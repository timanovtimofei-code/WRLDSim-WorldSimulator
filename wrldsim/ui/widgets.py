import math

import pygame

from . import fonts, glass, theme

_text_cache = {}
_DEFAULT = object()
GPU = None
STYLES = {"flat": "Плоский", "glass": "Стекло"}
STYLE = "flat"
FLAT_RADIUS = 3


def set_style(style):
    global STYLE
    STYLE = style if style in STYLES else "flat"
    reset_theme_caches()


def radius_for(radius):
    return min(radius, FLAT_RADIUS) if STYLE == "flat" else radius


def reset_theme_caches():
    for cache in (_flat_panel_cache, _flat_ctrl_cache, _card_glow, _fill_cache, _round_cache):
        cache.clear()
    glass.reset_caches()


def text_surface(text, size=16, color=None, bold=False):
    color = color or theme.TEXT
    key = (text, size, color, bold)
    img = _text_cache.get(key)
    if img is None:
        if len(_text_cache) > 1024:
            _text_cache.clear()
        img = _render(text, size, color, bold)
        _text_cache[key] = img
    return img


def _render(text, size, color, bold):
    font = fonts.get(size, bold)
    if not any(fonts.missing(font, ch) for ch in text):
        return font.render(text, True, color)
    alt = fonts.fallback(size, bold)
    runs, cur, cur_alt = [], "", None
    for ch in text:
        use_alt = fonts.missing(font, ch)
        if cur and use_alt != cur_alt:
            runs.append((cur, cur_alt))
            cur = ""
        cur, cur_alt = cur + ch, use_alt
    runs.append((cur, cur_alt))
    asc = max(font.get_ascent(), alt.get_ascent())
    imgs = [((alt if a else font).render(t, True, color), (alt if a else font).get_ascent()) for t, a in runs]
    h = max(asc - a + img.get_height() for img, a in imgs)
    out = pygame.Surface((sum(img.get_width() for img, _ in imgs), max(h, font.get_height())), pygame.SRCALPHA)
    x = 0
    for img, a in imgs:
        out.blit(img, (x, asc - a))
        x += img.get_width()
    return out


def draw_text(surface, text, pos, size=16, color=None, bold=False, anchor="topleft"):
    img = text_surface(text, size, color, bold)
    rect = img.get_rect(**{anchor: pos})
    surface.blit(img, rect)
    return rect


def draw_spaced(surface, text, pos, size, color=None, bold=True, spacing=0.3, anchor="center"):
    chars = [text_surface(ch, size, color, bold) for ch in text]
    gap = int(size * spacing)
    width = sum(c.get_width() for c in chars) + gap * (len(chars) - 1)
    rect = pygame.Rect(0, 0, width, max(c.get_height() for c in chars))
    setattr(rect, anchor, pos)
    x = rect.x
    for c in chars:
        surface.blit(c, (x, rect.y))
        x += c.get_width() + gap
    return rect


# Экраны каждый кадр переносят и обрезают одни и те же строки, поэтому результаты кэшируются.
_wrap_cache = {}
_ellipsize_cache = {}
_TEXT_CACHE_MAX = 4096


def wrap(text, width, size=16, bold=False):
    key = (text, width, size, bold)
    lines = _wrap_cache.get(key)
    if lines is not None:
        return lines
    font = fonts.get(size, bold)
    lines = []
    for paragraph in text.split("\n"):
        line = ""
        for word in paragraph.split():
            candidate = f"{line} {word}".strip()
            if line and font.size(candidate)[0] > width:
                lines.append(line)
                line = word
            else:
                line = candidate
        lines.append(line)
    if len(_wrap_cache) > _TEXT_CACHE_MAX:
        _wrap_cache.clear()
    lines = _wrap_cache[key] = tuple(lines)
    return lines


def ellipsize(text, width, font):
    key = (text, width, id(font))
    out = _ellipsize_cache.get(key)
    if out is not None:
        return out
    out = text
    if font.size(text)[0] > width:
        while out and font.size(out + "…")[0] > width:
            out = out[:-1]
        out = out.rstrip() + "…"
    if len(_ellipsize_cache) > _TEXT_CACHE_MAX:
        _ellipsize_cache.clear()
    _ellipsize_cache[key] = out
    return out


