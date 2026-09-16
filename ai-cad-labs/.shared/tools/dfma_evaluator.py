"""DFMA evaluator: bash-callable Design for Manufacturing / Assembly evaluation.

Self-contained evaluation unit: loads + filters rules from rules/*.json, reads the
8 render PNGs, builds an adversarial Critical-Think prompt, and makes an independent
LLM call through the `claude` CLI (schema-validated against DFMAEvaluation).

JSON contract: single machine-parseable object to STDOUT; human detail to STDERR.
Exit 0 = tool ran (even when the evaluated artifact fails checks, or a precondition
like missing renders is unmet; the JSON carries success/verdict). Exit 1 = tool
malfunction (unhandled crash; the JSON "error" carries the FULL traceback, error
messages are never truncated).

Evaluation authority (implemented 2026-07-13):
single-pass default · staleness reuse (ruleset-hash + mtime; --force overrides) ·
--mode=sweep parallel volley · probationary-rule governor (--include-probationary).

Modes:

    --mode=dfm --part-path <dir> [--dual-pass] [--force] [--include-probationary]
        DFM evaluation of <dir>/part.py renders. Default: ONE single-pass call over the
        full applicable rulebook. Reuses a fresh stamped dfma_report.json without any
        LLM call. --dual-pass = legacy two-call re-check:
        Pass 1: rules filtered by the manufacturing process parsed from constraints.md,
                manufacturing-technique framing.
        Pass 2: engineering-domain framing, runs ONLY if Pass 1 had no critical failure
                (active-tier, severity=critical, verdict=fail); sees Pass 1 findings.
        Merge: stricter verdict per rule wins. Writes <dir>/dfma_report.json (stamped
        with _meta.ruleset_hash for the staleness cache).

    --mode=sweep --project <dir> [--force] [--include-probationary]
        PARALLEL VOLLEY: every part's DFM + the assembly's DFA concurrently
        (CAD_EVALUATOR_CONCURRENCY, default 4). Fresh reports are reused at zero cost:
        the routine post-validation sweep approaches a no-op.
        Output: {success, part_path, manufacturing_process, rules_evaluated, rules_passed,
                 rules_failed, rules_uncertain, overall_verdict, pass2_skipped, failures[],
                 warnings[], proposed_rules_count, report_path}

    --mode=dfa --asm-path <dir>
        Single-pass DFA evaluation (global assembly rules, no process filtering, legacy
        parity). Writes <dir>/dfa_report.json. Output mirrors dfm (assembly_path key).

    --propose-rule '<json>' [--rule-type dfm|dfa]
        Append a rule to rules/<type>_rules.proposed.json, forced tier=probationary,
        counters reset. rule-type may instead be a "rule_type" key in the JSON payload.
        Output: {success, rule_id, tier, file, message}

    --judge-proposal --part-path <dir>
        Arithmetic DFM regression gate. The proposal side is always evaluated fresh;
        the stable side may reuse a fresh stamped dfma_report.json, else it too is
        evaluated fresh (score = sum of severity weights over failed rules:
        critical=10, major=5,
        minor=1). proposal_score <= stable_score -> PROMOTE (proposal replaces part.py);
        else REJECT (proposal deleted, stable + renders + report restored from backup).
        Output: {success, verdict, stable_score, proposal_score, regression_delta,
                 rule_diff: {new_failures, fixed_failures}, ...traceability}

Inner engine: evaluations run on **Claude via the
`claude` CLI** (headless `-p`, Read-only tools; Claude reads the render PNGs from disk
and returns schema-validated JSON; typing still enforced by DFMAEvaluation). Model:
env CAD_EVALUATOR_MODEL if set, else the CLI's configured default. Timeout: env
CAD_EVALUATOR_TIMEOUT_S (default 300). The legacy 8192-token output ceiling is GONE
in this path.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import contextlib
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path

from tools._dfma_models import DFMAEvaluation, DFMARuleResult

logger = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_RULES_DIR = _REPO_ROOT / "rules"

# Canonical manufacturing process IDs and their keyword aliases.
_PROCESS_KEYWORDS: dict[str, str] = {
    "cnc milling": "CNC_milling",
    "cnc machining": "CNC_milling",
    "milling": "CNC_milling",
    "cnc turning": "CNC_turning",
    "turning": "CNC_turning",
    "lathe": "CNC_turning",
    "injection molding": "injection_molding",
    "injection moulding": "injection_molding",
    "sheet metal": "sheet_metal",
    "stamping": "sheet_metal",
    "3d printing": "3D_printing",
    "fdm": "3D_printing",
    "sla": "3D_printing",
    "additive": "3D_printing",
    "casting": "casting",
    "sand casting": "casting",
    "die casting": "casting",
}


# ──────────────────────────────────────────────────────────────
# Rule loading / persistence
# ──────────────────────────────────────────────────────────────


def _atomic_write_json(path: Path, data: object) -> None:
    """Write JSON via tempfile + os.replace so rules files are never half-written."""
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise


_LIFECYCLE_LOG = "rule_lifecycle_log.json"


def _append_lifecycle_log(record: dict) -> None:
    """Append one rule-lifecycle decision to rules/rule_lifecycle_log.json (atomic).

    The append-only audit trail for promote / retire / triage decisions. Human review is
    DEFERRED (AI-triaged for now), not deleted; this is the record a human reads later to
    see what the AI decided and why, and reverses via git if needed.
    """
    log_path = _RULES_DIR / _LIFECYCLE_LOG
    existing: list = []
    if log_path.exists():
        try:
            loaded = json.loads(log_path.read_text())
            if isinstance(loaded, list):
                existing = loaded
        except (json.JSONDecodeError, OSError):
            existing = []
    record.setdefault("timestamp", datetime.now(tz=timezone.utc).isoformat())
    existing.append(record)
    _atomic_write_json(log_path, existing)


def _coerce_manufacturing(rule: dict) -> dict:
    """Fix the latent string-`manufacturing` bug (forensics 2026-07-13): a bare string
    would be CHAR-ITERATED by the filter below, silently killing the rule."""
    mfg = rule.get("manufacturing")
    if isinstance(mfg, str):
        rule["manufacturing"] = [mfg] if mfg.strip() else []
    return rule


def _canonical_process(token: str) -> str:
    """Map a free-text process token to a canonical process id (best-effort).

    Underscores→spaces + lowercase, then _PROCESS_KEYWORDS lookup; falls back to an
    already-canonical match; else returns the cleaned token unchanged (so scope is never
    silently dropped; the triage rationale flags un-mappable tokens).
    """
    cleaned = token.strip()
    if not cleaned:
        return ""
    key = cleaned.replace("_", " ").lower()
    if key in _PROCESS_KEYWORDS:
        return _PROCESS_KEYWORDS[key]
    for canon in set(_PROCESS_KEYWORDS.values()):
        if cleaned.lower() == canon.lower():
            return canon
    return cleaned


def _normalize_manufacturing(rule: dict) -> dict:
    """Repair the schema pollution in proposed rules IN PLACE; return the rule.

    Harness-born proposals carry manufacturing:[] but stash the real process in a
    non-standard key (manufacturing_process / manufacturing_processes) as a JSON-string,
    python-repr-string, comma-string, bare string, or boolean. Left unfixed, a promoted
    rule with manufacturing:[] becomes a GENERAL rule applied to EVERY part regardless of
    process. This coalesces every observed shape into one canonical list and drops the
    non-standard keys.
    """
    import ast

    candidates: list[str] = []

    def _harvest(value: object) -> None:
        if value is None or isinstance(value, bool):
            return
        if isinstance(value, list):
            candidates.extend(str(v) for v in value)
            return
        if isinstance(value, str):
            s = value.strip()
            if not s:
                return
            for parser in (json.loads, ast.literal_eval):
                try:
                    parsed = parser(s)
                except (ValueError, SyntaxError):
                    continue
                if isinstance(parsed, list):
                    candidates.extend(str(v) for v in parsed)
                    return
                if isinstance(parsed, str):
                    s = parsed
                    break
            candidates.extend(p.strip() for p in re.split(r"[,;]", s) if p.strip())

    _harvest(rule.get("manufacturing"))
    _harvest(rule.get("manufacturing_process"))
    _harvest(rule.get("manufacturing_processes"))

    seen: list[str] = []
    for tok in candidates:
        canon = _canonical_process(tok)
        if canon and canon not in seen:
            seen.append(canon)

    rule["manufacturing"] = seen
    rule.pop("manufacturing_process", None)
    rule.pop("manufacturing_processes", None)
    return rule


def _load_rules(
    rule_file: str,
    manufacturing_filter: str | None = None,
    include_probationary: bool = False,
) -> list[dict]:
    """Load rules from JSON, filtering by manufacturing process.

    GOVERNOR: probationary rules from the .proposed.json sibling are
    merged ONLY when include_probationary=True; routine evaluations run on the
    curated active set; the probationary audit is an explicit, batched event. This
    stops the self-inflation loop that doubled rules-per-call mid-run (forensics
    2026-07-13). Always excludes retired rules. When manufacturing_filter is set,
    returns rules matching that process PLUS general rules; when None, general only.
    """
    rules_path = _RULES_DIR / rule_file
    if not rules_path.exists():
        logger.warning(f"[dfma] Rules file not found: {rules_path}")
        return []

    all_rules = json.loads(rules_path.read_text())

    if include_probationary:
        proposed_path = _RULES_DIR / rule_file.replace(".json", ".proposed.json")
        if proposed_path.exists():
            try:
                all_rules.extend(json.loads(proposed_path.read_text()))
            except (json.JSONDecodeError, OSError):
                pass

    allowed_tiers = ("active", "probationary") if include_probationary else ("active",)
    rules = [_coerce_manufacturing(r) for r in all_rules if r.get("tier") in allowed_tiers]

    if manufacturing_filter:
        mfg_key = manufacturing_filter.strip()
        rules = [
            r
            for r in rules
            if not r.get("manufacturing")  # general rules always included
            or any(mfg_key == m for m in r.get("manufacturing", []))
        ]
    else:
        # No process specified — only general (process-agnostic) rules
        rules = [r for r in rules if not r.get("manufacturing")]

    return rules


def _update_rule_counters(rule_file: str, results: list[DFMARuleResult]) -> None:
    """Increment times_applied for each evaluated rule (atomic write).

    Checks both the seed file and its .proposed.json sibling, since evaluated
    probationary rules are merged in from the proposed file at load time.
    true_positives / false_positives are NOT auto-updated; they require
    external validation.
    """
    if not results:
        return

    evaluated_ids = {r.rule_id for r in results}

    for fname in (rule_file, rule_file.replace(".json", ".proposed.json")):
        rules_path = _RULES_DIR / fname
        if not rules_path.exists():
            continue
        try:
            existing = json.loads(rules_path.read_text())
        except (json.JSONDecodeError, OSError):
            continue

        updated = 0
        for rule in existing:
            if rule.get("id") in evaluated_ids:
                rule["times_applied"] = rule.get("times_applied", 0) + 1
                updated += 1

        if updated > 0:
            _atomic_write_json(rules_path, existing)
            logger.debug(f"[dfma] Updated times_applied for {updated} rules in {fname}")


def _auto_stage_proposed_rules(rule_file: str, proposed: list[dict]) -> None:
    """Auto-stage LLM-proposed rules into the .proposed.json sibling (atomic write).

    Keeps E2E-generated rules out of the curated seed file; they are merged back
    in at load time by _load_rules.
    """
    if not proposed:
        return

    rules_path = _RULES_DIR / rule_file.replace(".json", ".proposed.json")
    existing = []
    if rules_path.exists():
        existing = json.loads(rules_path.read_text())

    existing_ids = {r.get("id") for r in existing}

    staged = 0
    for rule in proposed:
        if rule.get("id") in existing_ids:
            continue

        rule["tier"] = "probationary"
        rule["confidence"] = 0.5
        rule.setdefault("times_applied", 0)
        rule.setdefault("true_positives", 0)
        rule.setdefault("false_positives", 0)
        rule.setdefault("manufacturing", [])
        rule["source"] = "Auto-proposed by DFMA evaluation LLM"

        existing.append(rule)
        existing_ids.add(rule.get("id"))
        staged += 1

    if staged > 0:
        _atomic_write_json(rules_path, existing)
        logger.info(f"[dfma] Auto-staged {staged} proposed rules for {rule_file}")


def _get_fix_hint(rule_id: str) -> str:
    """Look up the fix_hint for a rule by ID from the rules files."""
    for filename in ("dfm_rules.json", "dfa_rules.json"):
        rules_path = _RULES_DIR / filename
        if not rules_path.exists():
            continue
        rules = json.loads(rules_path.read_text())
        for r in rules:
            if r.get("id") == rule_id:
                return r.get("fix_hint", "")
    return ""


# ──────────────────────────────────────────────────────────────
# Parsing / grouping / prompt construction
# ──────────────────────────────────────────────────────────────


def _parse_manufacturing(text: str) -> str | None:
    """Extract manufacturing process from constraints.md content.

    Searches for a ## Manufacturing section and matches known process keywords.
    Returns the canonical process ID (e.g., 'CNC_milling') or None.
    """
    mfg_match = re.search(
        r"##\s*(?:Material\s*/\s*)?Manufacturing(.*?)(?=\n##|\Z)",
        text,
        re.IGNORECASE | re.DOTALL,
    )
    if not mfg_match:
        return None

    # Planner writes canonical tokens (e.g. "injection_molding") — normalize
    # underscores so they match the spaced keyword aliases.
    section = mfg_match.group(1).lower().replace("_", " ")

    for keyword, process_id in _PROCESS_KEYWORDS.items():
        if keyword in section:
            return process_id

    return None


def _group_rules(rules: list[dict], field: str) -> dict[str, list[dict]]:
    """Group rules by a field value (e.g., 'manufacturing' or 'category')."""
    groups: dict[str, list[dict]] = {}
    for rule in rules:
        values = rule.get(field, [])
        if isinstance(values, str):
            values = [values]
        if not values:
            values = ["general"]
        for v in values:
            groups.setdefault(v, []).append(rule)
    return groups


def _get_render_images(target_dir: Path) -> list[Path] | None:
    """Return PATHS of all individual render PNGs (skips collages). The Claude CLI
    Reads image files itself, so we pass paths, never bytes.

    No re-render fallback (deviation from legacy): rendering is a separate tool in
    the bash-first design; the caller must run `python -m tools.renderer` first.
    """
    renders_dir = target_dir / "renders"
    if not renders_dir.exists():
        return None
    png_files = sorted(
        p for p in renders_dir.glob("*.png") if "collage" not in p.name.lower()
    )
    if not png_files:
        return None
    return png_files


def _format_prior_findings(prior: DFMAEvaluation) -> str:
    """Summarize Pass 1's non-passing results for injection into the Pass 2 prompt."""
    lines = [
        f"- {r.rule_id} ({r.verdict}, {r.severity}): {r.observation}"
        for r in prior.results
        if r.verdict in ("fail", "uncertain")
    ]
    if not lines:
        return (
            "Pass 1 (manufacturing technique) found no failures. Do NOT anchor on its "
            "cleanliness — scrutinize independently with your own visual evidence."
        )
    return (
        "Pass 1 (manufacturing technique) produced these non-passing results. "
        "Re-examine each with your own visual evidence — corroborate or overturn — "
        "and actively look for issues Pass 1 missed:\n" + "\n".join(lines)
    )


