"""
导演分镜落时间线引擎 —— LibTV 对标补强 刀2b（2026-10-12）
=====================================================
背景：对标核对发现「导演结果落时间线」只差最后一跳 ——
`DirectorSkill._apply_to_timeline` 的落地逻辑（分镜 → 素材循环映射 →
EventBus MATERIAL_TO_TIMELINE）早已存在且有 4 场景测试
（`_verify/test_director_timeline_apply.py`），但只有跑整条导演技能
（给 source_dir）才触发；Agent 拆完分镜（pipeline.director_breakdown）
之后没有独立能力把结果送进时间线。

本模块把落地核心抽成**单一真源**：
  - DirectorSkill 步骤 5 改为薄委托（行为零变化，同测试回归）
  - 新 Agent 能力 `pipeline.director_apply_timeline` 直接调用
  - 与画布回流（canvas_bridge.push_to_timeline）同一条总线事件

机制：EventBus ``MATERIAL_TO_TIMELINE`` 批量载荷 —— ``editor_module.py:582``
订阅 ``_on_material_dropped`` 批量分支，最终落到 ``EditorModule._clips``
（时间线真相源，落轨持锁纪律在订阅方）。

如实边界：
  - 片段按**素材原始时长**排布；分镜表的精确裁剪点仍需二次调整
    （可用「裁剪片段/重锚片段」能力）。
  - 剪辑模块未打开（无订阅者）时不发事件（否则静默丢失），报告如实标注。
"""
from __future__ import annotations

import logging
import os
from typing import Any, Dict, List

logger = logging.getLogger(__name__)

# 视频扩展名白名单（音频不进时间线片段，避免把 BGM 当成镜头素材）
MEDIA_EXTS = (".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v", ".ts",
              ".flv", ".wmv", ".mpg", ".mpeg")


def _bus():
    """(EventBus 单例, MATERIAL_TO_TIMELINE 事件成员) —— 注意返回的是**成员**不是类。"""
    from app.modules.lego.core import EventBus, EventType
    return EventBus.get_instance(), EventType.MATERIAL_TO_TIMELINE


def collect_media_files(source_dir: str, cap: int = 200) -> List[str]:
    """递归收集素材目录里的视频文件（按路径排序，数量封顶）。"""
    found: List[str] = []
    for root, _dirs, files in os.walk(source_dir):
        for f in sorted(files):
            if os.path.splitext(f)[1].lower() in MEDIA_EXTS:
                found.append(os.path.join(root, f))
                if len(found) >= cap:
                    return found
    return found


def has_timeline_listener() -> bool:
    """剪辑时间线是否在听（MATERIAL_TO_TIMELINE 有无订阅者）。"""
    bus, event_type = _bus()
    listeners = getattr(bus, "_listeners", {}).get(event_type, []) or []
    return bool(listeners)


def apply_storyboard_to_timeline(
    source_dir: str,
    storyboard: List[Dict[str, Any]],
    source_tag: str = "director_skill",
) -> Dict[str, Any]:
    """把素材按分镜顺序加入剪辑时间线。**绝不抛异常**，返回诚实报告。

    返回::

        {"applied", "reason?", "clips"?, "files_used"?, "total_files_found"?}
    """
    if not os.path.isdir(source_dir or ""):
        return {"applied": False, "reason": f"素材目录不存在: {source_dir}"}

    files = collect_media_files(source_dir)
    if not files:
        return {"applied": False,
                "reason": f"素材目录中没有可用视频文件: {source_dir}"}

    if not has_timeline_listener():
        return {"applied": False,
                "reason": "剪辑模块未打开（时间线无 MATERIAL_TO_TIMELINE 订阅者）"}

    # 分镜 → 素材循环映射（素材少于分镜数时循环复用）
    clips_payload = []
    for i, shot in enumerate(storyboard or []):
        f = files[i % len(files)]
        desc = str(shot.get("description") or "").strip()
        clips_payload.append({
            "path": f,
            "title": f"镜{shot.get('id', i + 1)} {desc[:12]}".strip(),
        })

    bus, event_type = _bus()
    try:
        bus.emit(
            event_type,
            {"clips": clips_payload, "source": source_tag},
            source=source_tag,
        )
    except Exception as e:
        logger.debug("[director_timeline] 发送时间线事件失败", exc_info=True)
        return {"applied": False, "reason": f"发送时间线事件失败: {e}"}

    return {
        "applied": True,
        "clips": len(clips_payload),
        "files_used": min(len(files), len(clips_payload)),
        "total_files_found": len(files),
        "note": f"已按分镜顺序加入 {len(clips_payload)} 段素材（素材原始时长）",
    }
