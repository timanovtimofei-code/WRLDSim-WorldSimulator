import math
import random

import pygame

from ..ui import fonts, theme
from ..ui.widgets import Button, draw_paragraph, draw_spaced, draw_text, ellipsize, fill_round, wrap
from .base import ModalState

WARN_FROM = 35
PANEL_W = 620
CHEAT_ROW_H = 40
LEVELS = ((80, "КРИТИЧЕСКАЯ УГРОЗА"), (60, "ОПАСНО"), (0, "ВНИМАНИЕ"))


def _mix(a, b, t):
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


def glitch_strength(risk):
    return min(1.0, max(0.0, (risk - 20) / 80))


def level_name(risk):
    return next(name for edge, name in LEVELS if risk >= edge)


def alarm_frame(size, k, t, radius):
    img = pygame.Surface(size, pygame.SRCALPHA)
    rect = img.get_rect()
    fill_round(img, rect, _mix((16, 15, 18), (40, 6, 10), k), 250, radius)
    pulse = 0.5 + 0.5 * math.sin(t * (3 + 9 * k))
    border = _mix(theme.WARN, (255, 30, 40), k)
    pygame.draw.rect(img, _mix(border, (255, 255, 255), 0.25 * pulse * k), rect, 2 + int(2 * k), border_radius=radius)
    return img


class Glitch:
    def __init__(self, k):
        self.k = k
        self.burst = 0.0
        self.rng = random.Random()
        self._scan = None

    def update(self, dt):
        self.burst = max(0.0, self.burst - dt)
        if self.rng.random() < dt * (0.6 + 6 * self.k ** 1.5):
            self.burst = 0.05 + 0.25 * self.k * self.rng.random()

    def blit(self, surface, img, pos):
        k, rng = self.k, self.rng
        active = self.burst > 0
        amp = k * (1.0 if active else 0.18)
        x, y = pos
        x += int(rng.uniform(-1, 1) * 10 * amp)
        y += int(rng.uniform(-1, 1) * 5 * amp)
        split = int(2 + 9 * amp)
        if k > 0.15:
            for color, dx in (((255, 40, 50, 120), -split), ((40, 220, 255, 70), split)):
                ghost = img.copy()
                ghost.fill(color, special_flags=pygame.BLEND_RGBA_MULT)
                surface.blit(ghost, (x + dx, y))
        surface.blit(img, (x, y))
        w, h = img.get_size()
        if active:
            for _ in range(int(2 + 10 * k)):
                sh = rng.randint(3, 6 + int(26 * k))
                sy = rng.randint(0, max(0, h - sh))
                dx = int(rng.uniform(-1, 1) * 70 * k)
                surface.blit(img, (x + dx, y + sy), pygame.Rect(0, sy, w, sh))
            for _ in range(int(6 * k)):
                bw, bh = rng.randint(10, 80), rng.randint(2, 10)
                fill_round(surface, pygame.Rect(x + rng.randint(0, w - bw), y + rng.randint(0, h - bh), bw, bh),
                           (255, 50, 60) if rng.random() < 0.7 else (230, 230, 240), rng.randint(60, 200), 0)
        if self._scan is None or self._scan.get_size() != (w, h):
            self._scan = pygame.Surface((w, h), pygame.SRCALPHA)
            for sy in range(0, h, 3):
                self._scan.fill((0, 0, 0, 46), (0, sy, w, 1))
        surface.blit(self._scan, (x, y))


class _GlitchModal(ModalState):
    def __init__(self, app, k):
        super().__init__(app)
        self.glitch = Glitch(k)
        self.time = 0.0

    def update(self, dt):
        self.time += dt
        self.glitch.update(dt)

    def animating(self):
        return True

    def _frame(self, size, k):
        return alarm_frame(size, k, self.time, theme.RADIUS)

    def _alarm(self, surface, k):
        overlay = pygame.Surface(surface.get_size(), pygame.SRCALPHA)
        a = int(40 + 60 * k * (0.6 + 0.4 * math.sin(self.time * 5)))
        overlay.fill((120, 0, 8, a))
        surface.blit(overlay, (0, 0))


