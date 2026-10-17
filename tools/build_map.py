# Скачивает Natural Earth и собирает data/cache/world.pkl: python tools/build_map.py
import io
import pickle
import sys
import urllib.request
import zipfile
from pathlib import Path

import numpy as np
import shapefile
import shapely
from shapely.geometry import shape
from shapely.ops import polylabel

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from wrldsim import config  # noqa: E402

BASE_URL = "https://naciscdn.org/naturalearth/{scale}/{cat}/ne_{scale}_{name}.zip"
SOURCES = {
    "countries50": ("50m", "cultural", "admin_0_countries"),
    "countries110": ("110m", "cultural", "admin_0_countries"),
    "borders50": ("50m", "cultural", "admin_0_boundary_lines_land"),
    "borders110": ("110m", "cultural", "admin_0_boundary_lines_land"),
    "coast50": ("50m", "physical", "coastline"),
    "coast110": ("110m", "physical", "coastline"),
    "admin1": ("10m", "cultural", "admin_1_states_provinces"),
    "admin1_lines": ("10m", "cultural", "admin_1_states_provinces_lines"),
}

ADMIN1_SIMPLIFY = 0.01
FOCUS_AREA_SHARE = 0.15


def download(key):
    scale, cat, name = SOURCES[key]
    dest = config.RAW_DIR / f"ne_{scale}_{name}.zip"
    if dest.exists():
        return dest
    url = BASE_URL.format(scale=scale, cat=cat, name=name)
    print(f"  скачиваю {url}")
    req = urllib.request.Request(url, headers={"User-Agent": "WrldSim/0.1"})
    with urllib.request.urlopen(req, timeout=180) as resp:
        data = resp.read()
    config.RAW_DIR.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)
    return dest


def project(geom):
    return shapely.transform(geom, lambda c: c * np.array([1.0, -1.0]))


def read_features(key):
    with zipfile.ZipFile(download(key)) as zf:
        names = zf.namelist()

        def member(ext):
            return io.BytesIO(zf.read(next(n for n in names if n.lower().endswith(ext))))

        reader = shapefile.Reader(shp=member(".shp"), dbf=member(".dbf"), shx=member(".shx"),
                                  encoding="utf-8", encodingErrors="replace")
        fields = [f[0].lower() for f in reader.fields[1:]]
        for sr in reader.iterShapeRecords():
            if sr.shape.shapeType == shapefile.NULL or not sr.shape.points:
                continue
            props = dict(zip(fields, sr.record))
            geom = shape(sr.shape.__geo_interface__)
            if geom.geom_type in ("Polygon", "MultiPolygon") and not geom.is_valid:
                geom = geom.buffer(0)
            yield props, project(geom)


def polygons(geom):
    if geom.geom_type == "Polygon":
        return [geom]
    if hasattr(geom, "geoms"):
        return [g for part in geom.geoms for g in polygons(part)]
    return []


def lines(geom):
    if geom.geom_type == "LineString":
        return [geom]
    if geom.geom_type in ("Polygon", "MultiPolygon"):
        return lines(geom.boundary)
    if hasattr(geom, "geoms"):
        return [g for part in geom.geoms for g in lines(part)]
    return []


def build_layer(items):
    pts, off, bbox, owner = [], [0], [], []
    for coords, own in items:
        arr = np.asarray(coords, dtype=np.float32)[:, :2]
        if len(arr) < 2:
            continue
        pts.append(arr)
        off.append(off[-1] + len(arr))
        bbox.append([arr[:, 0].min(), arr[:, 1].min(), arr[:, 0].max(), arr[:, 1].max()])
        owner.append(own)
    return {
        "pts": np.concatenate(pts),
        "off": np.array(off, dtype=np.int64),
        "bbox": np.array(bbox, dtype=np.float32),
        "owner": np.array(owner, dtype=np.int32),
    }


def text(props, *keys):
    for k in keys:
        v = props.get(k)
        if isinstance(v, str) and v.strip() and v.strip() != "-99":
            return v.strip()
    return ""


def number(props, key):
    try:
        v = float(props.get(key) or 0)
    except (TypeError, ValueError):
        return 0.0
    return max(v, 0.0)


def country_id(props, used):
    for key in ("iso_a2_eh", "iso_a2"):
        v = text(props, key).upper()
        if len(v) == 2 and v.isalpha() and v not in used:
            return v
    return text(props, "adm0_a3").upper()


