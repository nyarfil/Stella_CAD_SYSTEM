"""brain_mouse_assembly_swap on synthetic labelled assemblies (module function through the worker subprocess). Needs OCP."""
from __future__ import annotations
import pytest
from cadmcp_brain.errors import BrainError
from cadmcp_brain.studio import mouse_assembly_swap as MS

pytest.importorskip('OCP')
from cadmcp_brain.studio import cad_brep_lib as L  # noqa: E402
from cadmcp_brain.studio import mouse_assembly_swap_worker as W  # noqa: E402


def box(x0, y0, z0, x1, y1, z1):
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox
    from OCP.gp import gp_Pnt
    return L.solids(BRepPrimAPI_MakeBox(gp_Pnt(x0, y0, z0), gp_Pnt(x1, y1, z1)).Shape())[0]


def rejects(code, fn):
    with pytest.raises(BrainError) as exc:
        fn()
    assert exc.value.code == code


@pytest.fixture()
def ws(tmp_path):
    red, grey, blue = {'surf': (0.8, 0.1, 0.1)}, {'surf': (0.6, 0.6, 0.6)}, {'surf': (0.1, 0.1, 0.8)}
    parts = [('top_shell', box(0, 0, 0, 10, 10, 10), red), ('pcb', box(20, 0, 0, 30, 10, 2), grey), ('wheel', box(40, 0, 0, 44, 4, 4), grey)]
    W.write_assembly([{'name': n, 'shape': sh, 'colors': c, 'face_colors': []} for n, sh, c in parts], tmp_path / 'asm.step', 'asm', 'AP242')      # own writer: names every component
    W.write_assembly([{'name': 'new', 'shape': box(0, 0, 0, 12, 10, 10), 'colors': blue, 'face_colors': []}], tmp_path / 'shell_new.step', 'new', 'AP242')
    return tmp_path


def test_swap_one_part_keeps_the_rest_unchanged(ws):
    r = MS.assembly_swap(ws, 'asm.step', [{'label': 'top_shell', 'step_path': 'shell_new.step'}])
    assert r['status'] == 'PASS', r['checks']
    assert r['labels'] == ['top_shell', 'pcb', 'wheel'] and 'AP242' in r['schema_header']
    u = r['untouched_max_change']
    assert u['dvolume_mm3'] < 1e-6 and u['dcentroid_mm'] < 1e-6 and u['dbbox_mm'] < 1e-6 and u['dfaces'] == 0
    rep = r['replaced']['top_shell']
    assert rep['old']['volume_mm3'] == pytest.approx(1000.0) and rep['readback']['volume_mm3'] == pytest.approx(1200.0)
    assert r['assembly_swap_id'].startswith('as_') and r['colours']['out_parts_with_colour'] >= 3
    back = W.read_assembly(ws / r['outputs']['assembly.step']['relative_path'])
    assert [p['name'] for p in back['parts']] == ['top_shell', 'pcb', 'wheel']
    assert MS.assembly_swap(ws, 'asm.step', [{'label': 'top_shell', 'step_path': 'shell_new.step'}]).get('cached') is True


def test_gate_numbers_see_a_micron_move(ws):
    base = W.read_assembly(ws / 'asm.step')
    d = W.delta(W.props(box(20.001, 0, 0, 30.001, 10, 2)), W.props(base['parts'][1]['shape']))
    assert d['dcentroid_mm'] == pytest.approx(0.001) and d['dbbox_mm'] > 5e-4


def test_bad_arguments(ws):
    rejects('SWAP_LABEL_UNKNOWN', lambda: MS.assembly_swap(ws, 'asm.step', [{'label': 'nope', 'step_path': 'shell_new.step'}]))
    rejects('ASSEMBLY_SWAP_SETTINGS', lambda: MS.assembly_swap(ws, 'asm.step', []))
    rejects('ASSEMBLY_SWAP_SETTINGS', lambda: MS.assembly_swap(ws, 'asm.step', [{'label': 'top_shell', 'step_path': 'shell_new.step', 'x': 1}]))
    rejects('SWAP_DUPLICATE_LABEL', lambda: MS.assembly_swap(ws, 'asm.step', [{'label': 'top_shell', 'step_path': 'shell_new.step'}] * 2))
    rejects('SWAP_SOURCE_AMBIGUOUS', lambda: MS.assembly_swap(ws, 'asm.step', [{'label': 'top_shell', 'step_path': 'asm.step'}]))
    ok = MS.assembly_swap(ws, 'asm.step', [{'label': 'wheel', 'step_path': 'asm.step', 'source_part': 'pcb'}])
    assert ok['status'] == 'PASS' and ok['replaced']['wheel']['source_part'] == 'pcb'
