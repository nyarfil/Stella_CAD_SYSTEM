"""brain_mouse_shell_solid (+ brain_mouse_shell_fit front_cut auto): synthetic mouse-like body, no scan data.

Body = ellipsoid 124 x 62 x 38 (z >= 0) cut by vertical side panels |y| <= W(x) in front (crease along the panel sides) and a plain front wall
(crease = front lip); plate below z = 4 (flat seam -> z-const parting plane). shell_fit picks the cut at the rear end of the click labels,
shell_solid closes the skin to ONE valid solid whose volume matches the mesh volume above the seam."""
from __future__ import annotations
import json
from pathlib import Path
import numpy as np
import pytest
from cadmcp_brain.api import Tools
from cadmcp_brain.engine import Brain
from cadmcp_brain.errors import BrainError
from cadmcp_brain.studio import scan_shell_fit as sf
from cadmcp_brain.studio import scan_shell_solid as ss

trimesh = pytest.importorskip('trimesh')
pytest.importorskip('OCP')

A, B, C = 62.0, 31.0, 38.0
XF, X0, SEAM = 52.0, 20.0, 4.0


def rejects(code, fn):
    with pytest.raises(BrainError) as exc:
        fn()
    assert exc.value.code == code
    return exc.value


def half_e(x):
    return B * np.sqrt(np.clip(1 - (x / A) ** 2, 0, None))


def W(x):
    return 0.85 * half_e(x) + np.where(x < X0, 2.0 * (X0 - x) ** 2, 0.0)


def inside(P):
    x, y, z = P[..., 0], P[..., 1], P[..., 2]
    return ((x / A) ** 2 + (y / B) ** 2 + (z / C) ** 2 <= 1) & (np.abs(y) <= W(x)) & (x <= XF + 0.1 * z) & (z >= 0)


def make(folder: Path, count=(300, 150)):
    """Star-shaped body meshed by ray bisection on a UV sphere; labels by geometry (plate below the seam, clicks on the front top)."""
    s = trimesh.creation.uv_sphere(radius=1.0, count=list(count))
    D = np.asarray(s.vertices, float)
    D /= np.linalg.norm(D, axis=1)[:, None]
    c = np.array([0.0, 0.0, 8.0])
    lo, hi = np.zeros(len(D)), np.full(len(D), 100.0)
    for _ in range(45):
        mid = 0.5 * (lo + hi)
        ok = inside(c + mid[:, None] * D)
        lo, hi = np.where(ok, mid, lo), np.where(ok, hi, mid)
    m = trimesh.Trimesh(c + lo[:, None] * D, np.asarray(s.faces), process=True)
    m.update_faces(m.nondegenerate_faces())
    m.remove_unreferenced_vertices()
    assert m.is_watertight
    folder.mkdir(parents=True, exist_ok=True)
    m.export(folder / 'in.stl')
    cen, nrm = m.triangles_center, m.face_normals
    plate = cen[:, 2] < SEAM
    click = ~plate & (nrm[:, 2] > 0.5) & (cen[:, 0] > X0 + 3) & (np.abs(cen[:, 1]) < W(cen[:, 0]) - 1.0) & (cen[:, 0] < XF - 2)
    lab = {'bottom_plate': np.flatnonzero(plate).tolist(), 'left_click': np.flatnonzero(click & (cen[:, 1] > 0.3)).tolist(),
           'right_click': np.flatnonzero(click & (cen[:, 1] < -0.3)).tolist()}
    used = np.zeros(len(cen), bool)
    for v in lab.values():
        used[v] = True
    lab['top_shell'] = np.flatnonzero(~used).tolist()
    (folder / 'labels.json').write_text(json.dumps(lab), encoding='utf-8')
    rep = {'plane': {'normal': [0.0, 1.0, 0.0], 'd': 0.0},
           'symmetry_test': {'global': {'plane_valid': True}, 'regions': {k: {'symmetric': True} for k in lab}}}
    (folder / 'sym.json').write_text(json.dumps(rep), encoding='utf-8')
    above = trimesh.intersections.slice_mesh_plane(m, [0, 0, 1.0], [0, 0, SEAM], cap=True)
    click_rear = float(m.vertices[np.unique(m.faces[click].ravel()), 0].min())
    return float(above.volume), click_rear


