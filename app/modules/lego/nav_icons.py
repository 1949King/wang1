# -*- coding: utf-8 -*-
"""导航栏模块图标 —— 单色矢量（SVG），颜色与尺寸由调用方决定。

为什么要从 emoji 换成矢量
------------------------
原先导航按钮用 emoji 当图标（`NavigationButton.setText(f"  {icon}  {text}")`）。
实测查出三个问题：

1. **色彩不统一**：11 个模块里 5 个 emoji 渲染为黑白（🎬 / ⚙️ / 🔌 彩色像素占比 **0%**，
   🤖 8%、📋 21%），另 6 个是彩色（🎨 75%、📁 68%）。同一个导航栏里混排，
   观感不整齐。
2. **颜色不可控**：emoji 的颜色由系统字体决定，**主题切换与选中态都改不了它**。
   矢量图标则完全跟随主题 / 选中 / 悬停三种状态。
3. **语义错配**：场记板（🎬）表达的是「拍摄现场」不是剪辑；机器人（🤖）表达的是
   AI 助手、会和本项目里的 Agent 概念撞车；手写（✍️）表达的是人工书写、
   对一个「AI 生成文案」的模块恰好是反的。

设计准则
--------
* **动宾优先** —— 图标表达「在这里做什么」，而非「这里存着什么」
* **避让既有概念** —— 机器人让给 Agent；调色板让给调色功能
* **小尺寸可辨** —— 主体在 24×24 画布内尽量占满
* **24×24 viewBox / stroke 2 / 圆角端点** —— 与业界通行的描边图标语言一致

工程约定
--------
* 本模块**导入期零副作用**：只有常量与函数定义；QtSvg 按需探测（首次渲染时）。
* QtSvg 缺失时 **不报错**，由 `nav_icon_available()` 返回 False，
  调用方回退到 module_registry 里原有的 emoji —— 一个装饰性问题不该让导航栏起不来。
"""

from typing import Dict, Optional

