# Значки рейки и кнопок карты, нарисованные линиями: значковые шрифты Windows есть не везде.
import math

import pygame

_cache = {}
SS = 3   # рисуем крупнее и уменьшаем, чтобы линии были сглажены


def _line(s, color, a, b, w):
    pygame.draw.line(s, color, a, b, w)
    for p in (a, b):
        pygame.draw.circle(s, color, p, max(1, w // 2))


def _menu(s, c, n, w):
    for y in (0.28, 0.5, 0.72):
        _line(s, c, (n * 0.18, n * y), (n * 0.82, n * y), w)


def _chat(s, c, n, w):
    body = pygame.Rect(n * 0.12, n * 0.16, n * 0.76, n * 0.54)
    pygame.draw.rect(s, c, body, w, border_radius=int(n * 0.14))
    pygame.draw.polygon(s, c, [(n * 0.28, n * 0.66), (n * 0.28, n * 0.88), (n * 0.48, n * 0.68)])
    for x in (0.32, 0.5, 0.68):
        pygame.draw.circle(s, c, (n * x, n * 0.43), w * 0.75)


def _news(s, c, n, w):
    page = pygame.Rect(n * 0.14, n * 0.16, n * 0.72, n * 0.68)
    pygame.draw.rect(s, c, page, w, border_radius=int(n * 0.06))
    pygame.draw.rect(s, c, pygame.Rect(n * 0.24, n * 0.28, n * 0.22, n * 0.18))
    for y in (0.3, 0.42):
        _line(s, c, (n * 0.54, n * y), (n * 0.76, n * y), w)
    for y in (0.56, 0.7):
        _line(s, c, (n * 0.24, n * y), (n * 0.76, n * y), w)


def _stats(s, c, n, w):
    for i, h in enumerate((0.34, 0.6, 0.46)):
        x = n * (0.2 + i * 0.22)
        pygame.draw.rect(s, c, pygame.Rect(x, n * (0.82 - h), n * 0.15, n * h), border_radius=int(n * 0.03))
    _line(s, c, (n * 0.12, n * 0.86), (n * 0.88, n * 0.86), w)


def _terminal(s, c, n, w):
    box = pygame.Rect(n * 0.1, n * 0.18, n * 0.8, n * 0.64)
    pygame.draw.rect(s, c, box, w, border_radius=int(n * 0.08))
    _line(s, c, (n * 0.24, n * 0.38), (n * 0.38, n * 0.5), w)
    _line(s, c, (n * 0.38, n * 0.5), (n * 0.24, n * 0.62), w)
    _line(s, c, (n * 0.46, n * 0.64), (n * 0.7, n * 0.64), w)


def _realm(s, c, n, w):
    pts = [(0.14, 0.72), (0.14, 0.32), (0.34, 0.5), (0.5, 0.22), (0.66, 0.5), (0.86, 0.32), (0.86, 0.72)]
    pygame.draw.lines(s, c, False, [(n * x, n * y) for x, y in pts], w)
    _line(s, c, (n * 0.14, n * 0.72), (n * 0.86, n * 0.72), w)
    _line(s, c, (n * 0.16, n * 0.84), (n * 0.84, n * 0.84), w)


def _shop(s, c, n, w):
    bag = pygame.Rect(n * 0.16, n * 0.34, n * 0.68, n * 0.52)
    pygame.draw.rect(s, c, bag, w, border_radius=int(n * 0.08))
    pygame.draw.arc(s, c, pygame.Rect(n * 0.32, n * 0.12, n * 0.36, n * 0.44), 0, math.pi, w)


def _settings(s, c, n, w):
    cx = cy = n / 2
    for i in range(8):
        a = i * math.pi / 4
        _line(s, c, (cx + math.cos(a) * n * 0.22, cy + math.sin(a) * n * 0.22),
              (cx + math.cos(a) * n * 0.38, cy + math.sin(a) * n * 0.38), int(w * 1.6))
    pygame.draw.circle(s, c, (cx, cy), n * 0.26, w)
    pygame.draw.circle(s, c, (cx, cy), n * 0.1, w)


def _home(s, c, n, w):
    pygame.draw.lines(s, c, False, [(n * 0.14, n * 0.5), (n * 0.5, n * 0.18), (n * 0.86, n * 0.5)], w)
    pygame.draw.lines(s, c, False, [(n * 0.24, n * 0.42), (n * 0.24, n * 0.84), (n * 0.76, n * 0.84), (n * 0.76, n * 0.42)], w)
    pygame.draw.rect(s, c, pygame.Rect(n * 0.43, n * 0.6, n * 0.14, n * 0.24))


def _plus(s, c, n, w):
    _line(s, c, (n * 0.22, n * 0.5), (n * 0.78, n * 0.5), w)
    _line(s, c, (n * 0.5, n * 0.22), (n * 0.5, n * 0.78), w)


def _minus(s, c, n, w):
    _line(s, c, (n * 0.22, n * 0.5), (n * 0.78, n * 0.5), w)


def _close(s, c, n, w):
    _line(s, c, (n * 0.26, n * 0.26), (n * 0.74, n * 0.74), w)
    _line(s, c, (n * 0.74, n * 0.26), (n * 0.26, n * 0.74), w)


def _undo(s, c, n, w):
    pygame.draw.arc(s, c, pygame.Rect(n * 0.24, n * 0.26, n * 0.56, n * 0.5), -math.pi / 2, math.pi / 2, w)
    _line(s, c, (n * 0.52, n * 0.76), (n * 0.3, n * 0.76), w)
    _line(s, c, (n * 0.52, n * 0.26), (n * 0.22, n * 0.26), w)
    pygame.draw.polygon(s, c, [(n * 0.12, n * 0.26), (n * 0.3, n * 0.12), (n * 0.3, n * 0.4)])


def _clock(s, c, n, w):
    pygame.draw.circle(s, c, (n / 2, n / 2), n * 0.36, w)
    _line(s, c, (n * 0.5, n * 0.5), (n * 0.5, n * 0.28), w)
    _line(s, c, (n * 0.5, n * 0.5), (n * 0.66, n * 0.58), w)


def _globe(s, c, n, w):
    r = n * 0.36
    pygame.draw.circle(s, c, (n / 2, n / 2), r, w)
    pygame.draw.ellipse(s, c, pygame.Rect(n / 2 - r * 0.45, n / 2 - r, r * 0.9, 2 * r), w)
    _line(s, c, (n / 2 - r, n / 2), (n / 2 + r, n / 2), w)


_DRAW = {"menu": _menu, "chat": _chat, "news": _news, "stats": _stats, "terminal": _terminal, "realm": _realm,
         "shop": _shop, "settings": _settings, "home": _home, "plus": _plus, "minus": _minus, "close": _close,
         "undo": _undo, "clock": _clock, "globe": _globe}
NAMES = tuple(_DRAW)


def image(name, size, color):
    key = (name, size, tuple(color))
    img = _cache.get(key)
    if img is None:
        n = size * SS
        big = pygame.Surface((n, n), pygame.SRCALPHA)
        _DRAW[name](big, (*color, 255), n, max(SS, round(n * 0.075)))
        img = _cache[key] = pygame.transform.smoothscale(big, (size, size))
    return img


def draw(surface, name, rect, color, size=None):
    size = size or min(rect.w, rect.h)
    img = image(name, size, color)
    surface.blit(img, img.get_rect(center=rect.center))
