# -*- coding: utf-8 -*-
"""阶段1：抽取 timeline_subwidgets.py（常量/工具函数/gate/4 个子控件）。

从 timeline_widget.py 中把底层共享符号（AUDIO_EXTS、_MediaWorkerGate、常量、
缩放/吸附/时间量化/帧转 QPixmap/胶片条抽帧工具函数、TimeRuler、TimelineMarkerLayer、
TrackControlPanel、TrackViewport）抽到独立文件，原文件 re-export 保持兼容。

边界（1-indexed，与当前文件实测一致）：
  AUDIO_EXTS                -> 50
  class TimeRuler           -> 266
  class TimelineMarkerLayer -> 444
  class TrackControlPanel   -> 683
  class TrackViewport       -> 848
  class TimelineWidget      -> 1044  （tail 起点）
"""
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC = ROOT / "app" / "modules" / "lego" / "timeline_widget.py"

lines = SRC.read_text(encoding="utf-8").split("\n")

SUB_HEADER = '''"""时间线控件 — 子控件与基础设施
================================
从 timeline_widget.py 抽取的底层共享符号：
- AUDIO_EXTS 音频扩展名列表
- _MediaWorkerGate 全局限流（胶片条/波形 QThread 并发上限）
- 时间线常量与工具函数（缩放、吸附、时间量化、帧转 QPixmap、胶片条抽帧）
- TimeRuler 时间标尺
- TimelineMarkerLayer 时间轴标记层
- TrackControlPanel 轨道控制面板
- TrackViewport 轨道视图区域
"""
import os
import json
import logging
import threading
import time
import urllib.request
import weakref

from PySide6.QtCore import Qt, Signal, QPoint
from PySide6.QtGui import (
    QFont, QColor, QPainter, QPen, QBrush, QFontMetrics,
    QPolygon, QPixmap, QImage,
)
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QSlider,
)

from .editor_timeline_tools import paint_marquee_overlay

logger = logging.getLogger("AI短剧编辑器.timeline_widget")

'''

# 原文件 50-1043 行（1-indexed）→ lines[49:1043]（0-indexed，AUDIO_EXTS 到 TrackViewport 末尾）
sub_body = "\n".join(lines[49:1043]).rstrip("\n") + "\n"

subwidgets = SUB_HEADER + sub_body
(ROOT / "app" / "modules" / "lego" / "timeline_subwidgets.py").write_text(
    subwidgets, encoding="utf-8"
)

NEW_DOC = '"""时间线控件模块\n'
NEW_DOC += "================\n"
NEW_DOC += "时间线主控件与片段控件（子控件与基础设施已抽到 timeline_subwidgets.py）。\n"
NEW_DOC += "- TimelineWidget: 时间线主控件\n"
NEW_DOC += "- ClipWidget: 片段控件\n"
NEW_DOC += '"""\n'

# 原文件 11-48 行（import + logger）；paint_marquee_overlay 已随 TrackViewport 抽到子文件
head_imports = "\n".join(lines[10:48])
head_imports = head_imports.replace("    paint_marquee_overlay,\n", "")

RE_EXPORT = '''# 子控件与基础设施已抽到 timeline_subwidgets.py，此处 re-export 保持外部 import 兼容
from .timeline_subwidgets import (
    AUDIO_EXTS,
    _MediaWorkerGate,
    _media_worker_gate,
    _TIMELINE_ZOOM_MIN,
    _TIMELINE_ZOOM_MAX,
    _TIMELINE_BASE_PPS,
    _TIMELINE_SNAP_PX,
    _TIMELINE_MIN_CLIP_PX,
    _DEFAULT_FPS,
    _clamp_timeline_zoom,
    _timeline_pps,
    _quantize_time,
    _ndarray_bgr_to_pixmap,
    _extract_filmstrip_frames,
    TimeRuler,
    TimelineMarkerLayer,
    TrackControlPanel,
    TrackViewport,
)
'''

# 原文件 1044 行起（TimelineWidget 到文件尾）
tail = "\n".join(lines[1043:])

new_tw = NEW_DOC + head_imports + "\n" + RE_EXPORT + "\n\n" + tail
SRC.write_text(new_tw, encoding="utf-8")

print("阶段1切分完成：已生成 timeline_subwidgets.py 并改写 timeline_widget.py")