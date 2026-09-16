"""Tests for tools.dfma_evaluator — rule loading/filtering, dual-pass gating, merge,
severity scoring, the proposal regression gate, rule staging, counter atomicity,
and the CLI JSON contract.

HERMETIC: the inner LLM call (_run_eval_llm) is monkeypatched with a scripted stub —
no live API, no .env. Renderer invocations (_regenerate_renders) are stubbed too.
Rules files live in tmp_path via a monkeypatched _RULES_DIR.
"""

import json
import shutil
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT))

from tools import dfma_evaluator as dfma  # noqa: E402
from tools._dfma_models import DFMAEvaluation, DFMARuleResult  # noqa: E402

STABLE_CODE = "# stable version\nresult = 1\n"
PROPOSAL_CODE = "# proposal version\nresult = 2\n"


# ──────────────────────────────────────────────────────────────
# Helpers / fixtures
# ──────────────────────────────────────────────────────────────


def _rule(rule_id, severity="minor", tier="active", manufacturing=None, **over):
    r = {
        "id": rule_id,
        "category": "geometry",
        "manufacturing": [] if manufacturing is None else manufacturing,
        "tier": tier,
        "description": f"desc {rule_id}",
        "look_for": "look",
        "pass_criteria": "pass crit",
        "fail_criteria": "fail crit",
        "severity": severity,
        "fix_hint": "",
        "source": "test",
        "confidence": 0.9,
        "times_applied": 0,
        "true_positives": 0,
        "false_positives": 0,
    }
    r.update(over)
    return r


def _result(rule_id, verdict="pass", severity="minor", tier="active", observation="obs"):
    return DFMARuleResult(
        rule_id=rule_id,
        rule_description=f"desc {rule_id}",
        verdict=verdict,
        severity=severity,
        tier=tier,
        observation=observation,
    )


def _make_eval(results=(), proposed=None):
    results = list(results)
    failed = sum(1 for r in results if r.verdict == "fail")
    uncertain = sum(1 for r in results if r.verdict == "uncertain")
    return DFMAEvaluation(
        eval_type="dfm",
        target_path="t",
        rules_evaluated=len(results),
        rules_passed=sum(1 for r in results if r.verdict == "pass"),
        rules_failed=failed,
        rules_uncertain=uncertain,
        overall_verdict="fail" if failed else ("conditional_pass" if uncertain else "pass"),
        results=results,
        proposed_rules=list(proposed or []),
    )


@pytest.fixture
def rules_dir(tmp_path, monkeypatch):
    rd = tmp_path / "rules"
    rd.mkdir()
    monkeypatch.setattr(dfma, "_RULES_DIR", rd)
    return rd


def _write_rules(rules_dir: Path, fname: str, rules: list) -> None:
    (rules_dir / fname).write_text(json.dumps(rules, indent=2))


def _seed_standard_rules(rules_dir: Path) -> None:
    _write_rules(
        rules_dir,
        "dfm_rules.json",
        [
            _rule("R-CNC", severity="critical", manufacturing=["CNC_milling"]),
            _rule("R-GEN", severity="minor"),
            _rule("R-SHEET", severity="major", manufacturing=["sheet_metal"]),
            _rule("R-RET", tier="retired", manufacturing=["CNC_milling"]),
        ],
    )
    _write_rules(rules_dir, "dfm_rules.proposed.json", [_rule("P-PROB", tier="probationary")])


def _make_part_dir(tmp_path: Path, mfg_line="- Primary process: CNC milling", n_renders=8) -> Path:
    part = tmp_path / "assembly" / "bracket"
    part.mkdir(parents=True)
    (part / "part.py").write_text(STABLE_CODE)
    if mfg_line is not None:
        (part / "constraints.md").write_text(f"# Constraints\n\n## Manufacturing\n{mfg_line}\n")
    renders = part / "renders"
    renders.mkdir()
    for i in range(n_renders):
        (renders / f"view_{i}.png").write_bytes(b"\x89PNG-fake-" + str(i).encode())
    return part


class LLMStub:
    """Scripted replacement for _run_eval_llm. script(pass_label, prompt) -> eval | None."""

    def __init__(self, monkeypatch, script):
        self.calls = []
        self.script = script

        async def fake(prompt, image_bytes_list, *, pass_label, target_path, eval_type="dfm", manufacturing_process=""):
            self.calls.append({"pass_label": pass_label, "prompt": prompt, "n_images": len(image_bytes_list)})
            ev = self.script(pass_label, prompt)
            if ev is None:
                return None
            ev = ev.model_copy(deep=True)
            ev.eval_type = eval_type
            ev.target_path = target_path
            ev.pass_label = pass_label
            ev.manufacturing_process = manufacturing_process
            return ev

        monkeypatch.setattr(dfma, "_run_eval_llm", fake)

    @property
    def labels(self):
        return [c["pass_label"] for c in self.calls]


# ──────────────────────────────────────────────────────────────
# Rule loading + process filtering
# ──────────────────────────────────────────────────────────────


def test_load_rules_filter_includes_process_and_general(rules_dir):
    _seed_standard_rules(rules_dir)
    # Governor default: curated active rules only — probationary excluded
    ids = {r["id"] for r in dfma._load_rules("dfm_rules.json", manufacturing_filter="CNC_milling")}
    assert ids == {"R-CNC", "R-GEN"}
    # Explicit probationary audit includes the staged rule
    ids = {
        r["id"]
        for r in dfma._load_rules(
            "dfm_rules.json", manufacturing_filter="CNC_milling", include_probationary=True
        )
    }
    assert ids == {"R-CNC", "R-GEN", "P-PROB"}


def test_load_rules_no_filter_returns_general_only(rules_dir):
    _seed_standard_rules(rules_dir)
    ids = {r["id"] for r in dfma._load_rules("dfm_rules.json", manufacturing_filter=None)}
    assert ids == {"R-GEN"}
    ids = {
        r["id"]
        for r in dfma._load_rules(
            "dfm_rules.json", manufacturing_filter=None, include_probationary=True
        )
    }
    assert ids == {"R-GEN", "P-PROB"}


def test_load_rules_excludes_retired(rules_dir):
    _seed_standard_rules(rules_dir)
    for filt in ("CNC_milling", None):
        assert "R-RET" not in {r["id"] for r in dfma._load_rules("dfm_rules.json", filt)}


