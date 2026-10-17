import numpy as np
import pygame
import shapely

from ..ui import theme
from . import sphere


def _segments(layer, closed=False):
    pts, off = layer.pts, layer.off
    owner = np.repeat(layer.owner.astype(np.float32), np.diff(off))
    keep = np.ones(len(pts) - 1, bool)
    keep[off[1:-1] - 1] = False                    # не соединяем конец одного кольца с началом следующего
    a, b = np.nonzero(keep)[0], np.nonzero(keep)[0] + 1
    if closed:
        ends = off[1:] - 1
        a, b = np.concatenate([a, ends]), np.concatenate([b, off[:-1]])
    seg = np.empty((len(a) * 2, 3), np.float32)
    seg[0::2, :2], seg[1::2, :2] = pts[a], pts[b]
    seg[0::2, 2], seg[1::2, 2] = owner[a], owner[a]
    return seg


def _triangles(geoms, owners):
    tris = shapely.constrained_delaunay_triangles(geoms)
    parts, idx = shapely.get_parts(tris, return_index=True)
    if len(parts) == 0:
        return np.zeros((0, 3), np.float32)
    coords = shapely.get_coordinates(parts).reshape(-1, 4, 2)[:, :3].reshape(-1, 2)
    out = np.empty((len(coords), 3), np.float32)
    out[:, :2] = coords
    out[:, 2] = np.repeat(np.asarray(owners, np.float32)[idx], 3)
    return out


def _layer_triangles(layer):
    sizes = np.diff(layer.off)
    ok = np.nonzero(sizes >= 4)[0]
    ring_id = np.repeat(np.arange(len(sizes)), sizes)
    mask = np.isin(ring_id, ok)
    rings = shapely.linearrings(layer.pts[mask].astype(np.float64), indices=ring_id[mask])
    polys = shapely.make_valid(shapely.polygons(rings))
    return _triangles(polys, layer.owner[ok])


class GpuMap:
    def __init__(self, gpu, world):
        from ..gpu import Mesh
        self.gpu, self.world = gpu, world
        self._Mesh = Mesh
        self.mesh = {}
        for lod in ("110", "50"):
            land = world.layers["land" + lod]
            self.mesh["land" + lod] = Mesh(_layer_triangles(land), 3)
            self.mesh["outline" + lod] = Mesh(_segments(land, closed=True), 3)
            for name in ("borders", "coast"):
                self.mesh[name + lod] = Mesh(_segments(world.layers[name + lod]), 3)
        self.mesh["admin1"] = Mesh(_segments(world.layers["admin1"]), 3)
        self.grid = Mesh(dynamic=True)
        self._regions = {}
        self._globe = {}

    def globe_mesh(self, name):
        m = self._globe.get(name)
        if m is None:
            if name.startswith("grid"):
                m = self._Mesh(sphere.graticule(int(name[4:])))
            else:
                m = self._Mesh(sphere.subdivide(_layer_triangles(self.world.layers[name])), 3)
            self._globe[name] = m
        return m

    def land(self, lod, globe):
        return self.globe_mesh("land" + lod) if globe else self.mesh["land" + lod]

    def region_meshes(self, region):
        m = self._regions.get(region.index)
        if m is None:
            if len(self._regions) > 128:
                for fill, line in self._regions.values():
                    fill.release()
                    line.release()
                self._regions.clear()
            tri = _triangles(np.array([region.geom]), [region.country])
            fill = self._Mesh(sphere.subdivide(tri) if len(tri) else tri, 3)
            segs = []
            for ring in region.rings():
                if len(ring) >= 2:
                    s = np.empty(((len(ring) - 1) * 2, 3), np.float32)
                    s[0::2, :2], s[1::2, :2] = ring[:-1], ring[1:]
                    s[:, 2] = region.country
                    segs.append(s)
            line = self._Mesh(np.concatenate(segs) if segs else np.zeros((0, 3), np.float32), 3)
            m = self._regions[region.index] = (fill, line)
        return m

    def draw(self, camera, lod, focus, admin1_world_zoom):
        g, m = self.gpu, self.mesh
        step = 30 if camera.zoom < 10 else 10 if camera.zoom < 40 else 5
        if camera.globe:
            g.lines(self.globe_mesh(f"grid{step}"), camera, theme.TEXT, 1.0, alpha=0.08)
            if focus is not None:
                g.fill(self.land(lod, True), camera, theme.TEXT, mode=2, owner=focus, alpha=0.08)
                g.lines(m["admin1"], camera, theme.TEXT, 1.0, mode=2, owner=focus, alpha=0.35)
            elif camera.zoom >= admin1_world_zoom:
                g.lines(m["admin1"], camera, theme.TEXT, 1.0, alpha=0.25)
            g.lines(m["borders" + lod], camera, (255, 236, 160), 1.2, alpha=0.75)
            g.lines(m["coast" + lod], camera, theme.TEXT, 1.0, alpha=0.35)
            return
        lines = []
        for lon in range(-180, 181, step):
            lines += [lon, -90, lon, 90]
        for lat in range(-90, 91, step):
            lines += [-180, lat, 180, lat]
        self.grid.upload(np.array(lines, np.float32))
        g.lines(self.grid, camera, theme.GRID, 1.0)

        land = m["land" + lod]
        if focus is None:
            g.fill(land, camera, theme.LAND)
        else:
            g.fill(land, camera, theme.LAND_DIM, mode=1, owner=focus)
            g.fill(land, camera, theme.LAND_FOCUS, mode=2, owner=focus)
        if focus is not None:
            g.lines(m["admin1"], camera, theme.ADMIN1_FOCUS, 1.0, mode=2, owner=focus)
        elif camera.zoom >= admin1_world_zoom:
            g.lines(m["admin1"], camera, theme.ADMIN1, 1.0)
        g.lines(m["borders" + lod], camera, theme.BORDER, 1.1)
        g.lines(m["coast" + lod], camera, theme.COAST, 1.1)


