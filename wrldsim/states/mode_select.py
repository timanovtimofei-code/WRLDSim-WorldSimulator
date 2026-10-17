import pygame

from ..session import GameSession
from ..sim.modes import describe_difficulty
from ..ui import fonts, theme
from ..ui.widgets import Button, draw_panel, draw_paragraph, draw_spaced, draw_text, wrap
from .base import State

MODE_ORDER = ["realism", "arcade"]


class ModeSelectState(State):
    def __init__(self, app, era_id="modern"):
        super().__init__(app)
        self.era_id = era_id
        self.modes = app.modes["modes"]
        self.mode_id = next(m for m in MODE_ORDER if self.modes[m]["enabled"])
        self.diff_id = self.modes[self.mode_id]["default_difficulty"]
        self.card_rects = {}
        self.view = pygame.Rect(0, 0, 0, 0)
        self.scroll = self.max_scroll = 0
        self.diff_buttons = {
            did: Button(d["name"], lambda did=did: self._set_difficulty(did), size=17)
            for did, d in self.modes["realism"]["difficulties"].items()
        }
        self.back_btn = Button("← К выбору эпохи", self._back, size=18)
        self.start_btn = Button("Начать →", self._start, size=20, bold=True)

    def _set_difficulty(self, did):
        self.diff_id = did

    def _back(self):
        from .era_select import EraSelectState
        self.app.replace(EraSelectState(self.app, self.era_id))

    def _start(self):
        from .world_map import WorldMapState
        self.app.session = GameSession(self.mode_id, self.diff_id, era_id=self.era_id)
        self.app.replace(WorldMapState(self.app))

    def handle_event(self, event):
        if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
            self._back()
            return
        if event.type == pygame.MOUSEWHEEL and self.max_scroll:
            self.scroll = min(max(self.scroll - event.y * 50, 0), self.max_scroll)
            return
        inside = event.type != pygame.MOUSEBUTTONDOWN or self.view.collidepoint(event.pos)
        for b in [*(self.diff_buttons.values() if inside else ()), self.back_btn, self.start_btn]:
            if b.handle_event(event):
                return
        if event.type == pygame.MOUSEBUTTONUP and event.button == 1 and self.view.collidepoint(event.pos):
            for mid, rect in self.card_rects.items():
                if rect.collidepoint(event.pos) and self.modes[mid]["enabled"]:
                    self.mode_id = mid
                    self.diff_id = self.modes[mid]["default_difficulty"]

    def draw(self, surface):
        w, h = surface.get_size()
        surface.fill(theme.OCEAN)
        compact = h < 640
        draw_spaced(surface, "ВЫБОР РЕЖИМА", (w // 2, 34 if compact else 56), 24 if compact else 30, spacing=0.25)
        draw_text(surface, self.app.eras.era(self.era_id)["name"].title(), (w // 2, 60 if compact else 84), 15,
                  theme.ACCENT, bold=True, anchor="center")

        content_w, gap = min(1040, w - 80), 40
        x0 = (w - content_w) // 2
        btn_h = 40 if compact else 48
        top = 82 if compact else 100
        self.view = pygame.Rect(0, top, w, h - btn_h - 32 - top)
        card_w = (content_w - gap) // 2
        card_h = max(300, min(360, h - 380), *(self._card_text_h(m, card_w) for m in MODE_ORDER))
        has_difficulty = bool(self.modes[self.mode_id]["difficulties"])
        content_h = card_h + (20 + 150 if has_difficulty else 0)
        self.max_scroll = max(0, content_h - self.view.h)
        self.scroll = min(self.scroll, self.max_scroll)
        prev = surface.get_clip()
        surface.set_clip(self.view.clip(prev))
        y = top - self.scroll
        for i, mid in enumerate(MODE_ORDER):
            rect = pygame.Rect(x0 + i * (card_w + gap), y, card_w, card_h)
            self.card_rects[mid] = rect
            self._draw_card(surface, rect, mid)
        self._draw_difficulty(surface, pygame.Rect(x0, y + card_h + 20, content_w, 150))
        surface.set_clip(prev)

        self.back_btn.rect = pygame.Rect(x0, h - btn_h - 16, 240, btn_h)
        self.start_btn.rect = pygame.Rect(x0 + content_w - 220, h - btn_h - 16, 220, btn_h)
        self.back_btn.draw(surface)
        self.start_btn.draw(surface)

    def _card_text_h(self, mid, card_w):
        mode = self.modes[mid]
        h = 62 + len(wrap(mode["tagline"], card_w - 48, 16)) * (fonts.get(16).get_linesize() + 3) + 8
        for line in mode["summary"]:
            h += len(wrap(line, card_w - 68, 14)) * (fonts.get(14).get_linesize() + 1) + 6
        return h + 20

    def _draw_card(self, surface, rect, mid):
        mode = self.modes[mid]
        enabled = mode["enabled"]
        selected = mid == self.mode_id
        draw_panel(surface, rect, border=theme.ACCENT if selected else None)

        text_color = theme.TEXT if enabled else theme.TEXT_MUTED
        draw_spaced(surface, mode["name"], (rect.x + 24, rect.y + 34), 30, text_color, spacing=0.25, anchor="midleft")
        if not enabled:
            badge = draw_text(surface, "В РАЗРАБОТКЕ", (rect.right - 24, rect.y + 34), 13,
                              theme.WARN, bold=True, anchor="midright")
            pygame.draw.rect(surface, theme.WARN, badge.inflate(14, 8), 1, border_radius=8)
        y = draw_paragraph(surface, mode["tagline"], (rect.x + 24, rect.y + 62), rect.w - 48, 16,
                           theme.ACCENT if enabled else theme.TEXT_MUTED)
        y += 8
        for line in mode["summary"]:
            draw_text(surface, "—", (rect.x + 24, y), 14, theme.TEXT_DIM if enabled else theme.TEXT_MUTED)
            y = draw_paragraph(surface, line, (rect.x + 44, y), rect.w - 68, 14,
                               theme.TEXT_DIM if enabled else theme.TEXT_MUTED, line_gap=1) + 6

    def _draw_difficulty(self, surface, rect):
        mode = self.modes[self.mode_id]
        if not mode["difficulties"]:
            return
        draw_text(surface, "СЛОЖНОСТЬ", (rect.x, rect.y), 15, theme.TEXT_DIM, bold=True)
        bx = rect.x
        for did, b in self.diff_buttons.items():
            b.selected = did == self.diff_id
            b.rect = pygame.Rect(bx, rect.y + 28, 160, 42)
            b.draw(surface)
            bx += 172

        rows = describe_difficulty(mode["difficulties"][self.diff_id])
        cols = 3
        col_w = rect.w // cols
        per_col = -(-len(rows) // cols)
        for i, (label, value) in enumerate(rows):
            x = rect.x + (i // per_col) * col_w
            y = rect.y + 86 + (i % per_col) * 24
            draw_text(surface, label, (x, y), 14, theme.TEXT_DIM)
            draw_text(surface, value, (x + col_w - 28, y), 14, theme.TEXT, bold=True, anchor="topright")
