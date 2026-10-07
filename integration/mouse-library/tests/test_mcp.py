"""Bounded acceptance checks authorized by the owner; no CAD/project writes."""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

PACKAGE = Path(__file__).resolve().parents[1]
REPO = PACKAGE.parents[1]
STELLA = REPO / "cadmcp-all-in-one-2026-09-17" / "01_CURRENT"
sys.path.insert(0, str(PACKAGE))
sys.path.insert(0, str(STELLA))

REQUEST = "G305の電子部品を使い、\n独立した左右ボタンとサイドボタンを持つ小型マウスを設計したい。"
REQUIREMENTS = {
    "original_request": REQUEST,
    "hardware_id": "G305 reference only; owner revision unknown",
    "button_architecture": "separate",
    "connection": "wireless",
    "manufacturing_process": "FDM prototype; material unknown",
    "available_cad_tools": ["ClassCAD MCP"],
    "measurements": {"example_height": {"value": 10, "unit": "mm"}},
    "protected_constraints": ["Do not scale the selected existing hardware."],
}


def session(calls, *, stella_workspace=None, version="2025-11-25", cwd=PACKAGE):
    frames = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
            "protocolVersion": version, "capabilities": {},
            "clientInfo": {"name": "mouse-library-acceptance", "version": "0.1.0"}}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
    ]
    frames.extend({"jsonrpc": "2.0", "id": i + 2, "method": method, "params": params}
                  for i, (method, params) in enumerate(calls))
    env = os.environ.copy()
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    env.pop("PYTHONPATH", None)
    if stella_workspace is None:
        command = [sys.executable, "-m", "mouse_library"]
    else:
        command = [sys.executable, "-m", "cadmcp_brain", "--workspace", str(stella_workspace), "serve"]
        env["PYTHONPATH"] = str(PACKAGE)
        cwd = STELLA
    completed = subprocess.run(command, cwd=cwd, env=env,
                               input="".join(json.dumps(frame, ensure_ascii=False) + "\n" for frame in frames),
                               capture_output=True, text=True, encoding="utf-8", timeout=30)
    if completed.returncode:
        raise RuntimeError(f"MCP exit {completed.returncode}: {completed.stderr[:2000]}")
    responses = [json.loads(line) for line in completed.stdout.splitlines()]
    return responses, completed.stderr


def tool(name, arguments=None):
    return ("tools/call", {"name": name, "arguments": arguments or {}})


def value(reply):
    result = reply["result"]
    if result.get("isError"):
        raise RuntimeError(result["structuredContent"])
    return result["structuredContent"]["result"]


