---
name: dfm-rules
description: How the DFM (design-for-manufacturing) and DFA (design-for-assembly) rule system works: where the canonical rulebooks live (rules/*.json), the severity-weighted scoring arithmetic and regression gate, the rule lifecycle CLI, and the rule-proposal schema with authoring guidance. Use when interpreting a dfma_report.json, fixing DFM/DFA failures, understanding why a proposal was rejected by the regression gate, or proposing new rules. Rule CONTENT lives only in rules/*.json (read the JSON for the current inventory); enforcement runs through the evaluator TOOL (uv run python -m tools.dfma_evaluator): this skill teaches the mechanics, never the inventory, and is never a substitute for running the evaluation.
---

# DFM / DFA Rule System

## How the rule system works

- **Canonical rulebooks (machine-loaded):** `rules/dfm_rules.json` and
  `rules/dfa_rules.json` at repo root.
  Rule CONTENT (ids, thresholds, severities, fix hints) lives ONLY in those JSON files:
  this skill teaches the mechanics of the rule system, never the inventory.
  To see the current rules, read the JSON.
- **Enforcement path (the ONLY one):**
  - `uv run python -m tools.dfma_evaluator --mode=dfm --part-path <p>`: evaluate a part
  - `uv run python -m tools.dfma_evaluator --mode=dfa --asm-path <p>`: evaluate an assembly
  - `uv run python -m tools.dfma_evaluator --propose-rule '<json>'`: propose a new rule
  - `uv run python -m tools.dfma_evaluator --judge-proposal --part-path <p>`: DFM regression gate
- **Evaluation is vision-based and stochastic** (an LLM inspects renders against each rule's
  `look_for` / `pass_criteria` / `fail_criteria`).
  The same part may score slightly differently across runs;
  severity weighting mitigates but does not eliminate this variance.
- **Severity weights (the gate arithmetic):** critical=10, major=5, minor=1.
  DFMA is a unit-test suite for parts:
  repair/redesign writes `part.proposal.py`,
  and the regression gate promotes the proposal
  iff `proposal_score <= stable_score` (weighted sum of violations).
  Proposals that worsen the score are automatically REJECTED.
- **Tiers:** three of them.
  `active` rules are evaluated on every run:
  they drive verdicts and the regression-gate score.
  `probationary` rules are staged proposals living in `rules/*.proposed.json`;
  they are merged in ONLY under `--include-probationary`,
  and even then they are warning-only:
  a failing probationary rule is reported as a warning
  and never affects the overall verdict or the gate score.
  `retired` rules are skipped tombstones,
  each recording its retirement reason in its own description
  (fillet-related rules, for example, are retired because fillets are deferred project-wide).

## Proposing a new rule

Proposals go through `--propose-rule '<json>'`.
They land in `rules/*.proposed.json` at `probationary` tier
and do NOT become active automatically:
promotion is adjudicated through the lifecycle CLI below.
Full rule schema:

```json
{
  "id": "DFM-<PROCESS>-NNN | DFA-NNN",
  "category": "geometry | features | access | part_count | self_locating | handling | sequence | fastening",
  "manufacturing": ["CNC_milling", "CNC_turning", "injection_molding", "sheet_metal", "3D_printing", "casting"],
  "tier": "active | probationary | retired",
  "description": "One-line rule statement with the threshold",
  "look_for": "What the vision evaluator should scan for in the renders",
  "pass_criteria": "Visually checkable condition for PASS",
  "fail_criteria": "Visually checkable condition for FAIL",
  "severity": "critical | major | minor",
  "confidence": 0.85,
  "times_applied": 0,
  "true_positives": 0,
  "false_positives": 0,
  "source": "Citation (e.g., Boothroyd-Dewhurst DFMA methodology)",
  "fix_hint": "Concrete CadQuery-level remediation the repair agent can act on"
}
```

Authoring guidance:
`look_for` / `pass_criteria` / `fail_criteria` must be judgeable from RENDERS
(the evaluator sees images, not code):
write them as visual checks, not code checks.
`fix_hint` should name concrete CadQuery calls, since the repair agent consumes it verbatim.
An empty `manufacturing` list means the rule applies to every process.
Whatever `tier` you write in the payload is ignored:
`--propose-rule` forces the new rule to `probationary` and resets its counters.

## Rule lifecycle

A proposed rule travels a fixed path, all of it through the evaluator tool.
`--propose-rule` lands it as `probationary`.
`--triage-proposals` walks every probationary proposal
and produces a deterministic promote / retire / keep recommendation with a rationale,
auto-applying the clear-cut decisions;
add `--dry-run` to preview the recommendations without mutating any rule file.
`--promote-rule <id>` moves a proposal into the active set,
and `--retire-rule <id> --reason "<why>"` tombstones a rule at either tier.
Proposals recommended as `keep` stay probationary until more evidence accrues.
Every transition appends a record to `rules/rule_lifecycle_log.json`,
so the decision trail survives:
the `dfma_inspector` agent acts as the AI arbiter for these calls,
human review is deferred rather than skipped,
and any transition is reversible through the log and git history.
For the exact flags and their arguments,
read the module docstring at the top of `.shared/tools/dfma_evaluator.py`.