def test_load_rules_merges_proposed_sibling_only_on_flag(rules_dir):
    """Governor: staged probationary rules join ONLY the explicit audit
    (include_probationary=True) — routine loads stay on the curated active set."""
    _write_rules(rules_dir, "dfm_rules.json", [_rule("R-GEN")])
    assert {r["id"] for r in dfma._load_rules("dfm_rules.json")} == {"R-GEN"}
    _write_rules(rules_dir, "dfm_rules.proposed.json", [_rule("P-NEW", tier="probationary")])
    assert {r["id"] for r in dfma._load_rules("dfm_rules.json")} == {"R-GEN"}
    assert {
        r["id"] for r in dfma._load_rules("dfm_rules.json", include_probationary=True)
    } == {"R-GEN", "P-NEW"}


def test_load_rules_missing_file_and_corrupt_proposed(rules_dir):
    assert dfma._load_rules("nonexistent.json") == []
    _write_rules(rules_dir, "dfm_rules.json", [_rule("R-GEN")])
    (rules_dir / "dfm_rules.proposed.json").write_text("{not json")
    assert {r["id"] for r in dfma._load_rules("dfm_rules.json")} == {"R-GEN"}


def test_load_rules_tolerates_real_production_files(tmp_path, monkeypatch):
    """The shipped rules/*.proposed.json contain a string-valued and a null 'manufacturing'
    (real E2E output). Loading must not crash; legacy-parity filter semantics apply."""
    rd = tmp_path / "rules"
    shutil.copytree(REPO_ROOT / "rules", rd)
    monkeypatch.setattr(dfma, "_RULES_DIR", rd)

    filtered = dfma._load_rules("dfm_rules.json", manufacturing_filter="CNC_milling")
    assert len(filtered) > 0
    assert all(r.get("tier") in ("active", "probationary") for r in filtered)
    for r in filtered:  # list-valued manufacturing respects the filter
        mfg = r.get("manufacturing")
        if isinstance(mfg, list) and mfg:
            assert "CNC_milling" in mfg

    dfa_rules = dfma._load_rules("dfa_rules.json")  # null-manufacturing rule → general
    assert len(dfa_rules) > 0


def test_parse_manufacturing():
    assert dfma._parse_manufacturing("## Manufacturing\n- Primary process: CNC milling\n") == "CNC_milling"
    assert dfma._parse_manufacturing("## Material / Manufacturing\nInjection molding, ABS\n") == "injection_molding"
    assert dfma._parse_manufacturing("## Manufacturing\nProcess: extrusion blow-forming\n") is None
    assert dfma._parse_manufacturing("## Dimensions\n10x10\n") is None
    # Canonical planner tokens (underscored) must parse too.
    assert dfma._parse_manufacturing("## Manufacturing\nProcess: CNC_milling\n") == "CNC_milling"
    assert dfma._parse_manufacturing("## Manufacturing\nProcess: injection_molding\n") == "injection_molding"
    assert dfma._parse_manufacturing("## Manufacturing\nProcess: sheet_metal\n") == "sheet_metal"
    assert dfma._parse_manufacturing("## Manufacturing\nProcess: 3D_printing\n") == "3D_printing"


# ──────────────────────────────────────────────────────────────
# Dual-pass trigger logic (evaluate_dfm with stubbed LLM)
# ──────────────────────────────────────────────────────────────


async def test_dfm_pass2_skipped_on_critical_p1_failure(tmp_path, rules_dir, monkeypatch):
    _seed_standard_rules(rules_dir)
    part = _make_part_dir(tmp_path)
    crit = _make_eval([_result("R-CNC", "fail", "critical")])
    stub = LLMStub(monkeypatch, lambda label, prompt: crit)

    out = await dfma.evaluate_dfm(part, "assembly/bracket", dual_pass=True)

    assert out["success"] is True
    assert stub.labels == ["manufacturing_technique"]  # exactly one LLM call
    assert out["pass2_skipped"] is True
    assert out["overall_verdict"] == "fail"
    assert [f["rule_id"] for f in out["failures"]] == ["R-CNC"]


async def test_dfm_pass2_runs_on_noncritical_failure_and_sees_p1_findings(tmp_path, rules_dir, monkeypatch):
    _seed_standard_rules(rules_dir)
    part = _make_part_dir(tmp_path)
    evals = {
        "manufacturing_technique": _make_eval(
            [_result("R-GEN", "fail", "minor", observation="thin wall seen")]
        ),
        "engineering_domain": _make_eval([_result("R-GEN", "pass")]),
    }
    stub = LLMStub(monkeypatch, lambda label, prompt: evals[label])

    out = await dfma.evaluate_dfm(part, "assembly/bracket", dual_pass=True)

    assert stub.labels == ["manufacturing_technique", "engineering_domain"]
    assert out["pass2_skipped"] is False
    p2_prompt = stub.calls[1]["prompt"]
    assert "Pass 1 Findings" in p2_prompt  # P2 sees P1 findings
    assert "R-GEN" in p2_prompt and "thin wall seen" in p2_prompt
    assert out["overall_verdict"] == "conditional_pass"  # merged: fail (stricter) wins, minor → conditional


async def test_dfm_pass2_runs_when_p1_clean_with_anchor_warning(tmp_path, rules_dir, monkeypatch):
    _seed_standard_rules(rules_dir)
    part = _make_part_dir(tmp_path)
    clean = _make_eval([_result("R-CNC", "pass"), _result("R-GEN", "pass")])
    stub = LLMStub(monkeypatch, lambda label, prompt: clean)

    out = await dfma.evaluate_dfm(part, "assembly/bracket", dual_pass=True)

    assert stub.labels == ["manufacturing_technique", "engineering_domain"]
    assert "found no failures" in stub.calls[1]["prompt"]
    assert out["overall_verdict"] == "pass"
    assert out["pass2_skipped"] is False


async def test_dfm_pass2_still_runs_if_p1_errored(tmp_path, rules_dir, monkeypatch):
    """One bad LLM call must not void the evaluation: P1 error → P2 runs, result = P2."""
    _seed_standard_rules(rules_dir)
    part = _make_part_dir(tmp_path)
    p2 = _make_eval([_result("R-GEN", "pass")])
    stub = LLMStub(monkeypatch, lambda label, prompt: None if label == "manufacturing_technique" else p2)

    out = await dfma.evaluate_dfm(part, "assembly/bracket", dual_pass=True)

    assert stub.labels == ["manufacturing_technique", "engineering_domain"]
    assert "Pass 1 Findings" not in stub.calls[1]["prompt"]  # no prior findings to inject
    assert out["success"] is True
    assert out["overall_verdict"] == "pass"


