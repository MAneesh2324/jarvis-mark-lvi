"""
Human head mesh for the HUD avatar.

The face is **real measured human geometry** — MediaPipe's canonical face model
(`core/face_model.obj`, Apache-2.0, 468 vertices / 898 triangles), which carries
actual eyelids, nostrils, lips and cheekbones. Everything a formula cannot give
you comes from there.

Earlier revisions of this file generated the whole head procedurally from an
ellipsoid pushed around by gaussians. It could be tuned endlessly and still read
as an egg with a face drawn on it, because there was no human anatomy in it —
only smooth blobs. Real topology fixed in one step what parameter tweaking could
not fix at all.

What is still generated here, around that face:
  * the cranium — the model is an open mask, so its 36-vertex border is swept
    back and up over a skull-shaped ellipsoid and closed at the occiput;
  * a tapering neck stub that fades out instead of needing shoulders;
  * vertex normals, jaw-rig weights, a thinned wireframe, and the landmark
    index rings (eyes, brows, lips) the renderer animates.

Coordinate system after normalisation (head-local, right-handed):
    +x → viewer's right      +y → up      +z → out of the face
    y = +1.0 crown,  y = -1.0 chin,  eyes land on y ≈ 0.
"""

from __future__ import annotations

import collections
from pathlib import Path

import numpy as np

_OBJ = Path(__file__).resolve().parent / "face_model.obj"

# Cranium shape, in the model's own units (chin ≈ -9.4, forehead ≈ +8.3).
# Tuned so that brow→crown is ~0.36 of the head's height, which is the real
# proportion; a taller cranium than that immediately reads as a long face even
# though the face itself is untouched measured geometry.
_SKULL_C = (0.0, 2.0, -1.0)      # centre of the cranial ellipsoid
_SKULL_R = (8.4, 12.4, 8.2)      # its radii
_SKULL_POLE = (0.0, 0.42, -1.0)  # direction of the occiput, where the sweep closes
_SKULL_RINGS = 6
_SKULL_BLEND = 1.7               # how fast the sweep leaves the face border
_SKULL_BULGE = 1.04

_NECK_RINGS, _NECK_SEGS = 9, 14
_NECK_Z = -1.6                   # the neck tube's axis, in model units
_WIRE_STRIDE = 3                 # keep every n-th edge; the surface carries the form

# MediaPipe landmark rings. Verified against the geometry at build time — see
# `_check_landmarks` — so a wrong index can never silently animate the cheek.
LANDMARKS: dict[str, list[int]] = {
    "eye_l":  [33, 7, 163, 144, 145, 153, 154, 155, 133, 173, 157, 158, 159,
               160, 161, 246],
    "eye_r":  [263, 249, 390, 373, 374, 380, 381, 382, 362, 398, 384, 385, 386,
               387, 388, 466],
    "brow_l": [70, 63, 105, 66, 107],
    "brow_r": [300, 293, 334, 296, 336],
    "lips_out": [61, 146, 91, 181, 84, 17, 314, 405, 321, 375, 291, 409, 270,
                 269, 267, 0, 37, 39, 40, 185],
    "lips_in": [78, 95, 88, 178, 87, 14, 317, 402, 318, 324, 308, 415, 310,
                311, 312, 13, 82, 81, 80, 191],
}

# Jaw rig, in normalised units. The pivot sits between the ears, which is where
# a real mandible hinges.
JAW_PIVOT = (0.0, 0.06, -0.34)
JAW_MAX = 0.115                  # radians of drop at full amplitude (~6.6°)
#   Speech barely moves a real jaw, and a talking head is watched at HUD size
#   where a small, precise mouth reads better than a large one. The lip rig
#   (spread / round) now carries most of the articulation, so the jaw does not
#   have to swing to show that something is being said.


def _load_obj(path: Path):
    verts, faces = [], []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("v "):
            verts.append([float(x) for x in line.split()[1:4]])
        elif line.startswith("f "):
            faces.append([int(t.split("/")[0]) - 1 for t in line.split()[1:4]])
    return np.array(verts, dtype=np.float64), np.array(faces, dtype=np.int64)


