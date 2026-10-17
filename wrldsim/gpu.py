# Вывод через OpenGL 3.3: карта рисуется в multisample-буфер, интерфейс pygame - на прозрачную поверхность поверх.
# Перед каждой стеклянной панелью интерфейс сбрасывается в сцену (flush), чтобы стекло размывало то, что под ним.
import ctypes
import math

import numpy as np
import OpenGL
import pygame

OpenGL.ERROR_CHECKING = False   # проверка после каждого вызова стоит ~1 мс на кадр; шейдеры проверяем сами
from OpenGL import GL as gl  # noqa: E402

from .ui import theme

SAMPLES = 4
BLUR_DIV = 2

_VS_SCREEN = """
#version 330 core
layout(location=0) in vec2 a_pos;
uniform vec2 u_size;
out vec2 v_px;
void main() {
    v_px = a_pos;
    gl_Position = vec4(a_pos.x / u_size.x * 2.0 - 1.0, 1.0 - a_pos.y / u_size.y * 2.0, 0.0, 1.0);
}
"""

_FS_UI = """
#version 330 core
in vec2 v_px;
uniform vec2 u_size;
uniform sampler2D u_tex;
out vec4 frag;
void main() { frag = texture(u_tex, v_px / u_size); }
"""

_FS_SNAP = """
#version 330 core
in vec2 v_px;
uniform vec2 u_size;
uniform sampler2D u_tex;
out vec4 frag;
// снимок сцены лежит в текстуре по правилам GL (первая строка снизу), а пиксели экрана считаются сверху
void main() { frag = vec4(texture(u_tex, vec2(v_px.x / u_size.x, 1.0 - v_px.y / u_size.y)).rgb, 1.0); }
"""

# Глобус: шар радиусом u_r px, повёрнутый к точке u_c (долгота, широта в радианах); снимок Земли, облака, атмосфера.
_FS_GLOBE = """
#version 330 core
in vec2 v_px;
uniform vec2 u_size;
uniform vec2 u_c;
uniform float u_r;
uniform vec2 u_off;           // сдвиг центра шара от середины окна, px
uniform sampler2D u_earth;
uniform sampler2D u_clouds;
uniform float u_has_tex;      // 0 - снимков нет: шар цвета океана
uniform vec3 u_ocean;
uniform vec3 u_space;
uniform float u_cloud;        // плотность облаков
out vec4 frag;
float hash(vec2 p) { return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453); }
void main() {
    vec2 p = (v_px - u_size * 0.5 - u_off) / u_r;
    p.y = -p.y;
    float r2 = dot(p, p);
    vec3 atmo = vec3(0.35, 0.6, 1.0);
    if (r2 > 1.0) {
        vec2 cell = floor(v_px / 3.0);
        float h = hash(cell);
        float star = h > 0.9965 ? pow(hash(cell + 7.0), 6.0) * 0.9 + 0.1 : 0.0;
        vec3 c = u_space + vec3(star);
        float d = sqrt(r2) - 1.0;
        c += atmo * 0.55 * exp(-d * u_r / 14.0);
        frag = vec4(c, 1.0);
        return;
    }
    float z = sqrt(1.0 - r2);
    float lat0 = u_c.y;
    float lat = asin(clamp(z * sin(lat0) + p.y * cos(lat0), -1.0, 1.0));
    float lon = u_c.x + atan(p.x, z * cos(lat0) - p.y * sin(lat0));
    vec2 uv = vec2(fract(lon / 6.2831853 + 0.5), 0.5 - lat / 3.1415927);
    vec3 c = u_has_tex > 0.5 ? texture(u_earth, uv).rgb : u_ocean;
    // крупные озёра (Ладога, Байкал) на снимке Blue Marble почти чёрные: красим их в синеву моря
    c = mix(c, vec3(0.08, 0.22, 0.40), 1.0 - smoothstep(0.03, 0.07, max(c.r, max(c.g, c.b))));
    if (u_has_tex > 0.5 && u_cloud > 0.0) {
        float cl = texture(u_clouds, uv).r;
        c = mix(c, vec3(1.0), smoothstep(0.15, 0.9, cl) * u_cloud);
    }
    vec3 n = vec3(p.x, p.y, z);
    float light = 0.55 + 0.6 * max(dot(n, normalize(vec3(-0.45, 0.55, 0.7))), 0.0);
    c *= light;
    c = mix(c, atmo, pow(1.0 - z, 3.0) * 0.55);
    float edge = clamp((1.0 - sqrt(r2)) * u_r, 0.0, 1.0);
    frag = vec4(mix(u_space + atmo * 0.55, c, edge), 1.0);
}
"""

_VS_FULL = """
#version 330 core
layout(location=0) in vec2 a_pos;      // -1..1
out vec2 v_uv;
void main() { v_uv = a_pos * 0.5 + 0.5; gl_Position = vec4(a_pos, 0.0, 1.0); }
"""

_FS_BLUR = """
#version 330 core
in vec2 v_uv;
uniform sampler2D u_tex;
uniform vec2 u_step;
out vec4 frag;
void main() {
    const float w[5] = float[](0.2270270, 0.1945946, 0.1216216, 0.0540540, 0.0162162);
    vec4 c = texture(u_tex, v_uv) * w[0];
    for (int i = 1; i < 5; i++) {
        c += texture(u_tex, v_uv + u_step * float(i)) * w[i];
        c += texture(u_tex, v_uv - u_step * float(i)) * w[i];
    }
    frag = c;
}
"""