def build_countries():
    countries, land50, by_a3 = [], [], {}
    used = set()
    for props, geom in read_features("countries50"):
        polys = polygons(geom)
        if not polys:
            continue
        idx = len(countries)
        cid = country_id(props, used)
        used.add(cid)
        a3 = text(props, "adm0_a3").upper()
        by_a3[a3] = idx

        largest = max(polys, key=lambda p: p.area)
        try:
            anchor = polylabel(largest, tolerance=0.05)
        except Exception:
            anchor = largest.representative_point()
        focus = [p.bounds for p in polys if p.area >= largest.area * FOCUS_AREA_SHARE]
        focus_bbox = (min(b[0] for b in focus), min(b[1] for b in focus),
                      max(b[2] for b in focus), max(b[3] for b in focus))

        countries.append({
            "id": cid,
            "adm0_a3": a3,
            "iso2": cid if len(cid) == 2 else "",
            "name": text(props, "name", "admin"),
            "name_ru": text(props, "name_ru"),
            "continent": text(props, "continent"),
            "subregion": text(props, "subregion"),
            "pop_est": number(props, "pop_est"),
            "gdp_md": number(props, "gdp_md"),
            "anchor": (float(anchor.x), float(anchor.y)),
            "focus_bbox": tuple(float(v) for v in focus_bbox),
            "geom": geom,
        })
        land50.extend((p.exterior.coords, idx) for p in polys)

    land110 = []
    for props, geom in read_features("countries110"):
        idx = by_a3.get(text(props, "adm0_a3").upper(), -1)
        land110.extend((p.exterior.coords, idx) for p in polygons(geom))

    return countries, by_a3, land50, land110


def build_lines(key, owner_of=None, simplify=0.0):
    # Линии склеиваются по владельцу: в исходниках они нарезаны мелко и на дальнем масштабе рвались бы.
    groups = {}
    for props, geom in read_features(key):
        groups.setdefault(owner_of(props) if owner_of else -1, []).append(geom)
    items = []
    for own, geoms in groups.items():
        merged = shapely.line_merge(shapely.union_all(geoms))
        if simplify:
            merged = merged.simplify(simplify, preserve_topology=False)
        items.extend((ln.coords, own) for ln in lines(merged))
    return build_layer(items)


def main():
    print("Страны...")
    countries, by_a3, land50, land110 = build_countries()
    by_iso = {c["iso2"]: i for i, c in enumerate(countries) if c["iso2"]}

    def owner_of(props):
        idx = by_a3.get(text(props, "adm0_a3").upper())
        if idx is None:
            idx = by_iso.get(text(props, "iso_a2").upper(), -1)
        return idx

    print("Границы и береговые линии...")
    layers = {
        "land50": build_layer(land50),
        "land110": build_layer(land110),
        "borders50": build_lines("borders50"),
        "borders110": build_lines("borders110"),
        "coast50": build_lines("coast50"),
        "coast110": build_lines("coast110"),
    }

    print("Регионы (штаты, провинции, области)...")
    layers["admin1"] = build_lines("admin1_lines", owner_of, simplify=ADMIN1_SIMPLIFY)
    regions, orphans = [], 0
    for props, geom in read_features("admin1"):
        idx = owner_of(props)
        if idx < 0:
            orphans += 1
            continue
        geom = geom.simplify(ADMIN1_SIMPLIFY, preserve_topology=True)
        if geom.is_empty:
            continue
        regions.append({
            "country": idx,
            "name": text(props, "name_en", "name"),
            "name_ru": text(props, "name_ru"),
            "kind": text(props, "type_en", "type"),
            "geom": geom,
        })

    config.CACHE_DIR.mkdir(parents=True, exist_ok=True)
    with open(config.WORLD_CACHE, "wb") as f:
        pickle.dump({"version": 1, "countries": countries, "layers": layers, "regions": regions},
                    f, protocol=pickle.HIGHEST_PROTOCOL)

    size_mb = config.WORLD_CACHE.stat().st_size / 1e6
    print(f"Готово: {len(countries)} стран, {len(regions)} регионов "
          f"(без страны: {orphans}), {config.WORLD_CACHE} ({size_mb:.1f} МБ)")
    for name, layer in layers.items():
        print(f"  {name:12s} {len(layer['off']) - 1:6d} линий, {len(layer['pts']):8d} точек")


if __name__ == "__main__":
    main()