def draw_paragraph(surface, text, topleft, width, size=16, color=None, bold=False, line_gap=3):
    x, y = topleft
    height = fonts.get(size, bold).get_linesize()
    for line in wrap(text, width, size, bold):
        draw_text(surface, line, (x, y), size, color, bold)
        y += height + line_gap
    return y


_fill_cache = {}


def fill_round(surface, rect, color, alpha=255, radius=None):
    # pygame.draw.rect не умеет полупрозрачность, поэтому заливка рисуется на отдельной поверхности.
    if rect.w < 2 or rect.h < 2:
        return
    radius = radius_for(theme.RADIUS_SM if radius is None else radius)
    key = (rect.size, color, alpha, radius)
    img = _fill_cache.get(key)
    if img is None:
        if len(_fill_cache) > 256:
            _fill_cache.clear()
        img = pygame.Surface(rect.size, pygame.SRCALPHA)
        pygame.draw.rect(img, (*color, alpha), img.get_rect(), border_radius=radius)
        _fill_cache[key] = img
    surface.blit(img, rect.topleft)


_flat_panel_cache = {}
_flat_ctrl_cache = {}


def _rounded_mask(size, radius):
    mask = pygame.Surface(size, pygame.SRCALPHA)
    pygame.draw.rect(mask, (255, 255, 255, 255), mask.get_rect(), border_radius=radius)
    return mask


def _flat_panel(surface, rect, alpha, border, radius):
    radius = radius_for(radius)
    bg = theme.GLASS_COLOR
    a = 255 if alpha >= 220 else alpha + 30
    if a >= 220 and rect.w >= 40 and rect.h >= 30:
        glass._draw_shadow(surface, rect, radius)
    line = border if border is not None else theme.mix(bg, theme.TEXT, 0.07)
    key = (rect.size, radius, a, line, bg)
    img = _flat_panel_cache.get(key)
    if img is None:
        if len(_flat_panel_cache) > 64:
            _flat_panel_cache.clear()
        img = pygame.Surface(rect.size, pygame.SRCALPHA)
        pygame.draw.rect(img, (*bg, a), img.get_rect(), border_radius=radius)
        pygame.draw.rect(img, (*line, 255), img.get_rect(), 1, border_radius=radius)
        _flat_panel_cache[key] = img
    surface.blit(img, rect.topleft)


def draw_panel(surface, rect, alpha=None, border=_DEFAULT, radius=None):
    if rect.w < 8 or rect.h < 8 or not rect.colliderect(surface.get_rect()):
        return
    alpha = theme.PANEL_ALPHA if alpha is None else alpha
    border = theme.PANEL_BORDER if border is _DEFAULT else border
    radius = theme.RADIUS if radius is None else radius
    if STYLE == "glass":
        glass.panel(surface, rect, alpha, border, radius, GPU)
        return
    _flat_panel(surface, rect, alpha, None if border in (theme.PANEL_BORDER, theme.BUTTON_BORDER) else border, radius)


def _q(v, steps=8):
    return round(min(max(v, 0.0), 1.0) * steps)


SWEEP_STEPS = 24
SWEEP_SLANT = 0.7


def sweep_of(hover, accent):
    return max(hover, min(max((accent - 0.6) / 0.4, 0.0), 1.0))


def text_on(fill):
    acc = theme.ACCENT
    light = 0.299 * acc[0] + 0.587 * acc[1] + 0.114 * acc[2] > 165
    return (18, 18, 20) if fill > 0.55 and light else theme.TEXT


