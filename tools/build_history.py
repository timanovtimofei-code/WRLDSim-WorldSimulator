# Собирает исторический атлас: кто какой территорией владел в годы снимков historical-basemaps.
# python tools/build_history.py [--era imperial]
# Атом - регион карты или его кусок: регион режется по границам снимков, если его делят разные государства.
import argparse
import colorsys
import hashlib
import json
import pickle
import re
import sys
import time
from pathlib import Path

import numpy as np
import shapely
from shapely.geometry import shape
from shapely.geometry.polygon import orient
from shapely.strtree import STRtree

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from wrldsim import config  # noqa: E402

HISTORY_DIR = config.DATA_DIR / "history"
RAW_DIR = config.RAW_DIR / "history"

ERAS = {
    "imperial": {"years": [1650, 1700, 1715, 1783, 1800, 1815, 1880, 1900, 1914, 1920, 1930], "source": "geojson"},
    "modern": {"years": [2026], "source": "countries"},
}

MODERN_COLORS = ["#5a8f55", "#4a7fc0", "#d9b84a", "#c4566d", "#7a6fb0", "#d98a5a", "#4aa6a0", "#b05a6f",
                 "#8aa85a", "#c9a24d"]

SIMPLIFY = 0.02          # градусы: упрощение геометрии атомов для экрана
WHOLE_SHARE = 0.97
MIN_PIECE_ABS = 0.35
MIN_PIECE_REL = 0.04
PROBE = (0.02, 0.06)


def project(geom):
    return shapely.transform(geom, lambda c: c * np.array([1.0, -1.0]))


def polygons(geom):
    if geom is None or geom.is_empty:
        return []
    if geom.geom_type == "Polygon":
        return [geom]
    if hasattr(geom, "geoms"):
        return [p for part in geom.geoms for p in polygons(part)]
    return []


GRID = 1e-5              # привязка к сетке (~1 м): без неё пересечения исторических полигонов падают на узлах


def snap(g):
    if not g.is_valid:
        g = shapely.make_valid(g)
    try:
        g = shapely.set_precision(g, GRID)
    except shapely.errors.GEOSException:
        return g
    return g if g.is_valid else shapely.make_valid(g)


def safe(op, a, b, fallback):
    try:
        return op(a, b)
    except shapely.errors.GEOSException:
        pass
    try:
        return op(a.buffer(0), b.buffer(0))
    except shapely.errors.GEOSException:
        return fallback


def as_multi(polys):
    if not polys:
        return shapely.Polygon()
    return polys[0] if len(polys) == 1 else shapely.MultiPolygon(polys)


class Table:
    def __init__(self):
        with open(HISTORY_DIR / "polities.json", encoding="utf-8") as f:
            raw = json.load(f)
        self.aliases = raw["aliases"]
        self.info = raw["polities"]
        self.names = [None]
        self.index = {}

    def canon(self, name):
        name = (name or "").strip()
        return self.aliases.get(name, name)

    def pid(self, name):
        name = self.canon(name)
        if not name:
            return 0
        if name not in self.index:
            self.index[name] = len(self.names)
            self.names.append(name)
        return self.index[name]


def load_snapshot(year, table):
    with open(RAW_DIR / f"world_{year}.geojson", encoding="utf-8") as f:
        feats = json.load(f)["features"]
    owners, geoms, overlord = [], [], {}
    for ft in feats:
        if not ft.get("geometry"):
            continue
        g = snap(shape(ft["geometry"]))
        polys = polygons(g)
        if not polys:
            continue
        p = table.pid(ft["properties"].get("NAME"))
        owners.append(p)
        geoms.append(project(as_multi(polys)))
        subj = table.canon(ft["properties"].get("SUBJECTO"))
        if p and subj and subj != table.names[p]:
            overlord.setdefault(p, subj)
    return np.array(owners, np.int32), np.array(geoms, dtype=object), overlord


