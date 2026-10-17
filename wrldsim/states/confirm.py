import pygame

from ..ui import fonts, theme
from ..ui.widgets import Button, draw_panel, draw_paragraph, draw_spaced, wrap
from .base import ModalState


class ChoiceState(ModalState):
    def __init__(self, app, title, message, options):
        super().__init__(app)
        self.title = title
        self.message = message
        self.buttons = [Button(text, self._wrap(fn), size=16, bold=main) for text, fn, main in options]
        self.cancel_btn = Button("Отмена", app.pop, size=16)

    def _wrap(self, fn):
        def run():
            self.app.pop()
            fn()
        return run

    def handle_event(self, event):
        if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
            self.app.pop()
            return
        for b in (*self.buttons, self.cancel_btn):
            if b.handle_event(event):
                return

    def draw(self, surface):
        w, h = surface.get_size()
        self.draw_backdrop(surface)
        pw = min(560, w - 24)
        message_h = len(wrap(self.message, pw - 64, 16)) * (fonts.get(16).get_linesize() + 3)
        ph = min(h - 16, 70 + message_h + 16 + len(self.buttons) * 54 + 64)
        panel = pygame.Rect((w - pw) // 2, (h - ph) // 2, pw, ph)
        draw_panel(surface, panel, alpha=250, border=theme.WARN)
        draw_spaced(surface, self.title, (panel.centerx, panel.y + 38), 20, theme.WARN, spacing=0.2)
        y = draw_paragraph(surface, self.message, (panel.x + 32, panel.y + 70), pw - 64, 16, theme.TEXT) + 16
        for b in self.buttons:
            b.rect = pygame.Rect(panel.x + 32, y, pw - 64, 44)
            b.draw(surface)
            y += 54
        self.cancel_btn.rect = pygame.Rect(panel.right - 192, panel.bottom - 60, 160, 40)
        self.cancel_btn.draw(surface)


class ConfirmState(ModalState):
    def __init__(self, app, title, message, on_accept, accept_text="Принять", cancel_text="Отмена"):
        super().__init__(app)
        self.title = title
        self.message = message
        self.on_accept = on_accept
        self.cancel_btn = Button(cancel_text, app.pop, size=17)
        self.accept_btn = Button(accept_text, self._accept, size=17, bold=True)

    def _accept(self):
        self.app.pop()
        self.on_accept()

    def handle_event(self, event):
        if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
            self.app.pop()
            return
        if event.type == pygame.KEYDOWN and event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
            self._accept()
            return
        for b in (self.cancel_btn, self.accept_btn):
            if b.handle_event(event):
                return

    def draw(self, surface):
        w, h = surface.get_size()
        self.draw_backdrop(surface)
        pw = min(520, w - 24)
        message_h = len(wrap(self.message, pw - 64, 16)) * (fonts.get(16).get_linesize() + 3)
        ph = min(h - 16, max(250, 76 + message_h + 90))
        panel = pygame.Rect((w - pw) // 2, (h - ph) // 2, pw, ph)
        draw_panel(surface, panel, alpha=250, border=theme.WARN)
        draw_spaced(surface, self.title, (panel.centerx, panel.y + 38), 20, theme.WARN, spacing=0.2)
        draw_paragraph(surface, self.message, (panel.x + 32, panel.y + 76), pw - 64, 16, theme.TEXT)
        btn_w = min(200, (pw - 76) // 2)
        self.cancel_btn.rect = pygame.Rect(panel.x + 32, panel.bottom - 66, btn_w, 44)
        self.accept_btn.rect = pygame.Rect(panel.right - 32 - btn_w, panel.bottom - 66, btn_w, 44)
        self.cancel_btn.draw(surface)
        self.accept_btn.draw(surface)