def _build_eval_prompt(
    rules: list[dict],
    context_description: str,
    pass_label: str,
    prior_findings: str | None = None,
) -> str:
    """Construct the adversarial evaluation prompt for the inner LLM call.

    Uses adversarial-review framing: the LLM must look for what's WRONG,
    not confirm what's right. Each rule gets structured pass/fail criteria.
    """
    rules_block = ""
    for r in rules:
        tier_tag = " [PROBATIONARY — warning only]" if r["tier"] == "probationary" else ""
        fix_hint = r.get("fix_hint", "")
        hint_line = f"- **Fix hint (CadQuery)**: {fix_hint}\n" if fix_hint else ""
        rules_block += (
            f"\n### Rule {r['id']}{tier_tag}\n"
            f"- **Severity**: {r['severity']}\n"
            f"- **Description**: {r['description']}\n"
            f"- **Look for**: {r['look_for']}\n"
            f"- **PASS if**: {r['pass_criteria']}\n"
            f"- **FAIL if**: {r['fail_criteria']}\n"
            f"{hint_line}"
        )

    prior_block = f"\n### Pass 1 Findings\n{prior_findings}\n" if prior_findings else ""

    return f"""## DFMA Evaluation — {pass_label}

### Context
{context_description}

### Your Objective

Your objective is NOT to confirm the design looks right, but to ACTIVELY IDENTIFY
manufacturing and assembly defects. You are an adversarial reviewer — assume defects
exist until you have specific visual evidence proving otherwise.

For each rule below, you MUST:
1. State what you LOOKED FOR in the rendered images
2. State what you ACTUALLY SAW (specific visual observations from the rendered views)
3. Render a verdict: pass, fail, or uncertain
4. If fail or uncertain: state specifically what is wrong and how to fix it

Do NOT give a rule a "pass" verdict just because you cannot see a problem clearly.
If the images do not provide enough information to evaluate a rule, mark it "uncertain"
and explain what additional information would be needed.
{prior_block}
### Rules to Evaluate
{rules_block}

### Additional Instructions

After evaluating all rules above, if you notice ANY manufacturing or assembly concern
NOT covered by the existing rules, add it to the `proposed_rules` array as a new rule
suggestion. Use this JSON structure for each proposed rule:
{{
    "id": "PROPOSED-001",
    "category": "geometry | features | tolerances | access | ...",
    "manufacturing": ["process_id"],
    "description": "One-sentence description",
    "look_for": "What to visually inspect",
    "pass_criteria": "What passes",
    "fail_criteria": "What fails",
    "severity": "critical | major | minor"
}}

Set overall_verdict to:
- "pass" if all active rules pass
- "conditional_pass" if only probationary rules fail or active rules are uncertain
- "fail" if any active rule with severity critical or major fails
"""


# ──────────────────────────────────────────────────────────────
# Inner LLM call + merge
# ──────────────────────────────────────────────────────────────


def _resolve_model() -> str:
    """CAD_EVALUATOR_MODEL env override; empty string = the claude CLI's configured default."""
    return os.environ.get("CAD_EVALUATOR_MODEL", "").strip()


def _evaluator_timeout_s() -> int:
    """CAD_EVALUATOR_TIMEOUT_S env knob: per-call CLI timeout in seconds (default 300)."""
    try:
        return int(os.environ.get("CAD_EVALUATOR_TIMEOUT_S", "300"))
    except ValueError:
        return 300


def _invoke_claude_cli(full_prompt: str) -> str:
    """Run one evaluation through the `claude` CLI (headless, Read-only tools).

    Returns the model's result text. Raises RuntimeError with FULL stderr/stdout on
    any CLI failure; error messages are never truncated (systemic pattern #1).
    """
    cmd = [
        "claude", "-p", full_prompt,
        "--allowedTools", "Read",
        "--max-turns", "8",
        "--output-format", "json",
        "--permission-mode", "bypassPermissions",
    ]
    model = _resolve_model()
    if model:
        cmd.extend(["--model", model])
    proc = subprocess.run(
        cmd, cwd=str(_REPO_ROOT), capture_output=True, text=True,
        timeout=_evaluator_timeout_s(),
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"claude CLI exited {proc.returncode}.\nstdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"
        )
    try:
        envelope = json.loads(proc.stdout)
        # CLI emits either a single result object or a LIST of message objects
        # (observed live 2026-07-13) — find the result-bearing entry either way.
        if isinstance(envelope, list):
            result_text = next(
                (e.get("result", "") for e in reversed(envelope)
                 if isinstance(e, dict) and e.get("result")),
                "",
            )
        elif isinstance(envelope, dict):
            result_text = envelope.get("result", "")
        else:
            result_text = ""
    except json.JSONDecodeError:
        result_text = proc.stdout
    if not result_text:
        raise RuntimeError(f"claude CLI returned an empty result.\nstdout:\n{proc.stdout}")
    return result_text


