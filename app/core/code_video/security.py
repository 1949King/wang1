# -*- coding: utf-8 -*-
"""code_video 渲染安检层（V4.45 · 2026-10-19）

职责（只做「能不能安全渲染」的判定，不渲染）：
1. **HTML 静态安检**：LLM 生成的镜头 HTML 是唯一不可信输入 ⇒ 必须自包含、零外联；
2. **路径 jail**：`html://` 只能落在 html_root 内，`asset://` 只能落在 inbox 内（realpath 判定，防 .. / 盘符 / 软链）；
3. **资源限额**：HTML 单文件/总数/总字节、成片帧数上限（与 spec.limits 的铁律互补，渲染边界再守一道）。

设计纪律：
* 纯标准库，不 import PyQt6 / playwright / ffmpeg（可被 _verify 守卫独立导入、可单测）；
* **不静默修正**：所有不合规都进 errors 列表，由调用方如实报告；绝不「先跑着」；
* 规则表 `FORBIDDEN_RULES` 是单一事实来源，守卫脚本据此断言「规则在册」；
* 运行时还有一道 `page.route("**/*")` 兜底（render_worker），但静态闸不能省 ——
  兜底只能拦网络，拦不住「文件里写了外联意图」这件事本身。
"""
from __future__ import annotations

import os
import re
from typing import Any, Dict, List, Optional, Tuple

try:
    from app.core.code_video.spec import ALLOWED_FPS, HTML_NAME_RE, TEXT_KINDS
except ImportError:  # 兼容 `core.*` 旧导入路径
    from core.code_video.spec import ALLOWED_FPS, HTML_NAME_RE, TEXT_KINDS  # type: ignore

# ============================================================
# 限额（与 spec.limits 的 60s/12clip/1080×1920/fps 铁律互补）
# ============================================================

# HTML 根目录（相对项目根）；可用参数覆盖，便于测试与用户自定义
HTML_ROOT_REL = os.path.join("data", "code_video", "html")

MAX_HTML_BYTES = 512 * 1024          # 单文件 512KB
MAX_HTML_FILES = 12                  # 与 max_clips 同量级
MAX_TOTAL_HTML_BYTES = 6 * 1024 * 1024  # 全部 HTML 合计 6MB
MAX_FRAMES = 1800                    # 60s × 30fps

# ============================================================
# 禁用规则表（单一事实来源；_verify/check_code_video_render.py 断言在册）
# (rule_id, 说明, 正则)
# ============================================================

FORBIDDEN_RULES: Tuple[Tuple[str, str, "re.Pattern[str]"], ...] = (
    ("S1-external-http", "禁止外联 http(s)（xmlns 标识符除外）",
     re.compile(r"https?://(?!www\.w3\.org/)", re.I)),
    ("S1-script-src", "禁止 <script src>（必须内联）", re.compile(r"<script\b[^>]*\bsrc\s*=", re.I)),
    ("S1-link-href", "禁止 <link href>（样式必须内联）", re.compile(r"<link\b[^>]*\bhref\s*=", re.I)),
    ("S1-css-import", "禁止 @import", re.compile(r"@import\b", re.I)),
    ("S1-protocol-relative", "禁止协议相对 URL（src/href/url 以 // 开头）",
     re.compile(r"""(?:src|href|url)\s*[=:(]\s*["']?//""", re.I)),
    ("S1-fetch", "禁止 fetch()", re.compile(r"\bfetch\s*\(", re.I)),
    ("S1-xhr", "禁止 XMLHttpRequest", re.compile(r"\bXMLHttpRequest\b", re.I)),
    ("S1-websocket", "禁止 WebSocket", re.compile(r"\bWebSocket\b", re.I)),
    ("S1-eventsource", "禁止 EventSource", re.compile(r"\bEventSource\b", re.I)),
    ("S1-beacon", "禁止 navigator.sendBeacon", re.compile(r"\bsendBeacon\b", re.I)),
    ("S1-dynamic-import", "禁止动态 import()", re.compile(r"\bimport\s*\(", re.I)),
    ("S1-eval", "禁止 eval()", re.compile(r"\beval\s*\(", re.I)),
    ("S1-new-function", "禁止 new Function", re.compile(r"\bnew\s+Function\b", re.I)),
    ("S1-window-open", "禁止 window.open", re.compile(r"\bwindow\.open\b", re.I)),
    ("S1-navigation", "禁止页面跳转（location.href/assign/replace）",
     re.compile(r"\b(?:window|document)\s*\.\s*location\s*(?:=|\.\s*(?:href|assign|replace))"
                r"|\blocation\s*\.\s*(?:href\s*=|assign\s*\(|replace\s*\()", re.I)),
    ("S1-parent-escape", "禁止访问 parent/top 的 document/location/frames",
     re.compile(r"\b(?:parent|top)\s*\.\s*(?:document|location|frames)\b", re.I)),
    ("S1-base-tag", "禁止 <base>（会改变相对路径基准）", re.compile(r"<base\b", re.I)),
    ("S1-meta-refresh", "禁止 <meta http-equiv=refresh>",
     re.compile(r"<meta\b[^>]*http-equiv\s*=\s*[\"']?refresh", re.I)),
    ("S1-storage", "禁止 localStorage/sessionStorage/indexedDB（跨帧状态会破坏确定性）",
     re.compile(r"\b(?:localStorage|sessionStorage|indexedDB)\b", re.I)),
)


