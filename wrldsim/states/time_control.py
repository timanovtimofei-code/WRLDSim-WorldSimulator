from datetime import timedelta

import pygame

from ..ui import theme
from ..ui import format as fmt
from ..ui.widgets import Button, NumberField, draw_glass_control, draw_panel, draw_spaced, draw_text
from .base import ModalState
from .confirm import ConfirmState

ROWS = [("Минуты", 999, 1), ("Часы", 999, 60), ("Дни", 999, fmt.MIN_DAY), ("Месяцы", 999, 30 * fmt.MIN_DAY),
        ("Годы", 6999, 365 * fmt.MIN_DAY), ("Века", 69, 36500 * fmt.MIN_DAY)]
# Год = века * 100 + годы; до н. э. век отрицательный: -5 и 69 дают 431 год до н. э.
VALUE_ROWS = [("Минуты", 0, 59, "0–59"), ("Часы", 0, 23, "0–23"), ("Дни", 1, 31, "1–31"), ("Месяцы", 1, 12, "1–12"),
              ("Годы", 0, 99, "0–99, год века"), ("Века", 0, 0, "")]
PRESETS = [("1 час", 1, 1), ("1 день", 2, 1), ("1 неделя", 2, 7), ("1 месяц", 3, 1), ("1 год", 4, 1)]
TABS = [("shift", "ПРИБАВЛЕНИЕ / УБАВЛЕНИЕ"), ("value", "ЗНАЧЕНИЕ")]
HOLD_DELAY = 0.4
HOLD_REPEAT = 0.06
ROW_H = 46
STEP_W = 40
TOP_H = 214


