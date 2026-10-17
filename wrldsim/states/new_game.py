import pygame

from ..ui import fonts, theme
from ..ui.widgets import Button, draw_panel, draw_paragraph, draw_spaced, draw_text, wrap
from .base import State

KINDS = [
    {"id": "real", "name": "REAL LIFE", "tagline": "Классический симулятор: реальный мир, любая эпоха.",
     "summary": ["Выбор эпохи: от первых царств до наших дней, с настоящими государствами, флагами и границами своего времени.",
                 "Режимы Realism (за всё платишь, настоящие поражения) и Arcade (песочница без поражений).",
                 "Правители управляют государством по-настоящему: казна, налоги, армия, указы, дипломатия, войны и границы, которые меняются со временем.",
                 "Ведёт игру ECLIPSE Prime."]},
    {"id": "anime", "name": "ANIME", "tagline": "Любое аниме: назовите его, и вы внутри.",
     "summary": ["Введите название любого аниме на любом языке: ECLIPSE Prime найдёт его в интернете.",
                 "Он соберёт мир: правила силы, организации, места, героев и точки старта по порядку канона.",
                 "Играйте за героя оригинала или за собственного персонажа, попавшего в этот мир.",
                 "Проиграть нельзя: история пойдёт дальше при любом исходе. Нужны интернет и ключ OpenRouter."]},
]


class NewGameKindState(State):
    def __init__(self, app):
        super().__init__(app)
        self.kind = KINDS[0]["id"]
        self.card_rects = {}
        self.back_btn = Button("← Назад", app.pop, size=18)
        self.next_btn = Button("Далее →", self._next, size=20, bold=True)

    def _next(self):
        if self.kind == "real":
            from .era_select import EraSelectState
            self.app.push(EraSelectState(self.app))
        else:
            from .anime_setup import AnimeSetupState
            self.app.push(AnimeSetupState(self.app))

    def handle_event(self, event):
        ids = [k["id"] for k in KINDS]
        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_ESCAPE:
                self.app.pop()
                return
            if event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                self._next()
                return
            if event.key in (pygame.K_LEFT, pygame.K_a, pygame.K_RIGHT, pygame.K_d):
                self.kind = ids[(ids.index(self.kind) + 1) % len(ids)]
                return
            if pygame.K_1 <= event.key < pygame.K_1 + len(ids):
                self.kind = ids[event.key - pygame.K_1]
                return
        for b in (self.back_btn, self.next_btn):
            if b.handle_event(event):
                return
        if event.type == pygame.MOUSEBUTTONUP and event.button == 1:
            for kid, rect in self.card_rects.items():
                if rect.collidepoint(event.pos):
                    if self.kind == kid:
                        self._next()
                    self.kind = kid

    def draw(self, surface):
        w, h = surface.get_size()
        surface.fill(theme.OCEAN)
        compact = h < 640
        draw_spaced(surface, "НОВАЯ ИГРА", (w // 2, 34 if compact else 56), 24 if compact else 30, spacing=0.25)
        draw_text(surface, "Выберите, во что играть.", (w // 2, 62 if compact else 90), 15, theme.TEXT_DIM, anchor="center")
        gap = 28
        content_w = min(1100, w - 60)
        x0 = (w - content_w) // 2
        card_w = (content_w - gap) // 2
        top = 92 if compact else 124
        card_h = max(300, h - top - (70 if compact else 96))
        for i, k in enumerate(KINDS):
            rect = pygame.Rect(x0 + i * (card_w + gap), top, card_w, card_h)
            self.card_rects[k["id"]] = rect
            selected = k["id"] == self.kind
            draw_panel(surface, rect, border=theme.ACCENT if selected else None)
            draw_text(surface, str(i + 1), (rect.right - 22, rect.y + 20), 13, theme.TEXT_MUTED, anchor="topright")
            draw_spaced(surface, k["name"], (rect.x + 26, rect.y + 44), 32, spacing=0.25, anchor="midleft")
            y = draw_paragraph(surface, k["tagline"], (rect.x + 26, rect.y + 80), rect.w - 52, 17, theme.ACCENT, bold=True)
            y += 10
            for line in k["summary"]:
                if y + len(wrap(line, rect.w - 76, 14)) * (fonts.get(14).get_linesize() + 1) > rect.bottom - 20:
                    break
                draw_text(surface, "—", (rect.x + 26, y), 14, theme.TEXT_DIM)
                y = draw_paragraph(surface, line, (rect.x + 48, y), rect.w - 76, 14, theme.TEXT_DIM, line_gap=1) + 8
        btn_h = 40 if compact else 48
        self.back_btn.rect = pygame.Rect(x0, h - btn_h - 16, 180, btn_h)
        self.next_btn.rect = pygame.Rect(x0 + content_w - 220, h - btn_h - 16, 220, btn_h)
        self.back_btn.draw(surface)
        self.next_btn.draw(surface)
