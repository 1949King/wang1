"""GPU 滤镜预览组件（第②层：剪辑不卡）

QOpenGLWidget + GLSL 滤镜链：
  帧上传纹理 → shader 一次完成 滤镜/亮度/对比度/饱和度/曝光/伽马/色相/锐化/模糊/暗角/不透明度/缩放
  → GPU 做信箱式缩放显示，替代 CPU numpy 逐帧 + QLabel SmoothTransformation。

设计约束：
- 滤镜数学与 PreviewManager._apply_named_filter / _apply_effects_sync 对齐（预览=导出口径）。
- 对比度/清新/复古的中性轴用帧亮度均值（u_pivot），由 32x32 缩略图在 CPU 侧廉价求得，与 numpy 版一致。
- 卷积核（锐化/模糊）单通着色器只能采样原图纹理，属已知近似；多级效果栈留待第③层 FBO。
- GL 初始化失败时 gl_ok=False，调用方回退既有 CPU 路径，行为完全不变。
"""

from typing import Optional, Dict, Any

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QImage
from PyQt6.QtOpenGLWidgets import QOpenGLWidget
from PyQt6.QtOpenGL import (
    QOpenGLShaderProgram,
    QOpenGLShader,
    QOpenGLTexture,
    QOpenGLBuffer,
    QOpenGLVertexArrayObject,
    QOpenGLVersionFunctionsFactory,
    QOpenGLVersionProfile,
)

from app.modules.utils.logger import logger

# GL 常量（避免依赖 PyOpenGL）
GL_COLOR_BUFFER_BIT = 0x00004000
GL_TRIANGLE_STRIP = 0x0005
GL_FLOAT = 0x1406

# 滤镜名 → shader 分支编号（与 _apply_named_filter 对齐；自然等走 8=默认饱和增强）
FILTER_IDS = {
    "黑白": 1,
    "暖色调": 2, "黄昏": 2,
    "冷色调": 3, "都市": 3,
    "清新": 4,
    "复古": 5, "电影感": 5,
    "梦幻": 6, "柔和": 6,
    "锐利": 7,
}

_VERT_SRC = """
attribute vec2 a_pos;
attribute vec2 a_uv;
varying vec2 v_uv;
uniform float u_scale;
void main() {
    v_uv = a_uv;
    float s = max(u_scale, 0.01);
    gl_Position = vec4(a_pos * s, 0.0, 1.0);
}
"""

