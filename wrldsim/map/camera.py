# Камера карты: центр (x = долгота, y = -широта) и масштаб в пикселях на градус.
# На глобусе проекция ортографическая, радиус шара R = zoom * 180 / pi, точки обратной стороны не видны.
import math


def _ease(t):
    return 4 * t ** 3 if t < 0.5 else 1 - (-2 * t + 2) ** 3 / 2


OFF_GLOBE = (1e6, 1e6)


class Camera:
    MAX_ZOOM = 160.0
    GLOBE_FIT = 0.42

    def __init__(self, cx=15.0, cy=-25.0, zoom=4.5, globe=False):
        self.cx, self.cy, self.zoom = cx, cy, zoom
        self.globe = globe
        self.offset = (0.0, 0.0)
        self._anim = None

    def key(self):
        return round(self.cx, 4), round(self.cy, 4), round(self.zoom, 4), self.globe

    def snapshot(self):
        return self.cx, self.cy, self.zoom

    @property
    def radius(self):
        return self.zoom * 180.0 / math.pi

    def _ortho(self, x, y):
        lon, lat = math.radians(x - self.cx), math.radians(-y)
        lat0 = math.radians(-self.cy)
        cl = math.cos(lat)
        cosc = math.sin(lat0) * math.sin(lat) + math.cos(lat0) * cl * math.cos(lon)
        return cl * math.sin(lon), math.cos(lat0) * math.sin(lat) - math.sin(lat0) * cl * math.cos(lon), cosc

    def to_screen(self, x, y, size):
        if not self.globe:
            return (x - self.cx) * self.zoom + size[0] / 2, (y - self.cy) * self.zoom + size[1] / 2
        px, py, cosc = self._ortho(x, y)
        if cosc < 0:
            return -1e5, -1e5
        r = self.radius
        return size[0] / 2 + self.offset[0] + px * r, size[1] / 2 + self.offset[1] - py * r

    def visible(self, x, y):
        return not self.globe or self._ortho(x, y)[2] > 0.02

    def to_world(self, sx, sy, size):
        if not self.globe:
            return (sx - size[0] / 2) / self.zoom + self.cx, (sy - size[1] / 2) / self.zoom + self.cy
        r = self.radius
        x, y = (sx - size[0] / 2 - self.offset[0]) / r, -(sy - size[1] / 2 - self.offset[1]) / r
        rho = math.hypot(x, y)
        if rho >= 1.0:
            return OFF_GLOBE
        if rho < 1e-9:
            return self.cx, self.cy
        c = math.asin(rho)
        lat0 = math.radians(-self.cy)
        lat = math.asin(math.cos(c) * math.sin(lat0) + y * math.sin(c) * math.cos(lat0) / rho)
        lon = math.atan2(x * math.sin(c), rho * math.cos(c) * math.cos(lat0) - y * math.sin(c) * math.sin(lat0))
        wx = (self.cx + math.degrees(lon) + 180.0) % 360.0 - 180.0
        return wx, -math.degrees(lat)

    def view_bounds(self, size):
        if self.globe:
            return -180.0, -90.0, 180.0, 90.0
        hw, hh = size[0] / 2 / self.zoom, size[1] / 2 / self.zoom
        return self.cx - hw, self.cy - hh, self.cx + hw, self.cy + hh

    @staticmethod
    def min_zoom(size, globe=False):
        if globe:
            return min(size) * Camera.GLOBE_FIT * math.pi / 180.0
        return max(1.0, min(size[0] / 360, size[1] / 180) * 0.9)

    def clamp(self, size):
        self.zoom = min(max(self.zoom, self.min_zoom(size, self.globe)), self.MAX_ZOOM)
        if self.globe:
            self.cx = (self.cx + 180.0) % 360.0 - 180.0
            self.cy = min(max(self.cy, -85.0), 85.0)
        else:
            self.cx = min(max(self.cx, -180.0), 180.0)
            self.cy = min(max(self.cy, -90.0), 90.0)

    def set_view(self, view_rect, size, smooth=1.0):
        if not self.globe:
            self.offset = (0.0, 0.0)
            return False
        tx, ty = view_rect.centerx - size[0] / 2, view_rect.centery - size[1] / 2
        ox, oy = self.offset
        ox, oy = ox + (tx - ox) * smooth, oy + (ty - oy) * smooth
        if abs(tx - ox) < 0.5 and abs(ty - oy) < 0.5:
            ox, oy = tx, ty
        self.offset = (ox, oy)
        return (ox, oy) != (tx, ty)

    def stop(self):
        self._anim = None

    def pan(self, dx, dy, size):
        self.stop()
        if self.globe:
            # у полюсов градус долготы короче, поэтому поворот по x быстрее
            lat = math.radians(-self.cy)
            self.cx -= dx / self.zoom / max(math.cos(lat), 0.2)
            self.cy -= dy / self.zoom
        else:
            self.cx -= dx / self.zoom
            self.cy -= dy / self.zoom
        self.clamp(size)

    def zoom_at(self, factor, pos, size):
        self.stop()
        if self.globe:
            wx, wy = self.to_world(*pos, size)
            self.zoom *= factor
            if factor > 1 and (wx, wy) != OFF_GLOBE:
                t = 1 - 1 / factor
                dx = (wx - self.cx + 180.0) % 360.0 - 180.0
                self.cx += dx * t
                self.cy += (wy - self.cy) * t
            self.clamp(size)
            return
        wx, wy = self.to_world(*pos, size)
        self.zoom *= factor
        self.clamp(size)
        self.cx = wx - (pos[0] - size[0] / 2) / self.zoom
        self.cy = wy - (pos[1] - size[1] / 2) / self.zoom
        self.clamp(size)

    def fit(self, bbox, view_rect, size, padding=0.8):
        bw, bh = max(bbox[2] - bbox[0], 0.1), max(bbox[3] - bbox[1], 0.1)
        zoom = min(view_rect.w / bw, view_rect.h / bh) * padding
        zoom = min(max(zoom, self.min_zoom(size, self.globe)), self.MAX_ZOOM)
        bcx, bcy = (bbox[0] + bbox[2]) / 2, (bbox[1] + bbox[3]) / 2
        if self.globe:
            return bcx, bcy, zoom
        cx = bcx - (view_rect.centerx - size[0] / 2) / zoom
        cy = bcy - (view_rect.centery - size[1] / 2) / zoom
        return cx, cy, zoom

    def fly_to(self, cx, cy, zoom, duration=0.9, on_done=None):
        if self.globe:
            cx = self.cx + (cx - self.cx + 180.0) % 360.0 - 180.0
        self._anim = {"from": self.snapshot(), "to": (cx, cy, zoom), "t": 0.0,
                      "duration": duration, "on_done": on_done}

    @property
    def animating(self):
        return self._anim is not None

    def update(self, dt):
        if not self._anim:
            return
        a = self._anim
        a["t"] = min(a["t"] + dt / a["duration"], 1.0)
        e = _ease(a["t"])
        (x0, y0, z0), (x1, y1, z1) = a["from"], a["to"]
        self.cx = x0 + (x1 - x0) * e
        self.cy = y0 + (y1 - y0) * e
        self.zoom = math.exp(math.log(z0) + (math.log(z1) - math.log(z0)) * e)
        if self.globe:
            self.cx = (self.cx + 180.0) % 360.0 - 180.0
        if a["t"] >= 1.0:
            self._anim = None
            if a["on_done"]:
                a["on_done"]()
