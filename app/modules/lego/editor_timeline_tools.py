"""
时间线手感工具（吸附指示线 / 多选 / 框选 / 批量平移）
================================================
从 timeline_widget 抽出的轻量逻辑，避免继续膨胀主文件。
真相源仍是 EditorModule._clips；此处只操作 TimelineWidget 视图层选区与吸附引导。
"""

from __future__ import annotations

import logging
from typing import Iterable, Optional, Sequence, Set, Tuple

from PySide6.QtCore import QPoint, QRect, Qt, QTimer
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QApplication, QFrame, QWidget

logger = logging.getLogger(__name__)

# 吸附线淡出（ms）
SNAP_GUIDE_FADE_MS = 180
# 框选启动阈值（px）
MARQUEE_DRAG_THRESHOLD_PX = 4
# 片段拖移/误触：低于此曼哈顿距离视为点击，不挪片
CLIP_DRAG_THRESHOLD_PX = 5


def clip_looks_heavy(clip_data) -> bool:
    """粗判高负载片段（转场/滤镜/LUT/关键帧/变速）— 供标尺红线提示。"""
    if not isinstance(clip_data, dict):
        return False
    if str(clip_data.get("type", "")).lower() == "audio":
        return False
    if clip_data.get("transition") or clip_data.get("transitions"):
        return True
    if clip_data.get("effects") or clip_data.get("filters") or clip_data.get("lut"):
        return True
    if clip_data.get("speed_ramp") or clip_data.get("keyframes"):
        return True
    try:
        if abs(float(clip_data.get("speed", 1) or 1) - 1.0) > 1e-3:
            return True
    except (TypeError, ValueError):
        logger.debug("clip speed 非数值，按 1.0 处理: %r", clip_data.get("speed"), exc_info=True)
    return False


def compute_load_spans(clips: Iterable) -> list:
    """返回 [(start, end), ...] 高负载区间（秒）。"""
    spans = []
    for c in clips or []:
        if not clip_looks_heavy(c):
            continue
        st = float(c.get("start_time", 0) or 0)
        dur = max(0.0, float(c.get("duration", 0) or 0))
        if dur <= 1e-4:
            continue
        spans.append((st, st + dur))
    return spans

_AUDIO_EXTS = (".mp3", ".wav", ".aac", ".m4a", ".flac", ".ogg", ".wma")


def clip_id_of(clip_data) -> Optional[str]:
    if not isinstance(clip_data, dict):
        return None
    cid = clip_data.get("id")
    return cid if cid is not None else None


def clip_span(clip_data) -> Tuple[float, float]:
    """返回 (start, end)，end = start + duration。"""
    st = float(clip_data.get("start_time", 0) or 0)
    dur = max(0.0, float(clip_data.get("duration", 0) or 0))
    return st, st + dur


def clip_is_audio(clip_data) -> bool:
    """片段是否应按音频轨约束（类型或常见音频扩展名）。"""
    if not isinstance(clip_data, dict):
        return False
    if str(clip_data.get("type", "")).lower() == "audio":
        return True
    path = str(clip_data.get("path") or "").lower()
    return path.endswith(_AUDIO_EXTS)


def track_is_audio(track) -> bool:
    if not isinstance(track, dict):
        return False
    return str(track.get("type", "")).lower() == "audio"


def clip_compatible_with_track(clip_data, track) -> bool:
    """跨轨落点：仅同类型（音频↔音频，非音频↔非音频）。字幕轨按非音频处理。"""
    return clip_is_audio(clip_data) == track_is_audio(track)


def keyboard_mods():
    return QApplication.keyboardModifiers()


def is_ctrl(mods=None) -> bool:
    m = mods if mods is not None else keyboard_mods()
    return bool(m & Qt.KeyboardModifier.ControlModifier)


def is_shift(mods=None) -> bool:
    m = mods if mods is not None else keyboard_mods()
    return bool(m & Qt.KeyboardModifier.ShiftModifier)


def rect_from_points(a: QPoint, b: QPoint) -> QRect:
    return QRect(a, b).normalized()


