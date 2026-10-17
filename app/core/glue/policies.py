# -*- coding: utf-8 -*-
"""三条主线世界观冲突的**显式策略** —— 用契约消解，不用重构。

【为什么是「策略」而不是「重构」】
三条主线的世界观冲突是结构性的（详见技术债报告 §1.3），
一次性统一等于把三条线全部重写 —— 会全面触碰冻结区，且单人带宽下必然烂尾。
本模块的做法是：**把冲突点变成可读、可测、可守卫的数据**，
让每条线保留自己的世界观，只在**交界处**遵守共同规则。

三处冲突与对策一一对应：

    冲突① 失败观：剪辑线要「失败可见」，生成线要「静默降级」，
          画布线要「诚实失败」 ⇒ 同一个 ``except`` 该不该 ``pass`` 各有答案。
          ⇒ 对策：``SILENT_EXCEPT_UI_WHITELIST`` + ``silent_except_verdict()``
             把项目已有的判定线变成**可执行数据**，守卫据此自动判定。

    冲突② 时间观：剪辑线用命令栈（帧级可撤销），画布线用图 undo/redo，
          生成线无历史 ⇒ 「画布改 → 回流时间线」的撤销语义一直没统一。
          ⇒ 对策：``TIMELINE_WRITE_ENTRYPOINTS`` 声明**唯一合法写入入口**，
             跨线写入必须落在这些入口上；不在清单里的直写一律报错。

    冲突③ 一致性观：剪辑线要求音画 ≈280ms 强对齐，生成线可降级出片
          ⇒ 降级产物可能破坏剪辑线的不变量。
          ⇒ 对策：``cross_lane_acceptance()`` —— 剪辑线默认只收「完整交付」，
             降级产物必须带显式 ack 才准入，且准入后自动打标可追溯。

【纯标准库】
"""
from __future__ import annotations

from typing import Any, Dict, Mapping, Optional, Tuple

from .schema import (
    DEGRADED_MAX,
    ORIGIN_CANVAS,
    ORIGIN_EDITOR,
    ORIGIN_GENERATOR,
)

# ===========================================================================
# 冲突① 失败观 —— 静默异常判定线（可执行化）
# ===========================================================================
# 项目既有判定线（MEMORY.md 不变量 #9）：
#   UI 绘制里的 `except: pass` 可接受；状态机/资源路径里的不可接受。
# 本表把那句话变成**可被守卫读取的数据**。

# 白名单：UI 绘制类 —— `pass` 可接受（不打日志也不报错）
SILENT_EXCEPT_UI_WHITELIST = (
    "app/modules/lego/clip_widget.py",
    "app/modules/lego/timeline_widget.py",
    "app/modules/lego/timeline_subwidgets.py",
    "app/modules/lego/timeline_ui.py",
    "app/modules/lego/nav_icons.py",
)

# 待整改：状态机 / 资源路径 —— `pass` 不可接受，须改 logger.debug(exc_info=True)
SILENT_EXCEPT_REVIEW_TARGETS = (
    # 状态机类（吞掉即任务卡死无痕迹）
    "app/modules/lego/editor_agent_runtime_mixin.py",
    "app/modules/lego/playback_shuttle.py",
    "app/core/canvas_agent_runtime.py",
    "app/core/project_agent_host.py",
    # 资源路径类（吞掉即"资源不存在"被伪装成"功能不支持"）
    "app/core/local_video_infer.py",
    "app/modules/lego/model_management.py",
    "app/core/ai/video_generation_client.py",
    "app/core/preview_manager.py",
)

# 冻结区内、暂不可改（必须先向用户申请解冻 zone 才能动）
SILENT_EXCEPT_FROZEN_PENDING = (
    # zone=clip-transform（整文件锁）
    "app/modules/lego/clip_transform.py",
    # zone=stage3d-core（整文件锁）
    "app/core/canvas_runtime.py",
)

# 有意降级、但缺 debug 日志（启动链基础设施加载失败不阻塞是设计意图）
SILENT_EXCEPT_INTENTIONAL_DEGRADE = (
    "app/main_qt6.py",
)

# UI 白名单的目录级兜底：路径里含这些片段也视为 UI 绘制
SILENT_EXCEPT_UI_HINTS = (
    "/ui/", "_panel.py", "_dialog.py", "_widget.py",
)

VERDICT_OK = "ok"                    # 白名单内，可接受
VERDICT_NEEDS_LOG = "needs_log"      # 状态机/资源路径，必须补日志
VERDICT_FROZEN = "frozen"            # 冻结区内，先解冻再改
VERDICT_UI_HEURISTIC = "ui_heuristic"  # 目录/文件名像 UI，按可接受处理


