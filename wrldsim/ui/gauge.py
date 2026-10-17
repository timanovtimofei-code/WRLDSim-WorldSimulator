import pygame

from . import theme
from .widgets import fill_round

GRADIENT = ((0.0, (96, 8, 16)), (0.2, (200, 30, 36)), (0.4, (240, 110, 40)), (0.55, (245, 190, 60)),
            (0.7, (220, 230, 80)), (0.85, (140, 225, 100)), (1.0, (170, 255, 190)))


def gradient(t):
    t = min(max(t, 0.0), 1.0)
    for (t0, c0), (t1, c1) in zip(GRADIENT, GRADIENT[1:]):
        if t <= t1:
            k = (t - t0) / (t1 - t0)
            return tuple(int(c0[i] + (c1[i] - c0[i]) * k) for i in range(3))
    return GRADIENT[-1][1]


def draw_gauge(surface, rect, frac, good_high=True):
    fill_round(surface, rect, (255, 255, 255), 28, rect.h // 2)
    frac = min(max(frac, 0.0), 1.0)
    if frac > 0:
        color = gradient(frac if good_high else 1 - frac)
        fill_round(surface, pygame.Rect(rect.x, rect.y, max(rect.h, round(rect.w * frac)), rect.h), color, 255,
                   rect.h // 2)


PYRAMID_STEPS, PYRAMID_BAR, PYRAMID_GAP, PYRAMID_H = 6, 4, 2, 14
PYRAMID_W = PYRAMID_STEPS * PYRAMID_BAR + (PYRAMID_STEPS - 1) * PYRAMID_GAP


def draw_pyramid(surface, pos, tier):
    x, y = pos
    for i in range(PYRAMID_STEPS):
        h = max(3, round(PYRAMID_H * (i + 1) / PYRAMID_STEPS))
        rect = pygame.Rect(x + i * (PYRAMID_BAR + PYRAMID_GAP), y + PYRAMID_H - h, PYRAMID_BAR, h)
        on = i <= tier
        fill_round(surface, rect, theme.ACCENT if on else theme.TEXT, 255 if on else 40, 1)
    return pygame.Rect(x, y, PYRAMID_W, PYRAMID_H)