def _boundary_loop(faces: np.ndarray) -> np.ndarray:
    """Ordered ring of vertices along the open border of a triangle mesh."""
    seen = collections.Counter()
    for a, b, c in faces:
        for e in ((a, b), (b, c), (c, a)):
            seen[(min(e), max(e))] += 1
    border = [e for e, n in seen.items() if n == 1]

    adj = collections.defaultdict(list)
    for a, b in border:
        adj[a].append(b)
        adj[b].append(a)

    start = border[0][0]
    loop, prev, cur = [start], None, start
    while True:
        nxt = [v for v in adj[cur] if v != prev]
        if not nxt or nxt[0] == start:
            break
        prev, cur = cur, nxt[0]
        loop.append(cur)
    return np.array(loop)


def _slerp(a: np.ndarray, b: np.ndarray, t):
    dot = np.clip((a * b).sum(-1, keepdims=True), -1.0, 1.0)
    om = np.arccos(dot)
    so = np.sin(om)
    safe = np.where(so < 1e-6, 1.0, so)
    out = np.where(so < 1e-6, a * (1 - t) + b * t,
                   (np.sin((1 - t) * om) / safe) * a + (np.sin(t * om) / safe) * b)
    return out / np.maximum(np.linalg.norm(out, axis=-1, keepdims=True), 1e-9)


def _add_cranium(verts: np.ndarray, faces: np.ndarray):
    """Sweep the mask's open border back over a skull and close it at the occiput."""
    loop = _boundary_loop(faces)

    # Orient the loop so the generated triangles wind the same way as the face's.
    centre2d = verts[loop, :2].mean(0)
    ang = np.arctan2(verts[loop, 1] - centre2d[1], verts[loop, 0] - centre2d[0])
    if np.diff(np.unwrap(ang)).sum() < 0:
        loop = loop[::-1]

    n = len(loop)
    C = np.array(_SKULL_C)
    R = np.array(_SKULL_R)
    pole = np.array(_SKULL_POLE)
    pole = pole / np.linalg.norm(pole)
    chin_y = verts[:, 1].min()

    rim = verts[loop] - C
    rim_r = np.linalg.norm(rim, axis=1, keepdims=True)
    rim_d = rim / rim_r

    def ell_r(d):
        return 1.0 / np.sqrt(((d / R) ** 2).sum(-1, keepdims=True))

    out_v = [verts]
    out_f = list(faces)
    prev_idx = loop
    ts = np.linspace(0.0, 1.0, _SKULL_RINGS + 1)[1:]

    for t in ts:
        d = _slerp(pole, rim_d, 1.0 - t)
        w = (1.0 - t) ** _SKULL_BLEND          # meets the rim exactly at t = 0
        # A skull is fuller than the border it springs from; peak it mid-sweep.
        r = ell_r(d) * (1.0 + (_SKULL_BULGE - 1.0) * np.sin(np.pi * t) ** 0.8)
        ring = C + d * (w * rim_r + (1.0 - w) * r)
        # Never dip below the chin: the sweep passing under the jaw would
        # otherwise hang a lip of geometry below the face. Vertices that hit
        # the clamp are also drawn in towards the neck axis, so the underside
        # closes as a small floor instead of a flat skirt sticking out.
        below = ring[:, 1] < chin_y
        if below.any():
            ring[below, 1] = chin_y
            ring[below, 0] *= 0.55
            ring[below, 2] = _NECK_Z + (ring[below, 2] - _NECK_Z) * 0.55
        if t == ts[-1]:
            ring = np.repeat((C + pole * ell_r(pole[None])[0])[None], n, axis=0)

        base = sum(len(a) for a in out_v)
        out_v.append(ring)
        idx = np.arange(base, base + n)
        for i in range(n):
            a0, b0 = prev_idx[i], prev_idx[(i + 1) % n]
            a1, b1 = idx[i], idx[(i + 1) % n]
            out_f.append([a0, a1, b1])
            out_f.append([a0, b1, b0])
        prev_idx = idx

    return np.vstack(out_v), np.array(out_f, dtype=np.int64)


