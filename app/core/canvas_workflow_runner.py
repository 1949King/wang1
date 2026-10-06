# -*- coding: utf-8 -*-
"""画布工作流运行器 —— 把「节点图」当程序跑（ComfyUI 视角的执行层）

为什么需要它
------------
画布目前的「链」是**语义链**（人理解的先后），不是**执行链**（机器跑的 DAG）：
- 连线只决定颜色/虚线（`EDGE_STYLE_BY_TYPE`），不参与执行；
- 真实生成靠人**逐节点点**「生成选中」；
- 唯一的"整条流水线"是 `agent_pipeline_orchestrator.py` 里**硬编码的 Python 序列**。

本模块补上「图执行」这一层：**接受画布的 nodes+edges，拓扑排序后逐节点执行**，
并联动 `canvas_node_cache` 做增量（同参数不重抽、改一处只重跑下游）。

三条纪律（与项目既有价值观一致）
--------------------------------
1. **默认只出计划（dry_run=True）** —— 守北极星「智能体只做确认后执行的遥控器，
   不默认一键成片」。要真跑必须显式 `dry_run=False`。
2. **诚实失败** —— 节点跑不了就**如实报告原因**（未接线/缺渠道/上游断裂），
   绝不伪造产物、绝不静默降级成别的模型。
3. **单节点失败不炸整图** —— 记录 `status=failed` 后**跳过其下游**（依赖已断），
   其余分支继续。与 `preview_validation_loop` 的容错口径一致。

边界（不做的事）
----------------
- 不做图编辑（增删节点/连线）——那是前端 store 的职责。
- 不做端口类型校验 —— 那是「类型化插座」的职责（前端 `isValidConnection`）。
  本模块对**非法连线**的态度是：**照跑，但如实报告**（不静默）。
- 不支持环（DAG only）——检测到环即整体拒绝并给出节点清单。
"""
from __future__ import annotations

import hashlib
import logging
from typing import Any, Callable, Dict, Iterable, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)

# 明确不可执行（登记原因，用于「如实报告」而不是含糊跳过）
_NOT_RUNNABLE: Dict[str, str] = {
    "group": "编组容器，无产物",
    "note": "画布笔记，无产物",
    "markdown": "文档节点，无产物",
    "prompt": "提示词载体，仅作为上游文本被下游消费",
    "config": "生成配置载体，仅作参数来源",
    "script": "剧本载体；拆镜请走 /host/storyboard-breakdown",
    "storyboard": "宫格分镜，纯前端裁剪",
    "shotlist": "分镜表，工具型节点",
    "director": "3D 导演台，交互式场景（需人工在舞台内操作）",
    "directorCard": "导演卡，拆解请走前端 breakdownDirectorCard",
    "digitalHuman": "数字人；口型成片未接入（后端无驱动端点）",
    "animation": "逐帧动画，前端逐帧表驱动",
    "panorama": "360° 全景，交互式节点",
    "source": "源文件入口，仅上传",
}

_MAX_NODES = 200          # 单次运行节点上限（防误传巨型图）


# ────────────────────────── 图结构 ──────────────────────────


def node_id(node: Dict[str, Any]) -> str:
    return str(node.get("id") or "")


def node_kind(node: Dict[str, Any]) -> str:
    """取节点 kind：优先 data.kind（node-factory 写入），其次节点 type。"""
    data = node.get("data")
    if isinstance(data, dict):
        k = data.get("kind")
        if k:
            return str(k)
    return str(node.get("type") or "")


def node_data(node: Dict[str, Any]) -> Dict[str, Any]:
    d = node.get("data")
    return d if isinstance(d, dict) else {}


