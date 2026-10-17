# Проверка всех экранов без окна: рисует их при нескольких размерах, кликает окна «Управление» и игру,
# сохраняет скриншоты и время кадра. Сеть отключена, сейвы и settings.json не меняются.
#   python tools/ui_check.py                       все экраны, размеры 1600x900 1280x720 800x520
#   python tools/ui_check.py --only realm game     только перечисленные экраны
#   python tools/ui_check.py --sizes 1600x900 --frames 120
#   python tools/ui_check.py --save saves/arcade_4.json --out build/ui_check
#   python tools/ui_check.py --style glass            вид «Стекло» (по умолчанию - как в settings.json)
# Код возврата 1, если хоть один экран упал или проверка кликов не прошла.
import argparse
import json
import os
import sys
import time
import traceback
from pathlib import Path

os.environ["SDL_VIDEODRIVER"] = "dummy"
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

import pygame  # noqa: E402

from wrldsim import settings  # noqa: E402

_load_settings = settings.load
_STYLE = {}
settings.load = lambda: {**_load_settings(), "gpu": False, **_STYLE}
settings.save = lambda prefs: None


def _offline(*args, **kwargs):
    raise urllib.error.URLError("ui_check: сеть отключена")


import urllib.error  # noqa: E402
import urllib.request  # noqa: E402

urllib.request.urlopen = _offline

from wrldsim.sim import shop as _shop  # noqa: E402


class _OfflineCatalog:
    SAMPLE = [("Особняк на набережной", 1_200_000, "Три этажа, сад и вид на реку."),
              ("Карета с гербом", 85_000, "Четвёрка лошадей и кучер в ливрее."),
              ("Доля в мануфактуре", 400_000, "Сукно для армии: стабильный доход."),
              ("Охрана из гвардейцев", 30_000, "Шесть человек, верных до гроба.")]

    def __init__(self, cfg, summary, category, query=""):
        self.category, self.query = category, query
        self.done, self.error = True, None
        self.items = [{"name": n, "price": float(p), "description": d, "image_query": ""} for n, p, d in self.SAMPLE]


_shop.CatalogRequest = _OfflineCatalog
_shop.ImageFetcher.path = lambda self, query: None

E = pygame.event.Event


class Ctx:
    def __init__(self, save_path):
        from wrldsim.app import App
        from wrldsim.session import GameSession
        self.app = App()
        data = json.loads(Path(save_path).read_text(encoding="utf-8"))
        self.data = data
        st = data["game"]
        self.app.session = GameSession(st["mode"], st.get("difficulty"), era_id=st.get("era") or "modern")
        self.state = st

    def new_game(self):
        from wrldsim.states import arcade_game as ag
        game = ag._make_game(self.app, self.app.session, state=self.state)
        self.app.session.game = game
        return game

    def game_screen(self):
        from wrldsim.states.arcade_game import ArcadeGameState
        self.new_game()
        gs = ArcadeGameState(self.app, self.data.get("eclipse"))
        return gs


def _home_idx(app, game):
    return next(i for i, c in enumerate(app.world.countries) if c.id == game.s["country_id"])


def _with_card(gs, card):
    gs._open_card(None if card == "none" else card)
    return gs