@pytest.fixture(scope='module')
def chain(tmp_path_factory):
    ws = tmp_path_factory.mktemp('shell_solid')
    vol, click_rear = make(ws / 'c')
    fit = sf.shell_fit(ws, 'c/in.stl', 'mm', labels_path='c/labels.json', symmetry_report_path='c/sym.json')
    rel = f"mouse/cad/{fit['fit_id']}/shell_fit_report.json"
    solid = ss.shell_solid(ws, rel)
    return {'ws': ws, 'vol': vol, 'click_rear': click_rear, 'fit': fit, 'fit_rel': rel, 'solid': solid}


def test_front_cut_auto_at_click_rear(chain):
    fit = chain['fit']
    assert fit['status'] == 'READY', (fit['blocking_reasons'], fit['deviation'])
    fc = fit['front_cut']
    assert fc['mode'] == 'auto' and 'click regions' in fc['rule'] and fc['chosen'] is not None
    assert fc['chosen_x_aligned'] <= chain['click_rear'] - 0.5 + 1e-6 and fc['chosen_x_aligned'] >= chain['click_rear'] - 0.5 - 3 * 3.0
    assert len(fit['cut_planes_used']) == 1 and fit['settings']['front_cut'] == 'auto'
    surf = json.loads((chain['ws'] / fit['outputs']['surface']['relative_path']).read_text(encoding='utf-8'))
    assert surf['cut_planes'] == fit['cut_planes_used']


def test_closed_solid_ready(chain):
    rep = chain['solid']
    assert rep['status'] == 'READY', (rep['blocking_reasons'], rep['warnings'])
    br = rep['brep']
    assert br['valid'] and br['solids'] == 1 and br['tessellates'] and br['min_face_area_mm2'] > 100
    assert br['volume_mm3'] == pytest.approx(chain['vol'], rel=0.01)
    assert rep['parting']['mode_used'] == 'plane' and rep['parting']['plane_z_mm'] == pytest.approx(SEAM, abs=0.15)
    assert br['bbox'][2] == pytest.approx(rep['parting']['plane_z_mm'], abs=1e-3)
    assert rep['deviation']['all']['p95'] < 0.1
    assert rep['construction']['cap']['G1_error_deg'] < 0.5 and rep['construction']['sewing']['multiple_edges'] == 0
    assert abs(rep['front']['front_length_error_mm']) < 1.0
    assert rep['outputs']['solid']['relative_path'].endswith('top_shell_solid.step')
    assert any('slot layout' in w for w in rep['warnings'])
    again = ss.shell_solid(chain['ws'], chain['fit_rel'])
    assert again['cached'] is True and again['solid_id'] == rep['solid_id']


def test_validation(chain, tmp_path):
    ws = chain['ws']
    rejects('SHELL_SOLID_SETTINGS', lambda: ss.shell_solid(ws, chain['fit_rel'], parting_mode='flat'))
    rejects('SHELL_SOLID_SETTINGS', lambda: ss.shell_solid(ws, chain['fit_rel'], plain_front='yes'))
    rejects('SHELL_SOLID_SETTINGS', lambda: ss.shell_solid(ws, chain['fit_rel'], shell_regions=[]))
    rejects('SHELL_SOLID_SKIN', lambda: ss.shell_solid(ws, 'c/sym.json'))
    no_cut = json.loads((ws / chain['fit_rel']).read_text(encoding='utf-8'))
    surf_rel = no_cut['outputs']['surface']['relative_path']
    srf = json.loads((ws / surf_rel).read_text(encoding='utf-8'))
    srf['cut_planes'] = []
    (ws / 'c' / 'surf_nocut.json').write_text(json.dumps(srf), encoding='utf-8')
    no_cut['outputs']['surface']['relative_path'] = 'c/surf_nocut.json'
    no_cut['settings']['cut_planes'] = []
    no_cut['front_cut'] = {'mode': 'none', 'chosen': None}
    (ws / 'c' / 'fit_nocut.json').write_text(json.dumps(no_cut), encoding='utf-8')
    rejects('SHELL_SOLID_NO_CUT', lambda: ss.shell_solid(ws, 'c/fit_nocut.json'))
    full = dict(no_cut, mode_used='full')
    (ws / 'c' / 'fit_full.json').write_text(json.dumps(full), encoding='utf-8')
    rejects('SHELL_SOLID_NEEDS_HALF', lambda: ss.shell_solid(ws, 'c/fit_full.json'))