class TimeControlState(ModalState):
    def __init__(self, app, game, on_apply):
        super().__init__(app)
        self.game = game
        self.on_apply = on_apply
        self.tab = "shift"
        self.shift_fields = [NumberField(hi, lo=-hi) for _, hi, _ in ROWS]
        lo_c, hi_c = game.min_display_year // 100, game.max_display_year // 100
        self.value_rows = [*VALUE_ROWS[:-1], ("Века", lo_c, hi_c,
                                              f"{lo_c}…{hi_c}: -5 и 69 → 431 г. до н. э." if lo_c < 0
                                              else f"{lo_c}–{hi_c}: 20 → 20xx")]
        self.value_fields = [NumberField(hi, lo=lo) for _, lo, hi, _ in self.value_rows]
        self._fill_now()
        self.tab_btns = {tid: Button(label, lambda t=tid: self._set_tab(t), size=15, bold=True) for tid, label in TABS}
        self.reset_btn = Button("Сбросить", self._reset, size=16)
        self.cancel_btn = Button("Отмена", app.pop, size=17)
        self.apply_btn = Button("Применить", self._ask, size=18, bold=True)
        self.preset_btns = [Button(sign + label, lambda r=row, n=n * k: self._add(r, n), size=14)
                            for sign, k in (("+", 1), ("−", -1)) for label, row, n in PRESETS]
        self.steppers = []
        self.row_rects = []
        self.hold = None

    def enter(self):
        for f in self.fields:
            f.blur()
        self.hold = None

    @property
    def fields(self):
        return self.shift_fields if self.tab == "shift" else self.value_fields

    def _set_tab(self, tab):
        for f in self.fields:
            f.blur()
        self.tab = tab
        self.hold = None

    def _fill_now(self):
        mi, h, d, mo, year = self.game.display_parts(self.game.now)
        century, in_century = divmod(year, 100)
        for f, v in zip(self.value_fields, (mi, h, d, mo, in_century, century)):
            f.value = v

    def _target(self):
        mi, h, d, mo, y, c = (f.value for f in self.value_fields)
        year = min(max(c * 100 + y, self.game.min_display_year), self.game.max_display_year)
        return self.game.from_display(year, mo, d, h, mi)

    def _delta(self):
        if self.tab == "shift":
            total = sum(f.value * unit for f, (_, _, unit) in zip(self.shift_fields, ROWS))
        else:
            total = int((self._target() - self.game.now).total_seconds() // 60)
        if total > 0:
            return min(total, self.game.remaining_minutes)
        return -min(-total, self.game.rewind_minutes)

    def _reset(self):
        if self.tab == "shift":
            for f in self.shift_fields:
                f.value = 0
        else:
            self._fill_now()
        for f in self.fields:
            f.blur()

    def _add(self, row, n):
        self.tab = "shift"
        self.shift_fields[row].value = self.shift_fields[row].value + n

    def _focus(self, index):
        for i, f in enumerate(self.fields):
            if i == index:
                f.focus()
            elif f.focused:
                f.blur()

    def _ask(self):
        for f in self.fields:
            f.blur()
        delta = self._delta()
        if delta == 0:
            return
        minutes = abs(delta)
        target = self.game.at(self.game.s["minute"] + delta)
        if delta > 0:
            message = (f"Перемотать время вперёд на {fmt.span_ru(minutes)}?\n"
                       f"Новая дата: {self.game.date_text(target)}.\n"
                       "За это время пройдут доход и события. Отменить можно кнопкой «Откат».")
        else:
            message = (f"Отмотать время назад на {fmt.span_ru(minutes)}?\n"
                       f"Новая дата: {self.game.date_text(target)}.\n"
                       "Деньги и события не изменятся, сдвинется только дата. Отменить можно кнопкой «Откат».")
        self.app.push(ConfirmState(self.app, "ПОДТВЕРДИТЬ ИЗМЕНЕНИЯ?", message, lambda: self._commit(delta)))

    def _commit(self, signed_minutes):
        self.app.pop()
        self.on_apply(signed_minutes)

    def handle_event(self, event):
        shift = pygame.key.get_mods() & pygame.KMOD_SHIFT
        fields = self.fields
        focused = next((i for i, f in enumerate(fields) if f.focused), -1)
        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_ESCAPE:
                if focused >= 0:
                    fields[focused].blur()
                else:
                    self.app.pop()
                return
            if event.key == pygame.K_TAB:
                step = -1 if shift else 1
                self._focus((focused + step) % len(fields) if focused >= 0 else (0 if step > 0 else -1))
                return
            if event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                self._ask()
                return
        if event.type == pygame.MOUSEBUTTONUP and event.button == 1:
            self.hold = None
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            for rect, index, sign in self.steppers:
                if rect.collidepoint(event.pos):
                    step = sign * (10 if shift else 1)
                    fields[index].value = fields[index].value + step
                    self.hold = [index, step, HOLD_DELAY]
                    return
            hit = next((i for i, f in enumerate(fields) if f.rect.collidepoint(event.pos)), -1)
            if hit >= 0:
                if not fields[hit].focused:
                    self._focus(hit)
                return
            for f in fields:
                f.blur()
        if event.type == pygame.MOUSEWHEEL:
            pos = pygame.mouse.get_pos()
            for i, rect in enumerate(self.row_rects):
                if rect.collidepoint(pos):
                    big = 10 if shift else 1
                    fields[i].step(big if event.y > 0 else -big if event.y < 0 else 0)
                    return
        buttons = [self.reset_btn, self.cancel_btn, self.apply_btn, *self.tab_btns.values()]
        if self.tab == "shift":
            buttons += self.preset_btns
        for b in buttons:
            if b.handle_event(event):
                return
        if focused >= 0:
            fields[focused].handle_event(event)

    def animating(self):
        return self.hold is not None

    def update(self, dt):
        if self.hold is None:
            return
        if not pygame.mouse.get_pressed()[0]:
            self.hold = None
            return
        self.hold[2] -= dt
        while self.hold[2] <= 0:
            field = self.fields[self.hold[0]]
            field.value = field.value + self.hold[1]
            self.hold[2] += HOLD_REPEAT

    def _draw_stepper(self, surface, rect, sign, index):
        mouse = pygame.mouse.get_pos()
        hovered = rect.collidepoint(mouse)
        pressed = self.hold is not None and self.hold[0] == index and (self.hold[1] > 0) == (sign > 0) and hovered
        field = self.fields[index]
        enabled = field.value < field.hi if sign > 0 else field.value > field.lo
        draw_glass_control(surface, rect, 10, hover=1.0 if hovered else 0.0, press=1.0 if pressed else 0.0,
                           accent=0.5 if hovered and enabled else 0.0, enabled=enabled)
        cx, cy = rect.center
        color = theme.TEXT if enabled else theme.TEXT_MUTED
        pygame.draw.line(surface, color, (cx - 7, cy), (cx + 7, cy), 2)
        if sign > 0:
            pygame.draw.line(surface, color, (cx, cy - 7), (cx, cy + 7), 2)

    def draw(self, surface):
        w, h = surface.get_size()
        self.draw_backdrop(surface)
        compact = h < 660
        pw = min(660, w - 24)
        top_h, tail_h = (176, 118) if compact else (TOP_H, 140)
        row_h = max(30, min(ROW_H, (h - 16 - top_h - tail_h) // len(ROWS))) if compact else ROW_H
        ph = min(h - 16, top_h + len(ROWS) * row_h + tail_h)
        panel = pygame.Rect((w - pw) // 2, max(8 if compact else theme.TOPBAR_H + 8, (h - ph) // 2), pw, ph)
        draw_panel(surface, panel, alpha=248, border=theme.BUTTON_BORDER)
        draw_spaced(surface, "TIME CONTROL", (panel.centerx, panel.y + (26 if compact else 38)), 24, spacing=0.25)
        draw_text(surface, "Сейчас: " + self.game.date_text(), (panel.centerx, panel.y + (46 if compact else 62)), 14,
                  theme.TEXT_DIM, anchor="center")

        x, gap = panel.x + 36, 8
        tab_w = (pw - 72 - gap) // 2
        tabs_y, tab_h = (62, 34) if compact else (82, 40)
        for i, (tid, _) in enumerate(TABS):
            b = self.tab_btns[tid]
            b.rect = pygame.Rect(x + i * (tab_w + gap), panel.y + tabs_y, tab_w, tab_h)
            b.selected = self.tab == tid
            b.draw(surface)

        if self.tab == "shift":
            n = len(PRESETS)
            chip_w = (pw - 72 - gap * (n - 1)) // n
            chip_h, chip_step, chips_y = (30, 34, 104) if compact else (32, 38, 134)
            for i, b in enumerate(self.preset_btns):
                b.rect = pygame.Rect(x + (i % n) * (chip_w + gap), panel.y + chips_y + (i // n) * chip_step, chip_w,
                                     chip_h)
                b.draw(surface)
        else:
            draw_text(surface, "Введите нужную дату и время в окошки и нажмите «Применить».",
                      (x, panel.y + (110 if compact else 146)), 15, theme.TEXT_DIM)
            draw_text(surface, "Год = века × 100 + годы: века 20 и годы 26 → 2026.",
                      (x, panel.y + (134 if compact else 172)), 13, theme.TEXT_MUTED)
            for b in self.preset_btns:
                b.rect = pygame.Rect(0, 0, 0, 0)

        y = panel.y + top_h
        self.steppers, self.row_rects = [], []
        if self.tab == "shift":
            rows = [(label, f"−{hi}…+{hi}") for label, hi, _ in ROWS]
        else:
            rows = [(label, hint) for label, _, _, hint in self.value_rows]
        for i, (field, (label, hint)) in enumerate(zip(self.fields, rows)):
            self.row_rects.append(pygame.Rect(panel.x + 24, y, pw - 48, row_h))
            changed = field.value != 0 or self.tab == "value"
            draw_text(surface, label, (panel.x + 36, y + row_h // 2), 16,
                      theme.TEXT if changed or field.focused else theme.TEXT_DIM, anchor="midleft")
            minus = pygame.Rect(panel.x + 140, y + 6, STEP_W, row_h - 12)
            field.rect = pygame.Rect(minus.right + 6, y + 6, 120, row_h - 12)
            plus = pygame.Rect(field.rect.right + 6, y + 6, STEP_W, row_h - 12)
            self.steppers += [(minus, i, -1), (plus, i, +1)]
            self._draw_stepper(surface, minus, -1, i)
            field.draw(surface)
            self._draw_stepper(surface, plus, +1, i)
            draw_text(surface, hint, (plus.right + 10, y + row_h // 2), 13, theme.TEXT_MUTED, anchor="midleft")
            y += row_h
        fields_bottom = y

        pygame.draw.line(surface, theme.PANEL_BORDER, (panel.x + 36, fields_bottom + 6),
                         (panel.right - 36, fields_bottom + 6))
        delta = self._delta()
        if delta:
            word = "Вперёд на " if delta > 0 else "Назад на "
            draw_text(surface, word + fmt.span_ru(abs(delta)), (panel.x + 36, fields_bottom + 16), 16,
                      theme.ACCENT if delta > 0 else theme.TEXT)
            draw_text(surface, "Новая дата: " + self.game.date_text(self.game.now + timedelta(minutes=delta)),
                      (panel.x + 36, fields_bottom + 42), 14, theme.TEXT_DIM)
        else:
            tip = ("Плюс - вперёд, минус - назад. Знак в окошке: клавиша «-»" if self.tab == "shift"
                   else "Дата совпадает с текущей")
            draw_text(surface, tip, (panel.x + 36, fields_bottom + 16), 15, theme.TEXT_MUTED)
            draw_text(surface, "Tab: следующее окошко  ·  ↑↓ и колесо: ±1, с Shift ±10  ·  Enter: применить",
                      (panel.x + 36, fields_bottom + 42), 13, theme.TEXT_MUTED)

        btn_h = 36 if compact else 40
        by = panel.bottom - btn_h - (14 if compact else 18)
        self.cancel_btn.rect = pygame.Rect(panel.x + 36, by, 120 if compact else 140, btn_h)
        self.reset_btn.rect = pygame.Rect(panel.x + 168 if compact else panel.x + 188, by, 120 if compact else 140,
                                          btn_h)
        self.apply_btn.rect = pygame.Rect(panel.right - 36 - 180 if compact else panel.right - 36 - 200, by,
                                          180 if compact else 200, btn_h)
        self.apply_btn.enabled = delta != 0
        self.cancel_btn.draw(surface)
        self.reset_btn.draw(surface)
        self.apply_btn.draw(surface)