# ── 图标几何：键 = module_registry 里的模块 id ──────────────────────────
# 全部为 24×24 viewBox 下的描边图形；需要实心填充的子元素写 currentColor，
# 渲染时会被替换成目标颜色。
NAV_ICON_PATHS: Dict[str, str] = {
    # 首页：房屋。保留原概念，但改为描边矢量，主体占比远高于 emoji。
    "home": (
        '<path d="M3.5 10.6 12 3.5l8.5 7.1V20a1 1 0 0 1-1 1h-4.7v-6.2H9.2V21H4.5a1 1 0 0 1-1-1z"/>'
    ),
    # 剪辑：剪刀。原 emoji 是场记板（= 拍摄现场），语义错位；剪刀是「剪辑」的通用符号。
    "editor": (
        '<circle cx="6" cy="6" r="3"/>'
        '<circle cx="6" cy="18" r="3"/>'
        '<path d="M20 4 8.12 15.88M14.47 14.48 20 20M8.12 8.12 12 12"/>'
    ),
    # 设置：齿轮。概念未变，改为描边矢量以获得一致的线宽与颜色。
    "settings": (
        '<circle cx="12" cy="12" r="3.2"/>'
        '<circle cx="12" cy="12" r="8.4"/>'
        '<path d="M12 1.6v2.6M12 19.8v2.6M1.6 12h2.6M19.8 12h2.6'
        'M4.7 4.7l1.8 1.8M17.5 17.5l1.8 1.8M19.3 4.7l-1.8 1.8M6.5 17.5l-1.8 1.8"/>'
    ),
    # 帮助：圆圈问号。原 emoji ❓ 的着色像素仅占 18%（11 个里最小），显得空而弱；
    # 加一圈外框后主体占满，小尺寸下反而更清楚。
    # 问号用业界通行的那条弧线路径（起点略偏左、半径 3、从上方绕过后向下收成钩）。
    "help": (
        '<circle cx="12" cy="12" r="9.2"/>'
        '<path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3"/>'
        '<circle cx="12" cy="16.9" r="1.05" fill="currentColor" stroke="none"/>'
    ),
    # 文案生成：文本行 + 四角星芒。原 emoji ✍️（手写）表达「人工书写」，
    # 对一个「AI 生成文案」的模块恰好是反的；星芒 = AI 生成。
    # 星芒中心对齐第二行文字（y=12），避免看起来像游离的装饰。
    "copywriting": (
        '<path d="M2.6 6.4h10.8M2.6 12h10.8M2.6 17.6h6"/>'
        '<path d="M18.3 8.4 19.4 10.9 21.9 12 19.4 13.1 18.3 15.6 17.2 13.1 14.7 12 17.2 10.9Z" '
        'fill="currentColor" stroke="none"/>'
    ),
    # 多任务：层叠。原 emoji 📋（剪贴板）表达的是「待办清单」，不是「批量队列」。
    "tasks": (
        '<path d="M12 2.6 2.6 7.5 12 12.4l9.4-4.9z"/>'
        '<path d="M2.6 12.3 12 17.2l9.4-4.9"/>'
        '<path d="M2.6 16.9 12 21.8l9.4-4.9"/>'
    ),
    # 素材库：文件夹 + 播放三角。原 emoji 📁 只表达「通用存储」，
    # 补一个播放三角后语义落到「装多媒体素材的库」。
    # 三角要够大才看得出来（首版太小，读起来只剩一个文件夹）。
    "materials": (
        '<path d="M2.8 7.4a2 2 0 0 1 2-2h3.3a2 2 0 0 1 1.5.7l1.2 1.4h7.4a2 2 0 0 1 2 2v8.3'
        'a2 2 0 0 1-2 2H4.8a2 2 0 0 1-2-2z"/>'
        '<path d="M9.7 11.1v6.2l5.6-3.1z" fill="currentColor" stroke="none"/>'
    ),
    # 模型管理：芯片。原 emoji 🤖（机器人）会被读成「AI 助手」，
    # 与本项目的 Agent（知心秘书）概念撞车；芯片 = 模型/算力单元，不歧义。
    "models": (
        '<rect x="6.6" y="6.6" width="10.8" height="10.8" rx="2"/>'
        '<rect x="10.4" y="10.4" width="3.2" height="3.2" rx=".7"/>'
        '<path d="M9.5 3.4v3.2M14.5 3.4v3.2M9.5 17.4v3.2M14.5 17.4v3.2'
        'M3.4 9.5h3.2M3.4 14.5h3.2M17.4 9.5h3.2M17.4 14.5h3.2"/>'
    ),
    # AI 画布：节点图。原 emoji 🎨（调色板）会被读成「调色/滤镜」，
    # 而该模块实际是节点式画布（生图/生视频回流剪辑）；两节点 + 连线才是它的形状。
    "characters": (
        '<rect x="8.4" y="2.6" width="7.2" height="5.2" rx="1.6"/>'
        '<rect x="2.4" y="16.2" width="7.2" height="5.2" rx="1.6"/>'
        '<rect x="14.4" y="16.2" width="7.2" height="5.2" rx="1.6"/>'
        '<path d="M12 7.8v4.4M6 16.2v-2h12v2"/>'
    ),
    # 拓展中心：插头。概念与原 emoji 🔌 一致，但原 emoji 着色像素仅 20%（倒数第二），
    # 改为描边插头后主体更大、线条统一。
    "extensions": (
        '<path d="M9.2 2.6v5.6M14.8 2.6v5.6"/>'
        '<path d="M6.2 8.2h11.6v3.3a5.8 5.8 0 0 1-5.8 5.8 5.8 5.8 0 0 1-5.8-5.8z"/>'
        '<path d="M12 17.3v4.1"/>'
    ),
    # 性能监控：仪表盘。原 emoji 📊（柱状图）表达「数据统计」，
    # 而该模块是系统资源监控；半圆 + 指针才是「仪表」。
    # 指针要接近弧顶才看得出是仪表（首版太短，读起来只剩半圆）。
    "performance": (
        '<path d="M3.4 17.2a8.6 8.6 0 0 1 17.2 0"/>'
        '<path d="M12 17.2 17 10.2"/>'
        '<circle cx="12" cy="17.2" r="1.35" fill="currentColor" stroke="none"/>'
    ),
}

_SVG_TEMPLATE = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" '
    'fill="none" stroke="{color}" stroke-width="{stroke}" '
    'stroke-linecap="round" stroke-linejoin="round">{body}</svg>'
)

# 导航按钮里的图标逻辑尺寸（按钮 min-height 44，四周留呼吸）
NAV_MODULE_ICON_SIZE = 20

# QtSvg 探测结果缓存：None = 尚未探测；False = 不可用；否则为 QSvgRenderer 类
_SVG_RENDERER = None

# 渲染结果缓存：(key, color, size) -> QIcon
# 导航按钮在悬停/选中切换时会反复请求图标，缓存后避免重复解析 SVG。
_ICON_CACHE: Dict[tuple, object] = {}


