import numpy as np
import pygame

from ..history import loader
from ..map.controller import MapController
from ..map.flags import FlagLayer
from ..map.labels import draw_labels
from ..sim.world import World
from ..ui import fonts, theme
from ..ui.widgets import Button, draw_panel, draw_text, draw_tooltip, ellipsize, text_surface
from .base import State, draw_topbar, topbar_rect

HINT = "ЛКМ по флагу или стране: открыть  ·  Колесо: масштаб  ·  Перетаскивание: карта  ·  Esc: меню"
HINT_PINS = ("ЛКМ по метке: государство эпохи  ·  Карта показывает современные границы  ·  Колесо: масштаб  ·  "
             "Esc: меню")
HINT_HISTORY = "ЛКМ по государству с красной меткой: играть  ·  Стрелки: год карты  ·  Колесо: масштаб  ·  Esc: меню"
PLAY_AHEAD = 25


class WorldMapState(State):
    def __init__(self, app):
        super().__init__(app)
        self.controller = MapController(app.camera)
        self.era_id = app.session.era_id
        self.pins = app.eras.pin_counts(self.era_id)
        self.flags = FlagLayer(app.world, app.flags, featured=app.country_info, pins=self.pins)
        self.toast = 0.0
        self.hover = None
        self.flying = False
        self.menu_btn = Button("Меню", self._to_menu, size=15)
        self.settings_btn = Button("Настройки", self._open_settings, size=15)
        self.history = None
        if self.pins is not None and loader.has_world(app, self.era_id):
            self.history = loader.hist(app, self.era_id)
            lo, hi = loader.ERA_RANGE.get(self.era_id) or self.history.range()
            self.map_years = [y for y in self.history.years if lo <= y <= hi] or self.history.years
            self.map_year = getattr(app.session, "map_year", None) or self.map_years[len(self.map_years) // 2]
            self.hover_key = 0
            self.hover_atom = None
            self._play, self._play_snap = {}, None
            self._labels, self._labels_snap = [], None
            self.year_btns = [Button("<", lambda: self._step_year(-1), size=18, bold=True, glass=True),
                              Button(">", lambda: self._step_year(1), size=18, bold=True, glass=True)]
            self._hover_cache = None

    def _snap(self):
        return loader.floor_snap(self.history, self.map_year)

    def _step_year(self, d):
        years = self.map_years
        i = min(range(len(years)), key=lambda j: abs(years[j] - self.map_year))
        if self.map_year != years[i]:
            i += 0 if (years[i] > self.map_year) == (d > 0) else d
        else:
            i += d
        self.map_year = years[min(max(i, 0), len(years) - 1)]

    def _playable(self):
        snap = self._snap()
        if self._play_snap == snap:
            return self._play
        h, out = self.history, {}
        for ep in self.app.eras.era(self.era_id)["polities"]:
            lo, hi = ep["span"]
            if hi < self.map_year or lo > self.map_year + PLAY_AHEAD:
                continue
            ids = [self.app.world.by_id[i].index for i in ep["map"] if i in self.app.world.by_id]
            k = World.resolve_player(h, snap, ep["id"], ids)
            if k >= 0:
                out.setdefault(int(h.top[snap][k]), []).append(ep)
        self._play, self._play_snap = out, snap
        return out

    def _atom_key(self, pos, size):
        layer = loader.layer(self.app, self.era_id)
        layer.set_state(self._snap(), True)
        atom = self.history.atom_at(*self.app.camera.to_world(*pos, size))
        return atom, layer.color_key(atom)

    def _open_polity(self, key):
        eps = self._playable().get(key)
        if not eps:
            self.toast = 2.8
            return
        ep = min(eps, key=lambda e: abs(e["span"][0] - self.map_year))
        country = next((self.app.world.by_id[i] for i in ep["map"] if i in self.app.world.by_id), None)
        if country is None:
            return
        layer = loader.layer(self.app, self.era_id)
        atoms = np.nonzero(layer.arrays()[2] == key)[0]
        self._fly_to_country(country.index, loader.focus_bbox(self.history, atoms), ep["id"])

    def _open_settings(self):
        from .settings_state import SettingsState
        self.app.push(SettingsState(self.app))

    def enter(self):
        self.flying = False
        self.controller.reset()

    def _to_menu(self):
        self.app.pop()

    def _pick(self, pos, size):
        if topbar_rect(size).collidepoint(pos):
            return None
        idx = self.flags.hit(pos)
        if idx is not None:
            return idx
        country = self.app.world.country_at(*self.app.camera.to_world(*pos, size))
        if country is None or (self.pins is not None and country.id not in self.pins):
            return None
        return country.index

    def _missed(self, pos, size):
        if self.pins is None or topbar_rect(size).collidepoint(pos):
            return False
        country = self.app.world.country_at(*self.app.camera.to_world(*pos, size))
        return country is not None and country.id not in self.pins

    def _open_country(self, idx):
        self._fly_to_country(idx, self.app.world.countries[idx].focus_bbox, None)

    def _fly_to_country(self, idx, bbox, polity_id):
        from .country_view import CountryViewState
        app = self.app
        size = app.screen.get_size()
        app.world_camera = app.camera.snapshot()
        target = app.camera.fit(bbox, CountryViewState.map_rect(size), size)
        self.flying = True
        self.hover = idx
        year = self.map_year if self.history else None
        app.camera.fly_to(*target, duration=0.9,
                          on_done=lambda: app.push(CountryViewState(app, idx, polity_id=polity_id, map_year=year)))

    def handle_event(self, event):
        if self.flying:
            return
        buttons = [self.menu_btn, self.settings_btn] + (self.year_btns if self.history else [])
        if any(b.handle_event(event) for b in buttons):
            return
        if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
            self._to_menu()
            return
        if self.history and event.type == pygame.KEYDOWN and event.key in (pygame.K_LEFT, pygame.K_RIGHT):
            self._step_year(-1 if event.key == pygame.K_LEFT else 1)
            return
        size = self.app.screen.get_size()
        click = self.controller.handle_event(event, size)
        if click:
            if self.history:
                if not topbar_rect(size).collidepoint(click):
                    self._open_polity(self._atom_key(click, size)[1])
                return
            idx = self._pick(click, size)
            if idx is not None:
                self._open_country(idx)
            elif self._missed(click, size):
                self.toast = 2.8

    def animating(self):
        return self.app.camera.animating

    def update(self, dt):
        self.toast = max(0.0, self.toast - dt)
        size = self.app.screen.get_size()
        self.app.camera.update(dt)
        if self.history:
            if not self.flying:
                pos = pygame.mouse.get_pos()
                key = (pos, self.app.camera.key(), self._snap())
                if key != self._hover_cache:
                    self._hover_cache = key
                    self.hover_atom, self.hover_key = (None, 0) if topbar_rect(size).collidepoint(pos) else \
                        self._atom_key(pos, size)
            return
        if not self.flying:
            self.hover = self._pick(pygame.mouse.get_pos(), size)
        self.flags.layout(self.app.camera, size, blocked=[topbar_rect(size).inflate(0, 8)])

    def _draw_history(self, surface):
        app = self.app
        h = self.history
        snap = self._snap()
        layer = loader.layer(app, self.era_id)
        layer.set_state(snap, True)
        if self._labels_snap != snap:
            self._labels, self._labels_snap = h.labels(snap, True), snap
        hl = self.hover_key if (self.hover_key and self.hover_key in self._playable()) else -1
        layer.render(surface, app.camera, highlight=hl)
        size = surface.get_size()
        ui = [topbar_rect(size).inflate(0, 8)]
        year = self.map_year
        draw_labels(surface, app, app.camera, self._labels, lambda k: h.polity(k).at(year), year, ui,
                    marks=set(self._playable()))

    def draw(self, surface):
        app = self.app
        w, h = surface.get_size()
        app.camera.set_view(pygame.Rect(0, theme.TOPBAR_H, w, h - theme.TOPBAR_H), (w, h))
        if self.history:
            self._draw_history(surface)
        else:
            app.renderer.render(surface, app.camera)
            if self.hover is not None:
                app.renderer.highlight_country(surface, app.camera, self.hover, fill=theme.LAND_HOVER)
            self.flags.draw(surface, hover=self.hover)

        bar = draw_topbar(surface, app, "Выберите государство" if self.history else "Выберите страну")
        self.menu_btn.rect = pygame.Rect(w - 110, bar.y + 7, 96, bar.h - 14)
        self.menu_btn.draw(surface)
        self.settings_btn.rect = pygame.Rect(w - 232, bar.y + 7, 114, bar.h - 14)
        self.settings_btn.draw(surface)
        if self.history:
            self._draw_year_control(surface, bar)

        hint = HINT_HISTORY if self.history else HINT if self.pins is None else HINT_PINS
        hint = ellipsize(hint, w - 64, fonts.get(13))
        hint_w = text_surface(hint, 13).get_width() + 40
        hint_rect = pygame.Rect((w - hint_w) // 2, h - 42, hint_w, 32)
        draw_panel(surface, hint_rect, alpha=200, border=None, radius=16)
        draw_text(surface, hint, hint_rect.center, 13, theme.TEXT_DIM, anchor="center")

        if self.toast > 0:
            msg = ("За это государство в выбранном году играть нельзя: ищите красные метки" if self.history
                   else "В эту эпоху здесь нет игровых государств: ищите метки на карте")
            img = text_surface(msg, 16, theme.WARN, bold=True)
            box = img.get_rect(center=(w // 2, h - 90)).inflate(28, 14)
            draw_panel(surface, box, alpha=235, border=theme.WARN, radius=14)
            surface.blit(img, img.get_rect(center=box.center))

        if self.history:
            self._draw_history_tooltip(surface)
            return
        if self.hover is not None and not self.flying:
            c = app.world.countries[self.hover]
            info = app.country_info.get(c.id)
            if self.pins is not None:
                polities = [p for p in app.eras.era(self.era_id)["polities"] if c.id in p["map"]]
                lines = [(p["name"], theme.TEXT, 16, True) for p in polities[:6]]
                lines.append((f"На карте: {(info or {}).get('name_ru') or c.display_name}", theme.TEXT_DIM, 13, False))
            else:
                lines = [((info or {}).get("name_ru") or c.display_name, theme.TEXT, 16, True)]
                lines.append(("Подробные данные" if info else "Базовые данные", theme.ACCENT if info else theme.TEXT_DIM, 13, False))
            draw_tooltip(surface, lines, pygame.mouse.get_pos())

    def _draw_year_control(self, surface, bar):
        x, y = 16, bar.bottom + 10
        self.year_btns[0].rect = pygame.Rect(x, y, 44, 40)
        self.year_btns[1].rect = pygame.Rect(x + 44 + 150, y, 44, 40)
        for b in self.year_btns:
            b.draw(surface)
        snap_year = self.history.years[self._snap()]
        draw_text(surface, f"Карта {snap_year} г.", (x + 44 + 75, y + 20), 17, theme.TEXT, bold=True, anchor="center")

    def _draw_history_tooltip(self, surface):
        if self.flying or self.hover_atom is None or not self.hover_key:
            return
        h, year = self.history, self.map_year
        title = h.polity(self.hover_key).at(year).title
        lines = [(title, theme.TEXT, 16, True)]
        eps = self._playable().get(self.hover_key)
        if eps:
            lines.append(("Можно играть: " + ", ".join(e["name"] for e in eps[:3]), theme.ACCENT, 13, True))
        else:
            lines.append(("Недоступно для игры", theme.TEXT_MUTED, 13, False))
        draw_tooltip(surface, lines, pygame.mouse.get_pos())
