# -*- coding: utf-8 -*-
"""CodeVideoSpec —— 「代码 × 扩散」混合视频渲染契约（V4.44 契约刀 · 2026-10-19）

定位
----
两条 AI 视频路线在一个 JSON 契约里汇合：

* **扩散路线**（可灵/Seedance/Veo/Vidu/Wan…）只产出「镜头像素片段」⇒ `clip.source = "asset://…"`
* **代码路线**（LLM 写 HTML/CSS/JS + Chromium 确定性渲染）负责时间轴/字幕/排版/转场/包装
  ⇒ `clip.source = "html://…"`

渲染编排层（render_host.py，V4.45）统一按时间轴取帧 ——「视频模型出画面，代码框架出成片」
在数据结构上就是一行的差别。

设计原则（对齐 timeline_dsl.py 的 DSL 风格）
------------------------------------------
1. 前后端同一份契约：画布前端（codeVideoSpec.ts）与后端（本文件）镜像同一结构
2. 可序列化：完整 to_dict/from_dict round-trip
3. 诚实校验：`validate_spec` 查结构、`compile` 查语义 + 钳制 limits；**错误列表空才放行**
4. 不猜默认值：缺字段不补造，非法值进 errors（绝不静默修正）

铁律（写进 compile 硬校验）
--------------------------
* **文字层禁止扩散路线**：`kind == "text"/"subtitle"` 的 clip.source 必须是 `html://`。
  视频内文字不可靠是扩散模型公认短板 ⇒ 字幕/标题卡必须代码渲染后期叠
* **limits 硬钳**：总时长 ≤60s、clip ≤12、fps∈{24,30}、分辨率 ≤1080×1920
  （8GB 显存 / 15.3GB 内存的诚实边界，超出 = 编译失败而非硬跑）
* **血缘 6 键不扩容**：assets 的 lineage 经 `glue.schema.normalize_generation` 清洗，
  与入轨 `stamp_clip` 同一份白名单（prompt/seed/model/channel/character_id/reference）

沙箱红线（V4.45 执行面，此处立约）
----------------------------------
* LLM 只产 HTML/CSS/JS，**永不写 Python** ⇒ JS 跑在 Chromium 沙箱内，主进程无 RCE 面
* `html://` 文件名白名单 `[a-z0-9_-]{1,40}.html`；`asset://` 只允许 inbox 内相对路径
* 沙箱缺口被发现时的行为是**显式禁用该路线并报告**，绝不是「先跑着」

设计借鉴出处（OpenFilm 逆向报告 docs/_reports/2026-10-19-OpenFilm逆向分析报告.html，MIT）
----------------------------------------------------------------------------------------
* `overrides` 字段 = OpenFilm Studio 的 overrides（人工修改，LLM 重生成永不覆盖）
* `qc.dual_shuffle` = OpenFilm look 的同 t 双乱序重绘比对质检
* frame(t) 纯函数契约由 render_worker.py 注入（V4.45），本契约经 `params` 供参
本文件为零依赖纯标准库 + glue/schema（纯标准库），可被 _verify 守卫独立导入。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

try:
    from app.core.glue.schema import normalize_generation
except ImportError:  # 兼容 `core.*` 旧导入路径
    from core.glue.schema import normalize_generation  # type: ignore

# ============================================================
# 常量（单一事实来源，_verify/check_code_video.py 镜像断言）
# ============================================================

SPEC_VERSION = "1.0"

SOURCE_PREFIXES = ("asset://", "html://")

# html:// 镜头文件名白名单（小写字母数字下划线连字符 + .html）
_HTML_NAME_RE = re.compile(r"^[a-z0-9_-]{1,40}\.html$")
# asset:// 相对路径：禁绝对路径、禁盘符、禁 ..、禁反斜杠、只允许安全字符集
_ASSET_PATH_RE = re.compile(r"^[A-Za-z0-9._\-/]{1,200}$")

FIT_MODES = ("cover", "contain", "blur-fill")

ALLOWED_FPS = (24, 30)

# limits 默认值（实例可覆盖，但 compile 时按本默认值校验外部传入的 limits 自身）
DEFAULT_MAX_DURATION = 60.0
DEFAULT_MAX_CLIPS = 12
MAX_CANVAS_W = 1080
MAX_CANVAS_H = 1920

# 文字层 kind（铁律：这些 kind 的 clip.source 必须 html://）
TEXT_KINDS = ("text", "subtitle")

# params 白名单：标量 + 标量列表；禁嵌套对象/禁函数混入
_SCALAR_TYPES = (str, int, float, bool)


# ============================================================
# 数据结构（dataclass 族，对齐 timeline_dsl.py 风格）
# ============================================================

@dataclass
class CanvasSettings:
    """画布（输出画面）设置。"""
    width: int = 1080
    height: int = 1920
    fps: int = 30
    duration: float = 24.0
    background: str = "#0b0f1a"


@dataclass
class SpecClip:
    """单个片段。range = 在成片中的时间窗；source_range = 素材截取窗。"""
    id: str
    source: str
    range: List[float] = field(default_factory=lambda: [0.0, 0.0])
    source_range: Optional[List[float]] = None
    kind: str = "video"            # video/text/subtitle/audio/transition
    fit: str = "cover"
    speed: float = 1.0
    volume: float = 0.0
    params: Dict[str, Any] = field(default_factory=dict)
    overrides: Dict[str, Any] = field(default_factory=dict)


@dataclass
class SpecTrack:
    """一条轨道（同 kind 的 clip 序列）。"""
    id: str
    kind: str = "video"            # video/subtitle/audio
    clips: List[SpecClip] = field(default_factory=list)


@dataclass
class AssetEntry:
    """素材登记（扩散产物/本地文件）。lineage 经 normalize_generation 清洗。"""
    kind: str = "video"
    duration: float = 0.0
    lineage: Dict[str, Any] = field(default_factory=dict)


@dataclass
class QcSettings:
    """质检设置。"""
    dual_shuffle: bool = True
    text_safe_area: Optional[List[int]] = None


@dataclass
class SpecLineage:
    """spec 自身血缘（入轨时 route 写 model、spec_id 写 reference）。"""
    route: str = "hybrid"
    spec_id: str = ""
    created_by: str = "pipeline.code_video_plan"


@dataclass
class SpecLimits:
    """资源上限（8GB 硬件诚实边界）。"""
    max_duration: float = DEFAULT_MAX_DURATION
    max_clips: int = DEFAULT_MAX_CLIPS
    max_width: int = MAX_CANVAS_W
    max_height: int = MAX_CANVAS_H
    allowed_fps: Tuple[int, ...] = ALLOWED_FPS


@dataclass
class CodeVideoSpec:
    """「代码 × 扩散」混合视频渲染契约。"""
    canvas: CanvasSettings = field(default_factory=CanvasSettings)
    tracks: List[SpecTrack] = field(default_factory=list)
    assets: Dict[str, AssetEntry] = field(default_factory=dict)
    qc: QcSettings = field(default_factory=QcSettings)
    lineage: SpecLineage = field(default_factory=SpecLineage)
    limits: SpecLimits = field(default_factory=SpecLimits)
    version: str = SPEC_VERSION

    # ---------- 序列化 ----------

    def to_dict(self) -> Dict[str, Any]:
        return {
            "version": self.version,
            "canvas": {
                "width": self.canvas.width,
                "height": self.canvas.height,
                "fps": self.canvas.fps,
                "duration": self.canvas.duration,
                "background": self.canvas.background,
            },
            "tracks": [
                {
                    "id": t.id,
                    "kind": t.kind,
                    "clips": [
                        {
                            "id": c.id,
                            "source": c.source,
                            "range": list(c.range),
                            "source_range": list(c.source_range) if c.source_range else None,
                            "kind": c.kind,
                            "fit": c.fit,
                            "speed": c.speed,
                            "volume": c.volume,
                            "params": dict(c.params),
                            "overrides": dict(c.overrides),
                        }
                        for c in t.clips
                    ],
                }
                for t in self.tracks
            ],
            "assets": {
                path: {"kind": a.kind, "duration": a.duration, "lineage": dict(a.lineage)}
                for path, a in self.assets.items()
            },
            "qc": {
                "dual_shuffle": self.qc.dual_shuffle,
                "text_safe_area": list(self.qc.text_safe_area) if self.qc.text_safe_area else None,
            },
            "lineage": {
                "route": self.lineage.route,
                "spec_id": self.lineage.spec_id,
                "created_by": self.lineage.created_by,
            },
            "limits": {
                "max_duration": self.limits.max_duration,
                "max_clips": self.limits.max_clips,
                "max_width": self.limits.max_width,
                "max_height": self.limits.max_height,
                "allowed_fps": list(self.limits.allowed_fps),
            },
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CodeVideoSpec":
        """从 dict 构建。**不做校验**（校验走 validate_spec/compile）——
        调用方拿到的对象必须原样反映输入，缺字段用 dataclass 默认值补齐，
        但「补齐」只是构造便利，compile 阶段仍会逐项查。"""
        canvas_d = data.get("canvas") or {}
        qc_d = data.get("qc") or {}
        lin_d = data.get("lineage") or {}
        lim_d = data.get("limits") or {}

        tracks: List[SpecTrack] = []
        for t in data.get("tracks") or []:
            clips = [
                SpecClip(
                    id=str(c.get("id") or ""),
                    source=str(c.get("source") or ""),
                    range=list(c.get("range") or [0.0, 0.0]),
                    source_range=list(c["source_range"]) if c.get("source_range") else None,
                    kind=str(c.get("kind") or "video"),
                    fit=str(c.get("fit") or "cover"),
                    speed=float(c.get("speed") if c.get("speed") is not None else 1.0),
                    volume=float(c.get("volume") if c.get("volume") is not None else 0.0),
                    params=dict(c.get("params") or {}),
                    overrides=dict(c.get("overrides") or {}),
                )
                for c in (t.get("clips") or [])
            ]
            tracks.append(SpecTrack(id=str(t.get("id") or ""), kind=str(t.get("kind") or "video"), clips=clips))

        assets: Dict[str, AssetEntry] = {}
        for path, a in (data.get("assets") or {}).items():
            assets[str(path)] = AssetEntry(
                kind=str(a.get("kind") or "video"),
                duration=float(a.get("duration") or 0.0),
                lineage=dict(a.get("lineage") or {}),
            )

        return cls(
            version=str(data.get("version") or SPEC_VERSION),
            canvas=CanvasSettings(
                width=int(canvas_d.get("width") or 1080),
                height=int(canvas_d.get("height") or 1920),
                fps=int(canvas_d.get("fps") or 30),
                duration=float(canvas_d.get("duration") or 0.0),
                background=str(canvas_d.get("background") or "#0b0f1a"),
            ),
            tracks=tracks,
            assets=assets,
            qc=QcSettings(
                dual_shuffle=bool(qc_d.get("dual_shuffle", True)),
                text_safe_area=list(qc_d["text_safe_area"]) if qc_d.get("text_safe_area") else None,
            ),
            lineage=SpecLineage(
                route=str(lin_d.get("route") or "hybrid"),
                spec_id=str(lin_d.get("spec_id") or ""),
                created_by=str(lin_d.get("created_by") or "pipeline.code_video_plan"),
            ),
            limits=SpecLimits(
                max_duration=float(lim_d.get("max_duration") or DEFAULT_MAX_DURATION),
                max_clips=int(lim_d.get("max_clips") or DEFAULT_MAX_CLIPS),
                max_width=int(lim_d.get("max_width") or MAX_CANVAS_W),
                max_height=int(lim_d.get("max_height") or MAX_CANVAS_H),
                allowed_fps=tuple(lim_d.get("allowed_fps") or ALLOWED_FPS),
            ),
        )

    # ---------- 派生量 ----------

    def total_clips(self) -> int:
        return sum(len(t.clips) for t in self.tracks)

    def iter_clips(self):
        for t in self.tracks:
            for c in t.clips:
                yield t, c


# ============================================================
# 校验：validate_spec（结构） / compile_spec（语义 + 钳制）
# ============================================================

def _num(v: Any) -> Optional[float]:
    """只接受真数值；bool 是 int 子类但在这里不算数（防 True 当 1 秒）。"""
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    return float(v)


def _sanitize_params(raw: Any) -> Tuple[Dict[str, Any], List[str]]:
    """params 白名单清洗：标量 + 标量列表；禁嵌套对象、禁函数混入。

    返回 (cleaned, dropped_keys)。丢弃是显式的 —— 调用方应把 dropped 报出来，
    不静默修正（「没传进来」和「被丢了」必须可分）。
    """
    if not isinstance(raw, dict):
        return {}, ["params 不是对象"]
    cleaned: Dict[str, Any] = {}
    dropped: List[str] = []
    for key, val in raw.items():
        if not isinstance(key, str) or not key:
            dropped.append("params 含非字符串键")
            continue
        if isinstance(val, _SCALAR_TYPES):
            cleaned[key] = val
        elif isinstance(val, list) and all(isinstance(x, _SCALAR_TYPES) for x in val):
            cleaned[key] = list(val)
        else:
            dropped.append(f"params.{key} 类型不允许（只收标量/标量列表）")
    return cleaned, dropped


def _check_source(source: str, kind: str) -> List[str]:
    """clip.source 的前缀与形态校验（目录逃逸防护第一层）。"""
    errors: List[str] = []
    if not source:
        return ["source 为空"]
    if not source.startswith(SOURCE_PREFIXES):
        errors.append(f"source 必须以 {' 或 '.join(SOURCE_PREFIXES)} 开头（收到 {source[:40]!r}）")
        return errors
    if source.startswith("html://"):
        name = source[len("html://"):]
        if not _HTML_NAME_RE.match(name):
            errors.append(f"html:// 文件名不合规（只允许 [a-z0-9_-]{{1,40}}.html）：{name[:60]!r}")
    else:  # asset://
        path = source[len("asset://"):]
        if not _ASSET_PATH_RE.match(path):
            errors.append(
                f"asset:// 路径不合规（相对路径、禁盘符/../反斜杠）：{path[:60]!r}"
            )
        elif path.startswith("/") or "\\" in path or ".." in path.split("/"):
            errors.append(f"asset:// 路径越界（绝对路径或 ..）：{path[:60]!r}")
    # 文字层铁律：字幕/标题必须代码渲染（视频内文字不可靠是扩散模型公认短板）
    if kind in TEXT_KINDS and not source.startswith("html://"):
        errors.append(
            f"文字层铁律：kind={kind} 的 clip.source 必须 html://"
            f"（字幕/标题卡禁止扩散路线，收到 {source[:40]!r}）"
        )
    return errors


def validate_spec(data: Dict[str, Any]) -> List[str]:
    """结构校验（对齐 timeline_dsl.validate_timeline 风格）。

    返回错误列表，空列表表示通过。只查「字段在不在、类型对不对」，
    语义与资源钳制在 compile_spec。
    """
    errors: List[str] = []
    if not isinstance(data, dict):
        return ["spec 不是 JSON 对象"]

    if "version" not in data:
        errors.append("缺失 version 字段")
    elif data["version"] != SPEC_VERSION:
        errors.append(f"version 不支持（只收 {SPEC_VERSION}，收到 {data['version']!r}）")

    canvas = data.get("canvas")
    if not isinstance(canvas, dict):
        errors.append("缺失 canvas 对象")
    else:
        for key in ("width", "height", "fps", "duration"):
            if key not in canvas:
                errors.append(f"canvas 缺失 {key}")
            elif _num(canvas[key]) is None:
                errors.append(f"canvas.{key} 不是数值（收到 {canvas[key]!r}）")

    tracks = data.get("tracks")
    if not isinstance(tracks, list):
        errors.append("缺失 tracks 数组")
    else:
        seen_track_ids = set()
        seen_clip_ids = set()
        for i, track in enumerate(tracks):
            if not isinstance(track, dict):
                errors.append(f"tracks[{i}] 不是对象")
                continue
            tid = track.get("id")
            if not tid:
                errors.append(f"tracks[{i}] 缺失 id")
            elif tid in seen_track_ids:
                errors.append(f"tracks id 重复：{tid}")
            else:
                seen_track_ids.add(tid)
            for j, clip in enumerate(track.get("clips") or []):
                if not isinstance(clip, dict):
                    errors.append(f"tracks[{i}].clips[{j}] 不是对象")
                    continue
                cid = clip.get("id")
                if not cid:
                    errors.append(f"tracks[{i}].clips[{j}] 缺失 id")
                elif cid in seen_clip_ids:
                    errors.append(f"clip id 重复（跨轨也必须唯一）：{cid}")
                else:
                    seen_clip_ids.add(cid)
                rng = clip.get("range")
                if not isinstance(rng, list) or len(rng) != 2 or any(_num(x) is None for x in rng):
                    errors.append(f"clips[{j}] ({cid or '?'}) range 必须是 [start, end] 两数值")

    assets = data.get("assets")
    if assets is not None and not isinstance(assets, dict):
        errors.append("assets 必须是对象（路径 → 登记项）")

    return errors


def compile_spec(spec: CodeVideoSpec) -> Tuple[Optional[Dict[str, Any]], List[str]]:
    """语义校验 + limits 钳制 + 归一化，输出渲染态编译产物。

    返回 (compiled, errors)：
    * errors 非空 ⇒ compiled 为 None，**调用方必须如实报告，不得强行渲染**
    * compiled 为 Timeline DSL 兼容子集（V4.45 render_host 消费）

    校验项：
    1. canvas 分辨率/帧率/总时长 limits 钳制
    2. clip 总数 limits 钳制
    3. clip.source 前缀与形态（_check_source，含文字层铁律）
    4. clip.range 时序：start < end、不越出 canvas.duration
    5. asset:// clip 必须在 assets 登记且时长够用
    6. params 白名单清洗（丢弃项显式进 errors —— 不静默修正）
    7. assets.lineage 经 glue normalize_generation 清洗（入轨 6 键同源）
    """
    errors: List[str] = []

    # ---- 1. canvas 钳制 ----
    c = spec.canvas
    if c.width <= 0 or c.height <= 0:
        errors.append(f"canvas 分辨率非法：{c.width}x{c.height}")
    elif c.width > spec.limits.max_width or c.height > spec.limits.max_height:
        errors.append(
            f"canvas 分辨率 {c.width}x{c.height} 超 limits "
            f"{spec.limits.max_width}x{spec.limits.max_height}（8GB 硬件诚实边界）"
        )
    if int(c.fps) not in tuple(int(f) for f in spec.limits.allowed_fps):
        errors.append(f"fps={c.fps} 不在允许集合 {list(spec.limits.allowed_fps)}")
    if c.duration <= 0:
        errors.append("canvas.duration 必须 > 0")
    elif c.duration > spec.limits.max_duration + 1e-9:
        errors.append(
            f"总时长 {c.duration}s 超 limits {spec.limits.max_duration}s"
        )

    # ---- 2. clip 总数钳制 ----
    total = spec.total_clips()
    if total == 0:
        errors.append("tracks 为空：没有任何片段可渲染")
    elif total > spec.limits.max_clips:
        errors.append(f"clip 总数 {total} 超 limits {spec.limits.max_clips}")

    # ---- 3~6. 逐 clip ----
    compiled_tracks: List[Dict[str, Any]] = []
    for track, clip in spec.iter_clips():
        errors.extend(_check_source(clip.source, clip.kind))

        rng = clip.range or [0.0, 0.0]
        start, end = float(rng[0]), float(rng[1])
        if end <= start:
            errors.append(f"clip {clip.id} range 无效（end 必须 > start）：{rng}")
        if end > c.duration + 1e-6:
            errors.append(
                f"clip {clip.id} 结束于 {end}s，越出成片总长 {c.duration}s"
            )
        if clip.fit not in FIT_MODES:
            errors.append(f"clip {clip.id} fit={clip.fit!r} 不在 {list(FIT_MODES)}")
        if not (0.0 <= clip.volume <= 1.0):
            errors.append(f"clip {clip.id} volume={clip.volume} 越界（0~1）")
        if not (0.25 <= clip.speed <= 4.0):
            errors.append(f"clip {clip.id} speed={clip.speed} 越界（0.25~4）")

        # asset:// 必须登记且素材时长够截取窗
        if clip.source.startswith("asset://"):
            path = clip.source[len("asset://"):]
            entry = spec.assets.get(path)
            if entry is None:
                errors.append(f"clip {clip.id} 引用素材未登记：asset://{path}")
            else:
                need = (end - start) / max(clip.speed, 1e-6)
                sr = clip.source_range
                if sr:
                    need = (float(sr[1]) - float(sr[0])) / max(clip.speed, 1e-6)
                if entry.duration > 0 and need > entry.duration + 1e-6:
                    errors.append(
                        f"clip {clip.id} 需要 {need:.2f}s 素材但登记时长只有 {entry.duration:.2f}s"
                    )

        # params 白名单（丢弃显式报错）
        cleaned, dropped = _sanitize_params(clip.params)
        errors.extend([f"clip {clip.id} {d}" for d in dropped])

        compiled_tracks.append({
            "track_id": track.id,
            "track_kind": track.kind,
            "clip": {
                "id": clip.id,
                "source": clip.source,
                "source_type": "asset" if clip.source.startswith("asset://") else "html",
                "range": [start, end],
                "source_range": list(clip.source_range) if clip.source_range else None,
                "kind": clip.kind,
                "fit": clip.fit,
                "speed": clip.speed,
                "volume": clip.volume,
                "params": cleaned,
                "overrides": dict(clip.overrides),
            },
        })

    # ---- 7. assets.lineage 清洗（与入轨 6 键同源）----
    compiled_assets: Dict[str, Any] = {}
    for path, entry in spec.assets.items():
        if not _ASSET_PATH_RE.match(path) or path.startswith("/") or ".." in path.split("/"):
            errors.append(f"assets 路径越界或不合规：{path[:60]!r}")
            continue
        compiled_assets[path] = {
            "kind": entry.kind,
            "duration": entry.duration,
            "lineage": normalize_generation(entry.lineage),
        }

    if errors:
        return None, errors

    compiled = {
        "version": spec.version,
        "canvas": {
            "width": c.width,
            "height": c.height,
            "fps": int(c.fps),
            "duration": c.duration,
            "background": c.background,
        },
        "tracks": compiled_tracks,
        "assets": compiled_assets,
        "qc": {
            "dual_shuffle": bool(spec.qc.dual_shuffle),
            "text_safe_area": list(spec.qc.text_safe_area) if spec.qc.text_safe_area else None,
        },
        "lineage": {
            "route": spec.lineage.route,
            "spec_id": spec.lineage.spec_id,
            "created_by": spec.lineage.created_by,
        },
    }
    return compiled, []


# ============================================================
# 从分镜表生成 spec 草案（V4.44 最小版：纯数据变换）
# ============================================================

def from_storyboard(
    shots: List[Dict[str, Any]],
    *,
    width: int = 1080,
    height: int = 1920,
    fps: int = 30,
    spec_id: str = "",
) -> Tuple[Optional[CodeVideoSpec], List[str]]:
    """分镜表 → CodeVideoSpec 草案。

    分镜表条目约定（与 director_timeline / pipeline.director_breakdown 同构）：
        {"shot": 1, "description": "雨夜霓虹街头，少女回头",
         "duration": 6.0, "camera": "推镜"}

    产物结构（模板优先原则，2026-10-19 用户截图验证的工作法）：
        * 每个镜头一条 asset:// clip（素材位，扩散路线产物稍后登记进 assets）
        * 片头标题卡 html://title.html（文字层铁律 ⇒ 只能代码路线）
        * 全片字幕轨 html://subtitle.html
    缺 duration 的镜头**不猜 3 秒**，进 errors 如实报告。
    """
    errors: List[str] = []
    if not isinstance(shots, list) or not shots:
        return None, ["分镜表为空或不是数组"]

    assets: Dict[str, AssetEntry] = {}
    cursor = 3.0  # 片头标题卡固定 3s（模板）
    video_clips: List[SpecClip] = []

    title_clip = SpecClip(
        id="clip_title",
        source="html://title.html",
        range=[0.0, cursor],
        kind="text",
        params={"title": "未命名成片"},
    )
    video_clips.append(title_clip)

    for i, shot in enumerate(shots):
        if not isinstance(shot, dict):
            errors.append(f"shots[{i}] 不是对象")
            continue
        dur = _num(shot.get("duration"))
        if dur is None or dur <= 0:
            errors.append(f"shots[{i}] (shot={shot.get('shot', '?')}) 缺有效 duration（不猜默认值）")
            continue
        sid = str(shot.get("shot") or i + 1)
        # 路径基准 = canvas_inbox_dir() 根（/inbox_file/<name> 直接服务该目录），
        # 因此是 shot_N.mp4，不是 inbox/shot_N.mp4（后者会多套一层，V4.44 修正）。
        asset_path = f"shot_{sid}.mp4"
        clip = SpecClip(
            id=f"clip_shot_{sid}",
            source=f"asset://{asset_path}",
            range=[cursor, cursor + dur],
            kind="video",
            params={"description": str(shot.get("description") or "")},
        )
        video_clips.append(clip)
        assets[asset_path] = AssetEntry(kind="video", duration=dur)
        cursor += dur

    total = cursor
    spec = CodeVideoSpec(
        canvas=CanvasSettings(width=width, height=height, fps=fps, duration=total),
        tracks=[
            SpecTrack(id="v1", kind="video", clips=video_clips),
            SpecTrack(
                id="s1",
                kind="subtitle",
                clips=[
                    SpecClip(
                        id="clip_subtitle",
                        source="html://subtitle.html",
                        range=[0.0, total],
                        kind="subtitle",
                        params={"text": []},
                    )
                ],
            ),
        ],
        assets=assets,
        lineage=SpecLineage(route="hybrid", spec_id=spec_id, created_by="pipeline.code_video_plan"),
    )
    return spec, errors


# JSON Schema 描述常量（文档/前端镜像用；运行时校验以 validate_spec/compile_spec 为准）
CODE_VIDEO_JSON_SCHEMA: Dict[str, Any] = {
    "$id": "code-video-spec/1.0",
    "type": "object",
    "required": ["version", "canvas", "tracks"],
    "properties": {
        "version": {"const": SPEC_VERSION},
        "canvas": {
            "type": "object",
            "required": ["width", "height", "fps", "duration"],
            "properties": {
                "width": {"type": "integer", "maximum": MAX_CANVAS_W},
                "height": {"type": "integer", "maximum": MAX_CANVAS_H},
                "fps": {"enum": list(ALLOWED_FPS)},
                "duration": {"type": "number", "maximum": DEFAULT_MAX_DURATION},
                "background": {"type": "string"},
            },
        },
        "tracks": {"type": "array", "items": {"type": "object"}},
        "assets": {"type": "object"},
        "qc": {"type": "object"},
        "lineage": {"type": "object"},
        "limits": {"type": "object"},
    },
}
