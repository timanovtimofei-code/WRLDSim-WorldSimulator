import pygame

from ..ui import theme
from ..ui.widgets import text_surface

SHARED_FLAG = {"MF": "FR"}


class FlagAtlas:
    def __init__(self, directory):
        self.directory = directory
        self._src = {}
        self._fitted = {}

    def source(self, code):
        if code not in self._src:
            path = self.directory / f"{code}.png"
            self._src[code] = pygame.image.load(path).convert_alpha() if code and path.exists() else None
        return self._src[code]

    def fitted(self, code, w, h):
        key = (code, w, h)
        img = self._fitted.get(key)
        if img is None:
            src = self.source(code)
            if src is None:
                return None
            k = min(w / src.get_width(), h / src.get_height())
            img = pygame.transform.smoothscale(src, (max(1, round(src.get_width() * k)),
                                                     max(1, round(src.get_height() * k))))
            mask = pygame.Surface(img.get_size(), pygame.SRCALPHA)
            radius = max(2, min(img.get_size()) // 7)
            pygame.draw.rect(mask, (255, 255, 255, 255), mask.get_rect(), border_radius=radius)
            img.blit(mask, (0, 0), special_flags=pygame.BLEND_RGBA_MULT)
            self._fitted[key] = img
        return img


class FlagLayer:
    PAD = 3
    ALWAYS_SHOWN = 24

    def __init__(self, world, atlas, featured=(), pins=None):
        # pins - {id страны: число государств эпохи на ней}: там, где флаги стран были бы анахронизмом,
        # вместо них рисуются метки.
        self.world = world
        self.atlas = atlas
        self.pins = pins
        featured = set(featured)
        order = sorted(world.countries, key=lambda c: (c.id not in featured, -c.pop_est))
        self.order = [c.index for c in order if c.iso2 not in SHARED_FLAG and (pins is None or c.id in pins)]
        self.extent = {}
        for c in world.countries:
            polys = [c.geom] if c.geom.geom_type == "Polygon" else list(c.geom.geoms)
            b = max(polys, key=lambda p: p.area).bounds
            self.extent[c.index] = max(b[2] - b[0], b[3] - b[1])
        self.placements = []

    @staticmethod
    def button_size(zoom):
        return int(max(22, min(44, 8 + zoom * 2.4)))

    def layout(self, camera, size, blocked=()):
        s = self.button_size(camera.zoom)
        screen = pygame.Rect(0, 0, *size)
        placed, taken = [], []
        for rank, idx in enumerate(self.order):
            c = self.world.countries[idx]
            if self.pins is None:
                if self.atlas.source(c.iso2) is None:
                    continue
                extent = self.extent[idx] * camera.zoom
                if extent < s * 1.3 and (rank >= self.ALWAYS_SHOWN or extent < 2):
                    continue
            sx, sy = camera.to_screen(*c.anchor, size)
            rect = pygame.Rect(0, 0, s, s)
            rect.center = (round(sx), round(sy))
            if not screen.contains(rect):
                continue
            zone = rect.inflate(6, 6)
            if zone.collidelist(taken) != -1 or zone.collidelist(blocked) != -1:
                continue
            placed.append((idx, rect))
            taken.append(zone)
        self.placements = placed

    def hit(self, pos):
        for idx, rect in reversed(self.placements):
            if rect.collidepoint(pos):
                return idx
        return None

    def _draw_pin(self, surface, rect, count, hovered):
        r = rect.inflate(6, 6) if hovered else rect
        pygame.draw.rect(surface, theme.FLAG_BG, r, border_radius=r.w // 2)
        pygame.draw.rect(surface, theme.ACCENT, r, 3 if hovered else 2, border_radius=r.w // 2)
        if count > 1:
            img = text_surface(str(count), max(12, r.w // 2), theme.TEXT, bold=True)
            surface.blit(img, img.get_rect(center=r.center))
        else:
            pygame.draw.circle(surface, theme.ACCENT, r.center, max(3, r.w // 5))

    def draw(self, surface, hover=None):
        for idx, rect in self.placements:
            hovered = idx == hover
            if self.pins is not None:
                self._draw_pin(surface, rect, self.pins.get(self.world.countries[idx].id, 1), hovered)
                continue
            r = rect.inflate(6, 6) if hovered else rect
            radius = max(4, r.w // 6)
            pygame.draw.rect(surface, theme.FLAG_BG, r, border_radius=radius)
            img = self.atlas.fitted(self.world.countries[idx].iso2, r.w - 2 * self.PAD, r.h - 2 * self.PAD)
            if img:
                surface.blit(img, img.get_rect(center=r.center))
            pygame.draw.rect(surface, theme.ACCENT if hovered else theme.FLAG_BORDER, r, 2 if hovered else 1,
                             border_radius=radius)