def build_adjacency(
    node_ids: Iterable[str], edges: List[Dict[str, Any]],
) -> Tuple[Dict[str, List[str]], Dict[str, List[str]]]:
    """构建图结构。返回 ``(upstream_of, downstream_of)``，两者均为 node_id → id 列表。

    - ``upstream_of[n]``   = n 的**上游**（边的 source 端）
    - ``downstream_of[n]`` = n 的**下游**（边的 target 端）

    只保留两端都在图里的边（悬空边忽略——画布历史数据里常见，不应报错）。
    """
    known = {str(i) for i in node_ids if i}
    upstream_of: Dict[str, List[str]] = {nid: [] for nid in known}
    downstream_of: Dict[str, List[str]] = {nid: [] for nid in known}
    for e in edges or []:
        if not isinstance(e, dict):
            continue
        s = str(e.get("source") or "")
        t = str(e.get("target") or "")
        if s not in known or t not in known or s == t:
            continue
        if s not in upstream_of[t]:
            upstream_of[t].append(s)
        if t not in downstream_of[s]:
            downstream_of[s].append(t)
    for nid in known:
        upstream_of[nid].sort()
        downstream_of[nid].sort()
    return upstream_of, downstream_of


def is_dag(upstream_of: Dict[str, List[str]]) -> Tuple[bool, List[str]]:
    """Kahn 判定是否有环。返回 (是否 DAG, 环上节点列表)。"""
    indeg = {nid: len(ups) for nid, ups in upstream_of.items()}
    downstream_of: Dict[str, List[str]] = {nid: [] for nid in upstream_of}
    for nid, ups in upstream_of.items():
        for up in ups:
            downstream_of.setdefault(up, []).append(nid)
    queue = sorted([nid for nid, d in indeg.items() if d == 0])
    seen = 0
    while queue:
        nid = queue.pop(0)
        seen += 1
        for child in downstream_of.get(nid, []):
            indeg[child] -= 1
            if indeg[child] == 0:
                queue.append(child)
    cyclic = sorted([nid for nid, d in indeg.items() if d > 0])
    return (not cyclic), cyclic


def topo_order(upstream_of: Dict[str, List[str]]) -> List[str]:
    """Kahn 拓扑排序；同层按 id 排序保证确定性（便于测试与缓存复现）。"""
    indeg = {nid: len(ups) for nid, ups in upstream_of.items()}
    downstream_of: Dict[str, List[str]] = {nid: [] for nid in upstream_of}
    for nid, ups in upstream_of.items():
        for up in ups:
            downstream_of.setdefault(up, []).append(nid)
    queue = sorted([nid for nid, d in indeg.items() if d == 0])
    order: List[str] = []
    while queue:
        nid = queue.pop(0)
        order.append(nid)
        for child in sorted(downstream_of.get(nid, [])):
            indeg[child] -= 1
            if indeg[child] == 0:
                queue.append(child)
    return order


# ────────────────────────── 指纹（增量缓存） ──────────────────────────


def compute_fingerprints(
    order: Iterable[str],
    node_map: Dict[str, Dict[str, Any]],
    upstream_of: Dict[str, List[str]],
) -> Dict[str, str]:
    """按拓扑序算每个节点的指纹（**含上游指纹**），实现「改一处只失效下游」。"""
    from app.core import canvas_node_cache as cache

    fps: Dict[str, str] = {}
    for nid in order:
        node = node_map.get(nid) or {}
        ups = [fps.get(u) for u in upstream_of.get(nid, [])]
        fps[nid] = cache.node_fingerprint(
            node_kind(node), node_data(node), [u for u in ups if u])
    return fps


# ────────────────────────── 上游产物注入 ──────────────────────────


_TEXT_UPSTREAM_KINDS = frozenset(
    {"script", "prompt", "text", "config", "note", "markdown", "shot"})


