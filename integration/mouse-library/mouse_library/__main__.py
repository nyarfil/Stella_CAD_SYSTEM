"""A dependency-free, newline-delimited JSON-RPC MCP server.

The server intentionally owns no CAD session and never asserts that a reference
part fits a user's hardware.  It turns the curated library JSON into bounded
retrieval and planning guidance for any MCP-capable CAD harness.
"""
from __future__ import annotations

import json
import hashlib
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any

from . import __version__
from .click_window import INPUT_SCHEMA as CLICK_WINDOW_SCHEMA, evaluate as evaluate_click_window


PROTOCOL = "2025-11-25"
SUPPORTED_PROTOCOLS = {"2024-11-05", "2025-03-26", "2025-06-18", "2025-11-25"}
MAX_FRAME_BYTES = 1024 * 1024
MAX_RESULTS = 20
ENTRY_ID = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{0,79}$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
DATA_PATH = Path(__file__).resolve().parent / "data" / "library.json"
MEASUREMENTS_PATH = Path(__file__).resolve().parent / "data" / "measurements.json"


class ToolError(ValueError):
    """An input or library problem that can be shown safely to an MCP caller."""


class LibrarySnapshot(dict[str, Any]):
    """A parsed library plus the digest of the exact bytes that were parsed."""

    def __init__(self, payload: dict[str, Any], content_sha256: str) -> None:
        super().__init__(payload)
        self.content_sha256 = content_sha256


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _strict_json(text: str) -> Any:
    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        value: dict[str, Any] = {}
        for key, item in items:
            if key in value:
                raise ValueError("duplicate JSON key")
            value[key] = item
        return value

    def reject(_: str) -> None:
        raise ValueError("non-finite JSON number")

    return json.loads(text, object_pairs_hook=pairs, parse_constant=reject)


def _require_object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ToolError(f"{label} must be an object")
    return value


def _only_keys(arguments: dict[str, Any], allowed: set[str]) -> None:
    unknown = sorted(set(arguments) - allowed)
    if unknown:
        raise ToolError(f"Unsupported arguments: {', '.join(unknown)}")


def _require_string(value: Any, label: str, *, minimum: int = 1, maximum: int = 20000) -> str:
    if not isinstance(value, str):
        raise ToolError(f"{label} must be a string")
    cleaned = " ".join(value.split())
    if not minimum <= len(cleaned) <= maximum:
        raise ToolError(f"{label} must contain {minimum}..{maximum} characters")
    return cleaned


def _require_sha256(value: Any, label: str) -> str:
    if not isinstance(value, str) or not SHA256.fullmatch(value):
        raise ToolError(f"{label} must be a lowercase SHA-256 hex digest")
    return value


def _validate_hash_fields(value: Any, label: str = "payload") -> None:
    """Keep copied provenance hashes machine-checkable without inventing schema."""
    if isinstance(value, dict):
        for key, item in value.items():
            key_label = f"{label}.{key}"
            if isinstance(key, str) and key.endswith("sha256"):
                if key == "input_sha256":
                    if not isinstance(item, dict):
                        raise ToolError(f"{key_label} must be an object")
                    for name, digest in item.items():
                        _require_sha256(digest, f"{key_label}.{name}")
                elif item is None and label.endswith("measurement_record_template.source"):
                    # This is a blank record form, not a claimed measurement.
                    # Actual source and bundled-report hashes remain mandatory.
                    pass
                else:
                    _require_sha256(item, key_label)
            _validate_hash_fields(item, key_label)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _validate_hash_fields(item, f"{label}[{index}]")


def _string_list(value: Any, label: str, *, maximum: int = 50) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list) or len(value) > maximum:
        raise ToolError(f"{label} must be an array with at most {maximum} strings")
    return [_require_string(item, label, maximum=1000) for item in value]


def _bounded_int(value: Any, label: str, *, default: int, minimum: int, maximum: int) -> int:
    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise ToolError(f"{label} must be an integer in {minimum}..{maximum}")
    return value


def _as_string(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, (list, tuple)):
        return " ".join(_as_string(item) for item in value)
    if isinstance(value, dict):
        return " ".join(f"{key} {_as_string(item)}" for key, item in value.items())
    return "" if value is None else str(value)