def test_layout_from_click_grooves_report(tmp_path):
    (tmp_path / 'g').mkdir()
    (tmp_path / 'g' / 'slot_layout.json').write_text(json.dumps({'schema': 'click_slot_layout/1', 'perimeter': {'points': [[0, 0], [1, 0]]}}))
    (tmp_path / 'g' / 'click_grooves_report.json').write_text(json.dumps({'schema': 'scan_click_grooves_report/1', 'outputs': {
        'layout': {'relative_path': 'g/slot_layout.json'}}}))
    p, rel = ss.resolve_layout(tmp_path, 'g/click_grooves_report.json')
    assert p.name == 'slot_layout.json' and rel == 'g/slot_layout.json'
    p, rel = ss.resolve_layout(tmp_path, 'g/slot_layout.json')
    assert rel == 'g/slot_layout.json'
    (tmp_path / 'g' / 'empty.json').write_text(json.dumps({'schema': 'scan_click_grooves_report/1', 'outputs': {}}))
    rejects('SHELL_SOLID_LAYOUT', lambda: ss.resolve_layout(tmp_path, 'g/empty.json'))


def test_tool_listed(tmp_path):
    tools = {t['name']: t for t in Tools(Brain(tmp_path)).list()}
    t = tools['brain_mouse_shell_solid']
    assert t['annotations']['readOnlyHint'] is False
    props = t['inputSchema']['properties']
    assert props['parting_mode']['default'] == 'auto' and props['plain_front']['default'] is True
    assert tools['brain_mouse_shell_fit']['inputSchema']['properties']['front_cut']['default'] == 'auto'


def _revolved(rz, z0=2.0, z1=10.0, nt=360, nz=161):
    th = np.linspace(0, 2 * np.pi, nt, endpoint=False)
    zz = np.linspace(z0, z1, nz)
    T, Z = np.meshgrid(th, zz, indexing='ij')
    Rr = rz(Z)
    V = np.c_[(Rr * np.cos(T)).ravel(), (Rr * np.sin(T)).ravel(), Z.ravel()]
    F = []
    for i in range(nt):
        for j in range(nz - 1):
            a, b, c, d = i * nz + j, ((i + 1) % nt) * nz + j, ((i + 1) % nt) * nz + j + 1, i * nz + j + 1
            F += [[a, b, c], [a, c, d]]
    return V, np.asarray(F)


def test_seam_moves_onto_a_wall_crest_but_not_up_a_leaning_wall():
    """SS1.2 seam_to_crest: a label seam 0.5 mm below a bulge crest moves onto the crest; a wall that keeps leaning out (no interior
    maximum) and a wall with a weak bulge (prominence below crest_prominence_mm) keep the seam; generic (any azimuth, no OP1 numbers)."""
    from cadmcp_brain.studio import scan_shell_solid_worker as w
    p = dict(w.DEFAULTS)
    ang = np.linspace(0, 2 * np.pi, 40, endpoint=False)
    for rz, z_seam, want in ((lambda z: 20.0 - 0.5 * (z - 6.0) ** 2, 5.5, 6.0),        # bulge, prominence 0.28 mm at 0.75 mm
                             (lambda z: 20.0 + 0.3 * z, 5.5, 5.5),                      # leaning wall: crest at the window edge -> kept
                             (lambda z: 20.0 - 0.05 * (z - 6.0) ** 2, 5.5, 5.5)):       # weak bulge (0.03 mm) -> kept
        V, F = _revolved(rz)
        S = np.c_[rz(z_seam) * np.cos(ang), rz(z_seam) * np.sin(ang), np.full(len(ang), z_seam)]
        out, log = w.seam_to_crest(V, F, S, p)
        assert np.allclose(out[:, :2], S[:, :2])
        assert np.abs(out[:, 2] - want).max() < 0.08, (want, out[:, 2].min(), out[:, 2].max(), log)