def _probe_svg():
    """惰性探测 QtSvg（与项目既有 `_ensure_*_probed` 模式一致）。"""
    global _SVG_RENDERER
    if _SVG_RENDERER is None:
        try:
            from PySide6.QtSvg import QSvgRenderer  # type: ignore
            _SVG_RENDERER = QSvgRenderer
        except Exception:
            _SVG_RENDERER = False
    return _SVG_RENDERER


def nav_icon_available(key: str) -> bool:
    """该模块是否有矢量图标，且 QtSvg 可用。不可用时调用方应回退到 emoji。"""
    return key in NAV_ICON_PATHS and bool(_probe_svg())


def nav_icon_keys() -> tuple:
    """全部已定义矢量图标的模块 id（供回归脚本核对覆盖度）。"""
    return tuple(NAV_ICON_PATHS.keys())


def build_nav_icon_svg(key: str, color: str, stroke_width: float = 2.0) -> Optional[str]:
    """生成着色后的 SVG 源码。key 未定义时返回 None。"""
    body = NAV_ICON_PATHS.get(key)
    if body is None:
        return None
    return _SVG_TEMPLATE.format(
        color=color,
        stroke=stroke_width,
        body=body.replace("currentColor", color),
    )


def make_nav_icon(key: str, color: str, size: int = 20, stroke_width: float = 2.0):
    """渲染为 QIcon；不可用时返回 None（调用方自行兜底）。

    size 为**逻辑像素**；位图按屏幕 DPR 放大后再设回 DPR，保证高分屏下边缘锐利。
    """
    renderer_cls = _probe_svg()
    if not renderer_cls:
        return None
    cache_key = (key, color, size)
    cached = _ICON_CACHE.get(cache_key)
    if cached is not None:
        return cached
    svg = build_nav_icon_svg(key, color, stroke_width)
    if svg is None:
        return None

    from PySide6.QtCore import QByteArray, Qt
    from PySide6.QtGui import QGuiApplication, QIcon, QPainter, QPixmap

    try:
        screen = QGuiApplication.primaryScreen()
        dpr = float(screen.devicePixelRatio()) if screen else 1.0
    except Exception:
        dpr = 1.0
    dpr = max(1.0, min(dpr, 4.0))

    renderer = renderer_cls(QByteArray(svg.encode("utf-8")))
    if not renderer.isValid():
        return None

    pm = QPixmap(int(round(size * dpr)), int(round(size * dpr)))
    pm.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pm)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    renderer.render(painter)
    painter.end()
    # ⚠️ setDevicePixelRatio 必须在**画完之后**调用。
    #
    # 踩过的坑：若先 setDevicePixelRatio(dpr) 再开 QPainter，
    # `painter.viewport()` 会返回**物理尺寸**（如 96 逻辑 / 1.5 → 报 144），
    # 而 QSvgRenderer.render(painter) 是「铺满 viewport」——
    # 于是它按 144 铺、再叠加 dpr 的 1.5 倍变换，最终画成 216 并被位图裁掉。
    # 实测症状：图标左侧被切（左右着色像素比 1.61，正常应为 1.00）。
    # 画完再设 dpr，则绘制期变换为 1:1、viewport 与坐标系一致，结果对称正确。
    pm.setDevicePixelRatio(dpr)
    icon = QIcon(pm)
    _ICON_CACHE[cache_key] = icon
    return icon


# 各模块图标的中文语义（供帮助页 / 设置页展示，避免图标含义靠猜）
NAV_ICON_MEANING: Dict[str, str] = {
    "home": "首页 · 快速入口与项目概览",
    "editor": "剪辑 · 剪刀＝裁剪与拼接",
    "settings": "设置 · 齿轮",
    "help": "帮助 · 问答",
    "copywriting": "文案生成 · 文本＋星芒＝AI 生成",
    "tasks": "多任务 · 层叠＝批量队列",
    "materials": "素材库 · 文件夹＋播放＝多媒体库",
    "models": "模型管理 · 芯片＝模型单元",
    "characters": "AI 画布 · 节点＋连线＝画布编排",
    "extensions": "拓展中心 · 插头＝插件接入",
    "performance": "性能监控 · 仪表盘＝资源读数",
}

__all__ = [
    "NAV_ICON_PATHS",
    "NAV_ICON_MEANING",
    "nav_icon_available",
    "nav_icon_keys",
    "build_nav_icon_svg",
    "make_nav_icon",
]
