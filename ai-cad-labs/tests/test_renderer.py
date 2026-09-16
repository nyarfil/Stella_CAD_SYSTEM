"""Smoke tests for tools.renderer — the 8-PNG contract, naming, JSON shape,
no-collage invariant, colored assembly mode + legend, and mono fallback.

Runs the real CLI (subprocess, cwd=repo root) against real CadQuery geometry,
so these tests exercise the DYLD/cairosvg import path too. Fixtures render
once per module; individual tests assert on the shared outputs.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

EXPECTED_PNG_NAMES = {
    f"{view}_{style}.png"
    for view in ("front", "top", "right", "iso")
    for style in ("clean", "wireframe")
}

BOX_PART = """\
import cadquery as cq
result = cq.Workplane("XY").box(80, 40, 20, centered=(True, True, False))
"""

CONSTRAINTS = """\
# Constraints — box_part
Overall: 80 x 40 x 20 mm (L x W x H)
"""

TWO_BOX_ASSEMBLY = """\
import cadquery as cq

base = cq.Workplane("XY").box(60, 60, 10, centered=(True, True, False))
tower = cq.Workplane("XY").box(20, 20, 30, centered=(True, True, False))

assy = cq.Assembly()
assy.add(base, name="base_plate")
assy.add(tower, name="tower", loc=cq.Location(cq.Vector(0, 0, 10)))
result = assy
"""

# Plain Workplane union — no cq.Assembly in the namespace, so colored
# extraction is impossible and the renderer must fall back to monochrome.
UNION_ASSEMBLY = """\
import cadquery as cq