def _extract_json(text: str) -> str:
    """Strip markdown fencing / surrounding prose; return the outermost JSON object."""
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError(f"No JSON object found in model output:\n{text}")
    return text[start : end + 1]


def _evaluator_concurrency() -> int:
    """CAD_EVALUATOR_CONCURRENCY env knob: sweep-mode concurrency cap (default 4, floor 1)."""
    try:
        return max(1, int(os.environ.get("CAD_EVALUATOR_CONCURRENCY", "4")))
    except ValueError:
        return 4


# ──────────────────────────────────────────────────────────────
# Evaluation authority: ruleset hashing + report staleness
# (one evaluation, reused by all callers)
# ──────────────────────────────────────────────────────────────

_RULE_IDENTITY_FIELDS = (
    "id", "tier", "severity", "manufacturing", "look_for", "pass_criteria", "fail_criteria"
)


def _rules_hash(rules: list[dict]) -> str:
    """Stable identity hash of the ruleset ACTUALLY used for an evaluation.

    Deliberately excludes volatile counters (times_applied, TP/FP); otherwise the
    counter update after every eval would invalidate every cache immediately.
    """
    identity = [
        {k: r.get(k) for k in _RULE_IDENTITY_FIELDS}
        for r in sorted(rules, key=lambda r: str(r.get("id")))
    ]
    return hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()[:16]


def _load_fresh_report(
    target_dir: Path, report_path: Path, expected_hash: str, code_filename: str
) -> dict | None:
    """Return the existing report dict iff it is FRESH, else None.

    Fresh = report exists, parses, carries a matching ruleset hash, and is newer
    than both the code file and every render PNG (geometry unchanged since eval).
    Re-evaluating unchanged geometry does not refresh truth; it injects variance
    (stochastic inner model); reuse INCREASES verdict consistency (§5 CAP note).
    """
    if not report_path.exists():
        return None
    try:
        data = json.loads(report_path.read_text())
    except (json.JSONDecodeError, OSError):
        return None
    meta = data.get("_meta") or {}
    if meta.get("ruleset_hash") != expected_hash:
        return None
    report_mtime = report_path.stat().st_mtime
    sources: list[float] = []
    code_path = target_dir / code_filename
    if code_path.exists():
        sources.append(code_path.stat().st_mtime)
    renders_dir = target_dir / "renders"
    if renders_dir.exists():
        sources.extend(p.stat().st_mtime for p in renders_dir.glob("*.png"))
    if not sources or report_mtime < max(sources):
        return None
    return data


def _write_stamped_report(report_path: Path, evaluation: DFMAEvaluation, ruleset_hash: str) -> None:
    """Persist the evaluation with the authority stamps the staleness cache keys on."""
    data = json.loads(evaluation.model_dump_json())
    data["_meta"] = {
        "ruleset_hash": ruleset_hash,
        "engine": "claude-cli",
        "evaluated_at": datetime.now(timezone.utc).isoformat(),
    }
    report_path.write_text(json.dumps(data, indent=2))


def _reused_failures_warnings(data: dict, *, dfm: bool) -> tuple[list[dict], list[dict]]:
    """Rebuild the result-dict failure/warning lists from a loaded report (shape parity
    with the fresh paths, incl. the probationary warn-only rule for DFM)."""
    results = data.get("results") or []
    failures = [
        {
            "rule_id": r.get("rule_id"),
            "severity": r.get("severity"),
            "description": r.get("rule_description"),
            "observation": r.get("observation"),
            "recommendation": r.get("recommendation"),
            **({"fix_hint": _get_fix_hint(str(r.get("rule_id")))} if dfm else {}),
        }
        for r in results
        if r.get("verdict") == "fail" and (not dfm or r.get("tier") != "probationary")
    ]
    warnings = [
        {"rule_id": r.get("rule_id"), "observation": r.get("observation")}
        for r in results
        if r.get("verdict") == "uncertain"
        or (dfm and r.get("verdict") == "fail" and r.get("tier") == "probationary")
    ]
    return failures, warnings


async def _run_eval_llm(
    prompt: str,
    image_paths: list[Path],
    *,
    pass_label: str,
    target_path: str,
    eval_type: str = "dfm",
    manufacturing_process: str = "",
) -> DFMAEvaluation | None:
    """Run the inner evaluation through the `claude` CLI.

    Claude Reads the render PNGs from disk and emits one JSON object; we validate it
    against DFMAEvaluation (typing preserved: generation moved, validation stayed).
    One retry with the validation error appended. Returns None on final failure
    (full error logged to stderr); callers merge around it.
    """
    schema = json.dumps(DFMAEvaluation.model_json_schema())
    paths_block = "\n".join(f"- {p}" for p in image_paths)
    base_prompt = (
        "You are a DFMA (Design for Manufacturing and Assembly) evaluation engine. "
        "You are adversarial — your job is to find problems, not confirm correctness.\n\n"
        f"{prompt}\n\n"
        "## Render images — Read EVERY file listed below before evaluating\n"
        f"{paths_block}\n\n"
        "## Output contract\n"
        "After reading all images, output ONLY one JSON object — no prose, no markdown "
        "fences — that validates against this JSON Schema:\n"
        f"{schema}"
    )

    last_error = ""
    for attempt in (1, 2):
        full_prompt = base_prompt if attempt == 1 else (
            base_prompt
            + "\n\n## Correction required\nYour previous output failed validation:\n"
            + last_error
            + "\nOutput ONLY the corrected JSON object."
        )
        try:
            raw = await asyncio.to_thread(_invoke_claude_cli, full_prompt)
            evaluation = DFMAEvaluation.model_validate_json(_extract_json(raw))

            evaluation.eval_type = eval_type
            evaluation.target_path = target_path
            evaluation.pass_label = pass_label
            evaluation.manufacturing_process = manufacturing_process

            logger.info(
                f"[dfma] {eval_type} eval ({pass_label}, attempt {attempt}) — "
                f"rules={evaluation.rules_evaluated}, passed={evaluation.rules_passed}, "
                f"failed={evaluation.rules_failed}, verdict={evaluation.overall_verdict}"
            )
            return evaluation
        except Exception as e:
            last_error = str(e)[:4000]
            logger.error(
                f"[dfma] Claude CLI eval failed for {pass_label} (attempt {attempt}):\n"
                f"{traceback.format_exc()}"
            )
    return None


def _merge_evaluations(
    pass1: DFMAEvaluation | None,
    pass2: DFMAEvaluation | None,
) -> DFMAEvaluation:
    """Merge results from dual-pass evaluation. Stricter verdict wins."""
    if pass1 is None and pass2 is None:
        return DFMAEvaluation(
            eval_type="dfm",
            target_path="",
            rules_evaluated=0,
            rules_passed=0,
            rules_failed=0,
            rules_uncertain=0,
            overall_verdict="fail",
            results=[],
        )

    if pass1 is None:
        return pass2  # type: ignore[return-value]
    if pass2 is None:
        return pass1

    verdict_rank = {"pass": 0, "uncertain": 1, "fail": 2}
    merged: dict[str, DFMARuleResult] = {}

    for r in pass1.results:
        merged[r.rule_id] = r
    for r in pass2.results:
        if r.rule_id not in merged or verdict_rank.get(
            r.verdict, 0
        ) > verdict_rank.get(merged[r.rule_id].verdict, 0):
            merged[r.rule_id] = r

    results = list(merged.values())
    passed = sum(1 for r in results if r.verdict == "pass")
    failed = sum(1 for r in results if r.verdict == "fail")
    uncertain = sum(1 for r in results if r.verdict == "uncertain")

    overall = _derive_verdict(results)  # hardening #2: deterministic, active-tier only

    proposed = list(pass1.proposed_rules) + list(pass2.proposed_rules)
    seen_descs: set[str] = set()
    unique_proposed = []
    for p in proposed:
        desc = p.get("description", "")
        if desc not in seen_descs:
            seen_descs.add(desc)
            unique_proposed.append(p)

    return DFMAEvaluation(
        eval_type=pass1.eval_type,
        target_path=pass1.target_path,
        manufacturing_process=pass1.manufacturing_process,
        pass_label="merged_dual_pass",
        rules_evaluated=len(results),
        rules_passed=passed,
        rules_failed=failed,
        rules_uncertain=uncertain,
        overall_verdict=overall,
        results=results,
        proposed_rules=unique_proposed,
    )


def _severity_score(rule_results: list[dict]) -> int:
    """Severity-weighted score: critical=10, major=5, minor=1.

    Prevents accepting proposals that trade minor failures for critical ones.
    """
    weights = {"critical": 10, "major": 5, "minor": 1}
    return sum(weights.get(r.get("severity", "minor"), 1) for r in rule_results)


def _derive_verdict(results: list) -> str:
    """Deterministic overall verdict over ACTIVE-tier results (probationary = warn-only).

    critical active fail -> "fail"; any other active fail OR active uncertain ->
    "conditional_pass"; else "pass". Deterministic derivation kills the fail/conditional_pass
    vocabulary stochasticity of the inner vision model (the same shape scored differently
    across runs). Minor active fails + active uncertains yield conditional_pass, never a
    silent pass on a flagged or unsure issue.
    """
    active = [r for r in results if getattr(r, "tier", "active") == "active"]
    if any(r.verdict == "fail" and r.severity == "critical" for r in active):
        return "fail"
    if any(r.verdict == "fail" or r.verdict == "uncertain" for r in active):
        return "conditional_pass"
    return "pass"