def test_hidden_inner_sheet_is_not_part_of_the_exterior():
    """A moulded lip scans as two sheets; the up-facing sheet under the outer one is hidden, walls and bottoms stay."""
    from cadmcp_brain.studio import scan_shell_solid_worker as ssw
    g = np.stack(np.meshgrid(np.arange(0, 20, 0.25), np.arange(0, 20, 0.25)), -1).reshape(-1, 2)
    outer = np.c_[g, np.full(len(g), 10.0)]
    inner = np.c_[g, np.full(len(g), 8.0)]
    buf = ssw.zbuffers(np.vstack([outer, inner]), 0.5)
    up = np.tile([0.0, 0.0, 1.0], (len(g), 1))
    assert ssw.exterior_mask(outer[:50], up[:50], buf, 0.9, 0.6).all()
    assert not ssw.exterior_mask(inner[:50], up[:50], buf, 0.9, 0.6).any()
    wall = np.tile([1.0, 0.0, 0.0], (50, 1))
    assert ssw.exterior_mask(inner[:50], wall, buf, 0.9, 0.6).all()


def test_frame_of_an_offset_mirror_plane_puts_the_plane_on_y0():
    from cadmcp_brain.studio import scan_shell_solid_worker as ssw
    n = np.array([0.02, 1.0, 0.0])
    n /= np.linalg.norm(n)
    d = 5.3                                                  # mirror plane n.x = d is far from the origin
    R, dd = ssw.frame_of(n, d, [1.0, -0.02, 0.0])
    on_plane = np.array([0.0, d / n[1], 7.0]) + 11.0 * np.cross(n, [0, 0, 1.0]) + 3.0 * np.array([0, 0, 1.0])
    assert abs(n @ on_plane - d) < 1e-9
    assert abs(ssw.to_q(on_plane[None], R, dd)[0, 1]) < 1e-9
    assert abs(np.linalg.det(R) - 1.0) < 1e-9


def _front_nose_samples(nose_slope=1.4, lip_z=12.0, nose_lip_z=10.0, r0=30.0):
    """Synthetic front half (aligned frame, cut at x = 0, outline a half circle of radius r0): the sides (|phi| > 45 deg) have a crisp
    lip at lip_z (sloped top above, vertical wall below); the nose (|phi| <= 45 deg) has NO wall: the top slope runs straight down to
    its bottom edge at nose_lip_z, receding inward above it by nose_slope mm per mm of height (an Inca-like nose)."""
    P, N = [], []
    for phi in np.linspace(-np.pi / 2, np.pi / 2, 361):
        n = np.array([np.cos(phi), np.sin(phi)])
        side = abs(phi) > np.pi / 4
        for z in np.arange(4.0, 22.0, 0.1):
            if side:
                h = 0.0 if z < lip_z else -(z - lip_z)
                nn = np.r_[n, 0.0] if z < lip_z else np.r_[n * 0.7071, 0.7071]
            else:
                if z < nose_lip_z:
                    continue
                h = -(z - nose_lip_z) * nose_slope
                nn = np.r_[n, nose_slope] / np.hypot(1, nose_slope)
            P.append([*((r0 + h) * n), z])
            N.append(nn)
    return np.array(P), np.array(N)