def _screens():
    from wrldsim.states.anime_setup import AnimeSetupState
    from wrldsim.states.atlas import AtlasState
    from wrldsim.states.confirm import ChoiceState, ConfirmState
    from wrldsim.states.country_view import CountryViewState
    from wrldsim.states.era_select import EraSelectState
    from wrldsim.states.main_menu import MainMenuState
    from wrldsim.states.mode_select import ModeSelectState
    from wrldsim.states.new_game import NewGameKindState
    from wrldsim.states.realm import RealmState
    from wrldsim.states.role_select import RoleSelectState
    from wrldsim.states.save_slots import SaveSlotsState
    from wrldsim.states.settings_state import SettingsState
    from wrldsim.states.shop import ShopState
    from wrldsim.states.time_control import TimeControlState
    from wrldsim.states.warning import GameOverState, WarningState
    from wrldsim.states.world_map import WorldMapState

    def plain(cls, *args):
        return lambda c: (cls(c.app, *args), None)

    def over_game(make):
        def build(c):
            gs = c.game_screen()
            c.app.states.append(gs)
            return make(c, gs), gs
        return build

    def role(c):
        game = c.new_game()
        polity = c.app.eras.polity(c.app.session.era_id, game.s.get("polity") or "generic", game.s.get("country_name", ""))
        roles = c.app.eras.roles(c.app.session.era_id, polity, 1721, c.app.roles["roles"])
        under = CountryViewState(c.app, _home_idx(c.app, game))
        c.app.states.append(under)
        return RoleSelectState(c.app, game.s.get("country_name", ""), lambda hero: None,
                               {"country_id": game.s["country_id"], "region": "", "polity_id": polity["id"]},
                               roles=roles), under

    choice = {"text": "Пробраться ночью в архив министерства", "risk": 70, "warning": "Охрана усилена.",
              "cheats": ["невидимость", "ключи от архива"]}
    return {
        "main_menu": plain(MainMenuState),
        "new_game": plain(NewGameKindState),
        "era_select": plain(EraSelectState),
        "mode_select": plain(ModeSelectState, "imperial"),
        "world_map": plain(WorldMapState),
        "country_view": lambda c: (CountryViewState(c.app, _home_idx(c.app, c.new_game())), None),
        "atlas": plain(AtlasState, "imperial"),
        "anime_setup": plain(AnimeSetupState),
        "role_select": role,
        "game": lambda c: (c.game_screen(), None),
        **{f"game_{card}": (lambda card: lambda c: (_with_card(c.game_screen(), card), None))(card)
           for card in ("news", "stats", "cheats", "menu", "none")},
        "realm": over_game(lambda c, gs: RealmState(c.app, gs.game, gs)),
        "time_control": over_game(lambda c, gs: TimeControlState(c.app, gs.game, lambda minutes: None)),
        "shop": over_game(lambda c, gs: ShopState(c.app, gs.game, gs.cfg["eclipse"], gs._summary)),
        "settings": over_game(lambda c, gs: SettingsState(c.app)),
        "settings_look": over_game(lambda c, gs: SettingsState(c.app, tab="look")),
        "save_slots": over_game(lambda c, gs: SaveSlotsState(c.app, gs.mode_id, "load", lambda slot: None)),
        "confirm": over_game(lambda c, gs: ConfirmState(c.app, "ПОДТВЕРДИТЬ?", "Проверка окна подтверждения.",
                                                        lambda: None)),
        "choice": over_game(lambda c, gs: ChoiceState(c.app, "ОШИБКА", "Проверка окна выбора.", [])),
        "warning": over_game(lambda c, gs: WarningState(c.app, choice, lambda: None, cheat_fn=lambda t: True)),
        "game_over": over_game(lambda c, gs: GameOverState(c.app, "КОНЕЦ ИГРЫ", "Проверка экрана поражения.",
                                                           lambda: None)),
    }


def _frames(screen, surface, n):
    w, h = surface.get_size()
    screen.draw(surface)
    t = time.perf_counter()
    for i in range(n):
        pygame.mouse.set_pos((int(w * (0.15 + 0.7 * (i % 17) / 16)), int(h * (0.2 + 0.6 * (i % 11) / 10))))
        screen.draw(surface)
    return (time.perf_counter() - t) / n * 1000


def _click(screen, surface, pos):
    pygame.mouse.set_pos(pos)
    screen.handle_event(E(pygame.MOUSEBUTTONDOWN, button=1, pos=pos))
    screen.draw(surface)
    screen.handle_event(E(pygame.MOUSEBUTTONUP, button=1, pos=pos))
    screen.draw(surface)


def check_realm(rs, surface, report):
    from wrldsim.states.realm import TABS
    for i, (key, _) in enumerate(TABS):
        rs.tab = "overview"
        rs.draw(surface)
        rail = [r for r, _, _ in rs.hits if r.x < 200 and r.y > 90]
        _click(rs, surface, rail[i].center)
        report(rs.tab == key, f"вкладка «{key}» кликом")
    for i, (key, _) in enumerate(TABS):
        rs.handle_event(E(pygame.KEYDOWN, key=pygame.K_1 + i, mod=0, unicode=str(i + 1)))
        report(rs.tab == key, f"вкладка «{key}» клавишей {i + 1}")
    for key, _ in TABS:
        rs.tab = key
        rs.draw(surface)
        hits = [(r, tip) for r, _, tip in rs.hits if r.x >= 200 and r.y >= 100]
        done = 0
        for r, tip in hits:
            rs.tab = key
            rs.draw(surface)
            if r.collidepoint(r.center):
                _click(rs, surface, r.center)
                done += 1
            rs.dialog = None
            if rs.edit:
                rs._cancel_edit()
        rs._fiscal_done()
        report(True, f"«{key}»: нажато элементов {done}")
    w, p = rs.w, rs.p
    rs.tab = "budget"
    rs.draw(surface)
    rects = [r for r, _, tip in rs.hits if tip == "Нажмите и введите число"]
    _click(rs, surface, rects[0].center)
    rs.num_input.text = ""
    for ch in "17":
        rs.handle_event(E(pygame.TEXTINPUT, text=ch))
    rs.handle_event(E(pygame.KEYDOWN, key=pygame.K_RETURN, mod=0, unicode=""))
    report(round(float(w.tax[p]) * 100) == 17, "налог вводом числа")
    rs._fiscal_done()


