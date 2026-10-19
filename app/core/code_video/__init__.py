# -*- coding: utf-8 -*-
"""code_video 域 —— 「代码 × 扩散」混合视频（V4.44 契约刀 · 2026-10-19）

域内模块（按刀次分批落地）：
    spec.py             CodeVideoSpec 渲染契约（V4.44 ✓）
    security.py         HTML 过闸 / 路径 jail / 限额（V4.45 ✓）
    page_builder.py     合成时间线页面（纯函数；postMessage 时钟）（V4.45 ✓）
    render_host.py      渲染编排（V4.45）
    render_worker.py    沙箱子进程（V4.45）
    video_critic.py     视频域代理评分（V4.45）
    llm_html.py         LLM 生成镜头 HTML（V4.46）

**延迟导出**：本文件只导出 spec（纯标准库零依赖），渲染面模块
（V4.45 起）不在此处导入 —— 避免契约刀阶段拖入 PyQt6/ffmpeg 重依赖，
也让 _verify/check_code_video.py 能独立 import 本域做静态断言。
"""
from app.core.code_video.spec import (
    ALLOWED_FPS,
    CODE_VIDEO_JSON_SCHEMA,
    DEFAULT_MAX_CLIPS,
    DEFAULT_MAX_DURATION,
    FIT_MODES,
    MAX_CANVAS_H,
    MAX_CANVAS_W,
    SOURCE_PREFIXES,
    SPEC_VERSION,
    TEXT_KINDS,
    AssetEntry,
    CanvasSettings,
    CodeVideoSpec,
    QcSettings,
    SpecClip,
    SpecLimits,
    SpecLineage,
    SpecTrack,
    compile_spec,
    from_storyboard,
    validate_spec,
)

__all__ = [
    "ALLOWED_FPS",
    "CODE_VIDEO_JSON_SCHEMA",
    "DEFAULT_MAX_CLIPS",
    "DEFAULT_MAX_DURATION",
    "FIT_MODES",
    "MAX_CANVAS_H",
    "MAX_CANVAS_W",
    "SOURCE_PREFIXES",
    "SPEC_VERSION",
    "TEXT_KINDS",
    "AssetEntry",
    "CanvasSettings",
    "CodeVideoSpec",
    "QcSettings",
    "SpecClip",
    "SpecLimits",
    "SpecLineage",
    "SpecTrack",
    "compile_spec",
    "from_storyboard",
    "validate_spec",
]