def _has_critical_failure(evaluation: DFMAEvaluation | None) -> bool:
    """Pass-2 gate: True when Pass 1 already found an active critical failure."""
    if evaluation is None:
        return False
    return any(
        r.verdict == "fail" and r.severity == "critical" and r.tier == "active"
        for r in evaluation.results
    )


# ──────────────────────────────────────────────────────────────
# Mode: dfm (dual-pass, gated)
# ──────────────────────────────────────────────────────────────


async def evaluate_dfm(
    part_dir: Path,
    part_path: str,
    *,
    dual_pass: bool = False,
    include_probationary: bool = False,
    force: bool = False,
) -> dict:
    """DFM evaluation of the part at part_dir (evaluation authority).

    Default = SINGLE-PASS over the full applicable rulebook (the Claude CLI engine
    has no output ceiling; dual_pass=True preserves the legacy two-call re-check).
    Staleness reuse: if a stamped dfma_report.json is newer than part.py + renders
    and carries the current ruleset hash, it is RETURNED WITHOUT an LLM call
    (force=True overrides). The gate inherits this automatically for the stable side.
    """
    logger.info(f"[dfma] Starting DFM evaluation for {part_path}")
    start = time.perf_counter()

    constraints_path = part_dir / "constraints.md"
    mfg_process = None
    if constraints_path.exists():
        mfg_process = _parse_manufacturing(constraints_path.read_text())
        logger.info(f"[dfma] Manufacturing process: {mfg_process or 'not specified'}")
    else:
        logger.warning(f"[dfma] No constraints.md found at {constraints_path}")

    rules = _load_rules(
        "dfm_rules.json",
        manufacturing_filter=mfg_process,
        include_probationary=include_probationary,
    )
    if not rules:
        msg = (
            "No applicable DFM rules found. "
            + (
                "No manufacturing process specified in constraints.md — "
                "add a '## Manufacturing' section with 'Primary process: CNC milling' "
                "(or another process) to enable process-specific DFM rules. "
                "Only general rules were checked but none exist."
                if mfg_process is None
                else f"No rules found for process '{mfg_process}'."
            )
        )
        return {"success": False, "part_path": part_path, "error": msg}

    logger.info(f"[dfma] Filtered to {len(rules)} applicable rules")

    ruleset_hash = _rules_hash(rules)
    report_path = part_dir / "dfma_report.json"
    if not force:
        cached = _load_fresh_report(part_dir, report_path, ruleset_hash, "part.py")
        if cached is not None:
            failures, warnings = _reused_failures_warnings(cached, dfm=True)
            logger.info(
                f"[dfma] REUSED fresh report for {part_path} "
                f"(ruleset {ruleset_hash}, zero LLM calls)"
            )
            return {
                "success": True,
                "reused": True,
                "part_path": part_path,
                "manufacturing_process": cached.get("manufacturing_process", mfg_process or ""),
                "rules_evaluated": cached.get("rules_evaluated"),
                "rules_passed": cached.get("rules_passed"),
                "rules_failed": cached.get("rules_failed"),
                "rules_uncertain": cached.get("rules_uncertain"),
                "overall_verdict": cached.get("overall_verdict"),
                "pass2_skipped": True,
                "failures": failures,
                "warnings": warnings,
                "proposed_rules_count": len(cached.get("proposed_rules") or []),
                "report_path": str(report_path),
            }

    image_paths = _get_render_images(part_dir)
    if image_paths is None:
        return {
            "success": False,
            "part_path": part_path,
            "error": (
                f"No render images available at {part_dir / 'renders'}. Render the part "
                "first: uv run python -m tools.renderer --mode=views --part-path "
                f"{part_path}"
            ),
        }

    context_desc = (
        f"Evaluating part at '{part_path}'. "
        f"Manufacturing process: {mfg_process or 'not specified (evaluating general rules)'}. "
        f"The 8 individual view images show: 4 perspectives (front, top, right, isometric) x "
        f"2 styles (wireframe with hidden lines, clean exterior only)."
    )

    if not dual_pass:
        # SINGLE-PASS default: one call, full applicable rulebook, both foci.
        # No output ceiling on the Claude CLI engine — front-load everything.
        sp_prompt = _build_eval_prompt(
            rules,
            context_desc
            + " Evaluate ALL rules in this ONE pass — both MANUFACTURING PROCESS "
            "constraints (can this part be made?) AND ENGINEERING DOMAIN constraints "
            "(geometry, features, tolerances, access).",
            f"Single Pass — Full Rulebook ({mfg_process or 'general'})",
        )
        pass1_result = await _run_eval_llm(
            sp_prompt,
            image_paths,
            pass_label="single_pass",
            target_path=part_path,
            eval_type="dfm",
            manufacturing_process=mfg_process or "",
        )
        pass2_result = None
        pass2_skipped = True  # accurate: no second pass exists on this path
    else:
        # Legacy dual-pass path, preserved as an explicit re-check tool (--dual-pass).
        pass1_prompt = _build_eval_prompt(
            rules,
            context_desc + " Focus on MANUFACTURING PROCESS constraints — can this part be made?",
            f"Pass 1 — Manufacturing Technique ({mfg_process or 'general'})",
        )
        pass1_result = await _run_eval_llm(
            pass1_prompt,
            image_paths,
            pass_label="manufacturing_technique",
            target_path=part_path,
            eval_type="dfm",
            manufacturing_process=mfg_process or "",
        )

        # Pass 2 — engineering domain; only if Pass 1 found no active critical failure.
        # (A critically failing part is going back for repair regardless — skip the
        # second LLM call. If Pass 1 itself errored, run Pass 2 anyway.)
        pass2_result = None
        pass2_skipped = False
        if _has_critical_failure(pass1_result):
            pass2_skipped = True
            logger.info("[dfma] Pass 2 skipped — Pass 1 found a critical failure")
        else:
            prior = _format_prior_findings(pass1_result) if pass1_result else None
            pass2_prompt = _build_eval_prompt(
                rules,
                context_desc
                + " Focus on ENGINEERING DOMAIN constraints — geometry, features, tolerances, access.",
                "Pass 2 — Engineering Domain",
                prior_findings=prior,
            )
            pass2_result = await _run_eval_llm(
                pass2_prompt,
                image_paths,
                pass_label="engineering_domain",
                target_path=part_path,
                eval_type="dfm",
                manufacturing_process=mfg_process or "",
            )

    if pass1_result is None and pass2_result is None:
        return {
            "success": False,
            "part_path": part_path,
            "error": (
                "DFM evaluation failed: every inner LLM call errored "
                f"(model={_resolve_model()}). See stderr for full tracebacks."
            ),
        }

    merged = _merge_evaluations(pass1_result, pass2_result)
    if not dual_pass:
        merged.pass_label = "single_pass"  # honest label; no second pass exists here
    # Deterministic verdict (hardening #2): single-pass short-circuits _merge_evaluations,
    # so overwrite here too — the stamped report + return then carry a verdict that is a
    # pure function of the active-tier severities, not the inner model's vocabulary.
    merged.overall_verdict = _derive_verdict(merged.results)

    _update_rule_counters("dfm_rules.json", merged.results)
    if merged.proposed_rules:
        _auto_stage_proposed_rules("dfm_rules.json", merged.proposed_rules)

    _write_stamped_report(report_path, merged, ruleset_hash)

    duration = time.perf_counter() - start
    logger.info(
        f"[dfma] DFM evaluation complete — {part_path}: verdict={merged.overall_verdict}, "
        f"rules={merged.rules_evaluated}, failed={merged.rules_failed}, "
        f"proposed={len(merged.proposed_rules)}, duration={duration:.1f}s"
    )

    return {
        "success": True,
        "part_path": part_path,
        "manufacturing_process": mfg_process or "unknown",
        "rules_evaluated": merged.rules_evaluated,
        "rules_passed": merged.rules_passed,
        "rules_failed": merged.rules_failed,
        "rules_uncertain": merged.rules_uncertain,
        "overall_verdict": merged.overall_verdict,
        "pass2_skipped": pass2_skipped,
        "failures": [
            {
                "rule_id": r.rule_id,
                "severity": r.severity,
                "description": r.rule_description,
                "observation": r.observation,
                "recommendation": r.recommendation,
                "fix_hint": _get_fix_hint(r.rule_id),
            }
            for r in merged.results
            # Probationary fails are warn-only — legacy
            # double-listed them here too, contradicting its own "warnings, not hard
            # failures" contract and letting unvetted rules sway the gate score
            if r.verdict == "fail" and r.tier != "probationary"
        ],
        "warnings": [
            {"rule_id": r.rule_id, "observation": r.observation}
            for r in merged.results
            if r.verdict == "uncertain"
            or (r.verdict == "fail" and r.tier == "probationary")
        ],
        "proposed_rules_count": len(merged.proposed_rules),
        "report_path": str(report_path),
    }


# ──────────────────────────────────────────────────────────────
# Mode: dfa (single pass — legacy parity)
# ──────────────────────────────────────────────────────────────