async def test_dfm_both_passes_errored_reports_failure(tmp_path, rules_dir, monkeypatch):
    _seed_standard_rules(rules_dir)
    part = _make_part_dir(tmp_path)
    LLMStub(monkeypatch, lambda label, prompt: None)

    out = await dfma.evaluate_dfm(part, "assembly/bracket")

    assert out["success"] is False
    assert "every inner LLM call errored" in out["error"]


async def test_dfm_process_filtering_reaches_prompt(tmp_path, rules_dir, monkeypatch):
    _seed_standard_rules(rules_dir)
    part = _make_part_dir(tmp_path)  # constraints: CNC milling
    clean = _make_eval([_result("R-CNC", "fail", "critical")])
    stub = LLMStub(monkeypatch, lambda label, prompt: clean)

    out = await dfma.evaluate_dfm(part, "assembly/bracket", include_probationary=True)

    assert out["manufacturing_process"] == "CNC_milling"
    p1_prompt = stub.calls[0]["prompt"]
    assert "R-CNC" in p1_prompt and "R-GEN" in p1_prompt
    assert "R-SHEET" not in p1_prompt and "R-RET" not in p1_prompt
    assert "P-PROB" in p1_prompt and "[PROBATIONARY — warning only]" in p1_prompt
    assert stub.calls[0]["n_images"] == 8  # all 8 render PNGs sent


async def test_dfm_no_renders_and_no_rules_precondition_errors(tmp_path, rules_dir, monkeypatch):
    LLMStub(monkeypatch, lambda label, prompt: pytest.fail("LLM must not be called"))

    # No applicable rules: process-specific seed only, constraints without ## Manufacturing
    _write_rules(rules_dir, "dfm_rules.json", [_rule("R-SHEET", manufacturing=["sheet_metal"])])
    part = _make_part_dir(tmp_path, mfg_line=None)
    (part / "constraints.md").write_text("# Constraints\n## Dimensions\n10x10\n")
    out = await dfma.evaluate_dfm(part, "assembly/bracket")
    assert out["success"] is False
    assert "## Manufacturing" in out["error"]

    # Renders missing (only a collage file, which is skipped)
    _seed_standard_rules(rules_dir)
    for png in (part / "renders").glob("*.png"):
        png.unlink()
    (part / "renders" / "collage_all.png").write_bytes(b"collage")
    out = await dfma.evaluate_dfm(part, "assembly/bracket")
    assert out["success"] is False
    assert "tools.renderer" in out["error"]


async def test_dfm_writes_report_and_increments_counters(tmp_path, rules_dir, monkeypatch):
    _seed_standard_rules(rules_dir)
    part = _make_part_dir(tmp_path)
    evaluation = _make_eval(
        [_result("R-CNC", "pass"), _result("P-PROB", "fail", "minor", tier="probationary")],
        proposed=[{"id": "PROPOSED-9", "description": "new concern", "category": "geometry",
                   "look_for": "l", "pass_criteria": "p", "fail_criteria": "f", "severity": "minor"}],
    )
    LLMStub(monkeypatch, lambda label, prompt: evaluation)

    out = await dfma.evaluate_dfm(part, "assembly/bracket")
    assert out["success"] is True

    # dfma_report.json written, honestly labeled for the single-pass default,
    # and stamped for the staleness cache
    report = json.loads((part / "dfma_report.json").read_text())
    assert report["pass_label"] == "single_pass"
    assert report["_meta"]["ruleset_hash"]
    assert report["_meta"]["engine"] == "claude-cli"
    assert out["report_path"] == str(part / "dfma_report.json")

    # times_applied incremented in BOTH seed and proposed files (once per part eval)
    seed = {r["id"]: r for r in json.loads((rules_dir / "dfm_rules.json").read_text())}
    prop = {r["id"]: r for r in json.loads((rules_dir / "dfm_rules.proposed.json").read_text())}
    assert seed["R-CNC"]["times_applied"] == 1
    assert prop["P-PROB"]["times_applied"] == 1
    assert seed["R-GEN"]["times_applied"] == 0  # not in results

    # LLM-proposed rule auto-staged as probationary
    assert prop["PROPOSED-9"]["tier"] == "probationary"

    # probationary failure surfaces as warning, not hard failure
    assert out["failures"] == []
    assert {w["rule_id"] for w in out["warnings"]} == {"P-PROB"}


# ──────────────────────────────────────────────────────────────
# Merge: stricter verdict wins
# ──────────────────────────────────────────────────────────────


def test_merge_stricter_verdict_wins_per_rule():
    cases = [  # (p1 verdict, p2 verdict, winner)
        ("pass", "fail", "fail"),
        ("fail", "pass", "fail"),  # order-independent: stricter kept, not last-write
        ("pass", "uncertain", "uncertain"),
        ("uncertain", "pass", "uncertain"),
        ("uncertain", "fail", "fail"),
        ("pass", "pass", "pass"),
    ]
    for v1, v2, want in cases:
        merged = dfma._merge_evaluations(
            _make_eval([_result("R1", v1)]), _make_eval([_result("R1", v2)])
        )
        assert merged.results[0].verdict == want, (v1, v2)
        assert merged.rules_evaluated == 1


def test_merge_union_counts_verdict_and_dedup():
    p1 = _make_eval(
        [_result("R1", "fail", "critical"), _result("R2", "pass")],
        proposed=[{"description": "A"}, {"description": "B"}],
    )
    p2 = _make_eval(
        [_result("R2", "uncertain"), _result("R3", "pass")],
        proposed=[{"description": "A"}, {"description": "C"}],
    )
    merged = dfma._merge_evaluations(p1, p2)

    assert merged.rules_evaluated == 3  # union of rule ids
    assert (merged.rules_passed, merged.rules_failed, merged.rules_uncertain) == (1, 1, 1)
    assert merged.overall_verdict == "fail"  # active critical failure
    assert merged.pass_label == "merged_dual_pass"
    assert [p["description"] for p in merged.proposed_rules] == ["A", "B", "C"]  # deduped


def test_merge_overall_verdict_tiers():
    # Hardening: a probationary-only failure is warn-only → excluded from the
    # active-tier verdict → pass (the finding still surfaces in warnings[]).
    m = dfma._merge_evaluations(
        _make_eval([_result("R1", "fail", "critical", tier="probationary")]),
        _make_eval([_result("R1", "fail", "critical", tier="probationary")]),
    )
    assert m.overall_verdict == "pass"
    # Deterministic rubric: only an active CRITICAL fail hard-fails; active minor AND active
    # major both surface as conditional_pass.
    m = dfma._merge_evaluations(
        _make_eval([_result("R1", "fail", "minor")]), _make_eval([_result("R1", "pass")])
    )
    assert m.overall_verdict == "conditional_pass"
    m = dfma._merge_evaluations(
        _make_eval([_result("R1", "fail", "major")]), _make_eval([_result("R1", "pass")])
    )
    assert m.overall_verdict == "conditional_pass"


