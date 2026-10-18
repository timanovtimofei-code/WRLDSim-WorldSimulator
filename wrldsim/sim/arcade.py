# Всё состояние прохождения - JSON-совместимый словарь self.s; он же пишется в сейв. Время - минуты от старта.
import copy
import math
import random
import uuid

import numpy as np
from calendar import monthrange
from datetime import datetime, timedelta

from ..ui import format as fmt

MAX_MONEY = 1e18
CHAOS_MAX = 100
MINUTES_DAY = 1440
MAX_YEAR = 9000
MIN_YEAR = 1800


def _finite(value, lo, hi):
    value = float(value)
    if not math.isfinite(value):
        raise ValueError("не число")
    return min(max(value, lo), hi)


def _v1_to_v2(state):
    state["minute"] = int(state.pop("day", 0)) * MINUTES_DAY
    for entry in state.get("log", []):
        entry[0] *= MINUTES_DAY


def _v2_to_v3(state):
    for key in ("rob_mult", "robberies", "robbed_total", "cooldowns"):
        state.pop(key, None)
    for entry in state.get("log", []):
        if entry[2] == "rob":
            entry[2] = "event"


STATS = {
    "health": ("Здоровье", 90),
    "energy": ("Энергия", 80),
    "stress": ("Стресс", 20),
    "reputation": ("Репутация", 50),
    "influence": ("Влияние", 10),
    "stability": ("Стабильность", 60),
    "economy": ("Экономика", 60),
    "tension": ("Напряжённость", 30),
}
STAT_MAX = 100


def default_stats():
    return {key: start for key, (_, start) in STATS.items()}


REF_GDP_PC = 40000
CUSTOM_START = {"money": 20000, "salary": 100, "fame": 0, "influence": 5, "reputation": 50, "stress": 35, "heat": 0}


def _clamp(value, lo=0, hi=STAT_MAX):
    return int(round(min(max(value, lo), hi)))


def wealth_factor(gdp_pc):
    return min(max((max(gdp_pc, 300) / REF_GDP_PC) ** 0.8, 0.03), 2.5)


def starting_profile(role_start, age, gdp_pc, money_mult=1.0, income_mult=1.0):
    start = {**CUSTOM_START, **(role_start or {})}
    k = wealth_factor(gdp_pc)
    money = float(start["money"]) * k * money_mult
    economy = _clamp(20 + 25 * math.log10(max(gdp_pc, 300) / 1000), 5, 95)
    older = max(0, int(age or 40) - 25)
    stats = {
        "health": _clamp(100 - older * 0.8, 20),
        "energy": _clamp(95 - older * 0.9, 15),
        "stress": _clamp(start["stress"]),
        "reputation": _clamp(start["reputation"]),
        "influence": _clamp(start["influence"]),
        "stability": _clamp(25 + 0.6 * economy),
        "economy": economy,
        "tension": STATS["tension"][1],
    }
    return {"money": money, "income": float(start["salary"]) * k * income_mult,
            "scale": min(max(money / 1e6, 0.001), 1000.0),
            "fame": int(start["fame"]), "heat": _clamp(start["heat"]), "stats": stats,
            "hidden": [s for s in start.get("hide", []) if s in STATS]}


def _v3_to_v4(state):
    state.setdefault("stats", default_stats())
    state.setdefault("hero", {})
    state.setdefault("mode", "arcade")


def _v4_to_v5(state):
    state.setdefault("heat", 0)


def _v5_to_v6(state):
    state.setdefault("meters", {})


def _v6_to_v7(state):
    state.setdefault("cheats", [])


def _v7_to_v8(state):
    state.setdefault("income", 25000.0 if state.get("mode", "arcade") == "arcade" else 0.0)
    state.setdefault("scale", 1.0)
    state.setdefault("hidden", [])


def _v8_to_v9(state):
    state.setdefault("dossier", [])
    state.setdefault("dossier_next", 0)


def _v9_to_v10(state):
    state.setdefault("era", "modern")
    state.setdefault("polity", "generic")


def _v10_to_v11(state):
    state.setdefault("realm_on", False)


def _v11_to_v12(state):
    # Раньше все сохранённые читы были постоянными и уже объявлены ECLIPSE - они остаются прикреплёнными.
    state.setdefault("cheats_on", list(state.get("cheats", [])))
    state.setdefault("cheats_new", [])