async def evaluate_dfa(
    asm_dir: Path,
    assembly_path: str,
    *,
    include_probationary: bool = False,
    force: bool = False,
) -> dict:
    """Single-pass DFA evaluation of the assembly at asm_dir (staleness-reusing)."""
    logger.info(f"[dfma] Starting DFA evaluation for {assembly_path}")
    start = time.perf_counter()

    rules = _load_rules("dfa_rules.json", include_probationary=include_probationary)
    if not rules:
        return {
            "success": False,
            "assembly_path": assembly_path,
            "error": f"No DFA rules found. Check {_RULES_DIR / 'dfa_rules.json'} exists.",
        }

    logger.info(f"[dfma] Loaded {len(rules)} DFA rules")

    ruleset_hash = _rules_hash(rules)
    report_path = asm_dir / "dfa_report.json"
    if not force:
        cached = _load_fresh_report(asm_dir, report_path, ruleset_hash, "assembly.py")
        if cached is not None:
            failures, warnings = _reused_failures_warnings(cached, dfm=False)
            logger.info(
                f"[dfma] REUSED fresh DFA report for {assembly_path} "
                f"(ruleset {ruleset_hash}, zero LLM calls)"
            )
            return {
                "success": True,
                "reused": True,
                "assembly_path": assembly_path,
                "rules_evaluated": cached.get("rules_evaluated"),
                "rules_passed": cached.get("rules_passed"),
                "rules_failed": cached.get("rules_failed"),
                "rules_uncertain": cached.get("rules_uncertain"),
                "overall_verdict": cached.get("overall_verdict"),
                "failures": failures,
                "warnings": warnings,
                "proposed_rules_count": len(cached.get("proposed_rules") or []),
                "report_path": str(report_path),
            }

    image_paths = _get_render_images(asm_dir)
    if image_paths is None:
        return {
            "success": False,
            "assembly_path": assembly_path,
            "error": (
                f"No assembly render images found at {asm_dir / 'renders'}. Render the "
                "assembly first: uv run python -m tools.renderer --mode=assembly "
                f"--project <project>"
            ),
        }

    context_desc = (
        f"Evaluating assembly at '{assembly_path}'. "
        f"The 8 individual view images show the assembled parts: 4 perspectives "
        f"(front, top, right, isometric) x 2 styles (wireframe, clean). "
        f"Focus on how parts fit together, fastener access, and assembly sequence."
    )

    prompt = _build_eval_prompt(rules, context_desc, "DFA — Design for Assembly Evaluation")

    evaluation = await _run_eval_llm(
        prompt,
        image_paths,
        pass_label="assembly_global",
        target_path=assembly_path,
        eval_type="dfa",
    )

    if evaluation is None:
        return {
            "success": False,
            "assembly_path": assembly_path,
            "error": (
                f"DFA evaluation LLM call failed (model={_resolve_model()}). "
                "See stderr for the full traceback."
            ),
        }

    evaluation.overall_verdict = _derive_verdict(evaluation.results)  # hardening #2: deterministic
    _update_rule_counters("dfa_rules.json", evaluation.results)
    if evaluation.proposed_rules:
        _auto_stage_proposed_rules("dfa_rules.json", evaluation.proposed_rules)

    _write_stamped_report(report_path, evaluation, ruleset_hash)

    duration = time.perf_counter() - start
    logger.info(
        f"[dfma] DFA evaluation complete — {assembly_path}: "
        f"verdict={evaluation.overall_verdict}, rules={evaluation.rules_evaluated}, "
        f"failed={evaluation.rules_failed}, duration={duration:.1f}s"
    )

    return {
        "success": True,
        "assembly_path": assembly_path,
        "rules_evaluated": evaluation.rules_evaluated,
        "rules_passed": evaluation.rules_passed,
        "rules_failed": evaluation.rules_failed,
        "rules_uncertain": evaluation.rules_uncertain,
        "overall_verdict": evaluation.overall_verdict,
        "failures": [
            {
                "rule_id": r.rule_id,
                "severity": r.severity,
                "description": r.rule_description,
                "observation": r.observation,
                "recommendation": r.recommendation,
            }
            for r in evaluation.results
            if r.verdict == "fail"
        ],
        "warnings": [
            {"rule_id": r.rule_id, "observation": r.observation}
            for r in evaluation.results
            if r.verdict == "uncertain"
        ],
        "proposed_rules_count": len(evaluation.proposed_rules),
        "report_path": str(report_path),
    }


# ──────────────────────────────────────────────────────────────
# Mode: propose-rule (synchronous, no LLM)
# ──────────────────────────────────────────────────────────────


def propose_rule(rule_type: str, rule_json: str) -> dict:
    """Append a proposed rule to rules/<type>_rules.proposed.json as probationary."""
    if rule_type not in ("dfm", "dfa"):
        return {"success": False, "error": "rule_type must be 'dfm' or 'dfa'"}

    try:
        rule = json.loads(rule_json)
    except json.JSONDecodeError as e:
        return {"success": False, "error": f"Invalid JSON: {e}"}

    if not isinstance(rule, dict):
        return {"success": False, "error": "Rule JSON must be an object"}

    required_fields = {"category", "description", "look_for", "pass_criteria", "fail_criteria", "severity"}
    missing = required_fields - set(rule.keys())
    if missing:
        return {"success": False, "error": f"Missing required fields: {missing}"}

    # Force probationary tier and reset counters
    rule["tier"] = "probationary"
    rule["confidence"] = 0.5
    rule["times_applied"] = 0
    rule["true_positives"] = 0
    rule["false_positives"] = 0

    if "id" not in rule or not rule["id"]:
        ts = datetime.now(tz=timezone.utc).strftime("%Y%m%d%H%M%S")
        prefix = "DFM" if rule_type == "dfm" else "DFA"
        rule["id"] = f"PROPOSED-{prefix}-{ts}"

    if rule_type == "dfm" and "manufacturing" not in rule:
        rule["manufacturing"] = []
    if rule_type == "dfa":
        rule["manufacturing"] = []

    rule["source"] = "LLM-proposed during DFMA evaluation"

    file_name = "dfm_rules.proposed.json" if rule_type == "dfm" else "dfa_rules.proposed.json"
    rules_path = _RULES_DIR / file_name

    existing = []
    if rules_path.exists():
        existing = json.loads(rules_path.read_text())

    existing.append(rule)
    _atomic_write_json(rules_path, existing)

    logger.info(f"[dfma] Proposed rule {rule['id']} added to {file_name} (probationary)")

    return {
        "success": True,
        "rule_id": rule["id"],
        "tier": "probationary",
        "file": file_name,
        "message": (
            f"Rule '{rule['id']}' added as probationary. "
            "It will generate warnings, not hard failures."
        ),
    }


# ──────────────────────────────────────────────────────────────
# Modes: promote-rule / retire-rule / triage-proposals
# (rule-lifecycle mechanism)
# ──────────────────────────────────────────────────────────────

# Evidence thresholds (times_applied). Moderate: evidence is inflated by the empty-
# manufacturing schema bug (argues higher) AND throttled by the probationary governor (argues
# lower). Only strongly-exercised, clean, novel rules auto-promote; the AI arbiter
# promotes strong-but-moderate-evidence rules on judgment.
PROMOTE_FLOOR = 10
KEEP_FLOOR = 3


def _rule_files(rule_type: str) -> tuple[str, str]:
    """(active_file, proposed_file) for a rule type."""
    prefix = "dfm" if rule_type == "dfm" else "dfa"
    return f"{prefix}_rules.json", f"{prefix}_rules.proposed.json"


def _read_rules_file(fname: str) -> list:
    """Load a rules JSON file as a list; [] if missing/corrupt."""
    path = _RULES_DIR / fname
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text())
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, OSError):
        return []


def _retire_in_place(rule: dict, reason: str) -> None:
    """Flip a rule to retired and prepend the bracketed RETIRED description marker (once)."""
    rule["tier"] = "retired"
    desc = str(rule.get("description", ""))
    if not desc.startswith("[RETIRED"):
        tag = f"[RETIRED — {reason}]" if reason else "[RETIRED]"
        rule["description"] = f"{tag} {desc}".strip()


def promote_rule(
    rule_id: str,
    rule_type: str | None = None,
    *,
    confidence: float | None = None,
    actor: str = "manual(--promote-rule)",
    rationale: str | None = None,
    criteria_hits: list | None = None,
) -> dict:
    """Promote a probationary proposed rule into the active rule set (moves proposed→active).

    Normalizes the manufacturing scope (else a manufacturing:[] rule becomes a GLOBAL rule),
    sets tier=active, bumps confidence to >=0.75, and logs the decision. Idempotent-safe:
    unknown id or already-active → structured error, no partial write. The tier flip changes
    the ruleset hash → stale stamped reports auto-recompute on next eval.
    """
    rule_types = [rule_type] if rule_type in ("dfm", "dfa") else ["dfm", "dfa"]
    for rt in rule_types:
        active_file, proposed_file = _rule_files(rt)
        proposed = _read_rules_file(proposed_file)
        idx = next((i for i, r in enumerate(proposed) if r.get("id") == rule_id), None)
        if idx is None:
            continue
        active = _read_rules_file(active_file)
        if any(r.get("id") == rule_id for r in active):
            return {"success": False, "error": f"Rule '{rule_id}' is already in {active_file}"}
        rule = proposed.pop(idx)
        conf_before = rule.get("confidence", 0.5)
        _normalize_manufacturing(rule)
        rule["tier"] = "active"
        conf_after = confidence if confidence is not None else max(float(conf_before or 0.5), 0.75)
        rule["confidence"] = conf_after
        active.append(rule)
        _atomic_write_json(_RULES_DIR / active_file, active)
        _atomic_write_json(_RULES_DIR / proposed_file, proposed)
        _append_lifecycle_log(
            {
                "rule_id": rule_id,
                "rule_type": rt,
                "decision": "promote",
                "from_tier": "probationary",
                "to_tier": "active",
                "rationale": rationale or f"Promoted to active; manufacturing normalized to {rule['manufacturing']}.",
                "criteria_hits": criteria_hits or ["manual"],
                "evidence": {
                    "times_applied": rule.get("times_applied", 0),
                    "confidence_before": conf_before,
                    "confidence_after": conf_after,
                },
                "actor": actor,
            }
        )
        return {
            "success": True,
            "rule_id": rule_id,
            "rule_type": rt,
            "tier": "active",
            "manufacturing": rule["manufacturing"],
            "confidence": conf_after,
            "active_file": active_file,
            "message": f"Rule '{rule_id}' promoted to active in {active_file}.",
        }
    return {"success": False, "error": f"Proposed rule '{rule_id}' not found in dfm/dfa proposed files"}