def _flat_control_image(size, radius, hq, pq, aq, enabled, inset, sq=0):
    key = (size, radius, hq, pq, aq, enabled, inset, sq, theme.VERSION)
    img = _flat_ctrl_cache.get(key)
    if img is not None:
        return img
    if len(_flat_ctrl_cache) > 600:
        _flat_ctrl_cache.clear()
    h_, p_, a_ = hq / 8, pq / 8, aq / 8
    w, h = size
    base, text, accent = theme.BUTTON_BG, theme.TEXT, theme.ACCENT
    if inset:
        top = bottom = theme.mix(theme.OCEAN, (0, 0, 0), 0.30)
        border = theme.mix(theme.mix(base, text, 0.28), accent, a_)
    else:
        lo, hi = 0.07 + 0.07 * h_, 0.19 + 0.07 * h_
        if p_ > 0.5:
            lo, hi = 0.12, 0.04
        top, bottom = theme.mix(base, text, hi), theme.mix(base, text, lo)
        if a_ and not sq:
            top, bottom = theme.mix(top, accent, 0.45 * a_), theme.mix(bottom, accent, 0.38 * a_)
        border = theme.mix(theme.mix(base, text, 0.32 + 0.08 * h_), accent, 0.7 * a_)
    if not enabled:
        top, bottom = theme.mix(top, base, 0.6), theme.mix(bottom, base, 0.6)
        border = theme.mix(border, base, 0.55)
    column = pygame.Surface((1, h), pygame.SRCALPHA)
    for y in range(h):
        column.set_at((0, y), (*theme.mix(top, bottom, y / max(h - 1, 1)), 255 if enabled else 200))
    img = pygame.transform.scale(column, size)
    f = sq / SWEEP_STEPS
    if f > 0 and enabled and not inset:
        slant = h * SWEEP_SLANT
        x_top = f * (w + slant)
        fill = theme.mix(accent, (0, 0, 0), 0.25) if p_ > 0.5 else accent
        pygame.draw.polygon(img, (*fill, 255), [(0, 0), (x_top, 0), (x_top - slant, h), (0, h)])
        if f < 1:
            shine = theme.mix(accent, (255, 255, 255), 0.55)
            pygame.draw.line(img, (*shine, 255), (x_top, 0), (x_top - slant, h), 2)
        border = theme.mix(accent, text, 0.25) if f >= 1 else border
    img.blit(_rounded_mask(size, radius), (0, 0), special_flags=pygame.BLEND_RGBA_MIN)
    if not inset and enabled and f <= 0:
        pygame.draw.line(img, (*theme.mix(top, text, 0.14), 255), (radius + 1, 1), (w - radius - 2, 1))
    pygame.draw.rect(img, (*border, 255), img.get_rect(), 1, border_radius=radius)
    _flat_ctrl_cache[key] = img
    return img


_round_cache = {}