def collect_inputs(
    nid: str,
    upstream_of: Dict[str, List[str]],
    node_map: Dict[str, Dict[str, Any]],
    outputs: Dict[str, Dict[str, Any]],
) -> Dict[str, Any]:
    """从上游节点的**已产出结果**汇总输入。

    这是对当前画布的**能力补齐**：前端的 `collectUpstreamContext` 只把
    `script/prompt/text/config/shot` 的**文本**拼进 prompt，
    **图/视频/音频上游完全不参与**。本函数补上产物注入。

    返回 ``{prompt, reference_image, reference_video, audio_ref}``。
    """
    prompt_parts: List[str] = []
    ref_image = ""
    ref_video = ""
    audio_ref = ""
    for up in upstream_of.get(nid, []):
        up_node = node_map.get(up) or {}
        data = node_data(up_node)
        out = outputs.get(up) or {}
        kind = node_kind(up_node)

        text = str(out.get("text") or out.get("prompt") or "").strip()
        if not text:
            for key in ("prompt", "content", "text", "dialogue", "line"):
                v = str(data.get(key) or "").strip()
                if v:
                    text = v
                    break
        if text and kind in _TEXT_UPSTREAM_KINDS:
            prompt_parts.append(text)

        img = str(out.get("image_url") or out.get("url") or "").strip()
        if not img:
            img = str(data.get("imageUrl") or data.get("firstFrameUrl") or "").strip()
        if img and not ref_image:
            ref_image = img

        vid = str(out.get("video_url") or "").strip()
        if not vid:
            vid = str(data.get("videoUrl") or "").strip()
        if vid and not ref_video:
            ref_video = vid

        aud = str(out.get("audio_url") or "").strip()
        if not aud:
            aud = str(data.get("audioUrl") or "").strip()
        if aud and not audio_ref:
            audio_ref = aud

    return {
        "prompt": " ".join(p for p in prompt_parts if p).strip(),
        "reference_image": ref_image,
        "reference_video": ref_video,
        "audio_ref": audio_ref,
    }


# ────────────────────────── 节点执行 ──────────────────────────


def handler_for(kind: str) -> Optional[str]:
    """kind → handler 名。返回 None 表示该 kind 不可执行。"""
    if kind in ("image", "shot"):
        return "image"
    if kind in ("video", "audio", "music", "text"):
        return kind
    if kind == "generator":
        return "generator"
    return None