_FS_GLASS = """
#version 330 core
in vec2 v_px;
uniform vec2 u_size;
uniform vec4 u_rect;          // x, y, w, h
uniform float u_radius;
uniform float u_lens;         // ширина фаски, px
uniform float u_alpha;        // плотность стекла 0..1
uniform vec3 u_rim;           // цвет блика кромки
uniform vec3 u_tint;
uniform float u_glass;        // доля подкраски стекла (theme.GLASS_TINT, настройка оформления)
uniform float u_shadow;       // сила тени
uniform vec4 u_accent;        // rgb, доля
uniform vec2 u_light;
uniform sampler2D u_scene;
uniform sampler2D u_blur;
out vec4 frag;

// расстояние до скруглённого прямоугольника (углы - суперэллипс)
float g_n;
float sd_shape(vec2 p, vec2 half_, float r) {
    vec2 q = abs(p) - half_ + r;
    vec2 m = max(q, 0.0) / max(r, 1e-3);
    return pow(pow(m.x, g_n) + pow(m.y, g_n), 1.0 / g_n) * r + min(max(q.x, q.y), 0.0) - r;
}
vec3 spectrum(float t) { return 0.62 + 0.38 * cos(6.28318 * (vec3(0.0, 0.33, 0.67) - t * 0.85)); }
vec2 uv_of(vec2 px) { return vec2(px.x, u_size.y - px.y) / u_size; }
vec3 grade(vec3 c, float bright, float lift) {
    float g = dot(c, vec3(0.299, 0.587, 0.114));
    return clamp((vec3(g) + (c - g) * 1.45) * bright + lift, 0.0, 1.0);
}

void main() {
    vec2 half_ = u_rect.zw * 0.5;
    vec2 pc = v_px - (u_rect.xy + half_);
    float r = min(u_radius * 1.25, min(half_.x, half_.y));
    g_n = mix(3.0, 2.0, smoothstep(0.75, 1.0, r / max(min(half_.x, half_.y), 1.0)));
    float d = sd_shape(pc, half_, r);
    if (d > 0.5) {
        float ds = max(sd_shape(pc - vec2(0.0, 4.0), half_, r), 0.0);
        float a = u_shadow * (0.16 * exp(-ds * ds / (2.0 * 14.0 * 14.0)) + 0.10 * exp(-ds * ds / (2.0 * 3.0 * 3.0)));
        frag = vec4(0.0, 0.0, 0.0, a);
        return;
    }
    float depth = -d;
    float lens = max(u_lens, 1.0);
    float e = 1.0 - clamp(depth / lens, 0.0, 1.0);
    // нормаль наружу
    float big = max(r, min(lens, min(half_.x, half_.y)));
    vec2 o = max(abs(pc) - (half_ - big), 0.0);
    vec2 g2 = pow(o + 1e-6, vec2(g_n - 1.0));
    vec2 n = dot(g2, g2) > 1e-8 ? normalize(g2) * sign(pc) : vec2(0.0);

    float shift = lens * 0.6 * e * e;
    // дисперсия: каналы цвета берутся со сдвигом вдоль нормали
    vec3 disp = vec3(1.0 + 0.45 * e, 1.0, 1.0 - 0.45 * e);
    vec3 spread = vec3(-3.0, 0.0, 3.0) * e * e;
    float sharp_k = 0.35 + 0.2 * smoothstep(0.0, 1.0, e);
    float lum = dot(texture(u_blur, uv_of(v_px)).rgb, vec3(0.299, 0.587, 0.114));
    float k = clamp(lum * 255.0 / 110.0, 0.0, 1.0);
    float bright = 1.0 + 0.18 * (1.0 - k);
    float lift = 6.0 * (1.0 - 0.6 * k) / 255.0;
    vec3 c;
    for (int i = 0; i < 3; i++) {
        vec2 uv = uv_of(v_px - n * (shift * disp[i] + spread[i]));
        float soft = grade(texture(u_blur, uv).rgb, bright, lift)[i];
        float sharp = grade(texture(u_scene, uv).rgb, bright, lift)[i];
        c[i] = mix(soft, sharp, sharp_k);
    }
    float tint = clamp(u_alpha * u_glass * (0.72 + 0.4 * k), 0.0, 0.94);
    c = mix(c, u_tint, tint);
    c = mix(c, vec3(1.0), 0.02);
    c = mix(c, u_accent.rgb, u_accent.a);

    vec2 L = normalize(u_light);
    float fd = dot(n, L);
    float key = pow(max(fd, 0.0), 1.6);
    float back = pow(max(-fd, 0.0), 1.6) * 0.6;
    float lit = max(key, back);
    float line = 1.0 - smoothstep(0.0, 1.5, depth);
    float inner = exp(-pow((depth - 2.4) / 1.1, 2.0));
    float fres = pow(e, 3.0);
    float shine = line * (0.12 + 0.78 * lit) + inner * 0.14 * lit + fres * (0.01 + 0.08 * lit);
    float band = clamp(lens * 0.75, 6.0, 12.0);
    float rt = clamp((depth - 0.8) / band, 0.0, 1.0);
    float rw = smoothstep(0.0, 0.15, rt) * (1.0 - smoothstep(0.45, 1.0, rt));
    float hue = rt + 0.06 * atan(n.y, n.x);
    c = mix(c, spectrum(hue), rw * (0.05 + 0.05 * lit));
    c = mix(c, u_rim, clamp(shine, 0.0, 1.0));
    frag = vec4(c, clamp(0.5 - d, 0.0, 1.0));
}
"""