base = cq.Workplane("XY").box(60, 60, 10, centered=(True, True, False))
tower = cq.Workplane("XY").box(20, 20, 30, centered=(True, True, False)).translate((0, 0, 10))
result = base.union(tower)
"""


def run_renderer(*flags: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "tools.renderer", *flags],
        cwd=REPO_ROOT, capture_output=True, text=True, timeout=300,
    )


@pytest.fixture(scope="module")
def views_run(tmp_path_factory) -> tuple[Path, subprocess.CompletedProcess]:
    part_dir = tmp_path_factory.mktemp("proj") / "assembly" / "box_part"
    part_dir.mkdir(parents=True)
    (part_dir / "part.py").write_text(BOX_PART)
    (part_dir / "constraints.md").write_text(CONSTRAINTS)
    proc = run_renderer("--mode=views", "--part-path", str(part_dir))
    return part_dir, proc


@pytest.fixture(scope="module")
def assembly_run(tmp_path_factory) -> tuple[Path, subprocess.CompletedProcess]:
    project_dir = tmp_path_factory.mktemp("asmproj")
    assembly_dir = project_dir / "assembly"
    assembly_dir.mkdir()
    (assembly_dir / "assembly.py").write_text(TWO_BOX_ASSEMBLY)
    proc = run_renderer("--mode=assembly", "--project", str(project_dir))
    return project_dir, proc


# ---------------------------------------------------------------- views mode

def test_views_exit_zero_and_json_shape(views_run):
    _, proc = views_run
    assert proc.returncode == 0, proc.stderr
    out = json.loads(proc.stdout)  # stdout must be a single valid JSON object
    assert set(out) == {"success", "png_paths", "legend",
                        "dimension_check", "error_message"}
    assert out["success"] is True
    assert out["error_message"] is None
    assert out["legend"] is None  # views mode never has a legend


def test_views_produces_exactly_8_pngs(views_run):
    part_dir, proc = views_run
    out = json.loads(proc.stdout)
    assert len(out["png_paths"]) == 8
    for p in out["png_paths"]:
        png = Path(p)
        assert png.exists() and png.stat().st_size > 0, f"missing/empty: {p}"


def test_views_naming_contract(views_run):
    _, proc = views_run
    out = json.loads(proc.stdout)
    names = {Path(p).name for p in out["png_paths"]}
    assert names == EXPECTED_PNG_NAMES


def test_views_no_composite(views_run):
    """No-collage invariant: the renders dir holds ONLY the 8 individual PNGs."""
    part_dir, _ = views_run
    renders = part_dir / "renders"
    actual = {p.name for p in renders.iterdir()}
    assert actual == EXPECTED_PNG_NAMES


def test_views_dimension_check_runs_and_passes(views_run):
    _, proc = views_run
    check = json.loads(proc.stdout)["dimension_check"]
    assert check is not None
    assert check["pass"] is True
    assert check["expected"] == [20.0, 40.0, 80.0]
    assert check["actual"] == [20.0, 40.0, 80.0]
    assert check["deviations"] == []


def test_views_missing_part_is_artifact_failure_exit_zero(tmp_path):
    """Artifact failure => exit 0 with success=false (JSON carries the verdict)."""
    proc = run_renderer("--mode=views", "--part-path", str(tmp_path))
    assert proc.returncode == 0
    out = json.loads(proc.stdout)
    assert out["success"] is False
    assert out["png_paths"] == []
    assert "part.py" in out["error_message"]


def test_views_code_file_renders_proposal(tmp_path):
    """--code-file renders part.proposal.py instead of part.py; PNGs still land in <part>/renders/."""
    part_dir = tmp_path / "assembly" / "box_part"
    part_dir.mkdir(parents=True)
    # Poisoned stable file: if the renderer ignored --code-file, this would blow up.
    (part_dir / "part.py").write_text("raise RuntimeError('stable part.py must not be executed')\n")
    (part_dir / "part.proposal.py").write_text(BOX_PART)
    proc = run_renderer("--mode=views", "--part-path", str(part_dir),
                        "--code-file", str(part_dir / "part.proposal.py"))
    assert proc.returncode == 0
    out = json.loads(proc.stdout)
    assert out["success"] is True
    assert len(out["png_paths"]) == 8
    assert {p.name for p in (part_dir / "renders").glob("*.png")} == EXPECTED_PNG_NAMES


# ------------------------------------------------------------- assembly mode

def test_assembly_exit_zero_8_pngs(assembly_run):
    project_dir, proc = assembly_run
    assert proc.returncode == 0, proc.stderr
    out = json.loads(proc.stdout)
    assert out["success"] is True
    assert len(out["png_paths"]) == 8
    names = {Path(p).name for p in out["png_paths"]}
    assert names == EXPECTED_PNG_NAMES
    for p in out["png_paths"]:
        assert Path(p).stat().st_size > 0


def test_assembly_colored_legend(assembly_run):
    """Per-part colors follow the fixed palette order; legend file written."""
    project_dir, proc = assembly_run
    out = json.loads(proc.stdout)
    legend = out["legend"]
    assert legend is not None
    assert set(legend) == {"base_plate", "tower"}
    assert legend["base_plate"] == {"color": "red", "rgb": [220, 40, 40]}
    assert legend["tower"] == {"color": "blue", "rgb": [40, 40, 220]}

    legend_file = project_dir / "assembly" / "renders" / "color_legend.txt"
    assert legend_file.exists()
    text = legend_file.read_text()
    assert "base_plate" in text and "red" in text
    assert "tower" in text and "blue" in text


def test_assembly_no_composite(assembly_run):
    """Renders dir = 8 PNGs + color_legend.txt, nothing else (no collage)."""
    project_dir, _ = assembly_run
    renders = project_dir / "assembly" / "renders"
    actual = {p.name for p in renders.iterdir()}
    assert actual == EXPECTED_PNG_NAMES | {"color_legend.txt"}


def test_assembly_wireframe_differs_from_clean(assembly_run):
    """Wireframe (X-ray, hidden lines dashed+lighter) must not equal clean."""
    project_dir, _ = assembly_run
    renders = project_dir / "assembly" / "renders"
    wire = (renders / "iso_wireframe.png").read_bytes()
    clean = (renders / "iso_clean.png").read_bytes()
    assert wire != clean


def test_assembly_mono_fallback_without_assembly_object(tmp_path):
    """No cq.Assembly in the namespace => monochrome fallback, legend=null."""
    assembly_dir = tmp_path / "assembly"
    assembly_dir.mkdir()
    (assembly_dir / "assembly.py").write_text(UNION_ASSEMBLY)
    proc = run_renderer("--mode=assembly", "--project", str(tmp_path))
    assert proc.returncode == 0, proc.stderr
    out = json.loads(proc.stdout)
    assert out["success"] is True
    assert len(out["png_paths"]) == 8
    assert out["legend"] is None
    assert not (assembly_dir / "renders" / "color_legend.txt").exists()
