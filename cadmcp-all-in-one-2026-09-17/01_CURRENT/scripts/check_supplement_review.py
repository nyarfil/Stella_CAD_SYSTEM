"""One bounded real-Sol two-round review of the isolated supplemental subject."""
from __future__ import annotations

import argparse
import copy
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from cadmcp_brain.api import Tools
from cadmcp_brain.engine import Brain
from cadmcp_brain.errors import BrainError
from cadmcp_brain.req2cad.common import atomic_json, file_hash, json_load
from cadmcp_brain.studio.autopilot import Autopilot
from cadmcp_brain.studio.provider import CodexProvider
from cadmcp_brain.studio.runtime import ROLES, Review


SOURCE_ROOT = ROOT / "verification" / "original-design-20260920-r2-remeasure"
SOURCE_RESULT = SOURCE_ROOT / "SUPPLEMENT_RESULT_V2.json"
SOURCE_WORKSPACE = SOURCE_ROOT / "workspace"
VERIFICATION_ROOT = (ROOT / "verification").resolve()
DEFAULT_RUN_ROOT = VERIFICATION_ROOT / "supplement-review-20260920"
PROJECT_ID = "original-l-plate"
EXPECTED_EVIDENCE = {
    "assembly.png", "build-record.json", "measurements.json",
    "source-build-record.json", "source-measurements.json",
    "supplement-spec.json", "supplement-report.json",
}


def resolve_run_root(value: Path) -> Path:
    candidate = value.resolve()
    try:
        candidate.relative_to(VERIFICATION_ROOT)
    except ValueError as exc:
        raise ValueError("Run root must stay under this checkout verification directory.") from exc
    if candidate == VERIFICATION_ROOT or candidate.exists():
        raise ValueError("Run root must be a new child of the verification directory.")
    return candidate


def provider_receipts(provider: CodexProvider) -> list[dict]:
    result = []
    for path in sorted(provider.root.glob("*/receipt.json")):
        result.append({"path": str(path.resolve()), "sha256": file_hash(path), **json_load(path)})
    return result


def file_manifest(folder: Path) -> dict[str, str]:
    return {path.relative_to(folder).as_posix(): file_hash(path)
            for path in folder.rglob("*") if path.is_file()}


def validate_attachments(packet: dict, subject_folder: Path) -> list[dict]:
    attachments = packet["subject"]["payload"].get("evidence_attachments", [])
    names = {Path(item["path"]).name for item in attachments}
    if not EXPECTED_EVIDENCE <= names or not any(name == "iso.png" for name in names):
        raise RuntimeError("Supplement packet omitted source/additional JSON or required PNG evidence.")
    for item in attachments:
        path = Path(item["path"])
        if not path.resolve().is_relative_to(subject_folder.resolve()):
            raise RuntimeError("Evidence attachment is outside the registered supplemental folder.")
        if path.is_symlink() or not path.is_file() or file_hash(path) != item["sha256"]:
            raise RuntimeError("Evidence attachment is missing, linked or hash-mismatched.")
    return attachments


