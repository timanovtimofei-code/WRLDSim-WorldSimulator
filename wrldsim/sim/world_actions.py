# Действия в живом мире (миксин World): каждое возвращает (успех, сообщение для игрока).
import colorsys
import math

import numpy as np

BUDGET_KEYS = ("army", "admin", "infra", "science", "court")


class ActionsMixin:
    def annual_revenue(self, p):
        return max(float(self.last["rev"][self.in_group(p)].sum()), 1.0)

    def cost_of(self, p, frac):
        return frac * self.annual_revenue(p)

    def _pay(self, p, amount):
        if self.treasury[p] < amount:
            return False
        self.treasury[p] -= amount
        return True

    def _poor(self, p, amount):
        return False, f"В казне не хватает средств: нужно {self._fmt(amount)}, есть {self._fmt(self.treasury[p])}."

    @staticmethod
    def _fmt(x):
        from ..ui import format as fmt
        return fmt.usd(max(x, 0.0))

    def set_tax(self, p, rate):
        rate = float(min(max(rate, 0.02), self.ec["tax_max"]))
        self.tax[p] = rate
        return True, f"Налоговая ставка: {round(rate * 100)}%."

    def set_budget(self, p, **shares):
        new = {k: float(min(max(shares.get(k, self.budget[k][p]), 0.0), 1.0)) for k in BUDGET_KEYS}
        total = sum(new.values())
        if total > 1.0:
            new = {k: v / total for k, v in new.items()}
        for k, v in new.items():
            self.budget[k][p] = v
        return True, "Бюджет обновлён."

    def borrow(self, p, frac):
        grp_rev = self.annual_revenue(p)
        limit = grp_rev * (self.sim["debt_limit_years"] + self.eff["debt_limit"][p])
        room = limit - self.debt[p]
        amount = min(frac * grp_rev, max(room, 0.0))
        if amount <= 0:
            return False, "Кредиторы больше не дают: долг уже у предела."
        self.debt[p] += amount
        self.treasury[p] += amount
        return True, f"Взят заём {self._fmt(amount)} под {round((self.ec['interest'] + self.eff['interest'][p]) * 100)}% годовых."

    def repay(self, p):
        amount = min(self.treasury[p], self.debt[p])
        if amount <= 0:
            return False, "Платить нечем или долгов нет."
        self.treasury[p] -= amount
        self.debt[p] -= amount
        return True, f"Погашено долга: {self._fmt(amount)}."

    def decree_cost(self, p, d):
        return self.cost_of(p, d["cost"])

    def decree_status(self, p, d):
        eras = d.get("eras") or []
        if eras and self.era not in eras:
            return False, "не для этой эпохи"
        active = self.decrees.get(p, {})
        if d["id"] in active:
            return False, "уже действует"
        year = self.date_year()
        if d.get("min_year") and year < d["min_year"]:
            return False, f"не раньше {d['min_year']} г."
        if self.tech[p] < d.get("min_tech", 0):
            return False, f"нужны технологии {d['min_tech']}+ (сейчас {round(self.tech[p])})"
        gov = self.gov_list[self.gov[p]]
        if d.get("gov") and gov not in d["gov"]:
            return False, "не подходит строю"
        for other in d.get("not", []):
            if other in active:
                return False, f"противоречит указу «{self._decree(other)['name']}»"
        if self.treasury[p] < self.decree_cost(p, d):
            return False, "не хватает денег в казне"
        return True, ""

    def enact(self, p, did):
        d = self._decree(did)
        ok, why = self.decree_status(p, d)
        if not ok:
            return False, why[:1].upper() + why[1:] + "."
        self.treasury[p] -= self.decree_cost(p, d)
        until = self.month + d["months"] if d.get("months") else 0
        self.decrees.setdefault(p, {})[did] = {"since": self.month, "until": until}
        fx = d["effects"]
        if "stab_once" in fx:
            self.stab[p] = min(100.0, max(0.0, self.stab[p] + fx["stab_once"]))
        if "legit_once" in fx:
            self.legit[p] = min(100.0, max(0.0, self.legit[p] + fx["legit_once"]))
        if d.get("set_gov") in self.gov_list:
            self.gov[p] = self.gov_list.index(d["set_gov"])
        self.recompute_effects()
        self.note(f"{self.title(p)}: издан указ «{d['name']}».", "decree", [p])
        return True, f"Указ «{d['name']}» вступил в силу."

    def repeal(self, p, did):
        if did not in self.decrees.get(p, {}):
            return False, "Этот указ не действует."
        del self.decrees[p][did]
        self.recompute_effects()
        self.legit[p] = max(0.0, self.legit[p] - 1)
        return True, f"Указ «{self._decree(did)['name']}» отменён."

    def invest(self, p, atom, points=5):
        if self.owner[atom] != p and not self.in_group(p)[self.owner[atom]]:
            return False, "Эта земля не ваша."
        cfg = self.cfg["invest"]
        out = self.pop[atom] * self.gpc[atom] * (0.55 + 0.009 * self.dev[atom])
        cost = points * out * cfg["cost_per_point"]
        if not self._pay(p, cost):
            return self._poor(p, cost)
        gain = points * (cfg["gain"] if self.dev[atom] < cfg["high_dev"] else cfg["gain_high"])
        self.dev[atom] = min(100.0, self.dev[atom] + gain)
        return True, f"Вложено {self._fmt(cost)}: развитие +{gain:.1f}."

    def amnesty(self, p, atom):
        cfg = self.cfg["invest"]
        out = self.pop[atom] * self.gpc[atom]
        cost = out * cfg["amnesty_cost"]
        if not self._pay(p, cost):
            return self._poor(p, cost)
        self.unrest[atom] = max(0.0, self.unrest[atom] - cfg["amnesty"])
        self.legit[p] = max(0.0, self.legit[p] - 0.5)
        return True, f"Амнистия и раздача хлеба обошлись в {self._fmt(cost)}: недовольство −{cfg['amnesty']}."

    def garrison(self, p, atom):
        cfg = self.cfg["invest"]
        out = self.pop[atom] * self.gpc[atom]
        cost = out * cfg["garrison_cost"]
        if not self._pay(p, cost):
            return self._poor(p, cost)
        self.fort[atom] = min(100.0, self.fort[atom] + cfg["garrison"])
        self.unrest[atom] = max(0.0, self.unrest[atom] - cfg["garrison"] * 0.6)
        return True, f"Гарнизон усилен за {self._fmt(cost)}."

    def cede(self, p, atoms, to):
        atoms = [a for a in atoms if self.owner[a] == p]
        if not atoms or to == p:
            return False, "Нечего передавать."
        self.transfer_atoms(atoms, to, text=f"{self.title(p)} передаёт {len(atoms)} обл. государству {self.title(to)}.",
                            actors=(p, to))
        self.add_relation(p, to, 30)
        self.legit[p] = max(0.0, self.legit[p] - 3)
        return True, f"Передано областей: {len(atoms)}."

    def city_at(self, atom):
        return next((c for c in self.cities if c["atom"] == atom and not c.get("pending")), None)

    def found_city(self, p, atom, name):
        if not self.in_group(p)[self.owner[atom]]:
            return False, "Основывать города можно только на своей земле."
        name = " ".join(str(name).split())[:28]
        if not name:
            return False, "Дайте городу название."
        if any(c["ru"].lower() == name.lower() for c in self.cities):
            return False, "Город с таким названием уже есть."
        cfg = self.cfg["invest"]
        cost = self.cost_of(p, cfg["found_city_cost"] * 0.02)
        if not self._pay(p, cost):
            return self._poor(p, cost)
        self.cities.append({"id": len(self.cities), "ru": name, "atom": int(atom), "pop": float(cfg["found_city_pop"]),
                            "b": [], "q": [], "mult": 1.0, "port": False, "dyn": True, "pending": 0})
        self.note(f"Основан город {name}.", "city", [p])
        return True, f"Город {name} основан (цена {self._fmt(cost)})."

    def building(self, bid):
        return next(b for b in self.cfg["buildings"] if b["id"] == bid)

    def build_status(self, p, city, b):
        if self.era not in b["eras"]:
            return False, "не для этой эпохи"
        if b.get("min_year") and self.date_year() < b["min_year"]:
            return False, f"не раньше {b['min_year']} г."
        if b["id"] in city["b"] or any(q[0] == b["id"] for q in city["q"]):
            return False, "уже есть или строится"
        if b.get("port") and not city.get("port"):
            return False, "нужен выход к морю"
        if self.treasury[p] < self.cost_of(p, b["cost"] * 0.05):
            return False, "не хватает денег в казне"
        return True, ""

    def build(self, p, city, bid):
        b = self.building(bid)
        ok, why = self.build_status(p, city, b)
        if not ok:
            return False, why[:1].upper() + why[1:] + "."
        cost = self.cost_of(p, b["cost"] * 0.05)
        self.treasury[p] -= cost
        city["q"].append([bid, self.month + 12])
        return True, f"Строительство: {b['name']} в городе {city['ru']} ({self._fmt(cost)}), срок - год."

    def find_polity(self, text):
        t = " ".join(str(text).lower().split())
        if not t:
            return None
        area = np.bincount(self.owner, self.km2, self.cap)
        best, score = None, 0
        for i in range(self.next_poly):
            if area[i] <= 0 or i == 0:
                continue
            pol = self.polity(i)
            names = [str(pol.ru or "").lower(), str(pol.name or "").lower()]
            s = 0
            if t in names:
                s = 4
            elif any(n.startswith(t) for n in names if n):
                s = 3
            elif any(t in n for n in names if n):
                s = 2
            elif any(n and n in t for n in names):
                s = 1
            if s and (s, area[i]) > (score, area[best] if best is not None else -1):
                best, score = i, s
        return best

    def find_atoms(self, text, within=None):
        if not self.atom_names:
            return []
        t = " ".join(str(text).lower().split())
        pool = range(self.A) if within is None else [int(a) for a in within]
        exact = [a for a in pool if self.atom_names[a].lower() == t]
        if exact:
            return exact
        return [a for a in pool if t and t in self.atom_names[a].lower()]

    def transfer_atoms(self, atoms, to, text=None, kind="territory", actors=(), quiet=False):
        atoms = np.asarray(list(atoms), dtype=np.int64)
        if not len(atoms):
            return 0
        old = np.unique(self.owner[atoms])
        if to:
            self.ensure_born(to)
        self.owner[atoms] = to
        self.unrest[atoms] = np.minimum(100.0, self.unrest[atoms] + 12.0)
        self.revolt[atoms] = 0
        self.version += 1
        for p in old:
            if p and p != to and not (self.owner == p).any():
                self._extinct(int(p))
        self.rebuild_city_effects()
        self.recompute_effects()
        if text and not quiet and to:
            self.note(text, kind, [*actors, *[int(p) for p in old], int(to)])
        return len(atoms)

    def _extinct(self, p):
        for w in [w for w in self.wars if p in (w["att"], w["dfn"])]:
            self.wars.remove(w)
        self.alliances = {a for a in self.alliances if p not in a}
        for v in np.nonzero(self.overlord == p)[0]:
            if v != p:
                self.overlord[v] = v
        self.overlord[p] = p
        self.army[p] = self.treasury[p] = self.debt[p] = 0.0
        self.born[p] = False
        self.version += 1

    def ensure_born(self, p):
        if self.born[p]:
            return
        pop = float(self.pop[self.owner == p].sum())
        self.born[p] = True
        self.tax[p] = self.ec["tax_default"]
        self.stab[p], self.legit[p] = 55.0, 55.0
        self.tech[p] = self.ec["tech_base"]
        self.morale[p] = 0.7
        self.army[p] = pop * self.ec["manpower"] * 0.3
        for k in BUDGET_KEYS:
            self.budget[k][p] = self.ec["budget"][k]
        self.gov[p] = self.gov_list.index(self.gov_for(self.polity(p).name, self.date_year()))

    def new_polity(self, ru, name, color=None, gov=None):
        if self.next_poly >= self.cap:
            return None
        i = self.next_poly
        self.next_poly += 1
        if color is None:
            h = self.rng.random()
            color = [round(c * 255) for c in colorsys.hls_to_rgb(h, 0.52, 0.45)]
        self.new_meta.append({"id": f"new{i}", "name": name, "ru": ru, "color": list(color), "flag": "", "flag_from": 0})
        self.overlord[i] = i
        self.born[i] = False
        if gov in self.gov_list:
            self.gov[i] = self.gov_list.index(gov)
        self.version += 1
        return i

    def can_reach(self, p, q):
        if q in self.neighbors(p):
            return True
        return self.distance(p, q) <= self.sim["reach_deg"] * (1.4 if self.tech[p] > 55 else 1.0)

    def diplo_state(self, p, q):
        rq = self.root(q)
        return {"relation": self.relation(p, rq), "war": self.at_war(p, rq), "allied": self.allied(p, rq),
                "truce": self.truce(p, rq), "reach": self.can_reach(p, rq),
                "vassal": int(self.overlord[q]) == p and q != p}

    def gift(self, p, q):
        d = self.cfg["diplomacy"]
        cost = self.cost_of(p, d["gift_cost"])
        if not self._pay(p, cost):
            return self._poor(p, cost)
        self.add_relation(p, q, d["gift_relation"])
        return True, f"Дар отправлен ({self._fmt(cost)}): отношения улучшились."

    def embassy(self, p, q):
        d = self.cfg["diplomacy"]
        cost = self.cost_of(p, d["embassy_cost"])
        if not self._pay(p, cost):
            return self._poor(p, cost)
        self.add_relation(p, q, d["embassy_relation"])
        return True, "Посольство работает: отношения немного лучше."

    def trade_pact(self, p, q):
        d = self.cfg["diplomacy"]
        if self.relation(p, q) < d["trade_min_relation"]:
            return False, "Для торгового договора отношения слишком холодные."
        cost = self.cost_of(p, d["trade_cost"])
        if not self._pay(p, cost):
            return self._poor(p, cost)
        self.add_relation(p, q, 10)
        self.treasury[p] += cost * 3.0
        self.treasury[q] += cost * 3.0
        return True, "Торговый договор заключён: обе стороны выигрывают."

    def alliance(self, p, q):
        d = self.cfg["diplomacy"]
        if self.allied(p, q):
            return False, "Союз уже есть."
        if self.relation(p, q) < d["alliance_min_relation"]:
            return False, f"Для союза нужны отношения {d['alliance_min_relation']}+."
        if self.at_war(p, q):
            return False, "Идёт война."
        self.alliances.add(self._key(p, q))
        self.note(f"Союз: {self.title(p)} и {self.title(q)}.", "dip", [p, q])
        return True, "Союз заключён."

    def break_alliance(self, p, q):
        if self._key(p, q) not in self.alliances:
            return False, "Союза нет."
        self.alliances.discard(self._key(p, q))
        self.add_relation(p, q, -35)
        return True, "Союз расторгнут."

    def declare_war(self, p, q, reason=""):
        a, d = self.root(p), self.root(q)
        if a == d or not (self.owner == d).any() and not self.in_group(d).any():
            return False, "Некому объявлять войну."
        if self.at_war(a, d):
            return False, "Вы уже воюете."
        if self.allied(a, d):
            return False, "Сначала расторгните союз."
        if self.truce(a, d):
            return False, "Действует перемирие."
        if not self.can_reach(a, d):
            return False, "Враг вне досягаемости: нет общей границы и пути."
        self.war_id += 1
        w = {"id": self.war_id, "att": a, "dfn": d, "since": self.month, "score": 0.0, "att_all": [], "dfn_all": [],
             "reason": reason}
        for x in range(self.cap):
            if x in (a, d):
                continue
            for side, key, foe in ((a, "att_all", d), (d, "dfn_all", a)):
                if self.allied(side, x) and not self.at_war(x, side) and self.rng.random() < 0.7 \
                        and self.root(x) == x and not self.allied(x, foe):
                    w[key].append(x)
        self.wars.append(w)
        self.add_relation(a, d, -60)
        if a == self.player:
            self.stab[a] = max(0.0, self.stab[a] + self.cfg["diplomacy"]["war_stab"])
            self.legit[a] = max(0.0, self.legit[a] + self.cfg["diplomacy"]["war_legit"])
        self.note(f"Война: {self.title(a)} против {self.title(d)}." + (f" Повод: {reason}." if reason else ""),
                  "war", [a, d])
        return True, f"Война объявлена: {self.title(d)}."

    def war_between(self, a, b):
        ra, rb = self.root(a), self.root(b)
        return next((w for w in self.wars if {w["att"], w["dfn"]} == {ra, rb}), None)

    def propose_peace(self, p, q, concede=False):
        w = self.war_between(p, q)
        if w is None:
            return False, "Войны нет."
        ours = 1.0 if self.root(p) == w["att"] else -1.0
        score = w["score"] * ours
        if score >= 40:
            self._settle(w, w["att"] if ours > 0 else w["dfn"], demand=True)
            return True, "Противник согласился на мир на ваших условиях."
        if abs(score) < 30:
            if self.rng.random() < 0.6:
                self._settle(w, None)
                return True, "Заключён белый мир: границы прежние."
            return False, "Противник отказался: у него ещё есть надежды."
        if concede:
            self._settle(w, w["dfn"] if ours > 0 else w["att"], demand=False)
            return True, "Вы заключили мир ценой уступок."
        return False, "Положение тяжёлое. Мир возможен только с уступками."

    def demand(self, p, q, share=0.1):
        a, d = self.root(p), self.root(q)
        if self.truce(a, d) or self.allied(a, d):
            return False, "Сейчас это невозможно: перемирие или союз."
        sa, sd = self.strength(a), self.strength(d)
        if sa < sd * 1.6:
            self.add_relation(a, d, -20)
            return False, "Противник отверг требование: он не считает вас достаточно сильным."
        cands = self.own_atoms(d)
        n = max(1, int(len(cands) * share))
        atoms = self.nearest_atoms(cands, self.group_atoms(a), n)
        self.transfer_atoms(atoms, a, text=f"{self.title(d)} уступает {self.title(a)} {len(atoms)} обл. под давлением.",
                            actors=(a, d))
        self.add_relation(a, d, -35)
        self.stab[d] = max(0.0, self.stab[d] - 3)
        self.truces[self._key(a, d)] = self.month + self.sim["truce_months"]
        self.prestige[a] += 3
        return True, f"Получено областей: {len(atoms)}."

    def release_vassal(self, p, v):
        if self.overlord[v] != p or v == p:
            return False, "Это не ваш вассал."
        self.overlord[v] = v
        self.add_relation(p, v, 40)
        self.version += 1
        self.note(f"{self.title(p)} даёт независимость государству {self.title(v)}.", "dip", [p, v])
        return True, "Независимость дарована."

    def nearest_atoms(self, cands, anchors_of, n):
        cands = np.asarray(cands, np.int64)
        if len(cands) <= n:
            return cands
        src = np.asarray(anchors_of, np.int64)
        if len(src) > 700:
            src = self.nrng.choice(src, 700, replace=False)
        a = self.hist.anchors.astype(np.float64)
        c = a[cands]
        s = a[src]
        d2 = np.full(len(cands), np.inf)
        for i in range(0, len(s), 100):
            blk = s[i:i + 100]
            dx = (c[:, None, 0] - blk[None, :, 0]) * np.cos(np.radians(-c[:, None, 1]))
            dy = c[:, None, 1] - blk[None, :, 1]
            d2 = np.minimum(d2, (dx * dx + dy * dy).min(axis=1))
        return cands[np.argsort(d2)[:n]]

    def _group_strengths(self):
        q = 0.5 + self.tech / 100.0 + self.eff["army_quality"]
        s = self.army * q * self.morale
        w = np.where(self.overlord == np.arange(self.cap), 1.0, 0.5)
        gs = np.zeros(self.cap)
        np.add.at(gs, self.roots(), s * w)
        return gs

    def _side_strength(self, gs, roots):
        return sum(float(gs[r]) for r in roots)

    def _wars_step(self, k):
        if not self.wars:
            return
        gs = self._group_strengths()
        sim = self.sim
        for w in list(self.wars):
            att, dfn = w["att"], w["dfn"]
            if not (self.in_group(att).any() and self.in_group(dfn).any()):
                self.wars.remove(w)
                continue
            sa = self._side_strength(gs, [att, *w["att_all"]])
            sd = self._side_strength(gs, [dfn, *w["dfn_all"]]) * sim["war_defender_bonus"]
            tot = sa + sd
            ratio = (sa - sd) / tot if tot > 0 else 0.0
            w["score"] = float(min(max(w["score"] + sim["war_score_rate"] * ratio * k
                                       + self.rng.gauss(0, sim["war_noise"]) * math.sqrt(k), -140), 140))
            if tot > 0:
                self._war_losses(att, [att, *w["att_all"]], sd / max(sa, 1.0), k)
                self._war_losses(dfn, [dfn, *w["dfn_all"]], sa / max(sd, 1.0), k)
            length = self.month - w["since"]
            weary_a = self.stab[att] < 10 or self.debt[att] > 3 * max(self.last["rev"][att], 1.0)
            weary_d = self.stab[dfn] < 10 or self.debt[dfn] > 3 * max(self.last["rev"][dfn], 1.0)
            if w["score"] >= 100 or weary_d:
                self._settle(w, att, demand=True)
            elif w["score"] <= -100 or weary_a:
                self._settle(w, dfn, demand=True)
            elif length >= sim["war_max_months"]:
                self._settle(w, None)

    def _war_losses(self, root, side, pressure, k):
        loss = min(self.sim["war_casualty"] * math.sqrt(max(pressure, 0.05)) * k, 0.10)
        for r in side:
            grp = self.in_group(r)
            self.army[grp] *= 1.0 - loss
            self.morale[grp] = np.clip(self.morale[grp] - 0.01 * k * min(pressure, 2.0), 0.2, 1.0)
            self.pop[self.group_atoms(r)] *= 1.0 - loss * 0.04

    def _settle(self, w, winner, demand=True):
        if w in self.wars:
            self.wars.remove(w)
        att, dfn = w["att"], w["dfn"]
        key = self._key(att, dfn)
        self.truces[key] = self.month + self.sim["truce_months"]
        if winner is None:
            self.note(f"Мир без победителя: {self.title(att)} и {self.title(dfn)}.", "peace", [att, dfn])
            return
        loser = dfn if winner == att else att
        score = abs(w["score"])
        loser_atoms = self.own_atoms(loser)
        if len(loser_atoms) == 0:
            return
        if winner == att:
            share = min(max((score - 35.0) / 130.0, 0.03), 0.40)
        else:
            share = min(max((score - 50.0) / 260.0, 0.0), 0.12)
        if len(loser_atoms) <= 3 and winner == att and score >= 100:
            share = 1.0
        n = int(round(share * len(loser_atoms)))
        if not demand:
            n = max(n, 1)
        if n >= 1:
            atoms = self.nearest_atoms(loser_atoms, self.group_atoms(winner), n)
            self.transfer_atoms(atoms, winner, text=(
                f"Мир: {self.title(winner)} побеждает, {self.title(loser)} теряет {len(atoms)} обл."),
                kind="peace", actors=(winner, loser))
        else:
            self.note(f"Мир: {self.title(winner)} побеждает, земли не меняют хозяев.", "peace", [winner, loser])
        self.prestige[self.in_group(winner)] += 5
        self.stab[loser] = max(0.0, self.stab[loser] - 8)
        self.legit[loser] = max(0.0, self.legit[loser] - 6)
        self.stab[winner] = min(100.0, self.stab[winner] + 3)
        self.add_relation(winner, loser, -30)

    def _rebellions(self, k, alive):
        hot = self.unrest >= self.sim["revolt_unrest"]
        self.revolt = np.where(hot, np.minimum(self.revolt + k, 200), 0).astype(np.int16)
        ready = np.nonzero(self.revolt >= self.sim["revolt_months"])[0]
        if not len(ready):
            return
        chance = 1.0 - (1.0 - self.sim["revolt_chance"]) ** k
        ready = np.array([a for a in ready if self.rng.random() < chance], np.int64)
        if not len(ready):
            return
        mask = np.zeros(self.A, bool)
        mask[ready] = True
        h = self.hist
        both = mask[h._pa] & mask[h._pb] & (self.owner[h._pa] == self.owner[h._pb])
        parent = {int(a): int(a) for a in ready}

        def find(x):
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x
        for a, b in zip(h._pa[both].tolist(), h._pb[both].tolist()):
            parent[find(a)] = find(b)
        groups = {}
        for a in ready.tolist():
            groups.setdefault(find(a), []).append(a)
        for atoms in groups.values():
            self._secede(atoms)

    def region_name(self, atom):
        if not self.atom_names:
            return f"область {atom}"
        names = getattr(self, "_region_names", None)
        if names is None or names[0] is not self.atom_names:
            parent = self.hist.parent
            count = np.bincount(parent)
            seen = {}
            out = []
            for a in range(self.A):
                base = self.atom_names[a]
                if count[parent[a]] > 1:
                    seen[parent[a]] = seen.get(parent[a], 0) + 1
                    base = f"{base} (ч. {seen[parent[a]]})"
                out.append(base)
            names = self._region_names = (self.atom_names, out)
        return names[1][atom]

    def _secede(self, atoms):
        old = int(self.owner[atoms[0]])
        if np.sum(self.owner == old) <= len(atoms) and len(atoms) > 0 and np.sum(self.owner == old) == len(atoms):
            return
        big = max(atoms, key=lambda a: self.km2[a])
        region = self.region_name(big)
        words = {"ancient": "Мятежная область", "imperial": "Мятежная республика", "modern": "Республика"}
        ru = f"{words.get(self.era, 'Республика')} {region}"
        i = self.new_polity(ru, ru, gov="republic" if self.era != "ancient" else "tribal")
        if i is None:
            self.unrest[atoms] = 60.0
            return
        self.transfer_atoms(atoms, i, quiet=True)
        self.stab[i], self.legit[i] = 40.0, 35.0
        self.army[i] = max(self.army[i], float(self.pop[atoms].sum()) * 0.01)
        self.add_relation(old, i, -60)
        self.note(f"Восстание: {region} отделяется от {self.title(old)} (образовано: {ru}).", "revolt", [old, i])
        old_root = self.root(old)
        if self.root(i) != old_root and (self.owner == old_root).any():
            self.war_id += 1
            self.wars.append({"id": self.war_id, "att": i, "dfn": old_root, "since": self.month, "score": 12.0,
                              "att_all": [], "dfn_all": [], "reason": "независимость"})

    def _vassals(self, k, alive):
        for v in np.nonzero((self.overlord != np.arange(self.cap)) & alive)[0]:
            lord = int(self.overlord[v])
            unrest = float(self.unrest[self.owner == v].mean()) if (self.owner == v).any() else 0.0
            weak = self.stab[lord] < 40 or self.legit[lord] < 35
            p = self.sim["vassal_independence_base"] * k * (1.0 + max(unrest - 30.0, 0.0) / 30.0) * (2.0 if weak else 1.0)
            if self.rng.random() < p:
                self.overlord[v] = v
                self.version += 1
                self.add_relation(v, lord, -40)
                self.note(f"{self.title(v)} добивается независимости от {self.title(lord)}.", "revolt", [v, lord])
                if self.rng.random() < 0.5 and self.can_reach(lord, v):
                    self.war_id += 1
                    self.wars.append({"id": self.war_id, "att": lord, "dfn": int(v), "since": self.month, "score": 0.0,
                                      "att_all": [], "dfn_all": [], "reason": "возвращение владений"})

    def _ai(self, k):
        if self.month % self.sim["ai_decision_every"] != 0 and k == 1:
            return
        mult = self.ec.get("ai_war_mult", 1.0)
        span = k * self.sim["ai_decision_every"] if k == 1 else k
        chance = 1.0 - (1.0 - self.sim["ai_war_chance"] * mult) ** span
        col = 1.0 - (1.0 - self.sim["colonial_war_chance"] * mult) ** span
        gs = self._group_strengths()
        roots = np.nonzero((self.roots() == np.arange(self.cap)) & (self.army > 0))[0]
        tribal = self.gov_list.index("tribal") if "tribal" in self.gov_list else -1
        for a in roots:
            a = int(a)
            if a == self.player or gs[a] <= 0:
                continue
            if self.rng.random() < chance * (0.5 + self.tech[a] / 60.0):
                nb = [x for x in self.neighbors(a) if self._ai_target_ok(a, x, gs, 1.35)]
                if nb:
                    self._ai_war(a, self.rng.choice(nb))
                    continue
            if self.tech[a] > 52 and self.rng.random() < col:
                targets = [x for x in range(self.P0) if self.gov[x] == tribal and self.owner_has(x)
                           and self._ai_target_ok(a, x, gs, 1.2) and self.distance(a, x) <= self.sim["reach_deg"]]
                if targets:
                    self._ai_war(a, self.rng.choice(targets))

    def owner_has(self, p):
        return bool((self.owner == p).any())

    def _ai_target_ok(self, a, x, gs, ratio):
        if x == a or x == 0:
            return False
        if self.at_war(a, x) or self.allied(a, x) or self.truce(a, x) or gs[x] <= 0 and gs[a] <= 0:
            return False
        if self.relation(a, x) > 25:
            return False
        return gs[a] >= gs[x] * ratio

    def _ai_war(self, a, x):
        if x == self.player or self.in_group(self.player)[x]:
            self.declare_war(a, x, reason="притязания соседа")
        else:
            self.declare_war(a, x)