def refine(atoms, snapshots):
    geoms = list(atoms)
    parent = list(range(len(atoms)))
    owner = []
    for s, (own, feat, _) in enumerate(snapshots):
        t0 = time.time()
        shapely.prepare(feat)
        tree = STRtree(feat)
        cur = [0] * len(geoms)
        new_geoms, new_parent = [], []
        history = {}
        split_count = 0
        garr = np.array(geoms, dtype=object)
        cand_a, cand_f = tree.query(garr, predicate="intersects")
        by_atom = {}
        for a, f in zip(cand_a.tolist(), cand_f.tolist()):
            by_atom.setdefault(a, []).append(f)

        for a, g in enumerate(geoms):
            cands = by_atom.get(a)
            if not cands:
                cur[a] = 0
                continue
            area = g.area
            whole = [f for f in cands if shapely.contains(feat[f], g)]
            if whole:
                cur[a] = int(own[whole[0]])
                continue
            share = {}
            pieces = {}
            for f in cands:
                inter = safe(shapely.intersection, g, feat[f], shapely.Polygon())
                ia = inter.area
                if ia <= 0:
                    continue
                p = int(own[f])
                share[p] = share.get(p, 0.0) + ia
                pieces.setdefault(p, []).append(inter)
            covered = sum(share.values())
            if covered < area * 0.999:
                share[0] = max(area - covered, 0.0)
            best = max(share, key=share.get)
            if share[best] >= area * WHOLE_SHARE or area < MIN_PIECE_ABS * 2:
                cur[a] = best
                continue
            parts = {p: as_multi([pp for x in v for pp in polygons(x)]) for p, v in pieces.items() if p}
            if share.get(0, 0) > 0:
                rest = g
                for v in parts.values():
                    rest = safe(shapely.difference, rest, v, rest)
                parts[0] = as_multi(polygons(rest))
            keep = {p: x for p, x in parts.items()
                    if not x.is_empty and x.area >= max(MIN_PIECE_ABS, MIN_PIECE_REL * area)}
            if len(keep) < 2:
                cur[a] = best
                continue
            for p, x in parts.items():
                if p in keep or x.is_empty:
                    continue
                near = min(keep, key=lambda q: shapely.distance(keep[q], x))
                keep[near] = as_multi(polygons(safe(shapely.union, keep[near], x, keep[near])))
            order = sorted(keep, key=lambda p: -keep[p].area)
            geoms[a] = keep[order[0]]
            cur[a] = order[0]
            split_count += 1
            for p in order[1:]:
                new_geoms.append(keep[p])
                new_parent.append(a)
                history[len(geoms) + len(new_geoms) - 1] = (a, p)
        base = len(geoms)
        for k, g in enumerate(new_geoms):
            a, p = history[base + k]
            geoms.append(g)
            parent.append(parent[a])
            cur.append(p)
        for prev in owner:
            for k in range(len(new_geoms)):
                prev.append(prev[history[base + k][0]])
        owner.append(cur)
        print(f"  снимок {s + 1}/{len(snapshots)}: режем {split_count} атомов, всего {len(geoms)} "
              f"({time.time() - t0:.0f} с)", flush=True)
    return geoms, np.array(parent, np.int32), np.array(owner, np.int32)


def edges(geoms, simplified):
    # Соседа ищем пробой точки снаружи середины отрезка: регионы упрощались порознь, общих вершин у них нет.
    tree = STRtree(geoms)
    out_a, out_b, seg = [], [], []
    for a, g in enumerate(simplified):
        for poly in polygons(g):
            poly = orient(poly, 1.0)
            for ring in [poly.exterior, *poly.interiors]:
                xy = np.asarray(ring.coords, np.float64)
                if len(xy) < 3:
                    continue
                p0, p1 = xy[:-1], xy[1:]
                d = p1 - p0
                ln = np.hypot(d[:, 0], d[:, 1])
                ok = ln > 1e-9
                p0, p1, d, ln = p0[ok], p1[ok], d[ok], ln[ok]
                if not len(p0):
                    continue
                normal = np.stack([d[:, 1], -d[:, 0]], 1) / ln[:, None]
                mid = (p0 + p1) / 2
                nb = np.full(len(mid), -1, np.int32)
                for eps in PROBE:
                    todo = np.nonzero(nb < 0)[0]
                    if not len(todo):
                        break
                    pts = shapely.points(mid[todo] + normal[todo] * eps)
                    ia, ib = tree.query(pts, predicate="intersects")
                    for i, j in zip(ia.tolist(), ib.tolist()):
                        if j != a and nb[todo[i]] < 0:
                            nb[todo[i]] = j
                seg.append(np.concatenate([p0, p1], 1).astype(np.float32))
                out_a.append(np.full(len(p0), a, np.int32))
                out_b.append(nb)
    return np.concatenate(seg), np.concatenate(out_a), np.concatenate(out_b)