def clip_widget_rect_in(widget: QWidget, target: QWidget) -> QRect:
    """将 clip 控件矩形映射到 target 坐标系。"""
    top_left = widget.mapTo(target, QPoint(0, 0))
    return QRect(top_left, widget.size())


def ids_intersecting_viewport_rect(timeline, viewport_rect: QRect) -> Set:
    """与视口矩形相交的片段 id 集合。"""
    hits: Set = set()
    viewport = getattr(timeline, "_track_viewport", None)
    if viewport is None or viewport_rect is None or viewport_rect.isNull():
        return hits
    for w in timeline.all_clip_widgets():
        try:
            r = clip_widget_rect_in(w, viewport)
        except Exception:
            continue
        if r.intersects(viewport_rect):
            cid = clip_id_of(getattr(w, "clip_data", None))
            if cid is not None:
                hits.add(cid)
    return hits


def same_track_range_ids(timeline, anchor_id, target_id) -> Set:
    """
    同轨范围选（直觉版）：
    - 锚点与目标片的时间外包络 [lo, hi] = [min(starts), max(ends)]
    - 选中同轨上与 [lo, hi] 时间重叠、或完全夹在其间的全部片段
    - 不同轨时退化为 {anchor, target} 中有效 id
    """
    clips = list(getattr(timeline, "_clips", []) or [])
    by_id = {c.get("id"): c for c in clips if c.get("id") is not None}
    a = by_id.get(anchor_id)
    t = by_id.get(target_id)
    out: Set = set()
    if a is None and t is None:
        return out
    if a is None:
        return {target_id}
    if t is None:
        return {anchor_id}
    ta = int(a.get("track", 0) or 0)
    tt = int(t.get("track", 0) or 0)
    if ta != tt:
        out.add(anchor_id)
        out.add(target_id)
        return out
    a0, a1 = clip_span(a)
    t0, t1 = clip_span(t)
    lo = min(a0, t0)
    hi = max(a1, t1)
    if hi < lo:
        lo, hi = hi, lo
    eps = 1e-6
    for c in clips:
        if int(c.get("track", 0) or 0) != ta:
            continue
        c0, c1 = clip_span(c)
        # 重叠或夹在 [lo, hi] 内（夹在是重叠的子集）
        if c1 > lo - eps and c0 < hi + eps:
            cid = c.get("id")
            if cid is not None:
                out.add(cid)
    if not out:
        out.add(anchor_id)
        out.add(target_id)
    return out


def pick_snap(
    proposed: float,
    candidates: Sequence[Tuple[float, float]],
    thr: float,
) -> Tuple[float, Optional[float]]:
    """
    candidates: (aligned_value, guide_time)
    返回 (best_aligned, guide_time|None)。
    guide_time 为实际对齐的边（片头/片尾/播放头），便于红线画在合缝处。
    """
    best = proposed
    best_d = thr + 1.0
    guide = None
    hit = False
    for aligned, g in candidates:
        d = abs(proposed - float(aligned))
        if d < best_d and d <= thr:
            best_d = d
            best = float(aligned)
            guide = float(g)
            hit = True
    return (best, guide if hit else None)