class MouseLibraryAcceptance(unittest.TestCase):
    def test_mount_patterns_do_not_become_fit_or_stroke(self):
        replies, _ = session([("resources/read", {"uri":"mouse-library://measurements"}), tool("mouse_library_get", {"id":"primary_click_mechanism"})])
        reports = {r["id"]:r["report"] for r in json.loads(replies[1]["result"]["contents"][0]["text"])["reports"]}
        old = reports["zs_f1_g305_primary_click_mount_pattern"]
        updated = reports["zs_f1_g305_updated_primary_click_mount_pattern"]
        self.assertEqual(old["bottom_sha256"], updated["bottom_sha256"])
        self.assertEqual(old["status"], "reference_pattern_mismatch_not_fit_verified")
        for side in old["sides"]:
            self.assertEqual(len(side["pair_candidates"]), 6)
            self.assertEqual(side["best_pair_count"], 2)
            self.assertAlmostEqual(side["pair_candidates"][0]["distance_mismatch_under_unit_scale"], .5, places=4)
            self.assertIn("Theoretical lower bound", side["residual_scope"])
        self.assertTrue(any("0.55mm" in e["claim"] and "ストロークではない" in e["claim"] for e in value(replies[2])["entry"]["evidence"]))

    def test_primary_click_contract_and_separate_boards(self):
        replies, _ = session([tool("mouse_library_get", {"id":"primary_click_mechanism"}),
                              ("resources/read", {"uri":"mouse-library://measurements"})])
        card=value(replies[1])["entry"]
        self.assertEqual(card["state_contract"]["status"],"symbolic_requirements_not_verified")
        self.assertEqual(len(card["concept_portfolio"]),3)
        self.assertTrue(any("OT" in s for s in card["principles"]))
        reports=json.loads(replies[2]["result"]["contents"][0]["text"])["reports"]
        left=next(r["report"] for r in reports if r["id"]=="g305_left_switch_board_reference")
        right=next(r["report"] for r in reports if r["id"]=="g305_right_switch_board_reference")
        self.assertNotEqual(left["shapes"][1]["extent"],right["shapes"][1]["extent"])
        self.assertEqual(left["source"],"G305_SWL_PCB.step")
        normal=next(r["report"] for r in reports if r["id"]=="zs_f1_g305_click_normal_chords")
        self.assertEqual(len(normal["samples"]),84)
        self.assertIn("force, return, travel or fatigue",normal["not_verified"])

    def test_stdio_catalog_and_provenance(self):
        replies, stderr = session([("tools/list", {}), tool("mouse_library_status")])
        self.assertEqual(len(replies), 3)
        self.assertEqual(replies[0]["result"]["serverInfo"]["name"], "mouse-library")
        names = {x["name"] for x in replies[1]["result"]["tools"]}
        self.assertEqual(len(names), 6)
        self.assertTrue(all(x["annotations"]["readOnlyHint"] for x in replies[1]["result"]["tools"]))
        status = value(replies[2])
        self.assertEqual(status["entry_count"], 12)
        self.assertEqual(len(status["library_provenance"]["content_sha256"]), 64)
        self.assertEqual(stderr, "")

    def test_japanese_and_english_retrieval(self):
        replies, _ = session([tool("mouse_library_search", {"query": "ホイールの構造"}),
                              tool("mouse_library_search", {"query": "wheel encoder", "subsystem": "scroll_input"}),
                              tool("mouse_library_get", {"id": "wheel_rotation_and_click"})])
        self.assertIn("wheel_rotation_and_click", {x["id"] for x in value(replies[1])["results"]})
        self.assertEqual(value(replies[2])["results"][0]["id"], "wheel_rotation_and_click")
        card = value(replies[3])
        self.assertTrue(card["entry"]["unknowns"])
        self.assertTrue(card["library_provenance"]["sources"])

    def test_plan_keeps_unknowns_and_measurement_status(self):
        replies, _ = session([tool("mouse_library_plan", {"requirements": REQUIREMENTS})])
        plan = value(replies[1])
        self.assertTrue(plan["required_hardware_facts"])
        self.assertEqual(plan["provided_measurements"][0]["status"], "user_provided_unvalidated")
        self.assertEqual(len(plan["workflow"]["stages"]), 6)
        self.assertIn("measurement_record_template", plan["workflow"])
        self.assertIn("outer_shell_scan",plan["workflow"]["generic_input_contract"]["asset_roles"])
        self.assertIn("independent check features and residuals",plan["workflow"]["generic_input_contract"]["registration_evidence_required"])
        self.assertEqual(plan["cad_tool_capability_status"]["reported_tools"][0]["capabilities"], "unverified")
        self.assertIn("side_button_mechanism", {x["id"] for x in plan["inferred_product_function_entries"]})
        self.assertIn("zs_f1_g305_case", {x["id"] for x in plan["planning_guidance_entries"]})
        self.assertNotIn("zs_f1_g305_case", {x["id"] for x in plan["inferred_product_function_entries"]})
        generic = {"original_request":"任意の採用基板と外側スキャンからクリックとホイールを持つマウスを設計したい。", "hardware_id":"CustomPCB-B; revision unmeasured"}
        replies, _ = session([tool("mouse_library_plan", {"requirements":generic})])
        generic_plan=value(replies[1])
        self.assertNotIn("zs_f1_g305_case", {x["id"] for x in generic_plan["planning_guidance_entries"]})
        self.assertEqual(generic_plan["provided_measurements"], [])
        self.assertIn("pcb_scan",generic_plan["workflow"]["generic_input_contract"]["asset_roles"])
        contract=generic_plan["workflow"]["generic_input_contract"]
        self.assertIn("Zero interference alone",contract["intake_readiness_rule"])
        self.assertIn("Empty switches metadata",contract["functional_interface_rule"])
        self.assertIn("not a manufacturer optical datum",contract["functional_interface_rule"])

    def test_bridge_matches_stella_models(self):
        from cadmcp_brain.studio.synthesis import FunctionBrief, FirstPrinciplesBasis
        from cadmcp_brain.studio.recipe import DesignBasis
        replies, _ = session([tool("mouse_library_stella_bridge", {"requirements": REQUIREMENTS})])
        bridge = value(replies[1])
        brief = FunctionBrief.model_validate(bridge["function_brief"])
        DesignBasis.model_validate(bridge["recipe_design_basis"])
        FirstPrinciplesBasis.model_validate(bridge["concept_design_basis"])
        self.assertEqual(brief.original_request, REQUEST)
        self.assertEqual(bridge["recipe_reference_uses"], [])
        self.assertIsInstance(bridge["library_provenance"], dict)
        self.assertTrue(bridge["knowledge_uses"])
        self.assertTrue(bridge["function_brief_annotation"]["inferred_function_ids"])

    def test_wired_power_and_cable_guidance_is_included(self):
        requirements = {"original_request": "小型マウスを設計したい。", "connection": "wired"}
        replies, _ = session([tool("mouse_library_plan", {"requirements": requirements})])
        entries = value(replies[1])["inferred_product_function_entries"]
        self.assertIn("power_wiring_and_service", {x["id"] for x in entries})

    def test_click_chords_remain_reference_measurements(self):
        replies, _ = session([tool("mouse_library_get", {"id": "primary_click_mechanism"}),
                              ("resources/read", {"uri": "mouse-library://measurements"})])
        entry = value(replies[1])["entry"]
        self.assertTrue(any("鉛直" in principle for principle in entry["principles"]))
        reports = json.loads(replies[2]["result"]["contents"][0]["text"])["reports"]
        report = next(row["report"] for row in reports if row["id"] == "zs_f1_g305_click_chords")
        self.assertEqual(len(report["samples"]), 84)
        self.assertIn("normal wall thickness", report["not_verified"])
        self.assertEqual(report["units"], "unspecified STL coordinate units")

    def test_resources_and_prompt(self):
        replies, _ = session([("resources/list", {}),
                              ("resources/read", {"uri": "mouse-library://workflow"}),
                              ("prompts/get", {"name": "guided_mouse_design"}),
                              ("resources/read", {"uri": "mouse-library://measurements"})])
        self.assertEqual(len(replies[1]["result"]["resources"]), 15)
        workflow = json.loads(replies[2]["result"]["contents"][0]["text"])
        self.assertIn("measurement_record_template", workflow)
        self.assertIn("messages", replies[3]["result"])
        measurements = json.loads(replies[4]["result"]["contents"][0]["text"])
        self.assertEqual(len(measurements["reports"]), 11)

    def test_bad_inputs_are_bounded_errors(self):
        replies, _ = session([tool("mouse_library_get", {"id": "../file"}),
                              tool("mouse_library_search", {"query": "wheel", "limit": True}),
                              tool("mouse_library_plan", {"requirements": {"original_request": "mouse", "invent": 3}}),
                              ("resources/read", {"uri": "file:///sensitive"})])
        for reply in replies[1:4]:
            self.assertTrue(reply["result"]["isError"])
        self.assertIn("error", replies[4])

    def test_protocol_version_negotiation(self):
        replies, _ = session([tool("mouse_library_status")], version="2025-06-18")
        self.assertEqual(replies[0]["result"]["protocolVersion"], "2025-06-18")
        self.assertEqual(value(replies[1])["entry_count"], 12)

    def test_native_stella_wire_link(self):
        with tempfile.TemporaryDirectory(prefix="stella-mouse-library-") as tmp:
            replies, _ = session([("tools/list", {}), tool("brain_mouse_knowledge_status"),
                                  tool("brain_mouse_knowledge_search", {"query": "ホイール"}),
                                  tool("brain_mouse_knowledge_get", {"record_id": "wheel_rotation_and_click"}),
                                  tool("brain_mouse_knowledge_plan", {"requirements": REQUIREMENTS}),
                                  tool("brain_mouse_knowledge_brief", {"requirements": REQUIREMENTS}),
                                  tool("brain_mouse_knowledge_schema", {"name": "requirements"})],
                                 stella_workspace=tmp)
        names = {x["name"] for x in replies[1]["result"]["tools"]}
        self.assertEqual(len([x for x in names if x.startswith("brain_mouse_knowledge_")]), 7)
        self.assertEqual(value(replies[2])["entry_count"], 12)
        for reply in replies[3:]:
            self.assertTrue(value(reply))
        self.assertTrue(value(replies[-2])["native_schema_validation"]["passed"])
        self.assertIn("original_request", value(replies[-1])["schema"]["required"])
        self.assertEqual(value(replies[-1])["library"]["schema_version"], "1.0")
        self.assertEqual(value(replies[-1])["library"]["library_version"], "0.1.4")

    def test_portable_copy_has_no_stella_dependency(self):
        with tempfile.TemporaryDirectory(prefix="portable-mouse-library-") as tmp:
            destination = Path(tmp)
            shutil.copytree(PACKAGE / "mouse_library", destination / "mouse_library",
                            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
            replies, _ = session([tool("mouse_library_status"),
                                  ("resources/read", {"uri": "mouse-library://measurements"})], cwd=destination)
            self.assertEqual(value(replies[1])["entry_count"], 12)
            self.assertEqual(len(json.loads(replies[2]["result"]["contents"][0]["text"])["reports"]), 11)


if __name__ == "__main__":
    unittest.main()
