# -*- coding: utf-8 -*-
"""粘合层共享数据模型 —— 三层交汇处的唯一契约。

【为什么需要这个包】
系统有三条世界观不同的主线：
  ① 剪辑线（真相源 ``EditorModule._clips``：绝对时间轴、帧级可撤销、强一致性）
  ② 生成线（provider 池 + 影子价格：无时间、整段原子、可降级）
  ③ 画布线（画布 store：图结构、可 undo/redo、诚实失败）

三者原本靠**散落各处的字段字面量**互相看见：
``canvas_node_id`` / ``canvas_kind`` / ``canvas_title`` 在三处硬编码，
没有 schema 版本、没有校验、没有溯源。任一处的字段改名都会静默失效。

本包把它们**收拢为单一来源 + 加版本 + 加校验 + 加溯源**，
是「粘合层契约」而非「第四套系统」：

  不做什么：不重建这三条线、不改它们的真相源、不搬动它们的状态。
  只做什么：给它们之间的每一次跨线传输一个**共同的形状与出处**。

【设计铁律】
1. **字段名保持原样**。``canvas_node_id`` 等名字被前端与已有工程文件依赖，
   改名＝破坏兼容。契约层的价值在「收拢 + 校验」，不在「重命名」。
2. **纯标准库**。本包不 import 任何项目内模块、不 import PyQt6/torch，
   因此守卫脚本与单测可以独立导入，不触发 ``import app`` 链（见项目不变量 #10）。
3. **只新增不改行为**。现有调用点继续工作；契约层以「包装 + 校验」方式接入。

参见 ``docs/_reports/2026-09-25-项目本质与技术债分析及优化方案.md``。
"""

from .schema import (  # noqa: F401
    GLUE_SCHEMA_VERSION,
    LINK_KEYS,
    EDITOR_TO_CANVAS_KEYS,
    CANVAS_TO_EDITOR_KEYS,
    CLIP_ROW_KEYS,
    ORIGIN_EDITOR,
    ORIGIN_CANVAS,
    ORIGIN_GENERATOR,
    ORIGINS,
    LANES,
    GlueProvenance,
    make_provenance,
)
from .convert import (  # noqa: F401
    clip_to_glue,
    glue_to_outbox,
    canvas_payload_to_glue,
    glue_to_clip_patch,
    glue_to_clip_row,
)
from .validate import (  # noqa: F401
    GlueIssue,
    validate_envelope,
    validate_clip_row,
    validate_canvas_payload,
)
from .policies import (  # noqa: F401
    SILENT_EXCEPT_UI_WHITELIST,
    SILENT_EXCEPT_REVIEW_TARGETS,
    SILENT_EXCEPT_FROZEN_PENDING,
    SILENT_EXCEPT_INTENTIONAL_DEGRADE,
    silent_except_verdict,
    TIMELINE_WRITE_ENTRYPOINTS,
    is_declared_timeline_writer,
    may_assign_clips_wholesale,
    ACCEPT_DEGRADED_MAX,
    ACCEPT,
    ACCEPT_WITH_FLAG,
    REJECT,
    ACK_FIELD,
    FLAG_FIELD,
    cross_lane_acceptance,
    acceptance_flag,
    LANE_BY_MODULE,
    lane_of,
    policy_snapshot,
)
from .schema import canonical_key, empty_envelope  # noqa: F401

__all__ = [
    "GLUE_SCHEMA_VERSION", "LINK_KEYS", "EDITOR_TO_CANVAS_KEYS",
    "CANVAS_TO_EDITOR_KEYS", "CLIP_ROW_KEYS", "FIELD_ALIASES",
    "ORIGIN_EDITOR", "ORIGIN_CANVAS", "ORIGIN_GENERATOR", "ORIGINS", "LANES",
    "GlueProvenance", "make_provenance", "canonical_key", "empty_envelope",
    "clip_to_glue", "glue_to_outbox", "canvas_payload_to_glue",
    "glue_to_clip_patch", "glue_to_clip_row", "clip_rows",
    "normalize_payload_keys",
    "GlueIssue", "validate_envelope", "validate_clip_row", "validate_canvas_payload",
    "summarize", "has_blocking",
    "SILENT_EXCEPT_UI_WHITELIST", "SILENT_EXCEPT_REVIEW_TARGETS",
    "SILENT_EXCEPT_FROZEN_PENDING", "SILENT_EXCEPT_INTENTIONAL_DEGRADE",
    "silent_except_verdict",
    "TIMELINE_WRITE_ENTRYPOINTS", "is_declared_timeline_writer",
    "may_assign_clips_wholesale",
    "ACCEPT_DEGRADED_MAX", "ACCEPT", "ACCEPT_WITH_FLAG", "REJECT",
    "ACK_FIELD", "FLAG_FIELD", "cross_lane_acceptance", "acceptance_flag",
    "LANE_BY_MODULE", "lane_of", "policy_snapshot",
]