def _load_library() -> dict[str, Any]:
    try:
        raw = DATA_PATH.read_bytes()
        payload = _strict_json(raw.decode("utf-8"))
    except FileNotFoundError as exc:
        raise ToolError("Knowledge data is not installed yet: data/library.json is missing") from exc
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as exc:
        raise ToolError(f"Knowledge data cannot be read: {type(exc).__name__}") from exc
    if not isinstance(payload, dict):
        raise ToolError("Knowledge data must be a JSON object")
    _validate_hash_fields(payload, "Knowledge data")
    for field in ("schema_version", "library_version", "scope"):
        _require_string(payload.get(field), f"Knowledge data.{field}", maximum=20000)
    sources = payload.get("sources")
    entries = payload.get("entries")
    if not isinstance(sources, list) or not sources:
        raise ToolError("Knowledge data has no nonempty sources array")
    if not isinstance(entries, list):
        raise ToolError("Knowledge data has no entries array")
    source_ids: set[str] = set()
    for source in sources:
        if not isinstance(source, dict):
            raise ToolError("Knowledge data contains a non-object source")
        source_id = source.get("id")
        if not isinstance(source_id, str) or not ENTRY_ID.fullmatch(source_id) or source_id in source_ids:
            raise ToolError("Knowledge data has an invalid or duplicate source id")
        source_ids.add(source_id)
        for field in ("title", "kind", "authority"):
            _require_string(source.get(field), f"Knowledge source {source_id}.{field}", maximum=20000)
        for field in ("url", "license", "observed_on", "artifact", "artifact_uri", "sha256"):
            if field in source and not isinstance(source[field], str):
                raise ToolError(f"Knowledge source {source_id}.{field} must be a string")
        if "sha256" in source:
            _require_sha256(source["sha256"], f"Knowledge source {source_id}.sha256")
        if "input_sha256" in source:
            hashes = source["input_sha256"]
            if not isinstance(hashes, dict) or not hashes:
                raise ToolError(f"Knowledge source {source_id}.input_sha256 must be a nonempty object")
            for artifact_name, digest in hashes.items():
                _require_string(artifact_name, f"Knowledge source {source_id}.input_sha256 key", maximum=500)
                _require_sha256(digest, f"Knowledge source {source_id}.input_sha256.{artifact_name}")
        if "measurement_records" in source:
            records = source["measurement_records"]
            if not isinstance(records, list) or not records:
                raise ToolError(f"Knowledge source {source_id}.measurement_records must be a nonempty array")
            record_ids: set[str] = set()
            for record in records:
                if not isinstance(record, dict):
                    raise ToolError(f"Knowledge source {source_id} has a non-object measurement record")
                record_id = record.get("id")
                if not isinstance(record_id, str) or not ENTRY_ID.fullmatch(record_id) or record_id in record_ids:
                    raise ToolError(f"Knowledge source {source_id} has an invalid measurement record id")
                record_ids.add(record_id)
                for field in ("method", "status"):
                    _require_string(record.get(field), f"Knowledge source {source_id}.measurement_records.{field}", maximum=20000)
                if not isinstance(record.get("units", record.get("unit_assumption")), str):
                    raise ToolError(f"Knowledge source {source_id} measurement record needs units or unit_assumption")
    seen: set[str] = set()
    for entry in entries:
        if not isinstance(entry, dict):
            raise ToolError("Knowledge data contains a non-object entry")
        entry_id = entry.get("id")
        if not isinstance(entry_id, str) or not ENTRY_ID.fullmatch(entry_id) or entry_id in seen:
            raise ToolError("Knowledge data has an invalid or duplicate entry id")
        seen.add(entry_id)
        for field in ("title", "subsystem", "summary"):
            _require_string(entry.get(field), f"Knowledge entry {entry_id}.{field}", maximum=20000)
        for field in ("tags", "principles", "interfaces", "workflow", "verification", "common_failures", "unknowns"):
            _string_list(entry.get(field), f"Knowledge entry {entry_id}.{field}", maximum=100)
        evidence = entry.get("evidence")
        if not isinstance(evidence, list) or not evidence:
            raise ToolError(f"Knowledge entry {entry_id}.evidence must be a nonempty array")
        for claim in evidence:
            if not isinstance(claim, dict) or claim.get("source_id") not in source_ids:
                raise ToolError(f"Knowledge entry {entry_id} has an unknown evidence source")
            for field in ("source_id", "status", "claim"):
                _require_string(claim.get(field), f"Knowledge entry {entry_id}.evidence.{field}", maximum=20000)
            if claim["status"] not in {"principle", "observed", "author_reported", "measured_reference"}:
                raise ToolError(f"Knowledge entry {entry_id} has an unsupported evidence status")
    workflow = payload.get("workflow")
    if not isinstance(workflow, dict):
        raise ToolError("Knowledge data has no workflow object")
    stages = workflow.get("stages")
    if not isinstance(stages, list) or not stages:
        raise ToolError("Knowledge workflow has no nonempty stages array")
    for stage in stages:
        if not isinstance(stage, dict):
            raise ToolError("Knowledge workflow contains a non-object stage")
        for field in ("id", "action"):
            _require_string(stage.get(field), f"Knowledge workflow stage.{field}", maximum=20000)
        _string_list(stage.get("outputs"), "Knowledge workflow stage.outputs", maximum=100)
    _string_list(workflow.get("required_hardware"), "Knowledge workflow.required_hardware", maximum=100)
    _string_list(workflow.get("gates"), "Knowledge workflow.gates", maximum=100)
    if not isinstance(workflow.get("states"), dict):
        raise ToolError("Knowledge workflow.states must be an object")
    if "measurement_record_template" in workflow and not isinstance(workflow["measurement_record_template"], dict):
        raise ToolError("Knowledge workflow.measurement_record_template must be an object")
    if "cad_capability_checklist" in workflow:
        _string_list(workflow["cad_capability_checklist"], "Knowledge workflow.cad_capability_checklist", maximum=100)
    return LibrarySnapshot(payload, hashlib.sha256(raw).hexdigest())


def _load_measurements() -> LibrarySnapshot:
    """Load only the portable, normalized derived-geometry reports."""
    try:
        raw = MEASUREMENTS_PATH.read_bytes()
        payload = _strict_json(raw.decode("utf-8"))
    except FileNotFoundError as exc:
        raise ToolError("Packaged measurements are missing: data/measurements.json") from exc
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as exc:
        raise ToolError(f"Packaged measurements cannot be read: {type(exc).__name__}") from exc
    if not isinstance(payload, dict):
        raise ToolError("Packaged measurements must be a JSON object")
    _validate_hash_fields(payload, "Packaged measurements")
    _require_string(payload.get("schema_version"), "Packaged measurements.schema_version", maximum=100)
    _require_string(payload.get("scope"), "Packaged measurements.scope", maximum=20000)
    reports = payload.get("reports")
    if not isinstance(reports, list) or not reports:
        raise ToolError("Packaged measurements has no nonempty reports array")
    ids: set[str] = set()
    for item in reports:
        if not isinstance(item, dict):
            raise ToolError("Packaged measurements contains a non-object report")
        report_id = item.get("id")
        if not isinstance(report_id, str) or not ENTRY_ID.fullmatch(report_id) or report_id in ids:
            raise ToolError("Packaged measurements has an invalid or duplicate report id")
        ids.add(report_id)
        _require_sha256(item.get("original_report_sha256"), f"Packaged measurement {report_id}.original_report_sha256")
        _require_string(item.get("normalization"), f"Packaged measurement {report_id}.normalization", maximum=20000)
        if not isinstance(item.get("report"), dict):
            raise ToolError(f"Packaged measurement {report_id}.report must be an object")
    return LibrarySnapshot(payload, hashlib.sha256(raw).hexdigest())