def execute_node(
    node: Dict[str, Any],
    inputs: Dict[str, Any],
    *,
    quality: str = "standard",
    aspect: str = "portrait",
) -> Dict[str, Any]:
    """执行单个节点。返回 ``{ok, output?, error?}``。异常绝不外抛。"""
    kind = node_kind(node)
    h = handler_for(kind)
    if not h:
        return {"ok": False, "error": f"节点类型 {kind} 不可执行"}
    data = node_data(node)
    prompt = str(inputs.get("prompt") or "").strip()
    if not prompt:
        prompt = str(data.get("prompt") or data.get("content") or "").strip()
    if not prompt and h in ("image", "generator", "video", "audio", "music", "text"):
        return {"ok": False, "error": "提示词为空（且无上游文本可注入）"}
    model = str(data.get("model") or "")
    size = str(data.get("size") or "")
    ref_img = str(inputs.get("reference_image") or "").strip()

    try:
        if h in ("image", "generator"):
            from app.core.canvas_aigc import generate_image_openai_compatible
            res = generate_image_openai_compatible(
                prompt=prompt, model=model, size=size,
                reference_image=ref_img, quality=quality, aspect=aspect)
            if not isinstance(res, dict):
                return {"ok": False, "error": "生图返回非字典"}
            if not res.get("ok"):
                return {"ok": False, "error": str(res.get("message") or "生图失败")}
            return {"ok": True, "output": {
                "image_url": res.get("image_url") or res.get("url") or "",
                "seed": res.get("seed"), "seed_sent": res.get("seed_sent"),
            }}

        if h == "video":
            from app.core.canvas_aigc import generate_video_via_host
            res = generate_video_via_host(
                prompt=prompt, model=model, size=size,
                reference_image=ref_img,
                reference_video=str(inputs.get("reference_video") or ""),
                duration=float(data.get("duration") or 5.0),
                quality=quality, aspect=aspect)
            if not isinstance(res, dict) or not res.get("ok"):
                return {"ok": False, "error": str(
                    (res or {}).get("message") or "生视频失败")}
            return {"ok": True, "output": {
                "video_url": res.get("video_url") or "",
                "seed": res.get("seed"),
            }}

        if h == "audio":
            from app.core.canvas_aigc import generate_audio_via_host
            res = generate_audio_via_host(prompt=prompt, model=model, quality=quality)
            if not isinstance(res, dict) or not res.get("ok"):
                return {"ok": False, "error": str(
                    (res or {}).get("message") or "生音频失败")}
            return {"ok": True, "output": {"audio_url": res.get("audio_url") or ""}}

        if h == "music":
            from app.core.canvas_aigc import generate_music_via_host
            res = generate_music_via_host(prompt=prompt, model=model)
            if not isinstance(res, dict) or not res.get("ok"):
                return {"ok": False, "error": str(
                    (res or {}).get("message") or "生音乐失败")}
            return {"ok": True, "output": {"audio_url": res.get("audio_url") or ""}}

        if h == "text":
            # 文本节点：走 AIEngine 的三级降级（云 → Ollama）。
            # **刻意不传 template** —— 传了会把「prompt 原样回显」当成功，
            # 那是静默降级（违反项目诚实失败纪律）。全链路失败时 chat_with_fallback
            # 会 yield 一个「错误: ...」字符串，必须识别出来如实报失败。
            from app.core.ai_engine import AIEngine
            gen = AIEngine().chat_with_fallback(
                [{"role": "user", "content": prompt}])
            text = "".join(gen or [])
            if not text.strip() or text.lstrip().startswith("错误:"):
                return {"ok": False,
                        "error": text.strip() or "文本生成返回空（无可用 AI 提供者）"}
            return {"ok": True, "output": {"text": text}}
    except Exception as e:
        logger.debug("[canvas_workflow_runner] 节点执行异常 kind=%s", kind, exc_info=True)
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}
    return {"ok": False, "error": f"未实现的 handler: {h}"}


# ────────────────────────── 主入口 ──────────────────────────


