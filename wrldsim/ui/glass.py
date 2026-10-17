# Вид интерфейса «Стекло»: размытый фон под панелью, линза по краю, блики. На видеокарте - шейдер в gpu.py.
import math

import numpy as np
import pygame

from . import theme


def reset_caches():
    for cache in (_panel_cache, _ctrl_cache, _fx_cache):
        cache.clear()
    _fx_bytes[0] = 0


_geo_cache = {}
_fx_cache = {}
_fx_bytes = [0]
_panel_cache = {}
_shadow_cache = {}
_ctrl_cache = {}

LENS_WIDTH = 28         # ширина фаски (толщина края стекла), px
LENS_POWER = 0.6        # увеличение под фаской: доля её ширины, на которую фон «подтягивается» от кромки внутрь
DISPERSION = (1.10, 1.0, 0.90)
SHARP = 0.2
LIGHT_DIR = (-0.55, -0.83)
LIGHT_FOLLOW = 0.45
LIGHT_RATE = 5.0
LIGHT_STEPS = 16
RIM_COLOR = (236, 240, 255)
BLUR_STEP = 4
BLUR_RADIUS = 2
SATURATION = 1.55
BRIGHTNESS = 1.14
LIFT = 5.0
GRAIN = 0.008
SHEEN = 0.02
SHADOW_PAD = 24
SHADOW_DY = 4
SHADOW_ALPHA = 60
_LUMA = np.array([0.299, 0.587, 0.114], np.float32)
_FX_BUDGET = 96 * 1024 * 1024
_light = {"x": LIGHT_DIR[0], "y": LIGHT_DIR[1], "t": None}


def _light_step(surface):
    now = pygame.time.get_ticks()
    first = _light["t"] is None
    dt = 0.0 if first else min((now - _light["t"]) / 1000.0, 0.1)
    _light["t"] = now
    w, h = surface.get_size()
    mx, my = pygame.mouse.get_pos()
    ox = min(max(mx / max(w, 1) * 2 - 1, -1.0), 1.0)
    oy = min(max(my / max(h, 1) * 2 - 1, -1.0), 1.0)
    tx = LIGHT_DIR[0] * 0.9 + ox * LIGHT_FOLLOW
    ty = LIGHT_DIR[1] * 0.9 + oy * LIGHT_FOLLOW
    n = math.hypot(tx, ty) or 1.0
    k = 1.0 if first else 1 - math.exp(-LIGHT_RATE * dt)
    _light["x"] += (tx / n - _light["x"]) * k
    _light["y"] += (ty / n - _light["y"]) * k
    ang = math.atan2(_light["y"], _light["x"])
    return int(round(ang / (2 * math.pi) * LIGHT_STEPS)) % LIGHT_STEPS


def _geometry(size, radius, lens, refract):
    key = (size, radius, lens, refract)
    geo = _geo_cache.get(key)
    if geo is not None:
        return geo
    if len(_geo_cache) > 96:
        _geo_cache.clear()
    w, h = size
    r = min(radius, w / 2, h / 2)
    gx, gy = np.mgrid[0:w, 0:h].astype(np.float32)
    px, py = gx + 0.5 - w / 2, gy + 0.5 - h / 2
    qx, qy = np.abs(px) - (w / 2 - r), np.abs(py) - (h / 2 - r)
    ox, oy = np.maximum(qx, 0), np.maximum(qy, 0)
    outer = np.hypot(ox, oy)
    depth = -(outer + np.minimum(np.maximum(qx, qy), 0) - r)
    # Нормаль берётся по скруглению не меньше ширины линзы, иначе на углах прямоугольника видны швы.
    big = max(r, min(lens, w / 2, h / 2))
    ox, oy = np.maximum(np.abs(px) - (w / 2 - big), 0), np.maximum(np.abs(py) - (h / 2 - big), 0)
    norm = np.hypot(ox, oy)
    safe = np.where(norm > 1e-4, norm, 1.0)
    nx = ox / safe * np.sign(px)
    ny = oy / safe * np.sign(py)
    inside = np.clip(depth + 0.5, 0, 1).astype(np.float32)

    fb = np.nonzero((depth > -0.5) & (depth < lens))
    geo = {"lens": lens, "inside": inside, "alpha": (inside * 255).astype(np.uint8), "fb": fb,
           "depth": depth[fb], "nx": nx[fb], "ny": ny[fb], "inside_b": inside[fb]}

    if refract:
        t = np.clip(depth / lens, 0, 1)
        bx, by = np.nonzero((depth >= 0) & (depth < lens))
        tb = t[bx, by]
        shift = lens * LENS_POWER * (1 - tb) ** 2
        margin = int(np.ceil(lens * LENS_POWER * max(DISPERSION))) + 2
        sx, sy = [], []
        for k in DISPERSION:
            sx.append(np.rint(bx + margin - nx[bx, by] * shift * k).astype(np.intp))
            sy.append(np.rint(by + margin - ny[bx, by] * shift * k).astype(np.intp))
        geo.update(band=(bx, by), src=(sx, sy), margin=margin,
                   sharp=(SHARP * (1 - tb) ** 1.4).astype(np.float32)[:, None])

        rng = np.random.default_rng(7)
        grain_c = rng.integers(0, 2, (w, h)).astype(np.float32) * 255
        sheen_a = np.full((w, h), SHEEN, np.float32)
        a_tot = GRAIN + sheen_a * (1 - GRAIN)
        col = (grain_c * GRAIN + 255 * sheen_a * (1 - GRAIN)) / a_tot
        tex = pygame.Surface(size, pygame.SRCALPHA)
        rgb = pygame.surfarray.pixels3d(tex)
        rgb[:] = col.astype(np.uint8)[:, :, None]
        pygame.surfarray.pixels_alpha(tex)[:] = (a_tot * inside * 255).astype(np.uint8)
        del rgb
        geo["tex"] = tex
    _geo_cache[key] = geo
    return geo