def triangles(geoms):
    tris = shapely.constrained_delaunay_triangles(np.array(geoms, dtype=object))
    parts, idx = shapely.get_parts(tris, return_index=True)
    coords = shapely.get_coordinates(parts).reshape(-1, 4, 2)[:, :3].reshape(-1, 2)
    return coords.astype(np.float32), np.repeat(idx.astype(np.int32), 3)


def hex_rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def auto_color(name, base=None):
    h = int(hashlib.md5(name.encode("utf-8")).hexdigest(), 16)
    if base:
        r, g, b = (c / 255 for c in base)
        hue, lig, sat = colorsys.rgb_to_hls(r, g, b)
        lig = min(0.78, max(0.3, lig + ((h % 13) - 6) / 100 + 0.08))
        sat = max(0.25, sat * 0.85)
        return tuple(round(c * 255) for c in colorsys.hls_to_rgb((hue + ((h >> 4) % 9 - 4) / 360) % 1, lig, sat))
    hue = (h % 360) / 360
    return tuple(round(c * 255) for c in colorsys.hls_to_rgb(hue, 0.42 + ((h >> 9) % 12 - 6) / 100, 0.20))


def slug(name):
    s = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
    return s or "x"


def modern_owner(table, countries, atom_country):
    owner = []
    info = {}
    for c in atom_country:
        country = countries[c]
        name = country["name"]
        owner.append(table.pid(name))
        info[name] = [country["name_ru"] or name, None, (country["iso2"] or None), 1, None, country["iso2"]]
    return np.array([owner], np.int32), info


def greedy_colors(P, owner, seg_a, seg_b, area, names):
    nb = {}
    ok = seg_b >= 0
    a, b = owner[seg_a[ok]], owner[seg_b[ok]]
    for x, y in set(zip(a.tolist(), b.tolist())):
        if x != y and x and y:
            nb.setdefault(x, set()).add(y)
            nb.setdefault(y, set()).add(x)
    total = np.bincount(owner, weights=area, minlength=P)
    colors = {}
    for p in np.argsort(-total):
        if p == 0 or total[p] == 0:
            continue
        used = [colors[q] for q in nb.get(int(p), ()) if q in colors]
        best = min(range(len(MODERN_COLORS)), key=lambda i: (used.count(i), (hash(names[p]) + i) % 7))
        colors[int(p)] = best
    return {p: hex_rgb(MODERN_COLORS[i]) for p, i in colors.items()}


