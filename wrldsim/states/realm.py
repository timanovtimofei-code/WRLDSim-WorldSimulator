# Окно рисуется заново каждый кадр и запоминает кликабельные места (hits); клики идут по ним.

import numpy as np
import pygame

from ..history.flags import draw_polity_flag
from ..ui import fonts, theme
from ..ui import format as fmt
from ..ui.widgets import (Glow, TextInput, draw_glass_control, draw_panel, draw_text, draw_tooltip, ellipsize, fill_round,
                          radius_for, sweep_of, text_on, text_surface, wrap)
from .base import ModalState

TABS = [("overview", "Обзор"), ("land", "Территории"), ("cities", "Города"), ("budget", "Бюджет"),
        ("army", "Армия"), ("diplomacy", "Дипломатия"), ("decrees", "Указы"), ("chronicle", "Хроника")]
BUDGET_LABELS = {"army": ("Армия и флот", "Содержание войск: больше солдат и сильнее оборона."),
                 "admin": ("Управление", "Чиновники и сборщики: налоги собираются полнее, порядок крепче."),
                 "infra": ("Дороги и строительство", "Развитие областей, торговля, рост городов."),
                 "science": ("Наука и школы", "Технологии, а с ними и качество армии, и выпуск."),
                 "court": ("Двор, церковь, раздачи", "Доверие к власти и спокойствие народа.")}
ROW = 30
PAD = 18


def _num(x):
    return fmt.people(max(float(x), 0.0))


def _money(x):
    return ("−" if x < 0 else "") + fmt.usd(abs(x))


