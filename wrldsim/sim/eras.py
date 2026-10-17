# datetime не знает годов до н. э., поэтому игра сдвигает счёт на BC_OFFSET лет (кратно 400, чтобы
# не сбить високосные годы) и пересчитывает обратно при выводе.
import json
from datetime import datetime

from .. import config

ERAS_FILE = config.DATA_DIR / "eras.json"
ERA_ORDER = ["ancient", "imperial", "modern"]
DEFAULT_ERA = "modern"
GENERIC = "generic"
BC_OFFSET = 4000
MAX_YEAR = 9000


def merge(base, over):
    result = dict(base)
    for key, value in over.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = merge(result[key], value)
        else:
            result[key] = value
    return result


def astro(year):
    return year if year > 0 else year + 1


def year_text(year):
    return f"{-year} г. до н. э." if year < 0 else f"{year} г."


class Eras:
    def __init__(self, path=ERAS_FILE):
        with open(path, encoding="utf-8") as f:
            self.data = json.load(f)["eras"]
        for era_id, era in self.data.items():
            era["id"] = era_id
            era["polities"], era["generic"] = [], None
            poly_path = path.with_name(f"polities_{era_id}.json")
            if poly_path.exists():
                with open(poly_path, encoding="utf-8") as f:
                    raw = json.load(f)
                era["polities"] = raw.get("polities", [])
                era["generic"] = raw.get("generic")
        self._by_id = {e: {p["id"]: p for p in era["polities"]} for e, era in self.data.items()}

    @property
    def order(self):
        return [e for e in ERA_ORDER if e in self.data]

    def era(self, era_id):
        return self.data.get(era_id) or self.data[DEFAULT_ERA]

    def restricted(self, era_id):
        return bool(self.era(era_id).get("restricted"))

    def sample_names(self, era_id, limit=8):
        era = self.era(era_id)
        names = [p["short"] for p in era["polities"]]
        return names[:limit]

    def generic(self, country_name):
        spec = self.data["modern"]["generic"]
        return {"id": GENERIC, "name": country_name, "short": country_name, "generic": True, "span": spec["span"],
                "wealth": spec.get("wealth"), "starts": spec["starts"], "coin": "", "regions": [],
                "capital": "", "government": "", "ruler": "", "blurb": ""}

    def polity(self, era_id, polity_id, country_name=""):
        if polity_id == GENERIC or era_id == "modern" and polity_id not in self._by_id.get(era_id, {}):
            return self.generic(country_name)
        found = self._by_id.get(era_id, {}).get(polity_id)
        return found if found else self.generic(country_name)

    def options(self, era_id, country_id, country_name):
        on_map = sorted((p for p in self.era(era_id)["polities"] if country_id in p["map"]),
                        key=lambda p: p["span"][0])
        if self.restricted(era_id):
            return on_map
        return [self.generic(country_name), *on_map]

    def pin_counts(self, era_id):
        if not self.restricted(era_id):
            return None
        counts = {}
        for p in self.era(era_id)["polities"]:
            for cid in p["map"]:
                counts[cid] = counts.get(cid, 0) + 1
        return counts

    def polity_names(self, era_id, exclude=None):
        names = [p["short"] for p in self.era(era_id)["polities"] if p["id"] != exclude]
        return names

    def calendar(self, polity, start):
        lo, hi = polity["span"]
        lo_a, hi_a = astro(lo), astro(hi)
        offset = BC_OFFSET if lo_a < 1 else 0
        start_dt = datetime(astro(start["year"]) + offset, start["month"], start["day"])
        min_dt = min(datetime(lo_a + offset, 1, 1), start_dt)
        if hi >= MAX_YEAR:
            max_dt = datetime(MAX_YEAR, 1, 1)
        else:
            max_dt = max(datetime(hi_a + offset, 12, 31, 23, 59), start_dt)
        return {"start": start_dt.isoformat(), "min": min_dt.isoformat(), "max": max_dt.isoformat(),
                "offset": offset}

    def roles(self, era_id, polity, year, base_roles):
        era = self.era(era_id)
        if era.get("roles"):
            return era["roles"]
        mins = era.get("role_min_year") or {}
        excluded = set(polity.get("exclude_roles") or [])
        return [r for r in base_roles if r["id"] not in excluded and year >= mins.get(r["id"], 0)]

    def currency(self, era_id):
        cur = self.era(era_id).get("currency") or {}
        return cur.get("prefix", "$"), cur.get("suffix", "")

    def shop_categories(self, era_id, default):
        return self.era(era_id).get("shop_categories") or default

    def game_cfg(self, base, era_id, mode_id):
        era = self.era(era_id)
        over = {}
        intro = era.get(f"intro_{mode_id}")
        if intro:
            over["intro"] = intro
        if era.get("quiet_days"):
            over["quiet_days"] = era["quiet_days"]
        if era.get("events"):
            over["events"] = {"list": era["events"]}
        if era.get("risks"):
            over["risks"] = era["risks"]
        if era.get("defeat_texts"):
            over["defeat"] = {"texts": era["defeat_texts"]}
        return merge(base, over) if over else base

    def prompt_block(self, era_id, polity, start, home_name=""):
        era = self.era(era_id)
        try:
            text = (config.ROOT / era["prompt_file"]).read_text(encoding="utf-8-sig").strip()
        except (OSError, KeyError):
            text = ""
        lines = [f"ВЫБРАННАЯ ЭПОХА: {era['name'].title()} ({era['period']})."]
        if polity.get("generic"):
            lines.append(f"Государство: {polity['name']} (современная страна). Год старта: {start['year']}.")
        else:
            lines.append(f"Государство игрока: {polity['name']} (на современной карте это {home_name or 'эта территория'}). "
                         f"Годы существования: {year_text(polity['span'][0])} - {year_text(polity['span'][1])}.")
            for label, key in (("Столица", "capital"), ("Строй", "government"), ("Высший титул", "ruler"),
                               ("Валюта и расчёты", "coin")):
                if polity.get(key):
                    lines.append(f"{label}: {polity[key]}.")
            if polity.get("blurb"):
                lines.append(polity["blurb"])
            lines.append(f"Точка старта: {start['label']} ({year_text(start['year'])}). {start['note']}")
        return (text + "\n\n" if text else "") + "\n".join(lines)


def validate(eras, country_ids):
    problems = []
    for era_id, era in eras.data.items():
        seen = set()
        for p in era["polities"]:
            where = f"{era_id}/{p['id']}"
            if p["id"] in seen:
                problems.append(f"{where}: повтор id")
            seen.add(p["id"])
            lo, hi = p["span"]
            if lo >= hi:
                problems.append(f"{where}: span")
            for cid in p["map"]:
                if cid not in country_ids:
                    problems.append(f"{where}: нет страны {cid}")
            if not p["starts"]:
                problems.append(f"{where}: нет стартов")
            for s in p["starts"]:
                if not lo <= s["year"] <= hi:
                    problems.append(f"{where}: старт {s['year']} вне span")
                try:
                    eras.calendar(p, s)
                except ValueError as e:
                    problems.append(f"{where}: старт {s['year']}: {e}")
    return problems