def _add_neck(verts: np.ndarray, faces: np.ndarray):
    """A tapering tube dropped from inside the jaw; it fades out, so no shoulders."""
    ph = np.linspace(0.0, 2.0 * np.pi, _NECK_SEGS, endpoint=False)
    # Short, and flaring hard at the bottom: a straight vertical tube reads as
    # a pedestal, whereas a neck that widens into the top of the shoulders
    # reads as a bust — and the shorter it is, the larger the head can be drawn
    # in the same HUD band.
    ys = np.linspace(-5.5, -13.0, _NECK_RINGS)
    d = (ys + 5.5) / -7.5

    rx = 4.6 * (1.0 + 0.52 * d ** 1.9)
    rz = 4.1 * (1.0 + 0.38 * d ** 1.9)
    nx = rx[:, None] * np.cos(ph)[None, :]
    nz = _NECK_Z + rz[:, None] * np.sin(ph)[None, :]
    ny = ys[:, None] * np.ones_like(ph)[None, :]

    nv = np.stack([nx.ravel(), ny.ravel(), nz.ravel()], axis=1)
    base = len(verts)
    idx = base + np.arange(_NECK_RINGS * _NECK_SEGS).reshape(_NECK_RINGS, _NECK_SEGS)

    nf = []
    for i in range(_NECK_RINGS - 1):
        for j in range(_NECK_SEGS):
            a, b = idx[i, j], idx[i, (j + 1) % _NECK_SEGS]
            c, e = idx[i + 1, (j + 1) % _NECK_SEGS], idx[i + 1, j]
            nf.append([a, b, c])
            nf.append([a, c, e])

    # Enough rings that the fade steps stay small. Each quad splits into one
    # triangle with two top vertices and one with two bottom vertices, so a
    # steep per-vertex fade gradient makes the pair land on visibly different
    # brightnesses and the neck grows a sawtooth edge.
    fade = np.ones(base)
    nd = np.repeat(d, _NECK_SEGS)
    fade = np.concatenate([fade, 1.0 - 0.30 * np.clip(nd, 0.0, 1.0) ** 1.5])
    return np.vstack([verts, nv]), np.vstack([faces, np.array(nf)]), fade


def _vertex_normals(verts: np.ndarray, faces: np.ndarray,
                    outward: np.ndarray) -> np.ndarray:
    """Area-weighted vertex normals, flipped to agree with `outward`.

    `outward` must be a per-vertex direction that genuinely points out of the
    surface. A single "away from the mesh centroid" rule is NOT good enough:
    down at the base of the neck that vector points almost straight down while
    the real normal is horizontal, so the dot product hovers around zero and
    the sign flips at random — which tears the neck into an asymmetric slab of
    half-culled, half-lit triangles.
    """
    a, b, c = verts[faces[:, 0]], verts[faces[:, 1]], verts[faces[:, 2]]
    fn = np.cross(b - a, c - a)          # length carries the area — the weighting

    n = np.zeros_like(verts)
    for k in range(3):
        np.add.at(n, faces[:, k], fn)
    n /= np.maximum(np.linalg.norm(n, axis=1, keepdims=True), 1e-9)

    flip = (n * outward).sum(1) < 0
    n[flip] *= -1.0
    return n


def _unique_edges(faces: np.ndarray) -> np.ndarray:
    e = np.vstack([faces[:, [0, 1]], faces[:, [1, 2]], faces[:, [2, 0]]])
    e = np.sort(e, axis=1)
    return np.unique(e, axis=0)


def _check_landmarks(verts: np.ndarray) -> None:
    """Fail loudly at build time if a landmark ring is not where it should be."""
    for left, right in (("eye_l", "eye_r"), ("brow_l", "brow_r")):
        cl = verts[LANDMARKS[left]].mean(0)
        cr = verts[LANDMARKS[right]].mean(0)
        assert cl[0] < 0 < cr[0], f"{left}/{right} are not on opposite sides"
        assert abs(cl[1] - cr[1]) < 0.5, f"{left}/{right} are at different heights"
    eye_y = verts[LANDMARKS["eye_l"]].mean(0)[1]
    brow_y = verts[LANDMARKS["brow_l"]].mean(0)[1]
    lips = verts[LANDMARKS["lips_out"]].mean(0)
    assert brow_y > eye_y, "brow is not above the eye"
    assert lips[1] < eye_y, "lips are not below the eyes"
    assert abs(lips[0]) < 0.5, "lips are not centred"


# ── robot parts, built in the normalised head space (y: crown +1, chin -1) ─────

