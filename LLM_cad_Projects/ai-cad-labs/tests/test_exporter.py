"""Tests for tools.exporter — part.py execution + STEP/STL export, CLI contract."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT))

from tools.exporter import export_part  # noqa: E402

BOX_CODE = """
import cadquery as cq
result = cq.Workplane("XY").box(10, 10, 10)
"""


def _make_part(tmp_path: Path, name: str = "bracket", code: str = BOX_CODE) -> Path:
    part_dir = tmp_path / name
    part_dir.mkdir()
    (part_dir / "part.py").write_text(code)
    return part_dir


def test_export_step_and_stl(tmp_path):
    part_dir = _make_part(tmp_path)
    out = export_part(str(part_dir))
    assert set(out.keys()) == {"success", "paths", "error_message"}
    assert out["success"] is True
    assert out["error_message"] is None
    for fmt in ("step", "stl"):
        exported = Path(out["paths"][fmt])
        assert exported == part_dir / "exports" / f"bracket.{fmt}"
        assert exported.exists()
        assert exported.stat().st_size > 0


def test_export_single_format(tmp_path):
    part_dir = _make_part(tmp_path)
    out = export_part(str(part_dir), formats="step")
    assert out["success"] is True
    assert list(out["paths"].keys()) == ["step"]


def test_export_missing_part_py(tmp_path):
    part_dir = tmp_path / "empty"
    part_dir.mkdir()
    out = export_part(str(part_dir))
    assert out["success"] is False
    assert "No part.py found" in out["error_message"]
    assert out["paths"] == {}


def test_export_unknown_format(tmp_path):
    part_dir = _make_part(tmp_path)
    out = export_part(str(part_dir), formats="obj")
    assert out["success"] is False
    assert "Unknown format 'obj'" in out["error_message"]
    assert out["paths"] == {}


def test_export_failing_part(tmp_path):
    part_dir = _make_part(tmp_path, code="raise ValueError('bad geometry')")
    out = export_part(str(part_dir))
    assert out["success"] is False
    assert "failed to execute" in out["error_message"]
    assert "bad geometry" in out["error_message"]


def test_export_project_relative_part_path(tmp_path):
    """With --project-path, a relative part path resolves via safe_path."""
    proj = tmp_path / "projX"
    (proj / "assembly").mkdir(parents=True)
    _make_part(proj / "assembly", name="gear")
    out = export_part("assembly/gear", formats="step", project_path=str(proj))
    assert out["success"] is True
    assert (proj / "assembly" / "gear" / "exports" / "gear.step").exists()


def test_export_traversal_blocked(tmp_path):
    with pytest.raises(ValueError, match="escapes project directory"):
        export_part("../outside", project_path=str(tmp_path))


def test_cli_exporter_json(tmp_path):
    part_dir = _make_part(tmp_path)
    proc = subprocess.run(
        [sys.executable, "-m", "tools.exporter",
         "--part-path", str(part_dir), "--formats", "step,stl"],
        cwd=REPO_ROOT, capture_output=True, text=True, timeout=120,
    )
    assert proc.returncode == 0, proc.stderr
    data = json.loads(proc.stdout)
    assert set(data.keys()) == {"success", "paths", "error_message"}
    assert data["success"] is True
    assert Path(data["paths"]["step"]).exists()
    assert Path(data["paths"]["stl"]).exists()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