class SnapGuideController:
    """吸附竖直指示线：QFrame 覆盖层 + 可选淡出定时器。"""

    def __init__(self, timeline: QWidget, *, object_name: str = "snapGuideLine",
                 css: str = "background-color: rgba(0, 229, 255, 200);", width: int = 2):
        self.timeline = timeline
        self._guide_time: Optional[float] = None
        self._frame: Optional[QFrame] = None
        self._fade_timer: Optional[QTimer] = None
        self._object_name = object_name
        self._css = css
        self._width = max(1, int(width))

    @property
    def guide_time(self) -> Optional[float]:
        return self._guide_time

    def ensure_frame(self) -> Optional[QFrame]:
        viewport = getattr(self.timeline, "_track_viewport", None)
        if viewport is None:
            return None
        if self._frame is None:
            fr = QFrame(viewport)
            fr.setObjectName(self._object_name)
            fr.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
            fr.setStyleSheet(self._css)
            fr.setFixedWidth(self._width)
            fr.hide()
            self._frame = fr
        return self._frame

    def set_guide(self, t: Optional[float]):
        """实时显示吸附线；t=None 立即隐藏。"""
        if self._fade_timer is not None:
            self._fade_timer.stop()
        if t is None:
            self._guide_time = None
            fr = self._frame
            if fr is not None:
                fr.hide()
            return
        self._guide_time = float(t)
        fr = self.ensure_frame()
        if fr is None:
            return
        tl = self.timeline
        # 与片缘对齐：用 clip_container 原点 + t*pps（勿写死 100，否则相对 identifier 错位）
        if hasattr(tl, "content_x_for_time"):
            x = int(tl.content_x_for_time(t))
        else:
            x = 100 + int(float(t) * max(1e-6, tl.px_per_sec()))
        fr.setFixedHeight(max(1, tl._track_viewport.height()))
        fr.move(x, 0)
        fr.show()
        fr.raise_()

    def clear_guide(self, fade: bool = True):
        if not fade or self._guide_time is None:
            self.set_guide(None)
            tl = self.timeline
            if tl is not None and self._object_name == "snapGuideLine":
                tl._snap_guide_time = None
            return
        if self._fade_timer is None:
            self._fade_timer = QTimer(self.timeline)
            self._fade_timer.setSingleShot(True)

            def _hide():
                self.set_guide(None)
                if self.timeline is not None and self._object_name == "snapGuideLine":
                    self.timeline._snap_guide_time = None

            self._fade_timer.timeout.connect(_hide)
        self._fade_timer.start(SNAP_GUIDE_FADE_MS)


class DropTrackFeedbackController:
    """
    跨轨拖移落点反馈：兼容轨淡青底，不兼容轨淡红底。
    只改 clip_container 样式，松手/取消时还原。
    """

    _OK_CSS = "background:#152018; border:1px solid rgba(0, 220, 160, 160);"
    _BAD_CSS = "background:#201515; border:1px solid rgba(255, 100, 100, 160);"
    _CLEAR_CSS = "background:#111;"

    def __init__(self, timeline: QWidget):
        self.timeline = timeline
        self._index: Optional[int] = None
        self._ok: Optional[bool] = None

    def set_feedback(self, track_index: Optional[int], compatible: bool = True):
        if track_index is not None and self._index == int(track_index) and self._ok is bool(compatible):
            return
        self.clear()
        if track_index is None:
            return
        tracks = getattr(self.timeline, "_tracks", None) or []
        ti = int(track_index)
        if ti < 0 or ti >= len(tracks):
            return
        cc = tracks[ti].get("clip_container")
        if cc is None:
            return
        try:
            cc.setStyleSheet(self._OK_CSS if compatible else self._BAD_CSS)
        except Exception:
            return
        self._index = ti
        self._ok = bool(compatible)

    def clear(self):
        if self._index is None:
            return
        tracks = getattr(self.timeline, "_tracks", None) or []
        ti = self._index
        self._index = None
        self._ok = None
        if 0 <= ti < len(tracks):
            cc = tracks[ti].get("clip_container")
            if cc is not None:
                try:
                    cc.setStyleSheet(self._CLEAR_CSS)
                except Exception:
                    logger.debug("清除 clip 容器样式失败（UI 容错）", exc_info=True)


class RazorGuideController(SnapGuideController):
    """刀片悬停切开线（白/浅红，略宽于吸附线）。"""

    def __init__(self, timeline: QWidget):
        super().__init__(
            timeline,
            object_name="razorGuideLine",
            css="background-color: rgba(255, 120, 120, 220);",
            width=2,
        )