def _lathe(rings, axis, centre, segs):
    """Rings of (offset along axis, radius_a, radius_b) around an axis ('x' or 'y') → verts, faces (quads split)."""
    c = np.array(centre, dtype=float)
    ph = np.linspace(0.0, 2.0 * np.pi, segs, endpoint=False)
    vs = []
    for off, ra, rb in rings:
        if axis == 'x':                                   # ring in the y-z plane
            vs.append(np.stack([np.full(segs, off), ra * np.cos(ph), rb * np.sin(ph)], 1) + c)
        else:                                             # ring in the x-z plane
            vs.append(np.stack([ra * np.cos(ph), np.full(segs, off), rb * np.sin(ph)], 1) + c)
    verts = np.vstack(vs)
    faces = []
    for i in range(len(rings) - 1):
        for j in range(segs):
            a, b = i * segs + j, i * segs + (j + 1) % segs
            cc, d = (i + 1) * segs + (j + 1) % segs, (i + 1) * segs + j
            faces += [[a, b, cc], [a, cc, d]]
    return verts, np.array(faces, dtype=np.int64)


def _ear(side):
    """A robotic audio pod: a chamfered disc on the side of the head, at ear height."""
    x0 = 0.60 * side
    rings = [(0.00, 0.175, 0.145), (0.090 * side, 0.178, 0.148), (0.128 * side, 0.160, 0.132),
             (0.160 * side, 0.118, 0.098), (0.170 * side, 0.050, 0.042), (0.172 * side, 0.002, 0.002)]
    v, f = _lathe(rings, 'x', (x0, -0.16, -0.19), 24)
    out = np.zeros_like(v)
    out[:, 1:] = v[:, 1:] - np.array([-0.16, -0.19])
    out[:, 0] = side * 0.6                               # the cap faces sideways
    return v, f, out


def _hair(head_verts):
    """Sculpted robot hair: plates swept back over the cranium, ending at a natural hairline."""
    c = np.array([0.0, 0.05, -0.12])
    rel = head_verts - c
    norm = np.linalg.norm(rel, axis=1)
    dirs = rel / norm[:, None]
    AZ, EL = 48, 16
    az = np.linspace(-np.pi, np.pi, AZ, endpoint=False)
    front = (1 + np.cos(az)) / 2                         # 1 at the forehead, 0 at the nape
    bound = np.radians(-38 + 82 * front ** 0.8)          # hairline elevation: forehead 44°, temples 9°, nape -38°
    D, R = [], []
    for i in range(EL + 1):
        k = i / EL
        el = np.radians(88) * (1 - k) + bound * k        # crown → hairline
        d = np.stack([np.sin(az) * np.cos(el), np.sin(el), np.cos(az) * np.cos(el)], 1)
        near = d @ dirs.T
        top = np.argsort(-near, axis=1)[:, :10]
        D.append((d, el, k)); R.append(norm[top].max(1))
    R = np.array(R)
    for _ in range(4):                                   # smooth the skull radius: no stripes from mesh noise
        R = (np.roll(R, 1, 1) + 2 * R + np.roll(R, -1, 1)) / 4
        R[1:-1] = (R[:-2] + 2 * R[1:-1] + R[2:]) / 4
    verts, outward, fade = [], [], []
    for i, (d, el, k) in enumerate(D):
        r = R[i]
        quiff = 0.05 * front ** 3 * np.clip(np.sin(el) * 1.6, 0, 1) * (1 - k)          # a little lift over the forehead
        lift = 1.0 + 0.028 + 0.022 * np.clip(np.sin(el), 0, 1) + quiff - 0.022 * k ** 3  # close to the head, a little volume on top
        plate = 0.008 * np.cos(14 * az + 2.2 * k) ** 2                                  # machined plates, swept back
        rr = r * lift + plate * (1 - k ** 4)
        if i == EL:
            rr = r * 1.004                               # the last ring meets the scalp: no gap under the edge
        verts.append(c + d * rr[:, None])
        outward.append(d)
        fade.append(np.full(AZ, 0.62))
    verts, outward, fade = np.vstack(verts), np.vstack(outward), np.concatenate(fade)
    faces, strands = [], []
    for i in range(EL):
        for j in range(AZ):
            a, b = i * AZ + j, i * AZ + (j + 1) % AZ
            cc, d = (i + 1) * AZ + (j + 1) % AZ, (i + 1) * AZ + j
            faces += [[a, b, cc], [a, cc, d]]
            if j % 3 == 0:
                strands.append([a, d])                   # strand lines run crown → hairline
    return verts, np.array(faces, dtype=np.int64), outward, fade, np.array(strands, dtype=np.int64)


