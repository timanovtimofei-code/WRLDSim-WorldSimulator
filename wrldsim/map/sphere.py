# Геометрия для глобуса: вершины проецируются на шар по одной, а грань остаётся прямой, поэтому
# крупные треугольники дробятся, пока сторона не станет короче max_deg градусов.
import numpy as np

MAX_DEG = 2.5


def subdivide(verts, max_deg=MAX_DEG, max_iter=8):
    k = verts.shape[1]
    tris = np.asarray(verts, np.float32).reshape(-1, 3, k)
    done = []
    for _ in range(max_iter):
        if not len(tris):
            break
        xy = tris[:, :, :2]
        edge = np.max(np.abs(xy - np.roll(xy, -1, axis=1)).max(axis=2), axis=1)
        big = edge > max_deg
        done.append(tris[~big])
        tris = tris[big]
        if not len(tris):
            break
        a, b, c = tris[:, 0], tris[:, 1], tris[:, 2]
        ab, bc, ca = (a + b) / 2, (b + c) / 2, (c + a) / 2
        tris = np.concatenate([np.stack(t, 1) for t in ((a, ab, ca), (ab, b, bc), (ca, bc, c), (ab, bc, ca))])
    done.append(tris)
    return np.concatenate(done).reshape(-1, k)


def graticule(step, seg=2.0):
    out = []
    for lon in range(-180, 180, step):
        ys = np.arange(-90.0, 90.0 + 1e-6, seg)
        pts = np.stack([np.full_like(ys, lon), ys], 1)
        out.append(np.repeat(pts, 2, axis=0)[1:-1])
    for lat in range(-90 + step, 90, step):
        xs = np.arange(-180.0, 180.0 + 1e-6, seg)
        pts = np.stack([xs, np.full_like(xs, lat)], 1)
        out.append(np.repeat(pts, 2, axis=0)[1:-1])
    return np.concatenate(out).astype(np.float32)