class TimelineSelectionMixin:
    """
    混入 TimelineWidget：多选 API。
    宿主需有：_clips, all_clip_widgets(), clip_selected 信号, _current_clip
    """

    def _init_selection_state(self):
        self._selected_ids: Set = set()
        self._selection_anchor_id = None
        self._current_clip = getattr(self, "_current_clip", None)

    def get_selected_ids(self) -> Set:
        return set(getattr(self, "_selected_ids", set()) or set())

    def get_selected_clips(self) -> list:
        ids = self.get_selected_ids()
        if not ids:
            return []
        out = []
        for c in getattr(self, "_clips", []) or []:
            if c.get("id") in ids:
                out.append(c)
        return out

    def clear_selection(self, emit: bool = True):
        """清空选区；默认通知 Editor，避免 Delete 幽灵删除。"""
        self._selected_ids = set()
        self._selection_anchor_id = None
        for w in self.all_clip_widgets():
            w.set_selected(False)
        self._current_clip = None
        if emit:
            self.clip_selected.emit(None)

    def _apply_selection_visual(self):
        ids = self.get_selected_ids()
        for w in self.all_clip_widgets():
            cid = clip_id_of(getattr(w, "clip_data", None))
            w.set_selected(cid in ids)

    def preview_selection_ids(self, ids: Iterable):
        """框选拖动中的临时高亮，不改 _selected_ids。"""
        id_set = {i for i in ids if i is not None}
        for w in self.all_clip_widgets():
            cid = clip_id_of(getattr(w, "clip_data", None))
            w.set_selected(cid in id_set)

    def set_selection(self, ids: Iterable, primary=None, emit: bool = True):
        id_set = {i for i in ids if i is not None}
        self._selected_ids = id_set
        if primary is not None and clip_id_of(primary) in id_set:
            self._current_clip = primary
            self._selection_anchor_id = clip_id_of(primary)
        elif id_set:
            # 主选：保留已有主选若仍在集内，否则取第一个
            cur = clip_id_of(getattr(self, "_current_clip", None))
            if cur not in id_set:
                for c in getattr(self, "_clips", []) or []:
                    if c.get("id") in id_set:
                        self._current_clip = c
                        break
            self._selection_anchor_id = clip_id_of(self._current_clip) or next(iter(id_set))
        else:
            self._current_clip = None
            self._selection_anchor_id = None
        self._apply_selection_visual()
        if emit:
            # 空选区也要 emit(None)，否则 Editor._current_clip 残留 → 幽灵 Delete
            self.clip_selected.emit(self._current_clip)

    def add_to_selection(self, ids: Iterable, primary=None, emit: bool = True):
        merged = self.get_selected_ids()
        merged.update(i for i in ids if i is not None)
        self.set_selection(merged, primary=primary, emit=emit)

    def toggle_selection(self, clip_data, emit: bool = True):
        cid = clip_id_of(clip_data)
        if cid is None:
            return
        ids = self.get_selected_ids()
        if cid in ids:
            ids.discard(cid)
            primary = None
            if ids:
                for c in getattr(self, "_clips", []) or []:
                    if c.get("id") in ids:
                        primary = c
                        break
            self.set_selection(ids, primary=primary, emit=emit)
        else:
            ids.add(cid)
            self.set_selection(ids, primary=clip_data, emit=emit)
            self._selection_anchor_id = cid

    def select_range_to(self, clip_data, emit: bool = True):
        cid = clip_id_of(clip_data)
        if cid is None:
            return
        anchor = getattr(self, "_selection_anchor_id", None)
        if anchor is None:
            self.set_selection([cid], primary=clip_data, emit=emit)
            return
        ids = same_track_range_ids(self, anchor, cid)
        self.set_selection(ids, primary=clip_data, emit=emit)

    def handle_clip_click(self, clip_data, mods=None):
        """普通 / Ctrl / Shift 点选。返回是否应保持多选拖移。"""
        mods = mods if mods is not None else keyboard_mods()
        cid = clip_id_of(clip_data)
        if cid is None:
            return False
        if is_ctrl(mods):
            self.toggle_selection(clip_data, emit=True)
            return False
        if is_shift(mods):
            self.select_range_to(clip_data, emit=True)
            return False
        # 点已在多选集中的成员：保持多选，仅换主选
        if cid in self.get_selected_ids() and len(self.get_selected_ids()) > 1:
            self._current_clip = clip_data
            self.clip_selected.emit(clip_data)
            return True
        self.set_selection([cid], primary=clip_data, emit=True)
        return False


