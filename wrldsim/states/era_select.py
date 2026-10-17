import pygame

from ..ui import fonts, theme
from ..ui.widgets import Button, draw_panel, draw_paragraph, draw_spaced, draw_text, wrap
from .base import State


class EraSelectState(State):
    def __init__(self, app, era_id=None):
        super().__init__(app)
        self.order = app.eras.order
        self.era_id = era_id if era_id in self.order else self.order[0]
        self.card_rects = {}
        self.back_btn = Button("← Назад", app.pop, size=18)
        self.next_btn = Button("Далее →", self._next, size=20, bold=True)

    def _next(self):
        from .mode_select import ModeSelectState
        self.app.replace(ModeSelectState(self.app, self.era_id))

    def _step(self, delta):
        self.era_id = self.order[(self.order.index(self.era_id) + delta) % len(self.order)]

    def handle_event(self, event):
        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_ESCAPE:
                self.app.pop()
                return
            if event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                self._next()
                return
            if event.key in (pygame.K_LEFT, pygame.K_a):
                self._step(-1)
                return
            if event.key in (pygame.K_RIGHT, pygame.K_d):
                self._step(1)
                return
            if pygame.K_1 <= event.key < pygame.K_1 + len(self.order):
                self.era_id = self.order[event.key - pygame.K_1]
                return
        for b in (self.back_btn, self.next_btn):
            if b.handle_event(event):
                return
        if event.type == pygame.MOUSEBUTTONUP and event.button == 1:
            for eid, rect in self.card_rects.items():
                if rect.collidepoint(event.pos):
                    self.era_id = eid

    def draw(self, surface):
        w, h = surface.get_size()
        surface.fill(theme.OCEAN)
        compact = h < 640
        draw_spaced(surface, "ВЕТВЬ ВРЕМЕНИ", (w // 2, 34 if compact else 50), 24 if compact else 30, spacing=0.25)
        draw_text(surface, "Выберите эпоху: от неё зависят государства, роли, события и правила, "
                  "по которым ECLIPSE Prime ведёт историю.", (w // 2, 66 if compact else 90), 15, theme.TEXT_DIM,
                  anchor="center")

        n = len(self.order)
        gap = 22
        content_w = min(1300, w - 60)
        x0 = (w - content_w) // 2
        card_w = (content_w - gap * (n - 1)) // n
        top = 92 if compact else 124
        card_h = max(220, h - top - (70 if compact else 96))
        for i, eid in enumerate(self.order):
            rect = pygame.Rect(x0 + i * (card_w + gap), top, card_w, card_h)
            self.card_rects[eid] = rect
            self._draw_card(surface, rect, eid, i + 1)

        btn_h = 40 if compact else 48
        self.back_btn.rect = pygame.Rect(x0, h - btn_h - 16, 180, btn_h)
        self.next_btn.rect = pygame.Rect(x0 + content_w - 220, h - btn_h - 16, 220, btn_h)
        self.back_btn.draw(surface)
        self.next_btn.draw(surface)

    def _draw_card(self, surface, rect, eid, number):
        era = self.app.eras.era(eid)
        selected = eid == self.era_id
        draw_panel(surface, rect, border=theme.ACCENT if selected else None)
        x, w = rect.x + 22, rect.w - 44
        draw_text(surface, str(number), (rect.right - 22, rect.y + 20), 13, theme.TEXT_MUTED, anchor="topright")
        y = draw_paragraph(surface, era["name"], (x, rect.y + 20), w - 20, 24, theme.TEXT, bold=True)
        draw_text(surface, era["period"], (x, y + 2), 15, theme.ACCENT, bold=True)
        y = draw_paragraph(surface, era["tagline"], (x, y + 28), w, 15, theme.TEXT, line_gap=2) + 10
        limit = rect.bottom - 70
        line_h = fonts.get(13).get_linesize() + 1
        for line in era["summary"]:
            if y + len(wrap(line, w - 22, 13)) * line_h > limit:
                break
            draw_text(surface, "—", (x, y), 13, theme.TEXT_DIM)
            y = draw_paragraph(surface, line, (x + 20, y), w - 22, 13, theme.TEXT_DIM, line_gap=1) + 6
        names = ", ".join(self.app.eras.sample_names(eid, 7))
        footer = f"Любая страна мира, {names}" if not era["restricted"] else f"{names} и другие"
        lines = wrap(footer, w, 12)[:3]
        footer_y = rect.bottom - 14 - len(lines) * 15
        pygame.draw.line(surface, theme.PANEL_BORDER, (x, footer_y - 8), (x + w, footer_y - 8))
        for i, line in enumerate(lines):
            draw_text(surface, line, (x, footer_y + i * 15), 12, theme.TEXT_MUTED)
