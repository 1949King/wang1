# -*- coding: utf-8 -*-
"""粘合层校验 —— 在桥边界给跨线传输做体检。

【为什么在「桥边界」校验】
三条主线各自内部怎么表示，契约层不管（尊重原创性与既有实现）。
但**每一次跨线**都必须过这里 —— 因为跨线是唯一「三线互相污染」的入口。
桥边界（``app/core/canvas_server.py`` 的 ``/ingest`` 与 ``/host/timeline-snapshot``）
不在冻结区，因此可以在这里加约束而**不动前端一行代码**。

【分级策略（不破坏功能）】
    blocking=False（默认）：只产出 issue，由调用方记日志。→ 第一阶段用这个。
    blocking=True         ：调用方据此拒绝载荷（用于日后收紧）。
本模块自身不抛异常、不记日志，保持纯函数可测。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional, Sequence

from .schema import (
    CANVAS_TO_EDITOR_KEYS,
    CLIP_ROW_KEYS,
    DEGRADED_MAX,
    ENVELOPE_FIELD,
    ENVELOPE_REQUIRED,
    GLUE_SCHEMA_VERSION,
    LANES,
    ORIGINS,
)

# 严重度
SEV_ERROR = "error"    # 契约被破坏（字段缺失/类型错/版本不认）
SEV_WARN = "warn"      # 可疑但可容忍（旧版载荷、别名键、溯源缺省）
SEV_INFO = "info"      # 提示（可选字段未给）


@dataclass(frozen=True)
class GlueIssue:
    """一条校验发现。"""

    severity: str
    code: str
    message: str
    field: str = ""
    blocking: bool = False

    def as_dict(self) -> Dict[str, Any]:
        return {
            "severity": self.severity,
            "code": self.code,
            "message": self.message,
            "field": self.field,
            "blocking": self.blocking,
        }

    def __str__(self) -> str:
        return "[%s/%s] %s%s" % (
            self.severity, self.code, self.message,
            ("（字段 %s）" % self.field) if self.field else "",
        )


def _mk(severity: str, code: str, message: str, field: str = "",
        blocking: bool = False) -> GlueIssue:
    return GlueIssue(severity, code, message, field, blocking)


def _try_float(v: Any) -> Optional[float]:
    """宽松浮点转换；不可转换返回 None。

    刻意**不**用 ``try/except + pass``：本包是纯校验层，
    自己必须遵守项目「状态机/资源路径不得静默吞异常」的判定线，
    这里用显式返回 None 表达「不是数值」比吞异常更清楚。
    """
    if v is None or isinstance(v, bool):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# ① 信封校验：任何跨线传输的出身证明
# ---------------------------------------------------------------------------
def validate_envelope(
    payload: Mapping[str, Any],
    *,
    expect_schema: Optional[int] = None,
    require: bool = False,
) -> List[GlueIssue]:
    """校验载荷中的 ``glue`` 信封。

    Args:
        payload:       跨线载荷（dict）。
        expect_schema: 期望的契约版本；None = 只做合法性检查。
        require:       True = 信封缺失即报 error（用于新路径）；
                       False = 缺失仅 warn（兼容历史载荷，第一阶段用这个）。
    """
    issues: List[GlueIssue] = []
    if not isinstance(payload, Mapping):
        issues.append(_mk(SEV_ERROR, "payload.not_mapping", "载荷不是 Mapping"))
        return issues

    env = payload.get(ENVELOPE_FIELD)
    if not isinstance(env, Mapping):
        issues.append(_mk(
            SEV_ERROR if require else SEV_WARN,
            "envelope.missing",
            "缺 glue 信封（无法判定出处/降级/契约版本）",
            ENVELOPE_FIELD,
        ))
        return issues

    for key in ENVELOPE_REQUIRED:
        if key not in env:
            issues.append(_mk(SEV_ERROR, "envelope.field_missing",
                              "信封缺必填字段", key))

    origin = env.get("origin")
    if origin is not None and origin not in ORIGINS:
        issues.append(_mk(SEV_ERROR, "envelope.bad_origin",
                          "origin 非法（应为 %s）" % (ORIGINS,), "origin"))

    lane = env.get("lane")
    if lane is not None and lane not in LANES:
        issues.append(_mk(SEV_ERROR, "envelope.bad_lane",
                          "lane 非法（应为 %s）" % (LANES,), "lane"))

    deg = env.get("degraded")
    if deg is not None:
        try:
            d = int(deg)
            if d < 0 or d > DEGRADED_MAX:
                issues.append(_mk(SEV_ERROR, "envelope.bad_degraded",
                                  "degraded 越界（0..%d）" % DEGRADED_MAX, "degraded"))
        except (TypeError, ValueError):
            issues.append(_mk(SEV_ERROR, "envelope.bad_degraded",
                              "degraded 非整数", "degraded"))

    ver = env.get("schema")
    if ver is not None:
        try:
            v = int(ver)
        except (TypeError, ValueError):
            v = -1
        if v != GLUE_SCHEMA_VERSION:
            issues.append(_mk(SEV_WARN, "envelope.schema_mismatch",
                              "契约版本 %s ≠ 当前 %d（需迁移或升级契约）"
                              % (ver, GLUE_SCHEMA_VERSION), "schema"))
        if expect_schema is not None and v != int(expect_schema):
            issues.append(_mk(SEV_ERROR, "envelope.schema_unexpected",
                              "契约版本 %s ≠ 期望 %s" % (ver, expect_schema), "schema"))
    return issues


# ---------------------------------------------------------------------------
# ② 画布 → 剪辑 载荷校验
# ---------------------------------------------------------------------------
def validate_canvas_payload(payload: Mapping[str, Any],
                            *, require_identity: bool = True) -> List[GlueIssue]:
    """校验画布/生成线的入轨载荷。

    Args:
        require_identity: True = 必须带身份（``canvas_node_id``）；False = 允许匿名入轨
                          （手工拖拽素材进时间线就是匿名的，必须放行）。
    """
    issues: List[GlueIssue] = []
    if not isinstance(payload, Mapping):
        issues.append(_mk(SEV_ERROR, "payload.not_mapping", "载荷不是 Mapping"))
        return issues

    unknown = [k for k in payload.keys() if k not in CANVAS_TO_EDITOR_KEYS
               and k not in (ENVELOPE_FIELD, "node_id", "kind", "file_path",
                             "url", "name", "title")]
    # 未知键只提示：画布可以带扩展字段，不能拦
    for k in unknown[:5]:
        issues.append(_mk(SEV_INFO, "payload.extra_key",
                          "载荷含契约外字段（允许，仅提示）", str(k)))

    if require_identity:
        has_id = bool(payload.get("canvas_node_id") or payload.get("node_id"))
        if not has_id:
            issues.append(_mk(SEV_WARN, "payload.no_identity",
                              "无 canvas_node_id ⇒ 入轨后无法回溯到画布节点",
                              "canvas_node_id"))
    # 别名键提示（历史路径兼容，不报错）
    if "node_id" in payload and "canvas_node_id" not in payload:
        issues.append(_mk(SEV_WARN, "payload.alias_key",
                          "使用别名 node_id（规范名 canvas_node_id）", "node_id"))
    if "kind" in payload and "canvas_kind" not in payload:
        issues.append(_mk(SEV_WARN, "payload.alias_key",
                          "使用别名 kind（规范名 canvas_kind）", "kind"))
    return issues


# ---------------------------------------------------------------------------
# ③ 时间线快照行校验
# ---------------------------------------------------------------------------
def validate_clip_row(row: Mapping[str, Any]) -> List[GlueIssue]:
    """校验给画布/Agent 看的快照行。"""
    issues: List[GlueIssue] = []
    if not isinstance(row, Mapping):
        issues.append(_mk(SEV_ERROR, "row.not_mapping", "快照行不是 Mapping"))
        return issues

    missing = [k for k in ("id", "start_time", "duration") if k not in row]
    for k in missing:
        issues.append(_mk(SEV_ERROR, "row.field_missing", "快照行缺字段", k))

    for k in ("start_time", "duration"):
        if k in row:
            try:
                float(row[k])
            except (TypeError, ValueError):
                issues.append(_mk(SEV_ERROR, "row.bad_number",
                                  "快照行数值不可转换", k))
    # end_time 一致性（不阻断，一致性漂移要能看见）
    et, st, du = (_try_float(row.get("end_time")),
                  _try_float(row.get("start_time")),
                  _try_float(row.get("duration")))
    if None not in (et, st, du) and abs(et - (st + du)) > 1e-6:
        issues.append(_mk(SEV_WARN, "row.end_time_mismatch",
                          "end_time ≠ start_time + duration", "end_time"))
    return issues


# ---------------------------------------------------------------------------
# ④ 批量校验辅助
# ---------------------------------------------------------------------------
def summarize(issues: Sequence[GlueIssue]) -> Dict[str, int]:
    """按严重度汇总（供桥边界一行日志）。"""
    out = {SEV_ERROR: 0, SEV_WARN: 0, SEV_INFO: 0}
    for it in issues:
        out[it.severity] = out.get(it.severity, 0) + 1
    return out


def has_blocking(issues: Sequence[GlueIssue]) -> bool:
    """是否存在阻断级问题（第一批不改行为，仅用于告警升级）。"""
    return any(i.blocking or i.severity == SEV_ERROR for i in issues)
