# -*- coding: utf-8 -*-
"""画布端口模型（后端镜像） —— 与前端 `vendor/packages/canvas-core/src/ports.ts` 同源

设计决策：**不做第二份表，而是直接解析前端的 TS 表**
-----------------------------------------------------
项目既有做法是「同一事实写多份 + 守卫比对」（如角色库 6 处）。但那是历史包袱，
新东西不该再背：本模块**直接读 `ports.ts` 并解析 `NODE_PORTS` / `PORT_COMPAT`**，
⇒ **漂移在构造上不可能发生**（只有一份表）。

为什么不放在前端算：执行前校验必须在后端做（前端可能被绕过/旧版缓存），
且 `canvas_workflow_runner` 需要它来「如实报告非法连接」。

降级纪律（重要）
----------------
解析失败时**绝不抛异常**，回退到「宽松表」（一切放行）+ 记 warning。
理由：端口校验是**增强**，不是主链路；解析失败不该阻断绘图/执行。
守卫 `_verify/check_port_model.py` 负责在 CI 阶段把「解析失败」暴露出来，
所以运行时降级不会让问题悄悄溜过去。

边界（不做的事）
----------------
- 不判审美、不判业务合法性（如「这个提示词合规吗」）——只判**类型能不能接**。
- 不管部署：前端仍然独立持有同一张表（由 `ports.ts` 提供）。
"""
from __future__ import annotations

import logging
import os
import re
from functools import lru_cache
from typing import Any, Dict, List, Tuple

logger = logging.getLogger(__name__)

UNBOUNDED = 99

# 主库真源路径（副库是副本，不读它——避免两份真源）
_TS_REL = os.path.join("vendor", "packages", "canvas-core", "src", "ports.ts")

# 宽松兜底：解析不出来时一切放行（不误拦用户）
_PERMISSIVE: Dict[str, Dict[str, Dict[str, int]]] = {}

_TABLE_LINE_RE = re.compile(
    r"^\s*(\w+):\s*\{\s*accepts:\s*\{([^}]*)\}\s*,\s*produces:\s*\{([^}]*)\}\s*\},?\s*$",
    re.M)
_PAIR_RE = re.compile(r"([A-Za-z_]\w*)\s*:\s*(\d+)")
_COMPAT_BLOCK_RE = re.compile(
    r"export\s+const\s+PORT_COMPAT[^=]*=\s*\{(.*?)\};", re.S)
_COMPAT_ITEM_RE = re.compile(r"(\w+)\s*:\s*\[([^\]]*)\]")


def project_root() -> str:
    """项目根（本文件在 app/core/ 下，上溯两层）。"""
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _ts_path() -> str:
    return os.path.join(project_root(), _TS_REL)


def _parse_pairs(raw: str) -> Dict[str, int]:
    return {k: int(v) for k, v in _PAIR_RE.findall(raw or "")}


@lru_cache(maxsize=1)
def _load() -> Tuple[Dict[str, Dict[str, Dict[str, int]]], Dict[str, List[str]], bool]:
    """解析 ports.ts。返回 (node_ports, port_compat, parsed_ok)。

    ⚠️ 结果被 lru_cache 缓存 —— 改了 ports.ts 需要重启进程（与其它模块的
    「启动时建索引」口径一致）。守卫脚本不走本缓存（它自己重新解析）。
    """
    path = _ts_path()
    try:
        with open(path, "r", encoding="utf-8") as f:
            src = f.read()
    except Exception:
        logger.warning("[canvas_port_model] 读不到 %s，回退宽松表", path, exc_info=True)
        return {}, {}, False

    ports: Dict[str, Dict[str, Dict[str, int]]] = {}
    for kind, acc, prod in _TABLE_LINE_RE.findall(src):
        ports[kind] = {"accepts": _parse_pairs(acc), "produces": _parse_pairs(prod)}

    compat: Dict[str, List[str]] = {}
    m = _COMPAT_BLOCK_RE.search(src)
    if m:
        for src_t, lst in _COMPAT_ITEM_RE.findall(m.group(1)):
            compat[src_t] = [x.strip().strip('"\'') for x in lst.split(",") if x.strip()]

    if not ports:
        logger.warning("[canvas_port_model] NODE_PORTS 解析为空（格式变了？），回退宽松表")
        return {}, compat, False
    return ports, compat, True


def node_ports() -> Dict[str, Dict[str, Dict[str, int]]]:
    return _load()[0]


def port_compat() -> Dict[str, List[str]]:
    return _load()[1]


def parse_ok() -> bool:
    return _load()[2]


def ports_of(kind: str) -> Dict[str, Dict[str, int]]:
    """取节点端口；未知 kind → 宽松（accepts/produces 皆 any）。"""
    return node_ports().get(kind) or {"accepts": {"any": UNBOUNDED}, "produces": {"any": 1}}


def edge_kind_for(source_kind: str, target_kind: str) -> str:
    """`data`（数据流，参与执行）或 `associate`（关联，仅组织）。编组相关一律 associate。"""
    if source_kind == "group" or target_kind == "group":
        return "associate"
    return "data"