# MIGRATIONS[n] переводит состояние версии n в n+1; новая версия - новая функция в конце.
MIGRATIONS = {1: _v1_to_v2, 2: _v2_to_v3, 3: _v3_to_v4, 4: _v4_to_v5, 5: _v5_to_v6, 6: _v6_to_v7, 7: _v7_to_v8,
              8: _v8_to_v9, 9: _v9_to_v10, 10: _v10_to_v11, 11: _v11_to_v12}
RULER_ROLES = ("president", "ruler", "monarch", "chancellor")
NEWS_KIND = {"war": "risk", "revolt": "risk", "econ": "minus", "decree": "plus", "city": "plus", "peace": "event",
             "territory": "event", "history": "event", "dip": "event", "info": "event"}
NEWS_PER_ADVANCE = 24
HEAT_MAX = 100
METERS_MAX = 6
CHEATS_MAX = 30
CHEAT_LEN = 200
STATE_VERSION = max(MIGRATIONS) + 1


def _migrate(state):
    version = state.get("version", 1)
    if version > STATE_VERSION:
        raise ValueError(f"сейв из более новой версии игры ({version})")
    while version < STATE_VERSION:
        MIGRATIONS[version](state)
        version += 1
    state["version"] = STATE_VERSION
    return state


class ArcadeGame:
    def __init__(self, cfg, rules, state):
        self.cfg = cfg
        self.rules = rules
        self.s = state
        self.rng = random.Random()
        self.names_fn = None
        self.difficulty = None
        self.world = None
        self.world_loader = None
        self._setup_calendar()

    # Начало, границы и сдвиг счёта лет - в s["calendar"]; без него старт из cfg и годы 1800..9000.
    def _setup_calendar(self):
        cal = (self.s or {}).get("calendar") or {}
        self._start = datetime.fromisoformat(cal.get("start") or self.cfg["start_date"])
        lo = datetime.fromisoformat(cal["min"]) if cal.get("min") else datetime(MIN_YEAR, 1, 1)
        hi = datetime.fromisoformat(cal["max"]) if cal.get("max") else datetime(MAX_YEAR, 1, 1)
        self.year_offset = int(cal.get("offset", 0))
        self.era_style = bool(cal.get("suffix"))
        self.show_clock = bool(cal.get("clock", True))
        self.max_minute = int((hi - self._start).total_seconds() // 60)
        self.min_minute = int((lo - self._start).total_seconds() // 60)

    def date_text(self, dt=None, clock=None):
        if self.s.get("anime"):
            return f"День {max(self.s.get('minute', 0), 0) // MINUTES_DAY + 1}"
        dt = dt or self.now
        clock = self.show_clock if clock is None else clock
        return fmt.game_date_ru(dt, self.year_offset, self.era_style, clock)

    def date_short(self, dt):
        return fmt.game_short_ru(dt, self.show_clock)

    def display_parts(self, dt):
        return dt.minute, dt.hour, dt.day, dt.month, fmt.game_year(dt, self.year_offset)

    def from_display(self, year, month, day, hour, minute):
        astro = year if year > 0 else year + 1 if year < 0 else 1
        year = astro + self.year_offset
        year = min(max(year, 1), 9999)
        day = min(day, monthrange(year, month)[1])
        return datetime(year, month, day, hour, minute)

    @property
    def min_display_year(self):
        return fmt.game_year(self._start + timedelta(minutes=self.min_minute), self.year_offset)

    @property
    def max_display_year(self):
        return fmt.game_year(self._start + timedelta(minutes=self.max_minute), self.year_offset)

    @classmethod
    def new(cls, cfg, rules, country_id, country_name, hero=None, mode_id="arcade", profile=None,
            difficulty_id=None, era_id="modern", polity_id="generic", calendar=None):
        profile = profile or starting_profile(None, (hero or {}).get("age"), REF_GDP_PC)
        state = {
            "version": STATE_VERSION,
            "mode": mode_id,
            "difficulty": difficulty_id,
            "era": era_id,
            "polity": polity_id,
            "save_id": uuid.uuid4().hex[:12],
            "country_id": country_id,
            "country_name": country_name,
            "hero": dict(hero or {}),
            "minute": 0,
            "money": float(profile["money"]),
            "income": float(profile["income"]),
            "scale": float(profile["scale"]),
            "fame": int(profile["fame"]),
            "chaos": 0,
            "heat": int(profile["heat"]),
            "stats": dict(profile["stats"]),
            "hidden": list(profile["hidden"]),
            "meters": {},
            "dossier": [],
            "dossier_next": 0,
            "cheats": [],
            "cheats_on": [],
            "cheats_new": [],
            "log": [],
        }
        if calendar:
            state["calendar"] = dict(calendar)
        game = cls(cfg, rules, state)
        game.log(cfg["intro"].format(country=country_name), "info")
        return game

    def to_dict(self):
        state = copy.deepcopy(self.s)
        if self.world is not None:
            state["realm"] = self.world.to_json()
        return state

    def load(self, state):
        state = copy.deepcopy(state)
        realm = state.pop("realm", None)
        self.s = _migrate(state)
        self._setup_calendar()
        self._restore_world(realm)

    def restore(self, state):
        state = copy.deepcopy(state)
        realm = state.pop("realm", None)
        self.s = state
        self._restore_world(realm)

    def _restore_world(self, realm):
        self.world = None
        if realm and self.world_loader:
            self.world = self.world_loader(self, realm)
            self.sync_world_stats()

    def attach_world(self, world):
        self.world = world
        self.s["realm_on"] = True
        self.sync_world_stats()

    @property
    def is_ruler(self):
        return (self.s.get("hero") or {}).get("role_id") in RULER_ROLES

    @property
    def realm_open(self):
        return self.world is not None and self.world.player >= 0 and self.is_ruler

    def world_mark(self):
        w = self.world
        if w is None or w.player < 0:
            return None
        p = w.player
        return (w.version, w.month, round(float(w.treasury[p])), round(float(w.tax[p]), 3), len(w.cities),
                len(w.wars), sum(len(v) for v in w.decrees.values()))

    def _tick_world(self):
        w = self.world
        if w is None:
            return
        w.advance(self.now)
        news = [e for e in w.pull_news() if w.relevant(e)]
        for entry in news[-NEWS_PER_ADVANCE:]:
            self.log(entry[1], NEWS_KIND.get(entry[2], "event"))
        if len(news) > NEWS_PER_ADVANCE:
            self.log(f"…и ещё событий в хронике: {len(news) - NEWS_PER_ADVANCE}.", "quiet")
        self.sync_world_stats()

    def sync_world_stats(self):
        w = self.world
        if w is None or w.player < 0:
            return
        p = w.player
        stats = self.s["stats"]
        stats["stability"] = _clamp(w.stab[p])
        atoms = w.group_atoms(p)
        if not len(atoms):
            return
        m = w.monthly(p)
        dev = float(np.average(w.dev[atoms], weights=np.maximum(w.pop[atoms], 1.0)))
        surplus = m["net"] / max(m["rev"], 1.0)
        stats["economy"] = _clamp(25 + 0.55 * dev + 40 * surplus + 100 * float(w.shock[p]))
        wars = float(w._war_counts()[p])
        stats["tension"] = _clamp(12 + 26 * min(wars, 3) + w.tension_extra)

    def at(self, minute):
        return self._start + timedelta(minutes=minute)

    @property
    def now(self):
        return self.at(self.s["minute"])

    @property
    def money(self):
        return self.s["money"]

    @property
    def remaining_minutes(self):
        return self.max_minute - self.s["minute"]

    @property
    def rewind_minutes(self):
        return max(0, self.s["minute"] - self.min_minute)

    def log(self, text, kind="info"):
        log = self.s["log"]
        log.append([self.s["minute"], text, kind])
        del log[:-self.cfg["log_size"]]

    @property
    def cheats(self):
        return self.s.setdefault("cheats", [])

    def add_cheat(self, text):
        text = " ".join(str(text).split())[:CHEAT_LEN]
        if not text or text.lower() in (c.lower() for c in self.cheats):
            return False
        self.cheats.append(text)
        for old in self.cheats[:-CHEATS_MAX]:
            self.detach_cheat(old)
        del self.cheats[:-CHEATS_MAX]
        return True

    def remove_cheat(self, index):
        if 0 <= index < len(self.cheats):
            text = self.cheats.pop(index)
            self.detach_cheat(text)
            return text
        return None

    # Буфер читов (cheats) хранит всё, что игрок ввёл в терминале; cheats_on - прикреплённые к сообщениям ECLIPSE,
    # cheats_new - прикреплённые, но ещё не отправленные (о них ECLIPSE узнает со следующим сообщением).
    @property
    def cheats_on(self):
        return self.s.setdefault("cheats_on", [])

    @property
    def cheats_new(self):
        return self.s.setdefault("cheats_new", [])

    def is_attached(self, text):
        return text.lower() in (c.lower() for c in self.cheats_on)

    def attach_cheat(self, text):
        if self.is_attached(text):
            return False
        self.cheats_on.append(text)
        self.cheats_new.append(text)
        return True

    def detach_cheat(self, text):
        """Возвращает True, если ECLIPSE уже знал об этом чите и его надо уведомить об отключении."""
        low = text.lower()
        if not self.is_attached(text):
            return False
        sent = low not in (c.lower() for c in self.cheats_new)
        self.s["cheats_on"] = [c for c in self.cheats_on if c.lower() != low]
        self.s["cheats_new"] = [c for c in self.cheats_new if c.lower() != low]
        return sent

    def _add_money(self, delta):
        before = self.s["money"]
        self.s["money"] = min(max(before + delta, 0.0), MAX_MONEY)
        return self.s["money"] - before

    def _add_stat(self, key, delta, hi=None):
        value = max(0, self.s[key] + int(delta))
        self.s[key] = min(value, hi) if hi is not None else value

    def advance_time(self, minutes):
        minutes = min(int(minutes), self.remaining_minutes)
        if minutes <= 0:
            return 0
        return self._advance_time(minutes)

    def rewind_time(self, minutes):
        minutes = min(int(minutes), self.rewind_minutes)
        if minutes <= 0:
            return 0
        self.s["minute"] -= minutes
        self.log(f"Время отмотано назад: {fmt.span_ru(minutes)}.", "info")
        return minutes

    def _advance_time(self, minutes):
        minutes = max(0, min(int(minutes), self.remaining_minutes))
        if minutes == 0:
            return 0
        old = self.s["minute"]
        self.s["minute"] += minutes
        self._add_money(self.s.get("income", 0.0) * minutes / MINUTES_DAY)
        self._tick_world()
        now = self.s["minute"]
        self.log(f"Прошло: {fmt.span_ru(minutes)}.", "info")
        days = now // MINUTES_DAY - old // MINUTES_DAY
        self._drift(days)
        self._run_events(days)
        self._run_risks(days)
        self.run_dossier(days)
        self.check_defeat()
        return minutes

    def _drift(self, days):
        days = min(days, 30)
        stats = self.s["stats"]
        stats["energy"] = min(80, stats["energy"] + 3 * days) if stats["energy"] < 80 else stats["energy"]
        stats["stress"] = max(20, stats["stress"] - days) if stats["stress"] > 20 else stats["stress"]

    def _run_events(self, days):
        # По шансу на каждые сутки, но не больше max_per_advance бросков: век не должен залить ленту.
        if days <= 0:
            return
        ev = self.cfg["events"]
        rolls = min(days, ev["max_per_advance"])
        count = sum(self.rng.random() < ev["chance_per_day"] for _ in range(rolls))
        if count == 0:
            self.log(self.rng.choice(self.cfg["quiet_days"]), "quiet")
            return
        names = self._names()
        for _ in range(count):
            self._fire_event(self.rng.choice(ev["list"]), names)

    def _names(self):
        if self.names_fn:
            return self.names_fn()
        name = self.s["country_name"]
        return {"country": name, "home": name, "region": name}

    def _fire_event(self, event, names):
        delta = event.get("money_add", 0) * self.s.get("scale", 1.0) + self.s["money"] * event.get("money_pct", 0)
        delta = self._add_money(delta)
        self._add_stat("fame", event.get("fame", 0))
        self._add_stat("chaos", event.get("chaos", 0), CHAOS_MAX)
        self._add_stat("heat", event.get("heat", 0), HEAT_MAX)
        text = event["text"].format(money=fmt.usd(abs(delta)), **names)
        self.log(text, "plus" if delta > 0 else "minus" if delta < 0 else "event")

    @property
    def risks(self):
        return self.cfg.get("risks") or {}

    def _run_risks(self, days):
        r = self.risks
        if days <= 0 or not r.get("enabled"):
            return
        stats = self.s["stats"]
        if stats["stress"] >= r["stress_limit"]:
            stats["health"] = max(0, stats["health"] - min(days, 10) * r["stress_health_per_day"])
        names = self._names()
        hits = 0
        for _ in range(min(days, r["max_rolls_per_advance"])):
            chance = r["chance_per_day"] * (1 + self.s["heat"] / r["heat_scale"])
            if self.rng.random() < chance:
                self._fire_risk(self.rng.choice(r["list"]), names)
                hits += 1
                if hits >= r["max_hits_per_advance"]:
                    break
        self.s["heat"] = max(0, self.s["heat"] - int(r["heat_decay_per_day"] * min(days, 365)))
        if stats["health"] <= 0:
            self._hospital()

    def _fire_risk(self, risk, names):
        heat = self.s["heat"]
        severity = 1 + heat / self.risks["heat_scale"]
        cost = risk.get("money_add", 0) * self.s.get("scale", 1.0) + self.s["money"] * risk.get("money_pct", 0)
        delta = self._add_money(-cost * severity)
        stats = self.s["stats"]
        for key, value in risk.get("stats", {}).items():
            if key in stats:
                stats[key] = min(max(0, stats[key] + int(round(value * (severity if value < 0 else 1)))), STAT_MAX)
        self._add_stat("fame", risk.get("fame", 0))
        self.s["heat"] = min(max(0, heat + risk.get("heat", 0)), HEAT_MAX)
        text = risk["text"].format(money=fmt.usd(abs(delta)), **names)
        self.log("▲ " + text, "risk")

    def _hospital(self):
        r = self.risks["hospital"]
        stats = self.s["stats"]
        stats["health"] = r["health_after"]
        stats["stress"] = max(stats["stress"], 40)
        lost = self._add_money(-self.s["money"] * r["money_pct"])
        self.s["minute"] = min(self.s["minute"] + r["days"] * MINUTES_DAY, self.max_minute)
        self.log(r["text"].format(days=r["days"], money=fmt.usd(abs(lost))), "risk")

    # Компромат Realism: ECLIPSE пишет улики в досье, каждый день есть шанс, что запись всплывёт;
    # шанс растёт с весом невсплывшего компромата и вниманием властей.
    @property
    def dossier_enabled(self):
        return bool((self.cfg.get("dossier") or {}).get("enabled"))

    def _diff(self, key, default):
        return (self.difficulty or {}).get(key, default)

    def _dossier_op(self, name, op):
        if not self.dossier_enabled:
            raise ValueError("досье выключено")
        dossier = self.s.setdefault("dossier", [])
        if name == "drop_dossier":
            entry_id = int(op["id"])
            before = len(dossier)
            dossier[:] = [e for e in dossier if e["id"] != entry_id or e.get("exposed")]
            if len(dossier) == before:
                raise KeyError(entry_id)
            return None
        text = " ".join(str(op["text"]).split())[:200]
        if not text:
            raise ValueError("пустая запись")
        weight = _finite(op.get("weight", 3), 1, 10) * self._diff("dossier_growth_mult", 1.0)
        self.s["dossier_next"] = self.s.get("dossier_next", 0) + 1
        dossier.append({"id": self.s["dossier_next"], "text": text, "weight": max(1, round(weight)),
                        "minute": self.s["minute"], "exposed": False})
        del dossier[:-self.cfg["dossier"]["max_entries"]]
        return None

    def dossier_score(self):
        return sum(e["weight"] for e in self.s.get("dossier", []) if not e.get("exposed"))

    def run_dossier(self, days):
        d = self.cfg.get("dossier") or {}
        if not d.get("enabled") or days <= 0 or self.over:
            return []
        hidden = [e for e in self.s.get("dossier", []) if not e.get("exposed")]
        if not hidden:
            return []
        interval = self._diff("scandal_mean_interval_days", 6)
        pressure = min(d["max_pressure"], self.dossier_score() / d["score_scale"])
        chance = ((1 - math.exp(-1 / interval)) * pressure * self._diff("inspection_chance_mult", 1.0)
                  * (0.6 + self.s.get("heat", 0) / 100))
        exposed = []
        for _ in range(min(days, 365)):
            if not hidden or len(exposed) >= d["max_per_advance"]:
                break
            if self.rng.random() < chance:
                entry = self.rng.choices(hidden, weights=[e["weight"] for e in hidden])[0]
                hidden.remove(entry)
                self._expose(entry, d)
                exposed.append(entry)
        return exposed

    def _expose(self, entry, d):
        w = entry["weight"]
        entry["exposed"] = True
        entry["exposed_at"] = self.s["minute"]
        self.s.setdefault("dossier_fresh", []).append(entry["id"])
        stats = self.s["stats"]
        self.s["heat"] = min(HEAT_MAX, self.s.get("heat", 0) + w * d["heat_per_weight"])
        stats["reputation"] = max(0, stats["reputation"] - w * d["reputation_per_weight"])
        stats["stress"] = min(STAT_MAX, stats["stress"] + w * d["stress_per_weight"])
        self.log(d["text"].format(text=entry["text"]), "risk")

    DEFEAT_REASONS = {"death": "Смерть", "prison": "Тюрьма", "resignation": "Отставка", "flight": "Бегство",
                      "bankrupt": "Банкротство", "breakdown": "Нервный срыв", "other": "Конец игры"}

    @property
    def over(self):
        return self.s.get("over")

    def check_defeat(self):
        d = self.cfg.get("defeat") or {}
        if not d.get("enabled") or self.over:
            return self.over
        stats, s = self.s["stats"], self.s
        if self.world is not None and self.is_ruler and self.world.player >= 0 \
                and not self.world.in_group(self.world.player).any():
            self._lose("other", "Ваше государство перестало существовать: земли разделены между соседями.")
        elif self.world is not None and self.is_ruler and self.world.player >= 0 \
                and self.world.stab[self.world.player] <= 3:
            self._lose("resignation", "Государство развалилось на глазах: вас свергли, а власть ушла к другим.")
        elif stats["health"] <= 0:
            self._lose("death", d["texts"]["death"])
        elif s.get("heat", 0) >= d["heat_arrest"]:
            self._lose("prison", d["texts"]["prison"])
        elif stats["stress"] >= d["stress_breakdown"]:
            self._lose("breakdown", d["texts"]["breakdown"])
        elif stats["reputation"] <= 0 and stats["influence"] <= d["influence_floor"]:
            self._lose("resignation", d["texts"]["resignation"])
        elif s["money"] <= 0 and s.get("income", 0) < 0:
            self._lose("bankrupt", d["texts"]["bankrupt"])
        return self.over

    def _lose(self, reason, text):
        self.s["over"] = {"reason": reason if reason in self.DEFEAT_REASONS else "other",
                          "text": str(text).strip()[:400] or "История героя окончена."}
        self.log("КОНЕЦ ИГРЫ: " + self.DEFEAT_REASONS[self.s["over"]["reason"]] + ". " + self.s["over"]["text"], "risk")

    OPS = ("add_money", "set_money", "add_fame", "set_fame", "add_chaos", "set_chaos", "add_heat", "set_heat",
           "add_stat", "set_stat", "add_meter", "set_meter", "drop_meter", "skip_days", "news",
           "add_income", "set_income", "show_stat", "hide_stat", "game_over", "add_dossier", "drop_dossier",
           "realm_treasury", "realm_stability", "realm_legitimacy", "realm_unrest", "realm_relation", "realm_war",
           "realm_peace", "realm_transfer", "realm_city", "realm_shock")

    def apply_ops(self, ops, tag="Чит"):
        cap = float(self.cfg["deepseek"]["max_money_per_command"])
        done = []
        for op in ops:
            if not isinstance(op, dict) or op.get("op") not in self.OPS:
                continue
            try:
                line = self._apply_op(op, cap)
            except (TypeError, ValueError, KeyError):
                line = f"пропущено: {op.get('op')}"
            if line is not None:
                done.append(line)
        for line in done:
            if tag == "Чит" or not line.startswith("пропущено"):
                self.log(f"{tag}: {line}", "cheat")
        self.check_defeat()
        return done

    def _apply_op(self, op, cap):
        name = op["op"]
        if name == "add_money":
            delta = self._add_money(_finite(op["amount"], -cap, cap))
            return f"деньги {'+' if delta >= 0 else '−'}{fmt.usd(abs(delta))}"
        if name == "set_money":
            self.s["money"] = _finite(op["amount"], 0, min(cap, MAX_MONEY))
            return f"деньги = {fmt.usd(self.s['money'])}"
        if name in ("add_fame", "set_fame"):
            value = int(_finite(op["amount"], -1e9, 1e9))
            self.s["fame"] = max(0, value if name == "set_fame" else self.s["fame"] + value)
            return f"известность = {self.s['fame']}"
        if name in ("add_chaos", "set_chaos"):
            value = int(_finite(op["amount"], -CHAOS_MAX, CHAOS_MAX))
            self.s["chaos"] = min(max(0, value if name == "set_chaos" else self.s["chaos"] + value), CHAOS_MAX)
            return f"абсурд = {self.s['chaos']}"
        if name in ("add_heat", "set_heat"):
            value = int(_finite(op["amount"], -HEAT_MAX, HEAT_MAX))
            self.s["heat"] = min(max(0, value if name == "set_heat" else self.s["heat"] + value), HEAT_MAX)
            return f"внимание = {self.s['heat']}"
        if name in ("add_stat", "set_stat"):
            key = op["stat"]
            if key not in STATS:
                raise KeyError(key)
            value = int(_finite(op["amount"], -STAT_MAX, STAT_MAX))
            stats = self.s["stats"]
            before = stats[key]
            stats[key] = min(max(0, value if name == "set_stat" else stats[key] + value), STAT_MAX)
            self._stat_to_world(key, stats[key] - before)
            hidden = self.s.setdefault("hidden", [])
            if key in hidden:
                hidden.remove(key)
            return f"{STATS[key][0].lower()} = {stats[key]}"
        if name in ("add_meter", "set_meter", "drop_meter"):
            return self._meter_op(name, op)
        if name in ("add_income", "set_income"):
            value = _finite(op["amount"], -cap, cap)
            self.s["income"] = value if name == "set_income" else self.s.get("income", 0.0) + value
            income = self.s["income"]
            return f"доход {'−' if income < 0 else ''}{fmt.usd(abs(income))}/день"
        if name in ("add_dossier", "drop_dossier"):
            return self._dossier_op(name, op)
        if name == "game_over":
            if not (self.cfg.get("defeat") or {}).get("enabled"):
                raise ValueError("поражения нет")
            if not self.over:
                self._lose(str(op.get("reason", "other")), op.get("text", ""))
            return "игра окончена"
        if name in ("show_stat", "hide_stat"):
            key = op["stat"]
            if key not in STATS:
                raise KeyError(key)
            hidden = self.s.setdefault("hidden", [])
            if name == "hide_stat" and key not in hidden:
                hidden.append(key)
            elif name == "show_stat" and key in hidden:
                hidden.remove(key)
            return f"{STATS[key][0].lower()}: {'скрыт' if name == 'hide_stat' else 'на панели'}"
        if name.startswith("realm_"):
            return self._realm_op(name, op)
        if name == "skip_days":
            days = int(_finite(op["days"], 1, 36500))
            passed = self._advance_time(days * MINUTES_DAY)
            return f"пропущено: {fmt.span_ru(passed)}"
        if name == "news":
            text = str(op["text"]).strip()[:300]
            if not text:
                raise ValueError("пустая новость")
            self.log(text, "event")
            return "новость опубликована"
        raise KeyError(name)

    def _stat_to_world(self, key, delta):
        w = self.world
        if w is None or w.player < 0 or not delta:
            return
        p = w.player
        if key == "stability":
            w.stab[p] = min(max(w.stab[p] + delta, 0.0), 100.0)
        elif key == "economy":
            w.shock[p] += delta * 0.004
        elif key == "tension":
            w.tension_extra += delta

    def _realm_op(self, name, op):
        w = self.world
        if w is None or w.player < 0:
            raise ValueError("мира нет")
        p = w.player
        rev = w.annual_revenue(p)
        if name == "realm_treasury":
            amount = _finite(op["amount"], -2.0 * rev, 2.0 * rev)
            w.treasury[p] = max(0.0, w.treasury[p] + amount)
            return f"казна {'+' if amount >= 0 else '−'}{fmt.usd(abs(amount))}"
        if name in ("realm_stability", "realm_legitimacy"):
            arr = w.stab if name == "realm_stability" else w.legit
            delta = _finite(op["amount"], -40, 40)
            arr[p] = min(max(arr[p] + delta, 0.0), 100.0)
            self.sync_world_stats()
            return f"{'стабильность' if arr is w.stab else 'легитимность'} {'+' if delta >= 0 else '−'}{abs(round(delta))}"
        if name == "realm_shock":
            w.shock[p] += _finite(op["amount"], -0.3, 0.3)
            self.sync_world_stats()
            return "потрясение хозяйства"
        if name == "realm_unrest":
            atoms = w.find_atoms(str(op["region"]), within=w.group_atoms(p))
            if not atoms:
                raise KeyError(op["region"])
            delta = _finite(op["amount"], -60, 60)
            w.unrest[atoms] = np.clip(w.unrest[atoms] + delta, 0.0, 100.0)
            return f"недовольство в «{op['region']}» {'+' if delta >= 0 else '−'}{abs(round(delta))}"
        target = w.find_polity(str(op.get("target") or op.get("to") or ""))
        if target is None or target == p:
            raise KeyError(op.get("target") or op.get("to"))
        if name == "realm_relation":
            delta = int(_finite(op["amount"], -60, 60))
            w.add_relation(p, target, delta)
            return f"отношения с {w.title(target)}: {w.relation(p, target):+d}"
        if name == "realm_war":
            ok, msg = w.declare_war(p, target, reason=str(op.get("reason", ""))[:60])
            if not ok:
                raise ValueError(msg)
            return msg
        if name == "realm_peace":
            outcome = str(op.get("outcome", "white"))
            war = w.war_between(p, target)
            if war is None:
                raise ValueError("войны нет")
            if outcome == "win":
                w._settle(war, w.root(p), demand=True)
            elif outcome == "lose":
                w._settle(war, w.root(target), demand=True)
            else:
                w._settle(war, None)
            self.sync_world_stats()
            return f"мир с {w.title(target)}"
        if name == "realm_transfer":
            src = w.find_polity(str(op.get("from"))) if op.get("from") else p
            names = op.get("regions") or []
            if src is None or not isinstance(names, list):
                raise ValueError("неясно, откуда")
            atoms = []
            for n in names[:30]:
                atoms += [a for a in w.find_atoms(str(n), within=w.own_atoms(src))]
            if not atoms:
                raise KeyError("области")
            n = w.transfer_atoms(sorted(set(atoms)), target,
                                 text=f"{w.title(src)} передаёт {w.title(target)} областей: {len(set(atoms))}.",
                                 actors=(src, target))
            self.sync_world_stats()
            return f"передано областей: {n} ({w.title(target)})"
        if name == "realm_city":
            atoms = w.find_atoms(str(op["region"]), within=w.group_atoms(p))
            if not atoms:
                raise KeyError(op["region"])
            ok, msg = w.found_city(p, atoms[0], str(op["name"]))
            if not ok:
                raise ValueError(msg)
            return msg
        raise KeyError(name)

    def _meter_op(self, name, op):
        meters = self.s.setdefault("meters", {})
        key = str(op["key"]).strip().lower()[:32]
        if not key:
            raise ValueError("пустой ключ")
        if name == "drop_meter":
            meter = meters.pop(key)
            return f"шкала «{meter['label']}» закрыта"
        meter = meters.pop(key, None)
        label = str(op.get("label") or (meter or {}).get("label") or key).strip()[:28]
        old = meter["value"] if meter else 0
        value = int(_finite(op["amount"], -STAT_MAX, STAT_MAX))
        value = min(max(0, value if name == "set_meter" else old + value), STAT_MAX)
        while len(meters) >= METERS_MAX:
            meters.pop(next(iter(meters)))
        good = op.get("good", (meter or {}).get("good"))
        meters[key] = {"label": label, "value": value}
        if isinstance(good, bool):
            meters[key]["good"] = good
        if name == "set_meter" or meter is None:
            return f"{label}: {value}"
        delta = value - old
        return f"{label} {'+' if delta >= 0 else '−'}{abs(delta)} → {value}"
