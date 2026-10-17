import numpy as np
import pygame

from ..ui import theme
from . import sphere

RASTER_W, RASTER_H = 2048, 1024
BORDER_COLOR = (14, 14, 20)
WIDTHS = (0.8, 1.2, 1.9)
ALPHAS = (0.0, 0.55, 0.9)
PROVINCE_ALPHA = 0.28
HIGHLIGHT = 0.30
GLOBE_FILL = 0.55


class AtlasLayer:
    def __init__(self, hist, gpu):
        self.hist = hist
        self.gpu = gpu
        self.snap = None
        self.empire = False
        self.provinces = False
        self._info = None
        self._palette_key = None
        self._stamp = None
        self._pal_rgb = hist.palette
        self._soft = {}
        self._soft_order = []
        self.tex = self.fill = self.lines = None
        self.fill_globe = None
        if gpu is not None:
            self._build_gpu()

    def _build_gpu(self):
        from ..gpu import AtlasTex, Mesh
        h = self.hist
        self.tex = AtlasTex()
        n = len(h.tri_atom)
        fill = np.empty((n, 3), np.float32)
        fill[:, :2] = h.tri_xy
        fill[:, 2] = h.tri_atom
        self.fill = Mesh(fill, 3)
        # Граница между атомами рисуется один раз (a < b); если соседа видно только с одной стороны, берём и a > b.
        a, b = h.seg_a.astype(np.int64), h.seg_b.astype(np.int64)
        has = b >= 0
        lo, hi = np.minimum(a, b), np.maximum(a, b)
        pair = lo * (h.atoms + 1) + hi
        forward = has & (a < b)
        covered = np.isin(pair, pair[forward])
        keep = forward | (has & (a > b) & ~covered)
        seg = h.seg[keep]
        ab = np.stack([a[keep], b[keep]], 1).astype(np.float32)
        verts = np.empty((len(seg) * 2, 4), np.float32)
        verts[0::2, :2], verts[1::2, :2] = seg[:, :2], seg[:, 2:]
        verts[0::2, 2:], verts[1::2, 2:] = ab, ab
        self.lines = Mesh(verts, 4)

    def release(self):
        if self.gpu is None or self.tex is None:
            return
        self.tex.release()
        self.fill.release()
        self.lines.release()
        if self.fill_globe is not None:
            self.fill_globe.release()
            self.fill_globe = None
        self.tex = None

    def set_state(self, snap, empire):
        stamp = ("snap", snap, empire)
        if stamp == self._stamp and self._info is not None:
            return False
        self.snap, self.empire = snap, empire
        self._pal_rgb = self.hist.palette
        self._palette_key = None
        state, top, color = self.hist.keys(snap, empire)
        self._load(state, top, color, stamp)
        return True

    def set_world(self, world, empire=True):
        stamp = ("world", id(world), world.version, empire)
        if stamp == self._stamp and self._info is not None:
            return False
        self.snap, self.empire = None, empire
        self._pal_rgb = world.palette()
        self._palette_key = None
        state = world.owner.astype(np.int32)
        top = world.roots()[state].astype(np.int32)
        self._load(state, top, top if empire else state, stamp)
        return True

    def _load(self, state, top, color, stamp):
        info = np.zeros((self.hist.atoms, 4), np.float32)
        info[:, 0], info[:, 1], info[:, 2] = color, state, top
        self._info = info
        self._stamp = stamp
        self._soft_stamp = None
        if self.tex is not None:
            self.tex.set_atoms(info)

    def arrays(self):
        return (self._info[:, 1].astype(np.int32), self._info[:, 2].astype(np.int32),
                self._info[:, 0].astype(np.int32))

    def color_key(self, atom):
        return int(self._info[atom, 0]) if atom is not None and self._info is not None else 0

    def _palette(self):
        rgba = np.empty((len(self._pal_rgb), 4), np.uint8)
        rgba[:, :3] = self._pal_rgb
        rgba[:, 3] = 255
        rgba[0, :3] = theme.LAND
        return rgba

    def _sync_palette(self):
        key = (tuple(theme.LAND), self._stamp)
        if key != self._palette_key:
            self._palette_key = key
            if self.tex is not None:
                self.tex.set_palette(self._palette())
            self._soft.clear()
            self._soft_order.clear()

    def render(self, surface, camera, highlight=-1, dim=-1, dim_amt=0.6):
        self._sync_palette()
        if self.tex is not None and surface is self.gpu.ui:
            g = self.gpu
            g.flush()
            fill, alpha = self.fill, 1.0
            if camera.globe:
                g.globe_base(camera)
                if self.fill_globe is None:
                    from ..gpu import Mesh
                    h = self.hist
                    v = np.empty((len(h.tri_atom), 3), np.float32)
                    v[:, :2], v[:, 2] = h.tri_xy, h.tri_atom
                    self.fill_globe = Mesh(sphere.subdivide(v), 3)
                fill, alpha = self.fill_globe, GLOBE_FILL
            g.atlas_fill(fill, camera, self.tex, hl=highlight, hl_amt=HIGHLIGHT if highlight > 0 else 0.0,
                         dim=dim, dim_amt=dim_amt if dim > 0 else 0.0, dim_color=theme.LAND, alpha=alpha)
            prov = PROVINCE_ALPHA if self.provinces or camera.zoom >= 22 else 0.0
            g.atlas_lines(self.lines, camera, self.tex, BORDER_COLOR, WIDTHS, (prov, ALPHAS[1], ALPHAS[2]))
            return
        self._render_soft(surface, camera, highlight)

    def _raster(self):
        key = self._stamp
        img = self._soft.get(key)
        if img is not None:
            return img
        h = self.hist
        img = pygame.Surface((RASTER_W, RASTER_H)).convert()
        img.fill(theme.OCEAN)
        pal = self._palette()
        color = self._info[:, 0].astype(np.int64)
        sx, sy = RASTER_W / 360.0, RASTER_H / 180.0
        tri = h.tri_xy.reshape(-1, 3, 2).astype(np.float64)
        px = ((tri[..., 0] + 180.0) * sx).tolist()
        py = ((tri[..., 1] + 90.0) * sy).tolist()
        cols = pal[color[h.tri_atom[::3]], :3].tolist()
        for i in range(len(px)):
            pygame.draw.polygon(img, cols[i], ((px[i][0], py[i][0]), (px[i][1], py[i][1]), (px[i][2], py[i][2])))
        a, b = h.seg_a.astype(np.int64), h.seg_b.astype(np.int64)
        ok = (b >= 0) & (a < b)
        level = np.where(self._info[a, 2] != self._info[np.maximum(b, 0), 2], 3,
                         np.where(self._info[a, 1] != self._info[np.maximum(b, 0), 1], 2, 1))
        seg = h.seg[ok & (level >= 2)]
        for x0, y0, x1, y1 in seg.astype(np.float64).tolist():
            pygame.draw.line(img, BORDER_COLOR, ((x0 + 180.0) * sx, (y0 + 90.0) * sy),
                             ((x1 + 180.0) * sx, (y1 + 90.0) * sy))
        self._soft[key] = img
        self._soft_order.append(key)
        if len(self._soft_order) > 4:
            self._soft.pop(self._soft_order.pop(0), None)
        return img

    def _render_soft(self, surface, camera, highlight):
        size = surface.get_size()
        surface.fill(theme.OCEAN)
        raster = self._raster()
        x0, y0, x1, y1 = camera.view_bounds(size)
        sx, sy = RASTER_W / 360.0, RASTER_H / 180.0
        src = pygame.Rect(int((x0 + 180) * sx), int((y0 + 90) * sy),
                          max(1, int((x1 - x0) * sx) + 1), max(1, int((y1 - y0) * sy) + 1))
        clip = src.clip(raster.get_rect())
        if clip.w < 1 or clip.h < 1:
            return
        dst = pygame.Rect(round((clip.x / sx - 180 - camera.cx) * camera.zoom + size[0] / 2),
                          round((clip.y / sy - 90 - camera.cy) * camera.zoom + size[1] / 2),
                          max(1, round(clip.w / sx * camera.zoom)), max(1, round(clip.h / sy * camera.zoom)))
        piece = raster.subsurface(clip)
        surface.blit(pygame.transform.smoothscale(piece, dst.size) if dst.size != clip.size else piece, dst)
        if highlight > 0:
            self._highlight_soft(surface, camera, highlight)

    def _highlight_soft(self, surface, camera, key):
        h, size = self.hist, surface.get_size()
        atoms = np.nonzero(self._info[:, 0] == key)[0]
        overlay = pygame.Surface(size, pygame.SRCALPHA)
        tri = h.tri_xy.reshape(-1, 3, 2)
        for atom in atoms.tolist():
            for t in tri[h._tri_off[atom]:h._tri_off[atom + 1]]:
                pts = [camera.to_screen(float(x), float(y), size) for x, y in t]
                pygame.draw.polygon(overlay, (255, 255, 255, int(255 * HIGHLIGHT)), pts)
        surface.blit(overlay, (0, 0))