# Проекция мировой точки (долгота, -широта) на экран для всех слоёв карты: u_globe.x = 0 - плоская карта,
# 1 - глобус радиусом u_globe.w со сдвигом центра u_globe.yz. Третья компонента < 0 - обратная сторона шара.
_PROJ = """
uniform vec3 u_cam;
uniform vec2 u_size;
uniform vec4 u_globe;
vec3 map_px(vec2 p) {
    if (u_globe.x < 0.5) return vec3((p - u_cam.xy) * u_cam.z + u_size * 0.5, 1.0);
    float lon = radians(p.x - u_cam.x), lat = radians(-p.y), lat0 = radians(-u_cam.y);
    float cl = cos(lat);
    float cosc = sin(lat0) * sin(lat) + cos(lat0) * cl * cos(lon);
    vec2 d = vec2(cl * sin(lon), -(cos(lat0) * sin(lat) - sin(lat0) * cl * cos(lon)));
    return vec3(u_size * 0.5 + u_globe.yz + d * u_globe.w, cosc);
}
"""

_VS_MAP = """
#version 330 core
layout(location=0) in vec2 a_pos;
layout(location=1) in float a_owner;
uniform int u_mode;           // 0 - всё, 1 - кроме u_owner, 2 - только u_owner
uniform float u_owner;
out float v_keep;
out float v_front;
""" + _PROJ + """
void main() {
    bool same = abs(a_owner - u_owner) < 0.5;
    v_keep = u_mode == 0 ? 1.0 : (u_mode == 1 ? (same ? 0.0 : 1.0) : (same ? 1.0 : 0.0));
    vec3 px = map_px(a_pos);
    v_front = px.z;
    gl_Position = vec4(px.xy, 0.0, 1.0);
}
"""

_GS_FILL = """
#version 330 core
layout(triangles) in;
layout(triangle_strip, max_vertices=3) out;
in float v_keep[];
in float v_front[];
uniform vec2 u_size;
out float g_front;
void main() {
    if (v_keep[0] < 0.5) return;
    if (max(v_front[0], max(v_front[1], v_front[2])) < 0.0) return;
    for (int i = 0; i < 3; i++) {
        vec2 px = gl_in[i].gl_Position.xy;
        g_front = v_front[i];
        gl_Position = vec4(px.x / u_size.x * 2.0 - 1.0, 1.0 - px.y / u_size.y * 2.0, 0.0, 1.0);
        EmitVertex();
    }
    EndPrimitive();
}
"""

_GS_LINE = """
#version 330 core
layout(lines) in;
layout(triangle_strip, max_vertices=4) out;
in float v_keep[];
in float v_front[];
uniform vec2 u_size;
uniform float u_width;
out float g_d;
vec4 ndc(vec2 px) { return vec4(px.x / u_size.x * 2.0 - 1.0, 1.0 - px.y / u_size.y * 2.0, 0.0, 1.0); }
void main() {
    if (v_keep[0] < 0.5) return;
    if (min(v_front[0], v_front[1]) < 0.0) return;
    vec2 a = gl_in[0].gl_Position.xy, b = gl_in[1].gl_Position.xy;
    vec2 dir = b - a;
    float len = length(dir);
    if (len < 1e-4) return;
    dir /= len;
    float hw = u_width * 0.5 + 1.0;
    vec2 nrm = vec2(-dir.y, dir.x) * hw;
    vec2 ext = dir * u_width * 0.5;
    g_d = hw;  gl_Position = ndc(a - ext + nrm); EmitVertex();
    g_d = -hw; gl_Position = ndc(a - ext - nrm); EmitVertex();
    g_d = hw;  gl_Position = ndc(b + ext + nrm); EmitVertex();
    g_d = -hw; gl_Position = ndc(b + ext - nrm); EmitVertex();
    EndPrimitive();
}
"""

_FS_COLOR = """
#version 330 core
in float g_front;
uniform vec4 u_color;
out vec4 frag;
void main() {
    if (g_front < 0.0) discard;
    frag = u_color;
}
"""

_FS_LINE = """
#version 330 core
in float g_d;
uniform vec4 u_color;
uniform float u_width;
out vec4 frag;
void main() {
    float a = clamp(u_width * 0.5 + 0.5 - abs(g_d), 0.0, 1.0);
    frag = vec4(u_color.rgb, u_color.a * a);
}
"""


# Атлас: хозяева атомов - в текстуре u_atoms (r - ключ цвета, g - государство, b - держава), цвета - в u_pal.
_VS_ATLAS = """
#version 330 core
layout(location=0) in vec2 a_pos;
layout(location=1) in float a_atom;
uniform sampler2D u_atoms;
uniform sampler2D u_pal;
uniform int u_tw;
uniform float u_hl;           // ключ цвета, который подсвечиваем (-1 - никакой)
uniform float u_hl_amt;
uniform vec4 u_dim;           // x - ключ цвета, который не гасим (-1 - гасить некого), y - сила затемнения
uniform vec3 u_dimc;
uniform float u_alpha;        // плотность заливки: на глобусе сквозь неё видна Земля
out vec4 v_col;
out float v_front;
""" + _PROJ + """
void main() {
    int i = int(a_atom + 0.5);
    vec4 info = texelFetch(u_atoms, ivec2(i % u_tw, i / u_tw), 0);
    vec4 c = texelFetch(u_pal, ivec2(int(info.r + 0.5), 0), 0);
    if (abs(info.r - u_hl) < 0.5) c.rgb = mix(c.rgb, vec3(1.0), u_hl_amt);
    if (u_dim.x >= 0.0 && abs(info.r - u_dim.x) > 0.5) c.rgb = mix(c.rgb, u_dimc, u_dim.y);
    v_col = vec4(c.rgb, c.a * u_alpha);
    if (u_alpha < 1.0 && info.r < 0.5) v_col.a = 0.0;
    vec3 px = map_px(a_pos);
    v_front = px.z;
    gl_Position = vec4(px.x / u_size.x * 2.0 - 1.0, 1.0 - px.y / u_size.y * 2.0, 0.0, 1.0);
}
"""