def retire_rule(
    rule_id: str,
    rule_type: str | None = None,
    *,
    reason: str = "",
    actor: str = "manual(--retire-rule)",
    rationale: str | None = None,
    criteria_hits: list | None = None,
) -> dict:
    """Retire a rule (proposed OR active) → tier=retired tombstone in the active file.

    A PROPOSED rule is MOVED proposed→active-file as retired (drains the pile, keeps a
    tombstone with full provenance). An ACTIVE rule is flipped in place. Logs the decision.
    Unknown id or already-retired → structured error.
    """
    rule_types = [rule_type] if rule_type in ("dfm", "dfa") else ["dfm", "dfa"]
    for rt in rule_types:
        active_file, proposed_file = _rule_files(rt)
        proposed = _read_rules_file(proposed_file)
        active = _read_rules_file(active_file)

        idx = next((i for i, r in enumerate(proposed) if r.get("id") == rule_id), None)
        if idx is not None:
            rule = proposed.pop(idx)
            from_tier = rule.get("tier", "probationary")
            _retire_in_place(rule, reason)
            active.append(rule)
            _atomic_write_json(_RULES_DIR / active_file, active)
            _atomic_write_json(_RULES_DIR / proposed_file, proposed)
            _append_lifecycle_log(
                {
                    "rule_id": rule_id, "rule_type": rt, "decision": "retire",
                    "from_tier": from_tier, "to_tier": "retired",
                    "rationale": rationale or f"Retired proposed rule. {reason}".strip(),
                    "criteria_hits": criteria_hits or ["manual"],
                    "evidence": {"times_applied": rule.get("times_applied", 0)},
                    "actor": actor,
                }
            )
            return {"success": True, "rule_id": rule_id, "rule_type": rt, "tier": "retired",
                    "moved_to": active_file, "message": f"Proposed rule '{rule_id}' retired (tombstoned in {active_file})."}

        aidx = next((i for i, r in enumerate(active) if r.get("id") == rule_id), None)
        if aidx is not None:
            rule = active[aidx]
            if rule.get("tier") == "retired":
                return {"success": False, "error": f"Rule '{rule_id}' is already retired"}
            from_tier = rule.get("tier", "active")
            _retire_in_place(rule, reason)
            _atomic_write_json(_RULES_DIR / active_file, active)
            _append_lifecycle_log(
                {
                    "rule_id": rule_id, "rule_type": rt, "decision": "retire",
                    "from_tier": from_tier, "to_tier": "retired",
                    "rationale": rationale or f"Retired active rule. {reason}".strip(),
                    "criteria_hits": criteria_hits or ["manual"],
                    "evidence": {"times_applied": rule.get("times_applied", 0)},
                    "actor": actor,
                }
            )
            return {"success": True, "rule_id": rule_id, "rule_type": rt, "tier": "retired",
                    "message": f"Active rule '{rule_id}' retired in place in {active_file}."}

    return {"success": False, "error": f"Rule '{rule_id}' not found in dfm/dfa files"}


def _keywords(rule: dict) -> set:
    """Content words (>=4 chars) from a rule's semantic fields, minus common stopwords."""
    text = " ".join(str(rule.get(k, "")) for k in ("description", "look_for", "fail_criteria")).lower()
    stop = {
        "that", "this", "with", "have", "which", "should", "must", "from", "when", "part",
        "parts", "rule", "any", "the", "and", "for", "are", "not", "without", "into", "than",
        "their", "there", "would", "will", "each", "other", "some", "such", "onto",
    }
    return set(re.findall(r"[a-z]{4,}", text)) - stop


def _find_duplicate(rule: dict, others: list) -> str | None:
    """Return the id of a near-duplicate (same category + Jaccard keyword overlap >= 0.6).

    Deliberately conservative: a high bar avoids false-positive retirements. Cross-domain
    conceptual overlaps (a DFM proposal echoing a DFA rule) are left to the AI arbiter.
    """
    cat = str(rule.get("category", "")).lower()
    kw = _keywords(rule)
    if not kw:
        return None
    for o in others:
        if str(o.get("category", "")).lower() != cat or o.get("id") == rule.get("id"):
            continue
        okw = _keywords(o)
        if not okw:
            continue
        if len(kw & okw) / len(kw | okw) >= 0.6:
            return o.get("id")
    return None


def _triage_recommendation(rule: dict, same_type_rules: list, rule_type: str) -> tuple[str, str, list]:
    """Deterministic per-proposal recommendation: (decision, rationale, criteria_hits).

    HARD quality gates first (quality beats evidence), then the evidence floor.
    decision ∈ {promote, retire, keep}.
    """
    rid = str(rule.get("id", ""))
    times = int(rule.get("times_applied", 0) or 0)
    category = str(rule.get("category", "")).lower()
    text = " ".join(
        str(rule.get(k, "")) for k in ("description", "look_for", "fail_criteria", "pass_criteria")
    ).lower()

    # Out of DFMA scope — usability / pure documentation (the render-vision evaluator
    # cannot assess "add a handle" or "show weld symbols").
    if category in ("usability", "clarity") or any(
        k in text for k in ("handle", "grip", "weld symbol", "joining method", "means of attachment")
    ):
        return ("retire", "Out of DFMA scope (usability/documentation — not a manufacturability "
                "check the render-vision evaluator can assess).", ["out_of_scope"])

    # Functional / design-intent rules (piston rings, counterweights) — valuable but a scope
    # question (do functional rules belong in a DFM rulebook?). Reserve for the arbiter.
    if category in ("functional", "function") or rid.startswith("PROPOSED-FUNC"):
        return ("keep", "Functional/design-intent rule (not manufacturability) — reserve for the "
                "human/AI scope decision on whether functional rules belong in the DFM rulebook.",
                ["functional_scope"])

    # Fillet-deferral policy.
    fillet = (
        any(k in text for k in ("fillet", "chamfer", "radius", "rounded"))
        or ("sharp" in text and "corner" in text)
    )
    escape = any(k in text for k in ("rib", "gusset", "reinforc", "clearance", "boss"))
    if fillet and not escape:
        return ("retire", "Fillet/chamfer/sharp-corner rule — conflicts with the standing "
                "fillet-deferral policy (mirrors the retired fillet rules); revisit if fillets "
                "are un-deferred.", ["fillet_policy"])
    if fillet and escape:
        return ("keep", "Fillet-adjacent, but the remedy is structural (rib/gusset/clearance) not "
                "a cosmetic fillet — reserve for AI adjudication.", ["fillet_adjacent"])

    # Near-duplicate of an existing rule in the same rulebook.
    dup = _find_duplicate(rule, same_type_rules)
    if dup:
        return ("retire", f"Duplicates existing {rule_type.upper()} rule {dup} "
                "(same category + high keyword overlap).", ["duplicate"])

    # Evidence floor → promote clean, novel, well-exercised rules.
    if times >= PROMOTE_FLOOR:
        return ("promote", f"Sound, novel, well-evidenced (times_applied={times} >= {PROMOTE_FLOOR}); "
                "no in-rulebook duplicate. (Pre-normalization evidence may be inflated by the "
                "empty-manufacturing bug; the arbiter may re-weight.)", ["evidence>=PROMOTE_FLOOR", "novel"])

    # Legacy-migrated generic proposal with negligible evidence → will never accrue.
    if re.match(r"^PROPOSED-\d+$", rid) and times < KEEP_FLOOR:
        return ("retire", f"Legacy-migrated proposal with negligible evidence "
                f"(times_applied={times}); not being generated, will never accrue.",
                ["legacy_low_evidence"])

    # Valid, non-conflicting, but under-evidenced → keep and re-triage.
    return ("keep", f"Valid, non-conflicting, but under-evidenced (times_applied={times} < "
            f"{PROMOTE_FLOOR}); keep probationary and re-triage as evidence accrues; candidate "
            "for AI-arbiter promotion on judgment.", ["under_evidenced"])


def triage_proposals(dry_run: bool = False) -> dict:
    """Recommend (and, unless dry_run, auto-apply the clear-cut) promote/retire decisions
    for every probationary proposal. KEEP-flagged proposals stay probationary for the AI
    arbiter. Every applied decision is logged to the audit trail. §5 Layer 2."""
    recommendations = []
    for rt in ("dfm", "dfa"):
        active_file, proposed_file = _rule_files(rt)
        proposed = _read_rules_file(proposed_file)
        same_type = _read_rules_file(active_file)  # active + retired live in this file
        for rule in proposed:
            decision, rationale, hits = _triage_recommendation(rule, same_type, rt)
            recommendations.append({
                "rule_id": rule.get("id"), "rule_type": rt, "decision": decision,
                "rationale": rationale, "criteria_hits": hits,
                "times_applied": int(rule.get("times_applied", 0) or 0),
                "severity": rule.get("severity"),
            })

    counts = {"promote": 0, "retire": 0, "keep": 0}
    for r in recommendations:
        counts[r["decision"]] += 1
    result = {"success": True, "dry_run": dry_run, "total": len(recommendations),
              "counts": counts, "recommendations": recommendations}
    if dry_run:
        return result

    applied: dict = {"promoted": [], "retired": [], "kept": [], "errors": []}
    for r in recommendations:
        rid, rt, hits = r["rule_id"], r["rule_type"], r["criteria_hits"]
        if r["decision"] == "promote":
            res = promote_rule(rid, rt, actor="triage-proposals(deterministic)",
                               rationale=r["rationale"], criteria_hits=hits)
            (applied["promoted"] if res.get("success") else applied["errors"]).append(
                rid if res.get("success") else res)
        elif r["decision"] == "retire":
            res = retire_rule(rid, rt, reason=f"triage: {hits[0]}", actor="triage-proposals(deterministic)",
                              rationale=r["rationale"], criteria_hits=hits)
            (applied["retired"] if res.get("success") else applied["errors"]).append(
                rid if res.get("success") else res)
        else:
            applied["kept"].append({"rule_id": rid, "rationale": r["rationale"]})

    _append_lifecycle_log({
        "decision": "triage_run", "actor": "triage-proposals(deterministic)", "dry_run": False,
        "promoted": applied["promoted"], "retired": applied["retired"],
        "kept": [k["rule_id"] for k in applied["kept"]],
    })
    result["applied"] = applied
    return result