def test_derive_verdict_branches():
    """Hardening #2: deterministic verdict over ACTIVE-tier results only."""
    dv = dfma._derive_verdict
    assert dv([_result("R", "fail", "critical")]) == "fail"
    assert dv([_result("R", "fail", "major")]) == "conditional_pass"
    assert dv([_result("R", "fail", "minor")]) == "conditional_pass"
    assert dv([_result("R", "uncertain", "minor")]) == "conditional_pass"
    assert dv([_result("R", "pass", "critical")]) == "pass"
    # Probationary results are excluded — a probationary critical fail → pass
    assert dv([_result("R", "fail", "critical", tier="probationary")]) == "pass"
    # an active critical fail dominates any other active results
    assert dv([_result("A", "fail", "critical"), _result("B", "fail", "minor")]) == "fail"


def test_merge_none_handling():
    p2 = _make_eval([_result("R1", "pass")])
    assert dfma._merge_evaluations(None, p2) is p2
    assert dfma._merge_evaluations(p2, None) is p2
    empty = dfma._merge_evaluations(None, None)
    assert empty.overall_verdict == "fail" and empty.rules_evaluated == 0


# ──────────────────────────────────────────────────────────────
# Severity score arithmetic
# ──────────────────────────────────────────────────────────────


def test_severity_score_arithmetic():
    assert dfma._severity_score([]) == 0
    assert dfma._severity_score(
        [{"severity": "critical"}, {"severity": "major"}, {"severity": "minor"}]
    ) == 16
    assert dfma._severity_score([{"severity": "bogus"}, {}]) == 2  # unknown/missing → minor=1
    assert dfma._severity_score([{"severity": "critical"}] * 3) == 30


# ──────────────────────────────────────────────────────────────
# Judge-proposal: the arithmetic DFM regression gate
# ──────────────────────────────────────────────────────────────


def _install_judge_stubs(monkeypatch, part: Path, stable_eval, proposal_eval):
    """Stub LLM (dispatch on part.py content — the gate swaps proposal code in before
    re-evaluating) and the renderer subprocess."""

    def script(label, prompt):
        current = (part / "part.py").read_text()
        return proposal_eval if current == PROPOSAL_CODE else stable_eval

    stub = LLMStub(monkeypatch, script)

    def fake_regen(part_dir):
        rd = part_dir / "renders"
        rd.mkdir(exist_ok=True)
        (rd / "proposal_view.png").write_bytes(b"proposal png")
        return True, "rendered"

    monkeypatch.setattr(dfma, "_regenerate_renders", fake_regen)
    return stub


async def test_judge_promotes_better_proposal_with_file_swap(tmp_path, rules_dir, monkeypatch):
    _seed_standard_rules(rules_dir)
    part = _make_part_dir(tmp_path)
    (part / "part.proposal.py").write_text(PROPOSAL_CODE)
    stable_eval = _make_eval([_result("R-CNC", "fail", "critical")])  # score 10, P2 skipped
    proposal_eval = _make_eval([_result("R-CNC", "pass")])  # score 0
    _install_judge_stubs(monkeypatch, part, stable_eval, proposal_eval)

    out = await dfma.judge_proposal(part, "assembly/bracket")

    assert out["success"] is True
    assert out["verdict"] == "promoted"
    assert (out["stable_score"], out["proposal_score"], out["regression_delta"]) == (10, 0, -10)
    assert out["rule_diff"] == {"new_failures": [], "fixed_failures": ["R-CNC"]}
    # file swap happened: proposal code now IS part.py, proposal file removed
    assert (part / "part.py").read_text() == PROPOSAL_CODE
    assert not (part / "part.proposal.py").exists()
    # backups discarded; renders describe the promoted version
    assert not (part / "part.py.stable").exists()
    assert not (part / "renders.stable").exists()
    assert not (part / "dfma_report.json.stable").exists()
    assert (part / "renders" / "proposal_view.png").exists()


async def test_judge_rejects_worse_proposal_and_restores_stable(tmp_path, rules_dir, monkeypatch):
    _seed_standard_rules(rules_dir)
    part = _make_part_dir(tmp_path, n_renders=2)
    (part / "part.proposal.py").write_text(PROPOSAL_CODE)
    stable_eval = _make_eval([_result("R-GEN", "fail", "minor")])  # score 1
    proposal_eval = _make_eval([_result("R-CNC", "fail", "critical")])  # score 10 → regression
    _install_judge_stubs(monkeypatch, part, stable_eval, proposal_eval)

    out = await dfma.judge_proposal(part, "assembly/bracket")

    assert out["success"] is True
    assert out["verdict"] == "rejected"
    assert (out["stable_score"], out["proposal_score"], out["regression_delta"]) == (1, 10, 9)
    assert out["rule_diff"] == {"new_failures": ["R-CNC"], "fixed_failures": ["R-GEN"]}
    # stable restored exactly: code, renders, report; proposal deleted
    assert (part / "part.py").read_text() == STABLE_CODE
    assert not (part / "part.proposal.py").exists()
    renders = {p.name for p in (part / "renders").glob("*.png")}
    assert renders == {"view_0.png", "view_1.png"}  # proposal_view.png gone
    report = json.loads((part / "dfma_report.json").read_text())
    assert {r["rule_id"] for r in report["results"]} == {"R-GEN"}  # stable's report, not proposal's
    # no backup artifacts left behind
    assert not (part / "part.py.stable").exists()
    assert not (part / "renders.stable").exists()
    assert not (part / "dfma_report.json.stable").exists()


async def test_judge_equal_score_promotes(tmp_path, rules_dir, monkeypatch):
    """Gate is proposal_score <= stable_score: a tie counts as no regression."""
    _seed_standard_rules(rules_dir)
    part = _make_part_dir(tmp_path)
    (part / "part.proposal.py").write_text(PROPOSAL_CODE)
    same = _make_eval([_result("R-GEN", "fail", "minor")])  # score 1 on both sides
    _install_judge_stubs(monkeypatch, part, same, same.model_copy(deep=True))

    out = await dfma.judge_proposal(part, "assembly/bracket")

    assert out["verdict"] == "promoted"
    assert out["regression_delta"] == 0
    assert (part / "part.py").read_text() == PROPOSAL_CODE
    assert not (part / "part.proposal.py").exists()


