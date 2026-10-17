import pickle
from dataclasses import dataclass, field

import numpy as np
from shapely import Point, STRtree


@dataclass
class Layer:
    pts: np.ndarray
    off: np.ndarray
    bbox: np.ndarray
    owner: np.ndarray

    def ring(self, i):
        return self.pts[self.off[i]:self.off[i + 1]]


@dataclass
class Country:
    index: int
    id: str
    adm0_a3: str
    iso2: str
    name: str
    name_ru: str
    continent: str
    subregion: str
    pop_est: float
    gdp_md: float
    anchor: tuple
    focus_bbox: tuple
    geom: object
    regions: list = field(default_factory=list)

    @property
    def display_name(self):
        return self.name_ru or self.name


@dataclass
class Region:
    index: int
    country: int
    name: str
    name_ru: str
    kind: str
    geom: object
    _rings: list = None

    @property
    def display_name(self):
        return self.name_ru or self.name

    def rings(self):
        if self._rings is None:
            polys = [self.geom] if self.geom.geom_type == "Polygon" else list(getattr(self.geom, "geoms", []))
            self._rings = [np.asarray(p.exterior.coords, dtype=np.float32)
                           for p in polys if p.geom_type == "Polygon"]
        return self._rings


class WorldData:
    def __init__(self, raw):
        self.countries = [Country(index=i, **c) for i, c in enumerate(raw["countries"])]
        self.by_id = {c.id: c for c in self.countries}
        self.layers = {name: Layer(**layer) for name, layer in raw["layers"].items()}
        self.regions = [Region(index=i, **r) for i, r in enumerate(raw["regions"])]
        for r in self.regions:
            self.countries[r.country].regions.append(r.index)

        self._country_tree = STRtree([c.geom for c in self.countries])
        self._region_trees = {}
        self.owner_rings = {name: self._group_by_owner(self.layers[name]) for name in ("land50", "land110")}

    @staticmethod
    def _group_by_owner(layer):
        groups = {}
        for i, own in enumerate(layer.owner):
            groups.setdefault(int(own), []).append(i)
        return groups

    def country_at(self, x, y):
        hits = self._country_tree.query(Point(x, y), predicate="intersects")
        if len(hits) == 0:
            return None
        # при наложении (анклавы, спорные зоны) берём меньшую страну
        return min((self.countries[i] for i in hits), key=lambda c: c.geom.area)

    def region_at(self, country, x, y):
        tree = self._region_trees.get(country.index)
        if tree is None:
            tree = STRtree([self.regions[i].geom for i in country.regions]) if country.regions else None
            self._region_trees[country.index] = tree
        if tree is None:
            return None
        hits = tree.query(Point(x, y), predicate="intersects")
        return self.regions[country.regions[int(hits[0])]] if len(hits) else None


def load_world(path):
    with open(path, "rb") as f:
        return WorldData(pickle.load(f))
