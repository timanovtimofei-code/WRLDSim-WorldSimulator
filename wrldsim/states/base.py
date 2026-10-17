import pygame

from ..ui import theme
from ..ui.widgets import draw_panel, draw_spaced, draw_text


class State:
    def __init__(self, app):
        self.app = app

    def enter(self):
        pass

    def exit(self):
        pass

    def handle_event(self, event):
        pass

    def update(self, dt):
        pass

    def draw(self, surface):
        pass

    def animating(self):
        # True, пока экран движется сам (перелёт камеры, глитч, ожидание ИИ): тогда App не уходит в простой.
        return False


class ModalState(State):
    # Окно поверх предыдущего экрана. Экран под окном не обновляется, поэтому рисуется один раз и
    # запоминается снимком; снимок пересобирается после действий в окне, смены размера и темы.
    def __init__(self, app):
        super().__init__(app)
        self.below = app.states[-1] if app.states else None
        self._shade = None
        self._backdrop = None
        self._backdrop_key = None

    def refresh_backdrop(self):
        self._backdrop_key = None
        if isinstance(self.below, ModalState):
            self.below.refresh_backdrop()

    def exit(self):
        self._drop_backdrop()

    def _drop_backdrop(self):
        if self._backdrop is not None and not isinstance(self._backdrop, pygame.Surface):
            from ..ui import widgets
            if widgets.GPU is not None:
                widgets.GPU.release_snapshot(self._backdrop)
        self._backdrop = self._backdrop_key = None

    def draw_backdrop(self, surface):
        if self.below is None:
            return
        from ..ui import widgets
        size = surface.get_size()
        gpu = widgets.GPU if widgets.GPU is not None and surface is widgets.GPU.ui else None
        key = (size, theme.VERSION, gpu is not None)
        if self._backdrop is not None and self._backdrop_key == key:
            if gpu is not None:
                gpu.paste(self._backdrop)
            else:
                surface.blit(self._backdrop, (0, 0))
            return
        if self._backdrop is not None and (gpu is None) != isinstance(self._backdrop, pygame.Surface):
            self._drop_backdrop()
        self.below.draw(surface)
        if self._shade is None or self._shade.get_size() != size or self._shade.get_at((0, 0))[:3] != theme.OCEAN:
            self._shade = pygame.Surface(size, pygame.SRCALPHA)
            self._shade.fill((*theme.OCEAN, 150))
        surface.blit(self._shade, (0, 0))
        if gpu is not None:
            self._backdrop = gpu.capture(self._backdrop)
        else:
            self._backdrop = surface.copy()
        self._backdrop_key = key


def topbar_rect(size):
    return pygame.Rect(0, 0, size[0], theme.TOPBAR_H)


def draw_topbar(surface, app, subtitle="", brand=True):
    rect = topbar_rect(surface.get_size()).inflate(-16, -(theme.TOPBAR_H - 40))
    rect.y = 6
    draw_panel(surface, rect, alpha=235, border=None, radius=20)
    x = rect.x + 20
    if brand:
        x = draw_spaced(surface, "WRLDSIM", (x, rect.centery), 18, anchor="midleft").right + 24
    session = app.session
    if session and rect.w >= 1000:
        mode = app.modes["modes"][session.mode_id]
        label = mode["name"]
        if session.difficulty_id:
            label += " · " + mode["difficulties"][session.difficulty_id]["name"]
        if session.mode_id != "anime":
            label += " · " + app.eras.era(session.era_id)["short"]
        x = draw_text(surface, label, (x, rect.centery), 15, theme.ACCENT, bold=True, anchor="midleft").right + 24
    if subtitle:
        draw_text(surface, subtitle, (x, rect.centery), 15, theme.TEXT_DIM, anchor="midleft")
    return rect