def check_game(gs, surface, report):
    gs.draw(surface)
    rail = gs.rects["rail"]
    items, tools = gs._rail_items()
    for i, (key, *_rest) in enumerate(items):
        r = pygame.Rect(rail.x, rail.y + 6 + i * 50, rail.w, 50)
        _click(gs, surface, r.center)
        report(gs.card == key, f"рейка: открыть «{key}»")
        _click(gs, surface, r.center)
        report(gs.card is None, f"рейка: повторный клик прячет «{key}»")
    _click(gs, surface, pygame.Rect(rail.x, rail.y + 56, rail.w, 50).center)
    close = next(r for r, _, tip in gs._hits if tip == "Скрыть карточку")
    _click(gs, surface, close.center)
    report(gs.card is None, "крестик прячет карточку")
    gs._open_card("eclipse")
    gs.draw(surface)
    cam = gs.app.camera
    z = cam.zoom
    plus = next(r for r, _, tip in gs._hits if tip == "Крупнее")
    _click(gs, surface, plus.center)
    report(cam.zoom > z, f"кнопка «+»: масштаб {z:.2f} → {cam.zoom:.2f}")
    view = gs.rects["view"]
    report(not gs._over_ui(view.center), "середина карты справа от карточки не под интерфейсом")
    report(gs._over_ui(gs.rects["card"].center), "карточка закрывает карту под собой")
    _click(gs, surface, gs.input_rect.center)
    report(gs.focus == "eclipse", "клик по полю ECLIPSE даёт фокус")
    for ch in "тест":
        gs.handle_event(E(pygame.TEXTINPUT, text=ch))
    report(gs.eclipse_input.text.endswith("тест"), "ввод в поле ECLIPSE")
    gs.eclipse_input.text = ""
    gs._open_card("news")
    report(gs.focus is None, "смена карточки снимает фокус с поля ECLIPSE")
    if tools and tools[0][0] == "realm" and tools[0][4]:
        r = pygame.Rect(rail.x, rail.y + 6 + len(items) * 50 + 13, rail.w, 50)
        gs.draw(surface)
        _click(gs, surface, r.center)
        top = gs.app.states[-1]
        report(type(top).__name__ == "RealmState", f"рейка: «Управление» открывает окно ({type(top).__name__})")
        if top is not gs:
            gs.app.states.pop()


def run(args):
    if args.style:
        _STYLE["ui_style"] = args.style
    ctx = Ctx(args.save)
    screens = _screens()
    names = args.only or list(screens)
    unknown = [n for n in names if n not in screens]
    if unknown:
        sys.exit(f"нет таких экранов: {', '.join(unknown)}; есть: {', '.join(screens)}")
    out = Path(args.out)
    failures = []
    timings = {}
    for size_text in args.sizes:
        size = tuple(int(v) for v in size_text.split("x"))
        ctx.app.screen = surface = pygame.display.set_mode(size)
        (out / size_text).mkdir(parents=True, exist_ok=True)
        for name in names:
            ctx.app.states.clear()
            try:
                screen, under = screens[name](ctx)
                ctx.app.states.append(screen)
                ms = _frames(screen, surface, args.frames)
                timings[(name, size_text)] = ms
                pygame.image.save(surface, str(out / size_text / f"{name}.png"))
                if name == "game" and not args.no_clicks:
                    def report(ok, text, name=name):
                        if not ok:
                            failures.append((name, size_text, "клик: " + text, ""))
                    check_game(screen, surface, report)
                if name == "realm" and not args.no_clicks:
                    def report(ok, text, name=name):
                        if not ok:
                            failures.append((name, size_text, "клик: " + text, ""))
                    check_realm(screen, surface, report)
            except Exception:
                failures.append((name, size_text, "исключение", traceback.format_exc()))
    sizes = args.sizes
    lines = [f"{'экран':14s}" + "".join(f"{s:>13s}" for s in sizes)]
    for name in names:
        row = f"{name:14s}"
        for s in sizes:
            ms = timings.get((name, s))
            row += f"{'ОШИБКА':>13s}" if ms is None else f"{ms:9.1f} мс"
        lines.append(row)
    text = "\n".join(lines)
    print(text)
    (out / "report.txt").write_text(text + "\n", encoding="utf-8")
    for name, size_text, what, tb in failures:
        print(f"\n=== {name} {size_text}: {what}\n{tb[-2000:]}")
    print(f"\nскриншоты: {out}\nошибок: {len(failures)}")
    return 1 if failures else 0


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="Проверка всех экранов WrldSim без окна")
    ap.add_argument("--save", default="saves/arcade_4.json", help="сейв, из которого строится игра")
    ap.add_argument("--sizes", nargs="+", default=["1600x900", "1280x720", "800x520"])
    ap.add_argument("--only", nargs="+", help="только эти экраны")
    ap.add_argument("--frames", type=int, default=40, help="кадров на замер")
    ap.add_argument("--out", default="build/ui_check", help="куда класть скриншоты и отчёт")
    ap.add_argument("--no-clicks", action="store_true", help="без прокликивания окна «Управление»")
    ap.add_argument("--style", choices=settings.UI_STYLES, help="вид оформления: flat или glass")
    sys.exit(run(ap.parse_args()))


if __name__ == "__main__":
    main()