class WarningState(_GlitchModal):
    def __init__(self, app, choice, on_go, cheat_fn=None, active_cheats=()):
        self.risk = choice.get("risk", 0)
        super().__init__(app, glitch_strength(self.risk))
        self.choice = choice
        self.on_go = on_go
        self.cheat_fn = cheat_fn
        self.cheats = list(choice.get("cheats") or []) if cheat_fn else []
        self.added = {c for c in self.cheats if c.lower() in (a.lower() for a in active_cheats)}
        self.plus_rects = {}
        self.back_btn = Button("Отступить", app.pop, size=17)
        self.go_btn = Button("Рискнуть", self._go, size=17, bold=True)

    def _go(self):
        self.app.pop()
        self.on_go()

    def _add(self, text):
        if text not in self.added and self.cheat_fn(text):
            self.added.add(text)

    def handle_event(self, event):
        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_ESCAPE:
                self.app.pop()
                return
            if event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                self._go()
                return
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            for text, rect in self.plus_rects.items():
                if rect.collidepoint(event.pos):
                    self._add(text)
                    return
        for b in (self.back_btn, self.go_btn):
            if b.handle_event(event):
                return

    def draw(self, surface):
        self.draw_backdrop(surface)
        k = self.glitch.k
        self._alarm(surface, k)
        w, h = surface.get_size()
        pw = min(PANEL_W, w - 24)
        color = _mix(theme.WARN, (255, 40, 50), k)
        warning = self.choice.get("warning") or "Последствия могут оказаться необратимыми."
        text_w = pw - 64
        lines_h = (len(wrap(self.choice["text"], text_w, 19, True)) * (fonts.get(19, True).get_linesize() + 3)
                   + len(wrap(warning, text_w, 16)) * (fonts.get(16).get_linesize() + 3))
        base_h = 112 + lines_h + 28 + 80
        cheats = self.cheats[:max(0, (h - 16 - base_h - 36) // CHEAT_ROW_H)]
        ph = base_h + ((36 + len(cheats) * CHEAT_ROW_H) if cheats else 0)
        panel = pygame.Rect((w - pw) // 2, max(8, (h - ph) // 2), pw, ph)

        img = self._frame(panel.size, k)
        draw_spaced(img, level_name(self.risk), (pw // 2, 40), 22, color, spacing=0.22)
        draw_text(img, f"РИСК {self.risk}%", (pw // 2, 70), 14, theme.TEXT_DIM, anchor="center")
        bar = pygame.Rect(32, 88, text_w, 8)
        fill_round(img, bar, (255, 255, 255), 24, 4)
        fill_round(img, pygame.Rect(bar.x, bar.y, max(8, bar.w * self.risk // 100), bar.h), color, 230, 4)
        y = draw_paragraph(img, self.choice["text"], (32, 112), text_w, 19, theme.TEXT, bold=True)
        y = draw_paragraph(img, warning, (32, y + 10), text_w, 16, _mix(theme.TEXT, color, 0.45))
        cheat_top = y + 18
        if cheats:
            pygame.draw.line(img, (70, 40, 44), (32, cheat_top), (pw - 32, cheat_top))
            draw_text(img, "ECLIPSE СОВЕТУЕТ ЧИТЫ (не обязательно)", (32, cheat_top + 12), 12, theme.WARN, bold=True)
            for i, text in enumerate(cheats):
                ry = cheat_top + 36 + i * CHEAT_ROW_H
                img.blit(fonts.mono(15).render(ellipsize("/" + text, pw - 130, fonts.mono(15)), True,
                                               theme.TEXT if text not in self.added else theme.TEXT_MUTED), (40, ry + 9))
        self.glitch.blit(surface, img, panel.topleft)

        self.plus_rects = {}
        mouse = pygame.mouse.get_pos()
        for i, text in enumerate(cheats):
            r = pygame.Rect(panel.right - 72, panel.y + cheat_top + 36 + i * CHEAT_ROW_H + 3, 36, 32)
            self.plus_rects[text] = r
            done = text in self.added
            hot = r.collidepoint(mouse) and not done
            fill_round(surface, r, theme.GOOD if done else theme.ACCENT, 200 if hot else 120, 10)
            cx, cy = r.center
            if done:
                pygame.draw.lines(surface, theme.TEXT, False, [(cx - 7, cy), (cx - 2, cy + 5), (cx + 8, cy - 6)], 3)
            else:
                pygame.draw.line(surface, theme.TEXT, (cx - 7, cy), (cx + 7, cy), 3)
                pygame.draw.line(surface, theme.TEXT, (cx, cy - 7), (cx, cy + 7), 3)
        self.back_btn.rect = pygame.Rect(panel.x + 32, panel.bottom - 62, min(200, (text_w - 12) // 2), 44)
        self.go_btn.rect = pygame.Rect(panel.right - 32 - self.back_btn.rect.w, panel.bottom - 62,
                                       self.back_btn.rect.w, 44)
        self.back_btn.draw(surface)
        self.go_btn.draw(surface)


class GameOverState(_GlitchModal):
    def __init__(self, app, title, text, on_load):
        super().__init__(app, 0.85)
        self.title = title
        self.text = text
        self.load_btn = Button("Загрузить сохранение", self._load(on_load), size=17, bold=True)
        self.menu_btn = Button("В главное меню", app.unwind, size=17)

    def _load(self, on_load):
        def run():
            self.app.pop()
            on_load()
        return run

    def handle_event(self, event):
        for b in (self.load_btn, self.menu_btn):
            if b.handle_event(event):
                return

    def draw(self, surface):
        self.draw_backdrop(surface)
        self._alarm(surface, 1.0)
        w, h = surface.get_size()
        pw = min(640, w - 24)
        text_h = len(wrap(self.text, pw - 80, 17)) * (fonts.get(17).get_linesize() + 3)
        ph = min(h - 16, max(330, 124 + text_h + 90))
        panel = pygame.Rect((w - pw) // 2, (h - ph) // 2, pw, ph)
        img = self._frame(panel.size, 1.0)
        draw_spaced(img, "ИГРА ОКОНЧЕНА", (pw // 2, 46), 30 if pw >= 520 else 22, (255, 50, 60), spacing=0.3)
        draw_spaced(img, self.title.upper(), (pw // 2, 90), 18, theme.TEXT, spacing=0.25)
        draw_paragraph(img, self.text, (40, 124), pw - 80, 17, theme.TEXT_DIM)
        self.glitch.blit(surface, img, panel.topleft)
        btn_w = (pw - 80 - 12) // 2
        self.load_btn.rect = pygame.Rect(panel.x + 40, panel.bottom - 66, btn_w, 44)
        self.menu_btn.rect = pygame.Rect(panel.right - 40 - btn_w, panel.bottom - 66, btn_w, 44)
        self.load_btn.draw(surface)
        self.menu_btn.draw(surface)
