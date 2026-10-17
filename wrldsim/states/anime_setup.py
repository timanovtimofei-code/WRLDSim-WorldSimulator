import time
from urllib.parse import urlparse

import pygame

from ..sim import anime as anime_mod
from ..ui import fonts, theme
from ..ui.widgets import (Button, TextInput, draw_panel, draw_paragraph, draw_spaced, draw_text, ellipsize, fill_round,
                          text_surface, wrap)
from .base import State

EXAMPLES = "Например: Наруто, Attack on Titan, Fullmetal Alchemist, Ванпанчмен, Evangelion, Hunter x Hunter"
GENDERS = ["М", "Ж", "иное"]
CUSTOM = -1


class AnimeSetupState(State):
    def __init__(self, app):
        super().__init__(app)
        self.phase = "ask"
        self.title_input = TextInput(size=24, max_len=80)
        self.name_input = TextInput(size=17, max_len=40)
        self.role_input = TextInput(size=17, max_len=140)
        self.focus = "title"
        self.research = None
        self.error = None
        self.card = None
        self.start_idx = 0
        self.hero_idx = 0
        self.age, self.gender = 17, "М"
        self.scroll_l = self.scroll_r = 0
        self.max_l = self.max_r = 0
        self.rect_l = self.rect_r = pygame.Rect(0, 0, 0, 0)
        self.hits = []
        self.back_btn = Button("← Назад", self._back, size=18)
        self.find_btn = Button("Найти мир →", self._search, size=20, bold=True)
        self.cancel_btn = Button("Отмена", self._cancel, size=18)
        self.other_btn = Button("← Другое аниме", self._other, size=16)
        self.go_btn = Button("Начать игру →", self._go, size=20, bold=True)

    def _back(self):
        self.app.pop()

    def _other(self):
        self.phase, self.card, self.error = "ask", None, None
        self.focus = "title"

    def _cancel(self):
        self.research = None
        self.phase = "ask"

    def _search(self):
        query = self.title_input.text.strip()
        if not query:
            return
        self.error = None
        self.research = anime_mod.AnimeResearch(self.app.arcade_cfg["eclipse"], query)
        self.phase = "search"

    def _hero(self):
        if self.hero_idx == CUSTOM:
            name = self.name_input.text.strip() or "Безымянный"
            role = self.role_input.text.strip() or "Путешественник из другого мира"
            return {"name": name, "role": role, "age": self.age, "gender": self.gender, "canon": False}
        c = self.card["characters"][self.hero_idx]
        return {"name": c["name"], "role": f"{c['role']}", "age": c.get("age") or 17, "gender": c.get("gender") or "иное",
                "canon": True}

    def _go(self):
        from .arcade_game import start_anime
        if self.hero_idx == CUSTOM and not self.name_input.text.strip():
            self.focus = "name"
            return
        start = self.card["starts"][self.start_idx]
        start_anime(self.app, self.card, self._hero(), start)

    def _poll(self):
        r = self.research
        if r is None or not r.done:
            return
        self.research = None
        if r.error:
            self.error, self.phase = r.error, "ask"
            self.focus = "title"
            return
        self.card = r.card
        self.phase, self.start_idx = "card", 0
        self.hero_idx = 0 if self.card["characters"] else CUSTOM
        self.scroll_l = self.scroll_r = 0

    def _inputs(self):
        if self.phase == "ask":
            return {"title": self.title_input}
        if self.phase == "card" and self.hero_idx == CUSTOM:
            return {"name": self.name_input, "role": self.role_input}
        return {}

    def handle_event(self, event):
        if self.phase == "search":
            if (event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE):
                self._cancel()
                return
            self.cancel_btn.handle_event(event)
            return
        inputs = self._inputs()
        if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
            self._back() if self.phase == "ask" else self._other()
            return
        if event.type == pygame.KEYDOWN and event.key == pygame.K_TAB and len(inputs) > 1:
            keys = list(inputs)
            self.focus = keys[(keys.index(self.focus) + 1) % len(keys)] if self.focus in keys else keys[0]
            return
        if event.type == pygame.KEYDOWN and event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
            if self.phase == "ask":
                self._search()
            else:
                self._go()
            return
        if self.focus in inputs and event.type in (pygame.TEXTINPUT, pygame.KEYDOWN):
            inputs[self.focus].handle_event(event)
            return
        if self.phase == "ask":
            for b in (self.back_btn, self.find_btn):
                if b.handle_event(event):
                    return
            if event.type == pygame.MOUSEBUTTONDOWN and self.title_input.rect.collidepoint(event.pos):
                self.focus = "title"
            return
        if event.type == pygame.MOUSEWHEEL:
            pos = pygame.mouse.get_pos()
            if self.rect_l.collidepoint(pos):
                self.scroll_l = min(max(self.scroll_l - event.y * 50, 0), self.max_l)
            elif self.rect_r.collidepoint(pos):
                self.scroll_r = min(max(self.scroll_r - event.y * 50, 0), self.max_r)
            return
        for b in (self.other_btn, self.go_btn):
            if b.handle_event(event):
                return
        if event.type == pygame.MOUSEBUTTONUP and event.button == 1:
            for rect, cb in reversed(self.hits):
                if rect.collidepoint(event.pos) and self.rect_r.collidepoint(event.pos):
                    cb()
                    return
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            for key, inp in inputs.items():
                if inp.rect.collidepoint(event.pos) and self.rect_r.collidepoint(event.pos):
                    self.focus = key

    def update(self, dt):
        self._poll()
        for inp in (self.title_input, self.name_input, self.role_input):
            inp.update(dt)

    def draw(self, surface):
        w, h = surface.get_size()
        surface.fill(theme.OCEAN)
        compact = h < 640
        draw_spaced(surface, "ANIME", (w // 2, 34 if compact else 52), 24 if compact else 30, spacing=0.25)
        if self.phase == "ask":
            self._draw_ask(surface)
        elif self.phase == "search":
            self._draw_search(surface)
        else:
            self._draw_card(surface)

    def _draw_ask(self, surface):
        w, h = surface.get_size()
        cw = min(760, w - 60)
        x = (w - cw) // 2
        y = max(110, h // 2 - 150)
        draw_text(surface, "В какое аниме отправимся?", (w // 2, y), 24, theme.TEXT, bold=True, anchor="midtop")
        y += 46
        self.title_input.rect = pygame.Rect(x, y, cw, 58)
        self.title_input.caret = self.focus == "title"
        self.title_input.draw(surface, placeholder="Название аниме, манги или ранобэ")
        y += 76
        for line in wrap("ECLIPSE Prime найдёт его в интернете и соберёт мир: правила, героев, места и точки старта. "
                         "Поиск занимает от десятка секунд до пары минут.", cw, 15):
            draw_text(surface, line, (w // 2, y), 15, theme.TEXT_DIM, anchor="midtop")
            y += 22
        y += 6
        for line in wrap(EXAMPLES, cw, 13):
            draw_text(surface, line, (w // 2, y), 13, theme.TEXT_MUTED, anchor="midtop")
            y += 19
        if self.error:
            y += 14
            for line in wrap(self.error, cw, 16, True):
                draw_text(surface, line, (w // 2, y), 16, theme.WARN, bold=True, anchor="midtop")
                y += 23
        self.find_btn.enabled = bool(self.title_input.text.strip())
        self.find_btn.rect = pygame.Rect(w // 2 + 10, h - 76, min(260, cw // 2 - 10), 48)
        self.back_btn.rect = pygame.Rect(w // 2 - 10 - min(180, cw // 2 - 10), h - 76, min(180, cw // 2 - 10), 48)
        self.find_btn.draw(surface)
        self.back_btn.draw(surface)

    def _draw_search(self, surface):
        w, h = surface.get_size()
        r = self.research
        elapsed = int(time.monotonic() - r.started) if r else 0
        dots = "." * (1 + int(time.monotonic() * 2) % 3)
        draw_text(surface, f"ECLIPSE Prime ищет «{r.query if r else ''}» в интернете{dots}", (w // 2, h // 2 - 40), 22,
                  theme.TEXT, bold=True, anchor="center")
        draw_text(surface, f"Читает страницы и собирает мир. Прошло {elapsed} с.", (w // 2, h // 2 + 4), 16, theme.TEXT_DIM,
                  anchor="center")
        self.cancel_btn.rect = pygame.Rect(w // 2 - 100, h // 2 + 60, 200, 46)
        self.cancel_btn.draw(surface)

    def _draw_card(self, surface):
        w, h = surface.get_size()
        card = self.card
        top, bottom = 84, h - 84
        gap = 18
        total = min(1280, w - 40)
        x0 = (w - total) // 2
        left_w = int(total * 0.52)
        self.rect_l = pygame.Rect(x0, top, left_w, bottom - top)
        self.rect_r = pygame.Rect(self.rect_l.right + gap, top, total - left_w - gap, bottom - top)
        self._draw_world(surface, self.rect_l, card)
        self._draw_hero(surface, self.rect_r, card)
        self.other_btn.rect = pygame.Rect(x0, h - 66, 220, 46)
        self.go_btn.rect = pygame.Rect(x0 + total - 260, h - 66, 260, 46)
        self.other_btn.draw(surface)
        self.go_btn.draw(surface)

    def _draw_world(self, surface, rect, card):
        draw_panel(surface, rect)
        view = rect.inflate(-4, -12)
        prev = surface.get_clip()
        surface.set_clip(view.clip(prev))
        x, w = rect.x + 24, rect.w - 48
        y = rect.y + 20 - self.scroll_l
        y = draw_paragraph(surface, anime_mod.card_name(card), (x, y), w, 26, theme.TEXT, bold=True)
        meta = " · ".join(str(v) for v in (card.get("kind"), card.get("year"), ", ".join(card.get("genres") or [])) if v)
        draw_text(surface, ellipsize(meta, w, fonts.get(14)), (x, y + 2), 14, theme.ACCENT, bold=True)
        y += 30
        for title, text in (("О мире", card.get("summary")), ("Место и время", card.get("setting")),
                            ("Правила мира", card.get("world_rules")), ("Тон", card.get("tone"))):
            if not text:
                continue
            draw_text(surface, title.upper(), (x, y), 11, theme.ACCENT, bold=True)
            y = draw_paragraph(surface, text, (x, y + 16), w, 14, theme.TEXT, line_gap=2) + 12
        for title, items, key in (("Фракции", card.get("factions"), "desc"), ("Места", card.get("locations"), "desc")):
            if not items:
                continue
            draw_text(surface, title.upper(), (x, y), 11, theme.ACCENT, bold=True)
            y += 18
            for it in items:
                draw_text(surface, it["name"], (x, y), 14, theme.TEXT, bold=True)
                y = draw_paragraph(surface, it[key], (x + 14, y + 18), w - 14, 13, theme.TEXT_DIM, line_gap=1) + 6
            y += 6
        if card.get("sources"):
            hosts = ", ".join(sorted({urlparse(u).netloc.removeprefix("www.") for u in card["sources"] if u}))
            draw_text(surface, ellipsize("Источники: " + hosts, w, fonts.get(12)), (x, y), 12, theme.TEXT_MUTED)
            y += 20
        elif card.get("offline"):
            draw_text(surface, ellipsize("Поиск в интернете не сработал: описание собрано по памяти модели.", w, fonts.get(12)),
                      (x, y), 12, theme.WARN)
            y += 20
        surface.set_clip(prev)
        self.max_l = max(0, y + self.scroll_l - (rect.y + 20) - view.h + 40)
        self.scroll_l = min(self.scroll_l, self.max_l)

    def _btn(self, surface, rect, text, cb, selected=False, size=14):
        hover = rect.collidepoint(pygame.mouse.get_pos()) and self.rect_r.collidepoint(pygame.mouse.get_pos())
        base = theme.mix(theme.GLASS_COLOR, theme.TEXT, 0.12 if hover else 0.05)
        if selected:
            base = theme.mix(base, theme.ACCENT, 0.4)
        fill_round(surface, rect, base, 235, 10)
        if selected:
            pygame.draw.rect(surface, theme.ACCENT, rect, 1, border_radius=10)
        img = text_surface(ellipsize(text, rect.w - 16, fonts.get(size, selected)), size, theme.TEXT, selected)
        surface.blit(img, img.get_rect(midleft=(rect.x + 10, rect.centery)))
        self.hits.append((rect, cb))

    def _draw_hero(self, surface, rect, card):
        draw_panel(surface, rect)
        self.hits = []
        view = rect.inflate(-4, -12)
        prev = surface.get_clip()
        surface.set_clip(view.clip(prev))
        x, w = rect.x + 20, rect.w - 40
        y = rect.y + 20 - self.scroll_r
        draw_text(surface, "ТОЧКА СТАРТА", (x, y), 11, theme.ACCENT, bold=True)
        y += 20
        for i, st in enumerate(card["starts"]):
            r = pygame.Rect(x, y, w, 34)
            self._btn(surface, r, st["label"], lambda i=i: setattr(self, "start_idx", i), i == self.start_idx)
            y += 38
        note = card["starts"][self.start_idx]["note"]
        y = draw_paragraph(surface, note, (x, y + 2), w, 13, theme.TEXT_DIM, line_gap=2) + 14
        draw_text(surface, "КЕМ ИГРАТЬ", (x, y), 11, theme.ACCENT, bold=True)
        y += 20
        for i, c in enumerate(card["characters"]):
            r = pygame.Rect(x, y, w, 34)
            self._btn(surface, r, f"{c['name']} · {c['role']}", lambda i=i: self._pick_hero(i), i == self.hero_idx)
            y += 38
        r = pygame.Rect(x, y, w, 34)
        self._btn(surface, r, "Свой персонаж…", lambda: self._pick_hero(CUSTOM), self.hero_idx == CUSTOM)
        y += 44
        if self.hero_idx == CUSTOM:
            draw_text(surface, "ИМЯ", (x, y), 11, theme.TEXT_MUTED, bold=True)
            self.name_input.rect = pygame.Rect(x, y + 16, w, 40)
            self.name_input.caret = self.focus == "name"
            self.name_input.draw(surface, placeholder="Как вас зовут")
            y += 66
            draw_text(surface, "КТО ВЫ И ЧТО УМЕЕТЕ", (x, y), 11, theme.TEXT_MUTED, bold=True)
            self.role_input.rect = pygame.Rect(x, y + 16, w, 40)
            self.role_input.caret = self.focus == "role"
            self.role_input.draw(surface, placeholder="Например: школьник с даром предвидения")
            y += 66
            draw_text(surface, f"Возраст: {self.age}", (x, y + 8), 15, theme.TEXT)
            self._btn(surface, pygame.Rect(x + 150, y, 40, 34), "−", lambda: setattr(self, "age", max(8, self.age - 1)), size=18)
            self._btn(surface, pygame.Rect(x + 196, y, 40, 34), "+", lambda: setattr(self, "age", min(99, self.age + 1)), size=18)
            self._btn(surface, pygame.Rect(x + 262, y, 110, 34), f"Пол: {self.gender}", self._cycle_gender)
            y += 46
        else:
            c = card["characters"][self.hero_idx]
            y = draw_paragraph(surface, c["desc"], (x, y), w, 13, theme.TEXT_DIM, line_gap=2) + 8
        surface.set_clip(prev)
        self.max_r = max(0, y + self.scroll_r - (rect.y + 20) - view.h + 40)
        self.scroll_r = min(self.scroll_r, self.max_r)

    def _pick_hero(self, i):
        self.hero_idx = i
        self.focus = "name" if i == CUSTOM else None

    def _cycle_gender(self):
        self.gender = GENDERS[(GENDERS.index(self.gender) + 1) % len(GENDERS)]