def draw_round_button(surface, rect, *, hover=False, press=False, active=False, enabled=True):
    d = min(rect.w, rect.h)
    key = (d, hover, press, active, enabled, theme.VERSION)
    img = _round_cache.get(key)
    if img is None:
        if len(_round_cache) > 64:
            _round_cache.clear()
        pad = 6
        img = pygame.Surface((d + 2 * pad, d + 2 * pad), pygame.SRCALPHA)
        c = d // 2 + pad
        for i in range(pad, 0, -1):
            pygame.draw.circle(img, (0, 0, 0, int(26 * (1 - i / (pad + 1)))), (c, c + 2), d // 2 + i)
        base = theme.mix(theme.GLASS_COLOR, theme.TEXT, 0.16 if hover and enabled else 0.04 if press else 0.08)
        pygame.draw.circle(img, (*base, 235 if enabled else 160), (c, c), d // 2)
        if active:
            pygame.draw.circle(img, (*theme.ACCENT, 255), (c, c), d // 2, 2)
        _round_cache[key] = img
    surface.blit(img, img.get_rect(center=rect.center))


def draw_glass_control(surface, rect, radius, *, hover=0.0, press=0.0, accent=0.0, enabled=True, inset=False,
                       refract=False, sweep=True):
    if rect.w < 8 or rect.h < 8:
        return
    if STYLE == "glass":
        glass.control(surface, rect, radius, hover=hover, press=press, accent=accent, enabled=enabled, inset=inset,
                      refract=refract, gpu=GPU)
        return
    radius = max(0, min(radius_for(radius), rect.w // 2, rect.h // 2))
    sq = _q(sweep_of(hover, accent), SWEEP_STEPS) if sweep and not inset and enabled else 0
    surface.blit(_flat_control_image(rect.size, radius, _q(hover), _q(press), _q(accent), enabled, inset, sq),
                 rect.topleft)


def _approach(value, target, rate, dt):
    value += (target - value) * (1 - math.exp(-rate * dt))
    return target if abs(target - value) < 0.004 else value


class Glow:
    def __init__(self):
        self.hover = self.press = self.accent = 0.0
        self._t = None

    def step(self, hover, press, accent):
        now = pygame.time.get_ticks()
        if self._t is None:
            self.hover, self.press, self.accent = hover, press, accent
        else:
            dt = min((now - self._t) / 1000.0, 0.1)
            self.hover = _approach(self.hover, hover, 13, dt)
            self.press = _approach(self.press, press, 28, dt)
            self.accent = _approach(self.accent, accent, 14, dt)
        self._t = now
        return self.hover, self.press, self.accent


_card_glow = {}


def draw_glass_card(surface, rect, key, *, hovered, selected, radius=None, refract=False):
    radius = theme.RADIUS if radius is None else radius
    glow = _card_glow.setdefault(key, Glow())
    h, p, a = glow.step(1.0 if hovered else 0.0, 0.0, 1.0 if selected else 0.0)
    draw_glass_control(surface, rect, radius, hover=h * 0.6, press=p, accent=a * 0.6, refract=refract, sweep=False)


def draw_tooltip(surface, lines, pos):
    imgs = [text_surface(t, s, c, b) for t, c, s, b in lines]
    w = max(i.get_width() for i in imgs) + 20
    h = sum(i.get_height() for i in imgs) + 12
    rect = pygame.Rect(pos[0] + 16, pos[1] + 18, w, h)
    rect.clamp_ip(surface.get_rect())
    draw_panel(surface, rect, alpha=240, border=None)
    y = rect.y + 6
    for img in imgs:
        surface.blit(img, (rect.x + 10, y))
        y += img.get_height()


class NumberField:
    def __init__(self, hi, size=20, lo=0):
        self.hi = hi
        self.lo = lo
        self.size = size
        self.text = str(max(lo, 0))
        self.focused = False
        self.fresh = False
        self.rect = pygame.Rect(0, 0, 0, 0)
        self._glow = Glow()

    @property
    def value(self):
        try:
            v = int(self.text)
        except ValueError:
            v = 0
        return min(max(v, self.lo), self.hi)

    @value.setter
    def value(self, v):
        self.text = str(min(max(int(v), self.lo), self.hi))

    def focus(self):
        self.focused = True
        self.fresh = True

    def blur(self):
        self.focused = False
        self.fresh = False
        self.text = str(self.value)

    def step(self, delta):
        self.value = self.value + delta
        self.fresh = True

    def handle_event(self, event):
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            inside = self.rect.collidepoint(event.pos)
            if inside and not self.focused:
                self.focus()
            elif not inside and self.focused:
                self.blur()
            return inside
        big = 10 if pygame.key.get_mods() & pygame.KMOD_SHIFT else 1
        if event.type == pygame.MOUSEWHEEL and self.rect.collidepoint(pygame.mouse.get_pos()):
            self.step(big if event.y > 0 else -big if event.y < 0 else 0)
            return True
        if not self.focused:
            return False
        if event.type == pygame.TEXTINPUT:
            if event.text == "-" and self.lo < 0:
                neg = not self.text.startswith("-")
                digits = self.text.lstrip("-")
                self.text = ("-" if neg else "") + ("" if self.fresh else digits)
                self.fresh = False
            elif event.text.isdigit():
                neg = self.text.startswith("-") and not self.fresh
                base = "" if self.fresh else self.text.lstrip("-").lstrip("0")
                self.fresh = False
                digits = (base + event.text)[:len(str(self.hi))]
                v = -int(digits) if neg else int(digits)
                # Ниже lo не зажимаем во время ввода: «1» на пути к «19» при lo=18.
                self.text = str(min(v, self.hi) if v >= 0 else max(v, self.lo))
                if neg and v == 0:
                    self.text = "-"
            return True
        if event.type == pygame.KEYDOWN:
            if event.key in (pygame.K_BACKSPACE, pygame.K_DELETE):
                self.text = "" if self.fresh else self.text[:-1]
                self.fresh = False
            elif event.key == pygame.K_UP:
                self.step(big)
            elif event.key == pygame.K_DOWN:
                self.step(-big)
            else:
                return False
            return True
        return False

    def draw(self, surface):
        hovered = self.rect.collidepoint(pygame.mouse.get_pos())
        hot = self.focused or hovered
        active = self.value != max(self.lo, 0) or self.focused
        h, p, a = self._glow.step(1.0 if hovered else 0.0, 0.0, 1.0 if self.focused else 0.6 if hot else 0.35 if active else 0.0)
        draw_glass_control(surface, self.rect, 12, hover=h, press=p, accent=a, sweep=False)
        shown = self.text if self.focused else str(self.value)
        img = text_surface(shown, self.size, theme.ACCENT if active else theme.TEXT_DIM, bold=True)
        rect = img.get_rect(center=self.rect.center)
        if self.focused and self.fresh and shown:
            fill_round(surface, rect.inflate(10, 2), theme.ACCENT, 70, 6)
        surface.blit(img, rect)
        if self.focused and not self.fresh and pygame.time.get_ticks() % 1000 < 500:
            x = rect.right + 2 if shown else self.rect.centerx
            pygame.draw.line(surface, theme.TEXT, (x, rect.y + 3), (x, rect.bottom - 3))


class TextInput:
    def __init__(self, size=16, max_len=300):
        self.size = size
        self.max_len = max_len
        self.text = ""
        self.rect = pygame.Rect(0, 0, 0, 0)
        self.radius = 0
        self.caret = True
        self._blink = 0.0
        self._glow = Glow()

    def handle_event(self, event):
        if event.type == pygame.TEXTINPUT:
            self.text = (self.text + event.text)[:self.max_len]
        elif event.type == pygame.KEYDOWN:
            if event.key == pygame.K_BACKSPACE:
                self.text = self.text[:-1]
            elif event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                text, self.text = self.text.strip(), ""
                return text or None
            elif event.key == pygame.K_v and event.mod & pygame.KMOD_CTRL:
                try:
                    self.text = (self.text + pygame.scrap.get_text().replace("\n", " "))[:self.max_len]
                except Exception:
                    pass
        return None

    def update(self, dt):
        self._blink = (self._blink + dt) % 1.0

    def draw(self, surface, placeholder=""):
        radius = self.radius or theme.RADIUS_SM
        h, p, a = self._glow.step(0.0, 0.0, 0.5 if self.caret else 0.0)
        draw_glass_control(surface, self.rect, radius, hover=h, press=p, accent=a, inset=True)
        font = fonts.get(self.size)
        inner = self.rect.inflate(-20 - self.radius // 2, 0)
        img = text_surface(self.text, self.size) if self.text else text_surface(placeholder, self.size, theme.TEXT_MUTED)
        offset = max(0, img.get_width() - inner.w + 4) if self.text else 0
        prev = surface.get_clip()
        surface.set_clip(inner)
        y = inner.centery - img.get_height() // 2
        surface.blit(img, (inner.x - offset, y))
        if self.caret and self._blink < 0.5:
            cx = inner.x + (font.size(self.text)[0] - offset if self.text else 0) + 1
            pygame.draw.line(surface, theme.TEXT, (cx, y + 3), (cx, y + img.get_height() - 3))
        surface.set_clip(prev)


class RoundButton:
    PAD = 9

    def __init__(self, text, on_click=None, *, size=15):
        self.text = text
        self.on_click = on_click
        self.size = size
        self.enabled = True
        self.rect = pygame.Rect(0, 0, 0, 0)
        self._pressed = False
        self._glow = Glow()

    def height(self, width):
        return len(wrap(self.text, width - 2 * (self.PAD + 6), self.size)) * fonts.get(self.size).get_linesize() + 2 * self.PAD

    def handle_event(self, event):
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if self.rect.collidepoint(event.pos):
                self._pressed = self.enabled
                return True
        elif event.type == pygame.MOUSEBUTTONUP and event.button == 1:
            was_pressed, self._pressed = self._pressed, False
            if was_pressed and self.rect.collidepoint(event.pos):
                if self.on_click:
                    self.on_click()
                return True
        return False

    def draw(self, surface):
        hovered = self.enabled and self.rect.collidepoint(pygame.mouse.get_pos())
        color = theme.TEXT if self.enabled else theme.TEXT_MUTED
        radius = min(18, self.rect.h // 2)
        h, p, a = self._glow.step(1.0 if hovered else 0.0, 1.0 if self._pressed and hovered else 0.0,
                                  0.6 if hovered and STYLE == "glass" else 0.0)
        draw_glass_control(surface, self.rect, radius, hover=h, press=p, accent=a, enabled=self.enabled)
        if self.enabled and STYLE == "flat":
            color = text_on(sweep_of(h, a))
        lines = wrap(self.text, self.rect.w - 2 * (self.PAD + 6), self.size)
        line_h = fonts.get(self.size).get_linesize()
        y = self.rect.centery - line_h * len(lines) // 2
        for line in lines:
            draw_text(surface, line, (self.rect.centerx, y), self.size, color, anchor="midtop")
            y += line_h


class Button:
    def __init__(self, text, on_click=None, *, size=18, bold=False, enabled=True, selected=False, glass=False):
        self.text = text
        self.glass = glass
        self.on_click = on_click
        self.size = size
        self.bold = bold
        self.enabled = enabled
        self.selected = selected
        self.rect = pygame.Rect(0, 0, 0, 0)
        self._pressed = False
        self._glow = Glow()

    def handle_event(self, event):
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if self.rect.collidepoint(event.pos):
                self._pressed = self.enabled
                return True
        elif event.type == pygame.MOUSEBUTTONUP and event.button == 1:
            was_pressed, self._pressed = self._pressed, False
            if was_pressed and self.rect.collidepoint(event.pos):
                if self.on_click:
                    self.on_click()
                return True
        return False

    def draw(self, surface):
        hovered = self.enabled and self.rect.collidepoint(pygame.mouse.get_pos())
        color = theme.TEXT if self.enabled else theme.TEXT_MUTED
        accent = 1.0 if self.selected else 0.6 if hovered and not self.glass and STYLE == "glass" else 0.0
        h, p, a = self._glow.step(1.0 if hovered else 0.0, 1.0 if self._pressed and hovered else 0.0,
                                  accent if self.enabled else 0.0)
        radius = self.rect.h // 2 if self.glass else theme.RADIUS_SM
        draw_glass_control(surface, self.rect, radius, hover=h, press=p, accent=a, enabled=self.enabled,
                           refract=self.glass)
        if self.enabled and STYLE == "flat":
            color = text_on(sweep_of(h, a))
        draw_text(surface, self.text, self.rect.center, self.size, color, self.bold, anchor="center")


TRASH_COLOR = (232, 64, 68)


def draw_trash(surface, rect, hot):
    color = (255, 96, 96) if hot else TRASH_COLOR
    if hot:
        fill_round(surface, rect, TRASH_COLOR, 46, 6)
    cx, top = rect.centerx, rect.y + 6
    pygame.draw.line(surface, color, (rect.x + 6, top + 3), (rect.right - 7, top + 3), 2)
    pygame.draw.rect(surface, color, (cx - 3, top, 6, 3), 1)
    body = pygame.Rect(rect.x + 8, top + 6, rect.w - 16, rect.bottom - top - 12)
    pygame.draw.rect(surface, color, body, 2, border_bottom_left_radius=3, border_bottom_right_radius=3)
    for dx in (-3, 0, 3):
        pygame.draw.line(surface, color, (cx + dx, body.y + 4), (cx + dx, body.bottom - 4), 1)