# ============================================================
# 路径工具
# ============================================================

def project_root() -> str:
    """项目根（app/core/code_video/security.py → 上四级）。"""
    return os.path.dirname(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    )


def _norm(path: str) -> str:
    return os.path.normcase(os.path.realpath(os.path.abspath(path)))


def is_within(path: str, root: str) -> bool:
    """realpath 后判断 path 是否在 root 内（含 root 本身）。"""
    p, r = _norm(path), _norm(root)
    try:
        return os.path.commonpath([p, r]) == r
    except ValueError:  # 不同盘符
        return False


# ============================================================
# HTML 静态安检
# ============================================================

def check_html(name: str, text: str) -> List[str]:
    """检查一个 html:// 文件是否可进入渲染。

    返回错误列表（空 = 通过）。只查「文件自身」，不做路径解析（见 resolve_html）。
    """
    errors: List[str] = []
    if not isinstance(name, str) or not HTML_NAME_RE.match(name):
        errors.append(f"html 文件名不合规（只允许 [a-z0-9_-]{{1,40}}.html）：{name!r}")
    if not isinstance(text, str) or not text.strip():
        errors.append(f"{name} 内容为空")
        return errors
    size = len(text.encode("utf-8", errors="replace"))
    if size > MAX_HTML_BYTES:
        errors.append(f"{name} 体积 {size}B 超单文件上限 {MAX_HTML_BYTES}B")
    for rule_id, reason, pattern in FORBIDDEN_RULES:
        m = pattern.search(text)
        if m:
            errors.append(f"{name} 命中 {rule_id}：{reason}（{m.group(0)[:40]!r}）")
    return errors


# ============================================================
# 资源解析（compiled spec → 本地路径 / HTML 文本）
# ============================================================

def collect_html_sources(compiled: Dict[str, Any]) -> List[str]:
    """按出现顺序收集去重后的 html:// source。"""
    seen: List[str] = []
    for item in compiled.get("tracks") or []:
        clip = (item or {}).get("clip") or {}
        src = clip.get("source") or ""
        if isinstance(src, str) and src.startswith("html://") and src not in seen:
            seen.append(src)
    return seen


def resolve_html_dir(root: Optional[str] = None) -> Tuple[str, List[str]]:
    """解析 HTML 根目录；不存在即报错（不自动建目录 —— 建了也渲染不出内容）。"""
    path = root or os.path.join(project_root(), HTML_ROOT_REL)
    real = os.path.realpath(os.path.abspath(path))
    errors: List[str] = []
    if not os.path.isdir(real):
        errors.append(f"HTML 根目录不存在：{real}（预期放 html:// 引用的 .html 文件）")
    return real, errors