_FS_ATLAS = """
#version 330 core
in vec4 v_col;
in float v_front;
out vec4 frag;
void main() {
    if (v_front < 0.0) discard;
    frag = v_col;
}
"""

_VS_ATLAS_LINE = """
#version 330 core
layout(location=0) in vec2 a_pos;
layout(location=1) in vec2 a_ab;
uniform sampler2D u_atoms;
uniform int u_tw;
out float v_level;
out float v_front;
""" + _PROJ + """
void main() {
    int a = int(a_ab.x + 0.5), b = int(a_ab.y + 0.5);
    vec4 ia = texelFetch(u_atoms, ivec2(a % u_tw, a / u_tw), 0);
    vec4 ib = texelFetch(u_atoms, ivec2(b % u_tw, b / u_tw), 0);
    v_level = ia.b != ib.b ? 3.0 : ((ia.g != ib.g || ia.r != ib.r) ? 2.0 : 1.0);
    vec3 px = map_px(a_pos);
    v_front = px.z;
    gl_Position = vec4(px.xy, 0.0, 1.0);
}
"""

_GS_ATLAS_LINE = """
#version 330 core
layout(lines) in;
layout(triangle_strip, max_vertices=4) out;
in float v_level[];
in float v_front[];
uniform vec2 u_size;
uniform vec3 u_w;             // толщина границ уровней 1..3, px
uniform vec3 u_a;             // их плотность (0 - не рисовать)
out float g_d;
out float g_w;
out float g_a;
vec4 ndc(vec2 px) { return vec4(px.x / u_size.x * 2.0 - 1.0, 1.0 - px.y / u_size.y * 2.0, 0.0, 1.0); }
void main() {
    int k = int(v_level[0] + 0.5);
    float width = k == 1 ? u_w.x : (k == 2 ? u_w.y : u_w.z);
    float alpha = k == 1 ? u_a.x : (k == 2 ? u_a.y : u_a.z);
    if (alpha <= 0.0) return;
    if (min(v_front[0], v_front[1]) < 0.0) return;
    vec2 a = gl_in[0].gl_Position.xy, b = gl_in[1].gl_Position.xy;
    vec2 dir = b - a;
    float len = length(dir);
    if (len < 1e-4) return;
    dir /= len;
    float hw = width * 0.5 + 1.0;
    vec2 nrm = vec2(-dir.y, dir.x) * hw;
    vec2 ext = dir * width * 0.5;
    g_w = width; g_a = alpha;
    g_d = hw;  gl_Position = ndc(a - ext + nrm); EmitVertex();
    g_d = -hw; gl_Position = ndc(a - ext - nrm); EmitVertex();
    g_d = hw;  gl_Position = ndc(b + ext + nrm); EmitVertex();
    g_d = -hw; gl_Position = ndc(b + ext - nrm); EmitVertex();
    EndPrimitive();
}
"""

_FS_ATLAS_LINE = """
#version 330 core
in float g_d;
in float g_w;
in float g_a;
uniform vec3 u_color;
out vec4 frag;
void main() {
    float a = clamp(g_w * 0.5 + 0.5 - abs(g_d), 0.0, 1.0);
    frag = vec4(u_color, g_a * a);
}
"""


def _shader(kind, src):
    sh = gl.glCreateShader(kind)
    gl.glShaderSource(sh, src)
    gl.glCompileShader(sh)
    if not gl.glGetShaderiv(sh, gl.GL_COMPILE_STATUS):
        raise RuntimeError(gl.glGetShaderInfoLog(sh).decode(errors="replace"))
    return sh


class Program:
    def __init__(self, vs, fs, gs=None):
        self.id = gl.glCreateProgram()
        stages = [_shader(gl.GL_VERTEX_SHADER, vs), _shader(gl.GL_FRAGMENT_SHADER, fs)]
        if gs:
            stages.append(_shader(gl.GL_GEOMETRY_SHADER, gs))
        for sh in stages:
            gl.glAttachShader(self.id, sh)
        gl.glLinkProgram(self.id)
        if not gl.glGetProgramiv(self.id, gl.GL_LINK_STATUS):
            raise RuntimeError(gl.glGetProgramInfoLog(self.id).decode(errors="replace"))
        for sh in stages:
            gl.glDeleteShader(sh)
        self._loc = {}

    def use(self, **uniforms):
        gl.glUseProgram(self.id)
        for name, value in uniforms.items():
            loc = self._loc.get(name)
            if loc is None:
                loc = self._loc[name] = gl.glGetUniformLocation(self.id, name)
            if loc < 0:
                continue
            if isinstance(value, int) and not isinstance(value, bool):
                gl.glUniform1i(loc, value)
            elif isinstance(value, float):
                gl.glUniform1f(loc, value)
            else:
                v = [float(x) for x in value]
                (gl.glUniform2f, gl.glUniform3f, gl.glUniform4f)[len(v) - 2](loc, *v)


