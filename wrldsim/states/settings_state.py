import colorsys

import pygame

from .. import settings
from ..ui import theme
from ..ui import widgets
from ..ui.widgets import Button, draw_panel, draw_spaced, draw_text, fill_round
from .base import ModalState

TABS = (("screen", "ЭКРАН"), ("look", "ОФОРМЛЕНИЕ"))
SLIDER_H = 14


class Slider:
    def __init__(self, on_change, on_release=None):
        self.value = 0.0
        self.rect = pygame.Rect(0, 0, 0, 0)
        self.drag = False
        self.on_change = on_change
        self.on_release = on_release

    def handle_event(self, event):
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1 and self.rect.inflate(16, 16).collidepoint(event.pos):
            self.drag = True
        elif event.type == pygame.MOUSEBUTTONUP and event.button == 1 and self.drag:
            self.drag = False
            if self.on_release:
                self.on_release()
            return True
        elif not (event.type == pygame.MOUSEMOTION and self.drag):
            return False
        self.value = min(max((event.pos[0] - self.rect.x) / max(1, self.rect.w), 0.0), 1.0)
        self.on_change(self.value)
        return True

    def draw(self, surface, strip=None):
        r = self.rect
        if strip is None:
            fill_round(surface, r, theme.BAR_TRACK, 255, r.h // 2)
            fill_round(surface, pygame.Rect(r.x, r.y, max(r.h, int(r.w * self.value)), r.h), theme.ACCENT, 230,
                       r.h // 2)
        else:
            step = 3
            for x in range(0, r.w, step):
                pygame.draw.rect(surface, strip(x / max(1, r.w - 1)), (r.x + x, r.y, step, r.h))
            pygame.draw.rect(surface, theme.PANEL_BORDER, r, 1)
        kx = r.x + int(r.w * self.value)
        hot = self.drag or r.inflate(16, 16).collidepoint(pygame.mouse.get_pos())
        rad = 10 if hot else 8
        fill_round(surface, pygame.Rect(kx - rad, r.centery - rad, 2 * rad, 2 * rad), theme.TEXT, 255, rad)
        fill_round(surface, pygame.Rect(kx - rad + 3, r.centery - rad + 3, 2 * rad - 6, 2 * rad - 6),
                   strip(self.value) if strip else theme.ACCENT, 255, rad - 3)


def _hsv(rgb):
    return colorsys.rgb_to_hsv(*(c / 255 for c in rgb))


def _rgb(h, s, v):
    return tuple(int(round(c * 255)) for c in colorsys.hsv_to_rgb(h, s, v))


class SettingsState(ModalState):
    def __init__(self, app, tab="screen"):
        super().__init__(app)
        self.tab = tab
        self.tab_btns = {tid: Button(label, lambda t=tid: self._set_tab(t), size=15, bold=True) for tid, label in TABS}
        self.mode_btns = {
            mode: Button(name, lambda m=mode: app.set_display(m), size=17)
            for mode, name in settings.DISPLAY_MODES.items()
        }
        self.style_btns = {sid: Button(name, lambda s=sid: app.set_ui_style(s), size=17)
                           for sid, name in widgets.STYLES.items()}
        self.globe_btns = {True: Button("3D-глобус", lambda: app.set_globe(True), size=17),
                           False: Button("Плоская карта", lambda: app.set_globe(False), size=17)}
        self.close_btn = Button("Закрыть", self._close, size=17, bold=True)

        cfg = dict(app.prefs.get("theme") or {})
        self.accent = theme.accent_of(cfg)
        self.glass = theme.GLASS_TINT
        self.radius = theme.RADIUS
        self.accent_btns = {name: Button(name, lambda c=color: self._set_accent(c), size=14)
                            for name, color in theme.ACCENTS.items()}
        self.hsv = [Slider(lambda v, i=i: self._set_hsv(i, v), self._save) for i in range(3)]
        self.glass_slider = Slider(self._set_glass, self._save)
        self.radius_slider = Slider(self._set_radius, self._save)
        self.reset_all_btn = Button("Как по умолчанию", self._reset_all, size=14)
        self.view = pygame.Rect(0, 0, 0, 0)
        self.scroll = self.max_scroll = 0
        self._sync_sliders()

    def _cfg(self):
        return {"accent": list(self.accent), "glass": round(self.glass, 3), "radius": int(self.radius)}

    def _apply(self, save=False):
        self.app.apply_theme(self._cfg(), save=save)

    def _save(self):
        self._apply(save=True)

    def _sync_sliders(self):
        for slider, value in zip(self.hsv, _hsv(self.accent)):
            slider.value = value
        self.glass_slider.value = (self.glass - theme.GLASS_MIN) / (theme.GLASS_MAX - theme.GLASS_MIN)
        self.radius_slider.value = (self.radius - theme.RADIUS_MIN) / (theme.RADIUS_MAX - theme.RADIUS_MIN)

    def _set_tab(self, tab):
        self.tab = tab

    def _set_accent(self, color):
        self.accent = tuple(color)
        self._save()
        self._sync_sliders()

    def _set_hsv(self, index, value):
        hsv = [s.value for s in self.hsv]
        hsv[index] = value
        self.accent = _rgb(*hsv)
        self._apply()

    def _set_glass(self, value):
        self.glass = theme.GLASS_MIN + value * (theme.GLASS_MAX - theme.GLASS_MIN)
        self._apply()

    def _set_radius(self, value):
        self.radius = round(theme.RADIUS_MIN + value * (theme.RADIUS_MAX - theme.RADIUS_MIN))
        self._apply()

    def _reset_all(self):
        self.accent = theme.DEFAULT_ACCENT
        self.glass, self.radius = theme.DEFAULT_GLASS, theme.DEFAULT_RADIUS
        self._save()
        self._sync_sliders()

    def _close(self):
        self._save()
        self.app.pop()

    def handle_event(self, event):
        if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
            self._close()
            return
        buttons = [*self.tab_btns.values(), self.close_btn]
        if self.tab == "screen":
            buttons += [*self.mode_btns.values(), *self.style_btns.values(), *self.globe_btns.values()]
        else:
            if event.type == pygame.MOUSEWHEEL:
                self.scroll = min(max(self.scroll - event.y * 40, 0), self.max_scroll)
                return
            inside = event.type != pygame.MOUSEBUTTONDOWN or self.view.collidepoint(event.pos)
            if inside:
                sliders = [*self.hsv] + ([self.glass_slider, self.radius_slider] if widgets.STYLE == "glass" else [])
                for slider in sliders:
                    if slider.handle_event(event):
                        return
                buttons += self.accent_btns.values()
            buttons.append(self.reset_all_btn)
        for b in buttons:
            if b.handle_event(event):
                return

    def draw(self, surface):
        w, h = surface.get_size()
        self.draw_backdrop(surface)
        pw, ph = (520, min(640, h - 40)) if self.tab == "screen" else (min(900, w - 40), min(680, h - 40))
        panel = pygame.Rect((w - pw) // 2, (h - ph) // 2, pw, ph)
        draw_panel(surface, panel, alpha=250, border=theme.ACCENT)
        draw_spaced(surface, "НАСТРОЙКИ", (panel.centerx, panel.y + 34), 20, theme.ACCENT, spacing=0.2)
        tab_w = (pw - 64 - 10) // 2
        for i, (tid, _) in enumerate(TABS):
            b = self.tab_btns[tid]
            b.rect = pygame.Rect(panel.x + 32 + i * (tab_w + 10), panel.y + 58, tab_w, 38)
            b.selected = self.tab == tid
            b.draw(surface)
        if self.tab == "screen":
            self._draw_screen(surface, panel)
        else:
            self._draw_look(surface, panel)
        self.close_btn.rect = pygame.Rect(panel.right - 32 - 200, panel.bottom - 58, 200, 42)
        self.close_btn.draw(surface)

    def _draw_screen(self, surface, panel):
        draw_text(surface, "Режим экрана", (panel.x + 32, panel.y + 112), 14, theme.TEXT_DIM)
        y = panel.y + 138
        for mode, btn in self.mode_btns.items():
            btn.selected = mode == self.app.display_mode
            btn.rect = pygame.Rect(panel.x + 32, y, panel.w - 64, 44)
            btn.draw(surface)
            y += 52
        draw_text(surface, "F11: быстро включить или выключить полный экран", (panel.centerx, y + 6), 13,
                  theme.TEXT_MUTED, anchor="center")
        y += 34
        draw_text(surface, "Оформление", (panel.x + 32, y), 14, theme.TEXT_DIM)
        y += 26
        bw = (panel.w - 64 - 10) // 2
        for i, (sid, btn) in enumerate(self.style_btns.items()):
            btn.selected = sid == widgets.STYLE
            btn.rect = pygame.Rect(panel.x + 32 + i * (bw + 10), y, bw, 44)
            btn.draw(surface)
        draw_text(surface, "Плоский - как Google Earth; стекло - размытие и блики",
                  (panel.centerx, y + 58), 12, theme.TEXT_MUTED, anchor="center")
        y += 84
        draw_text(surface, "Карта", (panel.x + 32, y), 14, theme.TEXT_DIM)
        y += 26
        gpu = self.app.gpu is not None
        for i, (on, btn) in enumerate(self.globe_btns.items()):
            btn.selected = on == self.app.globe_on
            btn.enabled = gpu
            btn.rect = pygame.Rect(panel.x + 32 + i * (bw + 10), y, bw, 44)
            btn.draw(surface)
        hint = "Земля со спутника, повороты мышью" if gpu else "3D-глобус работает только с видеокартой"
        draw_text(surface, hint, (panel.centerx, y + 58), 12, theme.TEXT_MUTED, anchor="center")

    def _draw_look(self, surface, panel):
        x, w = panel.x + 32, panel.w - 64
        self.view = pygame.Rect(panel.x, panel.y + 104, panel.w, panel.bottom - 58 - 12 - (panel.y + 104))
        y = start = self.view.y + 8
        prev_clip = surface.get_clip()
        surface.set_clip(self.view.clip(prev_clip))
        y -= self.scroll
        draw_text(surface, "ЦВЕТ АКЦЕНТА", (x, y), 12, theme.ACCENT, bold=True)
        draw_text(surface, "Выбранные кнопки, вкладки, заголовки и подсветка на карте.", (x, y + 18), 13,
                  theme.TEXT_MUTED)
        y += 44
        cols = 4 if w >= 560 else 2
        bw = (w - 8 * (cols - 1)) // cols
        for i, (name, b) in enumerate(self.accent_btns.items()):
            color = theme.ACCENTS[name]
            b.rect = pygame.Rect(x + (i % cols) * (bw + 8), y + (i // cols) * 44, bw, 36)
            b.selected = tuple(color) == tuple(self.accent)
            b.draw(surface)
            fill_round(surface, pygame.Rect(b.rect.x + 10, b.rect.centery - 6, 12, 12), color, 255, 6)
        y += -(-len(self.accent_btns) // cols) * 44 + 12

        sw = pygame.Rect(x, y, 74, 54)
        fill_round(surface, sw, self.accent, 255, 6)
        pygame.draw.rect(surface, theme.PANEL_BORDER, sw, 1, border_radius=6)
        draw_text(surface, "#%02X%02X%02X" % tuple(self.accent), (sw.right + 14, y + 6), 16, theme.TEXT, bold=True)
        draw_text(surface, "RGB %d, %d, %d" % tuple(self.accent), (sw.right + 14, y + 30), 13, theme.TEXT_DIM)
        y += 70
        h, s, v = (sl.value for sl in self.hsv)
        strips = (lambda t: _rgb(t, max(s, 0.6), max(v, 0.8)), lambda t: _rgb(h, t, v), lambda t: _rgb(h, s, t))
        for slider, label, strip in zip(self.hsv, ("Оттенок", "Насыщенность", "Яркость"), strips):
            draw_text(surface, label, (x, y), 13, theme.TEXT_DIM)
            slider.rect = pygame.Rect(x, y + 20, w, SLIDER_H)
            slider.draw(surface, strip)
            y += 50

        if widgets.STYLE == "glass":
            y += 6
            draw_text(surface, "СТЕКЛО И ФОРМА", (x, y), 12, theme.ACCENT, bold=True)
            y += 22
            draw_text(surface, "Плотность стекла панелей", (x, y), 13, theme.TEXT_DIM)
            draw_text(surface, f"{int(self.glass * 100)}%", (x + w, y), 13, theme.TEXT, anchor="topright")
            self.glass_slider.rect = pygame.Rect(x, y + 20, w, 8)
            self.glass_slider.draw(surface)
            y += 46
            draw_text(surface, "Скругление углов", (x, y), 13, theme.TEXT_DIM)
            draw_text(surface, f"{self.radius} px", (x + w, y), 13, theme.TEXT, anchor="topright")
            self.radius_slider.rect = pygame.Rect(x, y + 20, w, 8)
            self.radius_slider.draw(surface)
            y += 46
        else:
            self.glass_slider.rect = self.radius_slider.rect = pygame.Rect(0, 0, 0, 0)
            draw_text(surface, "Плотность стекла и скругление настраиваются в виде «Стекло» (вкладка «Экран»).",
                      (x, y + 4), 12, theme.TEXT_MUTED)
            y += 30
        surface.set_clip(prev_clip)
        self.max_scroll = max(0, y + self.scroll - start - (self.view.h - 8))
        self.scroll = min(self.scroll, self.max_scroll)
        self.reset_all_btn.rect = pygame.Rect(x, panel.bottom - 58, 220, 42)
        self.reset_all_btn.enabled = tuple(self.accent) != tuple(theme.DEFAULT_ACCENT) \
            or self.glass != theme.DEFAULT_GLASS or self.radius != theme.DEFAULT_RADIUS
        self.reset_all_btn.draw(surface)