ACCENT = object()


class MapRenderer:
    LOD_SWITCH_ZOOM = 7.0        # ниже - 1:110m, выше - 1:50m
    ADMIN1_WORLD_ZOOM = 14.0

    def __init__(self, world):
        self.world = world
        self._base = None
        self._key = None
        self.gpu = None

    def attach_gpu(self, gpu):
        self.gpu = GpuMap(gpu, self.world) if gpu else None

    def _on_gpu(self, surface):
        return self.gpu is not None and surface is self.gpu.gpu.ui

    def lod(self, zoom):
        return "50" if zoom >= self.LOD_SWITCH_ZOOM else "110"

    def invalidate(self):
        self._key = None

    def render(self, surface, camera, focus=None):
        if self._on_gpu(surface):
            self.gpu.gpu.flush()
            if camera.globe:
                self.gpu.gpu.globe_base(camera)
            self.gpu.draw(camera, self.lod(camera.zoom), focus, self.ADMIN1_WORLD_ZOOM)
            return
        size = surface.get_size()
        if self._base is None or self._base.get_size() != size:
            self._base = pygame.Surface(size).convert()
            self._key = None
        key = (size, camera.key(), focus)
        if key != self._key:
            self._draw_base(self._base, camera, focus)
            self._key = key
        surface.blit(self._base, (0, 0))

    def _draw_base(self, surf, camera, focus):
        size = surf.get_size()
        surf.fill(theme.OCEAN)
        self._draw_graticule(surf, camera, size)

        lod = self.lod(camera.zoom)
        land = self.world.layers["land" + lod]
        bounds = camera.view_bounds(size)
        fill = theme.LAND if focus is None else theme.LAND_DIM
        focus_rings = []
        for i in self._visible(land, bounds, camera.zoom, 1.0):
            if focus is not None and land.owner[i] == focus:
                focus_rings.append(i)
            else:
                self._polygon(surf, fill, land.ring(i), camera, size)
        for i in focus_rings:  # поверх соседей, чтобы анклавы не перекрывали страну
            self._polygon(surf, theme.LAND_FOCUS, land.ring(i), camera, size)

        admin1 = self.world.layers["admin1"]
        if focus is not None:
            for i in self._visible(admin1, bounds, camera.zoom, 0.5, owner=focus):
                self._lines(surf, theme.ADMIN1_FOCUS, admin1.ring(i), camera, size)
        elif camera.zoom >= self.ADMIN1_WORLD_ZOOM:
            for i in self._visible(admin1, bounds, camera.zoom, 0.5):
                self._lines(surf, theme.ADMIN1, admin1.ring(i), camera, size)

        for name, color in (("borders", theme.BORDER), ("coast", theme.COAST)):
            layer = self.world.layers[name + lod]
            for i in self._visible(layer, bounds, camera.zoom, 1.0):
                self._lines(surf, color, layer.ring(i), camera, size)

    def _draw_graticule(self, surf, camera, size):
        step = 30 if camera.zoom < 10 else 10 if camera.zoom < 40 else 5
        top_left = camera.to_screen(-180, -90, size)
        bottom_right = camera.to_screen(180, 90, size)
        for lon in range(-180, 181, step):
            x = camera.to_screen(lon, 0, size)[0]
            pygame.draw.line(surf, theme.GRID, (x, top_left[1]), (x, bottom_right[1]))
        for lat in range(-90, 91, step):
            y = camera.to_screen(0, -lat, size)[1]
            pygame.draw.line(surf, theme.GRID, (top_left[0], y), (bottom_right[0], y))

    def country_rings(self, camera, idx):
        land = self.world.layers["land" + self.lod(camera.zoom)]
        return [land.ring(i) for i in self.world.owner_rings["land" + self.lod(camera.zoom)].get(idx, [])]

    def highlight_country(self, surface, camera, idx, fill=None, outline=ACCENT, width=2):
        outline = theme.ACCENT if outline is ACCENT else outline
        if self._on_gpu(surface):
            g, lod = self.gpu, self.lod(camera.zoom)
            g.gpu.flush()
            if fill:
                g.gpu.fill(g.land(lod, camera.globe), camera, fill, mode=2, owner=idx, alpha=0.45 if camera.globe else 1.0)
            if outline:
                g.gpu.lines(g.mesh["outline" + lod], camera, outline, width, mode=2, owner=idx)
            return
        self._highlight(surface, camera, self.country_rings(camera, idx), fill, outline, width)

    def highlight_region(self, surface, camera, region, fill=None, outline=ACCENT, width=2):
        outline = theme.ACCENT if outline is ACCENT else outline
        if self._on_gpu(surface):
            g = self.gpu
            g.gpu.flush()
            fill_mesh, line_mesh = g.region_meshes(region)
            if fill:
                g.gpu.fill(fill_mesh, camera, fill, alpha=0.5 if camera.globe else 1.0)
            if outline:
                g.gpu.lines(line_mesh, camera, outline, width)
            return
        self._highlight(surface, camera, region.rings(), fill, outline, width)

    def _highlight(self, surface, camera, rings, fill, outline, width):
        size = surface.get_size()
        for ring in rings:
            span = max(np.ptp(ring[:, 0]), np.ptp(ring[:, 1])) * camera.zoom
            if span < 1.5:
                continue
            pts = self._project(ring, camera, size)
            if fill and len(pts) >= 3:
                pygame.draw.polygon(surface, fill, pts)
            if outline:
                pygame.draw.lines(surface, outline, True, pts, width)

    @staticmethod
    def _visible(layer, bounds, zoom, min_px, owner=None):
        b = layer.bbox
        mask = (b[:, 2] >= bounds[0]) & (b[:, 0] <= bounds[2]) & (b[:, 3] >= bounds[1]) & (b[:, 1] <= bounds[3])
        mask &= np.maximum(b[:, 2] - b[:, 0], b[:, 3] - b[:, 1]) * zoom >= min_px
        if owner is not None:
            mask &= layer.owner == owner
        return np.nonzero(mask)[0]

    @staticmethod
    def _project(ring, camera, size):
        pts = (ring - (camera.cx, camera.cy)) * camera.zoom + (size[0] / 2, size[1] / 2)
        return pts.tolist()

    def _polygon(self, surf, color, ring, camera, size):
        if len(ring) >= 3:
            pygame.draw.polygon(surf, color, self._project(ring, camera, size))

    def _lines(self, surf, color, ring, camera, size):
        if len(ring) >= 2:
            pygame.draw.aalines(surf, color, False, self._project(ring, camera, size))
