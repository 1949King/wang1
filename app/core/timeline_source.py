# -*- coding: utf-8 -*-
"""工程源码 —— 把「工程数据」升级成「工程源码」。

为什么需要这一层
----------------
工程文件（`.timeline`）本身已经是 JSON，也人可读，但它是**序列化产物**：
机器写、机器读、字段名是英文缩写、时间是一长串浮点秒。
它适合**存**，不适合**看**，更不适合**改**与**审**。

本模块提供另一条**投影**：同一份 `_clips`，渲染成
- 按片段分块（不是一维嵌套 dict）
- 时间用时间码 `00:10.000`（不是裸浮点）
- 字段用中文标签（不是 `in_point`）
- 未知字段**不丢弃**（归入「扩展」段）

于是它同时具备三件事：**人看得懂、diff 看得清、Agent 改得动**。
这正是 Hypit 那套「视频即代码」的实质 —— 而本项目原有的
`timeline_dsl.py`（时间轴 JSON-DSL）从未接入（全库唯一导入点导了不用），
所以这一层是**新补的**，不是复用旧的。

设计约束
--------
* **纯函数、无 Qt、无 I/O** —— 可脱离界面单测
* **不丢信息** —— 已知字段显式渲染，未知字段原样落到「扩展」段，
  往返后 `_clips` 的键集合不变
* **精度显式** —— 时间码为**毫秒**精度；原数据超出毫秒时照实截断并计入
  `warnings`，由调用方决定是否提示（绝不静默丢精度）
* **解析失败要响** —— `parse_source` 遇未知语法抛 `SourceParseError`，
  不猜、不吞（宁可报错也不要产出一份错的工程）

用法
----
    text = render_source(clips, sequence=seq, subtitles=subs)
    parsed = parse_source(text)          # {"clips": [...], "sequence": {...}, "warnings": [...]}
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence, Tuple

FORMAT_VERSION = 1

#: 时间码精度：毫秒。往返后时间误差应 < 1e-3 秒。
TIMECODE_PRECISION = 3

# ── 已知字段 → 中文标签。顺序即渲染顺序。
# `id` 必须渲染：它是片段身份，人改源码后回读、以及将来的「源码→工程」
# 导入都靠它定位。首版把它当内部字段不渲染，结果往返比对直接暴露矛盾。
KNOWN_FIELDS: Tuple[Tuple[str, str], ...] = (
    ("id", "标识"),
    ("name", "名称"),
    ("path", "素材"),
    ("type", "类型"),
    ("track", "轨道"),
    ("duration", "时长"),
    ("in_point", "取用入点"),
    ("out_point", "取用出点"),
    ("volume", "音量"),
    ("effects", "特效"),
    ("transitions", "转场"),
    ("transform", "变换"),
    ("keyframes", "关键帧"),
    ("color", "标记色"),
    ("notes", "备注"),
    ("metadata", "元数据"),
)

#: 在块头（`[n] 时间码 → 时间码`）里已体现、不再单独成行的字段
HEADER_FIELDS = frozenset({"start_time"})


class SourceParseError(ValueError):
    """工程源码语法错误。宁可报错，也不要产出一份错的工程。"""


# ══════════════════════════════════════════════════════════════
# 时间码
# ══════════════════════════════════════════════════════════════

def format_timecode(seconds: float) -> str:
    """秒 → `MM:SS.mmm`。负数取绝对值（剪辑数据不应出现负数，取绝对值是为了
    让异常值可见而不是渲染成奇怪的字符串）。"""
    try:
        s = abs(float(seconds))
    except (TypeError, ValueError):
        s = 0.0
    total_ms = int(round(s * 1000))
    minutes, rem = divmod(total_ms, 60_000)
    secs, ms = divmod(rem, 1000)
    return f"{minutes:02d}:{secs:02d}.{ms:03d}"


_TC_RE = re.compile(r"^(\d+):(\d{2})\.(\d{3})$")


def parse_timecode(text: str) -> float:
    """`MM:SS.mmm` → 秒。"""
    m = _TC_RE.match(text.strip())
    if not m:
        raise SourceParseError(f"时间码格式应为 MM:SS.mmm，实际收到: {text!r}")
    minutes, secs, ms = (int(x) for x in m.groups())
    if secs >= 60:
        raise SourceParseError(f"时间码秒位应 < 60，实际收到: {text!r}")
    return minutes * 60 + secs + ms / 1000.0


def _seconds_to_ms_loss(seconds: Any) -> float:
    """返回把该秒值截断到毫秒后丢失的量（用于 warnings）。"""
    try:
        v = float(seconds)
    except (TypeError, ValueError):
        return 0.0
    return abs(v - round(v * 1000) / 1000.0)


# ══════════════════════════════════════════════════════════════
# 渲染
# ══════════════════════════════════════════════════════════════

def _fmt_value(value: Any) -> str:
    """把字段值渲染成单行文本。"""
    if value is None:
        return "—"
    if isinstance(value, bool):
        return "是" if value else "否"
    if isinstance(value, (int, float)):
        if isinstance(value, float):
            return f"{value:g}"
        return str(value)
    if isinstance(value, str):
        return value if value else "—"
    # dict / list 等：紧凑 JSON，保证可解析回来
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _is_empty(value: Any) -> bool:
    return value in (None, "", 0, 0.0, {}, [], ())


def render_source(
    clips: Sequence[Dict[str, Any]],
    *,
    sequence: Optional[Dict[str, Any]] = None,
    subtitles: Optional[Sequence[Any]] = None,
    project_name: str = "",
    master_volume: Optional[float] = None,
    generated_at: Optional[datetime] = None,
) -> str:
    """把工程数据渲染成人类可读的工程源码。

    `clips` 用 `EditorModule._clips_snapshot()` 的产物（调用方负责在锁内取快照）。
    """
    clips = list(clips or [])
    generated_at = generated_at or datetime.now()

    out: List[str] = []
    warnings: List[str] = []

    # ── 头 ──
    out.append("# 拾光剪影 · 工程源码")
    out.append("#")
    out.append("# 这是给人看、给人改、能进版本管理的工程描述。")
    out.append("# 与 .timeline（JSON 工程文件）表达同一份数据，但按片段分块、")
    out.append("# 时间用时间码、字段用中文标签 —— 便于 review 与 diff。")
    out.append("#")
    if project_name:
        out.append(f"# 工程: {project_name}")
    out.append(f"# 生成: {generated_at.strftime('%Y-%m-%d %H:%M:%S')}")

    total = sum(float(c.get("duration", 0) or 0) for c in clips)
    if clips:
        last_end = max(
            (float(c.get("start_time", 0) or 0) + float(c.get("duration", 0) or 0))
            for c in clips
        )
        out.append(f"# 片段: {len(clips)} 个 | 总时长: {format_timecode(total)} "
                   f"| 成片末尾: {format_timecode(last_end)}")
    else:
        out.append("# 片段: 0 个（空时间轴）")

    if sequence:
        aspect = sequence.get("aspect", "")
        w, h = sequence.get("width", ""), sequence.get("height", "")
        fit = sequence.get("fit_mode", "")
        fit_cn = {"contain": "黑边", "cover": "裁切铺满"}.get(str(fit), str(fit))
        orient = "竖屏" if str(h).isdigit() and str(w).isdigit() and int(h) > int(w) else "横屏"
        if str(w) == str(h):
            orient = "方形"
        out.append(f"# 画幅: {orient} {aspect} · {w}×{h} · {fit_cn}")
    if subtitles:
        out.append(f"# 字幕: {len(subtitles)} 条")
    if master_volume is not None:
        out.append(f"# 主音量: {float(master_volume):g}")

    out.append("")
    out.append(f"@version {FORMAT_VERSION}")

    # ── 画幅块 ──
    if sequence:
        out.append("")
        out.append("[画幅]")
        for k in ("aspect", "width", "height", "fit_mode"):
            if k in sequence:
                out.append(f"  {k} = {_fmt_value(sequence[k])}")

    # ── 片段块 ──
    for idx, clip in enumerate(clips, start=1):
        start = float(clip.get("start_time", 0) or 0)
        dur = float(clip.get("duration", 0) or 0)
        track = clip.get("track", 0)
        ctype = clip.get("type", "video")

        for f in ("start_time", "duration", "in_point", "out_point"):
            loss = _seconds_to_ms_loss(clip.get(f))
            if loss > 1e-6:
                warnings.append(
                    f"片段 {idx} 的 {f}={clip.get(f)!r} 超出毫秒精度，"
                    f"已截断（损失 {loss:.6f}s）"
                )

        out.append("")
        out.append(
            f"[{idx}] {format_timecode(start)} → {format_timecode(start + dur)}"
            f"  ({dur:g}s)  轨道 {track} · {ctype}"
        )

        # 已知字段
        for key, label in KNOWN_FIELDS:
            if key in HEADER_FIELDS:
                continue
            if key not in clip:
                continue
            val = clip[key]
            if key == "duration":
                continue  # 已在块头显示
            if key == "track" or key == "type":
                continue  # 已在块头显示
            if _is_empty(val) and key in ("effects", "transitions"):
                continue  # 空特效/空转场不占行，保持源码干净
            out.append(f"  {label}  {_fmt_value(val)}")

        # 未知字段 → 扩展段（不丢信息）
        known = set(k for k, _ in KNOWN_FIELDS) | {"start_time"}
        extras = {k: v for k, v in clip.items() if k not in known}
        if extras:
            out.append("  扩展")
            for k in sorted(extras):
                out.append(f"    {k} = {_fmt_value(extras[k])}")

    # ── 脚注：把渲染期告警也写进源码，避免"看着没问题其实截断了" ──
    out.append("")
    if warnings:
        out.append("# ⚠️ 精度提示")
        for w in warnings:
            out.append(f"#   {w}")
    else:
        out.append("# 无警告：时间数据均在毫秒精度内，往返无损。")

    return "\n".join(out) + "\n"


# ══════════════════════════════════════════════════════════════
# 解析
# ══════════════════════════════════════════════════════════════

_BLOCK_HEAD_RE = re.compile(
    r"^\[(\d+)\]\s+(\d+:\d{2}\.\d{3})\s+→\s+(\d+:\d{2}\.\d{3})"
    r"\s+\(([\d.]+)s\)\s+轨道\s+(-?\d+)\s+·\s+(\S+)\s*$"
)

#: 中文标签 → 字段名（渲染用的反向映射）
_LABEL_TO_KEY = {label: key for key, label in KNOWN_FIELDS}
#: 值里是「紧凑 JSON」的字段：解析时要尝试 json.loads
_JSON_VALUED = frozenset({"effects", "transitions", "transform", "keyframes", "metadata"})


def _parse_value(key: str, raw: str) -> Any:
    raw = raw.strip()
    if raw == "—":
        return "" if key in ("name", "path", "color", "notes", "type") else None
    if raw == "是":
        return True
    if raw == "否":
        return False
    if key in _JSON_VALUED:
        try:
            return json.loads(raw)
        except json.JSONDecodeError as e:
            raise SourceParseError(f"字段 {key} 的值不是合法 JSON: {raw!r}（{e}）") from e
    # 数字字段
    if key in ("duration", "in_point", "out_point", "volume"):
        try:
            return float(raw)
        except ValueError:
            return raw
    return raw


def parse_source(text: str) -> Dict[str, Any]:
    """把工程源码解析回工程数据。

    返回 ``{"clips": [...], "sequence": {...}, "version": int, "warnings": [...]}``。
    语法不认识时抛 `SourceParseError` —— 不猜。
    """
    clips: List[Dict[str, Any]] = []
    sequence: Dict[str, Any] = {}
    version = 0
    warnings: List[str] = []

    current: Optional[Dict[str, Any]] = None
    in_sequence_block = False
    in_extras = False

    for lineno, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.rstrip()
        stripped = line.strip()

        if not stripped or stripped.startswith("#"):
            continue

        # @version
        if stripped.startswith("@version"):
            parts = stripped.split()
            if len(parts) != 2 or not parts[1].isdigit():
                raise SourceParseError(f"第 {lineno} 行：@version 需要数字，得到 {stripped!r}")
            version = int(parts[1])
            continue

        # [画幅] 块
        if stripped == "[画幅]":
            in_sequence_block = True
            current, in_extras = None, False
            continue

        # [n] 片段块
        m = _BLOCK_HEAD_RE.match(stripped)
        if m:
            idx, tc_start, tc_end, dur_s, track, ctype = m.groups()
            start = parse_timecode(tc_start)
            end = parse_timecode(tc_end)
            declared_dur = float(dur_s)
            # 块头的 (xxxs) 是给人看的；以时间码为准，不一致才告警
            if abs((end - start) - declared_dur) > 1e-3:
                warnings.append(
                    f"第 {lineno} 行：块头时长 {declared_dur}s 与时间码差 "
                    f"{abs((end - start) - declared_dur):.3f}s，已采用时间码"
                )
            current = {
                "start_time": start,
                "duration": round(end - start, 3),
                "track": int(track),
                "type": ctype,
            }
            clips.append(current)
            in_sequence_block, in_extras = False, False
            continue

        if current is None and not in_sequence_block:
            raise SourceParseError(
                f"第 {lineno} 行：在任何块之外出现内容 {stripped!r}"
            )

        # 画幅块内容：`key = value`
        if in_sequence_block:
            if "=" not in stripped:
                raise SourceParseError(f"第 {lineno} 行：画幅块内应为 `key = value`，得到 {stripped!r}")
            k, _, v = stripped.partition("=")
            k, v = k.strip(), v.strip()
            if k in ("width", "height"):
                try:
                    sequence[k] = int(v)
                except ValueError:
                    sequence[k] = v
            else:
                sequence[k] = v
            continue

        assert current is not None

        # 扩展段
        if stripped == "扩展":
            in_extras = True
            continue
        if in_extras:
            if "=" not in stripped:
                raise SourceParseError(f"第 {lineno} 行：扩展段内应为 `key = value`，得到 {stripped!r}")
            k, _, v = stripped.partition("=")
            k, v = k.strip(), v.strip()
            try:
                current[k] = json.loads(v)
            except json.JSONDecodeError:
                current[k] = v
            continue

        # 已知字段行：`标签  值`
        parts = stripped.split(None, 1)
        label = parts[0]
        value_raw = parts[1] if len(parts) > 1 else "—"
        key = _LABEL_TO_KEY.get(label)
        if key is None:
            raise SourceParseError(f"第 {lineno} 行：未知字段标签 {label!r}")
        if key in HEADER_FIELDS:
            # 块头已给出，忽略（但若是重复渲染产物，不应走到这里）
            continue
        current[key] = _parse_value(key, value_raw)

    return {
        "clips": clips,
        "sequence": sequence,
        "version": version,
        "warnings": warnings,
    }


# ══════════════════════════════════════════════════════════════
# 往返校验
# ══════════════════════════════════════════════════════════════

@dataclass
class RoundTripDiff:
    index: int
    field: str
    before: Any
    after: Any


_MISSING = object()


def compare_roundtrip(
    clips: Sequence[Dict[str, Any]], parsed_clips: Sequence[Dict[str, Any]]
) -> List[RoundTripDiff]:
    """比对原始 clips 与往返解析结果，返回差异清单（空 = 无损）。

    比对规则（三条，缺一不可）：
    1. **键集合按「渲染时会省略的空值」放宽**：空的特效/转场渲染时被省略，
       解析回来该键不存在 —— 这不算差异。但 `0` / `0.0` 这类「有意义的零」
       （如 `in_point=0`、`track=0`）**会被渲染**，因此必须算作存在，
       否则会把「本来就在的值」误报成「解析后多出」。
    2. 数值按毫秒精度比对（见 `TIMECODE_PRECISION`）。
    3. 其余按渲染文本比对（保证「人看到的」与「回来的」一致）。
    """
    diffs: List[RoundTripDiff] = []
    if len(clips) != len(parsed_clips):
        diffs.append(RoundTripDiff(-1, "<片段数>", len(clips), len(parsed_clips)))
        return diffs

    #: 渲染时会被省略的字段（空值即省略）
    omitted_when_empty = ("effects", "transitions", "keyframes")

    def _consider_missing(key: str, value: Any) -> bool:
        """该值是否会被渲染省略（= 在解析结果里可以合法地不存在）。"""
        return key in omitted_when_empty and _is_empty(value)

    for i, (a, b) in enumerate(zip(clips, parsed_clips)):
        for k in sorted(set(a) | set(b)):
            in_a, in_b = k in a, k in b
            va = a.get(k, _MISSING)
            vb = b.get(k, _MISSING)

            if not in_b and in_a and _consider_missing(k, va):
                continue                      # 渲染省略 → 合法缺失
            if not in_a and in_b and _consider_missing(k, vb):
                continue
            if not in_a:
                diffs.append(RoundTripDiff(i, k + "（解析后多出）", None, vb))
                continue
            if not in_b:
                diffs.append(RoundTripDiff(i, k + "（解析后缺失）", va, None))
                continue

            if isinstance(va, (int, float)) and isinstance(vb, (int, float)) \
                    and not isinstance(va, bool) and not isinstance(vb, bool):
                if abs(float(va) - float(vb)) > 10 ** (-TIMECODE_PRECISION):
                    diffs.append(RoundTripDiff(i, k, va, vb))
            elif _fmt_value(va) != _fmt_value(vb):
                diffs.append(RoundTripDiff(i, k, va, vb))
    return diffs


__all__ = [
    "FORMAT_VERSION",
    "TIMECODE_PRECISION",
    "KNOWN_FIELDS",
    "SourceParseError",
    "RoundTripDiff",
    "format_timecode",
    "parse_timecode",
    "render_source",
    "parse_source",
    "compare_roundtrip",
]