def _smooth_profile(points, n):
    """Points along a hand-drawn profile → n evenly spaced, smoothed points (a soft spline)."""
    pts = np.array(points, dtype=float)
    seg = np.r_[0, np.cumsum(np.linalg.norm(np.diff(pts, axis=0), axis=1))]
    t = np.linspace(0, seg[-1], n * 4)
    dense = np.stack([np.interp(t, seg, pts[:, 0]), np.interp(t, seg, pts[:, 1])], 1)
    for _ in range(6):
        dense[1:-1] = (dense[:-2] + 2 * dense[1:-1] + dense[2:]) / 4
    seg = np.r_[0, np.cumsum(np.linalg.norm(np.diff(dense, axis=0), axis=1))]
    t = np.linspace(0, seg[-1], n)
    return np.stack([np.interp(t, seg, dense[:, 0]), np.interp(t, seg, dense[:, 1])], 1)


# The silhouette seen from the front (x, y): neck → trapezius (a gentle concave slope) → the round
# cap of the deltoid → the upper arm hanging down. And the profile from the side (z, y): collarbone,
# then the flat plane of the chest.
SHOULDER_LINE = [(0.40, -0.96), (0.56, -1.04), (0.74, -1.13), (0.90, -1.22), (1.03, -1.31),
                 (1.13, -1.42), (1.18, -1.55), (1.18, -1.68), (1.15, -1.80), (1.12, -1.88)]
CHEST_LINE = [(0.32, -0.98), (0.40, -1.06), (0.46, -1.16), (0.49, -1.30), (0.50, -1.50), (0.49, -1.88)]


def _torso():
    """Shoulders and chest under the neck, so the head sits on a body with an upright posture."""
    U, V = 40, 16
    side = _smooth_profile(SHOULDER_LINE, V)               # (x, y) at the shoulder, per ring
    front = _smooth_profile(CHEST_LINE, V)                 # (z, y) at the chest, per ring
    u = np.linspace(0, 2 * np.pi, U, endpoint=False)
    cu, su = np.cos(u), np.sin(u)
    w_side = np.abs(cu) ** 2                               # how much a point belongs to the shoulder vs the chest
    verts, fades = [], []
    for i in range(V):
        k = i / (V - 1)
        e = 2.4 + 1.2 * k                                  # round over the shoulders, squarer down the chest
        rad = (np.abs(cu) ** e + np.abs(su) ** e) ** (-1 / e)
        delt = 0.06 * np.exp(-((k - 0.45) / 0.16) ** 2) * np.abs(cu) ** 3        # the deltoid's round cap
        x = (side[i, 0] + delt) * cu * rad
        z = -0.14 + front[i, 0] * su * rad * (1.0 if True else 1)
        z = np.where(su < 0, -0.14 + front[i, 0] * 0.92 * su * rad, z)   # the back is a little flatter
        y = front[i, 1] * (1 - w_side) + side[i, 1] * w_side
        verts.append(np.stack([x, y, z], 1))
        fades.append(np.full(U, float(np.interp(k, [0, 0.6, 1], [1.0, 0.9, 0.05]))))
    v = np.vstack(verts)
    f = []
    for i in range(V - 1):
        for j in range(U):
            a, b = i * U + j, i * U + (j + 1) % U
            c, d = (i + 1) * U + (j + 1) % U, (i + 1) * U + j
            f += [[a, b, c], [a, c, d]]
    out = v - np.array([0.0, -1.35, -0.14])
    out[:, 1] *= 0.5
    return v, np.array(f, dtype=np.int64), out, np.concatenate(fades)


def _ring_curve(centre, ra, rb, axis='y', n=48):
    ph = np.linspace(0, 2 * np.pi, n + 1)
    c = np.array(centre, dtype=float)
    if axis == 'y':
        return c + np.stack([ra * np.cos(ph), np.zeros_like(ph), rb * np.sin(ph)], 1)
    return c + np.stack([np.zeros_like(ph), ra * np.cos(ph), rb * np.sin(ph)], 1)


