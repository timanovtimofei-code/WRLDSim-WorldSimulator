# Шрифты интерфейса: Bahnschrift, а без него Segoe UI и Arial. У Bahnschrift нет файла жирного
# начертания, поэтому жирный дорисовывается (font.bold).
import pygame

_FACES = ["bahnschrift", "segoeui", "arial", "dejavusans", "liberationsans"]
_cache = {}


def get(size, bold=False):
    key = (size, bold)
    font = _cache.get(key)
    if font is None:
        path = regular = None
        for face in _FACES:
            regular = pygame.font.match_font(face)
            if regular:
                path = pygame.font.match_font(face, bold=bold)
                break
        font = pygame.font.Font(path, size)
        if bold and path == regular:
            font.bold = True
        _cache[key] = font
    return font


_MONO = ["consolas", "cascadiamono", "couriernew", "dejavusansmono"]


def mono(size):
    key = ("mono", size)
    font = _cache.get(key)
    if font is None:
        path = None
        for face in _MONO:
            path = pygame.font.match_font(face)
            if path:
                break
        font = pygame.font.Font(path, size)
        _cache[key] = font
    return font


# У Bahnschrift нет стрелок и ▲: pygame рисует вместо них пустой прямоугольник, такие символы берутся
# из запасного шрифта. Отсутствие символа видно по совпадению с незанятой точкой Юникода.
_FALLBACK = ["segoeui", "seguisym", "arial", "dejavusans"]
_NOTDEF = "\U0010FFFD"
_missing = {}


def fallback(size, bold=False):
    key = ("fallback", size, bold)
    font = _cache.get(key)
    if font is None:
        path = next((p for p in (pygame.font.match_font(f, bold=bold) for f in _FALLBACK) if p), None)
        font = _cache[key] = pygame.font.Font(path, size)
    return font


def missing(font, ch):
    if ch.isascii() or ("Ѐ" <= ch <= "ӿ"):
        return False
    key = (id(font), ch)
    res = _missing.get(key)
    if res is None:
        same = font.metrics(ch) == font.metrics(_NOTDEF)
        res = same and pygame.image.tobytes(font.render(ch, True, (255, 255, 255)), "RGBA") == \
            pygame.image.tobytes(font.render(_NOTDEF, True, (255, 255, 255)), "RGBA")
        _missing[key] = res
    return res
