import json

DIFFICULTY_PARAMS = [
    ("start_money_mult", "Стартовые деньги", "mult"),
    ("inspection_chance_mult", "Шанс проверки", "mult"),
    ("scandal_mean_interval_days", "Скандал", "days"),
    ("dossier_growth_mult", "Рост досье", "mult"),
    ("price_mult", "Цены", "mult"),
    ("bribe_fail_chance", "Срыв взятки", "pct"),
    ("ally_betrayal_mult", "Предательство союзников", "mult"),
]


def load_modes(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _format(value, kind):
    if kind == "mult":
        return "×" + f"{value:g}".replace(".", ",")
    if kind == "days":
        return f"~ раз в {value:g} дн."
    if kind == "pct":
        return f"{round(value * 100)}%"
    return str(value)


def describe_difficulty(difficulty):
    return [(label, _format(difficulty[key], kind))
            for key, label, kind in DIFFICULTY_PARAMS if key in difficulty]
