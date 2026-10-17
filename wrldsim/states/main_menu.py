import math

import pygame

from .. import __version__
from ..map.camera import Camera
from ..sim import saves
from ..ui import theme
from ..ui.widgets import Button, draw_spaced, draw_text
from .base import State


class MainMenuState(State):
    def __init__(self, app):
        super().__init__(app)
        self.bg_camera = app.new_camera(cx=15.0, cy=-30.0)
        self.time = 0.0
        self.continue_btn = Button("Продолжить", self._continue, size=20, glass=True)
        self.buttons = [
            Button("Новая игра", self._new_game, size=20, bold=True, glass=True),
            self.continue_btn,
            Button("Настройки", self._settings, size=20, glass=True),
            Button("Выход", app.quit, size=20, glass=True),
        ]
        self._shade = None

    def enter(self):
        self.continue_btn.enabled = saves.any_saves()

    def _new_game(self):
        from .new_game import NewGameKindState
        self.app.push(NewGameKindState(self.app))

    def _settings(self):
        from .settings_state import SettingsState
        self.app.push(SettingsState(self.app))

    def _continue(self):
        from .arcade_game import load_game_from_menu
        from .save_slots import SaveSlotsState
        mode_id = saves.latest_mode() or "arcade"
        self.app.push(SaveSlotsState(self.app, mode_id, "load",
                                     lambda slot: load_game_from_menu(self.app, mode_id, slot)))

    def handle_event(self, event):
        for b in self.buttons:
            if b.handle_event(event):
                return

    def update(self, dt):
        self.time += dt

    def animating(self):
        return True

    def draw(self, surface):
        w, h = surface.get_size()
        cam = self.bg_camera
        cam.globe = self.app.globe_on
        if cam.globe:
            cam.zoom = Camera.min_zoom((w, h), True) * 1.05
            cam.cx = (15.0 + self.time * 4.0 + 180.0) % 360.0 - 180.0
            cam.cy = -22.0 + 6.0 * math.sin(self.time * 0.05)
        else:
            cam.zoom = Camera.min_zoom((w, h)) * 1.6
            cam.cx = 15.0 + 40.0 * math.sin(self.time * 0.03)
            cam.cy = -30.0 + 6.0 * math.sin(self.time * 0.05)
        self.app.renderer.render(surface, cam)

        if self._shade is None or self._shade.get_size() != (w, h) or self._shade.get_at((0, 0))[:3] != theme.OCEAN:
            self._shade = pygame.Surface((w, h), pygame.SRCALPHA)
            self._shade.fill((*theme.OCEAN, 110))
        surface.blit(self._shade, (0, 0))

        title_size = min(88, max(40, int(h * 0.12)), max(40, w // 9))
        title_y = int(h * 0.26)
        draw_spaced(surface, "WRLDSIM", (w // 2, title_y), title_size, spacing=0.35)
        draw_text(surface, "симулятор мира", (w // 2, title_y + title_size * 3 // 4 + 14), 20 if h >= 600 else 16,
                  theme.TEXT_DIM, anchor="center")

        n = len(self.buttons)
        bw, gap = min(320, w - 40), 14 if h >= 600 else 8
        top = title_y + title_size + 40
        bh = min(52, max(34, (h - 40 - top - gap * (n - 1)) // n))
        y = min(int(h * 0.50), h - 40 - n * bh - gap * (n - 1))
        y = max(y, top)
        for b in self.buttons:
            b.rect = pygame.Rect(w // 2 - bw // 2, y, bw, bh)
            b.draw(surface)
            y += bh + gap

        draw_text(surface, f"v{__version__} · Карта: Natural Earth · Границы эпох: historical-basemaps · Флаги: flagcdn.com",
                  (w // 2, h - 24), 13, theme.TEXT_MUTED, anchor="center")
