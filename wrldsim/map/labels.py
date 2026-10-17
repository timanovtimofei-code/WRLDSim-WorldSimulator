import pygame

from ..history.flags import flag_image
from ..ui import theme
from ..ui.widgets import text_surface

SHADOW = (10, 10, 14)


def draw_labels(surface, app, camera, labels, polity_of, year, ui_rects=(), limit=300, marks=()):
    size = surface.get_size()
    screen = pygame.Rect(0, 0, *size).inflate(-20, -20)
    placed = []
    for key, _, own, main in labels[:limit]:
        p = polity_of(key)
        text = p.title
        spot = None
        for cand in (own, main):
            if cand is None:
                continue
            wx, wy, bw, bh = cand
            if not camera.visible(wx, wy):
                continue
            sx, sy = camera.to_screen(wx, wy, size)
            if not screen.collidepoint(sx, sy):
                continue
            fs = int(min(24, bw * camera.zoom * 0.8 / (0.52 * len(text)), bh * camera.zoom * 0.7))
            if fs >= 11:
                spot = (sx, sy, fs)
                break
        if spot is None:
            continue
        sx, sy, fs = spot
        img = text_surface(text, fs, theme.TEXT, True)
        shadow = text_surface(text, fs, SHADOW, True)
        flag = flag_image(app, p, year, int(fs * 1.5), fs) if fs >= 15 else None
        box = img.get_rect(center=(round(sx), round(sy)))
        mark = key in marks
        if flag:
            box.w += flag.get_width() + 6
            box.centerx = round(sx)
        if mark:
            box.w += 18
            box.centerx = round(sx)
        if box.inflate(10, 6).collidelist(placed) != -1 or box.collidelist(list(ui_rects)) != -1:
            continue
        placed.append(box.inflate(10, 6))
        x = box.x
        if mark:
            pygame.draw.circle(surface, SHADOW, (x + 7, box.centery), 7)
            pygame.draw.circle(surface, theme.ACCENT, (x + 7, box.centery), 6)
            x += 18
        if flag:
            surface.blit(flag, flag.get_rect(midleft=(x, box.centery)))
            x += flag.get_width() + 6
        surface.blit(shadow, (x + 1, box.y + 1))
        surface.blit(img, (x, box.y))