def test_gamma_lies_on_the_skin_where_the_nose_has_no_crisp_crease():
    """Inca cause: stations without a crisp crease were bridged in (h, z) from the side creases, so Gamma sat several mm in front of a
    receding nose at its own height (beak). Gamma must lie on the measured skin at every station."""
    from cadmcp_brain.studio import scan_shell_solid_worker as ssw
    P, N = _front_nose_samples()
    plan = ssw.Plan(P[:, :2], 0.0)
    log = {}
    hG, zG, rows = ssw.measure_gamma(plan, P, N, np.ones(len(P), bool), ssw.DEFAULTS, log)
    assert log['gamma']['on_surface']['applied']
    off = []
    for s in np.linspace(0.3 * plan.LS, 0.7 * plan.LS, 25):       # nose stations
        h_skin = ssw.surface_h_at(plan, P, s, float(np.interp(s, plan.ss, zG)), 0.5)
        off.append(float(np.interp(s, plan.ss, hG)) - h_skin)
    tol = float(ssw.DEFAULTS['gamma_surface_tol_mm'])                  # soft threshold: residual stays within the tolerance band
    assert np.isfinite(off).all() and np.abs(off).max() < tol + 0.1, off
    assert log['gamma_on_surface']['off_surface_before_mm']['max'] > 1.0    # the uncorrected bridge was off the skin
    for s in (0.05 * plan.LS, 0.95 * plan.LS):                          # crisp side lip keeps its crease (z 12, h 0)
        assert abs(float(np.interp(s, plan.ss, zG)) - 12.0) < 0.3
        assert abs(float(np.interp(s, plan.ss, hG))) < 0.3


def test_cap_heightfield_is_the_upper_envelope_not_pulled_into_a_well():
    """Inca cause: a wheel well without a layout window (walls + floor labelled as shell) pulled the least-squares cap down and the
    symmetric MAD trim then dropped the rim instead of the well (dent ring). The robust fit must stay on the skin over the well."""
    from cadmcp_brain.studio import scan_shell_solid_worker as ssw
    rng = np.random.default_rng(0)
    xy = np.c_[rng.uniform(70, 120, 60000), rng.uniform(-30, 30, 60000)]
    z = 30.0 - 0.006 * (xy[:, 0] - 95) ** 2 - 0.01 * xy[:, 1] ** 2 + rng.normal(0, 0.02, len(xy))
    well = (np.abs(xy[:, 0] - 97) < 10) & (np.abs(xy[:, 1]) < 4)
    z[well] -= 2.5 * rng.uniform(0.3, 1.0, well.sum())            # well floor and walls, 0.75 .. 2.5 mm below the skin
    C = np.c_[xy, z]
    X0, X1, Y1 = 69.0, 121.0, 31.0
    kx = np.r_[[X0] * 3, np.linspace(X0, X1, 20), [X1] * 3]
    ky = np.r_[[-Y1] * 3, np.linspace(-Y1, Y1, 20), [Y1] * 3]
    cf, keep, thr = ssw.upper_envelope_heightfield(C, kx, ky, 0.5)
    from scipy.interpolate import BSpline
    fit = np.einsum('ni,ij,nj->n', BSpline.design_matrix(C[:, 0], kx, 3).toarray(), cf, BSpline.design_matrix(C[:, 1], ky, 3).toarray())
    skin = 30.0 - 0.006 * (C[:, 0] - 95) ** 2 - 0.01 * C[:, 1] ** 2
    ring = (~well) & (np.abs(C[:, 0] - 97) < 13) & (np.abs(C[:, 1]) < 7)
    assert keep[~well].mean() > 0.99 and keep[well].mean() < 0.05, (keep[~well].mean(), keep[well].mean())
    assert np.abs(fit[ring] - skin[ring]).max() < 0.2, np.abs(fit[ring] - skin[ring]).max()
    assert np.abs(fit[well] - skin[well]).max() < 1.0                 # bridged over the well near the skin (symmetric trim: 1.78 sag)
