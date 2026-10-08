from __future__ import annotations

import json
import hashlib
from pathlib import Path
import sys
import tempfile
import tomllib
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import select_backend as selector


class BackendSelectionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.project_a = self.root / "project-a"
        self.project_b = self.root / "project-b"
        self.project_a.mkdir()
        self.project_b.mkdir()
        self.kit = self.root / "kit"
        (self.kit / "tools").mkdir(parents=True)
        (self.kit / "runtime").mkdir()
        (self.kit / "runtime" / "downloads").mkdir()
        (self.kit / "tools" / "launch_freecad.py").write_text("pass\n")
        (self.kit / "tools" / "launch_mcp.py").write_text("pass\n")
        freecad = self.kit / "freecad.exe"
        mcp = self.kit / "freecad-mcp.exe"
        freecad.write_text("")
        mcp.write_text("")
        (self.kit / "manifest.json").write_text(
            json.dumps(
                {
                    "kit_version": "1.0.0",
                    "freecad_target": "1.1.4",
                    "mcp": {
                        "repository": "neka-nat/freecad-mcp",
                        "commit": selector.FREECAD_MCP_COMMIT,
                    },
                }
            )
        )
        archive = self.kit / "runtime" / "downloads" / (
            f"mcp-{selector.FREECAD_MCP_COMMIT}.zip"
        )
        archive.write_bytes(b"pinned synthetic fixture")
        (self.kit / "runtime" / "sources.lock.json").write_text(
            json.dumps(
                {
                    "mcp": {
                        "repository": "neka-nat/freecad-mcp",
                        "commit": selector.FREECAD_MCP_COMMIT,
                        "archive_sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
                    }
                }
            )
        )
        (self.kit / "runtime" / "config.json").write_text(
            json.dumps(
                {
                    "root": str(self.kit),
                    "profile": str(self.kit / "runtime" / "profile"),
                    "freecad_exe": str(freecad),
                    "mcp_exe": str(mcp),
                    "python_exe": sys.executable,
                }
            )
        )

    def tearDown(self) -> None:
        self.temp.cleanup()

    @mock.patch.object(selector, "_port_is_open", return_value=False)
    def test_selection_is_project_local_and_does_not_launch(self, _port) -> None:
        with mock.patch.object(selector.subprocess, "run") as run:
            result = selector.select_backend(self.project_a, "freecad", self.kit)
        self.assertEqual(result["selection"]["backend"], "freecad")
        self.assertTrue(result["reload_required"])
        self.assertTrue((self.project_a / selector.STATE_RELATIVE_PATH).is_file())
        self.assertFalse((self.project_b / selector.STATE_RELATIVE_PATH).exists())
        run.assert_not_called()

    @mock.patch.object(selector, "_port_is_open", return_value=False)
    def test_different_projects_keep_independent_backends(self, _port) -> None:
        selector.select_backend(self.project_a, "freecad", self.kit)
        selector.select_backend(self.project_b, "fusion")
        self.assertEqual(selector.read_selection(self.project_a)["backend"], "freecad")
        self.assertEqual(selector.read_selection(self.project_b)["backend"], "fusion")

    def test_switch_updates_only_project_writer_enable_flags(self) -> None:
        config = self.project_a / ".codex" / "config.toml"
        config.parent.mkdir()
        original = """model = "keep-me"

[mcp_servers.cadmcp-design-brain]
enabled = true
command = "brain"

[mcp_servers.unrelated]
enabled = true # preserve
command = "unrelated"

[mcp_servers.stella_freecad_mouse_b]
enabled = false
command = "freecad"

[mcp_servers.classcad]
enabled = false
command = "classcad"
"""
        config.write_text(original, encoding="utf-8")

        first = selector.select_backend(self.project_a, "freecad", self.kit)
        parsed = tomllib.loads(config.read_text(encoding="utf-8"))
        servers = parsed["mcp_servers"]
        self.assertTrue(servers["stella_freecad_mouse_b"]["enabled"])
        self.assertFalse(servers["classcad"]["enabled"])
        self.assertFalse(servers["stella-fusion-community"]["enabled"])
        self.assertFalse(servers["fusion"]["enabled"])
        self.assertTrue(servers["cadmcp-design-brain"]["enabled"])
        self.assertEqual(servers["unrelated"]["command"], "unrelated")
        self.assertTrue(first["reload_required"])
        backup = config.with_name("config.toml.before-cad-selection")
        self.assertEqual(backup.read_text(encoding="utf-8"), original)

        second = selector.select_backend(self.project_a, "classcad")
        parsed = tomllib.loads(config.read_text(encoding="utf-8"))
        servers = parsed["mcp_servers"]
        self.assertFalse(servers["stella_freecad_mouse_b"]["enabled"])
        self.assertTrue(servers["classcad"]["enabled"])
        self.assertFalse(servers["stella-fusion-community"]["enabled"])
        self.assertFalse(servers["fusion"]["enabled"])
        self.assertTrue(servers["cadmcp-design-brain"]["enabled"])
        self.assertTrue(servers["unrelated"]["enabled"])
        self.assertEqual(backup.read_text(encoding="utf-8"), original)
        self.assertEqual(second["selection"]["backend"], "classcad")

    def test_failed_second_selection_restores_immediately_previous_config(self) -> None:
        selector.select_backend(self.project_a, "freecad", self.kit)
        config = self.project_a / ".codex" / "config.toml"
        before_second_selection = config.read_bytes()
        with mock.patch.object(
            selector, "_write_json_atomic", side_effect=OSError("synthetic state failure")
        ):
            with self.assertRaises(OSError):
                selector.select_backend(self.project_a, "classcad")
        self.assertEqual(config.read_bytes(), before_second_selection)
        self.assertEqual(selector.read_selection(self.project_a)["backend"], "freecad")

    def test_unapproved_freecad_commit_is_rejected(self) -> None:
        manifest = json.loads((self.kit / "manifest.json").read_text())
        manifest["mcp"]["commit"] = "b" * 40
        (self.kit / "manifest.json").write_text(json.dumps(manifest))
        with self.assertRaisesRegex(selector.SelectionError, "commit is not approved"):
            selector.select_backend(self.project_a, "freecad", self.kit)
        self.assertFalse((self.project_a / selector.STATE_RELATIVE_PATH).exists())

    def test_parallel_selection_lock_refuses_second_writer(self) -> None:
        with selector._exclusive_selection_lock(self.project_a):
            with self.assertRaisesRegex(selector.SelectionError, "already updating"):
                selector.select_backend(self.project_a, "fusion")

    def test_freecad_requires_kit_and_other_backends_reject_it(self) -> None:
        with self.assertRaises(selector.SelectionError):
            selector.select_backend(self.project_a, "freecad")
        with self.assertRaises(selector.SelectionError):
            selector.select_backend(self.project_a, "classcad", self.kit)

    def test_tampered_project_identity_is_rejected(self) -> None:
        selector.select_backend(self.project_a, "fusion")
        state_file = self.project_a / selector.STATE_RELATIVE_PATH
        state = json.loads(state_file.read_text())
        state["project_root"] = str(self.project_b)
        state_file.write_text(json.dumps(state))
        with self.assertRaises(selector.SelectionError):
            selector.read_selection(self.project_a)

    def test_prepare_without_selection_never_launches(self) -> None:
        with mock.patch.object(selector.subprocess, "run") as run:
            with self.assertRaises(selector.SelectionError):
                selector.prepare(self.project_a)
        run.assert_not_called()

    def test_prepare_non_freecad_returns_dispatch_without_launch(self) -> None:
        selector.select_backend(self.project_a, "classcad")
        with mock.patch.object(selector.subprocess, "run") as run:
            result = selector.prepare(self.project_a)
        self.assertEqual(result["action"], "NO_ACTION")
        self.assertEqual(result["backend"], "classcad")
        run.assert_not_called()

    @mock.patch.object(selector, "_port_is_open", return_value=False)
    def test_prepare_launches_only_the_selected_existing_kit(self, _port) -> None:
        selector.select_backend(self.project_a, "freecad", self.kit)
        before = {
            "ready": False,
            "runtime": {"pid_running": False, "rpc_open": False},
        }
        after = {
            "ready": True,
            "runtime": {"rpc_open": True},
        }
        completed = mock.Mock(returncode=0, stdout="ready", stderr="")
        with (
            mock.patch.object(selector, "inspect_freecad_kit", side_effect=[before, after]),
            mock.patch.object(selector.subprocess, "run", return_value=completed) as run,
        ):
            result = selector.prepare(self.project_a)
        self.assertEqual(result["action"], "LAUNCHED_EXISTING_KIT")
        command = run.call_args.args[0]
        self.assertEqual(Path(command[1]), self.kit / "tools" / "launch_freecad.py")
        self.assertEqual(run.call_args.kwargs["cwd"], self.kit)

    @mock.patch.object(selector, "_port_is_open", return_value=True)
    @mock.patch.object(selector, "_pid_is_running", return_value=True)
    def test_matching_live_freecad_is_reused_without_launch(self, _pid, _port) -> None:
        (self.kit / "runtime" / "gui.pid").write_text("1234")
        (self.kit / "runtime" / "ready.json").write_text(
            json.dumps(
                {
                    "root": str(self.kit),
                    "profile": str(self.kit / "runtime" / "profile"),
                    "pid": 1234,
                    "status": "READY",
                }
            )
        )
        selector.select_backend(self.project_a, "freecad", self.kit)
        with (
            mock.patch.object(selector, "_process_executable", return_value=self.kit / "freecad.exe"),
            mock.patch.object(selector.subprocess, "run") as run,
        ):
            result = selector.prepare(self.project_a)
        self.assertEqual(result["action"], "REUSED_RUNNING_GUI")
        run.assert_not_called()

    @mock.patch.object(selector, "_port_is_open", return_value=True)
    @mock.patch.object(selector, "_pid_is_running", return_value=False)
    def test_stale_ready_with_occupied_port_refuses_launch(self, _pid, _port) -> None:
        (self.kit / "runtime" / "ready.json").write_text(
            json.dumps(
                {
                    "root": str(self.kit),
                    "profile": str(self.kit / "runtime" / "profile"),
                    "pid": 9999,
                    "status": "READY",
                }
            )
        )
        selector.select_backend(self.project_a, "freecad", self.kit)
        with mock.patch.object(selector.subprocess, "run") as run:
            with self.assertRaises(selector.SelectionError):
                selector.prepare(self.project_a)
        run.assert_not_called()

    @mock.patch.object(selector, "_port_is_open", return_value=False)
    @mock.patch.object(selector, "_pid_is_running", return_value=True)
    def test_live_gui_without_rpc_refuses_duplicate_launch(self, _pid, _port) -> None:
        (self.kit / "runtime" / "gui.pid").write_text("1234")
        (self.kit / "runtime" / "ready.json").write_text(
            json.dumps(
                {
                    "root": str(self.kit),
                    "profile": str(self.kit / "runtime" / "profile"),
                    "pid": 1234,
                    "status": "READY",
                }
            )
        )
        selector.select_backend(self.project_a, "freecad", self.kit)
        with (
            mock.patch.object(
                selector, "_process_executable", return_value=self.kit / "freecad.exe"
            ),
            mock.patch.object(selector.subprocess, "run") as run,
        ):
            with self.assertRaisesRegex(selector.SelectionError, "No second GUI"):
                selector.prepare(self.project_a)
        run.assert_not_called()

    @mock.patch.object(selector, "_port_is_open", return_value=True)
    @mock.patch.object(selector, "_pid_is_running", return_value=True)
    def test_live_status_checks_profile_identity(self, _pid, _port) -> None:
        (self.kit / "runtime" / "gui.pid").write_text("1234")
        (self.kit / "runtime" / "ready.json").write_text(
            json.dumps(
                {
                    "root": str(self.kit),
                    "profile": str(self.root / "wrong-profile"),
                    "pid": 1234,
                    "status": "READY",
                }
            )
        )
        with mock.patch.object(
            selector, "_process_executable", return_value=self.kit / "freecad.exe"
        ):
            report = selector.inspect_freecad_kit(self.kit)
        self.assertFalse(report["ready"])
        self.assertFalse(report["runtime"]["profile_matches"])

    def test_project_state_directory_may_not_escape_project(self) -> None:
        outside = self.root / "outside"
        outside.mkdir()
        try:
            (self.project_a / ".stella").symlink_to(outside, target_is_directory=True)
        except OSError:
            self.skipTest("Directory symlinks are not permitted")
        with self.assertRaises(selector.SelectionError):
            selector.select_backend(self.project_a, "fusion")


if __name__ == "__main__":
    unittest.main(verbosity=2)