def _fx(size, radius, lens, step, strength=1.0, color=RIM_COLOR, panel=False):
    key = (size, radius, lens, step, strength, color, panel)
    fx = _fx_cache.get(key)
    if fx is not None:
        return fx
    if _fx_bytes[0] > _FX_BUDGET:
        _fx_cache.clear()
        _fx_bytes[0] = 0
    geo = _geometry(size, radius, lens, panel)
    ang = step * 2 * math.pi / LIGHT_STEPS
    lx, ly = math.cos(ang), math.sin(ang)
    d, nx, ny = geo["depth"], geo["nx"], geo["ny"]
    facing = nx * lx + ny * ly
    spec = np.maximum(np.clip(facing, 0, 1) ** 1.6, 0.6 * np.clip(-facing, 0, 1) ** 1.6)
    t = np.clip(d / 1.5, 0, 1)
    line = 1 - t * t * (3 - 2 * t)
    inner = np.exp(-(((d - 2.4) / 1.1) ** 2))
    fres = np.clip(1 - d / lens, 0, 1) ** 3
    shine = np.clip((line * (0.12 + 0.78 * spec) + inner * 0.14 * spec + fres * (0.01 + 0.08 * spec)) * strength,
                    0, 1)
    band = min(max(lens * 0.75, 4.0), 12.0)
    rt = np.clip((d - 0.8) / band, 0, 1)
    s1, s2 = np.clip(rt / 0.15, 0, 1), np.clip((rt - 0.45) / 0.55, 0, 1)
    rw = s1 * s1 * (3 - 2 * s1) * (1 - s2 * s2 * (3 - 2 * s2))
    hue = rt + 0.06 * np.arctan2(ny, nx)
    rain = 0.62 + 0.38 * np.cos(6.28318 * (np.array([0.0, 0.33, 0.67], np.float32)[None, :] - hue[:, None] * 0.85))
    ra = np.clip(rw * (0.05 + 0.05 * spec) * min(strength, 1.0), 0, 1)
    total = shine + ra * (1 - shine)
    safe = np.where(total > 1e-6, total, 1.0)[:, None]
    col = (np.array(color, np.float32)[None, :] * shine[:, None] + rain * 255 * (ra * (1 - shine))[:, None]) / safe
    bx, by = geo["fb"]
    fx = pygame.Surface(size, pygame.SRCALPHA)
    rgb = pygame.surfarray.pixels3d(fx)
    rgb[bx, by] = np.clip(col, 0, 255).astype(np.uint8)
    del rgb
    alpha = pygame.surfarray.pixels_alpha(fx)
    alpha[bx, by] = (total * geo["inside_b"] * 255).astype(np.uint8)
    del alpha
    _fx_cache[key] = fx
    _fx_bytes[0] += size[0] * size[1] * 4
    return fx


def _grade(rgb, sat, bright, lift):
    g = rgb.astype(np.float32)
    gray = (g @ _LUMA)[..., None]
    return np.clip((gray + (g - gray) * sat) * bright + lift, 0, 255).astype(np.uint8)