_FRAG_SRC = """
#ifdef GL_ES
precision mediump float;
#endif

varying vec2 v_uv;
uniform sampler2D u_tex;
uniform sampler2D u_lut;
uniform vec2 u_texel;
uniform int u_filter;
uniform float u_intensity;
uniform float u_pivot;
uniform float u_brightness;
uniform float u_contrast;
uniform float u_saturation;
uniform float u_exposure;
uniform float u_gamma;
uniform float u_hue;
uniform float u_sharpen;
uniform float u_blur;
uniform float u_vignette;
uniform float u_opacity;
uniform float u_lut_size;
uniform float u_lut_intensity;

float luma(vec3 c) { return dot(c, vec3(0.299, 0.587, 0.114)); }

vec3 applyLut2D(vec3 c) {
    float s = max(u_lut_size, 2.0);
    float blue = clamp(c.b, 0.0, 1.0) * (s - 1.0);
    float b0 = floor(blue);
    float b1 = min(b0 + 1.0, s - 1.0);
    float bf = blue - b0;
    float r = clamp(c.r, 0.0, 1.0) * (s - 1.0) + 0.5;
    float g = clamp(c.g, 0.0, 1.0) * (s - 1.0) + 0.5;
    float u0 = (b0 * s + r) / (s * s);
    float u1 = (b1 * s + r) / (s * s);
    float v = g / s;
    vec3 s0 = texture2D(u_lut, vec2(u0, v)).rgb;
    vec3 s1 = texture2D(u_lut, vec2(u1, v)).rgb;
    return mix(s0, s1, bf);
}

vec3 gauss3(vec2 uv, vec2 r) {
    vec3 s = texture2D(u_tex, uv + vec2(-r.x, -r.y)).rgb;
    s += texture2D(u_tex, uv + vec2(0.0, -r.y)).rgb * 2.0;
    s += texture2D(u_tex, uv + vec2(r.x, -r.y)).rgb;
    s += texture2D(u_tex, uv + vec2(-r.x, 0.0)).rgb * 2.0;
    s += texture2D(u_tex, uv).rgb * 4.0;
    s += texture2D(u_tex, uv + vec2(r.x, 0.0)).rgb * 2.0;
    s += texture2D(u_tex, uv + vec2(-r.x, r.y)).rgb;
    s += texture2D(u_tex, uv + vec2(0.0, r.y)).rgb * 2.0;
    s += texture2D(u_tex, uv + vec2(r.x, r.y)).rgb;
    return s / 16.0;
}

vec3 rgb2hsv(vec3 c) {
    vec4 K = vec4(0.0, -1.0 / 3.0, 2.0 / 3.0, -1.0);
    vec4 p = mix(vec4(c.bg, K.wz), vec4(c.gb, K.xy), step(c.b, c.g));
    vec4 q = mix(vec4(p.xyw, c.r), vec4(c.r, p.yzx), step(p.x, c.r));
    float d = q.x - min(q.w, q.y);
    float e = 1.0e-10;
    return vec3(abs(q.z + (q.w - q.y) / (6.0 * d + e)), d / (q.x + e), q.x);
}

vec3 hsv2rgb(vec3 c) {
    vec4 K = vec4(1.0, 2.0 / 3.0, 1.0 / 3.0, 3.0);
    vec3 p = abs(fract(c.xxx + K.xyz) * 6.0 - K.www);
    return c.z * mix(K.xxx, clamp(p - K.xxx, 0.0, 1.0), c.y);
}

void main() {
    vec3 base = texture2D(u_tex, v_uv).rgb;
    vec3 proc = base;

    if (u_filter == 1) {                       // 黑白
        proc = vec3(luma(base));
    } else if (u_filter == 2) {                // 暖色调
        proc = clamp(base * vec3(1.12, 1.0, 0.90), 0.0, 1.0);
    } else if (u_filter == 3) {                // 冷色调
        proc = clamp(base * vec3(0.92, 1.0, 1.10), 0.0, 1.0);
    } else if (u_filter == 4) {                // 清新
        proc = clamp((base - u_pivot) * 1.15 + u_pivot + 8.0 / 255.0, 0.0, 1.0);
    } else if (u_filter == 5) {                // 复古/电影感
        vec3 c = clamp((base - u_pivot) * 1.12 + u_pivot, 0.0, 1.0);
        float g = luma(c);
        proc = clamp(vec3(g) + (c - vec3(g)) * 0.85, 0.0, 1.0);
    } else if (u_filter == 6) {                // 梦幻/柔和
        proc = gauss3(v_uv, u_texel * (1.0 + 2.0 * u_intensity));
    } else if (u_filter == 7) {                // 锐利
        vec3 s = texture2D(u_tex, v_uv + vec2(-u_texel.x, -u_texel.y)).rgb * -1.0;
        s += texture2D(u_tex, v_uv + vec2(0.0, -u_texel.y)).rgb * -1.0;
        s += texture2D(u_tex, v_uv + vec2(u_texel.x, -u_texel.y)).rgb * -1.0;
        s += texture2D(u_tex, v_uv + vec2(-u_texel.x, 0.0)).rgb * -1.0;
        s += texture2D(u_tex, v_uv).rgb * 9.0;
        s += texture2D(u_tex, v_uv + vec2(u_texel.x, 0.0)).rgb * -1.0;
        s += texture2D(u_tex, v_uv + vec2(-u_texel.x, u_texel.y)).rgb * -1.0;
        s += texture2D(u_tex, v_uv + vec2(0.0, u_texel.y)).rgb * -1.0;
        s += texture2D(u_tex, v_uv + vec2(u_texel.x, u_texel.y)).rgb * -1.0;
        proc = clamp(s, 0.0, 1.0);
    } else if (u_filter == 8) {                // 自然等：饱和增强（强度内嵌，不再 mix）
        float g = luma(base);
        proc = clamp(vec3(g) + (base - vec3(g)) * (1.0 + 0.25 * u_intensity), 0.0, 1.0);
    }

    vec3 col;
    if (u_filter == 8) {
        col = proc;
    } else {
        col = mix(base, proc, clamp(u_intensity, 0.0, 1.0));
    }
    if (u_filter == 5 && u_intensity > 0.2) {  // 复古自带暗角
        float d5 = length((v_uv - 0.5) * 2.0);
        col *= clamp(1.0 - d5 * (0.35 * u_intensity), 0.35, 1.0);
    }

    col += u_brightness;
    if (abs(u_contrast - 1.0) > 0.001) {
        col = (col - u_pivot) * u_contrast + u_pivot;
    }
    if (abs(u_saturation - 1.0) > 0.001) {
        float g2 = luma(clamp(col, 0.0, 1.0));
        col = vec3(g2) + (col - vec3(g2)) * u_saturation;
    }
    col *= u_exposure;
    if (abs(u_gamma - 1.0) > 0.001) {
        col = pow(clamp(col, 0.0, 1.0), vec3(u_gamma));
    }
    if (abs(u_hue) > 0.0001) {
        vec3 hsv = rgb2hsv(clamp(col, 0.0, 1.0));
        hsv.x = fract(hsv.x + u_hue + 1.0);
        col = hsv2rgb(hsv);
    }
    if (abs(u_sharpen) > 0.001) {
        float norm = 1.0 + abs(u_sharpen) * 0.1;
        vec3 s = texture2D(u_tex, v_uv + vec2(-u_texel.x, -u_texel.y)).rgb * -1.0;
        s += texture2D(u_tex, v_uv + vec2(0.0, -u_texel.y)).rgb * -1.0;
        s += texture2D(u_tex, v_uv + vec2(u_texel.x, -u_texel.y)).rgb * -1.0;
        s += texture2D(u_tex, v_uv + vec2(-u_texel.x, 0.0)).rgb * -1.0;
        s += texture2D(u_tex, v_uv).rgb * (9.0 + u_sharpen);
        s += texture2D(u_tex, v_uv + vec2(u_texel.x, 0.0)).rgb * -1.0;
        s += texture2D(u_tex, v_uv + vec2(-u_texel.x, u_texel.y)).rgb * -1.0;
        s += texture2D(u_tex, v_uv + vec2(0.0, u_texel.y)).rgb * -1.0;
        s += texture2D(u_tex, v_uv + vec2(u_texel.x, u_texel.y)).rgb * -1.0;
        col = clamp(s / norm, 0.0, 1.0);
    }
    if (u_blur > 0.001) {
        col = gauss3(v_uv, u_texel * max(1.0, u_blur));
    }
    if (u_vignette > 0.001) {
        float dv = length((v_uv - 0.5) * 2.0);
        col *= clamp(1.0 - dv * u_vignette, 0.2, 1.0);
    }

    col = clamp(col, 0.0, 1.0) * clamp(u_opacity, 0.0, 1.0);
    if (u_lut_intensity > 0.001 && u_lut_size > 1.5) {
        vec3 mapped = applyLut2D(col);
        col = mix(col, mapped, clamp(u_lut_intensity, 0.0, 1.0));
    }
    gl_FragColor = vec4(col, 1.0);
}
"""