def _on_surface(verts, normals, path_xy, side_z=True, steps=18):
    """Follow a path over the front of the mesh: for each (x, y), the front-most surface point near it.
    The path is resampled smoothly first, so the line hugs the curve of the face instead of cutting across."""
    k = np.array(path_xy, dtype=float)
    t = np.linspace(0, 1, len(k))
    tt = np.linspace(0, 1, steps)
    path_xy = np.stack([np.interp(tt, t, k[:, 0]), np.interp(tt, t, k[:, 1])], 1)
    pts, nrm = [], []
    for x, y in path_xy:
        d = (verts[:, 0] - x) ** 2 + (verts[:, 1] - y) ** 2
        near = np.argsort(d)[:6]
        w = 1.0 / (d[near] + 1e-4)
        front = near[verts[near, 2] >= verts[near, 2].max() - 0.08] if side_z else near
        wf = 1.0 / (d[front] + 1e-4)
        point = (verts[front] * wf[:, None]).sum(0) / wf.sum()
        i = front[np.argmax(wf)]
        pts.append(point)
        nrm.append(normals[i])
    pts = np.array(pts)
    for _ in range(3):                                   # smooth the line, keeping its ends
        pts[1:-1] = (pts[:-2] + 2 * pts[1:-1] + pts[2:]) / 4
    nrm = np.array(nrm)
    for _ in range(3):
        nrm[1:-1] = (nrm[:-2] + 2 * nrm[1:-1] + nrm[2:]) / 4
    nrm /= np.maximum(np.linalg.norm(nrm, axis=1, keepdims=True), 1e-9)
    return pts + nrm * 0.018, nrm                       # float just above the skin