def _entries(library: dict[str, Any]) -> list[dict[str, Any]]:
    return [item for item in library["entries"] if isinstance(item, dict)]


def _entry_index(library: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {entry["id"]: entry for entry in _entries(library)}


def _library_provenance(library: dict[str, Any], source_ids: set[str] | None = None) -> dict[str, Any]:
    """Portable provenance for a response without treating a source as CAD."""
    content_sha256 = getattr(library, "content_sha256", None)
    if not isinstance(content_sha256, str):
        try:
            content_sha256 = hashlib.sha256(DATA_PATH.read_bytes()).hexdigest()
        except OSError as exc:
            raise ToolError(f"Knowledge data cannot be hashed: {type(exc).__name__}") from exc
    sources = _as_list(library.get("sources"))
    if source_ids is not None:
        sources = [source for source in sources if isinstance(source, dict) and source.get("id") in source_ids]
    measurements = _load_measurements()
    return {
        "schema_version": library["schema_version"],
        "library_version": library["library_version"],
        "content_sha256": content_sha256,
        "sources": sources,
        "data_artifacts": [{
            "uri": "mouse-library://measurements",
            "schema_version": measurements["schema_version"],
            "content_sha256": measurements.content_sha256,
            "scope": measurements["scope"],
        }],
    }


def _source_ids_for(entries: list[dict[str, Any]]) -> set[str]:
    return {evidence["source_id"] for entry in entries for evidence in _evidence_summary(entry)}


def _evidence_summary(entry: dict[str, Any]) -> list[dict[str, str]]:
    evidence = entry.get("evidence", [])
    if not isinstance(evidence, list):
        return []
    rows: list[dict[str, str]] = []
    for item in evidence:
        if isinstance(item, dict):
            source_id = item.get("source_id")
            status = item.get("status")
            claim = item.get("claim")
            if all(isinstance(x, str) for x in (source_id, status, claim)):
                rows.append({"source_id": source_id, "status": status, "claim": claim})
    return rows


def _result_card(entry: dict[str, Any], score: int | None = None) -> dict[str, Any]:
    card: dict[str, Any] = {
        "id": entry["id"],
        "title": entry.get("title", entry["id"]),
        "subsystem": entry.get("subsystem", "unspecified"),
        "tags": entry.get("tags", []),
        "summary": entry.get("summary", ""),
        "evidence": _evidence_summary(entry),
        "unknowns": entry.get("unknowns", []),
    }
    if score is not None:
        card["match_score"] = score
    return card


def mouse_library_status(_: dict[str, Any]) -> dict[str, Any]:
    _only_keys(_, set())
    library = _load_library()
    entries = _entries(library)
    statuses = Counter(
        evidence.get("status", "unspecified")
        for entry in entries
        for evidence in _evidence_summary(entry)
    )
    return {
        "server_version": __version__,
        "library_provenance": _library_provenance(library),
        "entry_count": len(entries),
        "subsystems": sorted({str(entry.get("subsystem", "unspecified")) for entry in entries}),
        "evidence_status_counts": dict(sorted(statuses.items())),
        "mode": "read_only_guidance",
        "limits": [
            "The library does not contain a CAD kernel, a measured hardware pack, or an automatic fit claim.",
            "Use measurements and physical checks before treating any suggested interface as build-ready.",
        ],
    }


def mouse_library_search(arguments: dict[str, Any]) -> dict[str, Any]:
    _only_keys(arguments, {"query", "subsystem", "limit"})
    query = _require_string(arguments.get("query"), "query", maximum=300).casefold()
    subsystem = arguments.get("subsystem")
    if subsystem is not None:
        subsystem = _require_string(subsystem, "subsystem", maximum=100).casefold()
    limit = _bounded_int(arguments.get("limit"), "limit", default=8, minimum=1, maximum=MAX_RESULTS)
    # ``\w+`` treats a Japanese phrase as one token.  Add compact CJK n-grams
    # so a request such as 「ホイールの構造」 can find cards containing the two
    # concepts in separate fields without needing an English paraphrase.
    words = [token for token in re.findall(r"[A-Za-z0-9_-]+", query) if len(token) >= 2]
    cjk_runs = re.findall(r"[\u3040-\u30ff\u3400-\u9fff]+", query)
    cjk_terms = [run[index:index + width] for run in cjk_runs for width in (2, 3) for index in range(len(run) - width + 1)]
    tokens = list(dict.fromkeys([*words, *cjk_terms]))
    if not tokens:
        raise ToolError("query must contain at least one searchable word")
    matches: list[tuple[int, dict[str, Any]]] = []
    library = _load_library()
    for entry in _entries(library):
        entry_subsystem = str(entry.get("subsystem", ""))
        if subsystem and entry_subsystem.casefold() != subsystem:
            continue
        haystack = _as_string({key: entry.get(key, "") for key in (
            "id", "title", "subsystem", "tags", "summary", "principles", "interfaces", "workflow", "common_failures"
        )}).casefold()
        score = sum(haystack.count(token) for token in tokens)
        if query in haystack:
            score += len(tokens) + 3
        if score:
            matches.append((score, entry))
    matches.sort(key=lambda item: (-item[0], str(item[1]["id"])))
    returned_entries = [entry for _, entry in matches[:limit]]
    return {
        "query": query,
        "subsystem": subsystem,
        "results": [_result_card(entry, score) for score, entry in matches[:limit]],
        "result_count": min(len(matches), limit),
        "total_matches": len(matches),
        "interpretation": "Lexical library retrieval only; a match is not a geometry, fit, strength, or safety validation.",
        "library_provenance": _library_provenance(library, _source_ids_for(returned_entries)),
    }


def mouse_library_get(arguments: dict[str, Any]) -> dict[str, Any]:
    _only_keys(arguments, {"id"})
    entry_id = _require_string(arguments.get("id"), "id", maximum=80)
    if not ENTRY_ID.fullmatch(entry_id):
        raise ToolError("id has an invalid format")
    library = _load_library()
    entry = _entry_index(library).get(entry_id)
    if entry is None:
        raise ToolError("Unknown library entry id")
    return {"entry": entry, "library_provenance": _library_provenance(library, _source_ids_for([entry])), "mode": "read_only_reference"}


def _requirements(arguments: dict[str, Any]) -> dict[str, Any]:
    req = _require_object(arguments.get("requirements"), "requirements")
    allowed = {
        "original_request", "hardware_id", "button_architecture", "connection", "manufacturing_process",
        "available_cad_tools", "measurements", "protected_constraints",
    }
    unknown = sorted(set(req) - allowed)
    if unknown:
        raise ToolError(f"requirements contains unsupported properties: {', '.join(unknown)}")
    # This text feeds Stella's traceability rule: FunctionTask.source_excerpt
    # must occur byte-for-byte in original_request.  Do not collapse whitespace.
    original_value = req.get("original_request")
    if not isinstance(original_value, str) or not 3 <= len(original_value) <= 20000:
        raise ToolError("requirements.original_request must contain 3..20000 characters")
    original = original_value
    hardware = req.get("hardware_id")
    if hardware is not None:
        hardware = _require_string(hardware, "requirements.hardware_id", maximum=200)
    architecture = req.get("button_architecture", "unspecified")
    if architecture not in ("integrated", "separate", "unspecified"):
        raise ToolError("requirements.button_architecture must be integrated, separate, or unspecified")
    connection = req.get("connection", "unspecified")
    if connection not in ("wired", "wireless", "unspecified"):
        raise ToolError("requirements.connection must be wired, wireless, or unspecified")
    process = req.get("manufacturing_process")
    if process is not None:
        process = _require_string(process, "requirements.manufacturing_process", maximum=200)
    tools = _string_list(req.get("available_cad_tools"), "requirements.available_cad_tools", maximum=30)
    measurements = req.get("measurements", {})
    if not isinstance(measurements, dict) or len(measurements) > 100:
        raise ToolError("requirements.measurements must be an object with at most 100 fields")
    constraints = _string_list(req.get("protected_constraints"), "requirements.protected_constraints", maximum=50)
    return {
        "original_request": original,
        "hardware_id": hardware,
        "button_architecture": architecture,
        "connection": connection,
        "manufacturing_process": process,
        "available_cad_tools": tools,
        "measurements": measurements,
        "protected_constraints": constraints,
    }


def _select_entries(library: dict[str, Any], req: dict[str, Any]) -> list[dict[str, Any]]:
    entries = _entries(library)
    query = req["original_request"].casefold()
    # These are baseline subsystems for the stated general mouse design goal.
    # They are planning inferences, not claims that the user's request named
    # every one.  The bridge exposes that distinction explicitly.
    wanted_ids = {
        "primary_click_mechanism", "pcb_support_and_location",
        "optical_datum_chain", "shell_loads_and_grip", "assembly_fasteners_and_feet",
    }
    if req["button_architecture"] == "integrated":
        wanted_ids.add("primary_click_mechanism")
    elif req["button_architecture"] == "separate":
        wanted_ids.add("primary_click_mechanism")
    if req["connection"] in {"wired", "wireless"}:
        wanted_ids.add("power_wiring_and_service")
    keyword_groups = {
        "wheel": "wheel_rotation_and_click", "scroll": "wheel_rotation_and_click", "ホイール": "wheel_rotation_and_click", "スクロール": "wheel_rotation_and_click",
        "side": "side_button_mechanism", "thumb": "side_button_mechanism", "サイド": "side_button_mechanism", "親指": "side_button_mechanism",
        "sensor": "optical_datum_chain", "optical": "optical_datum_chain", "センサー": "optical_datum_chain",
        "battery": "power_wiring_and_service", "wireless": "power_wiring_and_service", "wired": "power_wiring_and_service", "cable": "power_wiring_and_service", "usb": "power_wiring_and_service", "電池": "power_wiring_and_service", "充電": "power_wiring_and_service", "有線": "power_wiring_and_service", "ケーブル": "power_wiring_and_service",
    }
    for word, entry_id in keyword_groups.items():
        if word in query:
            wanted_ids.add(entry_id)
    selected = [entry for entry in entries if entry["id"] in wanted_ids]
    if not selected:
        selected = entries[:]
    # Stable cap protects the FunctionBrief's 12-function limit.
    return selected[:12]


def _guidance_entries(library: dict[str, Any], req: dict[str, Any]) -> list[dict[str, Any]]:
    """Context cards which guide planning but are not product functions."""
    ids = ["mouse_architecture", "cad_tool_handoff"]
    reference_text = f"{req['hardware_id'] or ''} {req['original_request']}".casefold()
    if "g305" in reference_text or "zs-f1" in reference_text:
        ids.append("zs_f1_g305_case")
    process = (req["manufacturing_process"] or "").casefold()
    if any(word in process for word in ("fdm", "3d print", "3dプリント", "3d プリント")):
        ids.append("fdm_manufacturing")
    return [entry for entry_id in ids if (entry := _entry_index(library).get(entry_id)) is not None]


def _unique_strings(values: list[Any], *, limit: int) -> list[str]:
    answer: list[str] = []
    for value in values:
        if isinstance(value, str):
            cleaned = " ".join(value.split())
            if cleaned and cleaned not in answer:
                answer.append(cleaned)
                if len(answer) == limit:
                    break
    return answer


def _plan(req: dict[str, Any], library: dict[str, Any] | None = None) -> dict[str, Any]:
    library = library if library is not None else _load_library()
    selected = _select_entries(library, req)
    guidance = _guidance_entries(library, req)
    workflow = library["workflow"]
    stages = workflow.get("stages", [])
    hardware_facts = workflow.get("required_hardware", [])
    workflow_gates = workflow.get("gates", [])
    unresolved: list[Any] = []
    for entry in [*selected, *guidance]:
        unresolved.extend(entry.get("unknowns", []) if isinstance(entry.get("unknowns"), list) else [])
    unresolved.extend([
        "Every provided measurement remains user-provided and unvalidated until its datum, method, unit, and uncertainty are recorded.",
        "A source-grounded design plan is not an assembled CAD model, a collision check, or a physical-fit result.",
    ])
    if not req["hardware_id"]:
        unresolved.append("Select the exact PCB, switches, sensor lens, wheel/encoder, power hardware, and fasteners before freezing interfaces.")
    if not req["measurements"]:
        unresolved.append("Record actual hardware datums and envelope measurements before building retaining features.")
    request_measurements = [
        {"name": str(key), "value": value, "status": "user_provided_unvalidated"}
        for key, value in req["measurements"].items()
    ]
    reported_tools = [
        {"name": tool, "reported_by_user": True, "capabilities": "unverified"}
        for tool in req["available_cad_tools"]
    ]
    capability_gaps = [
        "Read each CAD tool's live tool list and input schema; tool names alone prove no capability.",
        "Confirm whether the tool can represent protected hardware, create solids, inspect dimensions, analyze clearance/motion, and export STEP.",
        "Confirm which measurements, physical tests, and manufacturing checks remain outside the available CAD toolchain.",
    ]
    return {
        "status": "planning_guidance_not_cad_approval",
        "requirements": req,
        "library_provenance": _library_provenance(library, _source_ids_for([*selected, *guidance])),
        "inferred_product_function_entries": [
            {**_result_card(entry), "selection": "planning_inference_from_a_general_mouse_design_request; host_check_against_original_request"}
            for entry in selected
        ],
        "planning_guidance_entries": [
            {**_result_card(entry), "selection": "workflow_guidance_only; not_a_mandatory_product_function"}
            for entry in guidance
        ],
        "manufacturing_guidance": (
            "The declared process appears FDM-compatible, so the FDM card is supplied as workflow guidance only."
            if any(card["id"] == "fdm_manufacturing" for card in guidance)
            else "Choose a manufacturing process and its qualified material, tolerance, orientation, and support constraints before applying process-specific design rules."
        ),
        "workflow": {
            "stages": stages,
            "states": workflow.get("states", {}),
            "gates": workflow_gates,
            "measurement_record_template": workflow.get("measurement_record_template", {}),
            "cad_capability_checklist": workflow.get("cad_capability_checklist", []),
            "generic_input_contract": workflow.get("generic_input_contract", {}),
        },
        "required_hardware_facts": hardware_facts,
        "provided_measurements": request_measurements,
        "cad_tool_capability_status": {
            "reported_tools": reported_tools,
            "required_capability_checks": _unique_strings([
                *_as_list(workflow.get("cad_capability_checklist", [])),
                *capability_gaps,
            ], limit=50),
        },
        "unresolved": _unique_strings(unresolved, limit=50),
        "mandatory_gates": _unique_strings([
            *_as_list(workflow_gates),
            "Freeze selected hardware and protected constraints before CAD construction.",
            "Inspect idle, actuation, maximum travel, release, insertion, and service states for every moving subsystem.",
            "Measure or physically validate interfaces before declaring a fit.",
        ], limit=50),
        "safety_boundary": [
            "No CAD session was opened or modified.",
            "No hardware geometry, dimensions, tolerances, material properties, strength, or electrical safety was inferred.",
        ],
    }


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def mouse_library_plan(arguments: dict[str, Any]) -> dict[str, Any]:
    _only_keys(arguments, {"requirements"})
    return _plan(_requirements(arguments))


def _safe_id(value: Any, fallback: str, used: set[str]) -> str:
    candidate = re.sub(r"[^A-Za-z0-9_-]+", "_", str(value)).strip("_-")
    if not candidate or not candidate[0].isalpha():
        candidate = fallback
    candidate = candidate[:64]
    base = candidate
    counter = 2
    while candidate in used:
        suffix = f"_{counter}"
        candidate = base[: 64 - len(suffix)] + suffix
        counter += 1
    used.add(candidate)
    return candidate


def mouse_library_stella_bridge(arguments: dict[str, Any]) -> dict[str, Any]:
    _only_keys(arguments, {"requirements"})
    req = _requirements(arguments)
    library = _load_library()
    entry_by_id = _entry_index(library)
    plan = _plan(req, library)
    source_excerpt = req["original_request"][:2000]
    used_ids: set[str] = set()
    functions: list[dict[str, Any]] = []
    inferred_function_ids: list[str] = []
    for index, card in enumerate(plan["inferred_product_function_entries"], start=1):
        entry = entry_by_id[card["id"]]
        principle = _as_string(entry.get("principles", entry.get("summary", "")))
        title = _require_string(str(entry.get("title", entry["id"])), "entry title", maximum=300)
        objectives = {
            "primary_click_mechanism": "Transmit independent left and right primary click input.",
            "pcb_support_and_location": "Retain and locate the selected electronics without deforming protected hardware.",
            "optical_datum_chain": "Maintain the selected optical sensor and lens datum chain to the desk surface.",
            "shell_loads_and_grip": "Provide a hand-contact enclosure while preserving protected internal space and input motion.",
            "assembly_fasteners_and_feet": "Allow assembly, service, fastener access, and stable feet without constraining moving parts.",
            "wheel_rotation_and_click": "Provide scroll rotation and middle-click input as separately verified motions.",
            "power_wiring_and_service": "Retain the selected power hardware and route it clear of moving parts with service access.",
            "side_button_mechanism": "Transmit the selected thumb-button inputs to their intended switches.",
        }
        function = objectives.get(entry["id"], title)[:300]
        states = _as_list(library["workflow"].get("states", {}).get(entry.get("subsystem")))
        behavior = " ".join(filter(None, [
            f"Summary: {entry.get('summary', '')}",
            f"Principles: {_as_string(entry.get('principles', []))}",
            f"Interfaces: {_as_string(entry.get('interfaces', []))}",
            f"Workflow: {_as_string(entry.get('workflow', []))}",
            f"States: {_as_string(states)}" if states else "",
            f"Verification: {_as_string(entry.get('verification', []))}",
        ]))[:2000]
        behavior = behavior or "Preserve the relevant interface and verify it against measured hardware."
        if len(behavior) < 5:
            behavior = "Preserve the relevant interface and verify it against measured hardware."
        queries = _unique_strings([
            title, str(entry.get("subsystem", "mouse subsystem")), principle[:300],
        ], limit=8)
        queries = [item[:400] for item in queries if item]
        if not queries:
            queries = ["mouse mechanical subsystem"]
        function_id = _safe_id(entry["id"], f"mouse_function_{index}", used_ids)
        inferred_function_ids.append(function_id)
        functions.append({
            "id": function_id,
            "source_excerpt": source_excerpt,
            "function": function,
            "behavior": behavior,
            "queries": queries,
            "required_features": [],
        })
    if not functions:
        functions.append({
            "id": "mouse_system", "source_excerpt": source_excerpt,
            "function": "Create a source-grounded mouse system plan",
            "behavior": "Identify mechanical interfaces and verify them against selected, measured hardware before design approval.",
            "queries": ["computer mouse mechanical interfaces"], "required_features": [],
        })
    function_brief = {
        "original_request": req["original_request"],
        "functions": functions[:12],
        "protected_constraints": _unique_strings([
            *req["protected_constraints"],
            "Treat all selected existing electronics and user-owned hardware as protected until measured CAD and an explicit change authorization exist.",
            "Do not treat library references as a license to copy geometry or as proof of hardware fit.",
        ], limit=50),
        "unresolved": plan["unresolved"][:50],
    }
    knowledge_uses = [
        {
            "entry_id": entry["id"],
            "use": "principle_and_interface_reference_only_not_a_Req2CAD_ReferenceUse",
            "evidence": _evidence_summary(entry),
            "unknowns": entry.get("unknowns", []),
        }
        for entry in (entry_by_id[card["id"]] for card in plan["inferred_product_function_entries"])
    ]
    principle_text = [
        _as_string(entry_by_id[card["id"]].get("principles", card["summary"]))
        for card in plan["inferred_product_function_entries"]
    ]
    recipe_design_basis = {
        # This shape matches the current Stella Recipe.DesignBasis schema.  It
        # is intentionally separate from the richer conceptual basis below.
        "kind": "first_principles",
        "summary": "A first-principles mouse design draft using curated library principles as non-geometric provenance; all fit-critical hardware interfaces remain to be measured and verified.",
        "assumptions": [
            "Selected hardware and every fit-critical datum will be inspected from actual hardware or authoritative CAD before Recipe construction.",
            "Curated library cards guide reasoning only and are not Req2CAD references, protected hardware packs, or direct geometry reuse.",
        ],
    }
    return {
        "status": "bridge_draft_not_validated_recipe",
        "library_provenance": plan["library_provenance"],
        "function_brief": function_brief,
        "function_brief_annotation": {
            "inferred_function_ids": inferred_function_ids,
            "meaning": "These functions were inferred for a general mouse design plan. The original request does not itself prove that every one is required; confirm, remove, or add functions before Stella construction.",
        },
        "recipe_design_basis": recipe_design_basis,
        "recipe_completion_hints": {
            "verification_plan": plan["mandatory_gates"],
            "unverified_requirements": plan["unresolved"],
            "note": "These are adjacent hints for a future Recipe. They are not fields of Recipe.design_basis and do not form a Recipe without typed operations, outputs, and live Stella validation.",
        },
        "concept_design_basis": {
            # This matches the first-principles option-basis shape used during
            # Stella concept synthesis, but is not itself an Option or Recipe.
            "kind": "first_principles",
            "principles": principle_text,
            "assumptions": [
                "The selected hardware, its coordinate system, and all fit-critical dimensions must be measured or supplied by an authoritative CAD source.",
                "The resulting FunctionBrief is a host-model input and requires the Stella schema gate before any Recipe is built.",
            ],
            "verification_plan": plan["mandatory_gates"],
            "unknowns": plan["unresolved"],
        },
        "recipe_reference_uses": [],
        "knowledge_uses": knowledge_uses,
        "stella_handoff": {
            "recommended_next_calls": [
                "brain_studio_schema(name='FunctionBrief') and validate this draft against the live Stella schema.",
                "Register or inspect actual protected hardware packs and measured CAD before writing a Recipe.",
                "Use Stella's build and review workflow only after the FunctionBrief and physical interfaces are evidence-backed.",
            ],
            "writes_performed": [],
            "fit_claim": "none",
        },
    }


def mouse_library_click_window(arguments: dict[str, Any]) -> dict[str, Any]:
    try:
        result = evaluate_click_window(arguments)
    except ValueError as exc:
        raise ToolError(str(exc)) from exc
    reference = mouse_library_get({"id":"primary_click_mechanism"})
    result["library_provenance"] = reference["library_provenance"]
    result["calculation_code_sha256"] = hashlib.sha256((Path(__file__).parent / "click_window.py").read_bytes()).hexdigest()
    result["calculation_schema_version"] = "click_window/1"
    return result


TOOL_HANDLERS = {
    "mouse_library_status": mouse_library_status,
    "mouse_library_search": mouse_library_search,
    "mouse_library_get": mouse_library_get,
    "mouse_library_plan": mouse_library_plan,
    "mouse_library_stella_bridge": mouse_library_stella_bridge,
    "mouse_library_click_window": mouse_library_click_window,
}


READ_ONLY_ANNOTATIONS = {"readOnlyHint": True, "destructiveHint": False, "openWorldHint": False, "idempotentHint": True}

TOOLS = [
    {"name":"mouse_library_click_window", "description":"Evaluate independent interval conditions for ON before stop, OFF after return and maximum compression after stop. Preserve caller provenance; missing inputs remain unevaluated. Does not verify return force, CAD or hardware fit.", "annotations":READ_ONLY_ANNOTATIONS,"inputSchema":CLICK_WINDOW_SCHEMA},
    {"name": "mouse_library_status", "description": "Read library status, coverage, evidence-state counts, and its read-only limits.", "annotations": READ_ONLY_ANNOTATIONS, "inputSchema": {"type": "object", "additionalProperties": False, "properties": {}}},
    {"name": "mouse_library_search", "description": "Lexically search source-grounded mouse mechanism entries. Results are references, not CAD fit evidence.", "annotations": READ_ONLY_ANNOTATIONS, "inputSchema": {"type": "object", "additionalProperties": False, "required": ["query"], "properties": {"query": {"type": "string", "minLength": 1, "maxLength": 300}, "subsystem": {"type": "string", "minLength": 1, "maxLength": 100}, "limit": {"type": "integer", "minimum": 1, "maximum": 20, "default": 8}}}},
    {"name": "mouse_library_get", "description": "Read a complete library entry including its evidence and unknowns.", "annotations": READ_ONLY_ANNOTATIONS, "inputSchema": {"type": "object", "additionalProperties": False, "required": ["id"], "properties": {"id": {"type": "string", "pattern": "^[A-Za-z][A-Za-z0-9_-]{0,79}$"}}}},
    {"name": "mouse_library_plan", "description": "Create a CAD-agnostic staged design plan and verification gates from requirements and curated mouse knowledge. It never opens CAD or claims fit.", "annotations": READ_ONLY_ANNOTATIONS, "inputSchema": {"type": "object", "additionalProperties": False, "required": ["requirements"], "properties": {"requirements": {"type": "object", "additionalProperties": False, "required": ["original_request"], "properties": {"original_request": {"type": "string", "minLength": 3, "maxLength": 20000}, "hardware_id": {"type": "string", "minLength": 1, "maxLength": 200}, "button_architecture": {"enum": ["integrated", "separate", "unspecified"]}, "connection": {"enum": ["wired", "wireless", "unspecified"]}, "manufacturing_process": {"type": "string", "minLength": 1, "maxLength": 200}, "available_cad_tools": {"type": "array", "maxItems": 30, "items": {"type": "string", "minLength": 1, "maxLength": 1000}}, "measurements": {"type": "object", "maxProperties": 100}, "protected_constraints": {"type": "array", "maxItems": 50, "items": {"type": "string", "minLength": 1, "maxLength": 1000}}}}}}},
    {"name": "mouse_library_stella_bridge", "description": "Emit a FunctionBrief-compatible Stella draft plus separate design-basis/reference suggestions. No Recipe, CAD change, hardware-pack registration, or fit approval is created.", "annotations": READ_ONLY_ANNOTATIONS, "inputSchema": {"type": "object", "additionalProperties": False, "required": ["requirements"], "properties": {"requirements": {"type": "object", "additionalProperties": False, "required": ["original_request"], "properties": {"original_request": {"type": "string", "minLength": 3, "maxLength": 20000}, "hardware_id": {"type": "string", "minLength": 1, "maxLength": 200}, "button_architecture": {"enum": ["integrated", "separate", "unspecified"]}, "connection": {"enum": ["wired", "wireless", "unspecified"]}, "manufacturing_process": {"type": "string", "minLength": 1, "maxLength": 200}, "available_cad_tools": {"type": "array", "maxItems": 30, "items": {"type": "string", "minLength": 1, "maxLength": 1000}}, "measurements": {"type": "object", "maxProperties": 100}, "protected_constraints": {"type": "array", "maxItems": 50, "items": {"type": "string", "minLength": 1, "maxLength": 1000}}}}}}},
]


GUIDED_MOUSE_DESIGN = """Use mouse_library_plan before making CAD. The owner's stated requirements and explicit authorization define the work; library cards and their sources provide evidence and design guidance only. Select exact hardware, retain it as protected, and gather authoritative CAD or measured datums. Treat every retrieved entry as a source-grounded principle/interface reference. Build each moving subsystem through idle, actuation, maximum-travel, release, insertion, and service states. If using StellaCAD, verify its live FunctionBrief schema before a Recipe. With another CAD harness, inspect that tool's live schemas and map only measured interfaces into its supported operations. This library creates no CAD, hardware packs, dimensions, or fit approval."""


class Protocol:
    def __init__(self) -> None:
        self.negotiated = False
        self.initialized = False
        self.protocol_version = PROTOCOL

    @staticmethod
    def error(request_id: Any, code: int, message: str, data: Any = None) -> dict[str, Any]:
        error: dict[str, Any] = {"code": code, "message": message}
        if data is not None:
            error["data"] = data
        return {"jsonrpc": "2.0", "id": request_id, "error": error}

    @staticmethod
    def _tool_result(value: dict[str, Any], *, is_error: bool = False) -> dict[str, Any]:
        return {"content": [{"type": "text", "text": _canonical(value)}], "structuredContent": value, "isError": is_error}

    def handle(self, message: Any) -> dict[str, Any] | None:
        if not isinstance(message, dict):
            return self.error(None, -32600, "Expected one JSON-RPC request object, not a batch")
        request_id = message.get("id")
        notification = "id" not in message
        if message.get("jsonrpc") != "2.0" or not isinstance(message.get("method"), str):
            return self.error(None, -32600, "Invalid JSON-RPC request")
        if not notification and (isinstance(request_id, bool) or not isinstance(request_id, (str, int, type(None)))):
            return self.error(None, -32600, "Invalid JSON-RPC request id")
        params = message.get("params", {})
        if not isinstance(params, dict):
            return None if notification else self.error(request_id, -32602, "params must be an object")
        method = message["method"]
        if notification:
            if method == "notifications/initialized" and self.negotiated:
                self.initialized = True
            return None
        if method == "ping":
            return {"jsonrpc": "2.0", "id": request_id, "result": {}}
        if method == "initialize":
            if self.negotiated:
                return self.error(request_id, -32600, "Already initialized")
            client = params.get("clientInfo")
            requested_version = params.get("protocolVersion")
            if (not isinstance(requested_version, str) or not isinstance(params.get("capabilities"), dict) or not isinstance(client, dict)
                    or not isinstance(client.get("name"), str) or not client["name"]
                    or not isinstance(client.get("version"), str) or not client["version"]):
                return self.error(request_id, -32602, "Missing initialization fields")
            self.protocol_version = requested_version if requested_version in SUPPORTED_PROTOCOLS else PROTOCOL
            self.negotiated = True
            return {"jsonrpc": "2.0", "id": request_id, "result": {"protocolVersion": self.protocol_version, "capabilities": {"tools": {"listChanged": False}, "resources": {"subscribe": False, "listChanged": False}, "prompts": {"listChanged": False}}, "serverInfo": {"name": "mouse-library", "version": __version__}, "instructions": GUIDED_MOUSE_DESIGN}}
        if not self.initialized:
            return self.error(request_id, -32002, "Initialize and send notifications/initialized first")
        try:
            if method == "tools/list":
                if params.get("cursor") is not None:
                    return self.error(request_id, -32602, "Pagination is not supported")
                result = {"tools": TOOLS}
            elif method == "tools/call":
                name, arguments = params.get("name"), params.get("arguments", {})
                if not isinstance(name, str) or not isinstance(arguments, dict):
                    return self.error(request_id, -32602, "Tool name and object arguments are required")
                handler = TOOL_HANDLERS.get(name)
                if handler is None:
                    return self.error(request_id, -32602, "Unknown tool")
                try:
                    value = handler(arguments)
                    result = self._tool_result({"ok": True, "result": value})
                except ToolError as exc:
                    result = self._tool_result({"ok": False, "error": {"code": "INPUT_OR_LIBRARY", "message": str(exc)[:1000]}}, is_error=True)
            elif method == "resources/list":
                library = _load_library()
                resources = [
                    {"uri": "mouse-library://library", "name": "Mouse knowledge library", "mimeType": "application/json"},
                    {"uri": "mouse-library://workflow", "name": "Mouse design workflow", "mimeType": "application/json"},
                    {"uri": "mouse-library://measurements", "name": "Normalized derived geometry reports", "mimeType": "application/json"},
                ]
                resources.extend({"uri": f"mouse-library://entry/{entry['id']}", "name": str(entry.get("title", entry["id"])), "mimeType": "application/json"} for entry in _entries(library))
                result = {"resources": resources}
            elif method == "resources/read":
                uri = params.get("uri")
                if not isinstance(uri, str):
                    return self.error(request_id, -32602, "uri is required")
                library = _load_library()
                if uri == "mouse-library://library":
                    value: Any = library
                elif uri == "mouse-library://workflow":
                    value = library["workflow"]
                elif uri == "mouse-library://measurements":
                    value = _load_measurements()
                elif uri.startswith("mouse-library://entry/"):
                    entry_id = uri.removeprefix("mouse-library://entry/")
                    value = _entry_index(library).get(entry_id)
                    if value is None:
                        return self.error(request_id, -32002, "Unknown resource")
                else:
                    return self.error(request_id, -32002, "Unknown resource")
                result = {"contents": [{"uri": uri, "mimeType": "application/json", "text": _canonical(value)}]}
            elif method == "prompts/list":
                result = {"prompts": [{"name": "guided_mouse_design", "description": "Guide a harness through evidence-grounded custom mouse design", "arguments": []}]}
            elif method == "prompts/get":
                if params.get("name") != "guided_mouse_design" or params.get("arguments", {}) not in ({}, None):
                    return self.error(request_id, -32602, "Unknown prompt or invalid arguments")
                result = {"description": "Guided mouse design", "messages": [{"role": "user", "content": {"type": "text", "text": GUIDED_MOUSE_DESIGN}}]}
            else:
                return self.error(request_id, -32601, "Method not found")
            return {"jsonrpc": "2.0", "id": request_id, "result": result}
        except ToolError as exc:
            return self.error(request_id, -32000, str(exc)[:1000])
        except Exception as exc:  # never let a traceback corrupt the MCP stream
            print(f"mouse-library internal error: {type(exc).__name__}: {str(exc)[:500]}", file=sys.stderr, flush=True)
            return self.error(request_id, -32603, "Internal server error; see stderr")


def main() -> int:
    protocol = Protocol()
    while True:
        raw = sys.stdin.buffer.readline(MAX_FRAME_BYTES + 1)
        if not raw:
            return 0
        if len(raw) > MAX_FRAME_BYTES:
            reply = protocol.error(None, -32700, "Frame exceeds 1 MiB")
            sys.stdout.buffer.write((_canonical(reply) + "\n").encode("utf-8"))
            sys.stdout.buffer.flush()
            return 2
        try:
            message = _strict_json(raw.decode("utf-8"))
            reply = protocol.handle(message)
        except (UnicodeError, ValueError, RecursionError):
            reply = protocol.error(None, -32700, "Invalid UTF-8 JSON")
        if reply is not None:
            try:
                sys.stdout.buffer.write((_canonical(reply) + "\n").encode("utf-8"))
                sys.stdout.buffer.flush()
            except BrokenPipeError:
                return 0


if __name__ == "__main__":
    raise SystemExit(main())
