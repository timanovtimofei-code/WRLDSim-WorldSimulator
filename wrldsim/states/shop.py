import pygame

from ..sim import shop
from ..ui import fonts, theme
from ..ui import format as fmt
from ..ui.widgets import (Button, TextInput, draw_glass_control, draw_panel, draw_paragraph, draw_spaced,
                          draw_text, ellipsize, fill_round, wrap)
from .base import ModalState
from .confirm import ConfirmState

OWNED = "Моё имущество"
CARD_MIN_W = 230
CARD_H = 300
IMG_H = 140
GAP = 14
SIDEBAR_W = 210
_fetcher = None


def _images():
    global _fetcher
    if _fetcher is None:
        _fetcher = shop.ImageFetcher()
    return _fetcher


class ShopState(ModalState):
    def __init__(self, app, game, eclipse_cfg, summary_fn, on_change=None, before_change=None, categories=None):
        super().__init__(app)
        self.before_change = before_change
        self.categories = list(categories or shop.CATEGORIES)
        self.game = game
        self.cfg = eclipse_cfg
        self.summary_fn = summary_fn
        self.on_change = on_change
        if not hasattr(game, "shop_cache"):
            game.shop_cache = {}
        self.page = self.categories[0]
        self.query = ""
        self.scroll = 0
        self.max_scroll = 0
        self.cat_btns = {c: Button(c, lambda c=c: self._open(c), size=15) for c in [*self.categories, OWNED]}
        self.search = TextInput(size=16, max_len=80)
        self.search.caret = False
        self.search_rect = pygame.Rect(0, 0, 0, 0)
        self.find_btn = Button("Найти", self._find, size=15)
        self.refresh_btn = Button("Обновить", self._refresh, size=15)
        self.close_btn = Button("Закрыть", app.pop, size=15, bold=True)
        self.card_btns = []
        self._btns = {}               # кнопки карточек живут между кадрами (нажатие - это down + up)
        self._img_cache = {}
        self.grid_rect = pygame.Rect(0, 0, 0, 0)
        self._request()

    def _key(self):
        return (self.page, self.query)

    def _request(self, force=False):
        if self.page == OWNED:
            return
        key = self._key()
        if force or key not in self.game.shop_cache:
            self.game.shop_cache[key] = shop.CatalogRequest(self.cfg, self.summary_fn(), self.page, self.query)

    def _open(self, page):
        self.page, self.query, self.scroll = page, "", 0
        self.search.text = ""
        self._request()

    def _find(self):
        text = self.search.text.strip()
        if not text:
            return
        self.page, self.query, self.scroll = "Поиск", text, 0
        self.search.caret = False
        self._request()

    def _refresh(self):
        self.scroll = 0
        self._request(force=True)

    def _price(self, item):
        mult = (self.game.difficulty or {}).get("price_mult", 1.0)
        return round(item["price"] * float(mult), 2)

    def _buy(self, item):
        price = self._price(item)
        if self.game.money < price:
            return

        def accept():
            if self.before_change and self.game.money >= price:
                self.before_change()
            if shop.buy(self.game, item, price) and self.on_change:
                self.on_change(f"Куплено: {item['name']} за {fmt.usd(price)}")
        self.app.push(ConfirmState(self.app, "ПОКУПКА", f"{item['name']} за {fmt.usd(price)}. "
                                   f"Останется {fmt.usd(self.game.money - price)}.", accept, accept_text="Купить"))

    def _sell(self, index):
        item = shop.inventory(self.game.s)[index]
        gain = round(item["price"] * shop.SELL_SHARE, 2)

        def accept():
            if self.before_change:
                self.before_change()
            if shop.sell(self.game, index) is not None and self.on_change:
                self.on_change(f"Продано: {item['name']} за {fmt.usd(gain)}")
        self.app.push(ConfirmState(self.app, "ПРОДАЖА", f"Продать «{item['name']}» за {fmt.usd(gain)} "
                                   f"({int(shop.SELL_SHARE * 100)}% цены покупки)?", accept, accept_text="Продать"))

    def handle_event(self, event):
        if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
            if self.search.caret:
                self.search.caret = False
            else:
                self.app.pop()
            return
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            self.search.caret = self.search_rect.collidepoint(event.pos)
        if self.search.caret and event.type in (pygame.TEXTINPUT, pygame.KEYDOWN):
            if event.type == pygame.KEYDOWN and event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                self._find()
            else:
                self.search.handle_event(event)
            return
        if event.type == pygame.MOUSEWHEEL and self.grid_rect.collidepoint(pygame.mouse.get_pos()):
            self.scroll = min(max(0, self.scroll - event.y * 60), self.max_scroll)
            return
        for b in (*self.cat_btns.values(), self.find_btn, self.refresh_btn, self.close_btn):
            if b.handle_event(event):
                return
        for b, _ in self.card_btns:
            if b.rect.colliderect(self.grid_rect) and b.handle_event(event):
                return

    def update(self, dt):
        self.search.update(dt)

    def _image(self, query, size):
        path = _images().path(query)
        if path is None:
            return None
        key = (path, size)
        img = self._img_cache.get(key)
        if img is None:
            try:
                src = pygame.image.load(path).convert()
            except (pygame.error, OSError):
                return None
            k = max(size[0] / src.get_width(), size[1] / src.get_height())
            scaled = pygame.transform.smoothscale(src, (max(1, round(src.get_width() * k)),
                                                        max(1, round(src.get_height() * k))))
            rect = pygame.Rect(0, 0, *size)
            rect.center = scaled.get_rect().center
            img = scaled.subsurface(rect).copy()
            mask = pygame.Surface(size, pygame.SRCALPHA)
            pygame.draw.rect(mask, (255, 255, 255, 255), mask.get_rect(), border_radius=theme.RADIUS_SM)
            img = img.convert_alpha()
            img.blit(mask, (0, 0), special_flags=pygame.BLEND_RGBA_MIN)
            self._img_cache[key] = img
        return img

    def _placeholder(self, surface, rect, name):
        fill_round(surface, rect, theme.mix(theme.BUTTON_BG, theme.ACCENT, 0.12), 200, theme.RADIUS_SM)
        letter = (name or "?")[0].upper()
        draw_text(surface, letter, rect.center, 48, theme.mix(theme.TEXT, theme.ACCENT, 0.4), bold=True,
                  anchor="center")

    def _card(self, surface, rect, key, item, price_text, action_text, action, enabled, note=""):
        hovered = rect.collidepoint(pygame.mouse.get_pos()) and self.grid_rect.collidepoint(pygame.mouse.get_pos())
        draw_glass_control(surface, rect, theme.RADIUS, hover=0.6 if hovered else 0.0, sweep=False)
        img_rect = pygame.Rect(rect.x + 10, rect.y + 10, rect.w - 20, IMG_H)
        img = self._image(item.get("image_query", ""), img_rect.size)
        if img:
            surface.blit(img, img_rect)
        else:
            self._placeholder(surface, img_rect, item["name"])
        x, w = rect.x + 14, rect.w - 28
        y = img_rect.bottom + 10
        for line in wrap(item["name"], w, 15, True)[:2]:
            draw_text(surface, line, (x, y), 15, theme.TEXT, bold=True)
            y += fonts.get(15, True).get_linesize()
        desc = wrap(item.get("description", ""), w, 12)
        for i, line in enumerate(desc[:3]):
            if i == 2 and len(desc) > 3:
                line = ellipsize(line + "…", w, fonts.get(12))
            draw_text(surface, line, (x, y + 2), 12, theme.TEXT_DIM)
            y += fonts.get(12).get_linesize()
        bottom = rect.bottom - 12
        draw_text(surface, price_text, (x, bottom - 18), 16, theme.GOOD if enabled else theme.DANGER, bold=True,
                  anchor="midleft")
        if note:
            draw_text(surface, note, (x, bottom - 40), 11, theme.TEXT_MUTED, anchor="midleft")
        btn = self._btns.get(key)
        if btn is None:
            btn = self._btns[key] = Button(action_text, action, size=14)
        btn.text, btn.on_click, btn.enabled = action_text, action, enabled
        btn.rect = pygame.Rect(rect.right - 14 - 104, bottom - 34, 104, 32)
        btn.draw(surface)
        self.card_btns.append((btn, action))

    def draw(self, surface):
        w, h = surface.get_size()
        self.draw_backdrop(surface)
        if getattr(self, "_dim", None) is None or self._dim.get_size() != (w, h):
            self._dim = pygame.Surface((w, h), pygame.SRCALPHA)
            self._dim.fill((0, 0, 0, 150))
        surface.blit(self._dim, (0, 0))
        pw, ph = min(w - 60, 1240), min(h - theme.TOPBAR_H - 30, 820)
        panel = pygame.Rect((w - pw) // 2, theme.TOPBAR_H + max(8, (h - theme.TOPBAR_H - ph) // 2), pw, ph)
        draw_panel(surface, panel, alpha=250, border=theme.ACCENT)
        draw_spaced(surface, "МАГАЗИН", (panel.x + 30, panel.y + 34), 24, spacing=0.25, anchor="midleft")
        draw_text(surface, "Баланс", (panel.right - 30, panel.y + 18), 12, theme.TEXT_DIM, anchor="topright")
        draw_text(surface, fmt.usd(self.game.money), (panel.right - 30, panel.y + 32), 20, theme.GOOD, bold=True,
                  anchor="topright")

        y = panel.y + 74
        step = min(44, (panel.bottom - 62 - 10 - y - 10) // len(self.cat_btns))
        for page, b in self.cat_btns.items():
            if page == OWNED:
                y += 10
            b.rect = pygame.Rect(panel.x + 24, y, SIDEBAR_W, max(24, step - 6))
            b.selected = page == self.page
            b.draw(surface)
            y += step
        self.close_btn.rect = pygame.Rect(panel.x + 24, panel.bottom - 62, SIDEBAR_W, 40)
        self.close_btn.draw(surface)

        gx = panel.x + 24 + SIDEBAR_W + 24
        gw = panel.right - 24 - gx
        self.search_rect = pygame.Rect(gx, panel.y + 74, gw - 2 * 120 - 20, 40)
        self.search.rect = self.search_rect
        self.search.radius = 20
        self.search.draw(surface, "Найти что угодно: «квартира в центре», «спорткар», «охрана»…")
        self.find_btn.rect = pygame.Rect(self.search_rect.right + 10, self.search_rect.y, 120, 40)
        self.refresh_btn.rect = pygame.Rect(self.find_btn.rect.right + 10, self.search_rect.y, 120, 40)
        self.find_btn.draw(surface)
        self.refresh_btn.enabled = self.page != OWNED
        self.refresh_btn.draw(surface)

        title = f"Поиск: «{self.query}»" if self.query else self.page
        draw_text(surface, title, (gx, panel.y + 128), 15, theme.ACCENT, bold=True)
        self.grid_rect = pygame.Rect(gx, panel.y + 156, gw, panel.bottom - 20 - (panel.y + 156))
        self.card_btns = []
        prev = surface.get_clip()
        surface.set_clip(self.grid_rect.clip(prev) if prev else self.grid_rect)
        if self.page == OWNED:
            self._draw_owned(surface)
        else:
            self._draw_catalog(surface)
        surface.set_clip(prev)

    def _grid(self, count):
        cols = max(1, (self.grid_rect.w + GAP) // (CARD_MIN_W + GAP))
        cw = (self.grid_rect.w - GAP * (cols - 1)) // cols
        rows = -(-count // cols)
        self.max_scroll = max(0, rows * (CARD_H + GAP) - GAP - self.grid_rect.h)
        self.scroll = min(self.scroll, self.max_scroll)
        for i in range(count):
            r, c = divmod(i, cols)
            yield i, pygame.Rect(self.grid_rect.x + c * (cw + GAP), self.grid_rect.y + r * (CARD_H + GAP) - self.scroll,
                                 cw, CARD_H)

    def _message(self, surface, text, color=None):
        self.max_scroll = 0
        draw_paragraph(surface, text, (self.grid_rect.x, self.grid_rect.y + 10), self.grid_rect.w, 16,
                       color or theme.TEXT_DIM)

    def _draw_catalog(self, surface):
        req = self.game.shop_cache.get(self._key())
        if req is None:
            return
        if not req.done:
            dots = "." * (1 + pygame.time.get_ticks() // 400 % 3)
            self._message(surface, "ИИ подбирает товары" + dots)
            return
        if req.error:
            self._message(surface, req.error, theme.DANGER)
            return
        for i, rect in self._grid(len(req.items)):
            if rect.bottom < self.grid_rect.y or rect.y > self.grid_rect.bottom:
                continue
            item = req.items[i]
            price = self._price(item)
            self._card(surface, rect, ("buy", self._key(), i), item, fmt.usd(price), "Купить", lambda it=item: self._buy(it),
                       self.game.money >= price and not self.game.over)

    def _draw_owned(self, surface):
        inv = shop.inventory(self.game.s)
        if not inv:
            self._message(surface, "Пока ничего не куплено. Имущество героя видит ECLIPSE Prime и учитывает в сюжете.")
            return
        for i, rect in self._grid(len(inv)):
            if rect.bottom < self.grid_rect.y or rect.y > self.grid_rect.bottom:
                continue
            item = inv[i]
            gain = round(item["price"] * shop.SELL_SHARE, 2)
            self._card(surface, rect, ("sell", i), item, fmt.usd(gain), "Продать", lambda i=i: self._sell(i), not self.game.over,
                       note=f"куплено за {fmt.usd(item['price'])}")
