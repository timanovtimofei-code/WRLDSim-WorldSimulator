import pygame


class MapController:
    DRAG_THRESHOLD = 5
    ZOOM_STEP = 1.25

    def __init__(self, camera):
        self.camera = camera
        self._down = None
        self._button = None
        self._dragging = False

    def handle_event(self, event, size):
        cam = self.camera
        if event.type == pygame.MOUSEBUTTONDOWN and event.button in (1, 2, 3):
            self._down, self._button, self._dragging = event.pos, event.button, False
        elif event.type == pygame.MOUSEMOTION and self._down is not None:
            if not self._dragging:
                dx, dy = event.pos[0] - self._down[0], event.pos[1] - self._down[1]
                self._dragging = dx * dx + dy * dy > self.DRAG_THRESHOLD ** 2
            if self._dragging:
                cam.pan(*event.rel, size)
        elif event.type == pygame.MOUSEBUTTONUP and event.button == self._button:
            click = event.pos if self._button == 1 and not self._dragging else None
            self._down, self._button, self._dragging = None, None, False
            return click
        elif event.type == pygame.MOUSEWHEEL:
            cam.zoom_at(self.ZOOM_STEP ** event.precise_y, pygame.mouse.get_pos(), size)
        elif event.type == pygame.KEYDOWN:
            center = (size[0] / 2, size[1] / 2)
            if event.key in (pygame.K_PLUS, pygame.K_EQUALS, pygame.K_KP_PLUS):
                cam.zoom_at(self.ZOOM_STEP, center, size)
            elif event.key in (pygame.K_MINUS, pygame.K_KP_MINUS):
                cam.zoom_at(1 / self.ZOOM_STEP, center, size)
        return None

    def reset(self):
        self._down, self._button, self._dragging = None, None, False
