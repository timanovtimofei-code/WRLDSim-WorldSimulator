import json

from . import config

DISPLAY_MODES = {
    "windowed": "Оконный",
    "borderless": "Оконный без рамок",
    "fullscreen": "Полный экран",
}
DEFAULTS = {"display": "windowed", "gpu": True,
            "eclipse_font": 30,
            "theme": {},
            "ui_style": "flat",
            "globe": True}
UI_STYLES = ("flat", "glass")
ECLIPSE_FONT_MIN, ECLIPSE_FONT_MAX = 16, 30
SETTINGS_FILE = config.ROOT / "settings.json"


def load():
    data = dict(DEFAULTS)
    try:
        saved = json.loads(SETTINGS_FILE.read_text(encoding="utf-8-sig"))
        if isinstance(saved, dict) and saved.get("display") in DISPLAY_MODES:
            data["display"] = saved["display"]
        if isinstance(saved, dict) and isinstance(saved.get("gpu"), bool):
            data["gpu"] = saved["gpu"]
        if isinstance(saved, dict) and isinstance(saved.get("eclipse_font"), int):
            data["eclipse_font"] = min(max(saved["eclipse_font"], ECLIPSE_FONT_MIN), ECLIPSE_FONT_MAX)
        if isinstance(saved, dict) and isinstance(saved.get("globe"), bool):
            data["globe"] = saved["globe"]
        if isinstance(saved, dict) and saved.get("ui_style") in UI_STYLES:
            data["ui_style"] = saved["ui_style"]
        if isinstance(saved, dict) and isinstance(saved.get("theme"), dict):
            data["theme"] = saved["theme"]
    except (OSError, ValueError):
        pass
    return data


def save(data):
    try:
        SETTINGS_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        pass
