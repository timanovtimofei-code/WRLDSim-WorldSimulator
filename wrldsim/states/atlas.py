import pygame

from ..history import loader
from ..history.flags import draw_polity_flag
from ..map.labels import draw_labels
from ..map.camera import Camera
from ..map.controller import MapController
from ..ui import fonts, theme
from ..ui.widgets import Button, draw_panel, draw_text, draw_tooltip, ellipsize, text_surface, wrap
from .base import State, draw_topbar, topbar_rect

RANGES = {"imperial": (1700, 1922)}
PLAY_SPEED = 6.0
STEP_KEYS = {pygame.K_LEFT: -1, pygame.K_RIGHT: 1}
CREDIT = "Границы приблизительные (масштаб мира, до 1900 г. условны) · данные: historical-basemaps, A. Ourednik, GPL-3.0"
KEYS = "←/→ год · Shift ±10 · Ctrl ±50 · PgUp/PgDn снимок · Пробел пуск · E державы/государства · P провинции · L подписи"
PANEL_W = 340
TIMELINE_H = 116


class AtlasState(State):
    def __init__(self, app, era_id="imperial"):
        super().__init__(app)
        self.era_id = era_id
        self.hist = loader.hist(app, era_id)
        lo, hi = RANGES.get(era_id) or self.hist.range()
        self.lo, self.hi = lo, hi
        self.year = float(min(max(1815, lo), hi))
        self.camera = app.new_camera(cx=20.0, cy=-35.0, zoom=1.0)
        self.camera.zoom = Camera.min_zoom(app.screen.get_size(), self.camera.globe) * 1.15
        self.controller = MapController(self.camera)
        self.layer = None
        self.empire = True
        self.labels_on = True
        self.playing = False
        self.selected = 0
        self._hover = (None, 0)
        self._hover_key = None
        self._labels = []
        self._slider = False
        self._rects = {}
        self.back_btn = Button("← Меню", self._back, size=15)
        self.mode_btns = [Button("Державы", lambda: self._set_mode(True), size=14, glass=True),
                          Button("Государства", lambda: self._set_mode(False), size=14, glass=True)]
        self.prov_btn = Button("Провинции", self._toggle_prov, size=14, glass=True)
        self.label_btn = Button("Подписи", self._toggle_labels, size=14, glass=True, selected=True)
        self.play_btn = Button("Пуск", self._toggle_play, size=15, glass=True)

    def enter(self):
        self.controller.reset()

    def exit(self):
        self.layer = None

    def _back(self):
        self.app.pop()

    def _set_mode(self, empire):
        self.empire = empire

    def _toggle_prov(self):
        if self.layer:
            self.layer.provinces = not self.layer.provinces

    def _toggle_labels(self):
        self.labels_on = not self.labels_on

    def _toggle_play(self):
        if not self.playing and self.year >= self.hi:
            self.year = float(self.lo)
        self.playing = not self.playing

    def _ensure_layer(self):
        layer = loader.layer(self.app, self.era_id)
        if layer is not self.layer:
            keep = (self.layer.provinces if self.layer else False)
            self.layer = layer
            self.layer.provinces = keep
            self._labels_key = None

    def _snap(self):
        return self.hist.snapshot_at(round(self.year))

    def _refresh(self):
        self._ensure_layer()
        snap = self._snap()
        if self.layer.set_state(snap, self.empire) or getattr(self, "_labels_key", None) is None:
            self._labels = self.hist.labels(snap, self.empire)
            self._labels_key = (snap, self.empire)

    def _set_year(self, value):
        self.year = float(min(max(value, self.lo), self.hi))

    def _jump_snapshot(self, step):
        years = [y for y in self.hist.years if self.lo <= y <= self.hi]
        cur = round(self.year)
        if step > 0:
            self._set_year(next((y for y in years if y > cur), self.hi))
        else:
            self._set_year(next((y for y in reversed(years) if y < cur), self.lo))

    def _over_ui(self, pos):
        return any(r.collidepoint(pos) for r in self._rects.values())

    def _slider_year(self, x):
        track = self._rects.get("track")
        if not track or track.w <= 0:
            return self.year
        t = min(max((x - track.x) / track.w, 0.0), 1.0)
        return self.lo + t * (self.hi - self.lo)

    def handle_event(self, event):
        if event.type == pygame.KEYDOWN:
            mods = pygame.key.get_mods()
            if event.key == pygame.K_ESCAPE:
                if self.selected:
                    self.selected = 0
                else:
                    self._back()
                return
            if event.key in STEP_KEYS:
                step = 50 if mods & pygame.KMOD_CTRL else 10 if mods & pygame.KMOD_SHIFT else 1
                self._set_year(round(self.year) + STEP_KEYS[event.key] * step)
                self.playing = False
                return
            if event.key in (pygame.K_PAGEUP, pygame.K_LEFTBRACKET):
                self._jump_snapshot(-1)
                return
            if event.key in (pygame.K_PAGEDOWN, pygame.K_RIGHTBRACKET):
                self._jump_snapshot(1)
                return
            if event.key == pygame.K_HOME:
                self._set_year(self.lo)
                return
            if event.key == pygame.K_END:
                self._set_year(self.hi)
                return
            if event.key == pygame.K_SPACE:
                self._toggle_play()
                return
            if event.key == pygame.K_e:
                self._set_mode(not self.empire)
                return
            if event.key == pygame.K_l:
                self._toggle_labels()
                return
            if event.key == pygame.K_p:
                self._toggle_prov()
                return
        for b in (self.back_btn, *self.mode_btns, self.prov_btn, self.label_btn, self.play_btn):
            if b.handle_event(event):
                return
        track = self._rects.get("track_hit")
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1 and track and track.collidepoint(event.pos):
            self._slider = True
            self.playing = False
            self._set_year(self._slider_year(event.pos[0]))
            return
        if event.type == pygame.MOUSEMOTION and self._slider:
            self._set_year(self._slider_year(event.pos[0]))
            return
        if event.type == pygame.MOUSEBUTTONUP and event.button == 1 and self._slider:
            self._slider = False
            return
        if event.type in (pygame.MOUSEBUTTONDOWN, pygame.MOUSEWHEEL) and self._over_ui(pygame.mouse.get_pos()):
            return
        size = self.app.screen.get_size()
        click = self.controller.handle_event(event, size)
        if click and not self._over_ui(click):
            self.selected = self._hover[1] if self._hover[1] else 0

    def update(self, dt):
        if self.playing:
            self._set_year(self.year + PLAY_SPEED * dt)
            if self.year >= self.hi:
                self.playing = False
        self.camera.update(dt)
        size = self.app.screen.get_size()
        self.camera.clamp(size)
        self._refresh()
        pos = pygame.mouse.get_pos()
        key = (pos, self.camera.key(), self.layer.snap, self.empire)
        if key != self._hover_key:
            self._hover_key = key
            atom = None
            if not self._over_ui(pos) and not self._slider:
                atom = self.hist.atom_at(*self.camera.to_world(*pos, size))
            self._hover = (atom, self.layer.color_key(atom))

    def animating(self):
        return self.playing or self.camera.animating

    def draw(self, surface):
        self._ensure_layer()
        self._refresh()
        w, h = surface.get_size()
        hover_key = self._hover[1]
        self.layer.render(surface, self.camera, highlight=hover_key or self.selected or -1)
        if self.labels_on:
            self._draw_labels(surface)

        bar = draw_topbar(surface, self.app, f"Атлас · {self.app.eras.era(self.era_id)['short']}")
        self.back_btn.rect = pygame.Rect(w - 126, bar.y + 7, 112, bar.h - 14)
        self.back_btn.draw(surface)
        self._rects = {"bar": topbar_rect(surface.get_size()).inflate(0, 6)}
        self._draw_controls(surface, bar)
        self._draw_timeline(surface)
        if self.selected:
            self._draw_info(surface)
        elif hover_key and self._hover[0] is not None and not self._over_ui(pygame.mouse.get_pos()):
            self._draw_hover(surface)

    def _draw_controls(self, surface, bar):
        w = surface.get_width()
        self.mode_btns[0].selected = self.empire
        self.mode_btns[1].selected = not self.empire
        self.prov_btn.selected = bool(self.layer and self.layer.provinces)
        self.label_btn.selected = self.labels_on
        widths = [104, 132, 120, 108]
        x, y = 16, bar.bottom + 10
        if w < 640:
            widths = [92, 112, 100, 90]
        row = pygame.Rect(x, y, sum(widths) + 12 * 3, 36)
        for b, bw in zip((*self.mode_btns, self.prov_btn, self.label_btn), widths):
            b.rect = pygame.Rect(x, y, bw, 36)
            b.draw(surface)
            x += bw + 12
        self._rects["controls"] = row

    def _timeline_rect(self, size):
        w, h = size
        width = min(w - 32, 1180)
        return pygame.Rect((w - width) // 2, h - TIMELINE_H - 14, width, TIMELINE_H)

    def _draw_timeline(self, surface):
        size = surface.get_size()
        rect = self._timeline_rect(size)
        draw_panel(surface, rect, alpha=235, border=None, radius=22)
        self._rects["timeline"] = rect
        year = round(self.year)
        snap_year = self.hist.years[self._snap()]
        text = f"{year} г."
        label = draw_text(surface, text, (rect.x + 22, rect.y + 12), 34, theme.TEXT, bold=True)
        cap = f"снимок данных: {snap_year} г." if snap_year != year else "точный снимок данных"
        draw_text(surface, cap, (rect.x + 24, label.bottom + 2), 13,
                  theme.TEXT_DIM if snap_year != year else theme.ACCENT)

        self.play_btn.text = "Пауза" if self.playing else "Пуск"
        self.play_btn.rect = pygame.Rect(rect.right - 110, rect.y + 12, 92, 40)
        self.play_btn.draw(surface)

        track = pygame.Rect(max(rect.x + 190, label.right + 40), rect.y + 30, 0, 6)
        track.w = max(60, self.play_btn.rect.x - 28 - track.x)
        self._rects["track"] = track
        self._rects["track_hit"] = track.inflate(24, 36)
        pygame.draw.rect(surface, theme.mix(theme.GLASS_COLOR, theme.TEXT, 0.22), track, border_radius=3)
        t = (self.year - self.lo) / max(1, self.hi - self.lo)
        fill = pygame.Rect(track.x, track.y, int(track.w * t), track.h)
        pygame.draw.rect(surface, theme.ACCENT, fill, border_radius=3)
        for y in self.hist.years:
            if not self.lo <= y <= self.hi:
                continue
            tx = track.x + int(track.w * (y - self.lo) / max(1, self.hi - self.lo))
            pygame.draw.line(surface, theme.TEXT_DIM, (tx, track.bottom + 3), (tx, track.bottom + 9))
            if track.w > 360 or y in (self.lo, self.hi, 1815, 1914):
                img = text_surface(str(y), 12, theme.TEXT_DIM)
                surface.blit(img, img.get_rect(midtop=(tx, track.bottom + 11)))
        pygame.draw.circle(surface, theme.TEXT, (track.x + int(track.w * t), track.centery), 9)
        pygame.draw.circle(surface, theme.ACCENT, (track.x + int(track.w * t), track.centery), 9, 2)

        draw_text(surface, ellipsize(KEYS, rect.w - 36, fonts.get(12)), (rect.x + 18, rect.bottom - 40), 12,
                  theme.TEXT_DIM)
        draw_text(surface, ellipsize(CREDIT, rect.w - 36, fonts.get(12)), (rect.x + 18, rect.bottom - 22), 12,
                  theme.TEXT_MUTED)

    def _draw_labels(self, surface):
        ui = [r for k, r in self._rects.items() if k in ("bar", "controls", "timeline", "info")]
        year = round(self.year)
        draw_labels(surface, self.app, self.camera, self._labels, lambda k: self.hist.polity(k).at(year), year, ui)

    def _where(self, atom):
        world = self.app.world
        region = world.regions[int(self.hist.atom_region[atom])]
        country = world.countries[int(self.hist.atom_country[atom])]
        return region.display_name, country.display_name

    def _overlord_title(self, atom):
        state, top = int(self.layer._info[atom, 1]), int(self.layer._info[atom, 2])
        return self.hist.polity(top).title if top != state else ""

    def _draw_hover(self, surface):
        atom, key = self._hover
        state = int(self.layer._info[atom, 1])
        p = self.hist.polity(state)
        region, country = self._where(atom)
        lines = [(p.title, theme.TEXT, 16, True)]
        over = self._overlord_title(atom)
        if over:
            lines.append((f"Под властью: {over}", theme.TEXT_DIM, 13, False))
        lines.append((f"{region}, {country}" if region != country else country, theme.TEXT_DIM, 13, False))
        draw_tooltip(surface, lines, pygame.mouse.get_pos())

    def _draw_info(self, surface):
        w, h = surface.get_size()
        tl = self._rects["timeline"]
        bar_bottom = self._rects["bar"].bottom
        rect = pygame.Rect(w - PANEL_W - 16, bar_bottom + 54, PANEL_W, tl.y - bar_bottom - 54 - 10)
        if rect.h < 160 or w < 760:
            return
        draw_panel(surface, rect, alpha=238, border=None, radius=22)
        self._rects["info"] = rect
        year = round(self.year)
        p = self.hist.polity(self.selected).at(year)
        x, y = rect.x + 20, rect.y + 18
        flag_rect = pygame.Rect(x, y, 72, 50)
        real = draw_polity_flag(surface, self.app, p, year, flag_rect)
        tx = flag_rect.right + 14
        for line in wrap(p.title, rect.right - 16 - tx, 20, True)[:3]:
            draw_text(surface, line, (tx, y), 20, theme.TEXT, bold=True)
            y += 25
        if p.name and p.name != p.ru:
            draw_text(surface, ellipsize(p.name, rect.right - 16 - tx, fonts.get(13)), (tx, y), 13, theme.TEXT_DIM)
            y += 18
        y = max(y, flag_rect.bottom) + 14

        snap = self._snap()
        present = (self.layer._info[:, 0] == self.selected).any()
        rows = []
        if not present:
            rows.append(("На карте", f"в {self.hist.years[snap]} г. нет (данные)"))
        else:
            sub = {int(s) for s in self.layer._info[self.layer._info[:, 0] == self.selected, 1]}
            if self.empire and len(sub) > 1:
                rows.append(("Состав", f"{len(sub)} государств и владений"))
            lands = self.hist.countries_of(snap, self.selected, self.empire)
            if lands:
                names = ", ".join(self.app.world.countries[c].display_name for c, _ in lands)
                rows.append(("Сейчас это", names))
        years = self.hist.presence(self.selected)
        if years:
            rows.append(("В данных", f"{years[0]}–{years[-1]} г. ({len(years)} снимков)"))
        if real:
            rows.append(("Флаг", "исторический"))
        else:
            rows.append(("Флаг", "условный знак: настоящий исторический флаг ещё не добавлен"))
        if p.game:
            era_polity = self.app.eras.polity(self.era_id, p.game)
            rows.append(("В игре", era_polity.get("name", p.game)))
        for label, value in rows:
            draw_text(surface, label.upper(), (rect.x + 20, y), 11, theme.TEXT_MUTED, bold=True)
            y += 15
            y = self._paragraph(surface, value, rect.x + 20, y, rect.w - 40) + 8
            if y > rect.bottom - 24:
                break

    @staticmethod
    def _paragraph(surface, text, x, y, width):
        for line in wrap(text, width, 14)[:4]:
            draw_text(surface, line, (x, y), 14, theme.TEXT)
            y += 19
        return y
