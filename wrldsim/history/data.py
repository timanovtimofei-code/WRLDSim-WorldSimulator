# Мир поделён на атомы; owner[снимок][атом] - государство, top[снимок][государство] - верховная держава.
import json
from dataclasses import dataclass, replace as _dc_replace

import numpy as np

from .. import config


@dataclass
class Polity:
    index: int
    id: str
    name: str
    ru: str
    flag: str
    flag_from: int
    game: str
    color: tuple
    iso2: str = ""
    periods: tuple = ()

    @property
    def title(self):
        return self.ru or self.name

    def at(self, year):
        title = self.ru
        for start, name in self.periods:
            if start <= year:
                title = name
        return self if title == self.ru else _dc_replace(self, ru=title)


class History:
    def __init__(self, path):
        z = np.load(path, allow_pickle=False)
        self.years = [int(y) for y in z["years"]]
        self.owner = z["owner"]
        self.top = z["top"]
        self.palette = z["palette"]
        self.parent = z["parent"]
        self.atom_country = z["atom_country"]
        self.atom_region = z["atom_region"]
        self.area = z["area"]
        self.anchors = z["anchors"]
        self.tri_xy = z["tri_xy"]
        self.tri_atom = z["tri_atom"]
        self.seg = z["seg"]
        self.seg_a = z["seg_a"]
        self.seg_b = z["seg_b"]
        meta = json.loads(str(z["meta"]))
        self.polities = [Polity(i, m["id"], m["name"], m["ru"], m["flag"] or "", m["flag_from"] or 0,
                                m["game"] or "", tuple(int(c) for c in self.palette[i]), m.get("iso2") or "")
                         for i, m in enumerate(meta)]
        self._apply_info()
        self.atoms = self.owner.shape[1]
        self._index_atoms()

    def _apply_info(self):
        # Названия и флаги берутся из data/history/polities.json на лету, чтобы править их без пересборки кэша.
        if any(p.iso2 for p in self.polities):
            return
        try:
            with open(config.DATA_DIR / "history" / "polities.json", encoding="utf-8") as f:
                raw = json.load(f)
        except (OSError, ValueError):
            return
        info, periods = raw.get("polities", {}), raw.get("periods", {})
        for p in self.polities:
            row = info.get(p.name)
            if row:
                p.ru, p.flag, p.flag_from, p.game = row[0], row[2] or "", row[3] or 0, row[4] or ""
            if p.name in periods:
                p.periods = tuple((int(y), n) for y, n in periods[p.name])

    def _index_atoms(self):
        order = np.argsort(self.tri_atom[::3], kind="stable")
        if not np.all(order[:-1] <= order[1:]):
            tri = self.tri_xy.reshape(-1, 3, 2)[order]
            self.tri_xy = tri.reshape(-1, 2)
            self.tri_atom = np.repeat(self.tri_atom[::3][order], 3)
        ta = self.tri_atom[::3]
        counts = np.bincount(ta, minlength=self.atoms)
        self._tri_off = np.concatenate([[0], np.cumsum(counts)])
        tri = self.tri_xy.reshape(-1, 3, 2)
        lo = np.full((self.atoms, 2), np.inf, np.float32)
        hi = np.full((self.atoms, 2), -np.inf, np.float32)
        np.minimum.at(lo, ta, tri.min(axis=1))
        np.maximum.at(hi, ta, tri.max(axis=1))
        self.bbox = np.concatenate([lo, hi], axis=1)
        has = self.seg_b >= 0
        a, b = self.seg_a[has].astype(np.int64), self.seg_b[has].astype(np.int64)
        pair = np.unique(np.minimum(a, b) * (self.atoms + 1) + np.maximum(a, b))
        self._pa, self._pb = pair // (self.atoms + 1), pair % (self.atoms + 1)

    def _components(self, same):
        a, b = self._pa[same], self._pb[same]
        lab = np.arange(self.atoms)
        while len(a):
            m = np.minimum(lab[a], lab[b])
            new = lab.copy()
            np.minimum.at(new, a, m)
            np.minimum.at(new, b, m)
            new = new[new]
            if np.array_equal(new, lab):
                break
            lab = new
        return lab

    def snapshot_at(self, year):
        return min(range(len(self.years)), key=lambda i: abs(self.years[i] - year))

    def range(self):
        return self.years[0], self.years[-1]

    def keys(self, snap, empire=False):
        state = self.owner[snap].astype(np.int32)
        top = self.top[snap][state].astype(np.int32)
        return state, top, (top if empire else state)

    def polity(self, index):
        return self.polities[int(index)]

    def presence(self, polity):
        out = []
        for s, y in enumerate(self.years):
            state = self.owner[s]
            if (state == polity).any() or (self.top[s][state] == polity).any():
                out.append(y)
        return out

    def countries_of(self, snap, key, empire, limit=6):
        _, _, color = self.keys(snap, empire)
        mask = color == key
        if not mask.any():
            return []
        w = np.bincount(self.atom_country[mask], weights=self.area[mask])
        total = w.sum() or 1.0
        idx = np.argsort(-w)[:limit]
        return [(int(i), float(w[i] / total)) for i in idx if w[i] / total >= 0.03]

    def atom_at(self, x, y):
        b = self.bbox
        cands = np.nonzero((b[:, 0] <= x) & (b[:, 2] >= x) & (b[:, 1] <= y) & (b[:, 3] >= y))[0]
        tri = self.tri_xy.reshape(-1, 3, 2)
        for atom in cands.tolist():
            t = tri[self._tri_off[atom]:self._tri_off[atom + 1]]
            if not len(t):
                continue
            a, b_, c = t[:, 0], t[:, 1], t[:, 2]
            d = (b_[:, 1] - c[:, 1]) * (a[:, 0] - c[:, 0]) + (c[:, 0] - b_[:, 0]) * (a[:, 1] - c[:, 1])
            with np.errstate(all="ignore"):
                l1 = ((b_[:, 1] - c[:, 1]) * (x - c[:, 0]) + (c[:, 0] - b_[:, 0]) * (y - c[:, 1])) / d
                l2 = ((c[:, 1] - a[:, 1]) * (x - c[:, 0]) + (a[:, 0] - c[:, 0]) * (y - c[:, 1])) / d
                inside = (l1 >= 0) & (l2 >= 0) & (l1 + l2 <= 1)
            if inside.any():
                return int(atom)
        return None

    def _spot(self, idx, comp):
        labs, inv = np.unique(comp[idx], return_inverse=True)
        part = idx[inv == np.argmax(np.bincount(inv, weights=self.area[idx]))]
        w = self.area[part].astype(np.float64)
        pts = self.anchors[part].astype(np.float64)
        centre = (pts * w[:, None]).sum(axis=0) / w.sum()
        near = part[np.argmin(((pts - centre) ** 2).sum(axis=1))]
        lo, hi = self.bbox[part, :2].min(axis=0), self.bbox[part, 2:].max(axis=0)
        return (float(self.anchors[near][0]), float(self.anchors[near][1]), float(hi[0] - lo[0]), float(hi[1] - lo[1]))

    def labels(self, snap, empire):
        state, _, color = self.keys(snap, empire)
        return self.labels_for(state, color)

    def labels_for(self, state, color):
        pa, pb = self._pa, self._pb
        same = color[pa] == color[pb]
        comp_any = self._components(same)
        comp_own = self._components(same & (state[pa] == color[pa]) & (state[pb] == color[pb]))
        out = []
        for key in np.unique(color):
            if key == 0:
                continue
            idx = np.nonzero(color == key)[0]
            own = idx[state[idx] == key]
            out.append((int(key), float(self.area[idx].sum()),
                        self._spot(own, comp_own) if len(own) else None, self._spot(idx, comp_any)))
        out.sort(key=lambda r: -r[1])
        return out


def load(era_id):
    path = config.CACHE_DIR / f"history_{era_id}.npz"
    return History(path) if path.exists() else None
