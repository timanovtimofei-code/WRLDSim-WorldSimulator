import json

import numpy as np

from .. import config
from ..sim.world import World
from . import data as history

REF_GDP_PC = 40000
ERAS_WITH_WORLD = ("imperial", "modern")
ERA_RANGE = {"imperial": (1700, 1922)}


def floor_snap(h, year):
    return max([i for i, y in enumerate(h.years) if y <= year], default=0)


def focus_bbox(h, atoms, pad=(4.0, 3.0)):
    atoms = np.asarray(atoms, np.int64)
    if not len(atoms):
        return (-180.0, -60.0, 180.0, 80.0)
    pts = h.anchors[atoms].astype(float)
    wgt = np.maximum(h.area[atoms].astype(float), 1e-3)
    ox, oy = np.argsort(pts[:, 0]), np.argsort(pts[:, 1])
    cx, cy = np.cumsum(wgt[ox]) / wgt.sum(), np.cumsum(wgt[oy]) / wgt.sum()
    last = len(atoms) - 1
    x0, x1 = pts[ox[np.searchsorted(cx, 0.03)], 0], pts[ox[min(np.searchsorted(cx, 0.97), last)], 0]
    y0, y1 = pts[oy[np.searchsorted(cy, 0.03)], 1], pts[oy[min(np.searchsorted(cy, 0.97), last)], 1]
    return (x0 - pad[0], y0 - pad[1], x1 + pad[0], y1 + pad[1])


def _cache(app, name):
    return app.__dict__.setdefault(name, {})


def hist(app, era_id):
    cache = _cache(app, "_history")
    if era_id not in cache:
        cache[era_id] = history.load(era_id)
    return cache[era_id]


def has_world(app, era_id):
    return era_id in ERAS_WITH_WORLD and hist(app, era_id) is not None


def realm_cfg(app):
    cache = _cache(app, "_realm_cfg")
    if "cfg" not in cache:
        with open(config.DATA_DIR / "realm.json", encoding="utf-8") as f:
            cache["cfg"] = json.load(f)
    return cache["cfg"]


def lands(app):
    cache = _cache(app, "_lands")
    if "v" not in cache:
        pops, gpcs, conts = [], [], []
        for c in app.world.countries:
            info = app.country_info.get(c.id, {})
            pop = info.get("population") or c.pop_est or 0.0
            gdp = info.get("gdp_usd") or c.gdp_md * 1e6
            pops.append(float(pop))
            gpcs.append(float(gdp / pop) if pop > 0 and gdp > 0 else 10000.0)
            conts.append(c.continent)
        cache["v"] = {"pop": np.array(pops), "gdp_pc": np.array(gpcs), "continent": conts}
    return cache["v"]


def atom_names(app, era_id):
    cache = _cache(app, "_atom_names")
    if era_id not in cache:
        h = hist(app, era_id)
        regions = app.world.regions
        cache[era_id] = [regions[int(r)].display_name for r in h.atom_region]
    return cache[era_id]


def city_data(era_id):
    try:
        with open(config.DATA_DIR / f"cities_{era_id}.json", encoding="utf-8") as f:
            return json.load(f)
    except OSError:
        return None


def create_world(app, era_id, polity, country, start, now, year_offset=0, history_mode=None):
    h = hist(app, era_id)
    if h is None or era_id not in ERAS_WITH_WORLD:
        return None
    year = start["year"]
    snap = max([i for i, y in enumerate(h.years) if y <= year], default=0)
    known = {}
    if polity.get("generic"):
        if era_id != "modern":
            return None
        player = World.resolve_player(h, snap, "", [], country.iso2)
    else:
        if era_id == "modern":
            return None          # государства 1922-1991 требуют снимков карты тех лет
        ids = [app.world.by_id[i].index for i in polity.get("map", []) if i in app.world.by_id]
        player = World.resolve_player(h, snap, polity["id"], ids)
        if player >= 0 and polity.get("wealth"):
            known = {player: float(polity["wealth"]) * REF_GDP_PC}
    if player < 0:
        return None
    month = now.year * 12 + now.month - 1
    world = World.create(h, realm_cfg(app), era_id, year, month, lands(app), player, city_data(era_id), year_offset,
                         known, history_mode)
    world.atom_names = atom_names(app, era_id)
    return world


def load_world(app, data):
    h = hist(app, data["era"])
    if h is None:
        return None
    world = World.from_json(h, realm_cfg(app), data)
    world.atom_names = atom_names(app, data["era"])
    return world


def layer(app, era_id):
    from ..map.atlas import AtlasLayer
    cache = _cache(app, "_atlas_layers")
    cur = cache.get(era_id)
    if cur is None or cur.gpu is not app.gpu:
        cur = cache[era_id] = AtlasLayer(hist(app, era_id), app.gpu)
    return cur