# ──────────────────────────────────────────────────────────────
# Mode: judge-proposal (arithmetic DFM regression gate)
# ──────────────────────────────────────────────────────────────


def _regenerate_renders(part_dir: Path) -> tuple[bool, str]:
    """Re-render part.py via the renderer tool (spec §2 CLI contract).

    Returns (ok, detail). Subprocess so the gate has no import-level coupling to
    the renderer; tests monkeypatch this.
    """
    cmd = [sys.executable, "-m", "tools.renderer", "--mode=views", "--part-path", str(part_dir)]
    try:
        proc = subprocess.run(
            cmd, cwd=str(_REPO_ROOT), capture_output=True, text=True, timeout=600
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        return False, f"renderer invocation failed: {e}"
    if proc.returncode != 0:
        return False, (
            f"renderer exited {proc.returncode}.\nstdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"
        )
    return True, proc.stdout


def _restore_renders_backup(backup_dir: Path, renders_dir: Path) -> None:
    """Restore renders from backup directory after proposal rejection."""
    if not backup_dir.exists():
        return
    if renders_dir.exists():
        shutil.rmtree(str(renders_dir))
    shutil.copytree(str(backup_dir), str(renders_dir))
    shutil.rmtree(str(backup_dir))


def _failures_of(result: dict) -> list[dict]:
    """Extract {rule_id, severity} failure dicts from an evaluate_dfm result."""
    return [
        {"rule_id": f.get("rule_id", "unknown"), "severity": f.get("severity", "minor")}
        for f in result.get("failures", [])
    ]


async def judge_proposal(part_dir: Path, part_path: str) -> dict:
    """Compare part.proposal.py against stable part.py using DFM evaluations.

    The "DFMA as unit test" gate. The proposal side is always evaluated fresh
    (the code swap and re-render invalidate any cached report); the stable side
    may reuse a fresh stamped dfma_report.json via evaluate_dfm's staleness cache,
    else it is evaluated fresh. Either way the stable score comes from a real
    evaluation (deviation from legacy, per translation contract: legacy read the
    stable score from a cached dfma_report.json and scored an absent report as
    0 failures). Severity-weighted scoring; promote iff proposal_score <= stable_score. All file operations are
    backed by on-disk backups (part.py, renders/, dfma_report.json) so a crash or
    rejection restores the stable state exactly.
    """
    proposal_path = part_dir / "part.proposal.py"
    stable_path = part_dir / "part.py"

    if not proposal_path.exists():
        return {
            "success": False,
            "error": f"No proposal found at {proposal_path}",
        }

    if not stable_path.exists():
        shutil.move(str(proposal_path), str(stable_path))
        logger.info(f"[dfma] No stable version — proposal promoted directly for {part_path}")
        return {
            "success": True,
            "verdict": "promoted",
            "reason": "No existing stable version — proposal promoted directly",
            "stable_score": 0,
            "proposal_score": 0,
            "regression_delta": 0,
            "rule_diff": {"new_failures": [], "fixed_failures": []},
        }

    # 1. Evaluate the STABLE version fresh (renders should exist from the design loop)
    renders_dir = part_dir / "renders"
    if _get_render_images(part_dir) is None:
        ok, detail = _regenerate_renders(part_dir)
        if not ok:
            return {
                "success": False,
                "error": (
                    "Stable version has no renders and re-rendering failed — cannot "
                    f"judge proposal.\n{detail}"
                ),
            }

    stable_result = await evaluate_dfm(part_dir, part_path)
    if not stable_result.get("success"):
        return {
            "success": False,
            "error": (
                "Stable version could not be evaluated — cannot judge proposal: "
                f"{stable_result.get('error', 'unknown')}"
            ),
        }

    stable_rule_results = _failures_of(stable_result)
    stable_failing_rules = [r["rule_id"] for r in stable_rule_results]
    stable_score = _severity_score(stable_rule_results)

    # 2. On-disk backups BEFORE any file operations (crash-safe). The report backup
    #    keeps dfma_report.json consistent with part.py after a rejection.
    stable_backup_path = part_dir / "part.py.stable"
    renders_backup_dir = part_dir / "renders.stable"
    report_path = part_dir / "dfma_report.json"
    report_backup_path = part_dir / "dfma_report.json.stable"

    try:
        shutil.copy2(str(stable_path), str(stable_backup_path))
        if renders_dir.exists():
            if renders_backup_dir.exists():
                shutil.rmtree(str(renders_backup_dir))
            shutil.copytree(str(renders_dir), str(renders_backup_dir))
        if report_path.exists():
            shutil.copy2(str(report_path), str(report_backup_path))
    except OSError as e:
        logger.warning(f"[dfma] Backup failed for {part_path}: {e}. Proceeding without backup.")

    def _restore_stable() -> None:
        if stable_backup_path.exists():
            shutil.copy2(str(stable_backup_path), str(stable_path))
        _restore_renders_backup(renders_backup_dir, renders_dir)
        if report_backup_path.exists():
            shutil.copy2(str(report_backup_path), str(report_path))
        proposal_path.unlink(missing_ok=True)
        stable_backup_path.unlink(missing_ok=True)
        report_backup_path.unlink(missing_ok=True)

    def _discard_backups() -> None:
        stable_backup_path.unlink(missing_ok=True)
        report_backup_path.unlink(missing_ok=True)
        if renders_backup_dir.exists():
            shutil.rmtree(str(renders_backup_dir))

    proposal_code = proposal_path.read_text()

    # 3. Swap in the proposal, re-render, evaluate
    try:
        stable_path.write_text(proposal_code)

        if renders_dir.exists():
            for png in renders_dir.glob("*.png"):
                png.unlink()

        ok, detail = _regenerate_renders(part_dir)
        if not ok:
            _restore_stable()
            return {
                "success": False,
                "verdict": "rejected",
                "reason": f"Proposal could not be rendered — rejected.\n{detail}",
                "stable_score": stable_score,
            }

        proposal_result = await evaluate_dfm(part_dir, part_path)

        if not proposal_result.get("success"):
            _restore_stable()
            return {
                "success": False,
                "verdict": "rejected",
                "reason": (
                    f"Proposal could not be evaluated: {proposal_result.get('error', 'unknown')}"
                ),
                "stable_score": stable_score,
            }

        proposal_rule_results = _failures_of(proposal_result)
        proposal_failing_rules = [r["rule_id"] for r in proposal_rule_results]
        proposal_score = _severity_score(proposal_rule_results)

    except Exception:
        _restore_stable()
        err = traceback.format_exc()
        logger.error(f"[dfma] Proposal evaluation crashed for {part_path}:\n{err}")
        return {
            "success": False,
            "verdict": "rejected",
            "reason": f"Proposal evaluation crashed:\n{err}",
            "stable_score": stable_score,
        }

    # 4. Severity-weighted comparison
    new_failures = [r for r in proposal_failing_rules if r not in stable_failing_rules]
    fixed_failures = [r for r in stable_failing_rules if r not in proposal_failing_rules]
    regression_delta = proposal_score - stable_score
    rule_diff = {"new_failures": new_failures, "fixed_failures": fixed_failures}

    if proposal_score <= stable_score:
        # PROMOTE — part.py already contains the proposal code from the swap;
        # dfma_report.json + renders already describe the promoted version.
        proposal_path.unlink(missing_ok=True)
        _discard_backups()

        logger.info(
            f"[dfma] PROMOTED proposal for {part_path}: "
            f"score {stable_score}→{proposal_score} (delta={regression_delta}), "
            f"failures {len(stable_failing_rules)}→{len(proposal_failing_rules)}"
        )

        return {
            "success": True,
            "verdict": "promoted",
            "stable_score": stable_score,
            "proposal_score": proposal_score,
            "regression_delta": regression_delta,
            "rule_diff": rule_diff,
            "stable_failing_rules": stable_failing_rules,
            "proposal_failing_rules": proposal_failing_rules,
            "recommendation": (
                f"Proposal PROMOTED. Severity score: {stable_score}→{proposal_score}. "
                f"Failures: {len(stable_failing_rules)}→{len(proposal_failing_rules)}. "
                + (f"Fixed: {', '.join(fixed_failures)}. " if fixed_failures else "")
                + (f"New: {', '.join(new_failures)}. " if new_failures else "")
                + "Proceed to full validation."
            ),
        }

    # REJECT — restore stable part.py, renders, and report from backups
    _restore_stable()

    logger.warning(
        f"[dfma] REJECTED proposal for {part_path}: "
        f"score {stable_score}→{proposal_score} (+{regression_delta}), "
        f"new failures: {new_failures}"
    )

    new_failure_details = []
    for f in proposal_result.get("failures", []):
        if f.get("rule_id") in new_failures:
            hint = f.get("fix_hint", "")
            new_failure_details.append(
                f"{f['rule_id']} ({f.get('severity', 'unknown')}): {f.get('description', '')}. "
                f"Observation: {f.get('observation', '')[:100]}. "
                + (f"Fix hint: {hint}" if hint else "")
            )

    return {
        "success": True,
        "verdict": "rejected",
        "stable_score": stable_score,
        "proposal_score": proposal_score,
        "regression_delta": regression_delta,
        "rule_diff": rule_diff,
        "stable_failing_rules": stable_failing_rules,
        "proposal_failing_rules": proposal_failing_rules,
        "new_failure_details": new_failure_details,
        "recommendation": (
            f"Proposal REJECTED — severity score increased from {stable_score} to "
            f"{proposal_score} (+{regression_delta}). "
            f"Introduced {len(new_failures)} NEW failure(s): {', '.join(new_failures)}. "
            + (f"Fixed {len(fixed_failures)} failure(s): {', '.join(fixed_failures)}. " if fixed_failures else "")
            + "The repair approach worsened manufacturability. "
            "Try a DIFFERENT approach that preserves the base geometry and "
            "only modifies the specific features that are failing."
        ),
    }


# ──────────────────────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────────────────────


async def evaluate_sweep(
    project_dir: Path,
    *,
    include_probationary: bool = False,
    force: bool = False,
) -> dict:
    """PARALLEL VOLLEY: evaluate every part (DFM) + the assembly (DFA) concurrently.

    Concurrency capped by env CAD_EVALUATOR_CONCURRENCY (default 4). With staleness
    reuse on (default), parts whose stamped reports are fresh cost ZERO LLM calls;
    a routine sweep after per-part validation approaches a no-op; only stale or
    never-evaluated targets spend inner calls. One tool invocation replaces the
    inspector's serial per-part loop entirely.
    """
    start = time.perf_counter()
    assembly_dir = project_dir / "assembly"
    if not assembly_dir.is_dir():
        return {"success": False, "error": f"No assembly/ directory under {project_dir}"}

    part_dirs = sorted(
        d for d in assembly_dir.iterdir() if d.is_dir() and (d / "part.py").exists()
    )
    sem = asyncio.Semaphore(_evaluator_concurrency())

    async def _one_dfm(d: Path) -> tuple[str, dict]:
        async with sem:
            rel = str(d.relative_to(_REPO_ROOT)) if d.is_relative_to(_REPO_ROOT) else str(d)
            return d.name, await evaluate_dfm(
                d, rel, include_probationary=include_probationary, force=force
            )

    async def _one_dfa() -> dict | None:
        if _get_render_images(assembly_dir) is None:
            return None
        async with sem:
            rel = (
                str(assembly_dir.relative_to(_REPO_ROOT))
                if assembly_dir.is_relative_to(_REPO_ROOT)
                else str(assembly_dir)
            )
            return await evaluate_dfa(
                assembly_dir, rel, include_probationary=include_probationary, force=force
            )

    dfm_results, dfa_result = await asyncio.gather(
        asyncio.gather(*(_one_dfm(d) for d in part_dirs)), _one_dfa()
    )

    def _trim(r: dict) -> dict:
        return {
            "success": r.get("success"),
            "reused": bool(r.get("reused")),
            "overall_verdict": r.get("overall_verdict"),
            "rules_failed": r.get("rules_failed"),
            "failures": [f.get("rule_id") for f in (r.get("failures") or [])],
            "report_path": r.get("report_path"),
            **({"error": r.get("error")} if not r.get("success") else {}),
        }

    parts_out = {name: _trim(res) for name, res in dfm_results}
    duration = time.perf_counter() - start

    # Reuse observability (hardening #1): make reuse MACHINE-OBSERVABLE in the return —
    # the per-part REUSED lines log inside evaluate_dfm/dfa, but a grep-based count is
    # fragile across concurrent + multi-invocation logs. The summary line + these return
    # fields let callers measure reuse from the JSON, not `grep -c REUSED`.
    reused_parts = sum(1 for _, r in dfm_results if r.get("reused"))
    dfa_reused = "n/a" if dfa_result is None else ("reused" if dfa_result.get("reused") else "fresh")
    logger.info(
        f"[dfma] Sweep complete — {len(part_dirs)} parts + "
        f"{'DFA' if dfa_result else 'no DFA'} in {duration:.1f}s "
        f"(concurrency {_evaluator_concurrency()}, "
        f"reused {reused_parts}/{len(part_dirs)} parts, dfa {dfa_reused})"
    )
    return {
        "success": all(r.get("success") for _, r in dfm_results)
        and (dfa_result is None or dfa_result.get("success", False)),
        "mode": "sweep",
        "concurrency": _evaluator_concurrency(),
        "duration_s": round(duration, 1),
        "reused_parts": reused_parts,
        "total_parts": len(part_dirs),
        "dfa_reused": dfa_reused,
        "parts": parts_out,
        "dfa": _trim(dfa_result) if dfa_result else None,
    }


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m tools.dfma_evaluator",
        description=(
            "DFMA evaluation: dfm/dfa vision evaluation, rule proposal, and the "
            "proposal regression gate. Emits one JSON object to stdout; logs to stderr. "
            "Exit 0 = tool ran (JSON carries success/verdict); exit 1 = tool crash."
        ),
    )
    parser.add_argument(
        "--mode",
        choices=["dfm", "dfa", "sweep"],
        help="Evaluation mode: dfm (one part), dfa (assembly), or sweep "
        "(ALL parts + DFA as one parallel volley — the inspector's call).",
    )
    parser.add_argument(
        "--project",
        help="Project directory (contains assembly/). Used by --mode=sweep.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Bypass staleness reuse — evaluate fresh even if a stamped report is current.",
    )
    parser.add_argument(
        "--dual-pass",
        action="store_true",
        help="DFM only: legacy two-call re-check (P1 process + P2 engineering). "
        "Default is one single-pass call over the full applicable rulebook.",
    )
    parser.add_argument(
        "--include-probationary",
        action="store_true",
        help="Include auto-staged probationary rules from *.proposed.json (the batched "
        "probationary audit). Default: curated active rules only (inflation governor).",
    )
    parser.add_argument(
        "--part-path",
        help="Part directory (contains part.py, constraints.md, renders/). "
        "Used by --mode=dfm and --judge-proposal.",
    )
    parser.add_argument(
        "--asm-path",
        help="Assembly directory (contains renders/). Used by --mode=dfa.",
    )
    parser.add_argument(
        "--propose-rule",
        metavar="JSON",
        help="Propose a new rule (JSON object). Requires --rule-type, or a "
        "'rule_type' key inside the JSON.",
    )
    parser.add_argument(
        "--rule-type",
        choices=["dfm", "dfa"],
        help="Rule type for --propose-rule.",
    )
    parser.add_argument(
        "--judge-proposal",
        action="store_true",
        help="Run the DFM regression gate on <part-path>/part.proposal.py.",
    )
    parser.add_argument(
        "--promote-rule",
        metavar="RULE_ID",
        help="Promote a probationary proposed rule to active (moves it to *_rules.json, "
        "normalizes its manufacturing scope, bumps confidence). Optional --rule-type.",
    )
    parser.add_argument(
        "--retire-rule",
        metavar="RULE_ID",
        help="Retire a rule (proposed or active) to tier=retired. Optional --rule-type, --reason.",
    )
    parser.add_argument(
        "--reason",
        help="Retirement reason recorded in the rule description + audit trail (--retire-rule).",
    )
    parser.add_argument(
        "--triage-proposals",
        action="store_true",
        help="Recommend promote/retire/keep for every probationary proposal and auto-apply the "
        "clear-cut decisions (KEEP-flagged stay probationary). Use --dry-run to preview only.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="With --triage-proposals: print recommendations without mutating any rule file.",
    )
    return parser.parse_args(argv)