class RealmState(ModalState):
    def __init__(self, app, game, parent):
        super().__init__(app)
        self.game, self.parent = game, parent
        self.tab = "overview"
        self.hits = []
        self._glows = {}
        self.scrollers = []
        self.scroll = {t: 0 for t, _ in TABS}
        self.max_scroll = {t: 0 for t, _ in TABS}
        self.edit = None
        self.num_input = TextInput(size=17, max_len=6)
        self.fields = []
        self._fiscal_before = None
        self._fiscal_idle = 0.0
        self.pressed = None
        self.msg = None
        self.tip = None
        self.sel_atom = None
        self.sel_city = None
        self.sel_polity = None
        self.sort = ("pop", True)
        self.dialog = None
        self.target_idx = 0
        self.chron_all = False
        self.name_input = TextInput(size=18, max_len=28)
        self._mini = None
        self._rows_cache = None

    @property
    def w(self):
        # Мир берём у игры каждый раз: перемотка назад подменяет его новым объектом.
        return self.game.world

    @property
    def p(self):
        return self.w.player

    def _say(self, text, ok=True):
        self.msg = (text, ok, 4.0)

    def _do(self, fn, *args, **kw):
        self._fiscal_done()
        self.parent.realm_action()
        ok, text = fn(*args, **kw)
        self._say(text, ok)
        if ok:
            self.game.sync_world_stats()
            self.game.log(f"Управление: {text}", "plus")
            self.parent.eclipse.add_note(f"Правитель распорядился в панели управления государством: {text}")
        else:
            self.parent._drop_undo(self.parent.undo_stack[-1] if self.parent.undo_stack else None)
        return ok

    def _close(self):
        if self.edit:
            self._commit_edit()
        self._fiscal_done()
        self.app.pop()

    def _advance(self, months):
        self._fiscal_done()
        self.parent._apply_time(int(months * 30.4375 * 1440))

    def btn(self, surface, rect, text, cb, *, enabled=True, accent=False, size=14, tip=None, selected=False):
        hover = enabled and rect.collidepoint(pygame.mouse.get_pos())
        glow = self._glows.get((tuple(rect), text))
        if glow is None:
            if len(self._glows) > 300:
                self._glows.clear()
            glow = self._glows[(tuple(rect), text)] = Glow()
        pressed = hover and self.pressed == tuple(rect)
        h, p, a = glow.step(1.0 if hover else 0.0, 1.0 if pressed else 0.0, 1.0 if selected else 0.0)
        draw_glass_control(surface, rect, theme.RADIUS_SM, hover=h, press=p, accent=a, enabled=enabled)
        if accent and enabled and not selected:
            pygame.draw.rect(surface, theme.ACCENT, rect, 1, border_radius=radius_for(theme.RADIUS_SM))
        color = text_on(sweep_of(h, a)) if enabled else theme.TEXT_MUTED
        img = text_surface(ellipsize(text, rect.w - 14, fonts.get(size)), size, color, accent)
        surface.blit(img, img.get_rect(center=rect.center))
        if enabled:
            self.hits.append((rect, cb, tip))
        elif tip and rect.collidepoint(pygame.mouse.get_pos()):
            self.tip = tip
        if tip and hover:
            self.tip = tip

    def bar(self, surface, rect, frac, color, back=None):
        fill_round(surface, rect, back or theme.mix(theme.GLASS_COLOR, theme.TEXT, 0.08), 255, rect.h // 2)
        w = int(rect.w * min(max(frac, 0.0), 1.0))
        if w > 2:
            fill_round(surface, pygame.Rect(rect.x, rect.y, w, rect.h), color, 255, rect.h // 2)

    def num_field(self, surface, rect, key, value):
        self.fields.append(key)
        if self.edit == key:
            self.num_input.rect = rect
            self.num_input.caret = True
            self.num_input.draw(surface)
            self.hits.append((rect, lambda: None, None))
            return
        hover = rect.collidepoint(pygame.mouse.get_pos())
        fill_round(surface, rect, theme.mix(theme.GLASS_COLOR, theme.TEXT, 0.12 if hover else 0.06), 235, 10)
        pygame.draw.rect(surface, theme.ACCENT if hover else theme.PANEL_BORDER, rect, 1, border_radius=10)
        draw_text(surface, str(value), (rect.right - 12, rect.centery), 17, theme.TEXT, bold=True, anchor="midright")
        self.hits.append((rect, lambda: self._start_edit(key), "Нажмите и введите число"))

    def _start_edit(self, key):
        if self.edit and self.edit != key:
            self._commit_edit()
        self.edit = key
        self.num_input.text = str(self._fiscal()[key])
        pygame.key.start_text_input()

    def _cancel_edit(self):
        self.edit = None
        self.num_input.text = ""

    def _commit_edit(self):
        key, text = self.edit, self.num_input.text.strip().replace(",", ".").rstrip("%").strip()
        self._cancel_edit()
        if key is None or text == "" or text == str(self._fiscal()[key]):
            return
        try:
            value = float(text)
        except ValueError:
            self._say(f"«{text}» - не число. Введите проценты, например 25.", False)
            return
        self._set_fiscal(key, value)

    def _set_fiscal(self, key, percent):
        w, p = self.w, self.p
        lo, hi = self._limits(key)
        why = f"Допустимо от {lo:g} до {hi:g}%"
        if key != "tax":
            # Сумма статей не больше 100%: иначе модель урезала бы все статьи разом и введённое число бы «уплыло».
            free = round(100 - sum(float(w.budget[k][p]) * 100 for k in BUDGET_LABELS if k != key), 2)
            if free < hi:
                hi, why = max(free, 0), f"Свободно {max(free, 0):g}% дохода (сумма статей не больше 100%)"
        value = min(max(percent, lo), hi)
        if self._fiscal_before is None:
            self._fiscal_before = (self._fiscal(), self.parent._push_undo())
        if key == "tax":
            w.set_tax(p, value / 100)
        else:
            w.set_budget(p, **{key: value / 100})
        self._fiscal_idle = 0.0
        self.game.sync_world_stats()
        if value != percent:
            self._say(f"{why}: поставлено {value:g}%.", False)

    def _limits(self, key):
        return (2, round(self.w.ec["tax_max"] * 100)) if key == "tax" else (0, 60)

    def _step(self, key, delta):
        if self.edit:
            self._commit_edit()
        self._set_fiscal(key, self._fiscal()[key] + delta)

    def card(self, surface, rect, title=None):
        fill_round(surface, rect, theme.mix(theme.GLASS_COLOR, theme.TEXT, 0.05), 205, 14)
        if title:
            draw_text(surface, title.upper(), (rect.x + 14, rect.y + 10), 11, theme.ACCENT, bold=True)

    def metric(self, surface, rect, label, value, sub="", color=None, bar=None, bar_color=None):
        self.card(surface, rect)
        draw_text(surface, label, (rect.x + 14, rect.y + 10), 12, theme.TEXT_DIM)
        draw_text(surface, ellipsize(value, rect.w - 28, fonts.get(21, True)), (rect.x + 14, rect.y + 28), 21,
                  color or theme.TEXT, bold=True)
        if bar is not None:
            self.bar(surface, pygame.Rect(rect.x + 14, rect.bottom - 18, rect.w - 28, 6), bar, bar_color or theme.ACCENT)
        elif sub:
            draw_text(surface, ellipsize(sub, rect.w - 28, fonts.get(12)), (rect.x + 14, rect.y + 58), 12, theme.TEXT_MUTED)

    def paragraph(self, surface, text, x, y, width, size=14, color=None, gap=2):
        for line in wrap(text, width, size):
            draw_text(surface, line, (x, y), size, color or theme.TEXT_DIM)
            y += fonts.get(size).get_linesize() + gap
        return y

    def scroll_area(self, tab, rect):
        self.scrollers.append((rect, tab))

    def handle_event(self, event):
        if self.dialog:
            self._dialog_event(event)
            return
        if self.edit and self._edit_event(event):
            return
        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_ESCAPE:
                self._close()
                return
            if pygame.K_1 <= event.key <= pygame.K_8:
                self._set_tab(TABS[event.key - pygame.K_1][0])
                return
        if event.type == pygame.MOUSEWHEEL:
            pos = pygame.mouse.get_pos()
            for rect, tab in reversed(self.scrollers):
                if rect.collidepoint(pos) and self.max_scroll.get(tab, 0):
                    self.scroll[tab] = min(max(self.scroll[tab] - event.y * 48, 0), self.max_scroll[tab])
                    return
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            # Запоминаем место нажатия, а не обработчик: между нажатием и отпусканием hits пересоздаются с новыми лямбдами.
            self.pressed = next((tuple(rect) for rect, _, _ in reversed(self.hits) if rect.collidepoint(event.pos)), None)
        elif event.type == pygame.MOUSEBUTTONUP and event.button == 1:
            hit = next(((tuple(rect), cb) for rect, cb, _ in reversed(self.hits) if rect.collidepoint(event.pos)), None)
            pressed, self.pressed = self.pressed, None
            if hit is not None and hit[0] == pressed:
                hit[1]()

    def _fiscal(self):
        w, p = self.w, self.p
        return {"tax": round(float(w.tax[p]) * 100), **{k: round(float(w.budget[k][p]) * 100) for k in BUDGET_LABELS}}

    def _fiscal_done(self):
        if self._fiscal_before is None:
            return
        (before, snap), self._fiscal_before = self._fiscal_before, None
        after = self._fiscal()
        changes = [f"{'налог' if k == 'tax' else BUDGET_LABELS[k][0].lower()} {before[k]}% → {after[k]}%"
                   for k in after if after[k] != before[k]]
        if not changes:
            self.parent._drop_undo(snap)
            return
        text = "Бюджет: " + ", ".join(changes) + "."
        self.refresh_backdrop()
        self.game.log(f"Управление: {text}", "plus")
        self.parent.eclipse.add_note(f"Правитель распорядился в панели управления государством: {text}")
        self._say(text)

    def _edit_event(self, event):
        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_ESCAPE:
                self._cancel_edit()
            elif event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                self._commit_edit()
            elif event.key == pygame.K_TAB:
                key = self.edit
                self._commit_edit()
                order = self.fields or [key]
                step = -1 if event.mod & pygame.KMOD_SHIFT else 1
                self._start_edit(order[(order.index(key) + step) % len(order)] if key in order else order[0])
            else:
                self.num_input.handle_event(event)
            return True
        if event.type == pygame.TEXTINPUT:
            text = "".join(ch for ch in event.text if ch.isdigit() or ch in ".,")
            if text:
                self.num_input.handle_event(pygame.event.Event(pygame.TEXTINPUT, text=text))
            return True
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1 and not self.num_input.rect.collidepoint(event.pos):
            self._commit_edit()
        return False

    def _dialog_event(self, event):
        if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
            self.dialog = None
            return
        if event.type == pygame.KEYDOWN and event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
            self._confirm_dialog()
            return
        if self.name_input.handle_event(event):
            return
        if event.type == pygame.MOUSEBUTTONUP and event.button == 1:
            hit = next((cb for rect, cb, _ in reversed(self.hits) if rect.collidepoint(event.pos)), None)
            if hit:
                hit()

    def _confirm_dialog(self):
        d, self.dialog = self.dialog, None
        if d["kind"] == "city":
            self._do(self.w.found_city, self.p, d["atom"], self.name_input.text)

    def update(self, dt):
        self.name_input.update(dt)
        self.num_input.update(dt)
        if self._fiscal_before is not None and not self.edit:
            self._fiscal_idle += dt
            if self._fiscal_idle >= 1.5:
                self._fiscal_done()
        if self.msg:
            self.msg = (self.msg[0], self.msg[1], self.msg[2] - dt) if self.msg[2] > dt else None

    def draw(self, surface):
        self.draw_backdrop(surface)
        w = self.w
        size = surface.get_size()
        self.hits, self.scrollers, self.fields, self.tip = [], [], [], None
        rect = pygame.Rect(18, 14, size[0] - 36, size[1] - 28)
        draw_panel(surface, rect, alpha=244, radius=22)
        head = pygame.Rect(rect.x, rect.y, rect.w, 78)
        self._draw_head(surface, head)
        rail = pygame.Rect(rect.x + 12, head.bottom, 176, rect.bottom - head.bottom - 12)
        self._draw_rail(surface, rail)
        body = pygame.Rect(rail.right + 12, head.bottom, rect.right - rail.right - 24, rect.bottom - head.bottom - 14)
        prev = surface.get_clip()
        surface.set_clip(body.clip(prev))
        if len(w.group_atoms(self.p)):
            getattr(self, "_tab_" + self.tab)(surface, body)
        else:
            draw_text(surface, "Государство перестало существовать: все земли перешли к другим.",
                      (body.centerx, body.y + 120), 22, theme.WARN, bold=True, anchor="center")
            draw_text(surface, "Управлять нечем. Остальной мир идёт своим ходом: пропустите время или начните новую игру.",
                      (body.centerx, body.y + 160), 15, theme.TEXT_DIM, anchor="center")
        surface.set_clip(prev)
        if self.msg:
            text, ok, _ = self.msg
            img = text_surface(ellipsize(text, rect.w - 120, fonts.get(16, True)), 16, theme.GOOD if ok else theme.WARN, True)
            box = img.get_rect(midbottom=(rect.centerx, rect.bottom - 18)).inflate(30, 16)
            fill_round(surface, box, (14, 14, 17), 245, 12)
            pygame.draw.rect(surface, theme.GOOD if ok else theme.WARN, box, 1, border_radius=12)
            surface.blit(img, img.get_rect(center=box.center))
        if self.dialog:
            self._draw_dialog(surface, rect)
        if self.tip and not self.dialog:
            draw_tooltip(surface, [(line, theme.TEXT_DIM, 13, False) for line in wrap(self.tip, 320, 13)],
                         pygame.mouse.get_pos())

    def _draw_head(self, surface, head):
        w, p = self.w, self.p
        pol = w.polity(p)
        year = w.date_year()
        draw_polity_flag(surface, self.app, pol, year, pygame.Rect(head.x + 24, head.y + 14, 72, 48))
        m = w.monthly(p)
        x = head.right - 24
        close = pygame.Rect(x - 120, head.y + 18, 120, 40)
        self.btn(surface, close, "Закрыть  Esc", self._close, size=15)
        x = close.x - 14
        for text, cb in (("+1 год", lambda: self._advance(12)), ("+1 мес.", lambda: self._advance(1))):
            r = pygame.Rect(x - 84, head.y + 18, 84, 40)
            self.btn(surface, r, text, cb, size=14, tip="Пропустить время: мир живёт, казна и события идут.")
            x = r.x - 8
        x -= 10
        tx = head.x + 112
        title_w = min(fonts.get(26, True).size(w.title(p))[0], max(x - tx - 16, 80))
        imgs = [text_surface(label, 17, color, True) for label, color in
                ((f"{_money(m['net'])}/мес", theme.GOOD if m["net"] >= 0 else theme.DANGER),
                 (f"казна {_money(w.treasury[p])}", theme.TEXT))]
        need = sum(img.get_width() for img in imgs) + 24 * len(imgs)
        if x - need >= tx + title_w + 16:
            for img in imgs:
                surface.blit(img, img.get_rect(midright=(x, head.y + 38)))
                x -= img.get_width() + 24
            right = x
        else:
            line = f"казна {_money(w.treasury[p])}  ·  {_money(m['net'])}/мес"
            draw_text(surface, line, (head.right - 24, head.y + 61), 13, theme.GOOD if m["net"] >= 0 else theme.DANGER,
                      bold=True, anchor="topright")
            right = x
        draw_text(surface, ellipsize(w.title(p), right - tx - 16, fonts.get(26, True)), (tx, head.y + 12), 26,
                  theme.TEXT, bold=True)
        gov = w.cfg["governments"][w.gov_list[w.gov[p]]]["name"]
        role = (self.game.s.get("hero") or {}).get("role", "")
        draw_text(surface, ellipsize(f"{gov}  ·  {role}  ·  {self.game.date_text()}", right - tx - 16, fonts.get(14)),
                  (tx + 1, head.y + 46), 14, theme.TEXT_DIM)

    def _draw_rail(self, surface, rail):
        y = rail.y + 6
        step = min(46, max(30, (rail.h - 52) // len(TABS)))
        for i, (key, name) in enumerate(TABS):
            r = pygame.Rect(rail.x, y, rail.w, step - 6)
            self.btn(surface, r, f"{i + 1}  {name}", lambda k=key: self._set_tab(k), size=15 if step >= 40 else 14,
                     selected=self.tab == key, accent=False)
            y += step
        w, p = self.w, self.p
        mode = "Мягкая" if w.history_mode == "soft" else "Свободная"
        self.btn(surface, pygame.Rect(rail.x, rail.bottom - 40, rail.w, 34), f"История: {mode}", self._toggle_history,
                 size=13, tip=w.cfg["history_modes"][w.history_mode])
        if y + 110 > rail.bottom - 44:
            return
        y += 8
        pygame.draw.line(surface, theme.PANEL_BORDER, (rail.x + 6, y), (rail.right - 6, y))
        y += 10
        for label, value in (("Строй", w.cfg["governments"][w.gov_list[w.gov[p]]]["name"]),
                             ("История", w.cfg["history_modes"].get(w.history_mode, "").split(":")[0])):
            draw_text(surface, label.upper(), (rail.x + 8, y), 10, theme.TEXT_MUTED, bold=True)
            for line in wrap(value, rail.w - 16, 12)[:2]:
                y += 14
                draw_text(surface, line, (rail.x + 8, y), 12, theme.TEXT_DIM)
            y += 22

    def _set_tab(self, key):
        if self.edit:
            self._commit_edit()
        self.tab = key

    def _toggle_history(self):
        w = self.w
        w.history_mode = "free" if w.history_mode == "soft" else "soft"
        if w.history_mode == "free":
            w.drift = [e for e in w.drift if e["state"] != 0]
        else:
            w._build_drift(max([i for i, y in enumerate(w.hist.years) if y <= w.date_year()], default=0),
                           w.date_year(), w.month)
        self._say("Мягкая история: события прошлого снова давят на мир." if w.history_mode == "soft"
                  else "Свободная история: границы меняются только по ходу игры.")

    def _draw_dialog(self, surface, rect):
        shade = pygame.Surface(surface.get_size(), pygame.SRCALPHA)
        shade.fill((0, 0, 0, 150))
        surface.blit(shade, (0, 0))
        box = pygame.Rect(0, 0, 460, 200)
        box.center = rect.center
        draw_panel(surface, box, alpha=250, radius=20)
        draw_text(surface, "НАЗВАНИЕ НОВОГО ГОРОДА", (box.x + 24, box.y + 22), 13, theme.ACCENT, bold=True)
        self.name_input.rect = pygame.Rect(box.x + 24, box.y + 54, box.w - 48, 46)
        self.name_input.draw(surface, placeholder="Например: Новоград")
        self.btn(surface, pygame.Rect(box.x + 24, box.bottom - 62, 200, 42), "Основать", self._confirm_dialog, accent=True,
                 size=16)
        self.btn(surface, pygame.Rect(box.right - 224, box.bottom - 62, 200, 42), "Отмена",
                 lambda: setattr(self, "dialog", None), size=16)

    def _tab_overview(self, surface, body):
        w, p = self.w, self.p
        grp = w.in_group(p)
        atoms = w.group_atoms(p)
        pop = float(w.pop[atoms].sum())
        area = float(w.km2[atoms].sum()) / 1000
        m = w.monthly(p)
        cities = [c for c in w.cities if not c.get("pending") and grp[w.owner[c["atom"]]]]
        gs = w._group_strengths()
        cols = 4 if body.w >= 900 else 3
        cw = (body.w - 12 * (cols - 1)) // cols
        ch = 86
        cards = [
            ("Население", _num(pop), f"рост {w.ec['growth'] * 100:.1f}% в год", None, None, None),
            ("Площадь", f"{fmt.number(area, 0)} тыс. км²", f"областей: {len(atoms)}, городов: {len(cities)}", None, None, None),
            ("Казна", _money(w.treasury[p]), f"долг {_money(w.debt[p])}", None, None, None),
            ("Доход в месяц", _money(m["rev"]), f"налог {round(w.tax[p] * 100)}%", theme.GOOD, None, None),
            ("Расходы в месяц", _money(m["spend"]), f"из них проценты {_money(m['interest'])}", None, None, None),
            ("Баланс в месяц", _money(m["net"]), "", theme.GOOD if m["net"] >= 0 else theme.DANGER, None, None),
            ("Стабильность", f"{round(w.stab[p])}", "", None, w.stab[p] / 100, self._grade(w.stab[p])),
            ("Легитимность", f"{round(w.legit[p])}", "", None, w.legit[p] / 100, self._grade(w.legit[p])),
            ("Армия", f"{_num(w.army[grp].sum())} чел.", f"мощь {_num(gs[p])}, дух {round(w.morale[p] * 100)}%", None, None, None),
            ("Технологии", f"{round(w.tech[p])}", "", None, w.tech[p] / 100, theme.ACCENT),
            ("Развитие земель", f"{round(float(np.average(w.dev[atoms], weights=np.maximum(w.pop[atoms], 1))))}", "", None,
             float(np.average(w.dev[atoms], weights=np.maximum(w.pop[atoms], 1))) / 100, theme.GOOD),
            ("Недовольство", f"{round(float(np.average(w.unrest[atoms], weights=np.maximum(w.pop[atoms], 1))))}", "", None,
             float(np.average(w.unrest[atoms], weights=np.maximum(w.pop[atoms], 1))) / 100, self._grade(100 - float(
                 np.average(w.unrest[atoms], weights=np.maximum(w.pop[atoms], 1))))),
        ]
        grid_h = ((len(cards) + cols - 1) // cols) * (ch + 10) + 4
        low_h = max(body.h - grid_h - 8, 240)
        self.scroll_area("overview", body)
        self.max_scroll["overview"] = max(0, grid_h + low_h + 8 - body.h)
        self.scroll["overview"] = min(self.scroll["overview"], self.max_scroll["overview"])
        y = body.y - self.scroll["overview"]
        for i, (label, value, sub, color, bar, bcolor) in enumerate(cards):
            r = pygame.Rect(body.x + (i % cols) * (cw + 12), y + (i // cols) * (ch + 10), cw, ch)
            self.metric(surface, r, label, value, sub, color, bar, bcolor)
        y += grid_h
        left = pygame.Rect(body.x, y, int(body.w * 0.52) - 6, low_h)
        right = pygame.Rect(left.right + 12, y, body.right - left.right - 12, left.h)
        self.card(surface, left, "Государство на карте")
        self._minimap(surface, pygame.Rect(left.x + 8, left.y + 32, left.w - 16, left.h - 40))
        self.card(surface, right, "Что требует внимания")
        yy = right.y + 34
        notes = self._attention()
        if not notes:
            draw_text(surface, "Всё спокойно.", (right.x + 14, yy), 15, theme.TEXT_DIM)
        for color, text in notes[:9]:
            pygame.draw.circle(surface, color, (right.x + 20, yy + 9), 4)
            for k, line in enumerate(wrap(text, right.w - 50, 14)[:2]):
                draw_text(surface, line, (right.x + 34, yy + k * 17), 14, theme.TEXT)
            yy += 17 * min(2, len(wrap(text, right.w - 50, 14))) + 8

    @staticmethod
    def _grade(v):
        return theme.GOOD if v >= 60 else theme.WARN if v >= 35 else theme.DANGER

    def _attention(self):
        w, p = self.w, self.p
        grp = w.in_group(p)
        out = []
        for war in w.wars:
            if grp[war["att"]] or grp[war["dfn"]]:
                ours = 1 if grp[war["att"]] else -1
                foe = war["dfn"] if ours > 0 else war["att"]
                s = round(war["score"] * ours)
                out.append((theme.DANGER, f"Война с {w.title(foe)}: счёт {s:+d}, {w.month - war['since']} мес."))
        if w.debt[p] > w.annual_revenue(p) * 0.8:
            out.append((theme.WARN, f"Долг велик: {_money(w.debt[p])}. Кредиторы теряют терпение."))
        if w.monthly(p)["net"] < 0:
            out.append((theme.WARN, "Расходы превышают доходы: казна тает."))
        if w.stab[p] < 35:
            out.append((theme.DANGER, f"Стабильность низка ({round(w.stab[p])}): возможны мятежи."))
        hot = [a for a in w.group_atoms(p) if w.unrest[a] >= 70]
        if hot:
            names = ", ".join(w.region_name(a) for a in hot[:3])
            out.append((theme.WARN, f"Волнения в областях ({len(hot)}): {names}."))
        claims = w.claims(p)
        for ev, n in claims[:2]:
            out.append((theme.ACCENT, f"Исторические притязания к {w.title(ev['frm'])}: {n} обл."))
        for e in w.log[-30:][::-1]:
            if w.relevant(e) and e[2] in ("territory", "peace", "revolt", "history"):
                out.append((theme.TEXT_DIM, f"{w.date_year(e[0])} г.: {e[1]}"))
                break
        return out

    def _minimap(self, surface, rect):
        w, p = self.w, self.p
        key = (w.version, rect.size, p)
        if self._mini is None or self._mini[0] != key:
            img = pygame.Surface(rect.size)
            img.fill(theme.mix(theme.OCEAN, theme.GLASS_COLOR, 0.35))
            h = w.hist
            atoms = w.own_atoms(p)
            if not len(atoms):
                atoms = w.group_atoms(p)
            pts = h.anchors[atoms].astype(float)
            weights = np.maximum(w.km2[atoms], 1.0)
            ox, oy = np.argsort(pts[:, 0]), np.argsort(pts[:, 1])
            cx, cy = np.cumsum(weights[ox]) / weights.sum(), np.cumsum(weights[oy]) / weights.sum()
            x0, x1 = pts[ox[np.searchsorted(cx, 0.02)], 0] - 8, pts[ox[min(np.searchsorted(cx, 0.98), len(atoms) - 1)], 0] + 8
            y0, y1 = pts[oy[np.searchsorted(cy, 0.02)], 1] - 6, pts[oy[min(np.searchsorted(cy, 0.98), len(atoms) - 1)], 1] + 6
            k = min(rect.w / (x1 - x0), rect.h / (y1 - y0))
            ox0 = (rect.w - (x1 - x0) * k) / 2 - x0 * k
            oy0 = (rect.h - (y1 - y0) * k) / 2 - y0 * k
            b = h.bbox
            vis = np.nonzero((b[:, 2] >= x0) & (b[:, 0] <= x1) & (b[:, 3] >= y0) & (b[:, 1] <= y1))[0]
            grp = w.in_group(p)
            tri = h.tri_xy.reshape(-1, 3, 2)
            pal = w.palette()
            for a in vis.tolist():
                mine = bool(grp[w.owner[a]])
                col = [int(c) for c in pal[w.owner[a]]] if w.owner[a] else [60, 62, 68]
                col = col if mine else [int(c * 0.45 + 22) for c in col]
                for t in tri[h._tri_off[a]:h._tri_off[a + 1]]:
                    pygame.draw.polygon(img, col, [(float(px) * k + ox0, float(py) * k + oy0) for px, py in t])
            self._mini = (key, img)
        surface.blit(self._mini[1], rect)

    # ---------------- Территории ----------------
    def _tab_land(self, surface, body):
        w, p = self.w, self.p
        atoms = w.group_atoms(p)
        key, desc = self.sort
        out = w.pop[atoms] * w.gpc[atoms] * (0.55 + 0.009 * w.dev[atoms]) * w.tax[p] / 12
        cols = {"name": np.array([w.region_name(a) for a in atoms]), "pop": w.pop[atoms], "dev": w.dev[atoms],
                "unrest": w.unrest[atoms], "rev": out}
        order = np.argsort(cols[key], kind="stable")
        if desc and key != "name":
            order = order[::-1]
        elif key == "name" and desc:
            order = order[::-1]
        atoms, out = atoms[order], out[order]
        left = pygame.Rect(body.x, body.y, int(body.w * 0.58), body.h - 8)
        right = pygame.Rect(left.right + 12, body.y, body.right - left.right - 12, left.h)
        self.card(surface, left)
        heads = (("name", "Область", 0.40), ("pop", "Население", 0.18), ("dev", "Разв.", 0.12), ("unrest", "Недов.", 0.13),
                 ("rev", "Налог/мес", 0.17))
        x = left.x + 14
        for k, title, share in heads:
            wd = int((left.w - 28) * share)
            arrow = (" ▼" if desc else " ▲") if k == key else ""
            r = pygame.Rect(x - 4, left.y + 6, wd, 24)
            hov = r.collidepoint(pygame.mouse.get_pos())
            draw_text(surface, ellipsize(title.upper(), wd - 8 - fonts.get(11, True).size(arrow)[0], fonts.get(11, True)) + arrow,
                      (x, left.y + 12), 11, theme.ACCENT if k == key or hov else theme.TEXT_MUTED, bold=True)
            self.hits.append((r, lambda k=k: self._set_sort(k), "Сортировать"))
            x += wd
        view = pygame.Rect(left.x + 6, left.y + 36, left.w - 12, left.h - (66 if w.era != "modern" else 42))
        if w.era != "modern":
            draw_text(surface, "Названия областей даны по современному административному делению.",
                      (left.x + 16, left.bottom - 24), 12, theme.TEXT_MUTED)
        self.scroll_area("land", view)
        total = len(atoms) * ROW
        self.max_scroll["land"] = max(0, total - view.h)
        self.scroll["land"] = min(self.scroll["land"], self.max_scroll["land"])
        first = self.scroll["land"] // ROW
        prev = surface.get_clip()
        surface.set_clip(view.clip(prev))
        for i in range(first, min(len(atoms), first + view.h // ROW + 2)):
            a = int(atoms[i])
            r = pygame.Rect(view.x, view.y + i * ROW - self.scroll["land"], view.w, ROW - 2)
            sel = a == self.sel_atom
            hov = r.collidepoint(pygame.mouse.get_pos()) and view.collidepoint(pygame.mouse.get_pos())
            if sel or hov:
                fill_round(surface, r, theme.mix(theme.GLASS_COLOR, theme.ACCENT, 0.3 if sel else 0.12), 230, 8)
            mine = w.owner[a] == p
            tc = theme.TEXT if mine else theme.TEXT_DIM
            x = r.x + 8
            cells = (ellipsize(w.region_name(a) + ("" if mine else f" ({w.title(w.owner[a])})"),
                               int((left.w - 28) * 0.40) - 10, fonts.get(14)), _num(w.pop[a]), f"{round(w.dev[a])}",
                     f"{round(w.unrest[a])}", _money(out[i]))
            for (k, title, share), text in zip(heads, cells):
                wd = int((left.w - 28) * share)
                color = tc
                if k == "unrest":
                    color = theme.DANGER if w.unrest[a] >= 70 else theme.WARN if w.unrest[a] >= 45 else tc
                draw_text(surface, ellipsize(text, wd - 8, fonts.get(14)), (x, r.y + 6), 14, color)
                x += wd
            self.hits.append((r.clip(view), lambda a=a: setattr(self, "sel_atom", a), None))
        surface.set_clip(prev)
        self.card(surface, right)
        if self.sel_atom is None or self.sel_atom not in set(w.group_atoms(p).tolist()):
            self.sel_atom = int(atoms[0]) if len(atoms) else None
        if self.sel_atom is not None:
            self._land_detail(surface, right, self.sel_atom)

    def _set_sort(self, k):
        self.sort = (k, not self.sort[1] if self.sort[0] == k else k != "name")

    def _land_detail(self, surface, rect, a):
        w, p = self.w, self.p
        x, y, wd = rect.x + 16, rect.y + 14, rect.w - 32
        draw_text(surface, ellipsize(w.region_name(a), wd, fonts.get(20, True)), (x, y), 20, bold=True)
        y += 26
        owner = int(w.owner[a])
        draw_text(surface, f"Власть: {w.title(owner)}" + ("" if owner == p else " (вассал)"), (x, y), 13, theme.TEXT_DIM)
        y += 24
        for label, val, color, frac in (("Население", _num(w.pop[a]), None, None), ("Развитие", f"{round(w.dev[a])}", theme.GOOD, w.dev[a] / 100),
                                        ("Недовольство", f"{round(w.unrest[a])}", self._grade(100 - w.unrest[a]), w.unrest[a] / 100),
                                        ("Укрепления", f"{round(w.fort[a])}", theme.ACCENT, w.fort[a] / 100)):
            draw_text(surface, label, (x, y), 13, theme.TEXT_DIM)
            draw_text(surface, val, (x + wd, y), 14, anchor="topright")
            if frac is not None:
                self.bar(surface, pygame.Rect(x, y + 20, wd, 6), frac, color)
            y += 34
        y += 4
        cfg = w.cfg["invest"]
        out = w.pop[a] * w.gpc[a] * (0.55 + 0.009 * w.dev[a])
        bh = 36
        for text, cb, cost, tip in (
            ("Вложиться в развитие (+5)", lambda: self._do(w.invest, p, a, 5), 5 * out * cfg["cost_per_point"],
             "Дороги, мастерские, склады: растёт выпуск и налоги."),
            ("Амнистия и раздача хлеба", lambda: self._do(w.amnesty, p, a), out * cfg["amnesty_cost"],
             "Снижает недовольство, но это уступка."),
            ("Усилить гарнизон", lambda: self._do(w.garrison, p, a), out * cfg["garrison_cost"],
             "Меньше волнений, труднее взять.")):
            r = pygame.Rect(x, y, wd, bh)
            self.btn(surface, r, f"{text}  ·  {_money(cost)}", cb, enabled=w.treasury[p] >= cost, size=13, tip=tip)
            y += bh + 6
        r = pygame.Rect(x, y, wd, bh)
        self.btn(surface, r, "Основать город…", lambda: self._open_city_dialog(a), size=13,
                 tip="Новый город растёт и принимает постройки.", enabled=owner != 0)
        y += bh + 14
        nb = sorted(w.neighbors(p), key=lambda q: -float(w.pop[w.owner == q].sum()))[:12]
        if nb and w.owner[a] == p:
            self.target_idx %= len(nb)
            draw_text(surface, "ПЕРЕДАТЬ ЗЕМЛЮ", (x, y), 11, theme.ACCENT, bold=True)
            y += 18
            self.btn(surface, pygame.Rect(x, y, 34, 34), "<", lambda: setattr(self, "target_idx", self.target_idx - 1), size=15)
            self.btn(surface, pygame.Rect(x + wd - 34, y, 34, 34), ">", lambda: setattr(self, "target_idx", self.target_idx + 1), size=15)
            tgt = nb[self.target_idx]
            draw_text(surface, ellipsize(w.title(tgt), wd - 90, fonts.get(14, True)), (x + wd // 2, y + 9), 14, bold=True,
                      anchor="midtop")
            y += 42
            self.btn(surface, pygame.Rect(x, y, wd, bh), f"Передать «{ellipsize(w.region_name(a), 120, fonts.get(13))}»",
                     lambda: self._do(w.cede, p, [a], tgt), size=13, tip="Добровольная уступка: отношения улучшатся, доверие к власти упадёт.")

    def _open_city_dialog(self, atom):
        self.dialog = {"kind": "city", "atom": atom}
        self.name_input.text = ""

    # ---------------- Города ----------------
    def _tab_cities(self, surface, body):
        w, p = self.w, self.p
        grp = w.in_group(p)
        cities = sorted((c for c in w.cities if not c.get("pending") and grp[w.owner[c["atom"]]]), key=lambda c: -c["pop"])
        left = pygame.Rect(body.x, body.y, int(body.w * 0.42), body.h - 8)
        right = pygame.Rect(left.right + 12, body.y, body.right - left.right - 12, left.h)
        self.card(surface, left, f"Города государства: {len(cities)}")
        view = pygame.Rect(left.x + 6, left.y + 34, left.w - 12, left.h - 40)
        self.scroll_area("cities", view)
        self.max_scroll["cities"] = max(0, len(cities) * ROW - view.h)
        self.scroll["cities"] = min(self.scroll["cities"], self.max_scroll["cities"])
        prev = surface.get_clip()
        surface.set_clip(view.clip(prev))
        if self.sel_city is None or self.sel_city not in [c["id"] for c in cities]:
            self.sel_city = cities[0]["id"] if cities else None
        for i, c in enumerate(cities):
            r = pygame.Rect(view.x, view.y + i * ROW - self.scroll["cities"], view.w, ROW - 2)
            if r.bottom < view.y or r.y > view.bottom:
                continue
            sel = c["id"] == self.sel_city
            if sel or r.collidepoint(pygame.mouse.get_pos()):
                fill_round(surface, r, theme.mix(theme.GLASS_COLOR, theme.ACCENT, 0.3 if sel else 0.12), 230, 8)
            draw_text(surface, ellipsize(c["ru"], int(r.w * 0.55), fonts.get(14, sel)), (r.x + 10, r.y + 6), 14, bold=sel)
            draw_text(surface, _num(c["pop"]), (r.right - 10, r.y + 6), 14, theme.TEXT_DIM, anchor="topright")
            self.hits.append((r.clip(view), lambda cid=c["id"]: setattr(self, "sel_city", cid), None))
        surface.set_clip(prev)
        self.card(surface, right)
        city = next((c for c in cities if c["id"] == self.sel_city), None)
        if city is None:
            draw_text(surface, "В государстве нет городов. Основать город можно на вкладке «Территории».",
                      (right.x + 18, right.y + 20), 15, theme.TEXT_DIM)
            return
        self._city_detail(surface, right, city)

    def _city_detail(self, surface, rect, c):
        w, p = self.w, self.p
        x, y, wd = rect.x + 18, rect.y + 16, rect.w - 36
        draw_text(surface, c["ru"], (x, y), 24, bold=True)
        draw_text(surface, f"{w.region_name(c['atom'])}  ·  {w.title(w.owner[c['atom']])}", (x, y + 32), 13, theme.TEXT_DIM)
        draw_text(surface, f"{_num(c['pop'])} жителей", (rect.right - 18, y + 4), 18, theme.GOOD, bold=True, anchor="topright")
        y += 62
        bmap = {b["id"]: b for b in w.cfg["buildings"]}
        draw_text(surface, "ПОСТРОЙКИ", (x, y), 11, theme.ACCENT, bold=True)
        y += 20
        if c["b"] or c["q"]:
            for bid in c["b"]:
                draw_text(surface, "• " + bmap[bid]["name"], (x, y), 14)
                y += 22
            for bid, done in c["q"]:
                left = max(done - w.month, 0)
                draw_text(surface, f"• {bmap[bid]['name']} (строится, ещё {left} мес.)", (x, y), 14, theme.TEXT_DIM)
                y += 22
        else:
            draw_text(surface, "пока нет", (x, y), 14, theme.TEXT_MUTED)
            y += 22
        y += 10
        draw_text(surface, "ПОСТРОИТЬ", (x, y), 11, theme.ACCENT, bold=True)
        y += 22
        cols = 2 if wd >= 520 else 1
        bw = (wd - 10 * (cols - 1)) // cols
        i = 0
        for b in w.cfg["buildings"]:
            if w.era not in b["eras"]:
                continue
            ok, why = w.build_status(p, c, b)
            r = pygame.Rect(x + (i % cols) * (bw + 10), y + (i // cols) * 48, bw, 42)
            cost = w.cost_of(p, b["cost"] * 0.05)
            self.btn(surface, r, f"{b['name']}  ·  {_money(cost)}", lambda b=b: self._do(w.build, p, c, b["id"]),
                     enabled=ok, size=13, tip=(b["desc"] if ok else b["desc"] + " — " + why))
            i += 1

    # ---------------- Бюджет ----------------
    def _tab_budget(self, surface, body):
        w, p = self.w, self.p
        left = pygame.Rect(body.x, body.y, int(body.w * (0.56 if body.w >= 760 else 0.62)), body.h - 8)
        right = pygame.Rect(left.right + 12, body.y, body.right - left.right - 12, left.h)
        self.card(surface, left, "Налоги и расходы")
        x, y, wd = left.x + 18, left.y + 34, left.w - 36
        lo, hi = self._limits("tax")
        y = self._fiscal_row(surface, x, y, wd, "tax", "Налоговая ставка", f"от {lo} до {hi}%", float(w.tax[p]), hi / 100,
                             "Сколько процентов выпуска забирает казна.") + 4
        d = w.ec["tax_default"]
        text = ("Выше привычного: казна богаче, народ недоволен." if w.tax[p] > d + 0.01 else
                "Ниже привычного: народ доволен, казна беднее." if w.tax[p] < d - 0.01 else "Привычная ставка.")
        draw_text(surface, ellipsize(f"{text}  (привычная {round(d * 100)}%)", wd, fonts.get(13)), (x, y), 13, theme.TEXT_MUTED)
        y += 24
        draw_text(surface, "РАСХОДЫ, % ДОХОДА", (x, y), 11, theme.ACCENT, bold=True)
        y += 18
        row = min(56, max(44, (left.bottom - y - 26) // len(BUDGET_LABELS)))
        for key in ("army", "admin", "infra", "science", "court"):
            title, tip = BUDGET_LABELS[key]
            self._fiscal_row(surface, x, y, wd, key, title, "", float(w.budget[key][p]), 0.6, tip, h=row - 8)
            y += row
        used = sum(float(w.budget[k][p]) for k in BUDGET_LABELS)
        draw_text(surface, f"Распределено {round(used * 100)}% дохода, остальное идёт в казну.", (x, y + 2), 13, theme.TEXT_MUTED)
        self.card(surface, right, "Прогноз на месяц")
        e = w._economy()
        grp = w.in_group(p)
        rev = float(e["rev_net"][grp].sum()) / 12
        yy = right.y + 34
        spend_rows = [("Доход", rev, theme.GOOD)]
        for key in BUDGET_LABELS:
            spend_rows.append((BUDGET_LABELS[key][0], -float(w.budget[key][p]) * rev, theme.TEXT_DIM))
        interest = float(w.debt[p]) * max(w.ec["interest"] + float(w.eff["interest"][p]), 0) / 12
        spend_rows.append(("Проценты по долгу", -interest, theme.WARN))
        net = rev + sum(v for k, v, _ in spend_rows[1:])
        for label, value, color in spend_rows:
            vw = fonts.get(14).size(_money(value))[0]
            draw_text(surface, ellipsize(label, right.w - 48 - vw, fonts.get(14)), (right.x + 18, yy), 14, theme.TEXT_DIM)
            draw_text(surface, _money(value), (right.right - 18, yy), 14, color, anchor="topright")
            yy += 24
        pygame.draw.line(surface, theme.PANEL_BORDER, (right.x + 18, yy + 2), (right.right - 18, yy + 2))
        yy += 10
        draw_text(surface, "Итого", (right.x + 18, yy), 15, bold=True)
        draw_text(surface, _money(net), (right.right - 18, yy), 17, theme.GOOD if net >= 0 else theme.DANGER, bold=True,
                  anchor="topright")
        yy += 40
        draw_text(surface, f"Казна: {_money(w.treasury[p])}", (right.x + 18, yy), 15)
        draw_text(surface, f"Долг: {_money(w.debt[p])}", (right.x + 18, yy + 24), 15, theme.WARN if w.debt[p] else theme.TEXT_DIM)
        yy += 60
        rev_year = w.annual_revenue(p)
        self.btn(surface, pygame.Rect(right.x + 18, yy, right.w - 36, 38), f"Взять заём  +{_money(rev_year * 0.3)}",
                 lambda: self._do(w.borrow, p, 0.3), size=14,
                 tip=f"Деньги сейчас, проценты {round((w.ec['interest'] + w.eff['interest'][p]) * 100)}% годовых.")
        self.btn(surface, pygame.Rect(right.x + 18, yy + 46, right.w - 36, 38), "Погасить долг из казны", lambda: self._do(w.repay, p),
                 enabled=w.debt[p] > 0 and w.treasury[p] > 0, size=14)

    def _fiscal_row(self, surface, x, y, wd, key, title, note, share, scale, tip, h=48):
        fh = min(36, h)
        fw, bw, pct = (74, 34, 30) if wd >= 420 else (56, 28, 22)
        right = x + wd
        plus = pygame.Rect(right - bw, y, bw, fh)
        field = pygame.Rect(plus.x - pct - fw, y, fw, fh)
        minus = pygame.Rect(field.x - 4 - bw, y, bw, fh)
        lw = minus.x - x - 14
        draw_text(surface, ellipsize(title, lw, fonts.get(15)), (x, y + 2), 15)
        if note:
            draw_text(surface, ellipsize(note, lw, fonts.get(12)), (x, y + 21), 12, theme.TEXT_MUTED)
        else:
            self.bar(surface, pygame.Rect(x, y + fh - 10, lw, 6), share / scale, theme.ACCENT)
        self.btn(surface, minus, "−", lambda: self._step(key, -1), size=17, tip="−1%")
        self.num_field(surface, field, key, self._fiscal()[key])
        draw_text(surface, "%", (field.right + pct // 2, field.centery), 16, theme.TEXT_DIM, anchor="center")
        self.btn(surface, plus, "+", lambda: self._step(key, 1), size=17, tip="+1%")
        if pygame.Rect(x, y, lw, fh).collidepoint(pygame.mouse.get_pos()):
            self.tip = tip
        return y + fh + 8

    # ---------------- Армия ----------------
    def _tab_army(self, surface, body):
        w, p = self.w, self.p
        grp = w.in_group(p)
        gs = w._group_strengths()
        left = pygame.Rect(body.x, body.y, int(body.w * 0.46), body.h - 8)
        right = pygame.Rect(left.right + 12, body.y, body.right - left.right - 12, left.h)
        self.card(surface, left, "Вооружённые силы")
        x, y, wd = left.x + 18, left.y + 34, left.w - 36
        pop = float(w.pop[w.group_atoms(p)].sum())
        cap = w.ec["manpower"] * (1 + float(w.eff["manpower"][p]) + 0.7 * float(w.mob[p])) * pop
        quality = 0.5 + w.tech[p] / 100.0 + float(w.eff["army_quality"][p])
        rows = (("Численность", f"{_num(w.army[grp].sum())} чел."), ("Предел призыва", f"{_num(cap)} чел."),
                ("Качество войск", f"×{quality:.2f}"), ("Дух армии", f"{round(w.morale[p] * 100)}%"),
                ("Боевая мощь", _num(gs[p])), ("Бюджет армии", f"{round(w.budget['army'][p] * 100)}% дохода"))
        for label, value in rows:
            draw_text(surface, label, (x, y), 15, theme.TEXT_DIM)
            draw_text(surface, value, (x + wd, y), 16, theme.TEXT, bold=True, anchor="topright")
            y += 30
        y += 8
        mob = next((d for d in w.cfg["decrees"] if d["id"] == "mobilization"), None)
        if mob and w.era in mob["eras"]:
            ok, why = w.decree_status(p, mob)
            self.btn(surface, pygame.Rect(x, y, wd, 40), f"Объявить мобилизацию  ·  {_money(w.decree_cost(p, mob))}",
                     lambda: self._do(w.enact, p, "mobilization"), enabled=ok, size=14,
                     tip=mob["desc"] + ("" if ok else " — " + why))
            y += 50
        self.paragraph(surface, "Размер армии задаёт доля бюджета на вкладке «Бюджет».", x, y, wd, 13, theme.TEXT_MUTED)
        self.card(surface, right, "Войны и соседи")
        yy = right.y + 34
        my_wars = [war for war in w.wars if grp[war["att"]] or grp[war["dfn"]]]
        if my_wars:
            for war in my_wars:
                ours = 1 if grp[war["att"]] else -1
                foe = war["dfn"] if ours > 0 else war["att"]
                score = war["score"] * ours
                draw_text(surface, f"Война с {w.title(foe)}", (right.x + 18, yy), 15, bold=True)
                draw_text(surface, f"{w.month - war['since']} мес.", (right.right - 18, yy + 1), 13, theme.TEXT_MUTED, anchor="topright")
                yy += 24
                track = pygame.Rect(right.x + 18, yy, right.w - 36, 10)
                fill_round(surface, track, theme.mix(theme.DANGER, theme.GLASS_COLOR, 0.4), 255, 5)
                fill_round(surface, pygame.Rect(track.centerx, track.y, int(track.w * min(max(score, 0), 100) / 200), 10),
                           theme.GOOD, 255, 0)
                if score < 0:
                    r = pygame.Rect(track.centerx - int(track.w * min(-score, 100) / 200), track.y, int(track.w * min(-score, 100) / 200), 10)
                    fill_round(surface, r, theme.DANGER, 255, 0)
                pygame.draw.line(surface, theme.TEXT, (track.centerx, track.y - 3), (track.centerx, track.bottom + 3))
                yy += 20
                self.btn(surface, pygame.Rect(right.x + 18, yy, (right.w - 46) // 2, 34), "Предложить мир",
                         lambda foe=foe: self._do(w.propose_peace, p, foe), size=13,
                         tip="Белый мир при равенстве сил; победителю уступают.")
                self.btn(surface, pygame.Rect(right.x + 28 + (right.w - 46) // 2, yy, (right.w - 46) // 2, 34),
                         "Мир ценой уступок", lambda foe=foe: self._do(w.propose_peace, p, foe, True), size=13,
                         tip="Заплатить землями за немедленный мир.")
                yy += 52
        else:
            draw_text(surface, "Сейчас мир.", (right.x + 18, yy), 15, theme.TEXT_DIM)
            yy += 28
        yy += 6
        draw_text(surface, "СОСЕДИ ПО МОЩИ", (right.x + 18, yy), 11, theme.ACCENT, bold=True)
        yy += 20
        mine = max(float(gs[p]), 1.0)
        for q in sorted(w.neighbors(p), key=lambda q: -float(gs[q]))[:9]:
            ratio = float(gs[q]) / mine
            draw_text(surface, ellipsize(w.title(q), int(right.w * 0.5), fonts.get(14)), (right.x + 18, yy), 14)
            draw_text(surface, f"×{ratio:.2f} от нашей", (right.right - 18, yy), 14,
                      theme.DANGER if ratio > 1.3 else theme.WARN if ratio > 0.8 else theme.GOOD, anchor="topright")
            yy += 24

    # ---------------- Дипломатия ----------------
    def _diplo_rows(self):
        w, p = self.w, self.p
        key = (w.version, w.month // 3)
        if self._rows_cache and self._rows_cache[0] == key:
            return self._rows_cache[1]
        roots = w.roots()
        alive = [i for i in range(1, w.next_poly) if w.owner_has(i) and roots[i] == i and i != p]
        nb = w.neighbors(p)
        pops = np.bincount(w.owner, w.pop, w.cap)
        near = sorted([q for q in alive if q in nb or w.distance(p, q) < 45], key=lambda q: (q not in nb, -pops[q]))[:60]
        self._rows_cache = (key, near)
        return near

    def _tab_diplomacy(self, surface, body):
        w, p = self.w, self.p
        rows = self._diplo_rows()
        left = pygame.Rect(body.x, body.y, int(body.w * 0.40), body.h - 8)
        right = pygame.Rect(left.right + 12, body.y, body.right - left.right - 12, left.h)
        self.card(surface, left, "Державы вокруг")
        view = pygame.Rect(left.x + 6, left.y + 34, left.w - 12, left.h - 40)
        self.scroll_area("diplomacy", view)
        self.max_scroll["diplomacy"] = max(0, len(rows) * 34 - view.h)
        self.scroll["diplomacy"] = min(self.scroll["diplomacy"], self.max_scroll["diplomacy"])
        if self.sel_polity not in rows:
            self.sel_polity = rows[0] if rows else None
        prev = surface.get_clip()
        surface.set_clip(view.clip(prev))
        nb = w.neighbors(p)
        for i, q in enumerate(rows):
            r = pygame.Rect(view.x, view.y + i * 34 - self.scroll["diplomacy"], view.w, 32)
            if r.bottom < view.y or r.y > view.bottom:
                continue
            sel = q == self.sel_polity
            if sel or r.collidepoint(pygame.mouse.get_pos()):
                fill_round(surface, r, theme.mix(theme.GLASS_COLOR, theme.ACCENT, 0.3 if sel else 0.12), 230, 8)
            rel = w.relation(p, q)
            pygame.draw.circle(surface, theme.GOOD if rel > 15 else theme.DANGER if rel < -15 else theme.TEXT_MUTED, (r.x + 14, r.centery), 5)
            tag = "война" if w.at_war(p, q) else "союз" if w.allied(p, q) else "сосед" if q in nb else ""
            draw_text(surface, ellipsize(w.title(q), int(r.w * 0.6), fonts.get(14, sel)), (r.x + 28, r.y + 7), 14, bold=sel)
            if tag:
                draw_text(surface, tag, (r.right - 10, r.y + 8), 12, theme.DANGER if tag == "война" else theme.TEXT_MUTED,
                          anchor="topright")
            self.hits.append((r.clip(view), lambda q=q: setattr(self, "sel_polity", q), None))
        surface.set_clip(prev)
        self.card(surface, right)
        if self.sel_polity is not None:
            self._diplo_detail(surface, right, self.sel_polity)
        claims = w.claims(p)
        if claims:
            r = pygame.Rect(right.x + 16, right.bottom - 12 - 44 * min(len(claims), 3) - 24, right.w - 32, 24)
            draw_text(surface, "ИСТОРИЧЕСКИЕ ПРИТЯЗАНИЯ", (r.x, r.y), 11, theme.ACCENT, bold=True)
            for i, (ev, n) in enumerate(claims[:3]):
                rr = pygame.Rect(r.x, r.y + 20 + i * 44, r.w, 38)
                self.btn(surface, rr, f"Потребовать у {w.title(ev['frm'])}: {n} обл.",
                         lambda ev=ev: self._do(w.press_claim, p, ev), size=13,
                         tip="Давление по праву истории: сильному уступают, слабому отказывают.")

    def _diplo_detail(self, surface, rect, q):
        w, p = self.w, self.p
        st = w.diplo_state(p, q)
        d = w.cfg["diplomacy"]
        x, y, wd = rect.x + 18, rect.y + 16, rect.w - 36
        pol = w.polity(q)
        draw_polity_flag(surface, self.app, pol, w.date_year(), pygame.Rect(x, y, 60, 40))
        draw_text(surface, ellipsize(w.title(q), wd - 80, fonts.get(22, True)), (x + 74, y), 22, bold=True)
        gov = w.cfg["governments"][w.gov_list[w.gov[q]]]["name"]
        draw_text(surface, gov, (x + 74, y + 28), 13, theme.TEXT_DIM)
        y += 56
        gs = w._group_strengths()
        mine = max(float(gs[p]), 1.0)
        pop = float(w.pop[w.owner == q].sum())
        for label, val in (("Население", _num(pop)), ("Мощь относительно нашей", f"×{float(gs[q]) / mine:.2f}"),
                           ("Технологии", f"{round(w.tech[q])}"), ("Расстояние", f"{w.distance(p, q):.0f}°")):
            draw_text(surface, label, (x, y), 14, theme.TEXT_DIM)
            draw_text(surface, val, (x + wd, y), 15, anchor="topright")
            y += 26
        y += 6
        rel = st["relation"]
        draw_text(surface, "Отношения", (x, y), 14, theme.TEXT_DIM)
        draw_text(surface, f"{rel:+d}", (x + wd, y), 16, theme.GOOD if rel > 0 else theme.DANGER if rel < 0 else theme.TEXT,
                  bold=True, anchor="topright")
        y += 24
        track = pygame.Rect(x, y, wd, 10)
        fill_round(surface, track, theme.mix(theme.GLASS_COLOR, theme.TEXT, 0.1), 255, 5)
        mid = track.centerx
        size = int(track.w * abs(rel) / 200)
        fill_round(surface, pygame.Rect(mid if rel >= 0 else mid - size, track.y, size, 10), theme.GOOD if rel >= 0 else theme.DANGER, 255, 0)
        pygame.draw.line(surface, theme.TEXT, (mid, track.y - 3), (mid, track.bottom + 3))
        y += 28
        status = []
        if st["war"]:
            status.append("ВОЙНА")
        if st["allied"]:
            status.append("союз")
        if st["truce"]:
            status.append("перемирие")
        if st["vassal"]:
            status.append("ваш вассал")
        draw_text(surface, "Статус: " + (", ".join(status) if status else "мир"), (x, y), 14, theme.WARN if st["war"] else theme.TEXT)
        y += 30
        half = (wd - 10) // 2
        bh = 38
        cost = lambda f: _money(w.cost_of(p, f))
        acts = [
            (f"Дар  ·  {cost(d['gift_cost'])}", lambda: self._do(w.gift, p, q), True, "Подарки улучшают отношения."),
            (f"Посольство  ·  {cost(d['embassy_cost'])}", lambda: self._do(w.embassy, p, q), True, "Постоянные контакты."),
            ("Торговый договор", lambda: self._do(w.trade_pact, p, q), rel >= d["trade_min_relation"] and not st["war"],
             f"Нужны отношения {d['trade_min_relation']}+. Выгода обеим сторонам."),
            ("Союз" if not st["allied"] else "Расторгнуть союз",
             (lambda: self._do(w.alliance, p, q)) if not st["allied"] else (lambda: self._do(w.break_alliance, p, q)),
             (rel >= d["alliance_min_relation"] and not st["war"]) or st["allied"],
             f"Союзники помогают в войне. Нужны отношения {d['alliance_min_relation']}+."),
            ("Потребовать земли", lambda: self._do(w.demand, p, q, 0.1), not st["war"] and not st["truce"] and not st["allied"],
             "Сильному уступают 10% земель; слабому отказывают."),
            ("Объявить войну", lambda: self._do(w.declare_war, p, q), not st["war"] and not st["truce"] and not st["allied"] and st["reach"],
             "Нужна граница или путь. Стабильность и доверие упадут."),
        ]
        if st["war"]:
            acts[5] = ("Предложить мир", lambda: self._do(w.propose_peace, p, q), True, "Мир на равных или на ваших условиях.")
        if st["vassal"]:
            acts[4] = ("Дать независимость", lambda: self._do(w.release_vassal, p, q), True, "Вассал станет независимым.")
        for i, (text, cb, ok, tip) in enumerate(acts):
            r = pygame.Rect(x + (i % 2) * (half + 10), y + (i // 2) * (bh + 8), half, bh)
            self.btn(surface, r, text, cb, enabled=ok, size=13, tip=tip, accent=text in ("Объявить войну",))

    # ---------------- Указы ----------------
    def _tab_decrees(self, surface, body):
        w, p = self.w, self.p
        active = w.decrees.get(p, {})
        items = [d for d in w.cfg["decrees"] if w.era in (d.get("eras") or [w.era])]
        items.sort(key=lambda d: (d["id"] not in active, not w.decree_status(p, d)[0], d["name"]))
        cols = 2 if body.w >= 900 else 1
        cw = (body.w - 12 * (cols - 1)) // cols
        ch = 132
        rows = (len(items) + cols - 1) // cols
        self.scroll_area("decrees", body)
        self.max_scroll["decrees"] = max(0, rows * (ch + 10) - body.h)
        self.scroll["decrees"] = min(self.scroll["decrees"], self.max_scroll["decrees"])
        for i, d in enumerate(items):
            r = pygame.Rect(body.x + (i % cols) * (cw + 12), body.y + (i // cols) * (ch + 10) - self.scroll["decrees"], cw, ch)
            if r.bottom < body.y or r.y > body.bottom:
                continue
            self._decree_card(surface, r, d, d["id"] in active, active.get(d["id"]))

    def _decree_card(self, surface, r, d, is_active, info):
        w, p = self.w, self.p
        self.card(surface, r)
        if is_active:
            pygame.draw.rect(surface, theme.GOOD, r, 1, border_radius=14)
        draw_text(surface, ellipsize(d["name"], r.w - 190, fonts.get(16, True)), (r.x + 16, r.y + 12), 16, bold=True)
        ok, why = w.decree_status(p, d)
        cost = w.decree_cost(p, d)
        fx = d["effects"]
        parts = []
        names = {"output": "выпуск", "growth": "рост населения", "dev_growth": "развитие", "unrest": "недовольство/мес",
                 "tax_eff": "сбор налогов", "stab_target": "стабильность", "legit": "доверие", "science": "наука",
                 "army_quality": "качество армии", "army_cost": "цена армии", "manpower": "призыв", "interest": "проценты",
                 "debt_limit": "предел долга", "tribute": "дань", "relations": "отношения", "stab_once": "стабильность разово",
                 "legit_once": "доверие разово"}
        for k, v in fx.items():
            val = f"{v:+.0%}" if abs(v) < 1.5 and k not in ("unrest", "stab_target", "stab_once", "legit_once") else f"{v:+g}"
            parts.append(f"{names.get(k, k)} {val}")
        y = self.paragraph(surface, d["desc"], r.x + 16, r.y + 38, r.w - 32, 13)
        draw_text(surface, ellipsize("  ·  ".join(parts), r.w - 32, fonts.get(12)), (r.x + 16, min(y + 2, r.bottom - 42)), 12, theme.ACCENT)
        label = "действует" + (f", ещё {max(info['until'] - w.month, 0)} мес." if info and info.get("until") else "") if is_active else \
            f"{_money(cost)}"
        if is_active:
            draw_text(surface, label, (r.right - 16, r.y + 14), 13, theme.GOOD, anchor="topright")
            self.btn(surface, pygame.Rect(r.right - 120, r.bottom - 38, 104, 28), "Отменить", lambda: self._do(w.repeal, p, d["id"]), size=12)
        else:
            draw_text(surface, label, (r.right - 16, r.y + 14), 14, theme.TEXT_DIM, anchor="topright")
            self.btn(surface, pygame.Rect(r.right - 150, r.bottom - 38, 134, 28), "Издать указ", lambda: self._do(w.enact, p, d["id"]),
                     enabled=ok, size=13, accent=ok)
            if not ok:
                draw_text(surface, ellipsize(why, 210, fonts.get(12)), (r.x + 16, r.bottom - 30), 12, theme.WARN)

    # ---------------- Хроника ----------------
    def _tab_chronicle(self, surface, body):
        w = self.w
        self.btn(surface, pygame.Rect(body.x, body.y, 180, 34), "События: мои" if not self.chron_all else "События: все",
                 lambda: setattr(self, "chron_all", not self.chron_all), size=13,
                 tip="Переключить между событиями рядом с вами и всеми событиями мира.")
        entries = [e for e in reversed(w.log) if self.chron_all or w.relevant(e)]
        view = pygame.Rect(body.x, body.y + 46, body.w, body.h - 54)
        self.scroll_area("chronicle", view)
        lines = []
        for e in entries[:200]:
            for k, line in enumerate(wrap(e[1], view.w - 130, 14)):
                lines.append((e if k == 0 else None, line))
        lh = 22
        self.max_scroll["chronicle"] = max(0, len(lines) * lh - view.h)
        self.scroll["chronicle"] = min(self.scroll["chronicle"], self.max_scroll["chronicle"])
        prev = surface.get_clip()
        surface.set_clip(view.clip(prev))
        colors = {"war": theme.DANGER, "revolt": theme.DANGER, "peace": theme.GOOD, "territory": theme.WARN,
                  "history": theme.ACCENT, "econ": theme.WARN, "decree": theme.GOOD, "city": theme.GOOD}
        for i, (e, line) in enumerate(lines):
            y = view.y + i * lh - self.scroll["chronicle"]
            if y < view.y - lh or y > view.bottom:
                continue
            if e:
                draw_text(surface, f"{w.date_year(e[0])} г.", (view.x + 8, y), 13, theme.TEXT_MUTED)
                pygame.draw.circle(surface, colors.get(e[2], theme.TEXT_MUTED), (view.x + 88, y + 9), 4)
            draw_text(surface, line, (view.x + 104, y), 14, theme.TEXT)
        surface.set_clip(prev)
        if not lines:
            draw_text(surface, "Событий пока нет: пропустите время или объявите указ.", (view.x + 8, view.y + 8), 15, theme.TEXT_DIM)