async def test_judge_no_stable_promotes_directly(tmp_path, rules_dir, monkeypatch):
    part = tmp_path / "part"
    part.mkdir()
    (part / "part.proposal.py").write_text(PROPOSAL_CODE)
    LLMStub(monkeypatch, lambda label, prompt: pytest.fail("no evaluation needed"))

    out = await dfma.judge_proposal(part, "part")

    assert out["verdict"] == "promoted"
    assert (part / "part.py").read_text() == PROPOSAL_CODE
    assert not (part / "part.proposal.py").exists()


async def test_judge_without_proposal_errors(tmp_path):
    part = tmp_path / "part"
    part.mkdir()
    (part / "part.py").write_text(STABLE_CODE)
    out = await dfma.judge_proposal(part, "part")
    assert out["success"] is False
    assert "No proposal" in out["error"]


async def test_judge_render_failure_rejects_and_restores(tmp_path, rules_dir, monkeypatch):
    _seed_standard_rules(rules_dir)
    part = _make_part_dir(tmp_path, n_renders=1)
    (part / "part.proposal.py").write_text(PROPOSAL_CODE)
    stable_eval = _make_eval([_result("R-GEN", "pass")])
    LLMStub(monkeypatch, lambda label, prompt: stable_eval)
    monkeypatch.setattr(dfma, "_regenerate_renders", lambda part_dir: (False, "cadquery exploded"))

    out = await dfma.judge_proposal(part, "assembly/bracket")

    assert out["success"] is False
    assert out["verdict"] == "rejected"
    assert "cadquery exploded" in out["reason"]  # renderer detail passed through untruncated
    assert (part / "part.py").read_text() == STABLE_CODE
    assert not (part / "part.proposal.py").exists()
    assert {p.name for p in (part / "renders").glob("*.png")} == {"view_0.png"}


# ──────────────────────────────────────────────────────────────
# Proposal staging (--propose-rule) + auto-stage helper
# ──────────────────────────────────────────────────────────────


def test_propose_rule_forces_probationary_and_is_loaded(rules_dir):
    _write_rules(rules_dir, "dfm_rules.json", [_rule("R-GEN")])
    payload = {
        "category": "features",
        "description": "needs fixturing surfaces",
        "look_for": "l",
        "pass_criteria": "p",
        "fail_criteria": "f",
        "severity": "minor",
        "tier": "active",  # must be overridden
        "times_applied": 99,  # must be reset
    }
    out = dfma.propose_rule("dfm", json.dumps(payload))

    assert out["success"] is True
    assert out["tier"] == "probationary"
    assert out["file"] == "dfm_rules.proposed.json"
    saved = json.loads((rules_dir / "dfm_rules.proposed.json").read_text())
    assert len(saved) == 1
    rule = saved[0]
    assert rule["tier"] == "probationary"
    assert rule["times_applied"] == 0 and rule["true_positives"] == 0 and rule["false_positives"] == 0
    assert rule["confidence"] == 0.5
    assert rule["id"].startswith("PROPOSED-DFM-")  # generated when missing
    assert rule["manufacturing"] == []  # defaulted for dfm

    # auto-stage capture: the proposed rule joins the PROBATIONARY AUDIT (flagged
    # load) — and, per the governor, NOT the routine curated load
    ids = {r["id"] for r in dfma._load_rules("dfm_rules.json", include_probationary=True)}
    assert rule["id"] in ids and "R-GEN" in ids
    assert rule["id"] not in {r["id"] for r in dfma._load_rules("dfm_rules.json")}


def test_propose_rule_validation_errors(rules_dir):
    out = dfma.propose_rule("dfm", "{not json")
    assert out["success"] is False and "Invalid JSON" in out["error"]

    out = dfma.propose_rule("dfm", json.dumps({"category": "x", "severity": "minor"}))
    assert out["success"] is False and "Missing required fields" in out["error"]

    out = dfma.propose_rule("nope", json.dumps({}))
    assert out["success"] is False and "rule_type" in out["error"]

    out = dfma.propose_rule("dfm", json.dumps(["a", "list"]))
    assert out["success"] is False and "must be an object" in out["error"]

    assert not (rules_dir / "dfm_rules.proposed.json").exists()  # nothing persisted


def test_auto_stage_proposed_rules_dedups_and_defaults(rules_dir):
    proposed = [{"id": "PROPOSED-1", "description": "d", "severity": "minor"}]
    dfma._auto_stage_proposed_rules("dfm_rules.json", list(proposed))
    dfma._auto_stage_proposed_rules("dfm_rules.json", list(proposed))  # same id again

    saved = json.loads((rules_dir / "dfm_rules.proposed.json").read_text())
    assert len(saved) == 1  # deduped by id
    assert saved[0]["tier"] == "probationary"
    assert saved[0]["confidence"] == 0.5
    assert saved[0]["manufacturing"] == []


# ──────────────────────────────────────────────────────────────
# Counter persistence + atomic writes
# ──────────────────────────────────────────────────────────────


def test_update_rule_counters_persists_across_seed_and_proposed(rules_dir):
    _write_rules(rules_dir, "dfm_rules.json", [_rule("R-A", times_applied=0), _rule("R-B", times_applied=5)])
    _write_rules(rules_dir, "dfm_rules.proposed.json", [_rule("P-A", tier="probationary", times_applied=3)])

    dfma._update_rule_counters("dfm_rules.json", [_result("R-A"), _result("P-A"), _result("R-MISSING")])

    # write-then-reload: both files remain valid JSON with incremented counters
    seed = {r["id"]: r["times_applied"] for r in json.loads((rules_dir / "dfm_rules.json").read_text())}
    prop = {r["id"]: r["times_applied"] for r in json.loads((rules_dir / "dfm_rules.proposed.json").read_text())}
    assert seed == {"R-A": 1, "R-B": 5}
    assert prop == {"P-A": 4}
    assert list(rules_dir.glob("*.tmp")) == []  # atomic write left no temp files

    dfma._update_rule_counters("dfm_rules.json", [])  # no-op path
    assert json.loads((rules_dir / "dfm_rules.json").read_text())  # still valid


def test_atomic_write_failure_leaves_original_intact(tmp_path):
    target = tmp_path / "rules.json"
    target.write_text('[{"id": "ORIGINAL"}]')

    with pytest.raises(TypeError):
        dfma._atomic_write_json(target, {"bad": object()})  # not JSON-serializable

    assert json.loads(target.read_text()) == [{"id": "ORIGINAL"}]  # never half-written
    assert list(tmp_path.glob("*.tmp")) == []  # temp file cleaned up