def run_reviews(tools: Tools, autopilot: Autopilot, revision: int, subject: str,
                subject_folder: Path) -> tuple[list[dict], list[dict], list[dict]]:
    reports: list[dict] = []
    submissions: list[dict] = []
    evidence_manifest = None
    for round_number in (1, 2):
        first_round_ids = [item["review_id"] for item in submissions
                           if item["discussion_round"] == 1]

        def review_role(role: str) -> dict:
            nonlocal evidence_manifest
            packet = tools.brain_studio_review_packet(PROJECT_ID, revision, subject, role)
            manifest = validate_attachments(packet, subject_folder)
            if evidence_manifest is None:
                evidence_manifest = manifest
            elif manifest != evidence_manifest:
                raise RuntimeError("Role packets do not share one immutable evidence manifest.")
            packet["discussion_round"] = round_number
            if round_number == 2:
                packet["peer_findings"] = copy.deepcopy(reports)
                packet["required_challenged_review_ids"] = first_round_ids
                packet["instructions"] += (
                    " Challenge or corroborate every saved first-round review against the immutable "
                    "source build, supplemental specification/report, measurements and PNGs. Return every "
                    "required_challenged_review_id. Never clear a measured failure or unknown by vote."
                )
            review = autopilot.generate(Review, packet["instructions"], packet, role)
            if review["role"] != role or review["discussion_round"] != round_number:
                raise BrainError("AUTOPILOT_ROLE", "Reviewer returned another role or discussion round.")
            if round_number == 2 and set(review["challenged_review_ids"]) != set(first_round_ids):
                raise BrainError("AUTOPILOT_DEBATE", "Round-two review omitted saved first-round review IDs.")
            return review

        # A complete round is generated before any next-round call starts.
        with ThreadPoolExecutor(max_workers=3) as pool:
            round_reports = list(pool.map(review_role, ROLES))
        round_submissions = []
        for review in round_reports:
            receipt = tools.brain_studio_submit_review(PROJECT_ID, revision, subject, review)
            receipt["discussion_round"] = round_number
            round_submissions.append(receipt)
        reports.extend(round_reports)
        submissions.extend(round_submissions)
        autopilot.save("supplement_review", discussion_round=round_number,
                       review_reports=reports, review_receipts=submissions)
    return reports, submissions, evidence_manifest or []


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute-model", action="store_true",
                        help="Authorize this one bounded ten-call authenticated model run.")
    parser.add_argument("--run-root", type=Path, default=DEFAULT_RUN_ROOT,
                        help="New one-shot directory under this checkout verification folder.")
    args = parser.parse_args(argv)
    if not args.execute_model:
        parser.error("This proof makes one bounded authenticated model run; --execute-model is required.")
    try:
        run_root = resolve_run_root(args.run_root)
    except ValueError as exc:
        parser.error(str(exc))

    run_root.mkdir(parents=True)
    os.environ["CADMCP_REQ2CAD_ROOT"] = str((run_root / "isolated-req2cad").resolve())
    provider = None
    subject = None
    try:
        prior = json_load(SOURCE_RESULT)
        if not prior.get("passed") or prior.get("actual_model_called") is not False:
            raise RuntimeError("The fixed no-model supplemental result is not the expected passing source.")
        subject = prior["result"]["subject_digest"]
        subject_folder = Path(prior["result"]["folder"]).resolve()
        if not subject_folder.is_relative_to(SOURCE_WORKSPACE.resolve()):
            raise RuntimeError("Supplement subject is outside the fixed isolated source workspace.")

        tools = Tools(Brain(SOURCE_WORKSPACE))
        project = tools.brain_get(PROJECT_ID)["project"]
        revision = project["revision"]
        initial_status = tools.brain_studio_review_status(PROJECT_ID, revision, subject)
        if initial_status["reports"] != 0:
            raise RuntimeError("This one-shot subject already has model reviews; refusing a duplicate run.")
        source_before = file_manifest(subject_folder)

        provider = CodexProvider(run_root / "calls", model="gpt-5.6-sol", max_calls=10,
                                 timeout_seconds=180, evidence_root=SOURCE_WORKSPACE)
        autopilot = Autopilot(tools, provider, run_root / "autopilot", max_repairs=0,
                              max_replans=0, review_workers=3, debate_rounds=2,
                              design_route="original")
        reports, submissions, evidence_manifest = run_reviews(
            tools, autopilot, revision, subject, subject_folder)
        status = tools.brain_studio_review_status(PROJECT_ID, revision, subject)
        receipts = provider_receipts(provider)
        source_after = file_manifest(subject_folder)
        execution_checks = {
            "exactly_ten_model_calls": provider.calls == 10,
            "all_call_receipts_saved": len(receipts) == 10 and all(
                item.get("response_received") for item in receipts),
            "five_roles_two_rounds": len(reports) == 10 and all(
                sorted(item["discussion_round"] for item in reports if item["role"] == role) == [1, 2]
                for role in ROLES),
            "ten_reviews_registered": len(submissions) == 10 and status["reports"] == 10,
            "rounds_sequenced_and_peer_challenged": status["peer_challenge_complete"],
            "full_evidence_manifest_supplied": bool(evidence_manifest) and all(
                Path(item["path"]).is_file() for item in evidence_manifest),
            "source_build_folder_unchanged": source_before == source_after,
            "no_cad_regeneration_or_repair": status.get("cad_regenerated") is False,
        }
        execution_completed = all(execution_checks.values())
        accepted = bool(status["discussion_ready_for_owner"])
        report = {
            "execution_completed": execution_completed,
            "acceptance_status": "ready_for_owner_review" if accepted else "not_accepted",
            "overall_verdict": "unknown" if accepted else "not_accepted",
            "physical_performance_certified": False,
            "actual_model_called": provider.calls > 0,
            "model": "gpt-5.6-sol",
            "model_calls": provider.calls,
            "project_id": PROJECT_ID,
            "revision": revision,
            "subject_digest": subject,
            "source_result": str(SOURCE_RESULT.resolve()),
            "source_folder": str(subject_folder),
            "isolated_req2cad_root": os.environ["CADMCP_REQ2CAD_ROOT"],
            "evidence_manifest": evidence_manifest,
            "review_reports": reports,
            "review_receipts": submissions,
            "review_status": status,
            "execution_checks": execution_checks,
            "provider_receipts": receipts,
            "image_paths": [item["path"] for item in evidence_manifest if item["kind"] == "image"],
            "scope": "Existing isolated CAD only; two-round model review, no CAD generation, repair, physical test or certification.",
        }
        atomic_json(run_root / "SUPPLEMENT_REVIEW_RESULT.json", report)
        print(json.dumps({"execution_completed": execution_completed,
                          "acceptance_status": report["acceptance_status"],
                          "model_calls": provider.calls,
                          "report": str((run_root / "SUPPLEMENT_REVIEW_RESULT.json").resolve())},
                         ensure_ascii=True, indent=2))
        return 0 if execution_completed else 1
    except Exception as exc:
        error = exc.as_dict() if isinstance(exc, BrainError) else {
            "type": type(exc).__name__, "message": str(exc)}
        failure = {
            "execution_completed": False,
            "acceptance_status": "not_accepted",
            "overall_verdict": "not_accepted",
            "physical_performance_certified": False,
            "actual_model_called": bool(provider and provider.calls),
            "model_calls": provider.calls if provider else 0,
            "subject_digest": subject,
            "error": error,
            "provider_receipts": provider_receipts(provider) if provider else [],
            "run_root": str(run_root.resolve()),
        }
        atomic_json(run_root / "SUPPLEMENT_REVIEW_RESULT.json", failure)
        print(json.dumps(failure, ensure_ascii=True, indent=2))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