class Mesh:
    def __init__(self, data=None, comps=2, dynamic=False):
        self.comps = comps
        self.count = 0
        self.vao = gl.glGenVertexArrays(1)
        self.vbo = gl.glGenBuffers(1)
        self._usage = gl.GL_DYNAMIC_DRAW if dynamic else gl.GL_STATIC_DRAW
        gl.glBindVertexArray(self.vao)
        gl.glBindBuffer(gl.GL_ARRAY_BUFFER, self.vbo)
        stride = comps * 4
        gl.glEnableVertexAttribArray(0)
        gl.glVertexAttribPointer(0, 2, gl.GL_FLOAT, False, stride, ctypes.c_void_p(0))
        if comps > 2:
            gl.glEnableVertexAttribArray(1)
            gl.glVertexAttribPointer(1, comps - 2, gl.GL_FLOAT, False, stride, ctypes.c_void_p(8))
        else:
            gl.glDisableVertexAttribArray(1)
            gl.glVertexAttrib1f(1, -1.0)
        gl.glBindVertexArray(0)
        if data is not None:
            self.upload(data)

    def upload(self, data):
        data = np.ascontiguousarray(data, dtype=np.float32).reshape(-1, self.comps)
        self.count = len(data)
        gl.glBindBuffer(gl.GL_ARRAY_BUFFER, self.vbo)
        gl.glBufferData(gl.GL_ARRAY_BUFFER, data.nbytes if len(data) else 4, data if len(data) else None, self._usage)

    def draw(self, mode):
        if self.count:
            gl.glBindVertexArray(self.vao)
            gl.glDrawArrays(mode, 0, self.count)

    def release(self):
        gl.glDeleteBuffers(1, [self.vbo])
        gl.glDeleteVertexArrays(1, [self.vao])


def _texture(w, h, linear=True):
    tex = gl.glGenTextures(1)
    gl.glBindTexture(gl.GL_TEXTURE_2D, tex)
    f = gl.GL_LINEAR if linear else gl.GL_NEAREST
    gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_MIN_FILTER, f)
    gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_MAG_FILTER, f)
    gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_WRAP_S, gl.GL_CLAMP_TO_EDGE)
    gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_WRAP_T, gl.GL_CLAMP_TO_EDGE)
    gl.glTexImage2D(gl.GL_TEXTURE_2D, 0, gl.GL_RGBA8, w, h, 0, gl.GL_RGBA, gl.GL_UNSIGNED_BYTE, None)
    return tex


def _fbo_with(tex):
    fbo = gl.glGenFramebuffers(1)
    gl.glBindFramebuffer(gl.GL_FRAMEBUFFER, fbo)
    gl.glFramebufferTexture2D(gl.GL_FRAMEBUFFER, gl.GL_COLOR_ATTACHMENT0, gl.GL_TEXTURE_2D, tex, 0)
    return fbo


def _rgb(color, a=1.0):
    return (color[0] / 255, color[1] / 255, color[2] / 255, a)


