import re

import pygame

from .. import config
from ..map.flags import FlagAtlas
from ..ui import theme
from ..ui.widgets import text_surface

HISTORY_DIR = config.DATA_DIR / "flags_history"
_FILE = re.compile(r"^(?P<id>[A-Za-z0-9_\-]+?)(?:@(?P<year>-?\d+))?\.png$")


class HistoricFlags:
    def __init__(self):
        self.atlas = FlagAtlas(HISTORY_DIR)
        self._index = None

    def _scan(self):
        index = {}
        try:
            for path in HISTORY_DIR.iterdir():
                m = _FILE.match(path.name)
                if m:
                    index.setdefault(m["id"], []).append((int(m["year"]) if m["year"] else -10 ** 6, path.stem))
        except OSError:
            pass
        for items in index.values():
            items.sort()
        return index

    def code(self, polity_id, year):
        if self._index is None:
            self._index = self._scan()
        best = None
        for start, stem in self._index.get(polity_id, ()):
            if start <= year:
                best = stem
        return best

    def fitted(self, polity_id, year, w, h):
        stem = self.code(polity_id, year)
        return self.atlas.fitted(stem, w, h) if stem else None


def _hflags(app):
    if not hasattr(app, "_hflags"):
        app._hflags = HistoricFlags()
    return app._hflags


def flag_image(app, polity, year, w, h):
    img = _hflags(app).fitted(polity.id, year, w, h)
    if img is not None:
        return img
    if polity.iso2 and polity.flag and year >= (polity.flag_from or 0):
        return app.flags.fitted(polity.flag, w, h)
    return None


def draw_polity_flag(surface, app, polity, year, rect):
    img = flag_image(app, polity, year, rect.w, rect.h)
    if img is not None:
        frame = img.get_rect(center=rect.center)
        surface.blit(img, frame)
        pygame.draw.rect(surface, theme.FLAG_BORDER, frame.inflate(2, 2), 1, border_radius=8)
        return True
    pygame.draw.rect(surface, polity.color, rect, border_radius=8)
    pygame.draw.rect(surface, theme.mix(polity.color, (255, 255, 255), 0.35), rect, 2, border_radius=8)
    letter = (polity.title[:1] or "?").upper()
    img = text_surface(letter, max(12, rect.h // 2 + 6), (250, 250, 250), True)
    surface.blit(img, img.get_rect(center=rect.center))
    return False