def apply_batch_start_delta(
    timeline,
    id_to_start0: dict,
    primary_id,
    proposed_primary_start: float,
    exclude_ids: Optional[Sequence] = None,
    snap_track_i: Optional[int] = None,
) -> float:
    """
    多片同步平移：对主片做 snap_start_time，再把同一 Δ 应用到全集。
    snap_track_i：吸附参照轨（跨轨拖移时用指针下兼容轨）。
    返回吸附后的主片 start_time。
    """
    exclude = set(exclude_ids or ())
    exclude.update(id_to_start0.keys())
    primary_clip = None
    for c in getattr(timeline, "_clips", []) or []:
        if c.get("id") == primary_id:
            primary_clip = c
            break
    if primary_clip is None:
        return proposed_primary_start
    # 排除整组，避免组内互相吸附；命中时写 guide
    st = _snap_start_excluding(
        timeline,
        primary_clip,
        proposed_primary_start,
        exclude,
        track_i=snap_track_i,
    )
    st0 = float(id_to_start0.get(primary_id, primary_clip.get("start_time", 0)) or 0)
    delta = float(st) - st0
    widgets = {clip_id_of(w.clip_data): w for w in timeline.all_clip_widgets()}
    for cid, base in id_to_start0.items():
        new_st = max(0.0, float(base) + delta)
        for c in getattr(timeline, "_clips", []) or []:
            if c.get("id") == cid:
                timeline._write_clip_fields(c, start_time=new_st)  # 刀8：字段写走 store 唯一写缝
                break
        w = widgets.get(cid)
        if w is not None:
            w._write_fields(start_time=new_st)
            timeline.position_clip_widget(w)
    return float(st)


def snap_edge_candidates(
    timeline,
    proposed_start: float,
    dur: float,
    track_i: int,
    exclude_ids: Set,
) -> list:
    """构建 (aligned_start, guide_edge_time) 列表。"""
    playhead = float(getattr(timeline, "_playhead_pos", 0) or 0)
    # 对齐片头到 0 / 播放头 → 红线画在该点
    cands = [
        (0.0, 0.0),
        (playhead, playhead),
    ]
    for c in getattr(timeline, "_clips", []) or []:
        if c.get("id") in exclude_ids:
            continue
        if int(c.get("track", 0) or 0) != int(track_i):
            continue
        st = float(c.get("start_time", 0) or 0)
        cd = float(c.get("duration", 0) or 0)
        end = st + cd
        # 片头贴邻片头 / 邻片尾
        cands.append((st, st))
        cands.append((end, end))
        # 片尾贴邻片头 / 邻片尾 → aligned_start = edge - dur，红线画在合缝边
        cands.append((st - dur, st))
        cands.append((end - dur, end))
    return cands


def _snap_start_excluding(
    timeline,
    clip_data,
    proposed_start: float,
    exclude_ids: Set,
    track_i: Optional[int] = None,
) -> float:
    """吸附，但排除一组 id（批量拖移用）。命中时写 guide（画在对齐边上）。"""
    if not getattr(timeline, "_snap_enabled", False):
        if hasattr(timeline, "set_snap_guide"):
            timeline.set_snap_guide(None)
        return max(0.0, proposed_start)
    thr = timeline.snap_threshold_sec()
    if thr <= 0:
        if hasattr(timeline, "set_snap_guide"):
            timeline.set_snap_guide(None)
        return max(0.0, proposed_start)
    ti = int(track_i) if track_i is not None else int(clip_data.get("track", 0) or 0)
    dur = float(clip_data.get("duration", 0) or 0)
    cands = snap_edge_candidates(timeline, proposed_start, dur, ti, exclude_ids)
    best, guide = pick_snap(proposed_start, cands, thr)
    if hasattr(timeline, "set_snap_guide"):
        timeline.set_snap_guide(guide)
    return max(0.0, best)


def paint_marquee_overlay(painter: QPainter, rect: Optional[QRect]):
    if rect is None or rect.isNull() or rect.width() < 1 or rect.height() < 1:
        return
    painter.save()
    fill = QColor(30, 144, 255, 40)
    painter.fillRect(rect, fill)
    painter.setPen(QPen(QColor(0, 200, 255, 200), 1, Qt.PenStyle.DashLine))
    painter.drawRect(rect.adjusted(0, 0, -1, -1))
    painter.restore()
