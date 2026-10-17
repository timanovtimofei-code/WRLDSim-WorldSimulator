import copy
import math
import random
import time
import uuid

import numpy as np
import pygame

from .. import settings
from ..history import loader as hloader
from ..history.flags import draw_polity_flag
from ..map.controller import MapController
from ..map.labels import draw_labels
from .. import config
from ..sim import anime as anime_mod
from ..sim import saves
from ..sim.arcade import REF_GDP_PC, STATS, ArcadeGame, starting_profile
from ..sim.cheats import CheatRequest, parse_local, route_for
from ..sim import shop
from ..sim.eclipse import CHEAT_NOTICE, Eclipse
from ..sim.eras import GENERIC
from ..sim.risk import Assessment, assess
from ..ui import fonts, icons, theme
from ..ui import format as fmt
from ..ui.gauge import gradient
from ..ui.widgets import (TRASH_COLOR as TRASH, Button, RoundButton, TextInput, Glow, draw_glass_control, draw_panel, draw_round_button,
                          sweep_of, text_on,
                          draw_spaced,
                          draw_text, draw_tooltip, draw_trash as _draw_trash, ellipsize, fill_round, text_surface, wrap)
from .base import State
from .warning import (WARN_FROM, GameOverState, Glitch, WarningState, alarm_frame, glitch_strength, level_name)

ECLIPSE_START = "Начало сессии. Представь героя и страну, предложи первые действия."
CHEAT_FOLLOWUP = ("(Других действий игрок не совершал. Сцена продолжается под действием только что активированного "
                  "чита: покажи в ней, как чит меняет происходящее, и дай новые варианты действий.)")
INPUT_HINT = "Свой вариант: напишите действие и нажмите Enter"
CHOICE_MODES = {"topic": ("Разовое", "Тема вариантов: бизнес, побег, политика…", "Варианты на тему: ",
                          "Предложи новые варианты действий героя на тему: "),
                "free": ("Свободное", "Что угодно: «только мирные», «через связи»…", "Указание для вариантов: ",
                         "Сгенерируй новые варианты действий героя, выполняя указание игрока: ")}
RAIL_W = 56
RAIL_ITEM_H = 50
STATUS_H = 24
CARD_GAP = 10
CTRL = 40
GAP = 12
EC_TITLE = 26
EC_STATUS = 22
EC_GAP = 14
EC_SLIDER_H = 34
EC_TYPE_CPS = 140     # скорость «печати» ответа, символов в секунду
TERM_FONT = 15
TERM_ROW_H = 40
CHOICE_FONT = 16
LOG_COLORS = {"plus": "GOOD", "minus": "DANGER", "cheat": "WARN", "risk": "DANGER",
              "quiet": "TEXT_MUTED", "event": "TEXT", "info": "TEXT_DIM"}
CONSOLE_KEYS = (pygame.K_BACKQUOTE, pygame.K_F1)
CONSOLE_CHARS = "`~ёЁ"
DATE_COL_W = 92
CHEAT_ICON = "✅"
IND_COLORS = {"fame": (255, 200, 90), "chaos": (200, 120, 255), "heat": (255, 90, 70), "health": (90, 230, 130),
              "energy": (90, 200, 255), "stress": (255, 150, 60), "reputation": (240, 220, 140),
              "influence": (236, 62, 66), "stability": (120, 220, 200), "economy": (170, 230, 110),
              "tension": (255, 100, 150)}
NEGATIVE_STATS = ("stress", "tension")
METER_COLORS = ((120, 190, 255), (255, 170, 90), (190, 140, 255), (110, 220, 200), (255, 120, 160), (220, 210, 120))
IND_ROW_H = 35
IND_SPEED = 3.0
IND_FLASH_HOLD = 8.0
EMPTY = pygame.Rect(0, 0, 0, 0)
_strip_cache = {}


def _ind_color(polarity, frac, own):
    if polarity > 0:
        return gradient(frac)
    if polarity < 0:
        return gradient(1 - frac)
    return tuple(int(c * (0.55 + 0.45 * frac)) for c in own)


def _ind_strip(polarity, own, width):
    key = (polarity, own if polarity == 0 else None, width)
    strip = _strip_cache.get(key)
    if strip is None:
        strip = pygame.Surface((max(1, width), 6), pygame.SRCALPHA)
        for px in range(width):
            strip.fill((*_ind_color(polarity, px / max(1, width - 1), own), 255), (px, 0, 1, 6))
        _strip_cache[key] = strip
    return strip


def country_name(app, country):
    return app.country_info.get(country.id, {}).get("name_ru") or country.display_name


def mode_cfg(app, mode_id):
    if mode_id == "anime":
        return app.anime_cfg
    return app.realism_cfg if mode_id == "realism" else app.arcade_cfg


def game_cfg(app, mode_id, era_id):
    if mode_id == "anime":
        return app.anime_cfg
    return app.eras.game_cfg(mode_cfg(app, mode_id), era_id, mode_id)


def _new_session(app, mode_id, difficulty_id=None, era_id="modern"):
    from ..session import GameSession
    app.session = GameSession(mode_id, difficulty_id, era_id=era_id)
    return app.session


def _make_game(app, session, state=None, country=None, hero=None):
    mode_id = session.mode_id
    rules = app.modes["modes"][mode_id]["rules"]
    if state is not None:
        cfg = game_cfg(app, mode_id, state.get("era") or "modern")
        game = ArcadeGame(cfg, rules, None)
        game.world_loader = lambda g, data: hloader.load_world(app, data)
        game.load(state)
        game.difficulty = difficulty_params(app, game)
        if game.world is None and not state.get("anime"):
            _retrofit_world(app, game)
        return game
    era_id = session.era_id
    era = app.eras.era(era_id)
    cfg = game_cfg(app, mode_id, era_id)
    polity = app.eras.polity(era_id, session.polity_id or GENERIC, country_name(app, country))
    start = polity["starts"][min(session.start_idx, len(polity["starts"]) - 1)]
    calendar = {**app.eras.calendar(polity, start), "clock": era["show_clock"], "suffix": era_id != "modern"}
    mult = 1.0
    if session.difficulty_id:
        mult = app.modes["modes"][mode_id]["difficulties"][session.difficulty_id]["start_money_mult"]
    roles = app.eras.roles(era_id, polity, start["year"], app.roles["roles"])
    role = next((r for r in roles if r["id"] == hero.get("role_id")), None)
    gdp_pc = gdp_per_capita(app, country) if polity.get("generic") else REF_GDP_PC * polity["wealth"]
    profile = starting_profile((role or {}).get("start"), hero.get("age"), gdp_pc,
                               money_mult=mult, income_mult=cfg.get("income_mult", 1.0))
    name = country_name(app, country) if polity.get("generic") else polity["name"]
    game = ArcadeGame.new(cfg, rules, country.id, name, hero, mode_id, profile, session.difficulty_id,
                          era_id=era_id, polity_id=polity["id"], calendar=calendar)
    game.s["start_info"] = {"year": start["year"], "label": start["label"], "note": start["note"]}
    game.difficulty = difficulty_params(app, game)
    _attach_world(app, game, era_id, polity, country, start)
    return game


def _retrofit_world(app, game):
    era_id = game.s.get("era") or "modern"
    country = app.world.by_id.get(game.s.get("country_id"))
    if era_id not in hloader.ERAS_WITH_WORLD or country is None:
        return
    polity = app.eras.polity(era_id, game.s.get("polity") or GENERIC, game.s.get("country_name", ""))
    _attach_world(app, game, era_id, polity, country, {"year": fmt.game_year(game.now, game.year_offset)})
    if game.world is not None:
        game.log("Государство подключено к живому миру: территории, казна и войны теперь считаются по-настоящему.", "info")


def _attach_world(app, game, era_id, polity, country, start):
    game.world_loader = lambda g, data: hloader.load_world(app, data)
    try:
        world = hloader.create_world(app, era_id, polity, country, start, game.now, game.year_offset)
    except Exception:       # мир - надстройка: любой сбой не должен ронять старт игры
        import traceback
        traceback.print_exc()
        world = None
    if world is not None:
        game.attach_world(world)


def difficulty_params(app, game):
    diffs = app.modes["modes"][game.s["mode"]].get("difficulties") or {}
    return diffs.get(game.s.get("difficulty") or "")


def gdp_per_capita(app, country):
    info = app.country_info.get(country.id, {})
    gdp = info.get("gdp_usd") or country.gdp_md * 1e6
    population = info.get("population") or country.pop_est
    return gdp / population if gdp > 0 and population > 0 else 10000.0


def start_anime(app, card, hero, start):
    from ..session import GameSession
    session = app.session = GameSession("anime", None, era_id="modern")
    rules = app.modes["modes"]["anime"]["rules"]
    canon = bool(hero.get("canon"))
    profile = {"money": 0.0, "income": 0.0, "scale": 1.0, "fame": 5 if canon else 0, "heat": 0, "hidden": ["stability", "economy", "tension"],
               "stats": {"health": 100, "energy": 90, "stress": 15, "reputation": 40 if canon else 20,
                         "influence": 35 if canon else 8, "stability": 50, "economy": 50, "tension": 20}}
    name = anime_mod.card_name(card)
    game = ArcadeGame.new(game_cfg(app, "anime", "modern"), rules, "JP", name, hero, "anime", profile, None,
                          era_id="modern", polity_id="generic", calendar={"start": "2000-01-01T00:00:00", "clock": False})
    game.s["anime"] = {"card": card, "start": start}
    game.world_loader = lambda g, data: None
    session.game, session.country_id, session.hero = game, "JP", hero
    app.push(ArcadeGameState(app))


def start_game(app, country, hero):
    session = app.session
    session.country_id = country.id
    session.hero = hero
    session.game = _make_game(app, session, country=country, hero=hero)
    app.push(ArcadeGameState(app))


def _read_save(app, mode_id, slot):
    from .confirm import ChoiceState
    try:
        data = saves.load(mode_id, slot)
        ArcadeGame(mode_cfg(app, mode_id), {}, None).load(data["game"])
        return data
    except (OSError, ValueError, KeyError, TypeError) as e:
        app.push(ChoiceState(app, "ОШИБКА ЗАГРУЗКИ", f"Слот {slot} не читается: {e}", []))
        return None


def load_game_from_menu(app, mode_id, slot):
    data = _read_save(app, mode_id, slot)
    if data is None:
        return
    difficulty = data["game"].get("difficulty") or ("medium" if mode_id == "realism" else None)
    session = _new_session(app, mode_id, difficulty, data["game"].get("era") or "modern")
    session.game = _make_game(app, session, state=data["game"])
    session.polity_id = session.game.s.get("polity")
    session.country_id = session.game.s["country_id"]
    session.hero = session.game.s.get("hero")
    state = ArcadeGameState(app, eclipse_data=data.get("eclipse"), slot=slot)
    state.fit_camera(instant=True)
    app.push(state)


def layout(size, card="eclipse"):
    # Карта на весь экран, слева рейка значков и карточка раздела, справа сверху плашка, внизу строка состояния.
    # view - свободная часть карты, в неё камера вписывает цель.
    w, h = size
    status = pygame.Rect(0, h - STATUS_H, w, STATUS_H)
    rail = pygame.Rect(0, 0, RAIL_W, status.y)
    card_r = EMPTY
    if card:
        cw = int(min(680, max(400, w * 0.38))) if card == "eclipse" else int(min(440, max(340, w * 0.27)))
        cw = max(300, min(cw, w - RAIL_W - 2 * CARD_GAP - 160))
        card_r = pygame.Rect(rail.right + CARD_GAP, CARD_GAP, cw, status.y - 2 * CARD_GAP)
    left = card_r.right if card else rail.right
    controls = pygame.Rect(w - CARD_GAP - CTRL, status.y - CARD_GAP - 4 * CTRL - 18, CTRL, 4 * CTRL + 18)
    view = pygame.Rect(left, 0, max(1, w - left), status.y)
    return {"rail": rail, "card": card_r, "side": card_r, "controls": controls, "status": status, "view": view}


def _mono_wrap(text, width, size):
    font = fonts.mono(size)
    lines = []
    for para in str(text).split("\n"):
        line = ""
        for word in para.split(" "):
            cand = f"{line} {word}" if line else word
            if font.size(cand)[0] <= width or not line:
                line = cand
            else:
                lines.append(line)
                line = word
            while font.size(line)[0] > width and len(line) > 1:
                cut = max(1, int(len(line) * width / font.size(line)[0]))
                lines.append(line[:cut])
                line = line[cut:]
        lines.append(line)
    return lines