def silent_except_verdict(path: str) -> Tuple[str, str]:
    """判定某文件的 ``except: pass`` 属于哪一类。

    Args:
        path: 仓库相对路径（正斜杠）。

    Returns:
        ``(verdict, reason)``；verdict ∈ {ok, needs_log, frozen, ui_heuristic}。
    """
    p = (path or "").replace("\\", "/").lstrip("./")
    if p in SILENT_EXCEPT_UI_WHITELIST:
        return VERDICT_OK, "在 UI 绘制白名单内"
    if p in SILENT_EXCEPT_FROZEN_PENDING:
        return VERDICT_FROZEN, "冻结区文件，需先申请解冻对应 zone"
    if p in SILENT_EXCEPT_INTENTIONAL_DEGRADE:
        return VERDICT_NEEDS_LOG, "有意降级：保留语义但须补 logger.debug"
    if p in SILENT_EXCEPT_REVIEW_TARGETS:
        return VERDICT_NEEDS_LOG, "状态机/资源路径：pass 不可接受"
    if any(h in p for h in SILENT_EXCEPT_UI_HINTS):
        return VERDICT_UI_HEURISTIC, "文件名/目录像 UI 层，按可接受处理"
    return VERDICT_NEEDS_LOG, "未登记：默认按不可接受（状态机/资源路径）"


# ===========================================================================
# 冲突② 时间观 —— 时间线写入的唯一合法入口
# ===========================================================================
# 剪辑线的真相源是 ``EditorModule._clips``。跨线写入若不收敛到这几个入口，
# 撤销栈就会漏记，从而产生「画布改了、Ctrl+Z 撤不回」的经典错位。
TIMELINE_WRITE_ENTRYPOINTS = (
    # Agent 侧整段原子替换（内部持 _clips_lock）
    ("app/modules/lego/editor_module.py", "agent_replace_timeline_clips"),
    # 命令栈入口（撤销/重做的唯一记账点）
    ("app/modules/lego/editor_module.py", "_apply_action"),
    # 逐片新增（内部持锁 + 记账）
    ("app/modules/lego/editor_module.py", "_add_clip_to_timeline"),
    # 批量新增
    ("app/modules/lego/editor_module.py", "batch_add_clips"),
    # 删除
    ("app/modules/lego/editor_module.py", "_delete_clip"),
    # 桥接层写入器（由 EditorModule 注册，见 :594）
    ("app/core/canvas_bridge.py", "set_clips_writer"),
    # 时间线真相源 store 的结构写入 API（2026-10-18 解冻切换·刀1）：
    # EditorModule._timeline_store 收拢后，结构变更唯一合法入口
    ("app/core/timeline_store.py", "add"),
    ("app/core/timeline_store.py", "remove_by_id"),
    ("app/core/timeline_store.py", "replace_all"),
    ("app/core/timeline_store.py", "clear"),
    # 字段级写入唯一合法入口（2026-10-18 OTIO 迁移·刀4）：
    # 存量散落的 clip["k"]= 直写逐步改走这两个 API（棘轮守卫
    # _verify/check_timeline_write_surface.py 只减不增）
    ("app/core/timeline_store.py", "set_fields"),
    ("app/core/timeline_store.py", "update_where"),
)

# 允许出现 ``self._clips = ...`` 整段赋值的文件（其余的整段赋值即视为绕过入口）
TIMELINE_ASSIGN_ALLOWED = (
    "app/modules/lego/editor_module.py",
)


def is_declared_timeline_writer(path: str, symbol: str = "") -> bool:
    """该 (文件, 符号) 是否是声明过的时间线写入入口。"""
    p = (path or "").replace("\\", "/").lstrip("./")
    if not symbol:
        return any(p == f for f, _ in TIMELINE_WRITE_ENTRYPOINTS)
    return any(p == f and symbol == s for f, s in TIMELINE_WRITE_ENTRYPOINTS)


def may_assign_clips_wholesale(path: str) -> bool:
    """该文件是否允许对 ``self._clips`` 做整段赋值（必须持锁）。"""
    return (path or "").replace("\\", "/").lstrip("./") in TIMELINE_ASSIGN_ALLOWED


# ===========================================================================
# 冲突③ 一致性观 —— 跨线准入策略
# ===========================================================================
# 剪辑线不变量：音画对齐 ≈280ms（冻结区）、每片有可撤销记录。
# 生成线允许降级（六级），降级产物进剪辑线可能破坏上述不变量。
# 策略：**默认只收完整交付；降级产物须显式声明"我知道它降级了"才准入。**