# ──────────────────────────────────────────────────────────────
# CLI JSON contract + model resolution
# ──────────────────────────────────────────────────────────────


def test_cli_json_contract_error_paths(rules_dir, capsys):
    """Exit 0 with a machine-parseable JSON error object — never a crash — for bad usage."""
    assert dfma.main([]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["success"] is False and "No action" in out["error"]

    assert dfma.main(["--mode=dfm"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["success"] is False and "--part-path" in out["error"]

    assert dfma.main(["--mode=dfm", "--part-path", "does/not/exist"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["success"] is False and "not found" in out["error"]

    assert dfma.main(["--mode=dfa", "--judge-proposal"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["success"] is False and "exactly one" in out["error"]

    assert dfma.main(["--propose-rule", "{}"]) == 0  # no --rule-type and no rule_type key
    out = json.loads(capsys.readouterr().out)
    assert out["success"] is False and "Rule type missing" in out["error"]


def test_cli_propose_rule_with_rule_type_in_payload(rules_dir, capsys):
    payload = {
        "rule_type": "dfa",
        "category": "access",
        "description": "fastener access",
        "look_for": "l",
        "pass_criteria": "p",
        "fail_criteria": "f",
        "severity": "major",
    }
    assert dfma.main(["--propose-rule", json.dumps(payload)]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["success"] is True
    assert out["file"] == "dfa_rules.proposed.json"
    saved = json.loads((rules_dir / "dfa_rules.proposed.json").read_text())
    assert saved[0]["tier"] == "probationary"
    assert saved[0]["manufacturing"] == []  # dfa rules are never process-scoped


def test_resolve_model_from_env(monkeypatch):
    # CAD_EVALUATOR_MODEL overrides; empty/unset = "" (claude CLI default)
    monkeypatch.setenv("CAD_EVALUATOR_MODEL", "claude-opus-5")
    assert dfma._resolve_model() == "claude-opus-5"
    monkeypatch.setenv("CAD_EVALUATOR_MODEL", "  ")
    assert dfma._resolve_model() == ""
    monkeypatch.delenv("CAD_EVALUATOR_MODEL")
    assert dfma._resolve_model() == ""

    monkeypatch.setenv("CAD_EVALUATOR_TIMEOUT_S", "45")
    assert dfma._evaluator_timeout_s() == 45
    monkeypatch.setenv("CAD_EVALUATOR_TIMEOUT_S", "not-a-number")
    assert dfma._evaluator_timeout_s() == 300


# ──────────────────────────────────────────────────────────────
# Evaluation authority: staleness reuse, ruleset hash, governor, sweep
# ──────────────────────────────────────────────────────────────


async def test_dfm_reuses_fresh_stamped_report(tmp_path, rules_dir, monkeypatch):
    _seed_standard_rules(rules_dir)
    part = _make_part_dir(tmp_path)
    ok = _make_eval([_result("R-CNC", "pass"), _result("R-GEN", "pass")])
    stub = LLMStub(monkeypatch, lambda label, prompt: ok)

    first = await dfma.evaluate_dfm(part, "assembly/bracket")
    assert first["success"] is True and not first.get("reused")
    assert stub.labels == ["single_pass"]

    # Second call: nothing changed → report reused, ZERO LLM calls
    LLMStub(monkeypatch, lambda label, prompt: pytest.fail("LLM must not be called on reuse"))
    second = await dfma.evaluate_dfm(part, "assembly/bracket")
    assert second["success"] is True and second["reused"] is True
    assert second["overall_verdict"] == first["overall_verdict"]
    assert second["rules_evaluated"] == first["rules_evaluated"]


async def test_dfm_stale_geometry_and_force_reevaluate(tmp_path, rules_dir, monkeypatch):
    import os as _os

    _seed_standard_rules(rules_dir)
    part = _make_part_dir(tmp_path)
    ok = _make_eval([_result("R-GEN", "pass")])
    LLMStub(monkeypatch, lambda label, prompt: ok)
    await dfma.evaluate_dfm(part, "assembly/bracket")

    # Touch part.py NEWER than the report → cache must miss
    future = (part / "dfma_report.json").stat().st_mtime + 5
    _os.utime(part / "part.py", (future, future))
    stub2 = LLMStub(monkeypatch, lambda label, prompt: ok)
    out = await dfma.evaluate_dfm(part, "assembly/bracket")
    assert not out.get("reused") and stub2.labels == ["single_pass"]

    # --force bypasses even a fresh report
    stub3 = LLMStub(monkeypatch, lambda label, prompt: ok)
    out = await dfma.evaluate_dfm(part, "assembly/bracket", force=True)
    assert not out.get("reused") and stub3.labels == ["single_pass"]


async def test_dfm_ruleset_change_invalidates_cache(tmp_path, rules_dir, monkeypatch):
    _seed_standard_rules(rules_dir)
    part = _make_part_dir(tmp_path)
    ok = _make_eval([_result("R-GEN", "pass")])
    LLMStub(monkeypatch, lambda label, prompt: ok)
    await dfma.evaluate_dfm(part, "assembly/bracket")

    # New ACTIVE rule lands → ruleset hash changes → re-evaluation required
    rules = json.loads((rules_dir / "dfm_rules.json").read_text())
    rules.append(_rule("R-NEW"))
    _write_rules(rules_dir, "dfm_rules.json", rules)
    stub = LLMStub(monkeypatch, lambda label, prompt: ok)
    out = await dfma.evaluate_dfm(part, "assembly/bracket")
    assert not out.get("reused") and stub.labels == ["single_pass"]


def test_coerce_string_manufacturing_rule_not_dead(rules_dir):
    """The forensics bug: a string 'manufacturing' was char-iterated and silently dead."""
    _write_rules(
        rules_dir,
        "dfm_rules.json",
        [dict(_rule("R-STR"), manufacturing="CNC_milling")],
    )
    ids = {r["id"] for r in dfma._load_rules("dfm_rules.json", manufacturing_filter="CNC_milling")}
    assert ids == {"R-STR"}


async def test_sweep_volley_evaluates_all_then_reuses(tmp_path, rules_dir, monkeypatch):
    _seed_standard_rules(rules_dir)
    proj = tmp_path
    # three parts + assembly renders
    part1 = _make_part_dir(proj)  # assembly/bracket
    for name in ("lid", "pin"):
        d = proj / "assembly" / name
        d.mkdir(parents=True)
        (d / "part.py").write_text(STABLE_CODE)
        (d / "constraints.md").write_text("# C\n\n## Manufacturing\n- Primary process: CNC milling\n")
        r = d / "renders"
        r.mkdir()
        for i in range(8):
            (r / f"v{i}.png").write_bytes(b"png" + str(i).encode())
    asm_renders = proj / "assembly" / "renders"
    asm_renders.mkdir()
    for i in range(8):
        (asm_renders / f"a{i}.png").write_bytes(b"apng" + str(i).encode())
    _write_rules(rules_dir, "dfa_rules.json", [_rule("A-GEN")])

    ok = _make_eval([_result("R-GEN", "pass")])
    stub = LLMStub(monkeypatch, lambda label, prompt: ok)
    out = await dfma.evaluate_sweep(proj)

    assert out["success"] is True and out["mode"] == "sweep"
    assert set(out["parts"]) == {"bracket", "lid", "pin"}
    assert out["dfa"] is not None
    assert len(stub.labels) == 4  # 3 DFM + 1 DFA, all evaluated

    # Volley #2: everything fresh → full reuse, zero LLM calls
    LLMStub(monkeypatch, lambda label, prompt: pytest.fail("LLM must not be called on reuse"))
    out2 = await dfma.evaluate_sweep(proj)
    assert out2["success"] is True
    assert all(p["reused"] for p in out2["parts"].values())
    assert out2["dfa"]["reused"] is True


# ──────────────────────────────────────────────────────────────
# Rule-lifecycle: manufacturing normalization
# ──────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "key,val,expected",
    [
        ("manufacturing", ["CNC_milling"], ["CNC_milling"]),          # already a list
        ("manufacturing", "CNC_milling", ["CNC_milling"]),            # bare string (legacy)
        ("manufacturing", [], []),                                    # empty
        ("manufacturing_process", "3D_printing", ["3D_printing"]),    # non-standard key
        ("manufacturing_processes", '["3D_printing", "injection_molding", "CNC_machining"]',
         ["3D_printing", "injection_molding", "CNC_milling"]),        # JSON string-list + alias
        ("manufacturing_processes", "3D_printing, injection_molding, CNC",
         ["3D_printing", "injection_molding", "CNC"]),                # comma string
        ("manufacturing_processes", "['CNC_milling', 'casting', 'forging']",
         ["CNC_milling", "casting", "forging"]),                      # python-repr string
        ("manufacturing_processes", True, []),                        # boolean garbage
    ],
)
def test_normalize_manufacturing_shapes(key, val, expected):
    rule = {"id": "X", "manufacturing": []}
    rule[key] = val
    out = dfma._normalize_manufacturing(rule)
    assert out["manufacturing"] == expected
    assert "manufacturing_process" not in out and "manufacturing_processes" not in out


# ──────────────────────────────────────────────────────────────
# Rule-lifecycle: promote / retire primitives + audit trail
# ──────────────────────────────────────────────────────────────


def test_promote_rule_moves_normalizes_and_logs(rules_dir):
    _write_rules(rules_dir, "dfm_rules.json", [_rule("R-GEN")])
    prop = _rule("PROPOSED-3DP-X", tier="probationary", confidence=0.5, times_applied=15)
    del prop["manufacturing"]  # simulate the polluted shape: process in a non-standard key
    prop["manufacturing_process"] = "3D_printing"
    _write_rules(rules_dir, "dfm_rules.proposed.json", [prop])

    out = dfma.promote_rule("PROPOSED-3DP-X", "dfm")
    assert out["success"] is True and out["tier"] == "active"
    assert out["manufacturing"] == ["3D_printing"] and out["confidence"] >= 0.75

    active = {r["id"]: r for r in json.loads((rules_dir / "dfm_rules.json").read_text())}
    proposed = json.loads((rules_dir / "dfm_rules.proposed.json").read_text())
    assert active["PROPOSED-3DP-X"]["tier"] == "active"
    assert active["PROPOSED-3DP-X"]["manufacturing"] == ["3D_printing"]
    assert "manufacturing_process" not in active["PROPOSED-3DP-X"]
    assert all(r["id"] != "PROPOSED-3DP-X" for r in proposed)  # single copy: gone from proposed

    log = json.loads((rules_dir / "rule_lifecycle_log.json").read_text())
    rec = next(e for e in log if e["rule_id"] == "PROPOSED-3DP-X")
    assert rec["decision"] == "promote" and rec["to_tier"] == "active" and rec["timestamp"]


def test_promote_rule_unknown_id_errors_no_write(rules_dir):
    _write_rules(rules_dir, "dfm_rules.json", [_rule("R-ACTIVE")])
    _write_rules(rules_dir, "dfm_rules.proposed.json", [_rule("P-X", tier="probationary")])
    assert dfma.promote_rule("NOPE")["success"] is False
    # active id (not in proposed) can't be promoted
    assert dfma.promote_rule("R-ACTIVE", "dfm")["success"] is False
    assert {r["id"] for r in json.loads((rules_dir / "dfm_rules.json").read_text())} == {"R-ACTIVE"}
    assert {r["id"] for r in json.loads((rules_dir / "dfm_rules.proposed.json").read_text())} == {"P-X"}


def test_retire_proposed_rule_tombstones_and_drains(rules_dir):
    _write_rules(rules_dir, "dfm_rules.json", [_rule("R-GEN")])
    _write_rules(
        rules_dir, "dfm_rules.proposed.json",
        [_rule("P-FILLET", tier="probationary", description="Sharp corners need fillets")],
    )
    out = dfma.retire_rule("P-FILLET", "dfm", reason="fillet policy")
    assert out["success"] is True and out["tier"] == "retired"

    active = {r["id"]: r for r in json.loads((rules_dir / "dfm_rules.json").read_text())}
    assert active["P-FILLET"]["tier"] == "retired"
    assert active["P-FILLET"]["description"].startswith("[RETIRED — fillet policy]")
    assert json.loads((rules_dir / "dfm_rules.proposed.json").read_text()) == []  # drained
    log = json.loads((rules_dir / "rule_lifecycle_log.json").read_text())
    assert any(e["rule_id"] == "P-FILLET" and e["decision"] == "retire" for e in log)


def test_retire_active_rule_in_place_and_idempotent(rules_dir):
    _write_rules(rules_dir, "dfm_rules.json", [_rule("R-OLD"), _rule("R-KEEP")])
    assert dfma.retire_rule("R-OLD", "dfm", reason="obsolete")["success"] is True
    active = {r["id"]: r for r in json.loads((rules_dir / "dfm_rules.json").read_text())}
    assert active["R-OLD"]["tier"] == "retired" and active["R-KEEP"]["tier"] == "active"
    assert dfma.retire_rule("R-OLD", "dfm")["success"] is False  # already retired


# ──────────────────────────────────────────────────────────────
# Rule-lifecycle: triage-proposals recommender + executor
# ──────────────────────────────────────────────────────────────


def _seed_triage_fixture(rules_dir):
    _write_rules(
        rules_dir, "dfm_rules.json",
        [_rule("DFM-ACTIVE", severity="critical", manufacturing=["CNC_milling"])],
    )
    _write_rules(
        rules_dir, "dfm_rules.proposed.json",
        [
            _rule("PROPOSED-3DP-CLEAN", tier="probationary", times_applied=15,
                  description="Horizontal holes should be teardrop to avoid sagging",
                  look_for="horizontal circular holes", fail_criteria="round horizontal holes sag"),
            _rule("PROPOSED-FILL", tier="probationary", times_applied=12,
                  description="Sharp internal corners should be filleted",
                  look_for="sharp 90-degree corners", fail_criteria="sharp internal corner no fillet"),
            _rule("PROPOSED-FUNC-Z", tier="probationary", times_applied=8, category="features",
                  description="Pistons need ring grooves for sealing"),
            _rule("PROPOSED-LOWEV", tier="probationary", times_applied=1,
                  description="novel clean turning symmetry constraint",
                  look_for="asymmetric turned features", fail_criteria="non symmetric turned feature"),
            _rule("PROPOSED-1", tier="probationary", times_applied=0,
                  description="legacy generic vague concept", look_for="whatever", fail_criteria="stuff"),
        ],
    )
    _write_rules(rules_dir, "dfa_rules.json", [_rule("DFA-ACTIVE")])
    _write_rules(rules_dir, "dfa_rules.proposed.json", [])


def test_triage_dry_run_recommends_without_mutation(rules_dir):
    _seed_triage_fixture(rules_dir)
    before = (rules_dir / "dfm_rules.proposed.json").read_text()

    out = dfma.triage_proposals(dry_run=True)
    assert out["success"] is True and out["dry_run"] is True
    assert out["counts"] == {"promote": 1, "retire": 2, "keep": 2}
    recs = {r["rule_id"]: r["decision"] for r in out["recommendations"]}
    assert recs == {
        "PROPOSED-3DP-CLEAN": "promote",
        "PROPOSED-FILL": "retire",
        "PROPOSED-FUNC-Z": "keep",
        "PROPOSED-LOWEV": "keep",
        "PROPOSED-1": "retire",
    }
    assert (rules_dir / "dfm_rules.proposed.json").read_text() == before  # nothing mutated
    assert not (rules_dir / "rule_lifecycle_log.json").exists()


def test_triage_execute_applies_clear_cases_and_keeps_the_rest(rules_dir):
    _seed_triage_fixture(rules_dir)
    out = dfma.triage_proposals(dry_run=False)
    assert out["success"] is True and out["dry_run"] is False
    assert set(out["applied"]["promoted"]) == {"PROPOSED-3DP-CLEAN"}
    assert set(out["applied"]["retired"]) == {"PROPOSED-FILL", "PROPOSED-1"}
    assert {k["rule_id"] for k in out["applied"]["kept"]} == {"PROPOSED-FUNC-Z", "PROPOSED-LOWEV"}
    assert out["applied"]["errors"] == []

    remaining = {r["id"] for r in json.loads((rules_dir / "dfm_rules.proposed.json").read_text())}
    assert remaining == {"PROPOSED-FUNC-Z", "PROPOSED-LOWEV"}  # only kept ones remain

    active = {r["id"]: r for r in json.loads((rules_dir / "dfm_rules.json").read_text())}
    assert active["PROPOSED-3DP-CLEAN"]["tier"] == "active"
    assert active["PROPOSED-FILL"]["tier"] == "retired"
    assert active["PROPOSED-1"]["tier"] == "retired"

    log = json.loads((rules_dir / "rule_lifecycle_log.json").read_text())
    assert any(e.get("decision") == "triage_run" for e in log)
    assert any(e.get("rule_id") == "PROPOSED-3DP-CLEAN" and e["decision"] == "promote" for e in log)


# ──────────────────────────────────────────────────────────────
# Hardening #1: reuse observability
# ──────────────────────────────────────────────────────────────


async def test_sweep_reuse_observability(tmp_path, rules_dir, monkeypatch, caplog):
    """Per-part REUSED line fires ONCE per reused part; the sweep summary + return carry
    reuse counts and DFA reuse status (machine-observable, not grep-only)."""
    import logging as _logging

    _seed_standard_rules(rules_dir)
    proj = tmp_path
    _make_part_dir(proj)  # assembly/bracket
    for name in ("lid", "pin"):
        d = proj / "assembly" / name
        d.mkdir(parents=True)
        (d / "part.py").write_text(STABLE_CODE)
        (d / "constraints.md").write_text("# C\n\n## Manufacturing\n- Primary process: CNC milling\n")
        r = d / "renders"
        r.mkdir()
        for i in range(8):
            (r / f"v{i}.png").write_bytes(b"png" + str(i).encode())
    asm = proj / "assembly" / "renders"
    asm.mkdir()
    for i in range(8):
        (asm / f"a{i}.png").write_bytes(b"apng" + str(i).encode())
    _write_rules(rules_dir, "dfa_rules.json", [_rule("A-GEN")])

    ok = _make_eval([_result("R-GEN", "pass")])
    LLMStub(monkeypatch, lambda label, prompt: ok)
    first = await dfma.evaluate_sweep(proj)
    assert first["reused_parts"] == 0 and first["total_parts"] == 3 and first["dfa_reused"] == "fresh"

    # Volley #2: everything fresh → full reuse; every reused part logs exactly one line
    LLMStub(monkeypatch, lambda label, prompt: pytest.fail("LLM must not be called on reuse"))
    caplog.clear()
    with caplog.at_level(_logging.INFO, logger="tools.dfma_evaluator"):
        out2 = await dfma.evaluate_sweep(proj)
    assert out2["reused_parts"] == 3 and out2["dfa_reused"] == "reused"
    part_reuse_lines = [m for m in caplog.messages if "REUSED fresh report for" in m]
    assert len(part_reuse_lines) == 3  # one per reused part — no silent drop
    assert any("REUSED fresh DFA report" in m for m in caplog.messages)
    assert any("dfa reused" in m for m in caplog.messages)  # summary carries dfa status