class ArcadeGameState(State):
    def __init__(self, app, eclipse_data=None, slot=None):
        super().__init__(app)
        self.game = app.session.game
        self.mode_id = app.session.mode_id
        self.cfg = mode_cfg(app, self.mode_id)
        self.cheats_enabled = self.mode_id in ("arcade", "anime")
        self.anime = self.game.s.get("anime")
        self.game.names_fn = self._event_names
        self.undo_stack = []
        self.cheat_flush = False
        self.pending_cheat = None
        self._apply_era()
        self.controller = MapController(app.camera)
        self.home = app.world.by_id[self.game.s["country_id"]]
        self.target = self.home
        self.region = None
        self.hover = None
        self.toast = None
        self.card = "eclipse"
        self.rects = layout(app.screen.get_size(), self.card)
        self.chip_rect = EMPTY
        self._hits = []
        self._pressed = None
        self._rail_glow = {}
        self.ui_tip = None

        self.time_btn = Button("TIME CONTROL", self._open_time_control, size=17, bold=True)
        self.undo_btn = Button("← Откат", self._undo, size=15)
        self.save_btn = Button("Сохранить", self._open_save, size=15)
        self.load_btn = Button("Загрузить", self._open_load, size=15)
        self.menu_btn = Button("Выйти в главное меню", self._to_menu, size=15)
        self.settings_btn = Button("Настройки", self._open_settings, size=15)
        self.shop_btn = Button("Магазин", self._open_shop, size=15, bold=True)
        self.realm_btn = Button("Управление", self._open_realm, size=15, bold=True)
        self.world_btn = Button("← В меню" if self.game.s.get("anime") else "← Вернуться к карте",
                                self._to_menu if self.game.s.get("anime") else self._to_world_map, size=15)
        self.choice_mode = "topic"
        self.choice_mode_btn = Button("", self._toggle_choice_mode, size=13)
        self.topic_input = TextInput(size=15, max_len=200)
        self.topic_rect = EMPTY
        self.topic_send_btn = Button("→", self._send_topic, size=17, bold=True)
        self.tab = "side"
        self.tab_btns = {"side": Button("ПУЛЬТ" if self.cheats_enabled else "ДЕЙСТВИЯ", lambda: self._set_tab("side"),
                                        size=14, bold=True),
                         "stats": Button("ПОКАЗАТЕЛИ", lambda: self._set_tab("stats"), size=14, bold=True)}
        self.buttons = [self.time_btn, self.undo_btn, self.save_btn, self.load_btn, self.menu_btn,
                        self.settings_btn, self.shop_btn, self.world_btn, self.choice_mode_btn, self.topic_send_btn,
                        self.realm_btn, *self.tab_btns.values()]
        self.world_view = self.game.world is not None
        self.hover_atom = None
        self._labels, self._labels_key = [], None
        if self.world_view:
            self.fit_camera(instant=True)
        self.choices_rect = EMPTY
        self.choice_scroll = 0
        self.stats_view = EMPTY
        self.stats_scroll = self.stats_max_scroll = 0
        self.focus = None
        self._over_timer = None
        self._adopt_save(slot)
        self._mark = None
        self.ind = {}

        self.eclipse = self._new_eclipse()
        self.eclipse_rect = EMPTY
        self._anim_time = 0.0
        self.eclipse_scroll = 0
        self._scroll_view = 0.0
        self._typed_version, self._typed_at = -1, 0.0
        self._wrap_cache = {}
        self.eclipse_input = TextInput(size=30, max_len=400)
        self.font_slider = self.font_track = EMPTY
        self.font_drag = False
        self._win_h = app.screen.get_height()
        self._set_ec_font(app.prefs.get("eclipse_font", settings.DEFAULTS["eclipse_font"]))
        self.input_rect = EMPTY
        self.ec_compact, self.ec_status = False, EC_STATUS
        self.input_glitch = Glitch(0.0)
        self.risk_k = 0.0
        self.risk_view = Assessment(0, "", ())
        self.risk_plus_rects = {}
        self._risk_cache = ("", Assessment(0, "", ()))
        self.retry_btn = RoundButton("Повторить запрос", self._eclipse_retry, size=EC_STATUS)
        self.choice_btns = []
        self._choices_key = None
        if not self.eclipse.load(eclipse_data):
            self._ask(ECLIPSE_START)

        self.cheat_mode = "single"
        self.console_lines = [("Single: одноразовый чит. Full: постоянный, его помнит ECLIPSE Prime.",
                               theme.TEXT_MUTED), ("help: встроенные команды. Tab: сменить режим.", theme.TEXT_MUTED)]
        self.console_input = TextInput(size=TERM_FONT, max_len=200)
        self.pending = None
        self._swallow_toggle = False
        self.cheat_list_open = False
        self.term_rect = self.cheat_rect = self.arrow_rect = self.list_rect = EMPTY
        self.mode_rects = {}
        self.trash_rects = []

    def exit(self):
        if self.game.names_fn == self._event_names:
            self.game.names_fn = None
        fmt.set_currency()

    def _apply_era(self):
        s = self.game.s
        self.era_id = s.get("era") or "modern"
        self.polity = self.app.eras.polity(self.era_id, s.get("polity") or GENERIC, s["country_name"])
        fmt.set_currency(*self.app.eras.currency(self.era_id))

    def _new_eclipse(self):
        if self.anime:
            block = anime_mod.card_prompt(self.anime["card"], self.game.s.get("hero"), self.anime.get("start"))
        else:
            start = self.game.s.get("start_info") or self.polity["starts"][0]
            block = self.app.eras.prompt_block(self.era_id, self.polity, start, country_name(self.app, self.home))
            if self.game.world is not None and self.game.is_ruler:
                try:
                    block += "\n\n" + (config.DATA_DIR / "eclipse_realm.txt").read_text(encoding="utf-8-sig").strip()
                except OSError:
                    pass
        eclipse = Eclipse(self.cfg["eclipse"], era_block=block)
        eclipse.rules = list(self.game.cheats) if self.cheats_enabled else []
        return eclipse

    def _realm_bbox(self):
        w = self.game.world
        atoms = w.own_atoms(w.player)
        if not len(atoms):
            atoms = w.group_atoms(w.player)
        if not len(atoms):
            return self.target.focus_bbox
        pts = w.hist.anchors[atoms].astype(float)
        weights = np.maximum(w.km2[atoms], 1.0)
        order_x, order_y = np.argsort(pts[:, 0]), np.argsort(pts[:, 1])
        cx, cy = np.cumsum(weights[order_x]) / weights.sum(), np.cumsum(weights[order_y]) / weights.sum()
        x0, x1 = pts[order_x[np.searchsorted(cx, 0.03)], 0], pts[order_x[min(np.searchsorted(cx, 0.97), len(atoms) - 1)], 0]
        y0, y1 = pts[order_y[np.searchsorted(cy, 0.03)], 1], pts[order_y[min(np.searchsorted(cy, 0.97), len(atoms) - 1)], 1]
        return (x0 - 4, y0 - 3, x1 + 4, y1 + 3)

    def fit_camera(self, instant=False):
        size = self.app.screen.get_size()
        bbox = self._realm_bbox() if self.world_view else self.target.focus_bbox
        target = self.app.camera.fit(bbox, layout(size, self.card)["view"], size)
        if instant:
            self.app.camera.cx, self.app.camera.cy, self.app.camera.zoom = target
        else:
            self.app.camera.fly_to(*target, duration=0.7)

    def _name(self, country):
        return country_name(self.app, country)

    def _gdp(self, country):
        info = self.app.country_info.get(country.id, {})
        return max(0.0, info.get("gdp_usd") or country.gdp_md * 1e6)

    def _event_names(self):
        world = self.app.world
        home = self.game.s["country_name"]
        if self.era_id != "modern":
            others = self.app.eras.polity_names(self.era_id, exclude=self.polity["id"]) or [home]
            return {"country": random.choice(others), "home": home,
                    "region": random.choice(self.polity.get("regions") or [home])}
        if self.polity.get("regions"):
            return {"country": self._name(random.choice(world.countries)), "home": home,
                    "region": random.choice(self.polity["regions"])}
        return {
            "country": self._name(random.choice(world.countries)),
            "home": self._name(self.home),
            "region": (world.regions[random.choice(self.home.regions)].display_name
                       if self.home.regions else self._name(self.home)),
        }

    def _flash(self, text):
        self.toast = (text, 2.5)

    def _pick(self, pos, size):
        if self._over_ui(pos):
            return None
        wx, wy = self.app.camera.to_world(*pos, size)
        country = self.app.world.country_at(wx, wy)
        if country is None:
            return None
        return country, self.app.world.region_at(country, wx, wy)

    def _open_realm(self):
        from .realm import RealmState
        if self.game.over:
            return
        if not self.game.realm_open:
            self._flash("Управление государством доступно только правителям")
            return
        self.app.push(RealmState(self.app, self.game, self))

    def realm_action(self):
        self._push_undo()

    def _open_time_control(self):
        from .time_control import TimeControlState
        if self.game.over:
            return
        self.app.push(TimeControlState(self.app, self.game, self._apply_time))

    def _apply_time(self, minutes):
        log = self.game.s["log"]
        before = log[-1] if log else None
        snap = self._snapshot()
        if minutes > 0:
            passed = self.game.advance_time(minutes)
            text = "Прошло: "
        else:
            passed = self.game.rewind_time(-minutes)
            text = "Отмотано назад: "
        if passed:
            self._push_undo(snap)
            fresh = list(reversed(log))
            fresh = fresh[:fresh.index(before)] if before in fresh else fresh
            hits = sum(1 for _, _, kind in fresh if kind == "risk")
            self._flash(text + fmt.span_ru(passed) + (f"  ·  ▲ неприятностей: {hits}" if hits else ""))

    # Снимок перед каждым действием игрока: состояние игры, читы и диалог с ECLIPSE целиком,
    # чтобы после отката модель видела ровно то, что видела до действия.
    @property
    def can_undo(self):
        return bool(self.game.rules.get("allow_turn_undo")) and bool(self.undo_stack)

    def _snapshot(self):
        return {"game": self.game.to_dict(), "eclipse": copy.deepcopy(self.eclipse.to_dict())}

    def _push_undo(self, snap=None):
        if not self.game.rules.get("allow_turn_undo"):
            return None
        snap = snap or self._snapshot()
        self.undo_stack.append(snap)
        del self.undo_stack[:-self.cfg["undo_depth"]]
        return snap

    def _drop_undo(self, snap):
        if snap is not None and self.undo_stack and self.undo_stack[-1] is snap:
            self.undo_stack.pop()

    def _undo(self):
        if not self.can_undo:
            return
        snap = self.undo_stack.pop()
        self.eclipse.cancel()
        self.pending, self.pending_cheat, self.cheat_flush = None, None, False
        self.game.restore(snap["game"])
        self.eclipse.restore(snap["eclipse"])
        self._sync_rules()
        self.eclipse_scroll = 0
        self._typed_version, self._typed_at = self.eclipse.version, 0.0
        self._choices_key = None
        self._console_say("↶ Откат: последнее действие отменено вместе с диалогом ECLIPSE и читами.", theme.TEXT_DIM)
        self._flash("Отменено")

    def _go_home(self):
        self.target, self.region = self.home, None
        self.fit_camera()

    def _to_world_map(self):
        self._guard_exit("К КАРТЕ МИРА", "Игра закроется, вы вернётесь к выбору страны в том же режиме.",
                         self._leave_to_world_map)

    def _to_menu(self):
        self._guard_exit("ВЫХОД В МЕНЮ", "Игра закроется, вы вернётесь в главное меню.", self.app.unwind)

    def _guard_exit(self, title, message, leave):
        from .confirm import ChoiceState
        if self.game.over:
            leave()
            return
        slot = self.slot
        role = (self.game.s.get("hero") or {}).get("role") or "герой"
        if slot is None:
            options = [("Выбрать слот, сохранить и выйти", lambda: self._open_save(after=leave), True)]
            where = "Автосохранение не ведётся: нет свободных слотов или слот героя удалён."
        else:
            options = [(f"Сохранить в слот {slot} и выйти", lambda: (self._autosave(), leave()), True)]
            where = f"Слот {slot}: {role}, {self.game.s['country_name']}."
        if self._prev_save is not False:
            options.append(("Выйти, не сохраняя последнее действие", lambda: (self._drop_last_save(), leave()), False))
        else:
            options.append(("Выйти без сохранения", leave, False))
        self.app.push(ChoiceState(self.app, title, f"{message} {where}", options))

    def _autosave(self):
        if self.game.over or self.slot is None:
            return
        self._prev_save = saves.read_raw(self.mode_id, self.slot)
        saves.save(self.mode_id, self.slot, self.game.to_dict(), self._meta(), eclipse=self.eclipse.to_dict())

    def _adopt_save(self, slot=None):
        if not self.game.s.get("save_id"):
            self.game.s["save_id"] = uuid.uuid4().hex[:12]
        slots = self.app.modes["modes"][self.mode_id]["rules"]["save_slots"]
        self.slot = slot or saves.slot_for(self.mode_id, slots, self.game.s["save_id"])
        self._prev_save = False
        if self.slot is None:
            self.toast = ("Слоты заняты: сохраните вручную", 6.0)

    def _save_mark(self):
        s = self.game.s
        return (len(s["log"]), tuple(s["log"][-1]) if s["log"] else None, s["money"], s["minute"],
                self.eclipse.version, tuple(self.game.cheats), self.game.world_mark())

    def _update_autosave(self):
        mark = self._save_mark()
        if self._mark is None:
            self._mark = mark
        elif mark != self._mark:
            self._mark = mark
            if self.game.rules.get("autosave_every_turn"):
                self._autosave()

    def _drop_last_save(self):
        if self._prev_save is not False:
            saves.restore_raw(self.mode_id, self.slot, self._prev_save)
            self._prev_save = False

    def _leave_to_world_map(self):
        from .world_map import WorldMapState
        app = self.app
        old = app.session
        stack = app.states
        idx = next((i for i, s in enumerate(stack) if isinstance(s, WorldMapState)), None)
        if idx is None:
            app.unwind()
            app.session = old.fresh()
            app.push(WorldMapState(app))
        else:
            while len(stack) > idx + 1:
                stack.pop().exit()
            app.session = old.fresh()
            stack[-1].enter()
        app.camera.fly_to(*app.world_camera, duration=0.8)

    def _meta(self):
        g = self.game
        return {"country_name": g.s["country_name"], "minute": g.s["minute"], "date": g.date_text(),
                "money": g.money, "money_text": fmt.usd(g.money), "era": self.era_id,
                "era_name": "Anime" if self.anime else self.app.eras.era(self.era_id)["short"],
                "role": (g.s.get("hero") or {}).get("role", ""), "hero_name": (g.s.get("hero") or {}).get("name", ""),
                "save_id": g.s["save_id"]}

    def _open_save(self, after=None):
        from .save_slots import SaveSlotsState
        if self.game.over:
            return

        def do_save(slot):
            self.slot = slot
            self._autosave()
            self._prev_save = False
            self._flash(f"Сохранено в слот {slot}")
            if after:
                after()
        self.app.push(SaveSlotsState(self.app, self.mode_id, "save", do_save, on_delete=self._slot_deleted))

    def _open_load(self):
        from .save_slots import SaveSlotsState

        def do_load(slot):
            data = _read_save(self.app, self.mode_id, slot)
            if data is None:
                return
            session = self.app.session
            session.era_id = data["game"].get("era") or "modern"
            game = _make_game(self.app, session, state=data["game"])
            game.names_fn = self._event_names
            session.game, self.game = game, game
            session.polity_id = game.s.get("polity")
            self.home = self.app.world.by_id[game.s["country_id"]]
            self._apply_era()
            self._adopt_save(slot)
            self.eclipse_scroll = 0
            self.undo_stack.clear()
            self.pending, self.pending_cheat, self.cheat_flush = None, None, False
            self.eclipse.cancel()
            self.eclipse = self._new_eclipse()
            if not self.eclipse.load(data.get("eclipse")):
                self._ask(ECLIPSE_START)
            self._choices_key = None
            self.ind.clear()
            session.country_id = self.home.id
            session.hero = game.s.get("hero")
            self._go_home()
            self._flash(f"Загружен слот {slot}")
        self.app.push(SaveSlotsState(self.app, self.mode_id, "load", do_load, on_delete=self._slot_deleted))

    def _slot_deleted(self, slot):
        if slot == self.slot:
            self.slot, self._prev_save = None, False
            self._flash("Слот героя удалён: нажмите «Сохранить», чтобы продолжить автосохранение")

    def _summary(self):
        g = self.game.s
        news = [text for _, text, _ in g["log"][-3:]]
        hero = g.get("hero") or {}
        if self.anime:
            hidden = g.get("hidden", [])
            return {"режим": "anime", "мир": g["country_name"], "имя": hero.get("name"), "роль": hero.get("role"),
                    "возраст": hero.get("age"), "день": self.game.date_text(), "известность": g["fame"],
                    "показатели": {f"{STATS[k][0]} ({k})": v for k, v in g["stats"].items() if k not in hidden},
                    "шкалы_сюжета": {f"{m['label']} ({key})": m["value"] for key, m in g.get("meters", {}).items()},
                    "последние_новости": news}
        summary = {"режим": self.mode_id, "страна": g["country_name"], "имя": hero.get("name"),
                   "роль": hero.get("role"), "возраст": hero.get("age"), "пол": hero.get("gender"),
                   "дата": self.game.date_text(), "деньги": round(g["money"]), "известность": g["fame"]}
        summary["эпоха"] = self.app.eras.era(self.era_id)["short"]
        if self.polity.get("coin"):
            summary["монеты"] = self.polity["coin"]
        if self.mode_id == "arcade":
            summary["абсурд"] = g["chaos"]
        summary["внимание"] = g.get("heat", 0)
        summary["доход_в_день"] = round(g.get("income", 0))
        hidden = g.get("hidden", [])
        summary["показатели"] = {f"{STATS[key][0]} ({key})": value for key, value in g["stats"].items()
                                 if key not in hidden}
        if hidden:
            summary["скрытые_показатели"] = list(hidden)
        summary["шкалы_сюжета"] = {f"{m['label']} ({key})": m["value"] for key, m in g.get("meters", {}).items()}
        if self.game.difficulty:
            summary["сложность"] = {k: v for k, v in self.game.difficulty.items() if k != "name"}
        if self.game.dossier_enabled:
            dossier = g.get("dossier", [])
            summary["досье_скрытое"] = [{"id": e["id"], "запись": e["text"], "вес": e["weight"],
                                         "всплыло": e.get("exposed", False)} for e in dossier[-25:]]
            fresh = set(g.get("dossier_fresh", []))
            if fresh:
                summary["всплыло_с_прошлого_хода"] = [e["text"] for e in dossier if e["id"] in fresh]
        owned = shop.inventory(g)
        if owned:
            summary["имущество_героя"] = [f"{it['name']} ({fmt.usd(it['price'])})" for it in owned[-30:]]
        summary["последние_новости"] = news
        w = self.game.world
        if w is not None and w.player >= 0:
            digest = w.digest(w.player)
            if not self.game.is_ruler:
                keep = ("держава", "строй", "год", "население", "стабильность", "войны", "соседи", "недавно_в_мире")
                digest = {k: v for k, v in digest.items() if k in keep}
            summary["государство"] = digest
        return summary

    def _set_ec_font(self, size):
        # Шрифт переписки урезается по высоте окна, сохранённый выбор игрока при этом не меняется.
        self.ec_pref = int(min(max(size, settings.ECLIPSE_FONT_MIN), settings.ECLIPSE_FONT_MAX))
        size = min(self.ec_pref, max(settings.ECLIPSE_FONT_MIN, self._win_h // 30))
        k = size / 30
        self.ec_font = size
        self.ec_font_sm = round(26 * k)
        self.ec_fx = max(14, round(24 * k))
        self.ec_pad = max(10, round(18 * k))
        self.ec_fx_h = max(26, round(40 * k))
        self.ec_input_h = max(44, round(64 * k))
        self.eclipse_input.size = size

    def _slider_event(self, event):
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1 and self.font_slider.collidepoint(event.pos):
            self.font_drag = True
        elif event.type == pygame.MOUSEBUTTONUP and event.button == 1 and self.font_drag:
            self.font_drag = False
            self.app.prefs["eclipse_font"] = self.ec_pref
            settings.save(self.app.prefs)
            return True
        elif not (event.type == pygame.MOUSEMOTION and self.font_drag):
            return False
        track = self.font_track
        frac = min(max((event.pos[0] - track.x) / max(1, track.w), 0.0), 1.0)
        lo, hi = settings.ECLIPSE_FONT_MIN, settings.ECLIPSE_FONT_MAX
        self._set_ec_font(round(lo + frac * (hi - lo)))
        return True

    def _ask(self, text):
        if self.game.over:
            return
        if self.eclipse.busy:
            return
        if text != ECLIPSE_START:
            self._push_undo()
        self.eclipse.send(text, self._summary(), shown=text != ECLIPSE_START)
        self.game.s.pop("dossier_fresh", None)
        self.eclipse_scroll = 0

    def _choose(self, choice):
        if self.eclipse.busy or self.game.over:
            return
        if choice.get("risk", 0) < WARN_FROM:
            self._ask(choice["text"])
            return
        self.app.push(WarningState(self.app, choice, lambda: self._ask(choice["text"]),
                                   cheat_fn=self._add_suggested_cheat if self.cheats_enabled else None,
                                   active_cheats=self.game.cheats))

    def _add_suggested_cheat(self, text):
        if text.lower() in (c.lower() for c in self.game.cheats):
            return False
        self._push_undo()
        self.game.add_cheat(text)
        self._sync_rules()
        self._console_say(f"› full /{text}", theme.ACCENT)
        self._console_say("Постоянный чит добавлен из предупреждения ECLIPSE.", theme.GOOD)
        self._cheat_activated(text, True, [], flush=False)
        return True

    def _open_shop(self):
        from .shop import ShopState
        self.focus = None
        self.app.push(ShopState(self.app, self.game, self.cfg["eclipse"], self._summary, on_change=self._flash,
                                before_change=self._push_undo,
                                categories=self.app.eras.shop_categories(self.era_id, shop.CATEGORIES)))

    def _toggle_choice_mode(self):
        self.choice_mode = "free" if self.choice_mode == "topic" else "topic"
        self.focus = "topic"

    def _send_topic(self):
        text = " ".join(self.topic_input.text.split())
        if not text or self.eclipse.busy or self.game.over:
            return
        _, _, shown, ask = CHOICE_MODES[self.choice_mode]
        self.topic_input.text = ""
        self._push_undo()
        self.eclipse.send(ask + text, self._summary(), options_only=True, note=shown + text)
        self.eclipse_scroll = 0

    def _topic_event(self, event):
        if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
            self.focus = None
            return True
        if event.type == pygame.KEYDOWN and event.key == pygame.K_TAB:
            self._toggle_choice_mode()
            return True
        if event.type == pygame.KEYDOWN and event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
            self._send_topic()
            return True
        if event.type in (pygame.TEXTINPUT, pygame.KEYDOWN):
            self.topic_input.handle_event(event)
            return True
        return False

    def _open_settings(self):
        from .settings_state import SettingsState
        self.app.push(SettingsState(self.app))

    def _eclipse_retry(self):
        self.eclipse.retry(self._summary())

    def _poll_eclipse(self):
        ops = self.eclipse.poll()
        if ops is not None:
            for line in self.game.apply_ops(ops, tag="ECLIPSE"):
                if not line.startswith("пропущено"):
                    self.eclipse.note("fx", line)
            if not self.eclipse.options_only:
                for entry in self.game.run_dossier(1):
                    self.eclipse.note("fx", "всплыло: " + entry["text"])
            self.game.check_defeat()
            self.eclipse_scroll = 0
        key = tuple((c["text"], c["risk"]) for c in self.eclipse.choices)
        if key != self._choices_key:
            self._choices_key = key
            self.choice_scroll = 0
            self.choice_btns = [RoundButton(("▲ " if c["risk"] >= WARN_FROM else "") + c["text"],
                                            lambda c=c: self._choose(c), size=CHOICE_FONT)
                                for c in self.eclipse.choices]

    def _console_say(self, text, color=None):
        self.console_lines.append((text, color or theme.TEXT))
        del self.console_lines[:-60]

    def _sync_rules(self):
        self.eclipse.rules = list(self.game.cheats) if self.cheats_enabled else []

    def _cheat_activated(self, text, full, effects, flush=True):
        if not self.cheats_enabled:
            return
        kind = "ПОСТОЯННЫЙ (FULL): действует всю игру, добавлен в правила мира" if full else "РАЗОВЫЙ (SINGLE)"
        lines = [CHEAT_NOTICE, f"Чит-код игрока: «{text}». Тип: {kind}."]
        if effects:
            lines.append("Движок уже применил к показателям: " + "; ".join(effects) + ".")
        lines.append("Чит принимается безусловно: без сопротивления, нотаций и предупреждений. Примени его к сюжету "
                     "прямо в ответе: покажи в сцене, как мир это отражает. В «ops» отдай только то, чего движок "
                     "ещё не сделал.")
        self.eclipse.add_note("\n".join(lines), shown=f"{CHEAT_NOTICE}: /{text}")
        self.cheat_flush = self.cheat_flush or flush

    def _flush_cheats(self):
        if not self.cheat_flush or self.eclipse.busy or self.pending is not None or self.game.over:
            return
        self.cheat_flush = False
        if not self.eclipse.notes:
            return
        self.eclipse.send(CHEAT_FOLLOWUP, self._summary(), shown=False)
        self.game.s.pop("dossier_fresh", None)
        self.eclipse_scroll = 0

    def _submit(self, text):
        text = text.strip().lstrip("/").strip()
        if not text:
            return
        full = self.cheat_mode == "full"
        self._console_say(("› full /" if full else "› /") + text, theme.ACCENT if full else theme.WARN)
        local = parse_local(text)
        if local is not None and not (full and local[0]):
            ops, reply = local
            self._console_say(reply)
            if ops:
                self._push_undo()
                lines = self.game.apply_ops(ops)
                for line in lines:
                    self._console_say("  " + line, theme.WARN)
                self._cheat_activated(text, False, lines)
            return
        if self.pending is not None:
            self._console_say("DeepSeek ещё думает над прошлой командой.", theme.TEXT_DIM)
            return
        if full and text.lower() in (c.lower() for c in self.game.cheats):
            self._console_say("Этот постоянный чит уже активен.", theme.TEXT_DIM)
            return
        snap = self._push_undo()
        if full:
            self.game.add_cheat(text)
            self._sync_rules()
            self._console_say("Постоянный чит включён: ECLIPSE Prime учитывает его в каждой сцене.", theme.GOOD)
            if route_for(self.app.arcade_cfg["deepseek"]) is None:
                self._cheat_activated(text, True, [])
                return
        g = self.game.s
        summary = {"страна": g["country_name"], "эпоха": self.app.eras.era(self.era_id)["short"],
                   "дата": self.game.date_text(), "деньги": round(g["money"]),
                   "известность": g["fame"], "абсурд": g["chaos"], "внимание": g.get("heat", 0),
                   "показатели": dict(g["stats"]), "постоянные_читы": list(self.game.cheats)}
        self.pending = CheatRequest(self.app.arcade_cfg["deepseek"], text, summary, permanent=full)
        self.pending_cheat = (text, full, snap)
        self._console_say("DeepSeek думает…", theme.TEXT_DIM)

    def _remove_cheat(self, index):
        if not 0 <= index < len(self.game.cheats):
            return
        self._push_undo()
        text = self.game.remove_cheat(index)
        self._sync_rules()
        self._console_say(f"Удалён /{text}", TRASH)
        self.eclipse.add_note(f"Игрок отключил чит-код «{text}»: он больше не действует, считай его отменённым.")
        if not self.game.cheats:
            self.cheat_list_open = False

    def _poll_pending(self):
        if self.pending is None or not self.pending.done:
            return
        req, self.pending = self.pending, None
        text, full, snap = self.pending_cheat or ("", False, None)
        self.pending_cheat = None
        if req.error:
            self._console_say(req.error, theme.DANGER)
            if full:
                self._cheat_activated(text, True, [])
            else:
                self._drop_undo(snap)
            return
        self._console_say(req.reply)
        lines = self.game.apply_ops(req.ops)
        for line in lines:
            self._console_say("  " + line, theme.WARN)
        self._cheat_activated(text, full, lines)

    def handle_event(self, event):
        if self._hit_event(event):
            return
        if self._slider_event(event):
            return
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            for text, rect in self.risk_plus_rects.items():
                if rect.collidepoint(event.pos):
                    self._add_suggested_cheat(text)
                    return
        if event.type == pygame.MOUSEWHEEL and self._scroll_columns(event):
            return
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if self.cheat_list_open and not (self.list_rect.collidepoint(event.pos)
                                             or self.arrow_rect.collidepoint(event.pos)):
                self.cheat_list_open = False
                return
            if self.input_rect.collidepoint(event.pos):
                self.focus = "eclipse"
            elif self.topic_rect.collidepoint(event.pos):
                self.focus = "topic"
            elif self.cheat_rect.collidepoint(event.pos):
                self.focus = "cheat"
            elif not self.term_rect.collidepoint(event.pos):
                self.focus = None
        if self.focus == "eclipse" and self._input_event(event):
            return
        if self.focus == "cheat" and self._cheat_key_event(event):
            return
        if self.focus == "topic" and self._topic_event(event):
            return
        if event.type == pygame.KEYDOWN:
            ctrl = event.mod & pygame.KMOD_CTRL
            if event.key == pygame.K_ESCAPE and self.cheat_list_open:
                self.cheat_list_open = False
                return
            if self.cheats_enabled and (event.key in CONSOLE_KEYS or (event.unicode and event.unicode in CONSOLE_CHARS)):
                self._open_card("cheats")
                self.focus = "cheat"
                self._swallow_toggle = True
                return
            if event.key == pygame.K_t and not self.anime:
                self._open_time_control()
                return
            if (event.key == pygame.K_z and ctrl) or event.key == pygame.K_BACKSPACE:
                self._undo()
                return
        for b in self.buttons:
            if b.handle_event(event):
                return
        if self.cheats_enabled and self._terminal_event(event):
            return
        if not self.eclipse.busy and self._choice_event(event):
            return
        if self._eclipse_event(event):
            return
        size = self.app.screen.get_size()
        pos = getattr(event, "pos", None)
        if event.type in (pygame.MOUSEBUTTONDOWN, pygame.MOUSEWHEEL):
            pos = pos or pygame.mouse.get_pos()
            if self._over_ui(pos):
                return
        click = self.controller.handle_event(event, size)
        if click:
            self._click_map(click, size)

    def _scroll_columns(self, event):
        pos = pygame.mouse.get_pos()
        if self.choices_rect.collidepoint(pos) and sum(b.rect.h for b in self.choice_btns) > self.choices_rect.h:
            self.choice_scroll = max(0, self.choice_scroll - event.y * 40)
            return True
        if self.stats_view.collidepoint(pos) and self.stats_max_scroll:
            self.stats_scroll = min(max(0, self.stats_scroll - event.y * 40), self.stats_max_scroll)
            return True
        return False

    def _choice_event(self, event):
        pos = getattr(event, "pos", None)
        if event.type == pygame.MOUSEBUTTONDOWN and (pos is None or not self.choices_rect.collidepoint(pos)):
            return False
        return any(b.handle_event(event) for b in self.choice_btns)

    def _set_tab(self, tab):
        self.tab = tab

    def _over_ui(self, pos):
        r = self.rects
        return any(rect.collidepoint(pos) for rect in (r["rail"], r["card"], r["controls"], r["status"], self.chip_rect,
                                                         self.list_rect if self.cheat_list_open else EMPTY))

    def _open_card(self, card):
        if card != "eclipse" and self.focus in ("eclipse", "topic"):
            self.focus = None
        if card != "cheats":
            self.cheat_list_open = False
            if self.focus == "cheat":
                self.focus = None
        self.card = card

    def _toggle_card(self, card):
        self._open_card(None if self.card == card else card)

    def _hit_event(self, event):
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            hit = next((tuple(r) for r, _, _ in reversed(self._hits) if r.collidepoint(event.pos)), None)
            self._pressed = hit
            return hit is not None
        if event.type == pygame.MOUSEBUTTONUP and event.button == 1 and self._pressed is not None:
            pressed, self._pressed = self._pressed, None
            for r, cb, _ in reversed(self._hits):
                if tuple(r) == pressed and r.collidepoint(event.pos):
                    cb()
                    break
            return True
        return False

    def _zoom(self, factor):
        size = self.app.screen.get_size()
        self.app.camera.zoom_at(factor, self.rects["view"].center, size)

    def _input_event(self, event):
        if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
            self.focus = None
            return True
        if event.type not in (pygame.TEXTINPUT, pygame.KEYDOWN):
            return False
        if event.type == pygame.KEYDOWN and event.key in (pygame.K_RETURN, pygame.K_KP_ENTER) and self.eclipse.busy:
            return True
        text = self.eclipse_input.handle_event(event)
        if text:
            self._ask(text)
        return True

    def _cheat_key_event(self, event):
        if event.type == pygame.KEYDOWN and event.key in (pygame.K_ESCAPE, pygame.K_F1):
            self.focus = None
            self.cheat_list_open = False
            return True
        if event.type == pygame.KEYDOWN and event.key == pygame.K_TAB:
            self.cheat_mode = "full" if self.cheat_mode == "single" else "single"
            return True
        if event.type == pygame.TEXTINPUT:
            if self._swallow_toggle and event.text in CONSOLE_CHARS:
                self._swallow_toggle = False
                return True
            self._swallow_toggle = False
        if event.type in (pygame.TEXTINPUT, pygame.KEYDOWN):
            text = self.console_input.handle_event(event)
            if text:
                self._submit(text)
            return True
        return False

    def _terminal_event(self, event):
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if self.cheat_list_open:
                for rect, index in self.trash_rects:
                    if rect.collidepoint(event.pos):
                        self._remove_cheat(index)
                        return True
            if self.arrow_rect.collidepoint(event.pos):
                self.cheat_list_open = not self.cheat_list_open
                return True
            for mode, rect in self.mode_rects.items():
                if rect.collidepoint(event.pos):
                    self.cheat_mode = mode
                    self.focus = "cheat"
                    return True
        pos = pygame.mouse.get_pos() if event.type == pygame.MOUSEWHEEL else getattr(event, "pos", None)
        inside = pos is not None and (self.term_rect.collidepoint(pos)
                                      or (self.cheat_list_open and self.list_rect.collidepoint(pos)))
        return inside and event.type in (pygame.MOUSEBUTTONDOWN, pygame.MOUSEBUTTONUP, pygame.MOUSEWHEEL)

    def _eclipse_event(self, event):
        if not self.eclipse.busy:
            for b in ([self.retry_btn] if self.eclipse.error else []):
                if b.handle_event(event):
                    return True
        pos = pygame.mouse.get_pos() if event.type == pygame.MOUSEWHEEL else getattr(event, "pos", None)
        if pos is None:
            return False
        if self.eclipse_rect.collidepoint(pos):
            if event.type == pygame.MOUSEWHEEL:
                self.eclipse_scroll = max(0, self.eclipse_scroll + event.y * 80)
        elif not self._over_ui(pos):
            return False
        return event.type in (pygame.MOUSEBUTTONDOWN, pygame.MOUSEBUTTONUP, pygame.MOUSEWHEEL)

    def _click_map(self, pos, size):
        hit = self._pick(pos, size)
        if hit is None:
            return
        country, region = hit
        if country is not self.target:
            self.target = country
            self.region = region
            self.fit_camera()
        elif region is not None:
            self.region = region

    def enter(self):
        self.controller.reset()
        if self.world_view:
            self.game.sync_world_stats()
        if self.game.over:
            self._over_timer = 0.3

    def _update_defeat(self, dt):
        over = self.game.over
        if not over:
            self._over_timer = None
            return
        if self._over_timer is None:
            self._over_timer = 2.5
        self._over_timer -= dt
        if self._over_timer <= 0:
            self._over_timer = math.inf
            title = ArcadeGame.DEFEAT_REASONS.get(over["reason"], "Конец игры")
            self.app.push(GameOverState(self.app, title, over["text"], self._open_load))

    def update(self, dt):
        self._anim_time += dt
        self.app.camera.update(dt)
        self.console_input.update(dt)
        self.eclipse_input.update(dt)
        self.topic_input.update(dt)
        self._sync_rules()
        self._poll_pending()
        self._flush_cheats()
        self._poll_eclipse()
        self._update_defeat(dt)
        self._update_indicators(dt)
        self._update_risk(dt)
        self._update_autosave()
        if self.toast:
            self.toast = (self.toast[0], self.toast[1] - dt) if self.toast[1] > dt else None
        if self.world_view:
            self.hover = None
            pos = pygame.mouse.get_pos()
            size = self.app.screen.get_size()
            self.hover_atom = (self.game.world.hist.atom_at(*self.app.camera.to_world(*pos, size))
                               if not self._over_ui(pos) else None)
        else:
            self.hover = self._pick(pygame.mouse.get_pos(), self.app.screen.get_size())

    def animating(self):
        if (self.eclipse.busy or self.pending is not None or self.app.camera.animating or self.toast or self.risk_k > 0
                or getattr(self, "_globe_moving", False)):
            return True
        return any(abs(a["shown"] - a["target"]) > 0.002 or a["glow"] > 0 or 0 < a["vis"] < 1 or a["timer"] > 0
                   for a in self.ind.values())

    def draw(self, surface):
        app, cam = self.app, self.app.camera
        w, h = surface.get_size()
        if h != self._win_h:
            self._win_h = h
            self._set_ec_font(self.ec_pref)
        self.rects = layout((w, h), self.card)
        self._globe_moving = cam.set_view(self.rects["view"], (w, h), smooth=0.22)
        if self.anime:
            self._draw_anime_bg(surface)
        elif self.world_view:
            self._draw_world_map(surface)
        else:
            app.renderer.render(surface, cam, focus=self.target.index)

            if self.region:
                app.renderer.highlight_region(surface, cam, self.region, fill=theme.ACCENT_DIM)
            hover_country, hover_region = self.hover or (None, None)
            if hover_country is self.target and hover_region and hover_region is not self.region:
                app.renderer.highlight_region(surface, cam, hover_region, fill=theme.LAND_HOVER)
            elif hover_country is not None and hover_country is not self.target:
                app.renderer.highlight_country(surface, cam, hover_country.index, fill=theme.LAND_HOVER)
            app.renderer.highlight_country(surface, cam, self.target.index, outline=theme.COAST, width=2)
            if self.home is not self.target:
                app.renderer.highlight_country(surface, cam, self.home.index, outline=theme.ACCENT, width=1)

        self._hits, self.ui_tip = [], None
        self._hide_sections()
        self._draw_card(surface)
        self._draw_rail(surface)
        self._draw_chip(surface)
        self._draw_controls(surface)
        self._draw_status(surface)

        if self.toast:
            img = text_surface(self.toast[0], 18, theme.WARN, bold=True)
            view = self.rects["view"]
            box = img.get_rect(center=(view.centerx, view.y + 84)).inflate(24, 12)
            fill_round(surface, box, (14, 14, 17), 240, 10)
            pygame.draw.rect(surface, theme.WARN, box, 1, border_radius=10)
            surface.blit(img, img.get_rect(center=box.center))

        if self.ui_tip:
            draw_tooltip(surface, [(self.ui_tip, theme.TEXT, 14, False)], pygame.mouse.get_pos())
        elif self._over_ui(pygame.mouse.get_pos()):
            pass
        elif self.world_view and self.hover_atom is not None and not cam.animating and not self.cheat_list_open:
            self._draw_world_tooltip(surface)
        elif self.hover and not cam.animating and not self.cheat_list_open:
            country, region = self.hover
            title = region.display_name if country is self.target and region else self._name(country)
            hint = "регион" if country is self.target and region else "ЛКМ: выбрать целью"
            draw_tooltip(surface, [(title, theme.TEXT, 16, True), (hint, theme.TEXT_DIM, 13, False)],
                         pygame.mouse.get_pos())

    def _draw_anime_bg(self, surface):
        if self.app.gpu is None:
            surface.fill(theme.OCEAN)
        title = self.anime["card"].get("title_ru") or self.anime["card"].get("title") or ""
        size = 96
        font = fonts.get(size, True)
        while font.size(title)[0] > surface.get_width() * 0.7 and size > 28:
            size -= 6
            font = fonts.get(size, True)
        img = font.render(title, True, theme.mix(theme.OCEAN, theme.TEXT, 0.10))
        surface.blit(img, img.get_rect(center=(surface.get_width() // 2, surface.get_height() // 2)))

    def _world_layer(self):
        w = self.game.world
        layer = hloader.layer(self.app, w.era)
        if layer.set_world(w, empire=True) or self._labels_key != (id(w), w.version):
            state, top, color = layer.arrays()
            self._labels = w.hist.labels_for(state, color)
            self._labels_key = (id(w), w.version)
        return layer

    def _draw_world_map(self, surface):
        w = self.game.world
        layer = self._world_layer()
        hl = -1
        if self.hover_atom is not None:
            hl = layer.color_key(self.hover_atom) or -1
        layer.render(surface, self.app.camera, highlight=hl)
        ui = [self.rects["rail"], self.rects["card"], self.rects["controls"], self.rects["status"], self.chip_rect]
        year = w.date_year()
        draw_labels(surface, self.app, self.app.camera, self._labels, lambda k: w.polity(k).at(year), year, ui)

    def _draw_world_tooltip(self, surface):
        w = self.game.world
        atom = self.hover_atom
        owner = int(w.owner[atom])
        if not owner:
            title, sub = "Ничья земля", w.region_name(atom)
        else:
            title = w.title(owner)
            root = w.root(owner)
            sub = w.region_name(atom) + (f" · под властью: {w.title(root)}" if root != owner else "")
        lines = [(title, theme.TEXT, 16, True), (sub, theme.TEXT_DIM, 13, False)]
        city = w.city_at(atom)
        if city:
            lines.append((f"Город {city['ru']}: {fmt.people(city['pop'])}", theme.TEXT_DIM, 13, False))
        draw_tooltip(surface, lines, pygame.mouse.get_pos())

    def _hide_sections(self):
        self._hide_side(keep_list=self.card == "cheats")
        self._hide_stats()
        self.eclipse_rect = self.input_rect = self.font_slider = self.font_track = EMPTY
        self.retry_btn.rect = EMPTY
        for b in (self.menu_btn, self.settings_btn, self.shop_btn, self.realm_btn, *self.tab_btns.values()):
            b.rect = EMPTY

    def _card_title(self, surface, card, title):
        draw_text(surface, title.upper(), (card.x + 18, card.y + 16), 12, theme.ACCENT, bold=True)
        return card.y + 42

    def _draw_card(self, surface):
        c, kind = self.rects["card"], self.card
        if not kind:
            return
        draw_panel(surface, c, alpha=250, border=None)
        if kind == "eclipse":
            x, w = c.x + 14, c.w - 28
            actions_top = self._draw_choices(surface, x, w, c.y + int(c.h * 0.5), c.bottom - 14)
            pygame.draw.line(surface, theme.PANEL_BORDER, (x, actions_top - 10), (x + w, actions_top - 10))
            self.eclipse_rect = pygame.Rect(c.x, c.y, c.w, actions_top - 14 - c.y)
            self._draw_eclipse(surface, self.eclipse_rect, panel=False)
        elif kind == "news":
            self._draw_feed(surface, pygame.Rect(c.x + 18, c.y + 16, c.w - 36, c.h - 28))
        elif kind == "stats":
            self._draw_stats(surface, c, controls=False)
        elif kind == "cheats":
            self.term_rect = pygame.Rect(c.x + 12, c.y + 46, c.w - 24, c.h - 58)
            self._draw_terminal(surface, self.term_rect)
            if self.cheat_list_open:
                self._draw_cheat_list(surface)
            else:
                self.list_rect, self.trash_rects = EMPTY, []
        elif kind == "menu":
            self._draw_menu_card(surface, c)
        close = pygame.Rect(c.right - 38, c.y + 8, 30, 30)
        hot = close.collidepoint(pygame.mouse.get_pos())
        if hot:
            fill_round(surface, close, theme.TEXT, 22, 4)
        icons.draw(surface, "close", close, theme.TEXT if hot else theme.TEXT_DIM, 16)
        self._hits.append((close, lambda: self._open_card(None), "Скрыть карточку"))

    def _draw_menu_card(self, surface, c):
        x, w = c.x + 18, c.w - 36
        y = c.y + 18
        draw_spaced(surface, "WRLDSIM", (x, y + 10), 18, theme.TEXT, anchor="midleft")
        session = self.app.session
        if session:
            mode = self.app.modes["modes"][session.mode_id]
            label = mode["name"]
            if session.difficulty_id:
                label += " · " + mode["difficulties"][session.difficulty_id]["name"]
            if session.mode_id != "anime":
                label += " · " + self.app.eras.era(session.era_id)["short"]
            draw_text(surface, ellipsize(label, w, fonts.get(14, True)), (x, y + 30), 14, theme.ACCENT, bold=True)
        y += 64
        pygame.draw.line(surface, theme.PANEL_BORDER, (x, y), (x + w, y))
        y += 14
        self.save_btn.enabled = not self.game.over
        self.settings_btn.text = "Настройки"
        for b in (self.save_btn, self.load_btn, self.world_btn, self.settings_btn, self.menu_btn):
            b.rect = pygame.Rect(x, y, w, 40)
            b.draw(surface)
            y += 48
        y += 10
        keys = ["T: TIME CONTROL"] if not self.anime else []
        if self.game.rules.get("allow_turn_undo"):
            keys.append("Ctrl+Z: откат")
        if self.cheats_enabled:
            keys.append("`: чит-терминал")
        for line in wrap("   ·   ".join(keys), w, 12):
            draw_text(surface, line, (x, y), 12, theme.TEXT_MUTED)
            y += 16

    def _rail_items(self):
        items = [("menu", "Меню: сохранить, загрузить, выход", "menu", None, True),
                 ("eclipse", "ECLIPSE Prime: сцена и варианты действий", "chat", None, True),
                 ("news", "Новости", "news", None, True),
                 ("stats", "Показатели", "stats", None, True)]
        if self.cheats_enabled:
            items.append(("cheats", "Чит-терминал", "terminal", None, True))
        tools = []
        if self.world_view:
            ok = self.game.realm_open and not self.game.over
            tools.append(("realm", "Управление государством" if ok else "Управление: только для правителей",
                          "realm", self._open_realm, ok))
        if not self.anime:
            tools.append(("shop", "Магазин", "shop", self._open_shop, not self.game.over))
        return items, tools

    def _draw_rail(self, surface):
        rail = self.rects["rail"]
        surface.fill(theme.RAIL, rail)
        pygame.draw.line(surface, theme.PANEL_BORDER, (rail.right - 1, rail.y), (rail.right - 1, rail.bottom))
        mouse = pygame.mouse.get_pos()
        items, tools = self._rail_items()

        def item(y, key, tip, icon, action, ok):
            r = pygame.Rect(rail.x, y, rail.w, RAIL_ITEM_H)
            hot = ok and r.collidepoint(mouse)
            selected = action is None and self.card == key
            glow = self._rail_glow.setdefault(key, Glow())
            h, p, a = glow.step(1.0 if hot else 0.0, 1.0 if hot and self._pressed == tuple(r) else 0.0,
                                1.0 if selected else 0.0)
            fill = sweep_of(h, a)
            if fill > 0.01:
                draw_glass_control(surface, r.inflate(-10, -6), 4, hover=h, press=p, accent=a)
            if selected:
                pygame.draw.rect(surface, theme.ACCENT, (rail.x, r.y + 10, 3, r.h - 20))
            color = text_on(fill) if fill > 0.55 else theme.TEXT if hot else theme.TEXT_DIM if ok else theme.TEXT_MUTED
            icons.draw(surface, icon, r, color, 24)
            if ok:
                self._hits.append((r, action or (lambda k=key: self._toggle_card(k)), tip))
            if r.collidepoint(mouse):
                self.ui_tip = tip

        y = rail.y + 6
        for it in items:
            item(y, *it)
            y += RAIL_ITEM_H
        if tools:
            y += 6
            pygame.draw.line(surface, theme.PANEL_BORDER, (rail.x + 12, y), (rail.right - 12, y))
            y += 7
            for it in tools:
                item(y, *it)
                y += RAIL_ITEM_H
        item(rail.bottom - RAIL_ITEM_H - 4, "settings", "Настройки", "settings", self._open_settings, True)

    def _draw_chip(self, surface):
        w = surface.get_width()
        parts = []
        if w >= 1000 or self.anime:
            parts.append(text_surface(self.game.date_text(), 15, theme.TEXT_DIM))
        if not self.anime:
            parts.append(text_surface(fmt.usd(self.game.money), 17, theme.GOOD, bold=True))
        time_w = 0 if self.anime else 150
        undo_w = 104 if self.game.rules.get("allow_turn_undo") else 0
        inner = sum(img.get_width() + 18 for img in parts) + time_w + (undo_w + 8 if undo_w else 0)
        chip = pygame.Rect(w - CARD_GAP - inner - 16, CARD_GAP, inner + 16, 46)
        self.chip_rect = chip
        draw_panel(surface, chip, alpha=250, border=None)
        x = chip.x + 12
        for img in parts:
            surface.blit(img, img.get_rect(midleft=(x, chip.centery)))
            x += img.get_width() + 18
        if time_w:
            self.time_btn.rect = pygame.Rect(x, chip.y + 6, time_w, chip.h - 12)
            self.time_btn.size = 15
            self.time_btn.enabled = not self.game.over
            self.time_btn.draw(surface)
            x += time_w + 8
        if undo_w:
            self.undo_btn.rect = pygame.Rect(x, chip.y + 6, undo_w, chip.h - 12)
            self.undo_btn.size = 14
            self.undo_btn.enabled = self.can_undo
            self.undo_btn.draw(surface)

    def _toggle_globe(self):
        self.app.set_globe(not self.app.prefs.get("globe", True))
        self.fit_camera(instant=True)

    def _draw_controls(self, surface):
        box = self.rects["controls"]
        mouse = pygame.mouse.get_pos()
        gpu = self.app.gpu is not None
        globe_tip = ("Плоская карта" if self.app.globe_on else "3D-глобус") if gpu else "3D-глобус: нужна видеокарта"
        for i, (icon, tip, action, ok) in enumerate((
                ("globe", globe_tip, self._toggle_globe, gpu),
                ("home", "К своей стране", self._go_home, True),
                ("plus", "Крупнее", lambda: self._zoom(1.4), True),
                ("minus", "Мельче", lambda: self._zoom(1 / 1.4), True))):
            r = pygame.Rect(box.x, box.y + i * (CTRL + 6), CTRL, CTRL)
            hot = r.collidepoint(mouse)
            pressed = hot and self._pressed == tuple(r)
            on = icon == "globe" and self.app.globe_on
            draw_round_button(surface, r, hover=hot, press=pressed, active=on, enabled=ok)
            icons.draw(surface, icon, r, theme.TEXT if ok else theme.TEXT_MUTED, 20)
            if ok:
                self._hits.append((r, action, tip))
            if hot:
                self.ui_tip = tip

    def _draw_status(self, surface):
        bar = self.rects["status"]
        surface.fill(theme.RAIL, bar)
        pygame.draw.line(surface, theme.PANEL_BORDER, (bar.x, bar.y), (bar.right, bar.y))
        mouse = pygame.mouse.get_pos()
        cam = self.app.camera
        left = ""
        if not self._over_ui(mouse):
            if self.world_view and self.hover_atom is not None:
                w = self.game.world
                owner = int(w.owner[self.hover_atom])
                left = (w.title(owner) if owner else "Ничья земля") + "  ·  " + w.region_name(self.hover_atom)
            elif self.hover:
                country, region = self.hover
                left = self._name(country) + (f"  ·  {region.display_name}" if region else "")
            wx, wy = cam.to_world(*mouse, surface.get_size())
            lat, lon = -wy, (wx + 180) % 360 - 180
            coords = f"{abs(lat):.2f}° {'с. ш.' if lat >= 0 else 'ю. ш.'}   {abs(lon):.2f}° {'в. д.' if lon >= 0 else 'з. д.'}"
        else:
            coords = ""
        draw_text(surface, ellipsize(left, bar.w // 2, fonts.get(12)), (RAIL_W + 12, bar.centery), 12, theme.TEXT_DIM,
                  anchor="midleft")
        right = "   ·   ".join(t for t in (coords, f"масштаб ×{cam.zoom:.1f}") if t)
        draw_text(surface, right, (bar.right - 12, bar.centery), 12, theme.TEXT_DIM, anchor="midright")

    def _hide_side(self, keep_list=False):
        self.term_rect = self.cheat_rect = self.arrow_rect = self.topic_rect = EMPTY
        self.choices_rect = EMPTY
        self.mode_rects = {}
        if not keep_list:
            self.list_rect, self.trash_rects = EMPTY, []
            self.cheat_list_open = False
        self.choice_mode_btn.rect = self.topic_send_btn.rect = EMPTY
        for b in self.choice_btns:
            b.rect = EMPTY

    def _hide_stats(self):
        self.world_btn.rect = self.save_btn.rect = self.load_btn.rect = self.undo_btn.rect = EMPTY
        self.time_btn.rect = self.stats_view = EMPTY

    def _draw_feed(self, surface, rect):
        draw_text(surface, "НОВОСТИ", (rect.x, rect.y), 12, theme.ACCENT, bold=True)
        y, bottom = rect.y + 22, rect.bottom
        width = rect.w - DATE_COL_W
        line_h = fonts.get(14).get_linesize()
        prev = surface.get_clip()
        surface.set_clip(pygame.Rect(rect.x, y, rect.w, max(0, bottom - y)).clip(prev))
        for minute, text, kind in reversed(self.game.s["log"]):
            if y >= bottom:
                break
            draw_text(surface, self.game.date_short(self.game.at(minute)), (rect.x, y + 1), 12, theme.TEXT_MUTED)
            for line in wrap(text, width, 14):
                draw_text(surface, line, (rect.x + DATE_COL_W, y), 14, getattr(theme, LOG_COLORS.get(kind, "TEXT")))
                y += line_h
            y += 4
        surface.set_clip(prev)

    def _wrap(self, text, width, size):
        key = (text, width, size)
        lines = self._wrap_cache.get(key)
        if lines is None:
            if len(self._wrap_cache) > 400:
                self._wrap_cache.clear()
            lines = self._wrap_cache[key] = wrap(text, width, size)
        return lines

    def _eclipse_blocks(self, width):
        ec = self.eclipse
        blocks = []
        pad = self.ec_pad
        line_h = fonts.get(self.ec_font).get_linesize()
        bubble_w = int(width * 0.86) - 2 * pad
        last_ai = max((i for i, (k, _) in enumerate(ec.transcript) if k == "ai"), default=-1)
        for i, (kind, text) in enumerate(ec.transcript):
            if kind == "fx":
                continue
            if kind == "me" and text.startswith(CHEAT_ICON):
                lines = self._wrap(text[len(CHEAT_ICON):].lstrip(), bubble_w - self.ec_font, self.ec_font)
                blocks.append(("cheat", lines, len(lines) * line_h + 2 * pad))
                continue
            lines = self._wrap(text, bubble_w, self.ec_font)
            blocks.append((kind if i != last_ai else "ai_last", lines, len(lines) * line_h + 2 * pad))
        if ec.error:
            lines = self._wrap(ec.error, bubble_w, self.ec_font_sm)
            blocks.append(("err", lines, len(lines) * fonts.get(self.ec_font_sm).get_linesize() + 2 * pad))
        elif ec.busy or not blocks:
            blocks.append(("wait", [], line_h + 2 * pad))
        return blocks

    def _draw_eclipse_header(self, surface, rect):
        ec = self.eclipse
        compact = self.ec_compact
        cy = rect.y + (30 if compact else 40)
        text_x = rect.x + 22
        title_size = 20 if compact else EC_TITLE
        self._draw_shimmer_title(surface, "ECLIPSE PRIME", (text_x, cy - (9 if compact else 12)), title_size, ec.busy)
        if ec.error:
            dot, status = theme.DANGER, "нет связи"
        elif ec.busy:
            dots = "." * (1 + int(self._anim_time * 3) % 3)
            dot, status = theme.WARN, f"думает{dots}  {int(time.monotonic() - ec.started)} с"
        else:
            dot, status = theme.GOOD, "на связи · ведущий игры"
        dot_a = int(160 + 95 * (0.5 + 0.5 * math.sin(self._anim_time * 6))) if ec.busy else 255
        dot_d = 8 if compact else 10
        dot_y = cy + (13 if compact else 18)
        fill_round(surface, pygame.Rect(text_x + 1, dot_y, dot_d, dot_d), dot, dot_a, dot_d // 2)
        draw_text(surface, status, (text_x + dot_d + 9, dot_y + dot_d // 2), self.ec_status, theme.TEXT_DIM,
                  anchor="midleft")
        line_y = rect.y + (58 if compact else 82)
        key = ("eclipse_rule", rect.w, theme.ACCENT)
        img = self._wrap_cache.get(key)
        if img is None:
            img = pygame.Surface((rect.w - 28, 2), pygame.SRCALPHA)
            for x in range(img.get_width()):
                a = int(220 * (1 - x / img.get_width()) ** 1.6)
                img.fill((*theme.ACCENT, a), (x, 0, 1, 2))
            self._wrap_cache[key] = img
        surface.blit(img, (rect.x + 14, line_y))
        return self._draw_font_slider(surface, rect, line_y + (6 if compact else 10))

    def _draw_shimmer_title(self, surface, text, pos, size, busy):
        # Переливание: от тёмного оттенка акцента к светлому, по буквам бежит блик; пока ведущий думает - быстрее.
        # Надпись рисуется один раз белой маской и каждый кадр умножается на полосу градиента.
        key = ("shimmer_mask", text, size)
        mask = self._wrap_cache.get(key)
        if mask is None:
            gap = int(size * 0.18)
            chars = [text_surface(ch, size, (255, 255, 255), True) for ch in text]
            mask = pygame.Surface((sum(c.get_width() for c in chars) + gap * (len(chars) - 1),
                                   max(c.get_height() for c in chars)), pygame.SRCALPHA)
            x = 0
            for c in chars:
                mask.blit(c, (x, 0))
                x += c.get_width() + gap
            self._wrap_cache[key] = mask
        w, h = mask.get_size()
        u = np.linspace(0.0, 1.0, w, dtype=np.float32)
        p = (self._anim_time * (0.9 if busy else 0.28)) % 1.8 - 0.4
        k = np.exp(-((u - p) / 0.11) ** 2)[:, None]
        dark = np.array(theme.mix(theme.ACCENT, theme.GLASS_COLOR, 0.25), np.float32)
        light = np.array(theme.mix(theme.ACCENT, (255, 255, 255), 0.45), np.float32)
        shine = np.array(theme.mix(theme.ACCENT, (255, 255, 255), 0.85), np.float32)
        row = dark + (light - dark) * u[:, None]
        row = (row + (shine - row) * k).astype(np.uint8)
        strip = pygame.Surface((w, 1), pygame.SRCALPHA)
        pygame.surfarray.pixels3d(strip)[:, 0, :] = row
        pygame.surfarray.pixels_alpha(strip)[:] = 255
        img = mask.copy()
        img.blit(pygame.transform.scale(strip, (w, h)), (0, 0), special_flags=pygame.BLEND_RGBA_MULT)
        surface.blit(img, img.get_rect(midleft=pos))

    def _draw_font_slider(self, surface, rect, y):
        row_h = 28 if self.ec_compact else EC_SLIDER_H
        cy = y + row_h // 2
        label = draw_text(surface, "Шрифт", (rect.x + 22, cy), 15, theme.TEXT_DIM, anchor="midleft")
        small = draw_text(surface, "A", (label.right + 16, cy), 14, theme.TEXT_MUTED, anchor="midleft")
        big = draw_text(surface, "A", (rect.right - 22, cy), 24, theme.TEXT_MUTED, anchor="midright")
        track = pygame.Rect(small.right + 16, cy - 3, max(40, big.x - 16 - small.right - 16), 6)
        lo, hi = settings.ECLIPSE_FONT_MIN, settings.ECLIPSE_FONT_MAX
        frac = (self.ec_pref - lo) / (hi - lo)
        knob_x = track.x + int(track.w * frac)
        hot = self.font_drag or track.inflate(24, 24).collidepoint(pygame.mouse.get_pos())
        fill_round(surface, track, (255, 255, 255), 30, 3)
        fill_round(surface, pygame.Rect(track.x, track.y, max(6, knob_x - track.x), track.h), theme.ACCENT, 220, 3)
        r = 10 if hot else 8
        fill_round(surface, pygame.Rect(knob_x - r, cy - r, 2 * r, 2 * r), theme.TEXT, 255, r)
        if self.font_drag:
            draw_text(surface, str(self.ec_pref), (knob_x, cy - 14), 13, theme.TEXT, anchor="midbottom")
        self.font_track = track
        self.font_slider = track.inflate(24, 24)
        return y + row_h + 6

    def _draw_eclipse(self, surface, rect, panel=True):
        ec = self.eclipse
        self.ec_compact = rect.h < 560 or rect.w < 440
        self.ec_status = 15 if self.ec_compact else EC_STATUS
        if panel:
            draw_panel(surface, rect, alpha=240, border=theme.ACCENT)
        top = self._draw_eclipse_header(surface, rect)

        inner_w = rect.w - 28
        self.input_rect = pygame.Rect(rect.x + 14, rect.bottom - self.ec_input_h - 14, inner_w, self.ec_input_h)
        y = self.input_rect.y - 10
        self.retry_btn.size = self.ec_status
        buttons = [self.retry_btn] if ec.error else []
        if not buttons:
            self.retry_btn.rect = EMPTY
        for b in reversed(buttons):
            h = b.height(inner_w)
            y -= h
            b.rect = pygame.Rect(rect.x + 14, y, inner_w, h)
            b.enabled = not ec.busy
            y -= 8
        area = pygame.Rect(rect.x + 14, top, inner_w, max(60, y - top))

        blocks = self._eclipse_blocks(area.w)
        total = sum(h for _, _, h in blocks) + EC_GAP * max(0, len(blocks) - 1)
        max_scroll = max(0, total - area.h)
        self.eclipse_scroll = min(max(self.eclipse_scroll, 0), max_scroll)
        self._scroll_view += (self.eclipse_scroll - self._scroll_view) * 0.25
        if abs(self._scroll_view - self.eclipse_scroll) < 0.5:
            self._scroll_view = self.eclipse_scroll

        if self._typed_version != ec.version:
            self._typed_version, self._typed_at = ec.version, time.monotonic()
        typed = int((time.monotonic() - self._typed_at) * EC_TYPE_CPS)

        prev_clip = surface.get_clip()
        surface.set_clip(area.clip(prev_clip) if prev_clip else area)
        by = area.bottom + int(self._scroll_view)
        for kind, lines, h in reversed(blocks):
            by -= h
            if by + h >= area.top and by <= area.bottom:
                self._draw_block(surface, area, by, kind, lines, h, typed)
            by -= EC_GAP
            if by + EC_GAP < area.top - 2000:
                break
        surface.set_clip(prev_clip)
        if max_scroll and self.eclipse_scroll < max_scroll:
            draw_text(surface, "↑ колесо: история", (area.right, area.top), self.ec_status - 4, theme.TEXT_MUTED,
                      anchor="topright")

        for b in buttons:
            b.draw(surface)
        self._draw_custom_input(surface)
        self._draw_risk_popup(surface)

    def _custom_risk(self):
        # Совпало с вариантом ECLIPSE - берём его оценку риска, иначе оценка по ключевым словам.
        text = " ".join(self.eclipse_input.text.split())
        if text != self._risk_cache[0]:
            choice = next((c for c in self.eclipse.choices if c["text"].lower() == text.lower()), None)
            if choice:
                found = Assessment(choice["risk"], choice["warning"] or "Рискованное действие.", tuple(choice["cheats"]))
            else:
                found = assess(text)
            self._risk_cache = (text, found)
        found = self._risk_cache[1]
        return found if found.risk >= WARN_FROM else None

    def _update_risk(self, dt):
        found = self._custom_risk() if self.cheats_enabled else None
        if found:
            self.risk_view = found
        target = glitch_strength(found.risk) if found else 0.0
        self.risk_k += (target - self.risk_k) * min(1.0, dt * 8)
        if not found and self.risk_k < 0.01:
            self.risk_k = 0.0
        self.input_glitch.k = self.risk_k
        self.input_glitch.update(dt)

    def _draw_custom_input(self, surface):
        inp, rect = self.eclipse_input, self.input_rect
        if self.risk_k > 0.02:
            self._draw_alarm_input(surface)
            return
        inp.rect, inp.radius, inp.caret = rect, self.ec_input_h // 2, self.focus == "eclipse"
        inp.draw(surface, INPUT_HINT)
        if inp.text:
            draw_text(surface, "Enter", (rect.right - 22, rect.centery), self.ec_status - 2,
                      theme.ACCENT if not self.eclipse.busy else theme.TEXT_MUTED, anchor="midright")

    def _draw_alarm_input(self, surface):
        rect, inp, k = self.input_rect, self.eclipse_input, self.risk_k
        img = alarm_frame(rect.size, k, self._anim_time, rect.h // 2)
        inner = pygame.Rect(0, 0, rect.w, rect.h).inflate(-20 - rect.h // 4, 0)
        if inp.text:
            inner.w -= 64
            line = text_surface(inp.text, self.ec_font)
        else:
            line = text_surface(INPUT_HINT, self.ec_font, theme.TEXT_MUTED)
        offset = max(0, line.get_width() - inner.w + 4) if inp.text else 0
        y = inner.centery - line.get_height() // 2
        img.set_clip(inner)
        img.blit(line, (inner.x - offset, y))
        if self.focus == "eclipse" and inp._blink < 0.5:
            cx = inner.x + (line.get_width() - offset if inp.text else 0) + 1
            pygame.draw.line(img, theme.TEXT, (cx, y + 3), (cx, y + line.get_height() - 3))
        img.set_clip(None)
        if inp.text:
            draw_text(img, "Enter", (rect.w - 22, rect.h // 2), self.ec_status - 2,
                      theme.WARN if not self.eclipse.busy else theme.TEXT_MUTED, anchor="midright")
        self.input_glitch.blit(surface, img, rect.topleft)

    def _draw_risk_popup(self, surface):
        self.risk_plus_rects = {}
        k = self.risk_k
        if k <= 0.02:
            return
        found, rect = self.risk_view, self.input_rect
        pad, line_h = 14, fonts.get(15).get_linesize() + 2
        color = theme.mix(theme.WARN, (255, 40, 50), k)
        text_w = rect.w - 2 * pad
        reason = wrap(found.reason or "Рискованное действие.", text_w, 15)
        cheats = list(found.cheats[:2])
        height = 14 + 22 + 8 + len(reason) * line_h + ((12 + 16 + len(cheats) * 34) if cheats else 0) + 10
        appear = min(1.0, k * 5)
        box = pygame.Rect(rect.x, rect.y - 10 - height + int((1 - appear) * 14), rect.w, height)
        img = alarm_frame(box.size, k, self._anim_time, theme.RADIUS_SM + 4)
        draw_spaced(img, level_name(found.risk), (pad, 24), 13, color, spacing=0.2, anchor="midleft")
        draw_text(img, f"РИСК {found.risk}%", (box.w - pad, 24), 13, theme.TEXT_DIM, anchor="midright")
        bar = pygame.Rect(pad, 38, text_w, 4)
        fill_round(img, bar, (255, 255, 255), 24, 2)
        fill_round(img, pygame.Rect(bar.x, bar.y, max(4, bar.w * found.risk // 100), bar.h), color, 230, 2)
        y = 50
        for line in reason:
            draw_text(img, line, (pad, y), 15, theme.mix(theme.TEXT, color, 0.35))
            y += line_h
        row_tops = []
        if cheats:
            y += 6
            pygame.draw.line(img, (70, 40, 44), (pad, y), (box.w - pad, y))
            draw_text(img, "ЧИТ ДЛЯ ОБХОДА РИСКА", (pad, y + 8), 11, theme.WARN, bold=True)
            y += 24
            mono = fonts.mono(14)
            active = {c.lower() for c in self.game.cheats}
            for text in cheats:
                done = text.lower() in active
                label = ellipsize("/" + text, text_w - 44, mono)
                img.blit(mono.render(label, True, theme.TEXT_MUTED if done else theme.TEXT), (pad + 6, y + 8))
                row_tops.append((text, y, done))
                y += 34
        img.set_alpha(int(255 * appear))
        surface.blit(img, box.topleft)
        mouse = pygame.mouse.get_pos()
        for text, top, done in row_tops:
            btn = pygame.Rect(box.right - pad - 34, box.y + top + 1, 34, 28)
            self.risk_plus_rects[text] = btn
            hot = btn.collidepoint(mouse) and not done
            fill_round(surface, btn, theme.GOOD if done else theme.ACCENT, int((200 if hot else 120) * appear), 9)
            cx, cy = btn.center
            if done:
                pygame.draw.lines(surface, theme.TEXT, False, [(cx - 7, cy), (cx - 2, cy + 5), (cx + 8, cy - 6)], 3)
            else:
                pygame.draw.line(surface, theme.TEXT, (cx - 7, cy), (cx + 7, cy), 3)
                pygame.draw.line(surface, theme.TEXT, (cx, cy - 7), (cx, cy + 7), 3)

    def _draw_block(self, surface, area, y, kind, lines, h, typed):
        if kind == "fx":
            text = lines[0]
            color = theme.GOOD if "+" in text else theme.DANGER if "−" in text or "-" in text else theme.WARN
            img = text_surface("•  " + text, self.ec_fx, color)
            pill = pygame.Rect(area.x + 18, y, img.get_width() + 32, h)
            fill_round(surface, pill, color, 34, h // 2)
            surface.blit(img, img.get_rect(midleft=(pill.x + 16, pill.centery)))
            return
        pad = self.ec_pad
        size = self.ec_font_sm if kind == "err" else self.ec_font
        width = max(text_surface(line, size).get_width() for line in lines) if lines else 120
        icon = self.ec_font if kind == "cheat" else 0
        bw = width + 2 * pad + icon
        if kind in ("me", "cheat"):
            bubble = pygame.Rect(area.right - bw, y, bw, h)
            fill_round(surface, bubble, theme.ACCENT, 92, 22)
            color = theme.TEXT
            if icon:
                r = int(self.ec_font * 0.4)
                c = (bubble.x + pad + r, y + pad + fonts.get(self.ec_font).get_linesize() // 2)
                pygame.draw.circle(surface, theme.GOOD, c, r)
                pygame.draw.lines(surface, theme.OCEAN, False, [(c[0] - r // 2, c[1]), (c[0] - r // 6, c[1] + r // 2),
                                                               (c[0] + r // 2, c[1] - r // 2)], max(2, r // 4))
        elif kind == "err":
            bubble = pygame.Rect(area.x, y, bw, h)
            fill_round(surface, bubble, theme.DANGER, 40, 22)
            color = theme.DANGER
        else:
            bubble = pygame.Rect(area.x, y, max(bw, 140), h)
            fill_round(surface, bubble, (255, 255, 255), 16, 22)
            fill_round(surface, pygame.Rect(bubble.x, bubble.y + 14, 4, bubble.h - 28), theme.ACCENT, 230, 2)
            color = theme.TEXT
        if kind == "wait":
            for i in range(3):
                k = 0.5 + 0.5 * math.sin(self._anim_time * 6 - i * 0.9)
                fill_round(surface, pygame.Rect(bubble.x + 30 + i * 26, bubble.centery - 7 - int(5 * k), 14, 14),
                           theme.TEXT, int(90 + 150 * k), 7)
            return
        line_h = fonts.get(size).get_linesize()
        ty = y + pad
        left = typed if kind == "ai_last" else None
        for line in lines:
            if left is not None:
                if left <= 0:
                    break
                shown, left = line[:left], left - len(line) - 1
            else:
                shown = line
            draw_text(surface, shown, (bubble.x + pad + icon + (4 if kind.startswith("ai") else 0), ty), size, color)
            ty += line_h

    def _draw_side(self, surface, rect):
        x, w = rect.x + 14, rect.w - 28
        y = rect.y + 14
        if self.cheats_enabled:
            term_h = int(min(300, max(150 if rect.h < 520 else 220, rect.h * 0.3)))
            self.term_rect = pygame.Rect(x, y, w, term_h)
            self._draw_terminal(surface, self.term_rect)
            y = self.term_rect.bottom + 14
        else:
            self.term_rect = self.cheat_rect = self.arrow_rect = EMPTY
        actions_top = self._draw_choices(surface, x, w, y, rect.bottom - 14)
        if actions_top - y > 70:
            self._draw_feed(surface, pygame.Rect(x + 2, y, w - 4, actions_top - y - 18))
            pygame.draw.line(surface, theme.PANEL_BORDER, (x, actions_top - 10), (x + w, actions_top - 10))
        if self.cheats_enabled and self.cheat_list_open:
            self._draw_cheat_list(surface)
        else:
            self.list_rect, self.trash_rects = EMPTY, []

    def _draw_choices(self, surface, x, w, top_limit, bottom):
        ec = self.eclipse
        size = 14 if bottom - top_limit < 330 else CHOICE_FONT
        gap = 6 if size < CHOICE_FONT else 8
        for b in self.choice_btns:
            b.size = size
        heights = [b.height(w) for b in self.choice_btns]
        total = sum(heights) + gap * max(0, len(heights) - 1)
        free = bottom - top_limit - 78
        area_h = 30 if not self.choice_btns else total if total <= free else max(100, free)
        self.choices_rect = pygame.Rect(x, bottom - area_h, w, area_h)
        self.choice_scroll = min(max(self.choice_scroll, 0), max(0, total - area_h))
        if not self.choice_btns:
            note = "ECLIPSE Prime думает…" if ec.busy else "Вариантов нет: напишите своё действие выше"
            draw_text(surface, note, (x + w // 2, self.choices_rect.centery), 14, theme.TEXT_MUTED, anchor="center")
        prev = surface.get_clip()
        surface.set_clip(self.choices_rect.clip(prev))
        y = self.choices_rect.y - self.choice_scroll
        for b, h in zip(self.choice_btns, heights):
            b.rect = pygame.Rect(x, y, w, h)
            b.enabled = not ec.busy
            if b.rect.bottom > self.choices_rect.top and b.rect.top < self.choices_rect.bottom:
                b.draw(surface)
            y += h + gap
        surface.set_clip(prev)
        if total > area_h:
            track = pygame.Rect(self.choices_rect.right - 4, self.choices_rect.y, 3, area_h)
            thumb_h = max(24, area_h * area_h // total)
            thumb_y = track.y + (area_h - thumb_h) * self.choice_scroll // (total - area_h)
            fill_round(surface, pygame.Rect(track.x, thumb_y, 3, thumb_h), theme.ACCENT, 200, 1)
        self.topic_rect = pygame.Rect(x, self.choices_rect.y - 10 - 36, w - 46, 36)
        focused = self.focus == "topic"
        label, hint, _, _ = CHOICE_MODES[self.choice_mode]
        self.topic_input.rect = self.topic_rect
        self.topic_input.radius = 18
        self.topic_input.caret = focused
        self.topic_input.draw(surface, hint)
        self.topic_send_btn.rect = pygame.Rect(self.topic_rect.right + 8, self.topic_rect.y, 38, 36)
        self.topic_send_btn.enabled = bool(self.topic_input.text.strip()) and not ec.busy and not self.game.over
        self.topic_send_btn.draw(surface)
        top = self.topic_rect.y - 32
        draw_text(surface, "ДЕЙСТВИЯ", (x + 2, top + 6), 12, theme.ACCENT, bold=True)
        self.choice_mode_btn.text = label
        self.choice_mode_btn.rect = pygame.Rect(x + w - 112, top, 112, 26)
        self.choice_mode_btn.draw(surface)
        return top

    def _draw_terminal(self, surface, rect):
        font = fonts.mono(TERM_FONT)
        line_h = font.get_linesize()
        focused = self.focus == "cheat"
        fill_round(surface, rect, theme.TERM_BG, 235, 12)
        pygame.draw.rect(surface, theme.mix(theme.TERM_LINE, theme.WARN, 0.5) if focused else theme.TERM_LINE, rect, 1,
                         border_radius=12)
        hy = rect.y + 18
        fill_round(surface, pygame.Rect(rect.x + 14, hy - 7, 3, 14), theme.WARN, 255, 1)
        draw_spaced(surface, "CHEAT TERMINAL", (rect.x + 25, hy), 12, theme.TEXT, spacing=0.22, anchor="midleft")
        if self.pending is not None:
            dots = "." * (1 + int(self._anim_time * 3) % 3)
            status, color = "DeepSeek думает" + dots, theme.WARN
        else:
            status, color = "готов", theme.TEXT_MUTED
        img = fonts.mono(12).render(status, True, color)
        surface.blit(img, img.get_rect(midright=(rect.right - 14, hy)))
        pygame.draw.line(surface, theme.TERM_LINE, (rect.x + 14, rect.y + 34), (rect.right - 14, rect.y + 34))

        row_h = TERM_ROW_H if rect.h >= 200 else 34
        row = pygame.Rect(rect.x + 12, rect.bottom - row_h - 12, rect.w - 24, row_h)
        seg_w = 122
        seg = pygame.Rect(row.x, row.y, seg_w, row.h)
        fill_round(surface, seg, theme.TERM_FIELD, 255, row.h // 2)
        pygame.draw.rect(surface, theme.TERM_LINE, seg, 1, border_radius=row.h // 2)
        small = fonts.mono(12)
        self.mode_rects = {}
        half = (seg_w - 8) // 2
        for i, (mode, label) in enumerate((("single", "SINGLE"), ("full", "FULL"))):
            r = pygame.Rect(seg.x + 4 + i * half, seg.y + 4, half, seg.h - 8)
            self.mode_rects[mode] = r
            on = self.cheat_mode == mode
            if on:
                fill_round(surface, r, theme.WARN if mode == "single" else theme.ACCENT, 60, r.h // 2)
            img = small.render(label, True, theme.TEXT if on else theme.TEXT_MUTED)
            surface.blit(img, img.get_rect(center=r.center))
        self.arrow_rect = pygame.Rect(row.right - row.h, row.y, row.h, row.h)
        self.cheat_rect = pygame.Rect(seg.right + 8, row.y, self.arrow_rect.x - 8 - seg.right - 8, row.h)
        self._draw_cheat_input(surface, self.cheat_rect, font)
        self._draw_arrow(surface, self.arrow_rect)

        area = pygame.Rect(rect.x + 16, rect.y + 42, rect.w - 32, row.y - 10 - (rect.y + 42))
        rows = []
        for text, color in self.console_lines:
            rows.extend((line, color) for line in _mono_wrap(text, area.w, TERM_FONT))
        rows = rows[-max(0, area.h // line_h):]
        y = area.bottom - len(rows) * line_h
        for line, color in rows:
            surface.blit(font.render(line, True, color), (area.x, y))
            y += line_h

    def _draw_cheat_input(self, surface, rect, font):
        focused = self.focus == "cheat"
        fill_round(surface, rect, theme.TERM_FIELD, 255, rect.h // 2)
        pygame.draw.rect(surface, theme.WARN if focused else theme.TERM_LINE, rect, 1, border_radius=rect.h // 2)
        slash = font.render("/", True, theme.WARN if self.cheat_mode == "single" else theme.ACCENT)
        surface.blit(slash, slash.get_rect(midleft=(rect.x + 14, rect.centery)))
        inner = pygame.Rect(rect.x + 14 + slash.get_width() + 5, rect.y, rect.w - slash.get_width() - 33, rect.h)
        text = self.console_input.text
        hint = "одноразовый чит" if self.cheat_mode == "single" else "постоянный чит"
        img = font.render(text, True, theme.TEXT) if text else font.render(hint, True, theme.TEXT_MUTED)
        offset = max(0, img.get_width() - inner.w + 4) if text else 0
        prev = surface.get_clip()
        surface.set_clip(inner.clip(prev) if prev else inner)
        y = inner.centery - img.get_height() // 2
        surface.blit(img, (inner.x - offset, y))
        if focused and self.console_input._blink < 0.5:
            cx = inner.x + (font.size(text)[0] - offset if text else 0) + 1
            pygame.draw.rect(surface, theme.WARN, (cx, y + 2, 8, img.get_height() - 4))
        surface.set_clip(prev)

    def _draw_arrow(self, surface, rect):
        hot = rect.collidepoint(pygame.mouse.get_pos()) or self.cheat_list_open
        fill_round(surface, rect, theme.TERM_FIELD if not hot else theme.mix(theme.TERM_FIELD, theme.WARN, 0.12), 255,
                   rect.h // 2)
        pygame.draw.rect(surface, theme.TERM_LINE if not hot else theme.WARN, rect, 1, border_radius=rect.h // 2)
        cx, cy = rect.centerx, rect.centery
        if self.cheat_list_open:
            pts = [(cx - 7, cy + 3), (cx + 7, cy + 3), (cx, cy - 5)]
        else:
            pts = [(cx - 7, cy - 3), (cx + 7, cy - 3), (cx, cy + 5)]
        pygame.draw.polygon(surface, theme.TEXT if hot else theme.TEXT_DIM, pts)
        count = len(self.game.cheats)
        if count:
            badge = pygame.Rect(rect.right - 15, rect.y - 6, 18, 18)
            fill_round(surface, badge, theme.ACCENT, 255, 9)
            img = fonts.mono(11).render(str(count), True, theme.TEXT)
            surface.blit(img, img.get_rect(center=badge.center))

    def _draw_cheat_list(self, surface):
        cheats = self.game.cheats
        font = fonts.mono(TERM_FONT)
        row_h = 36
        side = self.rects["side"]
        x, w = self.term_rect.x, self.term_rect.w
        top = self.term_rect.bottom + 4
        h = 34 + max(1, len(cheats)) * row_h + 8
        h = min(h, side.bottom - 10 - top)
        self.list_rect = pygame.Rect(x, top, w, h)
        fill_round(surface, self.list_rect, theme.TERM_BG, 252, 10)
        pygame.draw.rect(surface, theme.WARN, self.list_rect, 1, border_radius=10)
        surface.blit(fonts.mono(12).render(f"АКТИВНЫЕ FULL-ЧИТЫ · {len(cheats)}", True, theme.WARN), (x + 12, top + 10))
        self.trash_rects = []
        mouse = pygame.mouse.get_pos()
        y = top + 32
        if not cheats:
            surface.blit(font.render("пусто: включите чит в режиме FULL", True, theme.TEXT_MUTED), (x + 12, y + 8))
            return
        for i, text in enumerate(cheats):
            if y + row_h > self.list_rect.bottom - 4:
                break
            row = pygame.Rect(x + 6, y, w - 12, row_h - 4)
            if row.collidepoint(mouse):
                fill_round(surface, row, (255, 255, 255), 12, 6)
            trash = pygame.Rect(row.right - 32, row.centery - 14, 28, 28)
            self.trash_rects.append((trash, i))
            label = ellipsize("/" + text, trash.x - row.x - 14, font)
            surface.blit(font.render(label, True, theme.TEXT), (row.x + 8, row.centery - font.get_linesize() // 2))
            _draw_trash(surface, trash, trash.collidepoint(mouse))
            y += row_h

    def _stat_items(self):
        s = self.game.s
        stats = s["stats"]
        hidden = set(s.get("hidden", []))

        def item(key, label, frac, text, polarity, pinned):
            return {"key": key, "label": label, "frac": min(max(frac, 0.0), 1.0), "text": text,
                    "color": IND_COLORS.get(key, theme.TEXT_DIM), "polarity": polarity, "pinned": pinned}

        def stat(key, pinned):
            pol = -1 if key in NEGATIVE_STATS else 1
            return item(key, STATS[key][0], stats[key] / 100, str(stats[key]), pol, pinned)

        fame, heat = s["fame"], s.get("heat", 0)
        hero = [item("fame", "Известность", fame / (fame + 100), str(fame), 0, fame >= 25)]
        if self.mode_id == "arcade":
            hero.append(item("chaos", "Абсурд", s["chaos"] / 100, f"{s['chaos']}%", 0, s["chaos"] >= 40))
        if self.game.risks.get("enabled") or (self.game.cfg.get("defeat") or {}).get("enabled"):
            hero.append(item("heat", "Внимание", heat / 100, str(heat), -1, heat >= 30))
        pins = {"health": True, "energy": stats["energy"] < 40, "stress": stats["stress"] >= 50, "reputation": True,
                "influence": True, "stability": True, "economy": True, "tension": stats["tension"] >= 50}
        hero += [stat(k, pins[k]) for k in ("health", "energy", "stress", "reputation", "influence")
                 if k not in hidden]
        world = [stat(k, pins[k]) for k in ("stability", "economy", "tension") if k not in hidden]
        story = []
        for i, (key, m) in enumerate(s.get("meters", {}).items()):
            good = m.get("good")
            it = item("m:" + key, m["label"], m["value"] / 100, str(m["value"]),
                      0 if good is None else 1 if good else -1, True)
            it["color"] = METER_COLORS[i % len(METER_COLORS)]
            story.append(it)
        return story, hero, world

    def _update_indicators(self, dt):
        fresh = not self.ind
        seen = set()
        for it in (i for g in self._stat_items() for i in g):
            key = it["key"]
            seen.add(key)
            a = self.ind.get(key)
            if a is None:
                a = self.ind[key] = {"shown": it["frac"], "target": it["frac"],
                                     "vis": 1.0 if fresh and it["pinned"] else 0.0,
                                     "glow": 0.0 if fresh else 1.0, "timer": 0.0 if fresh else IND_FLASH_HOLD}
            if abs(it["frac"] - a["target"]) > 1e-6:
                a["target"] = it["frac"]
                a["glow"] = 1.0
                a["timer"] = IND_FLASH_HOLD
            a["shown"] += (a["target"] - a["shown"]) * min(1.0, dt * IND_SPEED)
            a["glow"] = max(0.0, a["glow"] - dt * 0.7)
            a["timer"] = max(0.0, a["timer"] - dt)
            want = 1.0 if it["pinned"] or a["timer"] > 0 else 0.0
            step = dt * (4.0 if want > a["vis"] else 1.2)
            a["vis"] = min(want, a["vis"] + step) if want > a["vis"] else max(want, a["vis"] - step)
        for key in list(self.ind):
            if key not in seen:
                del self.ind[key]

    def _draw_grid(self, surface, x, y, w, items):
        items = [it for it in items if self.ind.get(it["key"], {}).get("vis", 1.0) > 0.02]
        gap = 16
        col_w = (w - gap) // 2
        for i, it in enumerate(items):
            self._draw_indicator(surface, x + (i % 2) * (col_w + gap), y + (i // 2) * IND_ROW_H, col_w, it)
        return y + -(-len(items) // 2) * IND_ROW_H + 2

    def _draw_indicator(self, surface, x, y, w, it):
        a = self.ind.get(it["key"]) or {"shown": it["frac"], "vis": 1.0, "glow": 0.0}
        vis, frac = a["vis"], a["shown"]
        img = pygame.Surface((w + 12, IND_ROW_H), pygame.SRCALPHA)
        ox, bar_y = 6, 21
        value_color = _ind_color(it["polarity"], frac, it["color"])
        fill_round(img, pygame.Rect(ox, 6, 6, 6), it["color"], 255, 3)
        img.blit(text_surface(it["label"], 12, theme.TEXT_DIM), (ox + 11, 1))
        val = text_surface(it["text"], 13, value_color, bold=True)
        img.blit(val, val.get_rect(topright=(ox + w, 0)))
        track = pygame.Rect(ox, bar_y, w, 6)
        fill_round(img, track, (255, 255, 255), 22, 3)
        fill_w = int(round(w * frac))
        if fill_w > 0:
            pulse = 0.5 + 0.5 * math.sin(self._anim_time * 2.2 + hash(it["key"]) % 7)
            halo = int(26 + 22 * pulse + 150 * a["glow"])
            fill_round(img, pygame.Rect(ox - 3, bar_y - 4, fill_w + 6, 14), value_color, min(halo, 255), 7)
            strip = _ind_strip(it["polarity"], it["color"], w)
            bar = pygame.Surface((fill_w, 6), pygame.SRCALPHA)
            bar.blit(strip, (0, 0), pygame.Rect(0, 0, fill_w, 6))
            mask = pygame.Surface((fill_w, 6), pygame.SRCALPHA)
            fill_round(mask, mask.get_rect(), (255, 255, 255), 255, 3)
            bar.blit(mask, (0, 0), special_flags=pygame.BLEND_RGBA_MULT)
            img.blit(bar, (ox, bar_y))
            fill_round(img, pygame.Rect(ox + fill_w - 3, bar_y - 1, 4, 8), (255, 255, 255),
                       int(120 + 120 * a["glow"]), 2)
        if vis < 1.0:
            img.set_alpha(int(255 * vis))
        surface.blit(img, (x - ox, y))

    def _draw_stats(self, surface, rect, controls=True):
        g = self.game
        compact = rect.h < 560
        x, w = rect.x + 20, rect.w - 40
        y = rect.y + (12 if compact else 18)

        generic = self.polity.get("generic")
        flag_w, flag_h = (45, 30) if compact else (54, 36)
        flag = self.app.flags.fitted(self.home.iso2, flag_w, flag_h) if generic and not self.anime else None
        world = self.game.world
        if world is not None and world.player >= 0:
            draw_polity_flag(surface, self.app, world.polity(world.player), world.date_year(),
                             pygame.Rect(x, y, flag_w, flag_h))
            flag = True
        left = x + flag_w + 16 if flag else x
        if flag is not None and flag is not True:
            frame = flag.get_rect(topleft=(x, y))
            surface.blit(flag, frame)
            pygame.draw.rect(surface, theme.FLAG_BORDER, frame.inflate(2, 2), 1, border_radius=8)
        hero = g.s.get("hero") or {}
        draw_text(surface, "МИР" if self.anime else "РОДИНА" if generic else "ГОСУДАРСТВО", (left, y - 2), 11,
                  theme.TEXT_DIM, bold=True)
        name = world.title(world.player) if world is not None and world.player >= 0 else g.s["country_name"]
        draw_text(surface, ellipsize(name, x + w - left, fonts.get(18, True)), (left, y + 10), 18, bold=True)
        line_y = y + 33
        if hero.get("name"):
            draw_text(surface, ellipsize(hero["name"], x + w - left, fonts.get(13, True)), (left, line_y), 13, bold=True)
            line_y += 17
        if hero.get("role"):
            line = f"{hero['role']} · {hero.get('age', '')} · {hero.get('gender', '')}"
            draw_text(surface, ellipsize(line, x + w - left, fonts.get(12)), (left, line_y), 12, theme.TEXT_DIM)
        y = max(y + 52, line_y + 20)
        if controls:
            world_h = 28 if compact else 34
            self.world_btn.rect = pygame.Rect(x, y, w, world_h)
            self.world_btn.draw(surface)
            y += world_h + (10 if compact else 14)
        else:
            y += 4

        if controls:
            half = (w - 10) // 2
            small_h, time_h, gap = (30, 38, 8) if compact else (36, 44, 10)
            bottom = rect.bottom - (12 if compact else 20)
            show_undo = bool(g.rules.get("allow_turn_undo"))
            self.save_btn.rect = pygame.Rect(x, bottom - small_h, half, small_h)
            self.load_btn.rect = pygame.Rect(x + half + 10, bottom - small_h, half, small_h)
            row = bottom - small_h - gap
            if show_undo:
                self.undo_btn.rect = pygame.Rect(x, row - small_h, w, small_h)
                row -= small_h + gap
            else:
                self.undo_btn.rect = EMPTY
            self.time_btn.rect = pygame.Rect(x, row - time_h, w, time_h)
            self.undo_btn.enabled = self.can_undo
            self.save_btn.enabled = self.time_btn.enabled = not g.over
            view_bottom = self.time_btn.rect.y - 8
        else:
            view_bottom = rect.bottom - 12
        view = pygame.Rect(rect.x, y - 6, rect.w, view_bottom - (y - 6))
        self.stats_view = view
        prev_clip = surface.get_clip()
        surface.set_clip(view.clip(prev_clip))

        story_items, hero_items, world_items = self._stat_items()
        top = y - self.stats_scroll
        y = top
        pygame.draw.line(surface, theme.PANEL_BORDER, (x, y - 4), (x + w, y - 4))
        y += 6
        if story_items:
            draw_text(surface, "СЮЖЕТ", (x, y), 11, theme.ACCENT, bold=True)
            y = self._draw_grid(surface, x, y + 18, w, story_items) + 4
        draw_text(surface, "ГЕРОЙ", (x, y), 11, theme.ACCENT, bold=True)
        y += 18
        if not self.anime:
            draw_text(surface, "Деньги", (x, y), 13, theme.TEXT_DIM)
            draw_text(surface, fmt.usd(g.money), (x + w, y - 1), 15, theme.GOOD, bold=True, anchor="topright")
            income = g.s.get("income", 0.0)
            draw_text(surface, "Доход в день", (x, y + 20), 13, theme.TEXT_DIM)
            if income:
                draw_text(surface, ("+" if income > 0 else "−") + fmt.usd(abs(income)), (x + w, y + 19), 14,
                          theme.GOOD if income > 0 else theme.DANGER, anchor="topright")
            else:
                draw_text(surface, "нет", (x + w, y + 19), 14, theme.TEXT_MUTED, anchor="topright")
            y += 44
        y = self._draw_grid(surface, x, y, w, hero_items)
        if world_items or not self.anime:
            draw_text(surface, "СТРАНА И МИР", (x, y + 2), 11, theme.ACCENT, bold=True)
            y = self._draw_grid(surface, x, y + 20, w, world_items) if world_items else y + 22
        info = self.app.country_info.get(self.home.id, {})
        population = info.get("population") or self.home.pop_est
        facts = "  ·  ".join(t for t in (f"Население {fmt.people(population)}" if population else "",
                                         f"ВВП {fmt.usd(self._gdp(self.home))}" if self._gdp(self.home) else "") if t)
        if self.anime:
            facts = ""
        elif world is not None and world.player >= 0:
            atoms = world.group_atoms(world.player)
            pop_w = float(world.pop[atoms].sum())
            facts = f"Население {fmt.people(pop_w)}  ·  областей {len(atoms)}"
        elif not generic:
            facts = f"Столица: {self.polity['capital']}" if self.polity.get("capital") else ""
        if facts:
            draw_text(surface, ellipsize(facts, w, fonts.get(12)), (x, y), 12, theme.TEXT_MUTED)
            y += 18
        surface.set_clip(prev_clip)
        self.stats_max_scroll = max(0, y - top + 6 - (view.bottom - view.y - 6))
        self.stats_scroll = min(self.stats_scroll, self.stats_max_scroll)

        if not controls:
            return
        if self.anime:
            self.time_btn.rect = EMPTY
        for b in (self.time_btn, self.undo_btn, self.save_btn, self.load_btn):
            if b.rect.w:
                b.draw(surface)

