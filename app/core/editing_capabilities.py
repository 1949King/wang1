"""
编辑能力统一入口 (EditingCapabilities)
========================================
对标 Shotcut/OpenShot 的所有剪辑能力的统一访问接口。

通过本模块可访问:
- 快捷键: shortcut_manager
- 自动备份: auto_backup_manager
- 速度曲线: SpeedRamp, reverse_clip, freeze_frame
- 自动更新: update_manager
- 转场: get_all_transitions
- 音频波形: waveform_generator
- LUT: lut_loader
- 逐帧导航: frame_navigator
- 遮罩: mask_manager
- 标题模板: get_all_templates
- 音频示波器: audio_scope_manager
- 国际化: i18n
- 章节标记: chapter_marker_manager
- 时间轴 DSL: Timeline
"""
from app.core.shortcut_manager import shortcut_manager, ShortcutEditorDialog
from app.core.auto_backup import auto_backup_manager, AutoBackupManager
from app.core.speed_ramping import (
    SpeedRamp, SpeedKeyframe, SpeedEasing,
    reverse_clip_ffmpeg, freeze_frame_ffmpeg, apply_speed_ramp_ffmpeg,
    SPEED_PRESETS,
)
from app.core.update_manager import update_manager, UpdateManager, UpdateInfo
from app.core.transitions import (
    TRANSITIONS, TransitionDef, TransitionCategory,
    get_all_transitions, get_transitions_by_category, get_transition,
    build_transition_filter, TRANSITION_COUNT,
)
from app.core.waveform_generator import waveform_generator, WaveformData
from app.core.lut_loader import lut_loader, LUT3D
from app.core.frame_navigator import (
    frame_navigator, FrameNavigator,
    seconds_to_timecode, timecode_to_seconds, frames_to_timecode,
)
from app.core.mask_system import (
    mask_manager, Mask, MaskShape, MaskKeyframe, MASK_PRESETS,
)
from app.core.title_templates import (
    TITLE_TEMPLATES, TitleTemplate, TitleCategory,
    get_all_templates, get_template, build_drawtext, TEMPLATE_COUNT,
)
from app.core.audio_scopes import (
    audio_scope_manager, AudioScopeManager,
    WaveformScope, SpectrumScope, LoudnessScope,
    PeakMeterScope, PhaseVectorScope,
)
from app.core.i18n import i18n, I18n
from app.core.chapter_markers import (
    chapter_marker_manager, ChapterMarker, ChapterMarkerManager,
)
from app.core.timeline_dsl import Timeline, validate_timeline, convert_from_v1


import logging
logger = logging.getLogger("AI短剧编辑器.core.editing_capabilities")

# 能力摘要
CAPABILITY_SUMMARY = {
    "ripple_edit": True,
    "ripple_delete": True,
    "insert_overwrite": True,
    "slip_slide": True,
    "shortcut_system": True,
    "shortcut_editor": True,
    "auto_backup": True,
    "auto_recovery": True,
    "speed_ramping": True,
    "freeze_frame": True,
    "reverse_clip": True,
    "auto_update": True,
    "transitions": TRANSITION_COUNT,
    "audio_waveform": True,
    "lut_support": True,
    "lut_presets": 4,
    "frame_navigation": True,
    "mask_system": True,
    "mask_shapes": 5,
    "title_templates": TEMPLATE_COUNT,
    "audio_scopes": 5,
    "i18n": True,
    "locales": 2,
    "chapter_markers": True,
    "chapter_export_youtube": True,
    "chapter_export_edl": True,
    "chapter_export_csv": True,
    "chapter_export_ffmetadata": True,
    "timeline_dsl": True,
}


def get_capability_report() -> dict:
    """获取能力报告"""
    return {
        "summary": CAPABILITY_SUMMARY,
        "stats": {
            "transitions": TRANSITION_COUNT,
            "title_templates": TEMPLATE_COUNT,
            "locales": len(i18n.available_locales()),
            "shortcuts": len(shortcut_manager.get_all_bindings()),
            "mask_presets": len(MASK_PRESETS),
        }
    }


def print_capability_report():
    """打印能力报告 (CLI)"""
    report = get_capability_report()
    logger.info('=' * 60)
    logger.info('  AI 短剧编辑器 能力清单 (对标 Shotcut/OpenShot)')
    logger.info('=' * 60)
    logger.info(f"  转场数量:   {report['stats']['transitions']} 种")
    logger.info(f"  标题模板:   {report['stats']['title_templates']} 种")
    logger.info(f"  快捷键:     {report['stats']['shortcuts']} 个")
    logger.info(f"  遮罩预设:   {report['stats']['mask_presets']} 种")
    logger.info(f"  语言:       {report['stats']['locales']} 种")
    logger.info('=' * 60)
    logger.info('  ✓ Ripple 编辑 (insert/overwrite/lift/ripple_delete)')
    logger.info('  ✓ Slip/Slide 编辑')
    logger.info('  ✓ 快捷键系统 (可视化编辑 + 导入导出)')
    logger.info('  ✓ 自动备份 (定时 + 多版本 + 崩溃恢复)')
    logger.info('  ✓ Speed Ramping (速度曲线 + 关键帧 + 5 种预设)')
    logger.info('  ✓ 冻结帧 + 倒放')
    logger.info('  ✓ 自动更新 (24h 周期检查)')
    logger.info('  ✓ 音频波形生成 (PyAV 提取 + 缓存)')
    logger.info('  ✓ LUT 加载 (.cube/.3dl + 内置预设)')
    logger.info('  ✓ 逐帧导航 (时间码/帧号互转)')
    logger.info('  ✓ 遮罩系统 (5 种形状 + 文件 + 色度键)')
    logger.info('  ✓ 标题模板 (短剧/电影/动画/卡拉OK)')
    logger.info('  ✓ 音频示波器 (波形/频谱/响度/峰值/相位)')
    logger.info('  ✓ 国际化 i18n (中/英 + 用户扩展)')
    logger.info('  ✓ 章节标记 (YouTube/EDL 导出)')
    logger.info('  ✓ 时间轴 JSON-DSL (前后端数据契约)')
    logger.info('=' * 60)
