import math

TIERS = ("Низы", "Простой люд", "Средний класс", "Верхний слой", "Элита", "Вершина")
TIER_EDGES = (0.12, 0.26, 0.36, 0.46, 0.62)

INDICATORS = (("Деньги", "money"), ("Доход", "income"), ("Влияние", "influence"), ("Слава", "fame"),
              ("Репутация", "reputation"), ("Риск", "risk"))


def _log_scale(value, lo, hi):
    return min(max((math.log10(max(value, lo)) - math.log10(lo)) / (math.log10(hi) - math.log10(lo)), 0.0), 1.0)


def levels(start):
    return {"money": _log_scale(start["money"], 1e3, 3e9), "income": _log_scale(start["salary"], 10, 3e5),
            "influence": start["influence"] / 100, "fame": start["fame"] / (start["fame"] + 60),
            "reputation": start["reputation"] / 100, "risk": min(start["heat"] / 50, 1.0)}


def status_score(start):
    lv = levels(start)
    return 0.40 * lv["influence"] + 0.30 * lv["money"] + 0.15 * lv["income"] + 0.15 * lv["fame"]


def tier(start):
    score = status_score(start)
    return sum(score >= edge for edge in TIER_EDGES)


def by_status(roles):
    return sorted(roles, key=lambda r: status_score(r["start"]))
