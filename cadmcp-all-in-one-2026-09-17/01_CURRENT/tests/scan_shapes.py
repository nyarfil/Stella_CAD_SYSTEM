"""Synthetic closed meshes for scan-to-shell tests (no files, no network)."""
from __future__ import annotations
from pathlib import Path
import numpy as np


def _weld(v: np.ndarray, f: np.ndarray, nd: int = 9) -> tuple[np.ndarray, np.ndarray]:
    key = np.round(v, nd)
    u, idx, inv = np.unique(key, axis=0, return_index=True, return_inverse=True)
    return v[idx], inv.reshape(-1)[f]


def cube_sphere(n: int) -> tuple[np.ndarray, np.ndarray]:
    """Unit sphere from a subdivided cube (n x n quads per face, 12n^2 triangles), outward CCW."""
    g = np.linspace(-1, 1, n + 1)
    uu, vv = np.meshgrid(g, g, indexing='ij')
    faces_v, faces_f, base = [], [], 0
    for ax in range(3):
        for sgn in (-1, 1):
            p = np.zeros((n + 1, n + 1, 3))
            a, b = (ax + 1) % 3, (ax + 2) % 3
            p[..., ax], p[..., a], p[..., b] = sgn, uu, vv
            idx = np.arange((n + 1) ** 2).reshape(n + 1, n + 1) + base
            q = np.stack([idx[:-1, :-1], idx[1:, :-1], idx[1:, 1:], idx[:-1, 1:]], axis=-1).reshape(-1, 4)
            if sgn < 0:
                q = q[:, ::-1]
            faces_f += [q[:, [0, 1, 2]], q[:, [0, 2, 3]]]
            faces_v.append(p.reshape(-1, 3))
            base += (n + 1) ** 2
    v = np.vstack(faces_v)
    v = v / np.linalg.norm(v, axis=1, keepdims=True)
    return _weld(v, np.vstack(faces_f))


def sphere(radius: float = 30.0, n: int = 24):
    v, f = cube_sphere(n)
    return v * radius, f


def superellipsoid(a: float, b: float, c: float, e: float = 0.6, n: int = 40):
    """Mouse-like smooth body: |x/a|^(2/e)+... = 1 style, exponent e<1 gives a boxier, flatter shape."""
    v, f = cube_sphere(n)
    w = np.sign(v) * np.abs(v) ** e
    return w * np.array([a, b, c]), f


def box(size=(40.0, 30.0, 20.0), n: int = 1):
    """Axis-aligned box centred at the origin, each face n x n quads."""
    v, f = cube_sphere(n)
    # cube_sphere normalises; rebuild from the cube instead
    g = np.linspace(-1, 1, n + 1)
    uu, vv = np.meshgrid(g, g, indexing='ij')
    fv, ff, base = [], [], 0
    for ax in range(3):
        for sgn in (-1, 1):
            p = np.zeros((n + 1, n + 1, 3))
            a, b = (ax + 1) % 3, (ax + 2) % 3
            p[..., ax], p[..., a], p[..., b] = sgn, uu, vv
            idx = np.arange((n + 1) ** 2).reshape(n + 1, n + 1) + base
            q = np.stack([idx[:-1, :-1], idx[1:, :-1], idx[1:, 1:], idx[:-1, 1:]], axis=-1).reshape(-1, 4)
            if sgn < 0:
                q = q[:, ::-1]
            ff += [q[:, [0, 1, 2]], q[:, [0, 2, 3]]]
            fv.append(p.reshape(-1, 3))
            base += (n + 1) ** 2
    v, f = _weld(np.vstack(fv), np.vstack(ff))
    return v * (np.array(size) / 2.0), f


def lattice_union(occ: np.ndarray, unit: float, origin=(0.0, 0.0, 0.0)):
    """Watertight boundary mesh of a union of unit cubes (occ[i,j,k] bool). Avoid edge-only contacts."""
    occ = np.pad(occ, 1)
    quads = []
    for ax in range(3):
        for sgn in (-1, 1):
            nb = np.roll(occ, -sgn, axis=ax)
            face = occ & ~nb
            for i, j, k in np.argwhere(face):
                c = np.array([i, j, k], float) - 1
                a, b = (ax + 1) % 3, (ax + 2) % 3
                base = c.copy()
                if sgn > 0:
                    base[ax] += 1
                p = [base.copy() for _ in range(4)]
                p[1][a] += 1
                p[2][a] += 1
                p[2][b] += 1
                p[3][b] += 1
                quads.append(p if sgn > 0 else p[::-1])
    pts = np.array(quads).reshape(-1, 3) * unit + np.array(origin)
    idx = np.arange(len(pts)).reshape(-1, 4)
    f = np.vstack([idx[:, [0, 1, 2]], idx[:, [0, 2, 3]]])
    return _weld(pts, f)


def write_stl(path: Path, v: np.ndarray, f: np.ndarray, ascii_: bool = False) -> None:
    t = v[f]
    if ascii_:
        lines = ['solid t']
        for tri in t:
            lines += ['facet normal 0 0 0', 'outer loop'] + [f'vertex {x:.9g} {y:.9g} {z:.9g}' for x, y, z in tri] + ['endloop', 'endfacet']
        lines.append('endsolid t')
        path.write_text('\n'.join(lines))
        return
    nrm = np.cross(t[:, 1] - t[:, 0], t[:, 2] - t[:, 0])
    nrm /= np.maximum(np.linalg.norm(nrm, axis=1, keepdims=True), 1e-300)
    rec = np.zeros(len(f), dtype=np.dtype([('n', '<f4', 3), ('v', '<f4', (3, 3)), ('a', '<u2')]))
    rec['n'], rec['v'] = nrm, t
    path.write_bytes(b'x' * 80 + np.uint32(len(f)).tobytes() + rec.tobytes())
