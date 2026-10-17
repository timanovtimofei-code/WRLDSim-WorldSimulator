# Ход - месяц (при перемотке на годы - год); всё считается массивами numpy по атомам сразу. Баланс - data/realm.json.
import base64
import math
import random
import zlib

import numpy as np

from .world_actions import ActionsMixin
from .world_history import HistoryMixin

VERSION = 1
EFFECT_KEYS = ("output", "growth", "dev_growth", "unrest", "tax_eff", "stab_target", "legit", "science",
               "army_quality", "army_cost", "manpower", "interest", "debt_limit", "tribute", "relations")
BUDGET_KEYS = ("army", "admin", "infra", "science", "court")
LOG_KINDS = ("war", "peace", "territory", "revolt", "decree", "econ", "dip", "history", "city", "info")
REF_KM = 111.32


def _enc(a):
    return base64.b64encode(zlib.compress(np.ascontiguousarray(a).tobytes(), 1)).decode("ascii")


def _dec(s, dtype, n):
    a = np.frombuffer(zlib.decompress(base64.b64decode(s)), dtype=dtype).copy()
    if len(a) != n:
        raise ValueError("сохранённый мир не подходит к карте")
    return a


class World(HistoryMixin, ActionsMixin):
    def __init__(self, hist, cfg, era_id, year_offset=0):
        self.hist, self.cfg, self.era = hist, cfg, era_id
        self.ec = cfg["eras"][era_id]
        self.sim = cfg["sim"]
        self.year_offset = year_offset
        self.rng = random.Random()
        self.nrng = np.random.default_rng()
        self.A = hist.atoms
        self.P0 = len(hist.polities)
        self.cap = self.P0 + self.sim["max_new_polities"]
        self.next_poly = self.P0
        self.new_meta = []
        self.atom_names = None
        self.version = 0
        self.month = 0                       # последний обработанный месяц (год*12 + месяц - 1)
        self.player = -1
        self.history_mode = cfg.get("default_history", "soft")
        self.log = []
        self.fresh = []
        self.rel = {}                        # (a, b) a < b -> отношения -100..100
        self.alliances = set()
        self.truces = {}                     # (a, b) -> месяц окончания перемирия
        self.wars = []
        self.drift = []
        self.decrees = {}
        self.cities = []
        self.war_id = 0
        A = self.A
        self.owner = np.zeros(A, np.int32)
        self.pop = np.zeros(A)
        self.dev = np.zeros(A)
        self.unrest = np.zeros(A)
        self.gpc = np.zeros(A)
        self.fort = np.zeros(A)
        self.revolt = np.zeros(A, np.int16)
        self.cmult = np.ones(A)
        self.cdev = np.zeros(A)
        self.cunrest = np.zeros(A)
        lat = -hist.anchors[:, 1].astype(np.float64)
        self.km2 = hist.area.astype(np.float64) * REF_KM * REF_KM * np.cos(np.radians(lat))
        n = self.cap
        z = lambda v=0.0: np.full(n, v, np.float64)
        self.treasury, self.debt, self.army = z(), z(), z()
        self.morale, self.tax, self.stab, self.legit = z(0.7), z(self.ec["tax_default"]), z(60), z(60)
        self.tech, self.prestige, self.mob = z(self.ec["tech_base"]), z(), z()
        self.shock = z()
        self.tension_extra = 0.0
        self.budget = {k: z(self.ec["budget"][k]) for k in BUDGET_KEYS}
        self.gov = np.zeros(n, np.int32)
        self.overlord = np.arange(n, dtype=np.int32)
        self.born = np.zeros(n, bool)
        self.last = {"rev": z(), "spend": z(), "net": z(), "out": z(), "pop": z(), "interest": z()}
        self.eff = {k: z() for k in EFFECT_KEYS}
        self.city_eff = {k: z() for k in ("tax_eff", "science", "legit", "manpower")}
        self._city_curves = {}
        self.gov_list = list(cfg["governments"])
        self.gov_tax = np.array([cfg["governments"][g]["tax_eff"] for g in self.gov_list])
        self.gov_stab = np.array([cfg["governments"][g]["stab_base"] for g in self.gov_list], np.float64)
        self.gov_legit = np.array([cfg["governments"][g]["legit_base"] for g in self.gov_list], np.float64)
        self._adj = None
        self._cent = None

    def polity(self, i):
        i = int(i)
        if i < self.P0:
            return self.hist.polities[i]
        return _Meta(self.new_meta[i - self.P0], i)

    def title(self, i):
        return self.polity(i).at(self.date_year()).title

    def color(self, i):
        return self.polity(i).color

    def palette(self):
        pal = np.zeros((self.cap, 3), np.uint8)
        pal[:self.P0] = self.hist.palette
        for j, m in enumerate(self.new_meta):
            pal[self.P0 + j] = m["color"]
        return pal

    def roots(self):
        r = self.overlord.copy()
        for _ in range(3):
            r = r[r]
        return r

    def alive(self):
        return np.bincount(self.owner, minlength=self.cap) > 0

    def in_group(self, root):
        return self.roots() == root

    def group_atoms(self, root):
        r = self.roots()
        return np.nonzero(r[self.owner] == root)[0]

    def date_year(self, month=None):
        m = self.month if month is None else month
        y = m // 12 - self.year_offset
        return y if y > 0 else y - 1

    def note(self, text, kind="info", pols=()):
        entry = [self.month, text, kind, [int(p) for p in pols]]
        self.log.append(entry)
        del self.log[:-self.sim["log_size"]]
        self.fresh.append(entry)
        return entry

    def pull_news(self):
        news, self.fresh = self.fresh, []
        return news

    def relevant(self, entry):
        if self.player < 0:
            return True
        pols = entry[3]
        if entry[2] in ("decree", "econ", "city", "info"):
            return True
        if not pols:
            return False
        grp = self.in_group(self.player)
        if any(grp[p] for p in pols):
            return True
        nb = self.neighbors(self.player)
        return any(p in nb for p in pols) or entry[2] in ("revolt", "war") and len(pols) > 0 and self._is_major(pols)

    def _is_major(self, pols):
        area = np.bincount(self.owner, self.km2, self.cap)
        return any(area[p] > self.km2.sum() * 0.02 for p in pols)

    @staticmethod
    def _key(a, b):
        a, b = int(a), int(b)
        return (a, b) if a < b else (b, a)

    def relation(self, a, b):
        if a == b:
            return 100
        return int(self.rel.get(self._key(a, b), 0))

    def add_relation(self, a, b, delta):
        k = self._key(a, b)
        self.rel[k] = int(min(max(self.rel.get(k, 0) + delta, -100), 100))

    def allied(self, a, b):
        return self._key(a, b) in self.alliances

    def at_war(self, a, b):
        ra, rb = self.root(a), self.root(b)
        return any({w["att"], w["dfn"]} == {ra, rb} for w in self.wars)

    def root(self, p):
        p = int(p)
        for _ in range(4):
            q = int(self.overlord[p])
            if q == p:
                break
            p = q
        return p

    def truce(self, a, b):
        return self.truces.get(self._key(a, b), 0) > self.month

    def adjacency(self):
        if self._adj is None or self._adj[0] != self.version:
            h = self.hist
            po, qo = self.owner[h._pa], self.owner[h._pb]
            m = po != qo
            lo, hi = np.minimum(po[m], qo[m]), np.maximum(po[m], qo[m])
            pairs = set(zip(lo.tolist(), hi.tolist()))
            self._adj = (self.version, pairs)
        return self._adj[1]

    def neighbors(self, p):
        grp = self.in_group(p)
        r = self.roots()
        out = set()
        for a, b in self.adjacency():
            if grp[a] and not grp[b]:
                out.add(int(r[b]))
            elif grp[b] and not grp[a]:
                out.add(int(r[a]))
        out.discard(0)
        out.discard(int(p))
        return out

    def centers(self):
        if self._cent is None or self._cent[0] != self.version:
            w = np.maximum(self.pop, 1.0)
            own = self.owner
            tot = np.bincount(own, w, self.cap)
            x = np.bincount(own, w * self.hist.anchors[:, 0], self.cap) / np.maximum(tot, 1.0)
            y = np.bincount(own, w * -self.hist.anchors[:, 1], self.cap) / np.maximum(tot, 1.0)
            self._cent = (self.version, np.stack([x, y], 1))
        return self._cent[1]

    def distance(self, a, b):
        c = self.centers()
        dx = (c[a, 0] - c[b, 0]) * math.cos(math.radians((c[a, 1] + c[b, 1]) / 2))
        return math.hypot(dx, c[a, 1] - c[b, 1])

    def aggregates(self):
        own = self.owner
        n = self.cap
        pop = np.bincount(own, self.pop, n)
        return {"pop": pop, "atoms": np.bincount(own, minlength=n), "area": np.bincount(own, self.km2, n),
                "dev": np.bincount(own, self.dev * self.pop, n) / np.maximum(pop, 1.0),
                "unrest": np.bincount(own, self.unrest * self.pop, n) / np.maximum(pop, 1.0)}

    def strength(self, root):
        grp = self.in_group(root)
        q = 0.5 + self.tech / 100.0 + self.eff["army_quality"]
        s = self.army * q * self.morale
        w = np.where(np.arange(self.cap) == root, 1.0, 0.5)
        return float((s * w)[grp].sum())

    def realm_atoms(self, p):
        return self.group_atoms(p)

    def own_atoms(self, p):
        return np.nonzero(self.owner == p)[0]

    def monthly(self, p):
        grp = self.in_group(p)
        return {k: float(self.last[k][grp].sum()) / 12.0 for k in ("rev", "spend", "net", "interest")}

    def digest(self, p):
        grp = self.in_group(p)
        atoms = self.group_atoms(p)
        m = self.monthly(p)
        gs = self._group_strengths()
        mine = max(float(gs[p]), 1.0)
        out = {
            "держава": self.title(p),
            "строй": self.cfg["governments"][self.gov_list[self.gov[p]]]["name"],
            "год": self.date_year(),
            "население": int(self.pop[atoms].sum()),
            "площадь_тыс_км2": int(self.km2[atoms].sum() / 1000),
            "областей": int(len(atoms)),
            "казна": round(float(self.treasury[p])),
            "долг": round(float(self.debt[p])),
            "доход_в_месяц": round(m["rev"]),
            "расход_в_месяц": round(m["spend"]),
            "налог_процентов": round(float(self.tax[p]) * 100),
            "стабильность": round(float(self.stab[p])),
            "легитимность": round(float(self.legit[p])),
            "армия_человек": int(self.army[grp].sum()),
            "технологии": round(float(self.tech[p])),
        }
        vassals = [self.title(v) for v in np.nonzero(grp & (np.arange(self.cap) != p))[0]][:8]
        if vassals:
            out["вассалы_и_колонии"] = vassals
        wars = []
        for war in self.wars:
            if p in (war["att"], war["dfn"]) or any(grp[x] for x in war["att_all"] + war["dfn_all"]):
                ours = 1.0 if (war["att"] == p or grp[war["att"]]) else -1.0
                foe = war["dfn"] if ours > 0 else war["att"]
                wars.append({"против": self.title(foe), "счёт_в_нашу_пользу": round(war["score"] * ours),
                             "месяцев": self.month - war["since"]})
        if wars:
            out["войны"] = wars
        nb = []
        for x in sorted(self.neighbors(p), key=lambda q: -float(gs[q]))[:7]:
            nb.append({"название": self.title(x), "отношения": self.relation(p, x), "мощь_к_нашей": round(float(gs[x]) / mine, 2),
                       **({"союз": True} if self.allied(p, x) else {}), **({"война": True} if self.at_war(p, x) else {})})
        out["соседи"] = nb
        decrees = [self._decree(d)["name"] for d in self.decrees.get(p, {})]
        if decrees:
            out["указы"] = decrees
        cities = sorted((c for c in self.cities if not c.get("pending") and grp[self.owner[c["atom"]]]),
                        key=lambda c: -c["pop"])
        if cities:
            out["города"] = [f"{c['ru']} ({int(c['pop'])})" for c in cities[:6]]
        hot = np.nonzero((self.unrest > 70) & np.isin(self.owner, np.nonzero(grp)[0]))[0]
        if len(hot):
            out["недовольные_области"] = [self.region_name(a) for a in hot[:6]]
        claims = [(ev, n) for ev, n in self.claims(p)][:3]
        if claims:
            out["притязания"] = [f"{self.title(ev['frm'])}: {n} обл." for ev, n in claims]
        recent = [e[1] for e in self.log[-6:] if self.relevant(e)]
        if recent:
            out["недавно_в_мире"] = recent
        return out

    def recompute_effects(self):
        for k in EFFECT_KEYS:
            self.eff[k][:] = 0.0
        dmap = {d["id"]: d for d in self.cfg["decrees"]}
        for p, active in self.decrees.items():
            for did, info in active.items():
                d = dmap.get(did)
                if not d:
                    continue
                for k, v in d["effects"].items():
                    if k in self.eff and not k.endswith("_once"):
                        self.eff[k][int(p)] += v
        for k, arr in self.city_eff.items():
            self.eff[k] += arr

    def advance(self, dt):
        target = dt.year * 12 + dt.month - 1
        done = 0
        while self.month < target:
            left = target - self.month
            k = 12 if left > self.sim["detail_months"] else 1
            k = min(k, left)
            self._step(k)
            done += k
            if done > self.sim["month_cap"] * 2:
                self.month = target
                break
        return done

    def _economy(self):
        ec, sim = self.ec, self.sim
        n, own = self.cap, self.owner
        ids = np.arange(n)
        alive = np.bincount(own, minlength=n) > 0
        alive[0] = False
        pop_p = np.bincount(own, self.pop, n)
        out_a = (self.pop * self.gpc * (0.55 + 0.009 * self.dev) * self.cmult
                 * np.maximum(0.2, 1.0 + self.eff["output"][own] + self.shock[own]))
        out_p = np.bincount(own, out_a, n)
        avg_gpc = np.where(pop_p > 0, out_p / np.maximum(pop_p, 1.0), 0.0)
        admin_b = 0.6 * (self.budget["admin"] - 0.15)
        eff_t = np.clip((0.5 + 0.5 * self.stab / 100.0) * (1.0 + admin_b + self.eff["tax_eff"]) * self.gov_tax[self.gov],
                        0.15, 1.35)
        rev = out_p * np.clip(self.tax, 0.0, 0.7) * eff_t
        rev[0] = 0.0
        vassal = (self.overlord != ids) & alive
        trib = np.where(vassal, rev * np.clip(sim["tribute_rate"] + self.eff["tribute"][self.overlord], 0, 0.8), 0.0)
        rev_net = rev - trib
        np.add.at(rev_net, self.overlord[vassal], trib[vassal])
        cost_man = ec["army_cost_k"] * np.maximum(avg_gpc, 1.0) * (1.0 + self.eff["army_cost"])
        man_cap = ec["manpower"] * (1.0 + self.eff["manpower"] + 0.7 * self.mob) * pop_p
        return {"alive": alive, "pop_p": pop_p, "out_p": out_p, "avg_gpc": avg_gpc, "rev": rev, "rev_net": rev_net,
                "vassal": vassal, "cost_man": cost_man, "man_cap": man_cap}

    def _step(self, k):
        ec, sim = self.ec, self.sim
        n, own = self.cap, self.owner
        dt = k / 12.0
        decay = lambda rate: 1.0 - (1.0 - rate) ** k
        ids = np.arange(n)
        e = self._economy()
        alive, pop_p, out_p = e["alive"], e["pop_p"], e["out_p"]
        rev, rev_net, vassal, cost_man, man_cap = e["rev"], e["rev_net"], e["vassal"], e["cost_man"], e["man_cap"]
        target_army = np.minimum(self.budget["army"] * rev_net / np.maximum(cost_man, 1.0), man_cap)
        grow = 0.06 * self.army * k + 0.0003 * pop_p * k
        self.army = np.where(alive, np.clip(target_army, self.army - 0.10 * self.army * k, self.army + grow), 0.0)
        self.army = np.minimum(self.army, np.where(alive, man_cap, 0.0))
        upkeep = self.army * cost_man
        spend = upkeep + (self.budget["admin"] + self.budget["infra"] + self.budget["science"] + self.budget["court"]) * rev_net
        interest = self.debt * np.maximum(ec["interest"] + self.eff["interest"], 0.0)
        net = rev_net - spend - interest
        self.treasury += net * dt
        short = np.minimum(self.treasury, 0.0)
        self.debt -= short
        self.treasury -= short
        pay = np.minimum(self.treasury * 0.5, self.debt)
        self.debt -= pay
        self.treasury -= pay
        cap_t = rev_net * 3.0
        npl = ids != self.player
        self.treasury = np.where(npl & (self.treasury > cap_t) & (cap_t > 0), cap_t, self.treasury)
        self.last["rev"], self.last["spend"] = rev_net, spend + interest
        self.last["net"], self.last["out"], self.last["pop"], self.last["interest"] = net, out_p, pop_p, interest
        limit = rev * (sim["debt_limit_years"] + self.eff["debt_limit"])
        crisis = alive & (self.debt > limit * 1.6) & (rev > 0)
        for p in np.nonzero(crisis)[0]:
            self.debt[p] *= 0.5
            self.stab[p] = max(0.0, self.stab[p] - 10)
            self.legit[p] = max(0.0, self.legit[p] - 10)
            if pop_p[p] > 3e6 or self.in_group(self.player)[p]:
                self.note(f"{self.title(p)}: государство не платит по долгам, кредиторы теряют половину.", "econ", [p])
        self._ai_fiscal(alive, rev, pop_p)
        tech_cap = 30.0 + 0.7 * self.tech
        dev_year = ec["dev_growth"] * (1.0 + self.tech / 100.0) * (1.0 + 3.0 * self.budget["infra"] + self.eff["dev_growth"])
        room = np.maximum(0.0, (tech_cap[own] - self.dev) / np.maximum(tech_cap[own], 1.0))
        self.dev = np.clip(self.dev + (dev_year[own] * room + self.cdev - 0.02 * np.maximum(0.0, self.unrest - 60)) * dt,
                           0.0, 100.0)
        g = ec["growth"] * (1.0 + self.eff["growth"][own]) * np.clip(
            1.0 + ec["dev_growth_slope"] * (self.dev - 50) - 0.004 * self.unrest, 0.1, 1.8)
        self.pop *= 1.0 + g * dt
        stab_a = self.stab[own]
        tax_pen = np.maximum(0.0, self.tax[own] - ec["tax_default"]) * 40.0
        target_u = np.clip(100.0 - stab_a * 1.05 + tax_pen + np.where(vassal[own], 10.0, 0.0), 0.0, 100.0)
        noise = self.nrng.normal(0.0, 1.5, self.A)
        self.unrest = np.clip(self.unrest + (target_u - self.unrest) * decay(0.12) + (self.eff["unrest"][own] + self.cunrest) * k
                              + noise * math.sqrt(k), 0.0, 100.0)
        war_cnt = self._war_counts()
        unrest_avg = np.bincount(own, self.unrest * self.pop, n) / np.maximum(pop_p, 1.0)
        tax_pen_p = np.maximum(0.0, self.tax - ec["tax_default"]) * 120.0
        debt_ratio = self.debt / np.maximum(rev, 1.0)
        debt_pen = 15.0 * np.clip(debt_ratio / max(sim["debt_limit_years"], 0.1) - 0.5, 0.0, 1.5)
        tgt = (self.gov_stab[self.gov] + 0.30 * (self.legit - 50.0) - tax_pen_p - 4.0 * np.minimum(war_cnt, 3) - debt_pen
               - 0.15 * np.maximum(0.0, unrest_avg - 35.0) + self.eff["stab_target"]
               + 8.0 * (self.budget["court"] - 0.2) + 10.0 * (self.budget["admin"] - 0.15))
        self.stab = np.clip(self.stab + (tgt - self.stab) * decay(0.12) + self.nrng.normal(0.0, 1.0, n) * math.sqrt(k),
                            0.0, 100.0)
        legit_t = self.gov_legit[self.gov] + 0.2 * (self.stab - 50.0) + self.prestige * 0.1 + self.eff["legit"] * 100.0
        self.legit = np.clip(self.legit + (legit_t - self.legit) * decay(0.05), 0.0, 100.0)
        avg_dev = np.bincount(own, self.dev * self.pop, n) / np.maximum(pop_p, 1.0)
        science = np.maximum(self.eff["science"], -0.9)
        self.tech = np.clip(self.tech + ec["tech_rate"] * dt * (0.4 + 4.0 * self.budget["science"]) * (0.6 + avg_dev / 100.0)
                            * (1.0 + science) * (1.0 - self.tech / 130.0), 0.0, 100.0)
        morale_t = np.clip(0.65 + 0.0025 * (self.stab - 50.0) + 0.1 * (self.budget["court"] - 0.2), 0.3, 1.0)
        self.morale = np.clip(self.morale + (morale_t - self.morale) * decay(0.2), 0.2, 1.0)
        self.prestige *= 0.99 ** k
        self.shock *= 0.96 ** k
        self.tension_extra *= 0.95 ** k
        self.mob = np.where(self.mob > 0, np.maximum(0.0, self.mob - 0.04 * k), 0.0)
        for key in list(self.rel):
            v = self.rel[key]
            nv = v - int(math.copysign(min(abs(v), max(1, round(abs(v) * self.cfg["diplomacy"]["relation_decay"] * k))), v))
            if nv:
                self.rel[key] = nv
            else:
                del self.rel[key]
        self.month += k
        self._expire_decrees()
        self._cities_step(k)
        self._wars_step(k)
        self._rebellions(k, alive)
        self._vassals(k, alive)
        self._ai(k)
        self._drift_step()

    def _ai_fiscal(self, alive, rev, pop_p):
        # Государства под управлением компьютера следят за долгом: поднимают налоги и урезают армию, а когда
        npl = np.arange(self.cap) != self.player
        sick = alive & npl & (self.debt > 0.5 * rev)
        rich = alive & npl & (self.debt <= 0) & (self.treasury > 1.5 * rev) & (self.tax > self.ec["tax_default"])
        self.tax = np.where(sick, np.minimum(self.tax * 1.01 + 0.0005, self.ec["tax_max"] * 0.8), self.tax)
        self.budget["army"] = np.where(sick, np.maximum(self.budget["army"] * 0.985, 0.04), self.budget["army"])
        self.tax = np.where(rich, np.maximum(self.tax * 0.99, self.ec["tax_default"]), self.tax)
        self.budget["army"] = np.where(rich, np.minimum(self.budget["army"] * 1.01, self.ec["budget"]["army"]),
                                       self.budget["army"])

    def _war_counts(self):
        cnt = np.zeros(self.cap)
        grp = self.roots()
        for w in self.wars:
            for side in (w["att"], w["dfn"]):
                cnt[grp == side] += 1
        return cnt

    def _expire_decrees(self):
        changed = False
        for p, active in self.decrees.items():
            for did in [d for d, info in active.items() if info.get("until") and info["until"] <= self.month]:
                del active[did]
                changed = True
                if int(p) == self.player:
                    self.note(f"Срок указа «{self._decree(did)['name']}» истёк.", "decree", [p])
        if changed:
            self.recompute_effects()

    def _decree(self, did):
        return next(d for d in self.cfg["decrees"] if d["id"] == did)

    def to_json(self):
        return {
            "v": VERSION, "era": self.era, "A": self.A, "cap": self.cap, "month": self.month, "player": self.player,
            "history": self.history_mode, "offset": self.year_offset, "next_poly": self.next_poly, "war_id": self.war_id,
            "owner": _enc(self.owner.astype(np.uint16)), "pop": _enc(self.pop.astype(np.float32)),
            "dev": _enc(self.dev.astype(np.float16)), "unrest": _enc(self.unrest.astype(np.float16)),
            "gpc": _enc(self.gpc.astype(np.float32)), "fort": _enc(self.fort.astype(np.float16)),
            "revolt": _enc(self.revolt),
            "p": {k: _enc(getattr(self, k).astype(np.float32)) for k in
                  ("treasury", "debt", "army", "morale", "tax", "stab", "legit", "tech", "prestige", "mob", "shock")},
            "tension_x": self.tension_extra,
            "budget": {k: _enc(v.astype(np.float32)) for k, v in self.budget.items()},
            "gov": _enc(self.gov.astype(np.int8)), "overlord": _enc(self.overlord.astype(np.uint16)),
            "born": _enc(self.born.astype(np.uint8)),
            "meta": self.new_meta,
            "rel": [[a, b, v] for (a, b), v in self.rel.items()],
            "alliances": [list(x) for x in self.alliances],
            "truces": [[a, b, m] for (a, b), m in self.truces.items()],
            "wars": self.wars, "drift": self.drift, "decrees": {str(p): d for p, d in self.decrees.items()},
            "cities": self.cities, "log": self.log[-120:],
        }

    @classmethod
    def from_json(cls, hist, cfg, data):
        if data.get("v", 0) > VERSION:
            raise ValueError("сейв мира из более новой версии игры")
        w = cls(hist, cfg, data["era"], data.get("offset", 0))
        if data["A"] != w.A:
            raise ValueError("сохранённый мир не подходит к карте")
        w.month, w.player, w.history_mode = data["month"], data["player"], data.get("history", "soft")
        w.next_poly, w.war_id, w.new_meta = data["next_poly"], data.get("war_id", 0), data["meta"]
        for key, dtype in (("owner", np.uint16), ("pop", np.float32), ("dev", np.float16), ("unrest", np.float16),
                           ("gpc", np.float32), ("fort", np.float16), ("revolt", np.int16)):
            getattr(w, key)[:] = _dec(data[key], dtype, w.A)
        w.owner = w.owner.astype(np.int32)
        for key in data["p"]:
            getattr(w, key)[:] = _dec(data["p"][key], np.float32, w.cap)
        w.tension_extra = data.get("tension_x", 0.0)
        for key in data["budget"]:
            w.budget[key][:] = _dec(data["budget"][key], np.float32, w.cap)
        w.gov[:] = _dec(data["gov"], np.int8, w.cap)
        w.overlord[:] = _dec(data["overlord"], np.uint16, w.cap)
        w.born[:] = _dec(data["born"], np.uint8, w.cap).astype(bool)
        w.rel = {(a, b): v for a, b, v in data["rel"]}
        w.alliances = {tuple(x) for x in data["alliances"]}
        w.truces = {(a, b): m for a, b, m in data["truces"]}
        w.wars, w.drift = data["wars"], data["drift"]
        w.decrees = {int(p): d for p, d in data["decrees"].items()}
        w.cities, w.log = data["cities"], data["log"]
        w.load_city_curves()
        w.rebuild_city_effects()
        w.recompute_effects()
        return w


class _Meta:
    def __init__(self, m, index):
        self.index, self.id, self.name, self.ru = index, m.get("id", f"new{index}"), m["name"], m["ru"]
        self.flag, self.flag_from, self.game = m.get("flag", ""), m.get("flag_from", 0), ""
        self.color, self.iso2 = tuple(m["color"]), ""

    @property
    def title(self):
        return self.ru or self.name

    def at(self, year):
        return self
