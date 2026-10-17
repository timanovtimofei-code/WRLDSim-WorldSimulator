import pygame

from ..sim import saves
from ..ui import fonts, theme
from ..ui import format as fmt
from ..ui.widgets import Button, draw_panel, draw_spaced, draw_text, draw_trash, ellipsize
from .base import ModalState
from .confirm import ConfirmState

ROW_H = 64
ROW_GAP = 10
TRASH_W = 40


def _hero_title(meta, sep):
    who = ", ".join(t for t in (meta.get("hero_name"), meta.get("role")) if t)
    return sep.join(t for t in (meta.get("country_name", "?"), who) if t)


class SaveSlotsState(ModalState):
    def __init__(self, app, mode_id, action, on_pick, on_delete=None):
        super().__init__(app)
        self.mode_id = mode_id
        self.action = action
        self.on_pick = on_pick
        self.on_delete = on_delete
        self.slots = app.modes["modes"][mode_id]["rules"]["save_slots"]
        self.meta = saves.read_meta(mode_id, self.slots)
        self.buttons = {slot: Button("", lambda s=slot: self._pick(s)) for slot in range(1, self.slots + 1)}
        self.trash_rects = {}
        self.cancel_btn = Button("Закрыть", app.pop, size=16)
        self.list_rect = pygame.Rect(0, 0, 0, 0)
        self.scroll = 0
        self.max_scroll = 0

    def _pick(self, slot):
        self.app.pop()
        self.on_pick(slot)

    def _ask_delete(self, slot):
        meta = self.meta[slot] or {}
        what = _hero_title(meta, " · ")
        self.app.push(ConfirmState(
            self.app, "УДАЛИТЬ СЛОТ?", f"Слот {slot}: {what}. Сохранение будет стёрто без возможности восстановления.",
            lambda: self._delete(slot), accept_text="Удалить"))

    def _delete(self, slot):
        saves.delete(self.mode_id, slot)
        self.meta = saves.read_meta(self.mode_id, self.slots)
        if self.on_delete:
            self.on_delete(slot)

    def _scroll_by(self, delta):
        self.scroll = min(max(self.scroll + delta, 0), self.max_scroll)

    def handle_event(self, event):
        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_ESCAPE:
                self.app.pop()
                return
            step = {pygame.K_UP: -ROW_H - ROW_GAP, pygame.K_DOWN: ROW_H + ROW_GAP,
                    pygame.K_PAGEUP: -4 * (ROW_H + ROW_GAP), pygame.K_PAGEDOWN: 4 * (ROW_H + ROW_GAP)}.get(event.key)
            if step:
                self._scroll_by(step)
                return
        if event.type == pygame.MOUSEWHEEL:
            self._scroll_by(-event.y * 50)
            return
        if self.cancel_btn.handle_event(event):
            return
        pos = getattr(event, "pos", None)
        if pos is None or not self.list_rect.collidepoint(pos):
            return
        if event.type == pygame.MOUSEBUTTONUP and event.button == 1:
            for slot, rect in self.trash_rects.items():
                if rect.collidepoint(pos):
                    self._ask_delete(slot)
                    return
        elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if any(rect.collidepoint(pos) for rect in self.trash_rects.values()):
                return
        for b in self.buttons.values():
            if b.handle_event(event):
                return

    def draw(self, surface):
        w, h = surface.get_size()
        self.draw_backdrop(surface)

        pw = min(680, w - 24)
        ph = min(h - 40, 150 + self.slots * (ROW_H + ROW_GAP))
        panel = pygame.Rect((w - pw) // 2, (h - ph) // 2, pw, ph)
        draw_panel(surface, panel, alpha=245, border=theme.BUTTON_BORDER)
        titles = {"save": "СОХРАНИТЬ", "load": "ЗАГРУЗИТЬ"}
        draw_spaced(surface, titles[self.action], (panel.centerx, panel.y + 38), 24, spacing=0.25)
        taken = sum(1 for m in self.meta.values() if m)
        draw_text(surface, f"Занято {taken} из {self.slots}", (panel.x + 28, panel.bottom - 40), 14, theme.TEXT_DIM,
                  anchor="midleft")

        self.list_rect = pygame.Rect(panel.x + 20, panel.y + 70, pw - 40, panel.h - 70 - 70)
        content_h = self.slots * (ROW_H + ROW_GAP) - ROW_GAP
        self.max_scroll = max(0, content_h - self.list_rect.h)
        self.scroll = min(self.scroll, self.max_scroll)
        prev_clip = surface.get_clip()
        surface.set_clip(self.list_rect.clip(prev_clip))
        row_w = self.list_rect.w - (14 if self.max_scroll else 0)
        self.trash_rects = {}
        mouse = pygame.mouse.get_pos()
        y = self.list_rect.y - self.scroll
        for slot, b in self.buttons.items():
            b.rect = pygame.Rect(self.list_rect.x, y, row_w, ROW_H)
            b.enabled = self.action == "save" or self.meta[slot] is not None
            if b.rect.bottom >= self.list_rect.top and b.rect.top <= self.list_rect.bottom:
                b.draw(surface)
                self._draw_slot(surface, b.rect, slot, b.enabled, mouse)
            y += ROW_H + ROW_GAP
        surface.set_clip(prev_clip)
        if self.max_scroll:
            track = pygame.Rect(self.list_rect.right - 6, self.list_rect.y + 2, 4, self.list_rect.h - 4)
            pygame.draw.rect(surface, theme.PANEL_BORDER, track, border_radius=2)
            thumb_h = max(30, track.h * self.list_rect.h // content_h)
            thumb_y = track.y + (track.h - thumb_h) * self.scroll // self.max_scroll
            pygame.draw.rect(surface, theme.ACCENT, (track.x, thumb_y, 4, thumb_h), border_radius=2)

        self.cancel_btn.rect = pygame.Rect(panel.right - 184, panel.bottom - 60, 160, 40)
        self.cancel_btn.draw(surface)

    def _draw_slot(self, surface, rect, slot, enabled, mouse):
        meta = self.meta[slot]
        color = theme.TEXT if enabled else theme.TEXT_MUTED
        draw_text(surface, f"Слот {slot}", (rect.x + 16, rect.y + 10), 16, color, bold=True)
        if meta is None:
            draw_text(surface, "Пусто", (rect.x + 16, rect.y + 34), 14, theme.TEXT_MUTED)
            return
        trash = pygame.Rect(rect.right - TRASH_W - 8, rect.centery - 20, TRASH_W, 40)
        self.trash_rects[slot] = trash
        right = trash.x - 10
        title = _hero_title(meta, "  ·  ")
        draw_text(surface, ellipsize(title, right - rect.x - 100 - 130, fonts.get(16)), (rect.x + 100, rect.y + 10), 16,
                  color)
        era = f"{meta['era_name']}  ·  " if meta.get("era_name") else ""
        draw_text(surface, ellipsize(f"{era}{meta.get('date', '')}  ·  {meta.get('money_text') or fmt.usd(meta.get('money', 0), ('$', ''))}",
                                     right - rect.x - 130, fonts.get(14)), (rect.x + 16, rect.y + 34), 14, theme.TEXT_DIM)
        saved = meta.get("saved_at", "").replace("T", " ")[:16]
        draw_text(surface, saved, (right, rect.y + 10), 13, theme.TEXT_MUTED, anchor="topright")
        if self.action == "save" and rect.collidepoint(mouse) and not trash.collidepoint(mouse):
            draw_text(surface, "перезаписать", (right, rect.y + 36), 13, theme.WARN, anchor="topright")
        draw_trash(surface, trash, trash.collidepoint(mouse))