class AtlasTex:
    WIDTH = 4096

    def __init__(self):
        self.info, self.pal = gl.glGenTextures(2)
        for t in (self.info, self.pal):
            gl.glBindTexture(gl.GL_TEXTURE_2D, t)
            gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_MIN_FILTER, gl.GL_NEAREST)
            gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_MAG_FILTER, gl.GL_NEAREST)
            gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_WRAP_S, gl.GL_CLAMP_TO_EDGE)
            gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_WRAP_T, gl.GL_CLAMP_TO_EDGE)

    def set_atoms(self, data):
        rows = -(-len(data) // self.WIDTH)
        buf = np.zeros((rows * self.WIDTH, 4), np.float32)
        buf[:len(data)] = data
        gl.glBindTexture(gl.GL_TEXTURE_2D, self.info)
        gl.glTexImage2D(gl.GL_TEXTURE_2D, 0, gl.GL_RGBA32F, self.WIDTH, rows, 0, gl.GL_RGBA, gl.GL_FLOAT, buf)

    def set_palette(self, rgba):
        rgba = np.ascontiguousarray(rgba, np.uint8)
        gl.glBindTexture(gl.GL_TEXTURE_2D, self.pal)
        gl.glPixelStorei(gl.GL_UNPACK_ALIGNMENT, 1)
        gl.glTexImage2D(gl.GL_TEXTURE_2D, 0, gl.GL_RGBA8, len(rgba), 1, 0, gl.GL_RGBA, gl.GL_UNSIGNED_BYTE, rgba)

    def release(self):
        gl.glDeleteTextures([self.info, self.pal])


class GPU:
    def __init__(self, size):
        self.size = (0, 0)
        self.ui = None
        self.p_ui = Program(_VS_SCREEN, _FS_UI)
        self.p_snap = Program(_VS_SCREEN, _FS_SNAP)
        self.p_globe = Program(_VS_SCREEN, _FS_GLOBE)
        self._globe_tex = None
        self.p_glass = Program(_VS_SCREEN, _FS_GLASS)
        self.p_blur = Program(_VS_FULL, _FS_BLUR)
        self.p_fill = Program(_VS_MAP, _FS_COLOR, _GS_FILL)
        self.p_line = Program(_VS_MAP, _FS_LINE, _GS_LINE)
        self.p_atlas = Program(_VS_ATLAS, _FS_ATLAS)
        self.p_atlas_line = Program(_VS_ATLAS_LINE, _FS_ATLAS_LINE, _GS_ATLAS_LINE)
        self.quad = Mesh(dynamic=True)
        self.full = Mesh(np.array([-1, -1, 1, -1, -1, 1, 1, 1], np.float32))
        self._objs = None
        self.light = (-0.55, -0.83)
        self.resize(size)

    def _free(self):
        if self._objs:
            fbos, texs, rbs = self._objs
            gl.glDeleteFramebuffers(len(fbos), fbos)
            gl.glDeleteTextures(texs)
            gl.glDeleteRenderbuffers(len(rbs), rbs)

    def resize(self, size):
        size = (max(1, size[0]), max(1, size[1]))
        if size == self.size:
            return
        self._free()
        self.size = w, h = size
        self.ms_rb = gl.glGenRenderbuffers(1)
        gl.glBindRenderbuffer(gl.GL_RENDERBUFFER, self.ms_rb)
        gl.glRenderbufferStorageMultisample(gl.GL_RENDERBUFFER, SAMPLES, gl.GL_RGBA8, w, h)
        self.ms_fbo = gl.glGenFramebuffers(1)
        gl.glBindFramebuffer(gl.GL_FRAMEBUFFER, self.ms_fbo)
        gl.glFramebufferRenderbuffer(gl.GL_FRAMEBUFFER, gl.GL_COLOR_ATTACHMENT0, gl.GL_RENDERBUFFER, self.ms_rb)
        self.scene_tex = _texture(w, h)
        self.scene_fbo = _fbo_with(self.scene_tex)
        sw, sh = max(1, w // BLUR_DIV), max(1, h // BLUR_DIV)
        self.small = (sw, sh)
        self.blur_tex = [_texture(sw, sh), _texture(sw, sh)]
        self.blur_fbo = [_fbo_with(t) for t in self.blur_tex]
        self.ui_tex = _texture(w, h, linear=False)
        gl.glBindFramebuffer(gl.GL_FRAMEBUFFER, 0)
        self._objs = ([self.ms_fbo, self.scene_fbo, *self.blur_fbo],
                      [self.scene_tex, *self.blur_tex, self.ui_tex], [self.ms_rb])
        self.ui = pygame.Surface(size, pygame.SRCALPHA)

    def begin_frame(self):
        w, h = self.size
        gl.glBindFramebuffer(gl.GL_FRAMEBUFFER, self.ms_fbo)
        gl.glViewport(0, 0, w, h)
        gl.glEnable(gl.GL_BLEND)
        gl.glBlendFuncSeparate(gl.GL_SRC_ALPHA, gl.GL_ONE_MINUS_SRC_ALPHA, gl.GL_ONE, gl.GL_ONE_MINUS_SRC_ALPHA)
        c = _rgb(theme.OCEAN)
        gl.glClearColor(*c)
        gl.glClear(gl.GL_COLOR_BUFFER_BIT)
        self.ui.fill((0, 0, 0, 0))

    def end_frame(self):
        self.flush()
        w, h = self.size
        gl.glBindFramebuffer(gl.GL_READ_FRAMEBUFFER, self.ms_fbo)
        gl.glBindFramebuffer(gl.GL_DRAW_FRAMEBUFFER, 0)
        gl.glBlitFramebuffer(0, 0, w, h, 0, 0, w, h, gl.GL_COLOR_BUFFER_BIT, gl.GL_NEAREST)
        gl.glBindFramebuffer(gl.GL_FRAMEBUFFER, 0)

    def _quad_px(self, rect):
        x, y, w, h = rect
        self.quad.upload(np.array([x, y, x + w, y, x, y + h, x + w, y + h], np.float32))
        self.quad.draw(gl.GL_TRIANGLE_STRIP)

    def _dirty_rect(self):
        view = self.ui.get_view("2")
        px = np.asarray(view).T
        wide = px.view(np.uint64) if px.shape[1] % 2 == 0 else px
        rows = np.flatnonzero(wide.any(axis=1))
        if len(rows) == 0:
            return None
        cols = np.flatnonzero(px[rows[0]:rows[-1] + 1].any(axis=0))
        del px, wide, view
        return pygame.Rect(int(cols[0]), int(rows[0]), int(cols[-1] - cols[0] + 1), int(rows[-1] - rows[0] + 1))

    def flush(self):
        r = self._dirty_rect()
        if r is None:
            return
        data = pygame.image.tobytes(self.ui.subsurface(r), "RGBA")
        gl.glBindTexture(gl.GL_TEXTURE_2D, self.ui_tex)
        gl.glPixelStorei(gl.GL_UNPACK_ALIGNMENT, 1)
        gl.glTexSubImage2D(gl.GL_TEXTURE_2D, 0, r.x, r.y, r.w, r.h, gl.GL_RGBA, gl.GL_UNSIGNED_BYTE, data)
        gl.glBindFramebuffer(gl.GL_FRAMEBUFFER, self.ms_fbo)
        gl.glViewport(0, 0, *self.size)
        self.p_ui.use(u_size=self.size, u_tex=0)
        gl.glActiveTexture(gl.GL_TEXTURE0)
        gl.glBindTexture(gl.GL_TEXTURE_2D, self.ui_tex)
        self._quad_px(r)
        self.ui.fill((0, 0, 0, 0), r)

    def capture(self, snap=None):
        self.flush()
        w, h = self.size
        if snap is None or snap[2] != self.size:
            self.release_snapshot(snap)
            tex = _texture(w, h, linear=False)
            snap = (tex, _fbo_with(tex), self.size)
        gl.glBindFramebuffer(gl.GL_READ_FRAMEBUFFER, self.ms_fbo)
        gl.glBindFramebuffer(gl.GL_DRAW_FRAMEBUFFER, snap[1])
        gl.glBlitFramebuffer(0, 0, w, h, 0, 0, w, h, gl.GL_COLOR_BUFFER_BIT, gl.GL_NEAREST)
        gl.glBindFramebuffer(gl.GL_FRAMEBUFFER, self.ms_fbo)
        return snap

    def paste(self, snap):
        self.flush()
        gl.glBindFramebuffer(gl.GL_FRAMEBUFFER, self.ms_fbo)
        gl.glViewport(0, 0, *self.size)
        gl.glDisable(gl.GL_BLEND)
        self.p_snap.use(u_size=self.size, u_tex=0)
        gl.glActiveTexture(gl.GL_TEXTURE0)
        gl.glBindTexture(gl.GL_TEXTURE_2D, snap[0])
        self._quad_px((0, 0, *self.size))
        gl.glEnable(gl.GL_BLEND)

    @staticmethod
    def release_snapshot(snap):
        if snap:
            gl.glDeleteFramebuffers(1, [snap[1]])
            gl.glDeleteTextures([snap[0]])

    def set_light(self, vec):
        self.light = vec

    def glass(self, rect, radius, alpha, rim, lens, *, shadow=1.0, accent=None):
        self.flush()
        w, h = self.size
        sw, sh = self.small
        # Снимок и размытие только вокруг стекла, а не всего экрана; координаты GL - снизу вверх.
        m = 64
        x0, x1 = max(0, int(rect[0]) - m), min(w, int(rect[0] + rect[2]) + m)
        y1, y0 = min(h, h - int(rect[1]) + m), max(0, h - int(rect[1] + rect[3]) - m)
        if x1 <= x0 or y1 <= y0:
            return
        sx0, sy0 = x0 * sw // w, y0 * sh // h
        sx1, sy1 = min(sw, -(-x1 * sw // w)), min(sh, -(-y1 * sh // h))
        gl.glBindFramebuffer(gl.GL_READ_FRAMEBUFFER, self.ms_fbo)
        gl.glBindFramebuffer(gl.GL_DRAW_FRAMEBUFFER, self.scene_fbo)
        gl.glBlitFramebuffer(x0, y0, x1, y1, x0, y0, x1, y1, gl.GL_COLOR_BUFFER_BIT, gl.GL_NEAREST)
        gl.glBindFramebuffer(gl.GL_READ_FRAMEBUFFER, self.scene_fbo)
        gl.glBindFramebuffer(gl.GL_DRAW_FRAMEBUFFER, self.blur_fbo[0])
        gl.glBlitFramebuffer(sx0 * w // sw, sy0 * h // sh, sx1 * w // sw, sy1 * h // sh, sx0, sy0, sx1, sy1,
                             gl.GL_COLOR_BUFFER_BIT, gl.GL_LINEAR)
        gl.glDisable(gl.GL_BLEND)
        gl.glEnable(gl.GL_SCISSOR_TEST)
        gl.glScissor(sx0, sy0, sx1 - sx0, sy1 - sy0)
        gl.glViewport(0, 0, sw, sh)
        gl.glActiveTexture(gl.GL_TEXTURE0)
        for _ in range(2):
            for src, dst, step in ((0, 1, (1 / sw, 0.0)), (1, 0, (0.0, 1 / sh))):
                gl.glBindFramebuffer(gl.GL_FRAMEBUFFER, self.blur_fbo[dst])
                gl.glBindTexture(gl.GL_TEXTURE_2D, self.blur_tex[src])
                self.p_blur.use(u_tex=0, u_step=step)
                self.full.draw(gl.GL_TRIANGLE_STRIP)
        gl.glDisable(gl.GL_SCISSOR_TEST)
        gl.glEnable(gl.GL_BLEND)

        gl.glBindFramebuffer(gl.GL_FRAMEBUFFER, self.ms_fbo)
        gl.glViewport(0, 0, w, h)
        gl.glActiveTexture(gl.GL_TEXTURE0)
        gl.glBindTexture(gl.GL_TEXTURE_2D, self.scene_tex)
        gl.glActiveTexture(gl.GL_TEXTURE1)
        gl.glBindTexture(gl.GL_TEXTURE_2D, self.blur_tex[0])
        gl.glActiveTexture(gl.GL_TEXTURE0)
        self.p_glass.use(u_size=self.size, u_rect=tuple(rect), u_radius=float(radius), u_lens=float(lens),
                         u_alpha=alpha / 255.0, u_rim=_rgb(rim)[:3], u_tint=_rgb(theme.GLASS_COLOR)[:3], u_glass=float(theme.GLASS_TINT),
                         u_light=self.light, u_scene=0, u_blur=1, u_shadow=float(shadow),
                         u_accent=(*_rgb(accent[0])[:3], float(accent[1])) if accent else (0.0, 0.0, 0.0, 0.0))
        pad = 30
        self._quad_px((rect[0] - pad, rect[1] - pad, rect[2] + 2 * pad, rect[3] + 2 * pad))

    def _load_globe_textures(self):
        from . import config
        out = []
        for name in ("earth_5400.jpg", "clouds_2048.jpg"):
            path = config.DATA_DIR / "textures" / name
            try:
                img = pygame.image.load(str(path))
            except (pygame.error, FileNotFoundError, OSError):
                return ()
            w, h = img.get_size()
            data = pygame.image.tobytes(img, "RGB")
            tex = gl.glGenTextures(1)
            gl.glBindTexture(gl.GL_TEXTURE_2D, tex)
            gl.glPixelStorei(gl.GL_UNPACK_ALIGNMENT, 1)
            gl.glTexImage2D(gl.GL_TEXTURE_2D, 0, gl.GL_RGB8, w, h, 0, gl.GL_RGB, gl.GL_UNSIGNED_BYTE, data)
            gl.glGenerateMipmap(gl.GL_TEXTURE_2D)
            gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_MIN_FILTER, gl.GL_LINEAR_MIPMAP_LINEAR)
            gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_MAG_FILTER, gl.GL_LINEAR)
            gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_WRAP_S, gl.GL_REPEAT)
            gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_WRAP_T, gl.GL_CLAMP_TO_EDGE)
            out.append(tex)
        return tuple(out)

    @property
    def has_earth(self):
        if self._globe_tex is None:
            self._globe_tex = self._load_globe_textures()
        return bool(self._globe_tex)

    def globe_base(self, camera):
        self.flush()
        has = self.has_earth
        gl.glBindFramebuffer(gl.GL_FRAMEBUFFER, self.ms_fbo)
        gl.glViewport(0, 0, *self.size)
        gl.glDisable(gl.GL_BLEND)
        if has:
            gl.glActiveTexture(gl.GL_TEXTURE4)
            gl.glBindTexture(gl.GL_TEXTURE_2D, self._globe_tex[0])
            gl.glActiveTexture(gl.GL_TEXTURE5)
            gl.glBindTexture(gl.GL_TEXTURE_2D, self._globe_tex[1])
            gl.glActiveTexture(gl.GL_TEXTURE0)
        cloud = 0.0 if not has else max(0.0, 0.6 - 0.6 * (camera.zoom - 3.0) / 9.0)
        self.p_globe.use(u_size=self.size, u_c=(math.radians(camera.cx), math.radians(-camera.cy)),
                         u_r=float(camera.radius), u_off=tuple(float(v) for v in camera.offset), u_earth=4, u_clouds=5, u_has_tex=1.0 if has else 0.0,
                         u_ocean=_rgb(theme.OCEAN)[:3], u_space=_rgb(theme.mix(theme.OCEAN, (0, 0, 0), 0.6))[:3],
                         u_cloud=float(cloud))
        self._quad_px((0, 0, *self.size))
        gl.glEnable(gl.GL_BLEND)

    def map_uniforms(self, camera):
        globe = ((1.0, float(camera.offset[0]), float(camera.offset[1]), float(camera.radius))
                 if getattr(camera, "globe", False) else (0.0, 0.0, 0.0, 0.0))
        return {"u_cam": (camera.cx, camera.cy, camera.zoom), "u_size": self.size, "u_globe": globe}

    def fill(self, mesh, camera, color, mode=0, owner=-1, alpha=1.0):
        gl.glBindFramebuffer(gl.GL_FRAMEBUFFER, self.ms_fbo)
        self.p_fill.use(**self.map_uniforms(camera), u_mode=mode, u_owner=float(owner), u_color=_rgb(color, alpha))
        mesh.draw(gl.GL_TRIANGLES)

    def lines(self, mesh, camera, color, width=1.0, mode=0, owner=-1, alpha=1.0):
        gl.glBindFramebuffer(gl.GL_FRAMEBUFFER, self.ms_fbo)
        self.p_line.use(**self.map_uniforms(camera), u_mode=mode, u_owner=float(owner), u_color=_rgb(color, alpha),
                        u_width=float(width))
        mesh.draw(gl.GL_LINES)
    def _bind_atlas(self, tex):
        gl.glActiveTexture(gl.GL_TEXTURE2)
        gl.glBindTexture(gl.GL_TEXTURE_2D, tex.info)
        gl.glActiveTexture(gl.GL_TEXTURE3)
        gl.glBindTexture(gl.GL_TEXTURE_2D, tex.pal)
        gl.glActiveTexture(gl.GL_TEXTURE0)

    def atlas_fill(self, mesh, camera, tex, hl=-1, hl_amt=0.0, dim=-1, dim_amt=0.0, dim_color=(30, 30, 34), alpha=1.0):
        gl.glBindFramebuffer(gl.GL_FRAMEBUFFER, self.ms_fbo)
        self._bind_atlas(tex)
        self.p_atlas.use(**self.map_uniforms(camera), u_atoms=2, u_pal=3, u_tw=AtlasTex.WIDTH, u_alpha=float(alpha),
                         u_hl=float(hl), u_hl_amt=float(hl_amt), u_dim=(float(dim), float(dim_amt), 0.0, 0.0),
                         u_dimc=_rgb(dim_color)[:3])
        mesh.draw(gl.GL_TRIANGLES)

    def atlas_lines(self, mesh, camera, tex, color, widths, alphas):
        gl.glBindFramebuffer(gl.GL_FRAMEBUFFER, self.ms_fbo)
        self._bind_atlas(tex)
        self.p_atlas_line.use(**self.map_uniforms(camera), u_atoms=2, u_tw=AtlasTex.WIDTH,
                              u_color=_rgb(color)[:3], u_w=tuple(widths), u_a=tuple(alphas))
        mesh.draw(gl.GL_LINES)


def create(size):
    try:
        return GPU(size)
    except Exception as e:
        print("GPU недоступен, программный вывод:", e)
        return None