def build_head() -> dict:
    """Assemble the full head. Called once; `get_head_mesh()` caches the result."""
    verts, faces = _load_obj(_OBJ)
    _check_landmarks(verts)

    n_face = len(verts)
    verts, faces = _add_cranium(verts, faces)
    n_head = len(verts)
    verts, faces, fade = _add_neck(verts, faces)

    # ── normalise: crown → +1, chin → -1, eyes land on y ≈ 0 ────────────────
    head_y = verts[:n_head, 1]
    crown, chin = head_y.max(), head_y.min()
    scale = 2.0 / (crown - chin)
    centre = np.array([0.0, (crown + chin) * 0.5, 0.0])
    verts = (verts - centre) * scale

    # Outward reference, per part: the head is star-shaped about its own centre,
    # while the neck is a tube whose outward direction is radial in x/z only.
    outward = verts - np.array([0.0, verts[:n_head, 1].mean(), 0.0])
    outward[n_head:] = verts[n_head:] - np.array([0.0, 0.0, _NECK_Z * scale])
    outward[n_head:, 1] = 0.0
    normals = _vertex_normals(verts, faces, outward)
    n_neck = len(verts)

    # ── robot parts: ears, hair, shoulders ──────────────────────────────────
    body = np.zeros(len(verts))                         # 0 = turns with the head, 1 = stays with the torso
    body[n_head:] = np.clip((-verts[n_head:, 1] - 0.55) / 0.8, 0.0, 1.0)      # the neck blends from head to body
    group = np.where(np.arange(len(faces)) >= 0, 1, 1)
    group = 1 - (faces >= n_head).all(axis=1).astype(np.int32)                # 1 head, 0 neck
    extra_edges = []

    def add(pv, pf, pout, pfade, pbody, pgroup, pedges=None):
        nonlocal verts, faces, normals, fade, body, group
        base = len(verts)
        pn = _vertex_normals(pv, pf, pout)
        verts = np.vstack([verts, pv]); normals = np.vstack([normals, pn])
        faces = np.vstack([faces, pf + base]); fade = np.concatenate([fade, pfade])
        body = np.concatenate([body, np.full(len(pv), pbody) if np.isscalar(pbody) else pbody])
        group = np.concatenate([group, np.full(len(pf), pgroup)])
        if pedges is not None:
            extra_edges.append(pedges + base)
        return base

    for side in (-1, 1):
        ev, ef, eo = _ear(side)
        add(ev, ef, eo, np.full(len(ev), 1.0), 0.0, 1, _unique_edges(ef)[::2])
    hv, hf, ho, hfade, strands = _hair(verts[:n_head])
    add(hv, hf, ho, hfade, 0.0, 1)
    hair_lines = {}
    AZ = 48
    rows = len(hv) // AZ
    for j in range(0, AZ, 2):                              # swept-back strand highlights, crown to hairline
        col = hv[np.arange(1, rows - 1) * AZ + j]
        hair_lines['hair_%02d' % j] = (col + ho[np.arange(1, rows - 1) * AZ + j] * 0.006, 0.0, 0)
    tv, tf, to, tfade = _torso()
    ring_edges = np.array([[i * 40 + j, i * 40 + (j + 1) % 40] for i in (3, 7, 11) for j in range(40)])
    add(tv, tf, to, tfade, 1.0, -1, ring_edges)

    # glowing robot details, drawn as lines over the surface
    curves = dict(hair_lines)
    for side, name in ((-1, 'ear_l'), (1, 'ear_r')):
        x = (0.60 + 0.171) * side
        curves[name + '_ring'] = (_ring_curve((x, -0.16, -0.19), 0.100, 0.083, 'x', 36), 0.0, side)
        curves[name + '_core'] = (_ring_curve((x + 0.001 * side, -0.16, -0.19), 0.035, 0.029, 'x', 18), 0.0, side)
    curves['collar'] = (_ring_curve((0.0, -1.09, -0.14), 0.46, 0.36), 1.0, 0)
    curves['neck_ring_1'] = (_ring_curve((0.0, -0.78, -0.13), 0.40, 0.34), 0.35, 0)
    curves['neck_ring_2'] = (_ring_curve((0.0, -0.93, -0.13), 0.43, 0.36), 0.6, 0)
    head_v, head_n = verts[:n_head], normals[:n_head]
    for side, tag in ((-1, 'l'), (1, 'r')):
        jaw_xy = [(0.60 * side, -0.30), (0.58 * side, -0.48), (0.50 * side, -0.66), (0.36 * side, -0.82), (0.20 * side, -0.92)]
        curves['jaw_seam_' + tag] = (*_on_surface(head_v, head_n, jaw_xy)[:1], 0.0, 0)
        temple_xy = [(0.50 * side, 0.42), (0.60 * side, 0.22), (0.63 * side, 0.02)]
        curves['temple_seam_' + tag] = (*_on_surface(head_v, head_n, temple_xy)[:1], 0.0, 0)
    # chest plate: a V from the collar, a seam across, and a small core light
    front = lambda y: -0.14 + np.interp(y, [-1.8, -1.2, -1.05, -1.0], [0.47, 0.47, 0.40, 0.32]) + 0.012
    for side, tag in ((-1, 'l'), (1, 'r')):
        ys = np.linspace(-1.12, -1.48, 8)
        xs = side * np.linspace(0.30, 0.10, 8)
        curves['chest_v_' + tag] = (np.stack([xs, ys, [front(y) - 0.02 * abs(x) * 3 for x, y in zip(xs, ys)]], 1), 1.0, 0)
        # a panel seam over the top of each shoulder, following the trapezius line
        line = _smooth_profile(SHOULDER_LINE, 26)[3:12]
        xs, ys = side * line[:, 0] * 0.96, line[:, 1] + 0.035
        zs = -0.14 + 0.30 * np.ones_like(xs)
        curves['shoulder_' + tag] = (np.stack([xs, ys, zs], 1), 1.0, 0)
    ph = np.linspace(0, 2 * np.pi, 25)
    curves['chest_core'] = (np.stack([0.07 * np.cos(ph), -1.58 + 0.07 * np.sin(ph), np.full(25, front(-1.58) + 0.005)], 1), 1.0, 0)
    t_n = _vertex_normals(tv, tf, to)
    for side, tag in ((-1, 'l'), (1, 'r')):
        clav = [(0.16 * side, -1.06), (0.40 * side, -1.10), (0.62 * side, -1.15), (0.80 * side, -1.21)]
        cv = _on_surface(tv, t_n, clav, steps=14)[0]
        curves['clavicle_' + tag] = (cv - np.array([0, 0, 0.004]), 1.0, 0)
        crease = [(0.86 * side, -1.30), (0.84 * side, -1.48), (0.86 * side, -1.66), (0.90 * side, -1.84)]
        curves['deltoid_' + tag] = (_on_surface(tv, t_n, crease, steps=14)[0], 1.0, 0)
    verts = verts.astype(np.float64)

    # ── jaw rig ─────────────────────────────────────────────────────────────
    # Everything below the mouth swings on the mandible, tapering to nothing at
    # the ears and around the back so the nape and the neck stay put.
    mouth_y = verts[LANDMARKS["lips_out"], 1].mean()
    chin_y = verts[:n_head, 1].min()
    jaw = np.clip((mouth_y - verts[:, 1]) / (mouth_y - chin_y), 0.0, 1.0) ** 0.8
    jaw *= np.clip(0.30 + 0.85 * (verts[:, 2] / 0.55), 0.0, 1.0)
    jaw[n_head:] = 0.0                                  # the neck never moves
    jaw[LANDMARKS["lips_in"][:10]] = 1.0                # lower inner lip leads
    jaw[LANDMARKS["lips_out"][:10]] = 0.95

    # ── brow rig ────────────────────────────────────────────────────────────
    # Raising the brows displaces the actual surface rather than sliding a drawn
    # line over it, so the brow ridge relights as it lifts.
    brow_y = verts[LANDMARKS["brow_l"] + LANDMARKS["brow_r"], 1].mean()
    brow = np.exp(-((verts[:, 1] - brow_y) / 0.115) ** 2)
    brow *= np.clip(verts[:, 2] / 0.35, 0.0, 1.0)       # front of the face only
    brow *= np.exp(-(verts[:, 0] / 0.42) ** 2)          # fades out past the temples
    brow[n_head:] = 0.0

    # ── lip rig ─────────────────────────────────────────────────────────────
    # Vowels are not just "how far open" — /i/ spreads the lips wide, /u/ purses
    # them forward. This weight lets the renderer widen or round the mouth
    # region as a whole, so the surrounding skin follows instead of tearing away
    # from the landmark rings.
    lip_c = verts[LANDMARKS["lips_out"]].mean(axis=0)
    lips = np.exp(-((verts[:, 1] - lip_c[1]) / 0.155) ** 2)
    lips *= np.exp(-(verts[:, 0] / 0.30) ** 2)
    lips *= np.clip(verts[:, 2] / 0.40, 0.0, 1.0)
    lips[n_head:] = 0.0

    base_edges = _unique_edges(faces[:len(faces) - sum(len(x) for x in ())])
    head_like = base_edges[(base_edges < n_neck).all(1)]
    rel = verts[:n_neck] - np.array([0.0, 0.05, -0.12])
    az = np.arctan2(rel[:, 0], rel[:, 2])
    el = np.arcsin(np.clip(rel[:, 1] / np.maximum(np.linalg.norm(rel, axis=1), 1e-9), -1, 1))
    hairline = np.radians(-38 + 82 * ((1 + np.cos(az)) / 2) ** 0.8)
    under = (el > hairline - 0.03) & (np.arange(n_neck) < n_head)       # the scalp is under the hair: no wire there
    head_like = head_like[~(under[head_like[:, 0]] | under[head_like[:, 1]])][::_WIRE_STRIDE]
    edges = np.vstack([head_like] + extra_edges)          # the parts bring their own clean lines

    # Body, neck and head interpenetrate, and a painter's-algorithm sort by triangle depth interleaves
    # them into a torn edge. Grouping fixes it: torso first, then the neck, then the head with its ears
    # and hair.

    return {
        "face_group": np.ascontiguousarray(group, dtype=np.float32),
        "body": np.ascontiguousarray(body, dtype=np.float32),
        "curves": curves,
        "brow": np.ascontiguousarray(brow, dtype=np.float32),
        "lips": np.ascontiguousarray(lips, dtype=np.float32),
        "lip_centre": np.ascontiguousarray(lip_c, dtype=np.float32),
        "verts": np.ascontiguousarray(verts, dtype=np.float32),
        "normals": np.ascontiguousarray(normals, dtype=np.float32),
        "faces": np.ascontiguousarray(faces, dtype=np.int32),
        "edges": np.ascontiguousarray(edges, dtype=np.int32),
        "jaw": np.ascontiguousarray(jaw, dtype=np.float32),
        "fade": np.ascontiguousarray(fade, dtype=np.float32),
        "landmarks": {k: np.array(v, dtype=np.int32) for k, v in LANDMARKS.items()},
        "n_face": n_face,
        "n_head": n_head,
        "span": (1.0, float(verts[:, 1].min())),        # crown, bottom of the bust
    }


_CACHE: dict | None = None


def get_head_mesh() -> dict:
    """Process-wide cached mesh — every HudCanvas shares the same arrays."""
    global _CACHE
    if _CACHE is None:
        _CACHE = build_head()
    return _CACHE