def can_connect(source_kind: str, target_kind: str) -> Dict[str, Any]:
    """校验一条连接。返回 ``{ok, kind, via?, reason?}``。**纯函数、不抛异常。**"""
    kind = edge_kind_for(source_kind, target_kind)
    if kind == "associate":
        return {"ok": True, "kind": kind, "via": "any", "reason": "编组关联（不参与数据流）"}
    src = ports_of(source_kind)
    dst = ports_of(target_kind)
    compat = port_compat()
    # 任一侧是「通配」即放行：
    #  - target 接受 any（编组等容器）
    #  - source 产出 any（**未知 kind 的宽松兜底** —— 不误拦将来新增的节点类型）
    if int(dst["accepts"].get("any", 0)) > 0:
        return {"ok": True, "kind": kind, "via": "any"}
    if int(src["produces"].get("any", 0)) > 0:
        return {"ok": True, "kind": kind, "via": "any"}
    for t in src["produces"]:
        if t == "any":
            continue
        if int(dst["accepts"].get(t, 0)) > 0:
            return {"ok": True, "kind": kind, "via": t}
        for alt in compat.get(t, []):
            if int(dst["accepts"].get(alt, 0)) > 0:
                return {"ok": True, "kind": kind, "via": alt}
    outs = "/".join(t for t in src["produces"] if t != "any") or "无"
    accs = "/".join(t for t in dst["accepts"] if t != "any") or "无"
    return {"ok": False, "kind": kind,
            "reason": f"{source_kind} 产出「{outs}」，而 {target_kind} 只接受「{accs}」"}


def validate_graph(nodes: List[Dict[str, Any]],
                   edges: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """校验整图，返回问题列表（**不抛异常、不改图**）。

    与前端 `ports.ts::validateGraph` 同语义，供执行前复核。
    问题级别：`type-mismatch` / `fan-in-exceeded` / `cycle` = error；`dangling` = warn。
    """
    problems: List[Dict[str, Any]] = []
    nodes = nodes or []
    edges = edges or []

    def kind_of(n: Dict[str, Any]) -> str:
        d = n.get("data")
        if isinstance(d, dict) and d.get("kind"):
            return str(d["kind"])
        return str(n.get("type") or "")

    by_id: Dict[str, Dict[str, Any]] = {}
    for n in nodes:
        if isinstance(n, dict) and n.get("id"):
            by_id[str(n["id"])] = n

    fan_in: Dict[str, Dict[str, int]] = {}
    data_edges: List[Tuple[str, str]] = []

    for e in edges:
        if not isinstance(e, dict):
            continue
        s, t = str(e.get("source") or ""), str(e.get("target") or "")
        # 无端点的畸形边直接跳过：那不是「悬空引用」，而是数据错误。
        if not s or not t:
            continue
        if s not in by_id or t not in by_id:
            problems.append({"level": "warn", "code": "dangling", "edgeId": e.get("id"),
                             "message": f"悬空边被忽略：{s} → {t}"})
            continue
        sk, tk = kind_of(by_id[s]), kind_of(by_id[t])
        v = can_connect(sk, tk)
        if v["kind"] == "associate":
            continue
        if not v["ok"]:
            problems.append({"level": "error", "code": "type-mismatch",
                             "edgeId": e.get("id"), "message": v.get("reason", "类型不匹配")})
            continue
        data_edges.append((s, t))
        via = v.get("via") or "any"
        fan_in.setdefault(t, {})
        fan_in[t][via] = fan_in[t].get(via, 0) + 1

    for nid, rec in fan_in.items():
        dst = ports_of(kind_of(by_id[nid]))
        for t, cnt in rec.items():
            cap = int(dst["accepts"].get(t, 0))
            if t != "any" and cnt > cap:
                problems.append({
                    "level": "error", "code": "fan-in-exceeded", "nodeId": nid,
                    "message": f"{kind_of(by_id[nid])} 的 {t} 输入超限：{cnt} > {cap}"})

    for nid in _detect_cycle(data_edges):
        problems.append({"level": "error", "code": "cycle", "nodeId": nid,
                         "message": f"数据流成环：{nid}"})
    return problems


def _detect_cycle(edges: List[Tuple[str, str]]) -> List[str]:
    adj: Dict[str, List[str]] = {}
    indeg: Dict[str, int] = {}
    nodes = set()
    for s, t in edges:
        nodes.add(s)
        nodes.add(t)
        adj.setdefault(s, []).append(t)
        indeg[t] = indeg.get(t, 0) + 1
        indeg.setdefault(s, indeg.get(s, 0))
    queue = sorted(n for n in nodes if indeg.get(n, 0) == 0)
    seen = 0
    while queue:
        n = queue.pop(0)
        seen += 1
        for m in adj.get(n, []):
            indeg[m] -= 1
            if indeg[m] == 0:
                queue.append(m)
    if seen == len(nodes):
        return []
    return sorted(n for n in nodes if indeg.get(n, 0) > 0)


def describe_illegal_edges(graph: Dict[str, Any]) -> List[Dict[str, Any]]:
    """便捷入口：给一张画布图，只返回**非法连接**（供 runner 如实报告）。"""
    nodes = (graph or {}).get("nodes") or []
    edges = (graph or {}).get("edges") or []
    return [p for p in validate_graph(nodes, edges)
            if p.get("code") in ("type-mismatch", "fan-in-exceeded")]


def stats() -> Dict[str, Any]:
    """诊断用：解析状态 + 表规模。"""
    ports = node_ports()
    return {
        "parsed_ok": parse_ok(),
        "kinds": len(ports),
        "compat_rules": len(port_compat()),
        "ts_path": _ts_path(),
    }