def run_graph(
    graph: Dict[str, Any],
    *,
    dry_run: bool = True,
    use_cache: bool = True,
    max_nodes: int = _MAX_NODES,
    progress: Optional[Callable[[str, Dict[str, Any]], None]] = None,
    quality: str = "standard",
    aspect: str = "portrait",
) -> Dict[str, Any]:
    """跑一张画布图。**默认 dry_run=True（只出计划，不真生成）**。

    ``graph`` 形状与画布工程一致：``{"nodes": [...], "edges": [...]}``。
    """
    from app.core import canvas_node_cache as cache

    nodes = [n for n in (graph or {}).get("nodes") or [] if isinstance(n, dict)]
    edges = [e for e in (graph or {}).get("edges") or [] if isinstance(e, dict)]

    if len(nodes) > max_nodes:
        return {"ok": False, "message": f"节点数 {len(nodes)} 超过上限 {max_nodes}",
                "hint": "请分次运行，或提高 max_nodes"}

    node_map: Dict[str, Dict[str, Any]] = {}
    for n in nodes:
        nid = node_id(n)
        if nid:
            node_map[nid] = n
    if not node_map:
        return {"ok": False, "message": "图中没有有效节点"}

    upstream_of, downstream_of = build_adjacency(node_map.keys(), edges)
    ok_dag, cyclic = is_dag(upstream_of)
    if not ok_dag:
        return {"ok": False, "message": "检测到环，无法执行（工作流必须是 DAG）",
                "cyclic": cyclic}

    order = topo_order(upstream_of)
    fps = compute_fingerprints(order, node_map, upstream_of) if use_cache else {}
    store = cache.get_store() if use_cache else None

    # 端口模型复核：**只报告，不拒绝**。
    # 理由：端口校验是「增强」不是「安全边界」；画布的历史图可能存有旧的非法连接，
    # 直接拒绝会让老工程跑不动。改为**如实报告**，由人决定要不要改。
    port_problems: List[Dict[str, Any]] = []
    try:
        from app.core import canvas_port_model as pm
        port_problems = pm.describe_illegal_edges(graph)
    except Exception:
        logger.debug("[canvas_workflow_runner] 端口校验不可用（不阻断执行）", exc_info=True)

    planned: List[Dict[str, Any]] = []
    executed: List[Dict[str, Any]] = []
    skipped: List[Dict[str, Any]] = []
    outputs: Dict[str, Dict[str, Any]] = {}
    failed_nodes: Set[str] = set()

    def _emit(stage: str, payload: Dict[str, Any]) -> None:
        if progress:
            try:
                progress(stage, payload)
            except Exception:
                logger.debug("[canvas_workflow_runner] 进度回调异常", exc_info=True)

    for nid in order:
        node = node_map[nid]
        kind = node_kind(node)
        name = str(node_data(node).get("title") or kind)

        if handler_for(kind) is None:
            skipped.append({"node_id": nid, "kind": kind, "title": name,
                            "reason": _NOT_RUNNABLE.get(kind, f"未登记的节点类型: {kind}")})
            continue

        broken = [u for u in upstream_of.get(nid, []) if u in failed_nodes]
        if broken:
            failed_nodes.add(nid)
            skipped.append({"node_id": nid, "kind": kind, "title": name,
                            "reason": f"上游失败，依赖已断: {broken}"})
            continue

        item = {"node_id": nid, "kind": kind, "title": name,
                "fingerprint": fps.get(nid, "")}
        planned.append(dict(item))

        if dry_run:
            continue

        fp = fps.get(nid, "")
        if store is not None and fp:
            hit = store.lookup(fp)
            if hit is not None:
                outputs[nid] = hit
                executed.append({**item, "status": "cached", "cached": True,
                                 "output": hit})
                _emit("node", {**item, "status": "cached"})
                continue

        inputs = collect_inputs(nid, upstream_of, node_map, outputs)
        res = execute_node(node, inputs, quality=quality, aspect=aspect)
        if res.get("ok"):
            out = res.get("output") or {}
            outputs[nid] = out
            if store is not None and fp:
                store.store(fp, out, kind=kind, head=inputs.get("prompt", ""))
            executed.append({**item, "status": "done", "cached": False, "output": out})
            _emit("node", {**item, "status": "done"})
        else:
            err = str(res.get("error") or "未知错误")
            failed_nodes.add(nid)
            executed.append({**item, "status": "failed", "cached": False, "error": err})
            _emit("node", {**item, "status": "failed", "error": err})

    counters = {
        "total": len(order),
        "planned": len(planned),
        "skipped": len(skipped),
        "done": len([e for e in executed if e.get("status") == "done"]),
        "cached": len([e for e in executed if e.get("status") == "cached"]),
        "failed": len([e for e in executed if e.get("status") == "failed"]),
    }
    return {
        "ok": True,
        "dry_run": bool(dry_run),
        "use_cache": bool(use_cache),
        "order": order,
        "planned": planned,
        "executed": executed,
        "skipped": skipped,
        "outputs": outputs,
        "counters": counters,
        "port_problems": port_problems,
        "cache": cache.get_store().stats() if use_cache else None,
        "note": ("这是执行计划（dry_run）。确认后以 dry_run=false 再调用才会真正生成。"
                 if dry_run else "已执行。产物仅返回引用，未写入时间线。"),
    }


def graph_signature(graph: Dict[str, Any]) -> str:
    """整图结构签名（节点+边），用于判断"图是否变过"。"""
    nodes = (graph or {}).get("nodes") or []
    edges = (graph or {}).get("edges") or []
    ids = sorted(node_id(n) for n in nodes if isinstance(n, dict))
    es = sorted(f"{e.get('source')}->{e.get('target')}"
                for e in edges if isinstance(e, dict))
    raw = "|".join(ids) + "##" + "|".join(es)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]
