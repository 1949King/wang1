# -*- coding: utf-8 -*-
"""粘合层 schema —— 字段名与领域模型的**单一事实来源**。

【范围】
本模块只放「三层交汇处」的字段与模型，不放任何一条主线的私有字段。
判据：一个字段若只被单条线使用 → 留在那条线；若被两条以上线传递 → 进本模块。

【纯标准库】本模块零项目依赖，可被守卫脚本独立导入。
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any, Dict, Mapping, Optional

# ---------------------------------------------------------------------------
# 1. schema 版本
# ---------------------------------------------------------------------------
# 每次「跨线字段集合」发生增删（不是每次改代码）就 +1。
# 守卫 _verify/check_glue_contract.py 会核对本常量与文档登记值一致。
# 2026-10-17：LINK_KEYS 增「generation」生成参数血缘块 ⇒ 1 → 2。
GLUE_SCHEMA_VERSION = 2

# ---------------------------------------------------------------------------
# 2. 跨线字段集合（单一来源）
# ---------------------------------------------------------------------------
# ① 剪辑线 → 画布线：盖在 clip 上的关联字段
#    （此前散落在 editor_canvas_link.LINK_KEYS 与 canvas_server.py 各处的字面量）
#    "generation" 为嵌套 dict（生成参数血缘块），语义与字符串键不同：
#    载荷携带且非空 ⇒ 整块替换；缺省 / 空块 ⇒ 不覆盖已有（见 normalize_generation）。
LINK_KEYS = ("canvas_node_id", "canvas_kind", "canvas_title", "generation")

# ①-b 生成参数血缘块的白名单键（画布节点 data → clip["generation"]）。
#     缺键不写、非白名单键丢弃、非标量值丢弃 —— 绝不猜默认值。
GENERATION_KEYS = ("prompt", "seed", "model", "channel", "character_id", "reference")


def normalize_generation(raw: Any) -> Dict[str, Any]:
    """把任意来源的生成参数归一成血缘块：只收 GENERATION_KEYS、逐键清洗。

    · seed → int（不可转换即丢弃）；其余键 → 非空字符串（bool/数值转 str）。
    · 非 Mapping 一律返回 {}（诚实：不造记录）。
    """
    if not isinstance(raw, Mapping):
        return {}
    out: Dict[str, Any] = {}
    for key in GENERATION_KEYS:
        if key not in raw:
            continue
        val = raw[key]
        if val is None or val == "":
            continue
        if key == "seed":
            try:
                out[key] = int(val)
            except (TypeError, ValueError):
                continue
            continue
        if isinstance(val, (str, int, float, bool)):
            text = val if isinstance(val, str) else str(val)
            if text:
                out[key] = text
    return out

# ② 剪辑线 → 画布 outbox：把 clip 身份告诉画布，供其自动落源节点
EDITOR_TO_CANVAS_KEYS = (
    "clip_id",
    "canvas_node_id",
    "kind",
    "in_point",
    "out_point",
    "start_time",
    "duration",
)

# ③ 画布线 → 剪辑线：画布产物入轨时携带的身份
#    注意同时接受「画布原生名」与「剪辑线别名」，兼容两条历史路径：
#    canvas_node_id/node_id、canvas_kind/kind 都出现过。
CANVAS_TO_EDITOR_KEYS = (
    "canvas_node_id",
    "canvas_kind",
    "title",
    "path",
    "type",
    "in_point",
    "out_point",
    "duration",
)

# ④ 时间线快照给画布/Agent 看的一行（不含大文件字节）
CLIP_ROW_KEYS = (
    "clip_index",
    "id",
    "name",
    "path",
    "type",
    "track",
    "start_time",
    "duration",
    "end_time",
    "in_point",
    "out_point",
    "canvas_node_id",
    "canvas_kind",
)

# 别名表：同一个语义在不同历史代码里的写法 → 规范名
# 契约层负责「收口」，不强制调用方立刻改名。
FIELD_ALIASES: Dict[str, str] = {
    "node_id": "canvas_node_id",
    "kind": "canvas_kind",
    "file_path": "path",
    "name": "title",
}

# ---------------------------------------------------------------------------
# 3. 三条主线的身份（origin）
# ---------------------------------------------------------------------------
ORIGIN_EDITOR = "editor"
ORIGIN_CANVAS = "canvas"
ORIGIN_GENERATOR = "generator"
ORIGINS = (ORIGIN_EDITOR, ORIGIN_CANVAS, ORIGIN_GENERATOR)

# ---------------------------------------------------------------------------
# 4. 四条专注轨（与 docs/现行技术文档.md §1.3 一致）
# ---------------------------------------------------------------------------
LANE_CLIP = "N"      # 剪辑
LANE_CANVAS = "P"    # 画布
LANE_AGENT = "A"     # Agent
LANE_DIGITAL = "D"   # 数字人
LANES = (LANE_CLIP, LANE_CANVAS, LANE_AGENT, LANE_DIGITAL)

# ---------------------------------------------------------------------------
# 5. 溯源（Provenance）—— 解决「三线互相看不见出处」的核心载体
# ---------------------------------------------------------------------------
# 每一条跨线传输都必须能回答四个问题：
#   谁造的（origin）· 属于哪条轨（lane）· 有没有降级（degraded）· 用的哪版契约（schema）
DEGRADED_MAX = 6     # 与 app/core/ai/degradation.py 的六级降级同阶


@dataclass(frozen=True)
class GlueProvenance:
    """跨线传输的出身证明。

    Attributes:
        origin:   产物由哪条主线产生（ORIGINS 之一）。
        lane:     归属专注轨（LANES 之一）。
        degraded: 降级级别 0..6；0 = 完整交付（fidelity 满分）。
        schema:   写入时的契约版本（GLUE_SCHEMA_VERSION）。
        note:     自由备注（如降级原因），进日志不进 UI。
    """

    origin: str = ORIGIN_EDITOR
    lane: str = LANE_CLIP
    degraded: int = 0
    schema: int = GLUE_SCHEMA_VERSION
    note: str = ""

    def as_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @property
    def is_pristine(self) -> bool:
        """是否「完整交付」—— 剪辑线默认只收 pristine 或无瑕疵声明的产物。"""
        return self.degraded == 0


def make_provenance(
    origin: str = ORIGIN_EDITOR,
    lane: str = LANE_CLIP,
    degraded: int = 0,
    note: str = "",
) -> GlueProvenance:
    """构造溯源的便捷入口（做参数归一与钳位，避免脏值流入）。"""
    o = origin if origin in ORIGINS else ORIGIN_EDITOR
    l = lane if lane in LANES else LANE_CLIP
    try:
        d = int(degraded)
    except (TypeError, ValueError):
        d = 0
    d = max(0, min(DEGRADED_MAX, d))
    return GlueProvenance(origin=o, lane=l, degraded=d, schema=GLUE_SCHEMA_VERSION,
                          note=str(note or ""))


# ---------------------------------------------------------------------------
# 6. 信封（Envelope）—— 跨线传输的统一外形
# ---------------------------------------------------------------------------
ENVELOPE_FIELD = "glue"          # 信封挂在载荷的哪个键下（可缺省，向后兼容）
ENVELOPE_REQUIRED = ("schema", "origin", "lane", "degraded")


def canonical_key(name: str) -> str:
    """把历史别名收敛到规范字段名；未知键原样返回。"""
    return FIELD_ALIASES.get(str(name), str(name))


def empty_envelope() -> Dict[str, Any]:
    """一个最小合法信封（供调用方按需填充）。"""
    return {
        "schema": GLUE_SCHEMA_VERSION,
        "origin": ORIGIN_EDITOR,
        "lane": LANE_CLIP,
        "degraded": 0,
        "note": "",
    }
