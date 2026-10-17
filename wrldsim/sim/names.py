import json
import random

from .. import config

NAMES_FILE = config.DATA_DIR / "names.json"


def _words(text):
    return [w.replace("_", " ") for w in (text or "").split()]


def _weights(spec):
    if isinstance(spec, str):
        return {spec: 1}
    if isinstance(spec, list):
        return dict.fromkeys(spec, 1)
    return dict(spec)


RU_EXCEPTIONS = {"Михаил": ("Михайлович", "Михайловна"), "Павел": ("Павлович", "Павловна"),
                 "Пётр": ("Петрович", "Петровна"), "Илья": ("Ильич", "Ильинична"),
                 "Никита": ("Никитич", "Никитична"), "Лев": ("Львович", "Львовна"),
                 "Яков": ("Яковлевич", "Яковлевна"), "Фома": ("Фомич", "Фоминична"),
                 "Кузьма": ("Кузьмич", "Кузьминична"), "Лука": ("Лукич", "Лукинична")}
UA_EXCEPTIONS = {"Микола": ("Миколайович", "Миколаївна"), "Григорій": ("Григорович", "Григорівна")}


def _patronymic_ru(father, female):
    if father in RU_EXCEPTIONS:
        return RU_EXCEPTIONS[father][female]
    if father in ("Дмитрий", "Георгий"):
        male = father[:-2] + "иевич"
    elif father.endswith("ий"):
        male = father[:-2] + "ьевич"
    elif father.endswith(("й", "ь")):
        male = father[:-1] + "евич"
    elif father.endswith(("а", "я")):
        male = father[:-1] + "ич"
    else:
        male = father + ("евич" if father[-1] in "жчшщц" else "ович")
    if not female:
        return male
    return male[:-2] + "на" if male.endswith("вич") else male + "на"


def _patronymic_ua(father, female):
    if father in UA_EXCEPTIONS:
        return UA_EXCEPTIONS[father][female]
    if father.endswith("о"):
        male = father[:-1] + "ович"
    else:
        male = father + "ович"
    if not female:
        return male
    if father.endswith("ь"):
        return father[:-1] + "івна"
    return male[:-6] + "іївна" if male.endswith("ійович") else male[:-4] + "івна"


PATRONYMICS = {"ru": _patronymic_ru, "ua": _patronymic_ua}


class Names:
    def __init__(self, path=NAMES_FILE):
        with open(path, encoding="utf-8") as f:
            raw = json.load(f)
        rules = {k: sorted(map(tuple, v), key=lambda r: -len(r[0])) for k, v in raw["fem_rules"].items()}
        self.cultures = {}
        for cid, c in raw["cultures"].items():
            male, female = _words(c.get("male")), _words(c.get("female"))
            self.cultures[cid] = {
                "label": c["label"], "male": male, "female": female,
                "surname": male if c.get("surname_from") == "male" else _words(c.get("surname")),
                "surname_f": _words(c.get("surname_f")), "rules": rules.get(c.get("fem"), ()),
                "middle": {False: _words(c.get("middle_m") or c.get("middle")),
                           True: _words(c.get("middle_f") or c.get("middle"))},
                "patronymic": PATRONYMICS.get(c.get("patronymic")),
                "fmt": {False: c.get("fmt", "{g} {s}"), True: c.get("fmt_f") or c.get("fmt", "{g} {s}")},
            }
        self.country_map = {}
        for cid, ids in raw["countries"].items():
            self.country_map.update(dict.fromkeys(ids.split(), cid))
        self.country_map.update(raw["mixed"])
        self.regions = raw["regions"]
        self.polities = raw["polities"]
        self.default = raw["default"]

    def pool(self, country_id, region="", polity_id=None):
        spec = self.polities.get(polity_id) if polity_id else None
        if spec is None:
            spec = self._region_spec(country_id, (region or "").lower())
        if spec is None:
            spec = self.country_map.get(country_id, self.default)
        weights = {c: w for c, w in _weights(spec).items() if c in self.cultures}
        return weights or {self.default: 1}

    def _region_spec(self, country_id, region):
        if not region:
            return None
        for rule in self.regions.get(country_id, ()):
            if any(m in region for m in rule.get("match", ())) or region in (n.lower() for n in rule.get("is", ())):
                return rule["cultures"]
        return None

    def describe(self, pool):
        labels = [self.cultures[c]["label"] for c, _ in sorted(pool.items(), key=lambda kv: -kv[1])]
        text = " · ".join(labels[:3])
        return text[:1].upper() + text[1:]

    def suggest(self, pool, gender, count, rng=None):
        rng = rng or random.Random()
        cultures, weights = list(pool), list(pool.values())
        result, seen = [], set()
        for _ in range(count * 30):
            if len(result) >= count:
                break
            cid = rng.choices(cultures, weights)[0]
            female = gender == "female" or (gender == "other" and rng.random() < 0.5)
            name = self._name(self.cultures[cid], female, rng)
            if name and name not in seen:
                seen.add(name)
                result.append({"name": name, "culture": self.cultures[cid]["label"] if len(pool) > 1 else None})
        return result

    @staticmethod
    def _feminize(surname, rules):
        for src, dst in rules:
            if surname.endswith(src):
                return surname[:-len(src)] + dst
        return surname

    def _name(self, c, female, rng):
        fmt = c["fmt"][female]
        given_pool = c["female" if female else "male"]
        parts = {"g": rng.choice(given_pool) if given_pool else "", "p": "", "m": "", "s": "", "s2": ""}
        if "{p}" in fmt and c["patronymic"]:
            parts["p"] = c["patronymic"](rng.choice(c["male"]), female)
        if "{m}" in fmt and c["middle"][female]:
            parts["m"] = rng.choice(c["middle"][female])
        if "{s}" in fmt and c["surname"]:
            if female and c["surname_f"]:
                parts["s"] = rng.choice(c["surname_f"])
            else:
                surname = rng.choice(c["surname"])
                parts["s"] = self._feminize(surname, c["rules"]) if female else surname
        if "{s2}" in fmt and len(c["surname"]) > 1:
            parts["s2"] = rng.choice([s for s in c["surname"] if s != parts["s"]])
        return " ".join(fmt.format(**parts).split())