ACCEPT = "accept"                    # 直接准入
ACCEPT_WITH_FLAG = "accept_flagged"  # 准入但打降级标（可追溯、可筛选）
REJECT = "reject"                    # 拒绝

# 准入阈值：degraded 超过此值一律拒绝（0 = 只收完整交付）
ACCEPT_DEGRADED_MAX = 0

# 显式确认字段名：调用方填 True 表示"接受降级产物"
ACK_FIELD = "degraded_ack"

# 准入后自动打标的字段名（写进 clip，供后续筛选/回滚）
FLAG_FIELD = "glue_degraded"


def cross_lane_acceptance(
    provenance: Mapping[str, Any],
    *,
    ack: Optional[bool] = None,
    max_degraded: int = ACCEPT_DEGRADED_MAX,
) -> Tuple[str, str]:
    """判定一条跨线产物能否进入剪辑线。

    Args:
        provenance: 溯源字典（含 origin / degraded / lane）。
        ack:        显式确认（None = 从 provenance 的 ACK_FIELD 读）。
        max_degraded: 可接受的最高降级级别。

    Returns:
        ``(verdict, reason)``；verdict ∈ {accept, accept_flagged, reject}。
    """
    env = dict(provenance or {})
    try:
        deg = int(env.get("degraded", 0) or 0)
    except (TypeError, ValueError):
        return REJECT, "degraded 非法，拒绝（无法判定瑕疵程度）"
    deg = max(0, min(DEGRADED_MAX, deg))

    origin = str(env.get("origin") or ORIGIN_EDITOR)
    if ack is None:
        ack = bool(env.get(ACK_FIELD, False))

    if deg == 0:
        return ACCEPT, "完整交付（degraded=0）"
    if deg > max_degraded and not ack:
        return REJECT, ("降级级别 %d > 容许 %d，且未显式确认"
                        "（需 %s=True）" % (deg, max_degraded, ACK_FIELD))
    if origin == ORIGIN_GENERATOR and deg >= 3:
        return ACCEPT_WITH_FLAG, ("生成线降级 %d（≥3 功能降级）——"
                                  "准入但打标，剪辑线需知悉" % deg)
    return ACCEPT_WITH_FLAG, "降级 %d 已确认，准入并打标" % deg


def acceptance_flag(provenance: Mapping[str, Any]) -> Dict[str, Any]:
    """准入后要写进 clip 的降级标记（供筛选与回滚）。"""
    env = dict(provenance or {})
    return {
        FLAG_FIELD: int(env.get("degraded", 0) or 0),
        "glue_origin": str(env.get("origin") or ""),
        "glue_lane": str(env.get("lane") or ""),
    }


# ===========================================================================
# 轨 → 模块归属（四条专注轨资源配比的落地映射，供守卫归类统计用）
# ===========================================================================
LANE_BY_MODULE: Dict[str, str] = {
    "app/modules/lego/editor": "N",
    "app/modules/lego/timeline": "N",
    "app/modules/lego/clip": "N",
    "app/core/editor_scheduler.py": "N",
    "app/core/preview_manager.py": "N",
    "app/core/canvas": "P",
    "vendor/shiguang-canvas": "P",
    "vendor/packages/libtv": "P",  # P0-1 抽包 Phase 1：画布真源 @shiguang/libtv
    "app/modules/lego/character": "P",
    "app/core/agent": "A",
    "app/core/capability": "A",
    "app/core/project_agent_host.py": "A",
    "app/core/ai/character_anchor.py": "D",
    "app/core/ai/tts_guard.py": "D",
    "app/modules/lego/director_skill.py": "D",
}


def lane_of(path: str) -> str:
    """按最长前缀匹配推断文件归属轨；未登记返回 '?'。"""
    p = (path or "").replace("\\", "/").lstrip("./")
    best, best_len = "?", 0
    for pref, lane in LANE_BY_MODULE.items():
        if p.startswith(pref) and len(pref) > best_len:
            best, best_len = lane, len(pref)
    return best


def policy_snapshot() -> Dict[str, Any]:
    """当前策略快照（供守卫 `--list` 输出与文档核对）。"""
    return {
        "silent_except_ui_whitelist": list(SILENT_EXCEPT_UI_WHITELIST),
        "silent_except_review_targets": list(SILENT_EXCEPT_REVIEW_TARGETS),
        "silent_except_frozen_pending": list(SILENT_EXCEPT_FROZEN_PENDING),
        "timeline_write_entrypoints": [list(x) for x in TIMELINE_WRITE_ENTRYPOINTS],
        "accept_degraded_max": ACCEPT_DEGRADED_MAX,
        "ack_field": ACK_FIELD,
        "flag_field": FLAG_FIELD,
    }