def resolve_html(
    compiled: Dict[str, Any], root: Optional[str] = None
) -> Tuple[Dict[str, str], List[str]]:
    """把 compiled 里引用的 html:// 全部读出来（source → 文本）。

    返回 (contents, errors)；errors 非空时调用方不得渲染。
    """
    sources = collect_html_sources(compiled)
    contents: Dict[str, str] = {}
    if not sources:
        return contents, []  # 纯素材片子不需要 HTML 根目录
    html_dir, errors = resolve_html_dir(root)
    if len(sources) > MAX_HTML_FILES:
        errors.append(f"html 文件数 {len(sources)} 超上限 {MAX_HTML_FILES}")
    total = 0
    for src in sources:
        name = src[len("html://"):]
        if not HTML_NAME_RE.match(name):
            errors.append(f"html source 文件名不合规：{src!r}")
            continue
        path = os.path.join(html_dir, name)
        if not is_within(path, html_dir):
            errors.append(f"{src} 路径越出 HTML 根目录（{path}）")
            continue
        if not os.path.isfile(path):
            errors.append(f"{src} 文件不存在：{path}")
            continue
        try:
            with open(path, "r", encoding="utf-8", errors="strict") as fh:
                text = fh.read()
        except (OSError, UnicodeDecodeError) as exc:
            errors.append(f"{src} 读取失败：{exc}")
            continue
        total += len(text.encode("utf-8", errors="replace"))
        errors.extend(check_html(name, text))
        contents[src] = text
    if total > MAX_TOTAL_HTML_BYTES:
        errors.append(f"html 总字节 {total}B 超上限 {MAX_TOTAL_HTML_BYTES}B")
    return contents, errors


def resolve_assets(
    compiled: Dict[str, Any], inbox_dir: str
) -> Tuple[Dict[str, str], List[str]]:
    """把 compiled.assets 的 asset:// 路径解析为 inbox 内绝对路径。

    基准 = `canvas_inbox_dir()` 根（`/inbox_file/<name>` 直接服务该目录），
    因此 `asset://shot_1.mp4` → `<inbox>/shot_1.mp4`。
    """
    errors: List[str] = []
    resolved: Dict[str, str] = {}
    root = os.path.realpath(os.path.abspath(inbox_dir))
    if not os.path.isdir(root):
        return {}, [f"inbox 目录不存在：{root}"]
    for key in (compiled.get("assets") or {}):
        if not isinstance(key, str) or not key:
            errors.append("assets 含非法键（必须是非空字符串）")
            continue
        path = os.path.join(root, key)
        if not is_within(path, root):
            errors.append(f"asset://{key} 路径越出 inbox（{path}）")
            continue
        if not os.path.isfile(path):
            errors.append(f"asset://{key} 文件不存在：{path}")
            continue
        resolved[key] = os.path.realpath(path)
    return resolved, errors


# ============================================================
# 渲染边界限额（补充 spec.compile 的硬钳）
# ============================================================

def check_limits(compiled: Dict[str, Any]) -> List[str]:
    """渲染前的最后一道限额检查（compiled 来自 compile_spec）。"""
    errors: List[str] = []
    canvas = compiled.get("canvas") or {}
    try:
        fps = int(canvas.get("fps"))
        duration = float(canvas.get("duration"))
        width = int(canvas.get("width"))
        height = int(canvas.get("height"))
    except (TypeError, ValueError):
        return ["compiled.canvas 缺少数值字段（width/height/fps/duration）"]
    if fps not in tuple(int(f) for f in ALLOWED_FPS):
        errors.append(f"fps={fps} 不在允许集合 {list(ALLOWED_FPS)}")
    if duration <= 0:
        errors.append("duration 必须 > 0")
    else:
        frames = int(round(duration * max(fps, 1)))
        if frames > MAX_FRAMES:
            errors.append(f"成片帧数 {frames} 超上限 {MAX_FRAMES}（{duration}s×{fps}fps）")
    if width <= 0 or height <= 0:
        errors.append(f"画布分辨率非法：{width}x{height}")
    if width > 1080 or height > 1920:
        errors.append(f"画布 {width}x{height} 超上限 1080x1920")
    clip_count = sum(
        1 for item in (compiled.get("tracks") or []) if (item or {}).get("clip")
    )
    if clip_count == 0:
        errors.append("compiled 没有任何 clip")
    if clip_count > 12:
        errors.append(f"clip 总数 {clip_count} 超上限 12")
    if len(collect_html_sources(compiled)) > MAX_HTML_FILES:
        errors.append(f"html 文件数超上限 {MAX_HTML_FILES}")
    # 文字层必须 html://（与 compile 同一铁律，渲染边界再确认一次）
    for item in compiled.get("tracks") or []:
        clip = (item or {}).get("clip") or {}
        if clip.get("kind") in TEXT_KINDS and not str(clip.get("source", "")).startswith("html://"):
            errors.append(
                f"文字层铁律在渲染边界被破坏：clip {clip.get('id')} kind={clip.get('kind')}"
            )
    return errors
