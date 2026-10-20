"""Parting seam (scan_shellparts S1.4): texture cue, geometry-only failure mode and the seam sanity gate. Synthetic meshes only.

Failure mode reproduced: a mouse whose plate / shell groove is faint and whose front carries a strong crease higher up (click-button lip).
Geometry alone follows the lip at the front (inferred bins drifting up) and the gate must say REVIEW; with the texture (dark plate, light
shell) the seam follows the colour boundary all round and the gate passes."""
from __future__ import annotations
import numpy as np
import pytest
from cadmcp_brain.studio import scan_regions as sr
from cadmcp_brain.studio import scan_segment as sg
from cadmcp_brain.studio import scan_shellparts as sp

Z_SEAM, Z_LIP, H_WALL, H_TOP = 3.0, 9.0, 14.0, 38.0


def _mouse_like(n_th: int = 240, lip: bool = True, groove_mm: float = 0.3, lip_half_deg: float = 20.0) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Closed mesh: flat underside, near-vertical outer wall (faint groove at Z_SEAM, optional 0.8 mm lip step at Z_LIP on the front
    |azimuth| < lip_half_deg), elliptical dome. Returns vertices, faces and a per-vertex 'texture' luminance (dark below the seam, light above)."""
    th = np.linspace(-np.pi, np.pi, n_th, endpoint=False)
    a, b = 60.0, 32.0
    rfoot = 1.0 / np.sqrt((np.cos(th) / a) ** 2 + (np.sin(th) / b) ** 2)
    # profile samples: underside (rho 0..1, z 0), wall (z 0..H_WALL), dome (quarter ellipse)
    s_under = np.linspace(0.05, 1.0, 12)
    z_wall = np.linspace(0.0, H_WALL, 120)
    t_dome = np.linspace(0.0, np.pi / 2, 40)[1:]
    rings = []
    lum = []
    for rho in s_under:
        rings.append(np.c_[rho * rfoot * np.cos(th), rho * rfoot * np.sin(th), np.zeros(n_th)])
        lum.append(np.full(n_th, 0.2))
    for z in z_wall:
        d = 1.0 - groove_mm / rfoot * np.exp(-((z - Z_SEAM) / 0.3) ** 2)      # faint groove (mm, radial)
        d = d + ((0.8 / rfoot) * (z > Z_LIP) * (np.abs(th) < np.radians(lip_half_deg)) if lip else 0.0)    # front lip step 0.8 mm (strong crease)
        d = d + 0.02 * z / rfoot                                      # slight draft (0.02 mm per mm)
        rings.append(np.c_[d * rfoot * np.cos(th), d * rfoot * np.sin(th), np.full(n_th, z)])
        lum.append(np.full(n_th, 0.2 if z < Z_SEAM else 0.8))
    for t in t_dome:
        d = (1.0 + 0.02 * H_WALL / rfoot) * np.cos(t) + 1e-3
        rings.append(np.c_[d * rfoot * np.cos(th), d * rfoot * np.sin(th), np.full(n_th, H_WALL + (H_TOP - H_WALL) * np.sin(t))])
        lum.append(np.full(n_th, 0.8))
    V = np.vstack(rings)
    L = np.concatenate(lum)
    nr = len(rings)
    F = []
    for i in range(nr - 1):
        for j in range(n_th):
            k = (j + 1) % n_th
            p0, p1, p2, p3 = i * n_th + j, i * n_th + k, (i + 1) * n_th + j, (i + 1) * n_th + k
            F += [[p0, p2, p1], [p1, p2, p3]]
    cb, ct = len(V), len(V) + 1
    V = np.vstack([V, [[0, 0, 0.0]], [[0, 0, H_TOP]]])
    L = np.r_[L, 0.2, 0.8]
    for j in range(n_th):
        k = (j + 1) % n_th
        F.append([cb, j, k])
        F.append([ct, (nr - 1) * n_th + k, (nr - 1) * n_th + j])
    F = np.array(F)
    rng = np.random.default_rng(0)
    V = V + rng.normal(0, 0.01, V.shape)                             # scanner noise
    return V, F, L


def _seam(V, F, lum=None):
    M = sr._Mesh(V, F)
    ft = sg.surface_features(M.P, M.F, M.L, M.vn, M.fn)
    return sp.seam_loop(M, ft, lum)


@pytest.fixture(scope='module')
def lip_mesh():
    return _mouse_like()


def test_texture_seam_follows_the_colour_boundary_and_passes_the_gate(lip_mesh):
    V, F, L = lip_mesh
    s = _seam(V, F, L)
    assert s['texture']['used'] and s['texture']['plate_class'] == 'dark'
    err = np.abs(s['z'] - Z_SEAM)
    assert float(err.max()) < 0.6, float(err.max())
    assert float(s['supported'].mean()) > 0.9
    assert any('texture' in e for e in s['evidence'])
    reasons, nums = sp.seam_review(s, float(V[:, 0].max() - V[:, 0].min()))
    assert reasons == [], reasons
    assert nums['texture_boundary_missed_fraction'] < 0.05


def test_geometry_only_drifts_to_the_front_lip(lip_mesh):
    """The failure mode: geometry alone takes the strong lip crease at the front (6 mm above the true seam). A SUPPORTED rise cannot be told
    from a legitimate skirt rise (a rear skirt is supported and 4-5 mm high on a real mouse), so the gate is not asserted here: the texture
    decides (test above); the gate catches the INFERRED drift of a real scan (test_gate_rules_on_synthetic_loops)."""
    V, F, _ = lip_mesh
    s = _seam(V, F, None)
    assert not s['texture']['used']
    front = np.abs(s['az']) < 15
    assert float(np.median(s['z'][front])) > Z_SEAM + 2.0, 'the front lip crease is expected to win over the faint groove'
    rear = np.abs(s['az']) > 90
    assert float(np.abs(s['z'][rear] - Z_SEAM).max()) < 0.6


def test_geometry_only_is_fine_without_the_lip():
    V, F, _ = _mouse_like(lip=False, groove_mm=0.25)
    s = _seam(V, F, None)
    assert float(np.abs(s['z'] - Z_SEAM).max()) < 0.6
    reasons, _ = sp.seam_review(s, float(V[:, 0].max() - V[:, 0].min()))
    assert reasons == []


def test_uniform_texture_gives_no_cue(lip_mesh):
    V, F, _ = lip_mesh
    s = _seam(V, F, np.full(len(V), 0.5))
    assert not s['texture']['used']


def test_gate_rules_on_synthetic_loops():
    n = sp.SEAM_COLS
    az = -180 + (np.arange(n) + .5) * 360 / n
    base = {'az': az, 'seglen': np.full(n, 0.5), 'zl': np.zeros(n), 'pts': np.zeros((n, 3)), 'texture': {'used': False}, 'tex_miss': np.zeros(n, bool)}
    # a supported rear rise (skirt) is legitimate
    z = 2.5 + 4.0 * (np.abs(az) > 140)
    s = {**base, 'z': ndi_smooth(z), 'supported': np.ones(n, bool)}
    assert sp.seam_review(s, 120.0)[0] == []
    # the same rise inferred = the prior drifting: REVIEW
    s = {**base, 'z': ndi_smooth(z), 'supported': np.abs(az) <= 140}
    assert {r['code'] for r in sp.seam_review(s, 120.0)[0]} == {'SEAM_BAND_INCONSISTENT'}
    # a 2 mm jump between neighbours
    z2 = np.full(n, 2.5); z2[10:] += 2.0
    s = {**base, 'z': z2, 'supported': np.ones(n, bool)}
    assert 'SEAM_JUMP' in {r['code'] for r in sp.seam_review(s, 120.0)[0]}
    # mostly inferred
    s = {**base, 'z': np.full(n, 2.5), 'supported': np.arange(n) < 0.2 * n}
    assert 'SEAM_UNSUPPORTED' in {r['code'] for r in sp.seam_review(s, 120.0)[0]}


def ndi_smooth(z):
    from scipy import ndimage as ndi
    return ndi.gaussian_filter1d(z, 6, mode='wrap')


def test_otsu_splits_two_classes():
    x = np.r_[np.random.default_rng(1).normal(0.2, 0.03, 500), np.random.default_rng(2).normal(0.8, 0.03, 300)]
    t = sp._otsu(x)
    assert 0.25 < t < 0.75
    assert sp._otsu(np.full(50, 0.4)) == 0.4
