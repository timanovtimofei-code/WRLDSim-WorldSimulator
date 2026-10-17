import json
import sys

import pygame

from . import config, settings
from .map.camera import Camera
from .map.data import load_world
from .map.flags import FlagAtlas
from .map.renderer import MapRenderer
from .sim.eras import Eras, merge as _merge
from .sim.modes import load_modes
from .sim.names import Names
from .ui import theme


def _enable_dpi_awareness():
    # Без этого Windows растягивает окно при масштабе больше 100%.
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass


def _refresh():
    try:
        return max(pygame.display.get_desktop_refresh_rates()[:1] or [0])
    except Exception:
        return 0


class App:
    def __init__(self):
        _enable_dpi_awareness()
        pygame.init()
        desktop = pygame.display.get_desktop_sizes()[0]
        size = (max(config.MIN_WINDOW_SIZE[0], min(config.WINDOW_SIZE[0], int(desktop[0] * 0.9))),
                max(config.MIN_WINDOW_SIZE[1], min(config.WINDOW_SIZE[1], int(desktop[1] * 0.85))))
        self.prefs = settings.load()
        theme.apply(self.prefs["theme"])
        from .ui import widgets
        widgets.set_style(self.prefs["ui_style"])
        self.display_mode = None
        self.gpu = None
        self.renderer = None
        self._window_size = size
        self._set_mode(size, pygame.RESIZABLE)
        pygame.display.set_caption(config.TITLE)
        self.set_display(self.prefs["display"], save=False)
        self.clock = pygame.time.Clock()

        self.world = load_world(config.WORLD_CACHE)
        self.modes = load_modes(config.MODES_FILE)
        self.eras = Eras()
        self.names = Names()
        with open(config.COUNTRIES_FILE, encoding="utf-8") as f:
            self.country_info = json.load(f)["countries"]
        with open(config.ARCADE_FILE, encoding="utf-8") as f:
            self.arcade_cfg = json.load(f)
        with open(config.REALISM_FILE, encoding="utf-8") as f:
            self.realism_cfg = _merge(self.arcade_cfg, json.load(f))
        with open(config.ROLES_FILE, encoding="utf-8") as f:
            self.roles = json.load(f)
        with open(config.DATA_DIR / "anime.json", encoding="utf-8") as f:
            self.anime_cfg = _merge(self.arcade_cfg, json.load(f))

        self.renderer = MapRenderer(self.world)
        self.renderer.attach_gpu(self.gpu)
        self.flags = FlagAtlas(config.FLAGS_DIR)
        self.camera = Camera(globe=self.globe_on)
        self.camera.clamp(size)
        self.world_camera = self.camera.snapshot()
        self.session = None

        self.states = []
        self.running = True

    def _set_mode(self, size, flags):
        if self.prefs.get("gpu", True):
            try:
                pygame.display.gl_set_attribute(pygame.GL_CONTEXT_MAJOR_VERSION, 3)
                pygame.display.gl_set_attribute(pygame.GL_CONTEXT_MINOR_VERSION, 3)
                pygame.display.gl_set_attribute(pygame.GL_CONTEXT_PROFILE_MASK, pygame.GL_CONTEXT_PROFILE_CORE)
                # Vsync включаем только на мониторах от 120 Гц, иначе он привязал бы кадры к 60 Гц.
                pygame.display.set_mode(size, flags | pygame.OPENGL | pygame.DOUBLEBUF, vsync=int(_refresh() >= config.FPS))
                from . import gpu
                self.gpu = gpu.create(pygame.display.get_window_size())
            except pygame.error as e:
                print("OpenGL недоступен:", e)
                self.gpu = None
        else:
            self.gpu = None
        from .ui import widgets
        widgets.GPU = self.gpu
        if hasattr(self, "camera"):
            self.camera.globe = self.globe_on
        if self.gpu is None:
            self.screen = pygame.display.set_mode(size, flags)
        else:
            self.screen = self.gpu.ui
        if self.renderer is not None:
            self.renderer.attach_gpu(self.gpu)

    def _sync_size(self):
        if self.gpu is None:
            return
        size = pygame.display.get_window_size()
        if size != self.gpu.size:
            self.gpu.resize(size)
            self.screen = self.gpu.ui
            self.renderer.attach_gpu(self.gpu)
            self.camera.clamp(size)

    def set_display(self, mode, save=True):
        if mode not in settings.DISPLAY_MODES:
            mode = "windowed"
        if mode == self.display_mode:
            return
        if self.display_mode in (None, "windowed"):
            self._window_size = self.screen.get_size()
        desktop = pygame.display.get_desktop_sizes()[0]
        if mode == "fullscreen":
            self._set_mode(desktop, pygame.FULLSCREEN)
        elif mode == "borderless":
            self._set_mode(desktop, pygame.NOFRAME)
        else:
            self._set_mode(self._window_size, pygame.RESIZABLE)
            try:
                pygame.Window.from_display_module().minimum_size = config.MIN_WINDOW_SIZE
            except Exception:
                pass
        self.display_mode = mode
        if hasattr(self, "camera"):
            self.camera.clamp(self.screen.get_size())
        if save:
            self.prefs["display"] = mode
            settings.save(self.prefs)

    def apply_theme(self, cfg, save=True):
        from .ui import widgets
        theme.apply(cfg)
        widgets.reset_theme_caches()
        if self.renderer is not None:
            self.renderer.invalidate()
        self.prefs["theme"] = cfg
        if save:
            settings.save(self.prefs)

    @property
    def globe_on(self):
        return self.gpu is not None and self.prefs.get("globe", True)

    def new_camera(self, **kw):
        return Camera(globe=self.globe_on, **kw)

    def set_globe(self, on, save=True):
        self.prefs["globe"] = bool(on)
        self.camera.globe = self.globe_on
        self.camera.clamp(self.screen.get_size())
        for state in self.states:
            cam = getattr(state, "camera", None)
            if isinstance(cam, Camera) and cam is not self.camera:
                cam.globe = self.globe_on
                cam.clamp(self.screen.get_size())
            if hasattr(state, "refresh_backdrop"):
                state.refresh_backdrop()
        if save:
            settings.save(self.prefs)

    def set_ui_style(self, style, save=True):
        from .ui import widgets
        widgets.set_style(style)
        theme.VERSION += 1
        self.prefs["ui_style"] = widgets.STYLE
        if save:
            settings.save(self.prefs)

    def toggle_fullscreen(self):
        self.set_display("windowed" if self.display_mode == "fullscreen" else "fullscreen")

    def push(self, state):
        self.states.append(state)
        state.enter()

    def pop(self):
        self.states.pop().exit()
        if self.states:
            self.states[-1].enter()
        else:
            self.running = False

    def replace(self, state):
        self.states.pop().exit()
        self.push(state)

    def unwind(self):
        while len(self.states) > 1:
            self.states.pop().exit()
        self.session = None
        self.states[-1].enter()

    def quit(self):
        self.running = False

    def run(self):
        from .states.main_menu import MainMenuState
        self.push(MainMenuState(self))
        last_input = pygame.time.get_ticks()
        while self.running:
            # В простое не крутим 120 кадров вхолостую (tick_busy_loop занимает ядро целиком), а ждём событие.
            top = self.states[-1] if self.states else None
            idle = (pygame.time.get_ticks() - last_input > config.IDLE_AFTER * 1000
                    and not (top is not None and top.animating()))
            if idle:
                first = pygame.event.wait(1000 // config.IDLE_FPS)
                events = ([first] if first.type != pygame.NOEVENT else []) + pygame.event.get()
                dt = min(self.clock.tick() / 1000.0, 0.1)
            else:
                dt = min(self.clock.tick_busy_loop(config.FPS) / 1000.0, 0.1)
                events = pygame.event.get()
            if events:
                last_input = pygame.time.get_ticks()
            self._sync_size()
            for event in events:
                if event.type == pygame.QUIT:
                    self.running = False
                elif event.type == pygame.KEYDOWN and event.key == pygame.K_F11:
                    self.toggle_fullscreen()
                elif self.states:
                    top = self.states[-1]
                    top.handle_event(event)
                    # Клик или Enter в модальном окне могли изменить игру под ним: подложку окна надо перерисовать.
                    if (event.type == pygame.MOUSEBUTTONUP or event.type == pygame.KEYDOWN and event.key in (
                            pygame.K_RETURN, pygame.K_KP_ENTER)) and hasattr(top, "refresh_backdrop"):
                        top.refresh_backdrop()
            if not self.running or not self.states:
                break
            state = self.states[-1]
            state.update(dt)
            if self.gpu:
                self.gpu.begin_frame()
            self.states[-1].draw(self.screen)
            if self.gpu:
                self.gpu.end_frame()
            pygame.display.flip()
        pygame.quit()


def main():
    if not config.WORLD_CACHE.exists():
        print("Нет кэша карты. Сначала выполните:\n"
              "  python tools/build_map.py\n"
              "  python tools/fetch_flags.py")
        sys.exit(1)
    App().run()