class GLFilterWidget(QOpenGLWidget):
    """GPU 滤镜预览画布。gl_ok=False 表示初始化失败（调用方回退 CPU 路径）。"""

    supports_lut = True  # 2D 图集 LUT；失败时调用方仍可走 CPU

    def __init__(self, parent=None):
        super().__init__(parent)
        self.gl_ok = False
        self._funcs = None
        self._prog: Optional[QOpenGLShaderProgram] = None
        self._vao: Optional[QOpenGLVertexArrayObject] = None
        self._vbo: Optional[QOpenGLBuffer] = None
        self._tex: Optional[QOpenGLTexture] = None
        self._lut_tex: Optional[QOpenGLTexture] = None
        self._lut_key = None
        self._tex_w = 0
        self._tex_h = 0
        self._img: Optional[QImage] = None
        self._frame_dirty = False
        self._uniforms: Dict[str, float] = self._default_uniforms()
        self._pending_lut = None  # (name, intensity, lut3d|None)
        self.setMinimumSize(320, 180)

    @staticmethod
    def _default_uniforms() -> Dict[str, float]:
        return {
            "u_filter": 0, "u_intensity": 0.7, "u_pivot": 0.5,
            "u_brightness": 0.0, "u_contrast": 1.0, "u_saturation": 1.0,
            "u_exposure": 1.0, "u_gamma": 1.0, "u_hue": 0.0,
            "u_sharpen": 0.0, "u_blur": 0.0, "u_vignette": 0.0,
            "u_opacity": 1.0, "u_scale": 1.0,
            "u_lut_size": 0.0, "u_lut_intensity": 0.0,
        }

    # ---------- GL 生命周期 ----------

    def initializeGL(self):
        try:
            # PyQt6 已移除 QOpenGLContext.functions()，改用 VersionFunctionsFactory
            ctx = self.context()
            funcs = None
            for major, minor in ((2, 1), (2, 0)):
                prof = QOpenGLVersionProfile()
                prof.setVersion(major, minor)
                funcs = QOpenGLVersionFunctionsFactory.get(prof, ctx)
                if funcs is not None:
                    break
            if funcs is None:
                raise RuntimeError("无法获取 QOpenGLFunctions_2_x")
            if hasattr(funcs, "initializeOpenGLFunctions"):
                if not funcs.initializeOpenGLFunctions():
                    raise RuntimeError("initializeOpenGLFunctions 失败")
            self._funcs = funcs
            prog = QOpenGLShaderProgram()
            prog.addShaderFromSourceCode(QOpenGLShader.ShaderTypeBit.Vertex, _VERT_SRC)
            prog.addShaderFromSourceCode(QOpenGLShader.ShaderTypeBit.Fragment, _FRAG_SRC)
            prog.bindAttributeLocation("a_pos", 0)
            prog.bindAttributeLocation("a_uv", 1)
            if not prog.link():
                logger.warning(f"GL 滤镜 shader 链接失败: {prog.log()}")
                self.gl_ok = False
                return
            self._prog = prog

            import array
            verts = array.array("f", [
                -1.0, -1.0, 0.0, 1.0,
                1.0, -1.0, 1.0, 1.0,
                -1.0, 1.0, 0.0, 0.0,
                1.0, 1.0, 1.0, 0.0,
            ]).tobytes()
            self._vao = QOpenGLVertexArrayObject()
            self._vao.create()
            self._vao.bind()
            self._vbo = QOpenGLBuffer(QOpenGLBuffer.Type.VertexBuffer)
            self._vbo.create()
            self._vbo.bind()
            self._vbo.allocate(verts, len(verts))
            self._prog.bind()
            self._prog.enableAttributeArray(0)
            self._prog.enableAttributeArray(1)
            self._prog.setAttributeBuffer(0, GL_FLOAT, 0, 2, 16)
            self._prog.setAttributeBuffer(1, GL_FLOAT, 8, 2, 16)
            self._prog.release()
            self._vbo.release()
            self._vao.release()
            self.gl_ok = True
            logger.info("GL 滤镜预览初始化成功")
        except Exception as e:
            logger.warning(f"GL 滤镜预览初始化失败，回退 CPU: {e}")
            self.gl_ok = False
            self._funcs = None

    # ---------- 公共接口 ----------

    def show_frame(self, qimage: QImage, effects: Optional[Dict[str, Any]] = None):
        """显示一帧并应用效果（效果在 GPU 完成）。"""
        self.set_effects(effects or {})
        self.set_frame(qimage)

    def set_frame(self, qimage: Optional[QImage]):
        if qimage is None or qimage.isNull():
            return
        self._img = qimage
        self._frame_dirty = True
        self.update()

    def set_effects(self, effects: Dict[str, Any]):
        self._uniforms = self._map_effects(effects)
        self._lut_dirty = True
        self.update()

    # ---------- 效果参数映射（口径对齐 PreviewManager） ----------

    def _map_effects(self, effects: Dict[str, Any]) -> Dict[str, float]:
        e: Dict[str, Any] = {}
        for k, v in (effects or {}).items():
            if k == "color_params" and isinstance(v, dict):
                e.update(v)
            else:
                e[k] = v

        u = self._default_uniforms()

        def _f(key, default):
            try:
                return float(e.get(key, default) or default)
            except Exception:
                return default

        fname = str(e.get("filter") or e.get("filter_name") or "")
        u["u_filter"] = FILTER_IDS.get(fname, 8 if fname else 0)
        u["u_intensity"] = max(0.0, min(1.0, _f("filter_intensity", 0.7)))

        b = _f("brightness", 0.0)
        if b:
            b = b / 100.0 * 80.0 if abs(b) > 1.5 else b * 80.0
        u["u_brightness"] = b / 255.0
        u["u_contrast"] = _f("contrast", 1.0)
        u["u_saturation"] = _f("saturation", 1.0)
        ex = _f("exposure", 0.0)
        u["u_exposure"] = (2.0 ** ex) if ex else 1.0
        g = _f("gamma", 1.0)
        u["u_gamma"] = (1.0 / g) if g and abs(g - 1.0) > 1e-3 else 1.0
        hue = _f("hue", 0.0)
        if hue:
            if abs(hue) > 180:
                hue /= 2.0
            u["u_hue"] = hue / 360.0
        u["u_sharpen"] = _f("sharpen", 0.0)
        u["u_blur"] = _f("blur", 0.0)
        u["u_vignette"] = _f("vignette", 0.0)
        u["u_opacity"] = max(0.0, min(1.0, _f("opacity", 1.0)))
        sc = _f("scale", 1.0)
        u["u_scale"] = sc if sc > 0 else 1.0

        # LUT：从 color_params / 顶层 lut 字段取名与强度
        # scrub / 滑杆快路径：跳过 GPU LUT（CPU 侧已有 lut_fast 半分辨率）
        cp = e.get("color_params") if isinstance(e.get("color_params"), dict) else {}
        lut_fast = bool(
            e.get("lut_fast") or e.get("_preview_fast") or cp.get("lut_fast")
        )
        lut_name = e.get("lut") or cp.get("lut") or ""
        lut_i = _f("lut_intensity", 0.0)
        if lut_i == 0.0 and cp.get("lut_intensity") is not None:
            try:
                lut_i = float(cp.get("lut_intensity") or 0)
            except Exception:
                lut_i = 0.0
        if isinstance(lut_i, float) and lut_i > 1.5:
            lut_i = lut_i / 100.0
        if lut_fast:
            self._pending_lut = ("", 0.0)
            u["u_lut_intensity"] = 0.0
            u["u_lut_size"] = 0.0
        else:
            self._pending_lut = (str(lut_name) if lut_name and lut_name != "无" else "", lut_i)
            u["u_lut_intensity"] = max(0.0, min(1.0, lut_i)) if self._pending_lut[0] else 0.0
            # size 在上传后写入
            u["u_lut_size"] = float(getattr(self, "_lut_size", 0) or 0)
        return u

    def _upload_lut_texture(self):
        """把 LUT3D 展成 2D 图集并上传（宽=S*S，高=S）。"""
        pending = getattr(self, "_pending_lut", None)
        if not pending or not pending[0] or pending[1] <= 0.001:
            self._uniforms["u_lut_size"] = 0.0
            self._uniforms["u_lut_intensity"] = 0.0
            return
        name, intensity = pending
        key = (name, round(float(intensity), 3))
        if key == getattr(self, "_lut_key", None) and self._lut_tex is not None:
            self._uniforms["u_lut_intensity"] = float(intensity)
            self._uniforms["u_lut_size"] = float(getattr(self, "_lut_size", 0) or 0)
            return
        try:
            from app.core.lut_loader import lut_loader
            lut = lut_loader.get_preset(name)
        except Exception:
            try:
                from core.lut_loader import lut_loader
                lut = lut_loader.get_preset(name)
            except Exception:
                lut = None
        if lut is None or getattr(lut, "data", None) is None:
            self._uniforms["u_lut_size"] = 0.0
            return
        try:
            import numpy as np
            from app.modules.lego.clip_transform import lut_to_2d_atlas
            s = int(lut.size)
            atlas = lut_to_2d_atlas(lut.data, s)  # float32 HxW x3, H=s W=s*s
            # → RGBA8888 QImage
            rgba = np.zeros((s, s * s, 4), dtype=np.uint8)
            rgb8 = np.clip(atlas * 255.0, 0, 255).astype(np.uint8)
            rgba[..., :3] = rgb8
            rgba[..., 3] = 255
            h, w = rgba.shape[:2]
            qimg = QImage(rgba.data, w, h, w * 4, QImage.Format.Format_RGBA8888).copy()
            if self._lut_tex is not None:
                self._lut_tex.destroy()
            self._lut_tex = QOpenGLTexture(QOpenGLTexture.Target.Target2D)
            self._lut_tex.create()
            self._lut_tex.setFormat(QOpenGLTexture.TextureFormat.RGBA8_UNorm)
            self._lut_tex.setSize(w, h)
            self._lut_tex.allocateStorage()
            self._lut_tex.setMinMagFilters(
                QOpenGLTexture.Filter.Linear, QOpenGLTexture.Filter.Linear)
            self._lut_tex.setWrapMode(QOpenGLTexture.WrapMode.ClampToEdge)
            ptr = qimg.bits()
            ptr.setsize(qimg.sizeInBytes())
            self._lut_tex.setData(
                QOpenGLTexture.PixelFormat.RGBA,
                QOpenGLTexture.PixelType.UInt8,
                ptr.asstring(),
            )
            self._lut_size = float(s)
            self._lut_key = key
            self._uniforms["u_lut_size"] = float(s)
            self._uniforms["u_lut_intensity"] = float(intensity)
            self.supports_lut = True
        except Exception as e:
            logger.warning("GPU LUT 上传失败，回退 CPU: %s", e)
            self.supports_lut = False
            self._uniforms["u_lut_size"] = 0.0
            self._uniforms["u_lut_intensity"] = 0.0

    # ---------- 绘制 ----------

    def _upload_texture(self):
        img = self._img
        if img is None:
            return
        if img.format() != QImage.Format.Format_RGBA8888:
            img = img.convertToFormat(QImage.Format.Format_RGBA8888)
        w, h = img.width(), img.height()
        if w <= 0 or h <= 0:
            return
        if self._tex is None:
            self._tex = QOpenGLTexture(QOpenGLTexture.Target.Target2D)
            self._tex.create()
        if (w, h) != (self._tex_w, self._tex_h):
            self._tex.setFormat(QOpenGLTexture.TextureFormat.RGBA8_UNorm)
            self._tex.setSize(w, h)
            self._tex.allocateStorage()
            self._tex.setMinMagFilters(
                QOpenGLTexture.Filter.Linear, QOpenGLTexture.Filter.Linear)
            self._tex.setWrapMode(QOpenGLTexture.WrapMode.ClampToEdge)
            self._tex_w, self._tex_h = w, h
        ptr = img.bits()
        ptr.setsize(img.sizeInBytes())
        self._tex.setData(
            QOpenGLTexture.PixelFormat.RGBA,
            QOpenGLTexture.PixelType.UInt8,
            ptr.asstring(),
        )

    def _update_pivot(self):
        """32x32 缩略图求亮度均值（与 numpy 版 mean 口径一致，约 0.1ms）。"""
        try:
            small = self._img.scaled(
                32, 32,
                Qt.AspectRatioMode.IgnoreAspectRatio,
                Qt.TransformationMode.FastTransformation,
            )
            if small.format() != QImage.Format.Format_RGBA8888:
                small = small.convertToFormat(QImage.Format.Format_RGBA8888)
            ptr = small.bits()
            ptr.setsize(small.sizeInBytes())
            data = ptr.asstring()
            total = 0
            n = small.width() * small.height()
            for i in range(0, n * 4, 4):
                total += data[i] + data[i + 1] + data[i + 2]
            self._uniforms["u_pivot"] = total / (3.0 * n * 255.0) if n else 0.5
        except Exception:
            self._uniforms["u_pivot"] = 0.5

    def paintGL(self):
        if not self.gl_ok or self._prog is None or self._funcs is None:
            return
        f = self._funcs
        dpr = self.devicePixelRatioF()
        w = max(1, int(self.width() * dpr))
        h = max(1, int(self.height() * dpr))
        f.glViewport(0, 0, w, h)
        f.glClearColor(0.0, 0.0, 0.0, 1.0)
        f.glClear(GL_COLOR_BUFFER_BIT)
        if self._img is None:
            return
        if self._frame_dirty:
            self._update_pivot()
            self._upload_texture()
            self._frame_dirty = False
            self._lut_dirty = True
        if getattr(self, "_lut_dirty", False):
            self._upload_lut_texture()
            self._lut_dirty = False
        if self._tex is None or self._tex_w == 0:
            return

        # 信箱式保持宽高比（GPU 免费缩放，替代 CPU SmoothTransformation）
        fa = self._tex_w / self._tex_h
        wa = w / h
        if wa > fa:
            vh, vw = h, int(h * fa)
            vx, vy = (w - vw) // 2, 0
        else:
            vw, vh = w, int(w / fa)
            vx, vy = 0, (h - vh) // 2
        f.glViewport(vx, vy, vw, vh)

        self._prog.bind()
        self._tex.bind(0)
        self._prog.setUniformValue("u_tex", 0)
        if self._lut_tex is not None and float(self._uniforms.get("u_lut_size", 0) or 0) > 1.5:
            self._lut_tex.bind(1)
            self._prog.setUniformValue("u_lut", 1)
        self._prog.setUniformValue("u_texel", 1.0 / self._tex_w, 1.0 / self._tex_h)
        self._prog.setUniformValue("u_filter", int(self._uniforms["u_filter"]))
        for name in ("u_intensity", "u_pivot", "u_brightness", "u_contrast",
                     "u_saturation", "u_exposure", "u_gamma", "u_hue",
                     "u_sharpen", "u_blur", "u_vignette", "u_opacity", "u_scale",
                     "u_lut_size", "u_lut_intensity"):
            self._prog.setUniformValue(name, float(self._uniforms.get(name, 0.0)))
        self._vao.bind()
        f.glDrawArrays(GL_TRIANGLE_STRIP, 0, 4)
        self._vao.release()
        if self._lut_tex is not None:
            self._lut_tex.release()
        self._tex.release()
        self._prog.release()
