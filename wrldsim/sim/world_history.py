import json
import math

import numpy as np

from .. import config

PENDING, APPLIED, SKIPPED, CLAIM, THREAT = 0, 1, 2, 3, 4
CLAIM_MONTHS = 72


def _interp_log(x, xs, ys):
    if len(xs) == 1:
        return ys[0]
    for i in range(len(xs) - 1):
        if x <= xs[i + 1] or i == len(xs) - 2:
            t = (x - xs[i]) / (xs[i + 1] - xs[i])
            t = min(max(t, -0.35), 1.35)
            return math.exp(math.log(ys[i]) * (1 - t) + math.log(ys[i + 1]) * t)
    return ys[-1]


class HistoryMixin:
    @staticmethod
    def resolve_player(hist, snap, game_id, map_ids, iso2=""):
        own = hist.owner[snap]
        present = np.bincount(own, minlength=len(hist.polities))
        area = np.bincount(own, weights=hist.area, minlength=len(hist.polities))
        if game_id:
            cands = [p.index for p in hist.polities if p.game == game_id and present[p.index]]
            if cands:
                return max(cands, key=lambda i: area[i])
        if iso2:
            cands = [p.index for p in hist.polities if p.iso2 == iso2 and present[p.index]]
            if cands:
                return cands[0]
        mask = np.isin(hist.atom_country, np.asarray(list(map_ids), int))
        if mask.any():
            votes = np.bincount(own[mask], weights=hist.area[mask], minlength=len(hist.polities))
            votes[0] = 0
            if votes.max() > 0:
                return int(votes.argmax())
        return -1

    @classmethod
    def create(cls, hist, cfg, era_id, year, month_idx, lands, player, city_data, year_offset=0, known_wealth=None,
               history_mode=None):
        w = cls(hist, cfg, era_id, year_offset)
        if history_mode in cfg["history_modes"]:
            w.history_mode = history_mode
        snap = max([i for i, y in enumerate(hist.years) if y <= year], default=0)
        w.owner[:] = hist.owner[snap]
        w.overlord[:w.P0] = hist.top[snap]
        w.month = month_idx
        w._seed_atoms(lands, year, known_wealth or {})
        w._seed_polities()
        w.player = int(player)
        w.rng.seed()
        w._init_cities(city_data, year)
        w._build_drift(snap, year, month_idx)
        w.recompute_effects()
        w.rebuild_city_effects()
        w._prime()
        return w

    def _hist_total(self, continent, year):
        table = self.cfg["population_millions"].get(continent)
        if not table:
            return None
        xs = sorted(int(k) for k in table)
        ys = [table[str(x)] * 1e6 for x in xs]
        return _interp_log(year, xs, ys)

    def _seed_atoms(self, lands, year, known):
        h, ec = self.hist, self.ec
        A = self.A
        cont = np.array([lands["continent"][c] for c in h.atom_country])
        lat = -h.anchors[:, 1].astype(np.float64)
        hab = np.exp(-((np.abs(lat) - 32.0) / 24.0) ** 2) * 0.9 + 0.1
        wgt = np.maximum(h.area.astype(np.float64), 1e-6) * np.cos(np.radians(lat)) * hab
        pop = np.zeros(A)
        for c in np.unique(h.atom_country):
            idx = np.nonzero(h.atom_country == c)[0]
            pop[idx] = lands["pop"][c] * wgt[idx] / wgt[idx].sum()
        if self.era != "modern":
            modern = {}
            for c, name in enumerate(lands["continent"]):
                modern[name] = modern.get(name, 0.0) + float(lands["pop"][c])
            for name in np.unique(cont):
                total = self._hist_total(str(name), year)
                if total and modern.get(str(name)):
                    pop[cont == name] *= total / modern[str(name)]
        self.pop[:] = np.maximum(pop, 50.0)
        if self.era == "modern":
            gpc = np.array([lands["gdp_pc"][c] for c in h.atom_country], np.float64)
        else:
            mult = np.array([self.cfg["continent_wealth"].get(str(c), 0.8) for c in cont])
            gpc = ec["gdp_base"] * mult * (1.0 + 0.9 * min(max((year - ec["start_year"]) / 200.0, 0.0), 1.5))
        for p, v in known.items():
            gpc[self.owner == p] = v
        self.gpc[:] = np.maximum(gpc, 200.0)
        rel = self.gpc / max(ec["gdp_base"], 1.0)
        if self.era == "modern":
            dev = 20.0 + 25.0 * np.log10(np.maximum(self.gpc, 300.0) / 1000.0)
        else:
            dev = 10.0 + 32.0 * rel + 0.12 * (year - ec["start_year"])
        self.dev[:] = np.clip(dev + self.nrng.normal(0, 4.0, A), 5.0, 92.0)
        self.unrest[:] = np.clip(self.nrng.normal(18.0, 6.0, A), 0.0, 60.0)
        self.fort[:] = 0.0

    def gov_for(self, name, year):
        words = self.cfg["government_words"]
        for gov in ("tribal", "republic", "constitutional"):
            if any(w in name for w in words.get(gov, [])):
                return gov
        if self.era == "modern":
            mon = self.cfg.get("modern_monarchies", {})
            for gov, names in mon.items():
                if name in names:
                    return gov
            return "republic"
        return "absolute"

    def _seed_polities(self):
        own, n = self.owner, self.cap
        cnt = np.bincount(own, minlength=n)
        pop_p = np.bincount(own, self.pop, n)
        dev_p = np.bincount(own, self.dev * self.pop, n) / np.maximum(pop_p, 1.0)
        year = self.date_year()
        ec = self.ec
        noise = self.nrng
        for p in np.nonzero(cnt > 0)[0]:
            p = int(p)
            if p == 0:
                continue
            self.born[p] = True
            gov = self.gov_for(self.polity(p).name, year)
            self.gov[p] = self.gov_list.index(gov)
            tribal = gov == "tribal"
            self.tax[p] = ec["tax_default"] * (0.5 if tribal else noise.uniform(0.85, 1.2))
            self.stab[p] = float(np.clip(noise.normal(60, 7), 35, 85))
            self.legit[p] = float(np.clip(noise.normal(62, 7), 35, 85))
            self.tech[p] = float(np.clip(ec["tech_base"] + 0.5 * (dev_p[p] - 50.0) - (15 if tribal else 0), 5, 95))
            self.morale[p] = 0.7
            self.army[p] = pop_p[p] * ec["manpower"] * 0.32 * noise.uniform(0.7, 1.3)
            for k, v in ec["budget"].items():
                self.budget[k][p] = float(np.clip(v + noise.normal(0, 0.02), 0.02, 0.6))
        self.born[0] = False

    def _prime(self):
        e = self._economy()
        rev = e["rev_net"]
        self.last["rev"], self.last["out"], self.last["pop"] = rev, e["out_p"], e["pop_p"]
        self.last["spend"] = self.budget["army"] * rev + (1 - self.budget["army"]) * rev * 0.6
        self.last["net"] = rev - self.last["spend"]
        self.last["interest"] = np.zeros(self.cap)
        alive = e["alive"]
        self.treasury = np.where(alive, rev * self.nrng.uniform(0.15, 0.5, self.cap), 0.0)
        self.debt = np.where(alive, rev * self.nrng.uniform(0.0, 0.45, self.cap), 0.0)
        if 0 <= self.player < self.cap:
            self.treasury[self.player] = rev[self.player] * 0.4
            self.debt[self.player] = rev[self.player] * 0.1

    def _city_data_curve(self, data):
        return data["anchors"]

    def _init_cities(self, data, year):
        self._city_curves = {}
        self.cities = []
        if not data:
            return
        anchors = data["anchors"]
        for i, c in enumerate(data["cities"]):
            atom = self.hist.atom_at(c["lon"], -c["lat"])
            if atom is None:
                atom = self._nearest_atom(c["lon"], -c["lat"])
            if atom is None:
                continue
            curve = [(a, p * 1000.0) for a, p in zip(anchors, c["pop"]) if p > 0]
            self._city_curves[i] = (curve, c.get("founded"))
            founded = c.get("founded")
            exists = (founded is None or founded <= year) and curve
            city = {"id": i, "ru": c["ru"], "atom": int(atom), "pop": 0.0, "b": [], "q": [], "mult": 1.0,
                    "port": bool(c.get("port")), "dyn": False, "pending": 0 if exists else (founded or 99999)}
            if exists:
                city["pop"] = self._city_target(city, year)
            self.cities.append(city)
        self.rebuild_city_effects()

    def _nearest_atom(self, x, y):
        a = self.hist.anchors.astype(np.float64)
        d = (a[:, 0] - x) ** 2 + (a[:, 1] - y) ** 2
        i = int(d.argmin())
        return i if d[i] < 9.0 else None

    def load_city_curves(self):
        # Кривые роста городов не пишутся в сейв, а читаются из data/cities_<эпоха>.json.
        self._city_curves = {}
        path = config.DATA_DIR / f"cities_{self.era}.json"
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        except OSError:
            return
        for i, c in enumerate(data["cities"]):
            curve = [(a, p * 1000.0) for a, p in zip(data["anchors"], c["pop"]) if p > 0]
            self._city_curves[i] = (curve, c.get("founded"))

    def _city_target(self, city, year):
        if city.get("dyn"):
            return city["pop"]
        curve, founded = self._city_curves.get(city["id"], ([], None))
        if not curve:
            return 0.0
        xs, ys = [c[0] for c in curve], [c[1] for c in curve]
        if founded and year < xs[0]:
            if len(xs) == 1:
                return 3000.0
            t = (year - founded) / max(xs[0] - founded, 1)
            return math.exp(math.log(3000.0) * (1 - t) + math.log(ys[0]) * t) if t > 0 else 3000.0
        if len(xs) == 1:
            return ys[0] * (1.0 + 0.004 * max(year - xs[0], 0))
        return _interp_log(year, xs, ys)

    def rebuild_city_effects(self):
        self.cmult = np.ones(self.A)
        self.cdev = np.zeros(self.A)
        self.cunrest = np.zeros(self.A)
        self.city_eff = {k: np.zeros(self.cap) for k in ("tax_eff", "science", "legit", "manpower")}
        bmap = {b["id"]: b for b in self.cfg["buildings"]}
        for c in self.cities:
            if c.get("pending"):
                continue
            atom = c["atom"]
            share = min(1.0, c["pop"] / max(self.pop[atom], 1.0) * 3.0)
            owner = int(self.owner[atom])
            for bid in c["b"]:
                fx = bmap[bid]["effects"] if bid in bmap else {}
                self.cmult[atom] += fx.get("city_output", 0.0) * share
                self.cdev[atom] += fx.get("dev", 0.0)
                self.cunrest[atom] += fx.get("unrest", 0.0)
                for k in self.city_eff:
                    self.city_eff[k][owner] += fx.get(k, 0.0)

    def _cities_step(self, k):
        year = self.date_year()
        bmap = {b["id"]: b for b in self.cfg["buildings"]}
        rebuild = False
        for c in self.cities:
            if c.get("pending"):
                if year >= c["pending"]:
                    c["pending"] = 0
                    c["pop"] = 3000.0
                    rebuild = True
                    self.note(f"Основан город {c['ru']}.", "city", [int(self.owner[c["atom"]])])
                continue
            atom = c["atom"]
            target = self._city_target(c, year)
            if not c.get("dyn"):
                target *= (0.85 + 0.003 * self.dev[atom]) * (1.0 - 0.004 * max(0.0, self.unrest[atom] - 50.0))
                c["pop"] += (target - c["pop"]) * (1.0 - 0.98 ** k)
            else:
                c["pop"] *= 1.0 + 0.004 * (self.dev[atom] / 50.0) * k / 12.0 * 3
            done = [q for q in c["q"] if q[1] <= self.month]
            for q in done:
                c["q"].remove(q)
                c["b"].append(q[0])
                rebuild = True
                if self.player >= 0 and self.in_group(self.player)[self.owner[atom]]:
                    self.note(f"В городе {c['ru']} построено: {bmap[q[0]]['name']}.", "city", [int(self.owner[atom])])
        if rebuild:
            self.rebuild_city_effects()
            self.recompute_effects()

    def _build_drift(self, snap, year, month_idx):
        hist, off = self.hist, self.year_offset
        self.drift = []
        if self.history_mode != "soft":
            return
        events = []
        for s in range(snap, len(hist.years) - 1):
            a, b = hist.owner[s].astype(np.int64), hist.owner[s + 1].astype(np.int64)
            changed = np.nonzero(a != b)[0]
            if not len(changed):
                continue
            m0, m1 = (hist.years[s] + off) * 12, (hist.years[s + 1] + off) * 12
            groups = {}
            for atom in changed.tolist():
                groups.setdefault((int(a[atom]), int(b[atom])), []).append(atom)
            for (frm, to), atoms in groups.items():
                if frm == to:
                    continue
                events.append({"month": self.rng.randrange(m0, max(m1, m0 + 1)), "frm": frm, "to": to,
                               "atoms": atoms, "state": PENDING, "until": 0})
        events.sort(key=lambda e: e["month"])
        for ev in events:
            if ev["month"] <= month_idx:
                self._apply_drift(ev, silent=True)
            else:
                self.drift.append(ev)

    def _apply_drift(self, ev, silent=False):
        frm, to = ev["frm"], ev["to"]
        atoms = np.asarray(ev["atoms"], np.int64)
        held = atoms[self.owner[atoms] == frm]
        if not len(held):
            ev["state"] = SKIPPED
            return
        if not silent and self.player >= 0:
            grp = self.in_group(self.player)
            if grp[to] and not grp[frm]:
                ev["state"], ev["until"] = CLAIM, self.month + CLAIM_MONTHS
                self.note(f"Исторические притязания: {self.title(self.player)} может потребовать у "
                          f"{self.title(frm)} {len(held)} обл. (дипломатия).", "history", [to, frm])
                return
            if grp[frm] and not grp[to]:
                ev["state"] = SKIPPED
                self._threat(to, frm, held)
                return
        ev["state"] = APPLIED
        if silent or to == 0:
            self.owner[held] = to
            if to:
                self.ensure_born(to)
            self.version += 1
            return
        self.transfer_atoms(held, to, text=f"{self.title(to)} получает {len(held)} обл. ({self.title(frm)}).",
                            kind="history", actors=(frm, to))
        self.add_relation(frm, to, -15)

    def _threat(self, aggressor, victim, atoms):
        a, v = self.root(aggressor), self.root(victim)
        ratio = self.strength(a) / max(self.strength(v), 1.0)
        if ratio > 0.7 or self.rng.random() < 0.35:
            ok, _ = self.declare_war(a, v, reason="исторические притязания")
            if ok:
                return
        self.note(f"{self.title(aggressor)} не решается требовать земли у {self.title(victim)}.", "history",
                  [aggressor, victim])

    def _drift_step(self):
        if not self.drift:
            return
        keep = []
        for ev in self.drift:
            if ev["state"] == PENDING and ev["month"] <= self.month:
                self._apply_drift(ev)
            if ev["state"] in (PENDING, CLAIM):
                if ev["state"] == CLAIM and ev["until"] <= self.month:
                    continue
                keep.append(ev)
        self.drift = keep

    def claims(self, p):
        out = []
        for ev in self.drift:
            if ev["state"] != CLAIM:
                continue
            atoms = np.asarray(ev["atoms"], np.int64)
            held = int((self.owner[atoms] == ev["frm"]).sum())
            if held:
                out.append((ev, held))
        return out

    def press_claim(self, p, ev):
        atoms = np.asarray(ev["atoms"], np.int64)
        held = atoms[self.owner[atoms] == ev["frm"]]
        if not len(held):
            return False, "Эти земли уже сменили владельца."
        a, d = self.root(p), self.root(ev["frm"])
        if self.truce(a, d) or self.allied(a, d):
            return False, "Сейчас это невозможно: перемирие или союз."
        ratio = self.strength(a) / max(self.strength(d), 1.0)
        if ratio >= 1.6:
            self.transfer_atoms(held, a, text=f"{self.title(d)} уступает {self.title(a)} {len(held)} обл. "
                                f"(исторические притязания).", kind="history", actors=(a, d))
            self.add_relation(a, d, -25)
            self.truces[self._key(a, d)] = self.month + self.sim["truce_months"]
            ev["state"] = APPLIED
            self.drift.remove(ev)
            return True, f"Притязания признаны: получено областей {len(held)}."
        self.add_relation(a, d, -20)
        return False, "Требование отвергнуто: сил для давления не хватает. Остаётся война."