def _require_dir(raw: str | None, flag: str) -> tuple[Path | None, dict | None]:
    """Resolve a directory argument; structured error dict when missing/invalid."""
    if not raw:
        return None, {"success": False, "error": f"{flag} is required for this mode"}
    path = Path(raw)
    if not path.is_absolute():
        path = _REPO_ROOT / path
    if not path.is_dir():
        return None, {
            "success": False,
            "error": f"{flag} directory not found: {raw} (resolved to {path})",
        }
    return path, None


def _dispatch(args: argparse.Namespace) -> dict:
    actions = sum([
        args.mode is not None,
        args.propose_rule is not None,
        args.judge_proposal,
        args.promote_rule is not None,
        args.retire_rule is not None,
        args.triage_proposals,
    ])
    if actions == 0:
        return {
            "success": False,
            "error": "No action given. Use --mode=dfm|dfa, --propose-rule, --judge-proposal, "
            "--promote-rule, --retire-rule, or --triage-proposals (see --help).",
        }
    if actions > 1:
        return {
            "success": False,
            "error": "Give exactly one of --mode, --propose-rule, --judge-proposal, "
            "--promote-rule, --retire-rule, --triage-proposals.",
        }

    if args.promote_rule is not None:
        return promote_rule(args.promote_rule, args.rule_type)

    if args.retire_rule is not None:
        return retire_rule(args.retire_rule, args.rule_type, reason=args.reason or "")

    if args.triage_proposals:
        return triage_proposals(dry_run=args.dry_run)

    if args.propose_rule is not None:
        rule_type = args.rule_type
        if not rule_type:
            try:
                payload = json.loads(args.propose_rule)
                if isinstance(payload, dict):
                    rule_type = payload.get("rule_type") or payload.get("type")
            except json.JSONDecodeError:
                pass  # propose_rule() reports the JSON error with full detail
        if not rule_type:
            return {
                "success": False,
                "error": "Rule type missing: pass --rule-type dfm|dfa or include a 'rule_type' key in the JSON.",
            }
        return propose_rule(rule_type, args.propose_rule)

    if args.judge_proposal:
        part_dir, err = _require_dir(args.part_path, "--part-path")
        if err:
            return err
        return asyncio.run(judge_proposal(part_dir, args.part_path))

    if args.mode == "dfm":
        part_dir, err = _require_dir(args.part_path, "--part-path")
        if err:
            return err
        return asyncio.run(
            evaluate_dfm(
                part_dir,
                args.part_path,
                dual_pass=args.dual_pass,
                include_probationary=args.include_probationary,
                force=args.force,
            )
        )

    if args.mode == "sweep":
        project_dir, err = _require_dir(args.project, "--project")
        if err:
            return err
        return asyncio.run(
            evaluate_sweep(
                project_dir,
                include_probationary=args.include_probationary,
                force=args.force,
            )
        )

    # args.mode == "dfa"
    asm_dir, err = _require_dir(args.asm_path, "--asm-path")
    if err:
        return err
    return asyncio.run(
        evaluate_dfa(
            asm_dir,
            args.asm_path,
            include_probationary=args.include_probationary,
            force=args.force,
        )
    )


def main(argv: list[str] | None = None) -> int:
    """CLI entry point: dispatch per the mode flags in the module docstring."""
    args = _parse_args(argv)

    logging.basicConfig(
        stream=sys.stderr,
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    try:
        result = _dispatch(args)
    except Exception:
        print(json.dumps({"success": False, "error": traceback.format_exc()}, indent=2))
        return 1

    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
