# -*- coding: utf-8 -*-
"""阶段2：抽取 clip_widget.py（ClipWidget），并解 isinstance 循环依赖。

从 timeline_widget.py 尾部抽出 ClipWidget（1-indexed 第 1427 行到文件末尾），
移入独立文件 clip_widget.py，原文件 re-export 保持外部 import 兼容。

循环依赖处理：ClipWidget._find_timeline_widget 内 `isinstance(w, TimelineWidget)`
改为方法内延迟导入 TimelineWidget，避免形成
timeline_widget -> clip_widget -> timeline_widget 的模块导入环。

边界（1-indexed，Python split 实测对齐）：
  class TimelineWidget  -> 68
  class ClipWidget      -> 1427（tail 起点，直到文件末尾）
"""
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC = ROOT / "app" / "modules" / "lego" / "timeline_widget.py"
DST = ROOT / "app" / "modules" / "lego" / "clip_widget.py"

lines = SRC.read_text(encoding="utf-8").split("\n")
# 去掉 split 在文件末尾产生的空串，使行号与 1-indexed 对齐
while lines and lines[-1] == "":
    lines.pop()

# ClipWidget 类从 1-indexed 第 1427 行开始 = 0-indexed lines[1426]
CLIP_START = 1426
assert lines[CLIP_START].startswith("class ClipWidget"), lines[CLIP_START]

clip_body = "\n".join(lines[CLIP_START:]).rstrip("\n") + "\n"

# 解循环依赖：在 _find_timeline_widget 内延迟导入 TimelineWidget
_FIND_METHOD = """    def _find_timeline_widget(self):
        w = self.parent()"""
_FIND_METHOD_FIXED = """    def _find_timeline_widget(self):
        from .timeline_widget import TimelineWidget  # 延迟导入，避免与 timeline_widget 循环依赖
        w = self.parent()"""
assert _FIND_METHOD in clip_body, "未找到 _find_timeline_widget 目标方法"
clip_body = clip_body.replace(_FIND_METHOD, _FIND_METHOD_FIXED, 1)

CLIP_HEADER = '''"""时间线片段控件模块
====================
从 timeline_widget.py 抽取的 ClipWidget（时间线片段控件）。
- ClipWidget: 时间线中的单个片段（拖拽 / 裁剪 / 关键帧 / 胶片条 / 波形）。
延迟导入 TimelineWidget 以解除与 timeline_widget 的循环依赖。
"""
import os
import logging

from PyQt6.QtCore import Qt, pyqtSignal, QTimer, QPoint
from PyQt6.QtGui import (
    QColor, QPainter, QPen, QBrush, QFontMetrics, QPolygon, QPixmap,
)
from PyQt6.QtWidgets import QFrame, QHBoxLayout, QLabel, QToolTip

from .editor_timeline_tools import (
    apply_batch_start_delta,
    clip_compatible_with_track,
    CLIP_DRAG_THRESHOLD_PX,
)
from .timeline_subwidgets import (
    AUDIO_EXTS,
    _media_worker_gate,
    _TIMELINE_MIN_CLIP_PX,
    _timeline_pps,
    _quantize_time,
    _extract_filmstrip_frames,
)

logger = logging.getLogger("AI短剧编辑器.timeline_widget")

'''

DST.write_text(CLIP_HEADER + clip_body, encoding="utf-8")

# 重写 timeline_widget.py：保留 TimelineWidget 部分，移除 ClipWidget，re-export
head = "\n".join(lines[:CLIP_START]).rstrip("\n") + "\n"

# 更新模块 docstring，说明 ClipWidget 已抽到 clip_widget.py
head = head.replace(
    "时间线主控件与片段控件（子控件与基础设施已抽到 timeline_subwidgets.py）。",
    "时间线主控件（子控件/基础设施抽到 timeline_subwidgets.py，片段控件抽到 clip_widget.py）。",
)
head = head.replace(
    "- ClipWidget: 片段控件",
    "- ClipWidget: 片段控件（抽到 clip_widget.py，此处 re-export）",
)

RE_EXPORT = (
    "\n# ClipWidget 已抽到 clip_widget.py，此处 re-export 保持外部 import 兼容\n"
    "from .clip_widget import ClipWidget\n\n"
)

SRC.write_text(head + RE_EXPORT, encoding="utf-8")

print("阶段2切分完成：已生成 clip_widget.py 并改写 timeline_widget.py")