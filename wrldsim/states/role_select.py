import random

import pygame

from ..sim import roles as role_stats
from ..ui import fonts, theme
from ..ui.gauge import PYRAMID_W, draw_gauge, draw_pyramid
from ..ui.widgets import (Button, NumberField, TextInput, draw_glass_card, draw_panel, draw_paragraph, draw_spaced,
                          draw_text, draw_tooltip, ellipsize)
from .base import ModalState

CUSTOM_HINT = "Или впишите свою роль и нажмите Enter"
NAME_HINT = "Или впишите своё имя и нажмите Enter"
STEPS = 3
CARD_GAP = 12
HEAD_H = 30
NAME_COUNT = 15
LABEL_W = 58


class RoleSelectState(ModalState):
    def __init__(self, app, country_name, on_done, name_ctx, roles=None):
        super().__init__(app)
        self.country_name = country_name
        self.on_done = on_done
        cfg = app.roles
        self.roles = roles or cfg["roles"]
        self.sorted_roles = role_stats.by_status(self.roles)
        self.tiers = {r["id"]: role_stats.tier(r["start"]) for r in self.roles}
        self.genders = cfg["genders"]
        self.age_cfg = cfg["age"]
        self.name_ctx = name_ctx
        self.name_pool = app.names.pool(**self.name_ctx)
        self.rng = random.Random()

        self.page = 0
        self.role_id = None
        self.gender_id = None
        self.custom = TextInput(size=16, max_len=80)
        self.custom.radius = 16
        self.custom_focused = False
        self.age = NumberField(self.age_cfg["max"], size=22)
        self.age.value = self.age_cfg["default"]
        self.card_rects = {}
        self.grid_rect = pygame.Rect(0, 0, 0, 0)
        self.scroll = 0
        self.max_scroll = 0
        self.gender_btns = {g["id"]: Button(g["name"], lambda gid=g["id"]: self._set_gender(gid), size=18)
                            for g in self.genders}
        self.age_btns = [Button(str(a), lambda a=a: self._set_age(a), size=16) for a in self.age_cfg["presets"]]

        self.suggestions = []
        self.name_idx = None
        self.name_rects = []
        self.rolled_for = None
        self.custom_name = TextInput(size=16, max_len=60)
        self.custom_name.radius = 16
        self.name_focused = False
        self.reroll_btn = Button("Другие варианты", self._roll, size=15)

        self.back_btn = Button("← Назад", self._back, size=17)
        self.next_btn = Button("Далее →", self._next, size=18, bold=True)

    @property
    def role_name(self):
        text = self.custom.text.strip()
        if text:
            return text
        role = next((r for r in self.roles if r["id"] == self.role_id), None)
        return role["name"] if role else None

    @property
    def gender_name(self):
        return next((g["name"] for g in self.genders if g["id"] == self.gender_id), None)

    @property
    def hero_name(self):
        text = self.custom_name.text.strip()
        if text:
            return text
        if self.name_idx is not None and self.name_idx < len(self.suggestions):
            return self.suggestions[self.name_idx]["name"]
        return None

    def _set_gender(self, gid):
        self.gender_id = gid

    def _set_age(self, age):
        self.age.value = age
        self.age.focused = False

    def _roll(self):
        self.suggestions = self.app.names.suggest(self.name_pool, self.gender_id or "other", NAME_COUNT, self.rng)
        self.name_idx = 0 if self.suggestions else None
        self.custom_name.text = ""
        self.rolled_for = self.gender_id

    def _back(self):
        if self.page == 0:
            self.app.pop()
        else:
            self.page -= 1

    def _clamped_age(self):
        return min(max(self.age.value, self.age_cfg["min"]), self.age_cfg["max"])

    def _next(self):
        if self.page == 0:
            if self.role_name:
                self.page = 1
            return
        if self.page == 1:
            if self.gender_id is not None:
                if self.rolled_for != self.gender_id:
                    self._roll()
                self.page = 2
            return
        name = self.hero_name
        if not name:
            return
        custom = bool(self.custom.text.strip())
        hero = {"name": name, "role": self.role_name, "age": self._clamped_age(), "gender": self.gender_name,
                "role_id": None if custom else self.role_id}
        self.app.pop()
        self.on_done(hero)

    def handle_event(self, event):
        if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
            if self.custom_focused or self.name_focused or self.age.focused:
                self.custom_focused = self.name_focused = False
                self.age.blur()
            else:
                self._back()
            return
        if self.page == 0:
            self._event_role(event)
        elif self.page == 1:
            self._event_hero(event)
        else:
            self._event_name(event)
        for b in (self.back_btn, self.next_btn):
            if b.handle_event(event):
                return

    def _event_role(self, event):
        if event.type == pygame.MOUSEWHEEL and self.grid_rect.collidepoint(pygame.mouse.get_pos()):
            self.scroll = min(max(self.scroll - event.y * 60, 0), self.max_scroll)
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            self.custom_focused = self.custom.rect.collidepoint(event.pos)
        if event.type == pygame.MOUSEBUTTONUP and event.button == 1 and self.grid_rect.collidepoint(event.pos):
            for rid, rect in self.card_rects.items():
                if rect.collidepoint(event.pos):
                    self.role_id = rid
                    self.custom.text = ""
        if self.custom_focused and event.type in (pygame.TEXTINPUT, pygame.KEYDOWN):
            text = self.custom.handle_event(event)
            if self.custom.text:
                self.role_id = None
            if text:
                self.custom.text = text
                self._next()

    def _event_hero(self, event):
        if event.type == pygame.KEYDOWN and event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
            self.age.blur()
            return
        for b in [*self.age_btns, *self.gender_btns.values()]:
            if b.handle_event(event):
                return
        if self.age.handle_event(event):
            return
        if event.type == pygame.MOUSEBUTTONDOWN:
            self.age.blur()

    def _event_name(self, event):
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            self.name_focused = self.custom_name.rect.collidepoint(event.pos)
        if event.type == pygame.MOUSEBUTTONUP and event.button == 1:
            for i, rect in enumerate(self.name_rects):
                if rect.collidepoint(event.pos):
                    self.name_idx = i
                    self.custom_name.text = ""
        if self.reroll_btn.handle_event(event):
            return
        if self.name_focused and event.type in (pygame.TEXTINPUT, pygame.KEYDOWN):
            entered = self.custom_name.handle_event(event)
            if entered:
                self.custom_name.text = entered
                self._next()

    def update(self, dt):
        self.custom.update(dt)
        self.custom_name.update(dt)

    def draw(self, surface):
        w, h = surface.get_size()
        self.draw_backdrop(surface)
        pw, ph = min(1120, w - 24), min(780, h - 24)
        panel = pygame.Rect((w - pw) // 2, (h - ph) // 2, pw, ph)
        compact = ph < 600
        draw_panel(surface, panel, alpha=250, border=theme.ACCENT)

        head = 26 if compact else 34
        draw_spaced(surface, "ECLIPSE PRIME", (panel.x + 28, panel.y + head), 18 if compact else 20, theme.ACCENT,
                    spacing=0.25, anchor="midleft")
        draw_text(surface, f"Шаг {self.page + 1} из {STEPS}", (panel.right - 28, panel.y + head), 14, theme.TEXT_DIM,
                  anchor="midright")
        rule = panel.y + head + 28
        pygame.draw.line(surface, theme.PANEL_BORDER, (panel.x + 20, rule), (panel.right - 20, rule))

        btn_h = 38 if compact else 44
        btn_y = panel.bottom - btn_h - (14 if compact else 20)
        self.back_btn.rect = pygame.Rect(panel.x + 28, btn_y, 150 if compact else 160, btn_h)
        self.next_btn.rect = pygame.Rect(panel.right - 28 - (190 if compact else 220), btn_y,
                                         190 if compact else 220, btn_h)
        top, bottom = rule + (10 if compact else 16), btn_y - (10 if compact else 16)
        if self.page == 0:
            self._draw_roles(surface, panel, top, bottom, compact)
        elif self.page == 1:
            self._draw_hero(surface, panel, top, compact)
        else:
            self._draw_name(surface, panel, top, bottom, compact)

        self.back_btn.text = "← Назад" if self.page else "Отмена"
        self.next_btn.text = "Начать игру" if self.page == STEPS - 1 else "Далее →"
        self.next_btn.enabled = (bool(self.role_name) if self.page == 0
                                 else self.gender_id is not None if self.page == 1 else bool(self.hero_name))
        self.back_btn.draw(surface)
        self.next_btn.draw(surface)

    def _roles_layout(self, x, width, compact):
        cols = 3 if width >= 1000 else 2 if width >= 560 else 1
        card_w = (width - CARD_GAP * (cols - 1)) // cols
        ind_cols = 3 if card_w >= 330 else 2
        ind_rows = -(-len(role_stats.INDICATORS) // ind_cols)
        card_h = (46 if compact else 52) + ind_rows * 16 + 10
        items, y = [], 0
        for tier in range(len(role_stats.TIERS)):
            group = [r for r in self.sorted_roles if self.tiers[r["id"]] == tier]
            if not group:
                continue
            items.append(("head", y, tier, len(group)))
            y += HEAD_H
            for i, role in enumerate(group):
                rect = pygame.Rect(x + (i % cols) * (card_w + CARD_GAP), y + (i // cols) * (card_h + CARD_GAP),
                                   card_w, card_h)
                items.append(("card", rect, role))
            y += -(-len(group) // cols) * (card_h + CARD_GAP)
        return items, max(0, y - CARD_GAP), ind_cols

    def _draw_roles(self, surface, panel, top, bottom, compact):
        x, w = panel.x + 28, panel.w - 56
        size = 15 if compact else 17
        y = draw_paragraph(surface, f"Кем вы будете в государстве «{self.country_name}»? Роли идут от низов общества "
                           "к вершине: выберите готовую или опишите свою.", (x, top), w, size, theme.TEXT) + 6
        field_h = 38 if compact else 44
        custom_y = bottom - field_h
        self.grid_rect = pygame.Rect(x - 6, y, w + 12, custom_y - 12 - y)
        items, content_h, ind_cols = self._roles_layout(x, w, compact)
        self.max_scroll = max(0, content_h - self.grid_rect.h)
        self.scroll = min(self.scroll, self.max_scroll)
        prev = surface.get_clip()
        surface.set_clip(self.grid_rect.clip(prev))
        mouse = pygame.mouse.get_pos()
        self.card_rects = {}
        hovered = None
        for item in items:
            if item[0] == "head":
                _, ly, tier, count = item
                hy = self.grid_rect.y + ly - self.scroll
                if hy + HEAD_H < self.grid_rect.top or hy > self.grid_rect.bottom:
                    continue
                icon = draw_pyramid(surface, (x, hy + 4), tier)
                label = f"{role_stats.TIERS[tier].upper()}  ·  {count}"
                text = draw_text(surface, label, (icon.right + 10, hy + 12), 12, theme.ACCENT, bold=True,
                                 anchor="midleft")
                pygame.draw.line(surface, theme.PANEL_BORDER, (text.right + 12, hy + 12), (x + w, hy + 12))
                continue
            _, local, role = item
            rect = local.move(0, self.grid_rect.y - self.scroll)
            if rect.bottom < self.grid_rect.top or rect.top > self.grid_rect.bottom:
                continue
            self.card_rects[role["id"]] = rect
            is_hover = rect.collidepoint(mouse) and self.grid_rect.collidepoint(mouse)
            if is_hover:
                hovered = role
            selected = role["id"] == self.role_id
            draw_glass_card(surface, rect, ("role", role["id"]), hovered=is_hover, selected=selected)
            if selected:
                pygame.draw.rect(surface, theme.ACCENT, rect, 2, border_radius=theme.RADIUS)
            self._draw_role_card(surface, rect, role, ind_cols, compact)
        surface.set_clip(prev)
        if self.max_scroll:
            self._draw_scrollbar(surface, content_h)

        self.custom.rect = pygame.Rect(x, custom_y, w, field_h)
        self.custom.caret = self.custom_focused
        self.custom.draw(surface, CUSTOM_HINT)
        if hovered:
            start = hovered["start"]
            draw_tooltip(surface, [(hovered["name"], theme.TEXT, 16, True),
                                   (f"Ступень {self.tiers[hovered['id']] + 1} из {len(role_stats.TIERS)}: "
                                    f"{role_stats.TIERS[self.tiers[hovered['id']]]}", theme.ACCENT, 13, False),
                                   (f"Стресс {start['stress']}  ·  Внимание властей {start['heat']}",
                                    theme.TEXT_DIM, 13, False)], mouse)

    def _draw_role_card(self, surface, rect, role, ind_cols, compact):
        pad = 16
        tier = self.tiers[role["id"]]
        draw_pyramid(surface, (rect.right - pad - PYRAMID_W, rect.y + (9 if compact else 11)), tier)
        name_w = rect.w - 2 * pad - PYRAMID_W - 10
        draw_text(surface, ellipsize(role["name"], name_w, fonts.get(17, True)), (rect.x + pad, rect.y + (8 if compact else 10)),
                  17, theme.TEXT, bold=True)
        draw_text(surface, ellipsize(role["desc"], rect.w - 2 * pad, fonts.get(13)),
                  (rect.x + pad, rect.y + (30 if compact else 34)), 13, theme.TEXT_DIM)
        levels = role_stats.levels(role["start"])
        gap = 8
        cell_w = (rect.w - 2 * pad - gap * (ind_cols - 1)) // ind_cols
        base = rect.y + (50 if compact else 56)
        for i, (label, key) in enumerate(role_stats.INDICATORS):
            cx = rect.x + pad + (i % ind_cols) * (cell_w + gap)
            cy = base + (i // ind_cols) * 16
            draw_text(surface, label, (cx, cy), 11, theme.TEXT_DIM)
            draw_gauge(surface, pygame.Rect(cx + LABEL_W, cy + 5, cell_w - LABEL_W, 5), levels[key],
                       good_high=key != "risk")

    def _draw_scrollbar(self, surface, content_h):
        g = self.grid_rect
        track = pygame.Rect(g.right + 4, g.y + 4, 4, g.h - 8)
        pygame.draw.rect(surface, theme.PANEL_BORDER, track, border_radius=2)
        thumb_h = max(30, track.h * g.h // content_h)
        thumb_y = track.y + (track.h - thumb_h) * self.scroll // self.max_scroll
        pygame.draw.rect(surface, theme.ACCENT, (track.x, thumb_y, 4, thumb_h), border_radius=2)

    def _draw_hero(self, surface, panel, top, compact):
        x, w = panel.x + 28, panel.w - 56
        y = draw_paragraph(surface, f"Роль: {self.role_name}. Теперь о самом герое.", (x, top), w,
                           15 if compact else 17, theme.TEXT) + (6 if compact else 14)

        draw_text(surface, "ВОЗРАСТ", (x, y), 13, theme.ACCENT, bold=True)
        y += 24
        self.age.rect = pygame.Rect(x, y, 110, 48 if compact else 52)
        self.age.draw(surface)
        draw_text(surface, f"{self.age_cfg['min']}–{self.age_cfg['max']} лет", (x + 124, self.age.rect.centery), 14,
                  theme.TEXT_MUTED, anchor="midleft")
        step = 72
        presets_w = len(self.age_btns) * step - 8
        bx, by = x + 250, y + 6
        if bx + presets_w > x + w:
            bx, by = x, y + self.age.rect.h + 10
        for i, b in enumerate(self.age_btns):
            b.rect = pygame.Rect(bx + i * step, by, 64, 40)
            b.selected = str(self.age.value) == b.text
            b.draw(surface)
        y = max(self.age.rect.bottom, by + 40) + (18 if compact else 34)

        draw_text(surface, "ПОЛ", (x, y), 13, theme.ACCENT, bold=True)
        y += 24
        gw = (w - 2 * 14) // 3
        gh = 46 if compact else 56
        for i, g in enumerate(self.genders):
            b = self.gender_btns[g["id"]]
            b.rect = pygame.Rect(x + i * (gw + 14), y, gw, gh)
            b.selected = g["id"] == self.gender_id
            b.draw(surface)
        y += gh + (14 if compact else 24)
        draw_paragraph(surface, "Возраст и пол влияют на то, как к герою относятся люди и что для него доступно: "
                       "ECLIPSE Prime учтёт это в сценах. Следующий шаг - имя.", (x, y), w, 13 if compact else 14,
                       theme.TEXT_DIM)

    def _draw_name(self, surface, panel, top, bottom, compact):
        x, w = panel.x + 28, panel.w - 56
        y = draw_paragraph(surface, f"Роль: {self.role_name}. Как зовут героя? Варианты подобраны под страну, регион "
                           "и пол.", (x, top), w, 15 if compact else 17, theme.TEXT) + 4
        region = self.name_ctx.get("region")
        parts = [f"Имена: {self.app.names.describe(self.name_pool)}", f"пол: {(self.gender_name or '').lower()}"]
        if region:
            parts.append(region)
        draw_text(surface, ellipsize("  ·  ".join(parts), w, fonts.get(13)), (x, y), 13, theme.TEXT_DIM)
        y += 24

        field_h = 38 if compact else 44
        custom_y = bottom - field_h
        draw_text(surface, "ВАРИАНТЫ", (x, y + 10), 12, theme.ACCENT, bold=True, anchor="midleft")
        self.reroll_btn.rect = pygame.Rect(x + w - 190, y, 190, 32)
        self.reroll_btn.draw(surface)
        y += 40

        cols = 3 if w >= 780 else 2 if w >= 440 else 1
        card_w = (w - CARD_GAP * (cols - 1)) // cols
        labelled = any(s["culture"] for s in self.suggestions)
        card_h = 52 if labelled else 42
        rows = max(1, (custom_y - 12 - y + CARD_GAP) // (card_h + CARD_GAP))
        self.name_rects = []
        mouse = pygame.mouse.get_pos()
        for i, s in enumerate(self.suggestions[:cols * rows]):
            rect = pygame.Rect(x + (i % cols) * (card_w + CARD_GAP), y + (i // cols) * (card_h + CARD_GAP),
                               card_w, card_h)
            self.name_rects.append(rect)
            selected = i == self.name_idx and not self.custom_name.text.strip()
            draw_glass_card(surface, rect, ("name", i), hovered=rect.collidepoint(mouse), selected=selected)
            if selected:
                pygame.draw.rect(surface, theme.ACCENT, rect, 2, border_radius=theme.RADIUS)
            if s["culture"]:
                draw_text(surface, ellipsize(s["name"], card_w - 28, fonts.get(17, True)), (rect.x + 14, rect.y + 8), 17,
                          theme.TEXT, bold=True)
                draw_text(surface, s["culture"], (rect.x + 14, rect.y + 31), 12, theme.TEXT_DIM)
            else:
                draw_text(surface, ellipsize(s["name"], card_w - 28, fonts.get(17, True)),
                          (rect.x + 14, rect.centery), 17, theme.TEXT, bold=True, anchor="midleft")

        self.custom_name.rect = pygame.Rect(x, custom_y, w, field_h)
        self.custom_name.caret = self.name_focused
        self.custom_name.draw(surface, NAME_HINT)
