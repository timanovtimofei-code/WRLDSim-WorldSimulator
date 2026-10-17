EARTH = {
    "ACCENT": (66, 133, 244),
    "OCEAN": (10, 12, 16),
    "LAND": (44, 46, 50),
    "BORDER": (150, 156, 164),
    "COAST": (200, 206, 214),
    "ADMIN1": (78, 82, 90),
    "TEXT": (236, 236, 238),
    "GLASS_COLOR": (24, 24, 26),
    "BUTTON_BG": (40, 40, 43),
    "GOOD": (129, 201, 149),
    "WARN": (253, 214, 99),
    "DANGER": (242, 139, 130),
}
ACCENTS = {
    "Синий": (66, 133, 244), "Голубой": (78, 194, 240), "Зелёный": (52, 168, 83), "Бирюзовый": (36, 193, 166),
    "Жёлтый": (251, 188, 4), "Оранжевый": (250, 123, 23), "Красный": (234, 67, 53), "Фиолетовый": (161, 113, 247),
}
DEFAULT_ACCENT = EARTH["ACCENT"]
GLASS_MIN, GLASS_MAX = 0.2, 0.95
RADIUS_MIN, RADIUS_MAX = 0, 24
DEFAULT_GLASS = 0.55
DEFAULT_RADIUS = 14


def mix(a, b, t):
    return tuple(int(round(a[i] + (b[i] - a[i]) * t)) for i in range(3))


def _derive(c):
    ocean, land, text, accent = c["OCEAN"], c["LAND"], c["TEXT"], c["ACCENT"]
    glass, button = c["GLASS_COLOR"], c["BUTTON_BG"]
    return {
        "GRID": mix(ocean, land, 0.35),
        "LAND_DIM": mix(land, ocean, 0.4),
        "LAND_FOCUS": mix(land, text, 0.08),
        "LAND_HOVER": mix(land, accent, 0.3),
        "ACCENT_DIM": mix(accent, ocean, 0.58),
        "ADMIN1_FOCUS": mix(c["ADMIN1"], c["COAST"], 0.45),
        "COOLDOWN": mix(ocean, c["DANGER"], 0.25),
        "TEXT_DIM": mix(text, ocean, 0.38),
        "TEXT_MUTED": mix(text, ocean, 0.62),
        "PANEL_BG": mix(ocean, glass, 0.3),
        "PANEL_BORDER": mix(glass, text, 0.22),
        "BUTTON_HOVER": mix(button, accent, 0.18),
        "BUTTON_BORDER": mix(button, text, 0.55),
        "BUTTON_DISABLED": mix(button, text, 0.16),
        "BUTTON_ACTIVE": mix(button, accent, 0.5),
        "INSET_BG": mix(ocean, button, 0.3),
        "FLAG_BG": mix(ocean, land, 0.3),
        "FLAG_BORDER": mix(text, ocean, 0.12),
        "BAR_TRACK": mix(ocean, text, 0.1),
        "GLASS_SHINE": mix(glass, text, 0.4),
        "TERM_BG": mix(ocean, (0, 0, 0), 0.45),
        "TERM_FIELD": mix(ocean, button, 0.7),
        "TERM_LINE": mix(ocean, text, 0.18),
        "RAIL": mix(glass, (0, 0, 0), 0.45),
    }


def _color(value):
    if isinstance(value, (list, tuple)) and len(value) == 3:
        try:
            return tuple(int(min(max(v, 0), 255)) for v in value)
        except (TypeError, ValueError):
            return None
    return None


def accent_of(cfg):
    # Старые настройки хранили готовую тему и 12 цветов: свой акцент из них сохраняется.
    cfg = cfg or {}
    return _color(cfg.get("accent")) or _color((cfg.get("colors") or {}).get("ACCENT")) or DEFAULT_ACCENT


def resolve(cfg=None):
    cfg = cfg or {}
    colors = {**EARTH, "ACCENT": accent_of(cfg)}
    values = {**colors, **_derive(colors)}
    glass = min(max(float(cfg.get("glass", DEFAULT_GLASS)), GLASS_MIN), GLASS_MAX)
    radius = int(min(max(int(cfg.get("radius", DEFAULT_RADIUS)), RADIUS_MIN), RADIUS_MAX))
    values.update(GLASS_TINT=glass, RADIUS=radius, RADIUS_SM=max(0, round(radius * 0.7)))
    return values


def apply(cfg=None):
    # VERSION растёт при каждой смене: по нему кэши и снимки экрана узнают, что цвета устарели.
    globals().update(resolve(cfg))
    globals()["VERSION"] = globals().get("VERSION", 0) + 1


PANEL_ALPHA = 228
TOPBAR_H = 50
apply()
