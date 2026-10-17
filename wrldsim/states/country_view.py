import pygame

from ..history import loader
from ..history.flags import draw_polity_flag
from ..map.controller import MapController
from ..sim.eras import year_text
from ..sim.world import World
from ..ui import fonts, theme
from ..ui import format as fmt
from ..ui.widgets import Button, draw_panel, draw_paragraph, draw_text, draw_tooltip, ellipsize
from .base import State, draw_topbar, topbar_rect

PANEL_W = 400


class CountryViewState(State):
    @staticmethod
    def panel_rect(size):
        return pygame.Rect(size[0] - PANEL_W - 12, theme.TOPBAR_H + 12, PANEL_W, size[1] - theme.TOPBAR_H - 24)

    @staticmethod
    def map_rect(size):
        return pygame.Rect(0, theme.TOPBAR_H, size[0] - PANEL_W, size[1] - theme.TOPBAR_H)

    def __init__(self, app, idx, polity_id=None, map_year=None):
        super().__init__(app)
        self.country = app.world.countries[idx]
        self.info = app.country_info.get(self.country.id, {})
        self.controller = MapController(app.camera)
        self.hover_region = None
        self.selected_region = None
        self.leaving = False
        self.role_btn = Button("Выбрать роль →", self._choose_role, size=17, bold=True)
        self.back_btn = Button("← К карте мира", self._back, size=16)
        self.era_id = app.session.era_id
        self.options = app.eras.options(self.era_id, self.country.id, self.modern_name)
        self.opt_idx = 0
        self.start_idx = 0
        if polity_id:
            self.opt_idx = next((i for i, o in enumerate(self.options) if o["id"] == polity_id), 0)
        self.history = None
        self.map_year = map_year
        if app.eras.restricted(self.era_id) and loader.has_world(app, self.era_id):
            self.history = loader.hist(app, self.era_id)
            starts = self.options[self.opt_idx]["starts"]
            if map_year is None:
                map_year = starts[0]["year"]
            self.start_idx = min(range(len(starts)), key=lambda i: abs(starts[i]["year"] - map_year))
            self.map_year = starts[self.start_idx]["year"]
        self._key_cache = None
        self.hover_atom = None
        self.polity_btns = [Button("", lambda i=i: self._set_polity(i), size=14) for i in range(len(self.options))]
        self.start_btns = []
        self._rebuild_starts()
        self.scroll = 0
        self.max_scroll = 0
        self.view_rect = pygame.Rect(0, 0, 0, 0)

    @property
    def modern_name(self):
        return self.info.get("name_ru") or self.country.display_name

    @property
    def polity(self):
        return self.options[self.opt_idx]

    @property
    def start(self):
        return self.polity["starts"][self.start_idx]

    @property
    def name(self):
        return self.modern_name if self.polity.get("generic") else self.polity["name"]

    def _set_polity(self, i):
        self.opt_idx, self.start_idx, self.scroll = i, 0, 0
        self._rebuild_starts()
        if self.history:
            self.map_year = self.start["year"]

    def _set_start(self, i):
        self.start_idx = i
        if self.history:
            self.map_year = self.start["year"]

    def _history_key(self):
        h = self.history
        snap = loader.floor_snap(h, self.map_year)
        cache = self._key_cache
        if cache and cache[0] == (self.polity["id"], snap):
            return cache[1]
        ids = [self.app.world.by_id[i].index for i in self.polity.get("map", []) if i in self.app.world.by_id]
        k = World.resolve_player(h, snap, self.polity["id"], ids)
        res = (snap, k, int(h.top[snap][k]) if k >= 0 else 0)
        self._key_cache = ((self.polity["id"], snap), res)
        return res

    def _rebuild_starts(self):
        self.start_btns = [Button("", lambda i=i: self._set_start(i), size=14)
                           for i in range(len(self.polity["starts"]))]

    def _back(self):
        if self.leaving:
            return
        self.leaving = True
        self.hover_region = None
        self.app.camera.fly_to(*self.app.world_camera, duration=0.8, on_done=self.app.pop)

    def _choose_role(self):
        from .arcade_game import start_game
        from .role_select import RoleSelectState
        if self.leaving:
            return
        session = self.app.session
        session.polity_id, session.start_idx = self.polity["id"], self.start_idx
        roles = self.app.eras.roles(self.era_id, self.polity, self.start["year"], self.app.roles["roles"])
        region = self.selected_region.display_name if self.selected_region else ""
        name_ctx = {"country_id": self.country.id, "region": region, "polity_id": self.polity["id"]}
        self.app.push(RoleSelectState(self.app, self.name, lambda hero: start_game(self.app, self.country, hero),
                                      name_ctx, roles=roles))

    def _region_at(self, pos, size):
        if not self.map_rect(size).collidepoint(pos):
            return None
        return self.app.world.region_at(self.country, *self.app.camera.to_world(*pos, size))

    def handle_event(self, event):
        if self.leaving:
            return
        for b in (self.role_btn, self.back_btn):
            if b.handle_event(event):
                return
        if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
            self._back()
            return
        pos = getattr(event, "pos", None) or pygame.mouse.get_pos()
        if event.type == pygame.MOUSEWHEEL and self.view_rect.collidepoint(pos) and self.max_scroll:
            self.scroll = min(max(self.scroll - event.y * 50, 0), self.max_scroll)
            return
        if event.type in (pygame.MOUSEBUTTONDOWN, pygame.MOUSEBUTTONUP) and self.view_rect.collidepoint(pos):
            for b in (*(self.polity_btns if len(self.options) > 1 else ()), *self.start_btns):
                if b.handle_event(event):
                    return
        size = self.app.screen.get_size()
        pos = getattr(event, "pos", None)
        if event.type in (pygame.MOUSEBUTTONDOWN, pygame.MOUSEWHEEL):
            pos = pos or pygame.mouse.get_pos()
            if self.panel_rect(size).collidepoint(pos) or topbar_rect(size).collidepoint(pos):
                return
        click = self.controller.handle_event(event, size)
        if click and not self.history:
            self.selected_region = self._region_at(click, size)

    def animating(self):
        return self.app.camera.animating

    def update(self, dt):
        self.app.camera.update(dt)
        if self.leaving:
            return
        if self.history:
            pos = pygame.mouse.get_pos()
            size = self.app.screen.get_size()
            ok = self.map_rect(size).collidepoint(pos) and not topbar_rect(size).collidepoint(pos)
            self.hover_atom = self.history.atom_at(*self.app.camera.to_world(*pos, size)) if ok else None
        else:
            self.hover_region = self._region_at(pygame.mouse.get_pos(), self.app.screen.get_size())

    def draw(self, surface):
        app = self.app
        cam = app.camera
        cam.set_view(self.map_rect(surface.get_size()), surface.get_size())
        if self.history:
            snap, k, top = self._history_key()
            layer = loader.layer(app, self.era_id)
            layer.set_state(snap, True)
            layer.render(surface, cam, highlight=-1, dim=top, dim_amt=0.55)
        else:
            app.renderer.render(surface, cam, focus=self.country.index)
            if self.selected_region:
                app.renderer.highlight_region(surface, cam, self.selected_region, fill=theme.ACCENT_DIM)
            if self.hover_region and self.hover_region is not self.selected_region:
                app.renderer.highlight_region(surface, cam, self.hover_region, fill=theme.LAND_HOVER)
            app.renderer.highlight_country(surface, cam, self.country.index, outline=theme.COAST, width=2)

        draw_topbar(surface, app, self.name)
        self._draw_panel(surface)
        if self.history and self.hover_atom is not None and not self.leaving:
            h = self.history
            snap = loader.floor_snap(h, self.map_year)
            own = int(h.owner[snap][self.hover_atom])
            top = int(h.top[snap][own])
            lines = [(h.polity(top).at(self.map_year).title, theme.TEXT, 16, True)]
            if own and own != top:
                lines.append((f"{h.polity(own).at(self.map_year).title} (владение)", theme.TEXT_DIM, 13, False))
            draw_tooltip(surface, lines, pygame.mouse.get_pos())
            return

        if self.hover_region and not self.leaving:
            r = self.hover_region
            lines = [(r.display_name, theme.TEXT, 16, True)]
            if r.kind:
                lines.append((fmt.REGION_KINDS_RU.get(r.kind, r.kind), theme.TEXT_DIM, 13, False))
            draw_tooltip(surface, lines, pygame.mouse.get_pos())

    def _draw_panel(self, surface):
        rect = self.panel_rect(surface.get_size())
        draw_panel(surface, rect)
        x, w = rect.x + 24, rect.w - 48
        self.back_btn.rect = pygame.Rect(x, rect.bottom - 64, w, 44)
        self.role_btn.rect = pygame.Rect(x, rect.bottom - 118, w, 44)
        view = pygame.Rect(rect.x, rect.y + 6, rect.w, self.role_btn.rect.y - 10 - (rect.y + 6))
        self.view_rect = view
        prev_clip = surface.get_clip()
        surface.set_clip(view.clip(prev_clip))
        top = rect.y + 24 - self.scroll
        y = self._draw_content(surface, x, top, w, rect)
        surface.set_clip(prev_clip)
        self.max_scroll = max(0, y - top + 24 - view.h)
        self.scroll = min(self.scroll, self.max_scroll)
        if self.max_scroll:
            track = pygame.Rect(rect.right - 10, view.y + 6, 4, view.h - 12)
            pygame.draw.rect(surface, theme.PANEL_BORDER, track, border_radius=2)
            thumb_h = max(30, track.h * view.h // (self.max_scroll + view.h))
            thumb_y = track.y + (track.h - thumb_h) * self.scroll // self.max_scroll
            pygame.draw.rect(surface, theme.ACCENT, (track.x, thumb_y, 4, thumb_h), border_radius=2)
        self.role_btn.draw(surface)
        self.back_btn.draw(surface)

    def _draw_rows(self, surface, x, y, w, rows):
        for label, value in rows:
            if not value:
                continue
            label_w = fonts.get(13).size(label)[0]
            if label_w + fonts.get(15).size(value)[0] + 16 <= w:
                draw_text(surface, label, (x, y + 2), 13, theme.TEXT_DIM)
                draw_text(surface, value, (x + w, y), 15, anchor="topright")
                y += 26
            else:
                draw_text(surface, label, (x, y), 13, theme.TEXT_DIM)
                y = draw_paragraph(surface, value, (x, y + 17), w, 15, line_gap=1) + 8
        return y

    def _draw_choosers(self, surface, x, y, w):
        if len(self.options) > 1:
            draw_text(surface, "ГОСУДАРСТВО", (x, y), 12, theme.ACCENT, bold=True)
            y += 20
            font = fonts.get(14)
            for i, (b, opt) in enumerate(zip(self.polity_btns, self.options)):
                label = f"{self.modern_name}, наши дни" if opt.get("generic") else opt["name"]
                b.text = ellipsize(label, w - 24, font)
                b.selected = i == self.opt_idx
                b.rect = pygame.Rect(x, y, w, 32)
                b.draw(surface)
                y += 38
            y += 6
        starts = self.polity["starts"]
        if len(starts) > 1:
            draw_text(surface, "ТОЧКА СТАРТА", (x, y), 12, theme.ACCENT, bold=True)
            y += 20
            font = fonts.get(14)
            for i, (b, st) in enumerate(zip(self.start_btns, starts)):
                b.text = ellipsize(f"{year_text(st['year'])} · {st['label']}", w - 24, font)
                b.selected = i == self.start_idx
                b.rect = pygame.Rect(x, y, w, 32)
                b.draw(surface)
                y += 38
            y += 6
        return y

    def _draw_content(self, surface, x, y, w, rect):
        polity = self.polity
        generic = polity.get("generic")
        compact = rect.h < 760
        if generic:
            flag = self.app.flags.fitted(self.country.iso2, *((96, 64) if compact else (150, 100)))
            if flag:
                frame = flag.get_rect(topleft=(x, y))
                surface.blit(flag, frame)
                pygame.draw.rect(surface, theme.FLAG_BORDER, frame.inflate(2, 2), 1, border_radius=10)
                y = frame.bottom + 16
        elif self.history:
            snap, k, top = self._history_key()
            if k >= 0:
                size = (96, 64) if compact else (120, 80)
                draw_polity_flag(surface, self.app, self.history.polity(k).at(self.map_year), self.map_year,
                                 pygame.Rect(x, y, *size))
                y += size[1] + 16
        y = draw_paragraph(surface, self.name, (x, y), w, 26, bold=True)
        if generic:
            continent = fmt.CONTINENTS_RU.get(self.country.continent, self.country.continent)
            draw_text(surface, continent, (x, y), 14, theme.TEXT_DIM)
        else:
            lo, hi = polity["span"]
            y = draw_paragraph(surface, f"{year_text(lo)} - {year_text(hi)}", (x, y), w, 14, theme.TEXT_DIM)
            if self.history:
                snap, k, top = self._history_key()
                layer = loader.layer(self.app, self.era_id)
                n = int((layer.arrays()[2] == top).sum()) if k >= 0 and layer.snap == snap else 0
                draw_text(surface, f"Карта {self.history.years[snap]} г." + (f" · областей: {n}" if n else ""), (x, y), 13,
                          theme.TEXT_MUTED)
            else:
                draw_text(surface, f"На карте: {self.modern_name}", (x, y), 13, theme.TEXT_MUTED)
        y += 28
        pygame.draw.line(surface, theme.PANEL_BORDER, (x, y), (x + w, y))
        y += 14
        y = self._draw_choosers(surface, x, y, w)

        if generic:
            population = self.info.get("population") or self.country.pop_est
            gdp = self.info.get("gdp_usd") or self.country.gdp_md * 1e6
            rows = [
                ("Столица", self.info.get("capital")),
                ("Строй", self.info.get("government")),
                ("Глава государства", self.info.get("head_of_state")),
                ("Глава правительства", self.info.get("head_of_government")),
                ("Население", fmt.people(population) if population else None),
                ("ВВП", fmt.usd(gdp) if gdp else None),
                ("ВВП на душу", fmt.usd(gdp / population) if gdp and population else None),
                ("Валюта", self.info.get("currency")),
                ("Регионов", str(len(self.country.regions)) if self.country.regions else None),
            ]
            note = "Данные: приблизительно, 2024" if self.info else "Данные: оценка Natural Earth"
        else:
            rows = [("Столица", polity["capital"]), ("Строй", polity["government"]),
                    ("Высший титул", polity["ruler"]), ("Деньги", polity["coin"])]
            note = "Данные: исторические, для игры упрощены"
        y = self._draw_rows(surface, x, y, w, rows)
        draw_text(surface, note, (x, y + 2), 12, theme.TEXT_MUTED)
        y += 30

        if not generic:
            pygame.draw.line(surface, theme.PANEL_BORDER, (x, y), (x + w, y))
            draw_text(surface, "СИТУАЦИЯ НА СТАРТЕ", (x, y + 12), 12, theme.ACCENT, bold=True)
            y = draw_paragraph(surface, self.start["note"], (x, y + 32), w, 15, theme.TEXT, line_gap=2) + 8
            y = draw_paragraph(surface, polity["blurb"], (x, y), w, 13, theme.TEXT_DIM, line_gap=1) + 12
        elif self.start.get("note") and len(polity["starts"]) > 1:
            y = draw_paragraph(surface, self.start["note"], (x, y), w, 14, theme.TEXT_DIM) + 8

        if self.selected_region and not self.history:
            r = self.selected_region
            pygame.draw.line(surface, theme.PANEL_BORDER, (x, y), (x + w, y))
            draw_text(surface, "ВЫБРАННЫЙ РЕГИОН", (x, y + 12), 12, theme.ACCENT, bold=True)
            y = draw_paragraph(surface, r.display_name, (x, y + 32), w, 17, bold=True)
            if r.kind:
                draw_text(surface, fmt.REGION_KINDS_RU.get(r.kind, r.kind), (x, y), 13, theme.TEXT_DIM)
                y += 20
        return y