def _grade_params(lum):
    k = min(max(lum / 110.0, 0.0), 1.0)
    return SATURATION, 1.0 + (BRIGHTNESS - 1.0) * (1 - k), LIFT * (1 - 0.6 * k), k


def _blurred(region):
    w, h = region.get_size()
    small = pygame.transform.smoothscale(region, (max(1, w // BLUR_STEP), max(1, h // BLUR_STEP)))
    arr = pygame.surfarray.pixels3d(small)
    lum = float(arr[::2, ::2].mean())
    sat, bright, lift, _ = _grade_params(lum)
    arr[:] = _grade(arr, sat, bright, lift)
    del arr
    small = pygame.transform.gaussian_blur(small, BLUR_RADIUS, True)
    return pygame.transform.smoothscale(small, (w, h)), lum


def _shadow_image(size, radius):
    key = (size, radius)
    img = _shadow_cache.get(key)
    if img is None:
        if len(_shadow_cache) > 24:
            _shadow_cache.clear()
        w, h = size
        pad, s = SHADOW_PAD, 4
        full = (w + 2 * pad, h + 2 * pad)
        mask = pygame.Surface((max(1, full[0] // s), max(1, full[1] // s)))
        mask.fill((0, 0, 0))
        pygame.draw.rect(mask, (255, 255, 255), pygame.Rect(pad // s, pad // s, max(1, w // s), max(1, h // s)),
                         border_radius=radius // s)
        mask = pygame.transform.gaussian_blur(mask, 2, True)
        mask = pygame.transform.smoothscale(mask, full)
        img = pygame.Surface(full, pygame.SRCALPHA)
        pygame.surfarray.pixels_alpha(img)[:] = (pygame.surfarray.pixels3d(mask)[:, :, 0].astype(np.float32)
                                                 * (SHADOW_ALPHA / 255)).astype(np.uint8)
        _shadow_cache[key] = img
    return img


def _draw_shadow(surface, rect, radius):
    img = _shadow_image(rect.size, radius)
    pad = SHADOW_PAD
    W, H = img.get_size()
    ox, oy = rect.x - pad, rect.y - pad + SHADOW_DY
    top = pad - SHADOW_DY
    bottom = top + rect.h
    parts = [pygame.Rect(0, 0, W, top), pygame.Rect(0, bottom, W, H - bottom),
             pygame.Rect(0, top, pad, rect.h), pygame.Rect(pad + rect.w, top, W - pad - rect.w, rect.h)]
    r = int(min(radius, rect.w // 2, rect.h // 2))
    if r:
        parts += [pygame.Rect(pad, top, r, r), pygame.Rect(pad + rect.w - r, top, r, r),
                  pygame.Rect(pad, bottom - r, r, r), pygame.Rect(pad + rect.w - r, bottom - r, r, r)]
    for part in parts:
        if part.w > 0 and part.h > 0:
            surface.blit(img, (ox + part.x, oy + part.y), part)


def panel(surface, rect, alpha, border, radius, gpu=None):
    lens = min(LENS_WIDTH, max(6, min(rect.w, rect.h) // 2 - 2))
    rim = border if border not in (None, theme.PANEL_BORDER, theme.BUTTON_BORDER) else None
    color = RIM_COLOR if rim is None else tuple(int(a * 0.6 + b * 0.4) for a, b in zip(RIM_COLOR, rim))
    if gpu is not None and surface is gpu.ui:
        _light_step(surface)
        gpu.set_light((_light["x"], _light["y"]))
        gpu.glass(rect, radius, alpha, color, lens)
        return
    geo = _geometry(rect.size, radius, lens, True)
    m = geo["margin"]
    area = rect.inflate(2 * m, 2 * m)
    region = pygame.Surface(area.size)
    region.blit(surface, (-area.x, -area.y))
    _draw_shadow(surface, rect, radius)

    # Фон под панелью обычно не меняется между кадрами: сверяем его уменьшенную копию и берём готовое стекло.
    digest = pygame.transform.smoothscale(region, (max(1, area.w // 6), max(1, area.h // 6))).get_buffer().raw
    cache_key = (rect.topleft, rect.size, radius, alpha)
    entry = _panel_cache.get(cache_key)
    if entry is None or entry[0] != digest:
        blurred, lum = _blurred(region)
        glass = blurred.subsurface(pygame.Rect(m, m, rect.w, rect.h)).copy().convert_alpha()
        bx, by = geo["band"]
        sx, sy = geo["src"]
        sat, bright, lift, k = _grade_params(lum)
        blur_px = pygame.surfarray.pixels3d(blurred)
        raw_px = pygame.surfarray.pixels3d(region)
        soft = np.stack([blur_px[sx[c], sy[c], c] for c in range(3)], axis=1).astype(np.float32)
        sharp = _grade(np.stack([raw_px[sx[c], sy[c], c] for c in range(3)], axis=1), sat, bright, lift)
        del blur_px, raw_px
        mixed = soft + (sharp.astype(np.float32) - soft) * geo["sharp"]
        dst = pygame.surfarray.pixels3d(glass)
        dst[bx, by] = mixed.astype(np.uint8)
        del dst
        tint = pygame.Surface(rect.size, pygame.SRCALPHA)
        tint.fill((*theme.GLASS_COLOR, min(255, int(alpha * theme.GLASS_TINT * (0.8 + 0.5 * k)))))
        glass.blit(tint, (0, 0))
        pygame.surfarray.pixels_alpha(glass)[:] = geo["alpha"]
        if len(_panel_cache) > 32:
            _panel_cache.clear()
        entry = _panel_cache[cache_key] = [digest, glass, None, None]

    final_key = (_light_step(surface), color)
    if entry[2] != final_key:
        final = entry[1].copy()
        final.blit(geo["tex"], (0, 0))
        final.blit(_fx(rect.size, radius, lens, final_key[0], 1.0, color, True), (0, 0))
        entry[2], entry[3] = final_key, final
    surface.blit(entry[3], rect.topleft)


def _control_image(size, radius, lens, aq, lq, step, enabled, inset):
    key = (size, radius, aq, lq, step, enabled, inset)
    img = _ctrl_cache.get(key)
    if img is not None:
        return img
    if len(_ctrl_cache) > 400:
        _ctrl_cache.clear()
    geo = _geometry(size, radius, lens, False)
    w, h = size
    a_t, l_t = aq / 6.0, lq / 6.0
    if inset:
        base, base_a = np.array(theme.TERM_BG, np.float32), 0.42
    else:
        base, base_a = np.array(theme.TEXT, np.float32), 0.11 + 0.07 * l_t
    tint = np.array(theme.BUTTON_ACTIVE, np.float32)
    tint_a = 0.6 + 0.25 * l_t
    body_a = base_a + (tint_a - base_a) * a_t
    color = base + (tint - base) * min(1.0, a_t * tint_a / max(body_a, 1e-3))
    yy = (np.arange(h, dtype=np.float32) / max(h - 1, 1))[None, :, None]
    shade = 10 * (1 - yy) - 6 * yy
    rgb = np.clip(color[None, None, :] + shade, 0, 255).astype(np.uint8) * np.ones((w, 1, 1), np.uint8)
    if not enabled:
        body_a *= 0.55
    img = pygame.Surface(size, pygame.SRCALPHA)
    pygame.surfarray.pixels3d(img)[:] = rgb
    pygame.surfarray.pixels_alpha(img)[:] = (geo["inside"] * min(body_a, 1.0) * 255).astype(np.uint8)
    img.blit(_fx(size, radius, lens, step, (0.85 + 0.3 * l_t) if enabled else 0.4, RIM_COLOR), (0, 0))
    _ctrl_cache[key] = img
    return img


def control(surface, rect, radius, *, hover=0.0, press=0.0, accent=0.0, enabled=True, inset=False,
            refract=False, gpu=None):
    if rect.w < 8 or rect.h < 8:
        return
    grow = round(hover * 1.0 + press * 3.0) if enabled else 0
    r = rect.inflate(2 * grow, 2 * grow)
    radius = max(0, min(radius, r.w // 2, r.h // 2))
    if refract and gpu is not None and surface is gpu.ui:
        _light_step(surface)
        gpu.set_light((_light["x"], _light["y"]))
        a = min(max(accent, 0.0), 1.0)
        gpu.glass(r, radius, 150 if enabled else 110, RIM_COLOR, min(16, max(6, min(r.w, r.h) // 2 - 1)),
                  shadow=0.7, accent=(theme.BUTTON_ACTIVE, 0.62 * a) if a > 0.01 else None)
        return
    lens = min(12, max(6, min(r.w, r.h) // 2 - 1))
    aq = round(min(max(accent, 0.0), 1.0) * 6)
    lq = round(min(max(max(hover * 0.6, press), 0.0), 1.0) * 6)
    img = _control_image(r.size, radius, lens, aq, lq, _light_step(surface), enabled, inset)
    surface.blit(img, r.topleft)