def build(era):
    spec = ERAS[era]
    years = spec["years"]
    t0 = time.time()
    table = Table()
    with open(config.WORLD_CACHE, "rb") as f:
        world = pickle.load(f)
    countries = world["countries"]

    atoms, atom_country, atom_region = [], [], []
    for ri, r in enumerate(world["regions"]):
        c = countries[r["country"]]
        if c["continent"] in ("Antarctica", "Seven seas (open ocean)"):
            continue
        g = snap(r["geom"])
        polys = polygons(g)
        if polys:
            atoms.append(as_multi(polys))
            atom_country.append(r["country"])
            atom_region.append(ri)
    print(f"Атомов-регионов: {len(atoms)}")

    extra = {}
    if spec["source"] == "geojson":
        print("Снимки...")
        snaps = [load_snapshot(y, table) for y in years]
        print(f"Государств в таблице: {len(table.names) - 1} ({time.time() - t0:.0f} с)")
        print("Нарезка регионов по границам снимков...")
        geoms, parent, owner = refine(atoms, snaps)
    else:
        geoms, parent = list(atoms), np.arange(len(atoms), dtype=np.int32)
        table.aliases = {}
        owner, extra = modern_owner(table, countries, atom_country)
        snaps = [(None, None, {})]
        print(f"Государств в таблице: {len(table.names) - 1}")
    n = len(geoms)
    atom_country = np.array(atom_country, np.int32)[parent]
    atom_region = np.array(atom_region, np.int32)[parent]

    print("Упрощение, треугольники...")
    simp = [g.simplify(SIMPLIFY, preserve_topology=True) for g in geoms]
    simp = [s if not s.is_empty else g for s, g in zip(simp, geoms)]
    tri_xy, tri_atom = triangles(simp)
    area = np.array([g.area for g in geoms], np.float32)
    anchors = np.zeros((n, 2), np.float32)
    for i, g in enumerate(simp):
        big = max(polygons(g), key=lambda p: p.area)
        pt = shapely.point_on_surface(big)
        anchors[i] = (pt.x, pt.y)
    print(f"  треугольников: {len(tri_xy) // 3}")

    print("Границы между атомами...")
    seg, seg_a, seg_b = edges(geoms, simp)
    print(f"  отрезков: {len(seg)}, из них с соседом: {int((seg_b >= 0).sum())}")

    P = len(table.names)
    top = np.tile(np.arange(P, dtype=np.int32), (len(years), 1))
    for s, (_, _, over) in enumerate(snaps):
        for p, name in over.items():
            q = table.index.get(name)
            if q is None or q == p:
                continue
            seen = {p}
            while q is not None and q not in seen:
                seen.add(q)
                nxt = table.index.get(snaps[s][2].get(q, ""))
                if nxt is None or nxt == q:
                    break
                q = nxt
            top[s, p] = q

    rows = []
    rgb = {}
    for name in table.names[1:]:
        i = table.index[name]
        ru, color, flag, flag_from, game, *rest = extra.get(name) or table.info.get(name, [name, None, None, None, None])
        rows.append((i, name, ru, color, flag, flag_from, game, rest[0] if rest else ""))
        if color:
            rgb[i] = hex_rgb(color)
    if spec["source"] == "countries":
        rgb = greedy_colors(P, owner[0], seg_a, seg_b, area, table.names)
    palette = np.zeros((P, 3), np.uint8)
    palette[0] = (0, 0, 0)
    for i, name, ru, color, flag, flag_from, game, iso in rows:
        if i in rgb:
            palette[i] = rgb[i]
        else:
            base = next((rgb[top[s, i]] for s in range(len(years)) if top[s, i] != i and top[s, i] in rgb), None)
            palette[i] = auto_color(name, base)
    meta = [{"id": iso.lower() if iso else (slug(name) if name not in table.info or not table.info[name][4]
                                              else table.info[name][4]),
             "name": name, "ru": ru, "flag": flag, "flag_from": flag_from, "game": game, "iso2": iso}
            for _, name, ru, _, flag, flag_from, game, iso in rows]
    meta.insert(0, {"id": "none", "name": "", "ru": "Ничья земля", "flag": None, "flag_from": None, "game": None,
                    "iso2": ""})

    out = config.CACHE_DIR / f"history_{era}.npz"
    np.savez_compressed(
        out,
        years=np.array(years, np.int32),
        owner=owner.astype(np.uint16), top=top.astype(np.uint16), palette=palette,
        parent=parent, atom_country=atom_country, atom_region=atom_region, area=area, anchors=anchors,
        tri_xy=tri_xy, tri_atom=tri_atom.astype(np.int32),
        seg=seg, seg_a=seg_a, seg_b=seg_b,
        meta=np.array(json.dumps(meta, ensure_ascii=False)),
    )
    print(f"Готово: {out} ({out.stat().st_size / 1e6:.1f} МБ), {n} атомов, {P - 1} государств, "
          f"{time.time() - t0:.0f} с")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--era", default="imperial", choices=list(ERAS))
    build(ap.parse_args().era)
