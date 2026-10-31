# -*- coding: utf-8 -*-
"""工作流蓝图（Blueprint）—— Agent 的「编排器」原语（2026-10-31）

═══ 为什么有这个模块 ═══════════════════════════════════════════════════════
用户实锤的原问题（2026-10-31）：

    「用户输入需求之后，AI 画布不能根据用户输入的需求生成提示词，然后去调动
      里面的节点跟意图胶囊卡片去组成一个完整的工作流程，而是只能调出一到
      两张或者是三张节点或意图卡片，但不能完整地去组出来一套完整的工作
      流程，并且就是只是随意放置，不是很规整，很杂乱的那种放置。」

拆成三个病根（都已定位到文件:行号）：

  ① **只能出 1~3 张卡** —— 画布 Agent 走 `canvas_fast` 快路径，
     system prompt 只列 17 个前端 action（`project_agent_host.py:274-285`
     + `agent_policy.py:283-301` 硬编码字符串），**没有「完整流程」的
     输出形态**；LLM 只能一条条发 addNode，于是只发得出几条。
  ② **没有提示词** —— 提示词这件事本来就该 LLM 做，但快路径的提示里
     从没告诉它「每个节点都要写 prompt」，它就只给标题。
  ③ **放置杂乱** —— `store.addNode` 无坐标时 `Math.random()` 撒点
     （`store.ts:888-891`，冻结区不可改）；Agent 显式传 x/y 时又不做整理。

═══ 本模块的解法 ═══════════════════════════════════════════════════════════
引入一个**新原语：蓝图（blueprint）** —— LLM 一次性产出「一整张图」，
而不是一串零散指令：

    {"canvas_tools":[{"action":"applyBlueprint","params":{"blueprint":{
        "goal": "…", "mode": "workflow",
        "nodes":[{"key":"n1","kind":"script","title":"剧本","prompt":"…"}],
        "edges":[{"from":"n1","to":"n2"}]}}}]}

三条开源启发（借鉴 + 落法）：

  1. **ComfyUI：图是一等公民** —— LLM 直接产出 graph JSON，执行器吃图。
     ⇒ 后端把蓝图当**一等契约**（本模块：解析/校验/补全），
       前端把蓝图当**一等操作**（`applyBlueprint.ts`：一次落完整张图）。
  2. **React Flow + Dagre：拓扑 → 自动坐标** —— 布局由图结构算出来。
     ⇒ 前端 `blueprintLayout.ts` 实现 Dagre 的分层+层内排序（零新依赖）。
  3. **AiDiagram：LLM 永不输出像素坐标，只输出语义放置元数据** ——
     布局可换而不用重问 LLM，且对模型输出波动健壮。
     ⇒ **蓝图 schema 里没有 x/y**；坐标一律由本地布局引擎算。

═══ 标准流程补全（解决「只能出 1~3 张卡」）═══════════════════════════════
光靠提示词，LLM 仍可能只给 2 张卡。所以后端做**终点驱动的补全**：

  · 先从需求里判断**流程终点**（成片 / 分镜表 / 视频 / 生图 / 分镜 / 剧本）；
    判不出但用户明确要「完整流程」⇒ 终点 = 全生产链（成片）。
  · 再沿**该终点的标准路径**（`CANONICAL_PATHS`）补齐缺失环节。
    ⚠️ 终点不同路径不同：「到分镜表」不该硬塞一段视频生成 ⇒ 走宫格路径；
      「到成片」生图/生视频是漫剧本体 ⇒ 走全生产链。
  · **每条边都过端口类型校验**（`can_connect`）——
    踩出来的坑：`shotlist` 只吃 video/grid，**不吃 image**
    ⇒「镜头 → 分镜表」类型上是断的，不能进标准链。
  · 补出来的节点标 `auto=true` + 人话说明，**并在回复里如实告知补了几张**；
  · 单步需求（"给我一张图"）**完全不补** —— 不臆造端点。

═══ 纪律 ═══════════════════════════════════════════════════════════════════
  - **节点目录不写第二份表**：`kind → 中文名/说明` 直接解析前端真源
    `NodePalette.tsx`；`kind → 端口类型` 直接复用 `canvas_port_model`
    （它自己解析 `ports.ts`）。⇒ 漂移在构造上不可能发生。
  - **不抛异常**：解析失败 ⇒ 回退宽松 + 记 warning（端口校验是增强不是主链路）。
  - **诚实**：非法 kind / 悬空边 / 类型不兼容的边 / 环 —— 全部**如实报告**，
    绝不静默吞掉；不兼容的边**剔除**（落画布的必须是可执行 DAG）。
"""
from __future__ import annotations

import logging
import os
import re
from functools import lru_cache
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ── 规模上限（防 LLM 幻觉铺爆画布）──────────────────────────────────────
MAX_NODES = 24
MAX_EDGES = 48

# 前端真源（画布单一真源在 vendor/packages/libtv）
_LIBTV_REL = os.path.join("vendor", "packages", "libtv", "src")
_PALETTE_REL = os.path.join(_LIBTV_REL, "NodePalette.tsx")

_PALETTE_ROW_RE = re.compile(
    r'type:\s*"([A-Za-z][A-Za-z0-9_]*)"\s*,\s*label:\s*"([^"]*)"'
    r'\s*,\s*keywords:\s*"([^"]*)"\s*,\s*hint:\s*"([^"]*)"'
)


# ═══════════════════════════════════════════════════════════════════════════
# 标准阶段与标准路径
# ═══════════════════════════════════════════════════════════════════════════
# 标准阶段（kind → 中文名）。顺序 = 漫剧生产链的自然顺序。
CANONICAL_STAGES: Tuple[Tuple[str, str], ...] = (
    ("script", "剧本"),
    ("directorCard", "导演卡"),
    ("shot", "镜头"),
    ("image", "画面"),
    ("storyboard", "宫格分镜"),
    ("video", "片段"),
    ("shotlist", "分镜表"),
    ("codeVideo", "成片"),
)

# 标准流程路径：**终点不同 ⇒ 路径不同**。
# 为什么不是一条直线：不同终点需要的前置不同。
#   · 「到分镜表」为止 ⇒ 不该硬塞一段视频生成 ⇒ 走宫格路径；
#   · 「到成片」为止 ⇒ 生图/生视频是漫剧的本体 ⇒ 走全生产链。
# ⚠️ 每条边的两端都过端口类型校验（`can_connect`）——
#   踩过的坑：`shotlist` 只接受 video/grid，**不吃 image**
#   ⇒ 「镜头 → 分镜表」这条边在类型上是断的，不能进标准链。
CANONICAL_PATHS: Dict[str, Tuple[str, ...]] = {
    "script": ("script",),
    "directorCard": ("script", "directorCard"),
    "shot": ("script", "directorCard", "shot"),
    "image": ("script", "directorCard", "shot", "image"),
    "video": ("script", "directorCard", "shot", "image", "video"),
    "shotlist": ("script", "directorCard", "shot", "storyboard", "shotlist"),
    "codeVideo": ("script", "directorCard", "shot", "image", "video", "shotlist", "codeVideo"),
}

# 各阶段补出来的节点写什么（人话说明，不是最终提示词 —— 明确标 auto）
_AUTO_INTENT: Dict[str, str] = {
    "script": "把需求整理成可拍的剧本",
    "directorCard": "把剧本拆成分镜",
    "shot": "按拆解结果逐镜写提示词",
    "image": "把镜头提示词转成画面",
    "storyboard": "把镜头排成宫格分镜",
    "video": "把画面转成视频片段",
    "shotlist": "汇总镜头清单与时长",
    "codeVideo": "按镜头清单渲染成片",
}

# 需求里出现这些词 ⇒ 用户要的是「完整流程」，允许补全
_WORKFLOW_MARKERS: Tuple[str, ...] = (
    "完整流程", "完整工作流", "工作流", "全流程", "一条龙", "端到端",
    "从剧本到", "到成片", "串起来", "编排", "流水线", "整套", "一整套",
    "完整链路", "生产链", "做一集", "做一条", "做一部", "一集漫剧",
)

# 需求里出现这些词 ⇒ 流程终点（**scope 信号**）。
# ⚠️ 只收范围信号：「画面要二次元」这种风格描述不算
#    （否则会把「完整流程」缩成「只到生图」）。
_SCOPE_MARKERS: Tuple[Tuple[str, str], ...] = (
    ("成片", "codeVideo"), ("交付", "codeVideo"), ("导出", "codeVideo"),
    ("上线", "codeVideo"), ("渲染成片", "codeVideo"),
    ("分镜表", "shotlist"), ("剪辑", "shotlist"), ("时间线", "shotlist"),
    ("生视频", "video"), ("视频片段", "video"), ("动起来", "video"),
    ("做成视频", "video"), ("生成视频", "video"), ("做视频", "video"),
    ("出视频", "video"), ("拍视频", "video"), ("转成视频", "video"),
    ("生图", "image"), ("出图", "image"), ("生成图片", "image"),
    ("生图片", "image"), ("生成图", "image"),
    ("分镜", "shot"), ("镜头脚本", "shot"), ("拆分镜", "shot"),
    ("写剧本", "script"), ("写脚本", "script"), ("编剧本", "script"),
)


# ═══════════════════════════════════════════════════════════════════════════
# 节点目录（从前端真源解析，不写第二份表）
# ═══════════════════════════════════════════════════════════════════════════
def _project_root() -> str:
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@lru_cache(maxsize=1)
def _load_palette() -> Dict[str, Dict[str, str]]:
    """解析 `NodePalette.tsx` 的 `NODE_PALETTE` ⇒ {kind: {label, hint}}。"""
    path = os.path.join(_project_root(), _PALETTE_REL)
    try:
        with open(path, "r", encoding="utf-8") as fh:
            src = fh.read()
    except Exception:
        logger.warning("[canvas_blueprint] 读不到 %s，节点中文名回退空", path, exc_info=True)
        return {}
    out: Dict[str, Dict[str, str]] = {}
    for kind, label, _kw, hint in _PALETTE_ROW_RE.findall(src):
        out[kind] = {"label": label, "hint": hint}
    if not out:
        logger.warning("[canvas_blueprint] NODE_PALETTE 解析为空（格式变了？）")
    return out


def node_kind_catalog() -> List[Dict[str, Any]]:
    """全部可用节点 kind 目录（kind / 中文名 / 说明 / 端口类型）。

    - kind + 端口类型：来自 `canvas_port_model`（它解析 `ports.ts`）；
    - 中文名 + 说明：来自前端 `NodePalette.tsx`。
    """
    from app.core.canvas_port_model import node_ports, parse_ok, ports_of

    palette = _load_palette()
    ports = node_ports()
    if not parse_ok():
        logger.warning("[canvas_blueprint] ports.ts 解析失败，端口类型不可用")
    kinds = sorted(set(palette) | set(ports))
    out: List[Dict[str, Any]] = []
    for kind in kinds:
        p = ports_of(kind)
        acc = sorted(k for k in p.get("accepts", {}) if k != "any")
        pro = sorted(k for k in p.get("produces", {}) if k != "any")
        if not acc:
            acc = ["any"]
        if not pro:
            pro = ["any"]
        meta = palette.get(kind, {})
        out.append({
            "kind": kind,
            "label": meta.get("label") or kind,
            "hint": meta.get("hint") or "",
            "accepts": acc,
            "produces": pro,
        })
    return out


def known_kinds() -> List[str]:
    return [row["kind"] for row in node_kind_catalog()]


def _stage_label(kind: str) -> str:
    for k, label in CANONICAL_STAGES:
        if k == kind:
            return label
    return kind


# ── 提示词骨架（后端补环节 / 合成整图时共用）────────────────────────────
# 需求里命中的**环节**（去重后的 scope kind），用来判断「是不是一条链」
def _matched_scope_kinds(text: str) -> List[str]:
    t = str(text or "")
    out: List[str] = []
    for kw, kind in _SCOPE_MARKERS:
        if kw in t and kind not in out:
            out.append(kind)
    return out


# 时长（"60 秒" / "3 分钟"）—— 用户给了就带进提示词，没给就不编
_DURATION_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(秒|分钟|分|s\b)")


def _extract_duration(text: str) -> str:
    m = _DURATION_RE.search(str(text or ""))
    if not m:
        return ""
    num, unit = m.group(1), m.group(2)
    if unit.startswith("分"):
        return f"{num} 分钟"
    return f"{num} 秒"


# 风格词表 —— 只在需求里**确实出现**时引用，不猜、不臆造
_STYLE_HINTS: Tuple[str, ...] = (
    "二次元", "日漫", "国漫", "赛璐璐", "厚涂", "写实", "真人", "实拍",
    "赛博朋克", "蒸汽朋克", "古风", "国风", "水彩", "油画", "国画",
    "3D", "皮克斯", "迪士尼", "治愈", "悬疑", "科幻", "末世", "蒸汽",
    "校园", "都市", "古装", "民国", "黑白", "彩色", "冷色", "暖色",
)


def _extract_style(text: str) -> str:
    t = str(text or "")
    hits = [w for w in _STYLE_HINTS if w in t]
    return "、".join(hits[:3])


def _extract_requirement(text: str) -> str:
    """把用户原话压成一行「创作依据」（不加工、不改写，只裁剪）。"""
    raw = re.sub(r"\s+", " ", str(text or "")).strip()
    if len(raw) > 400:
        raw = raw[:400] + "…"
    return raw


# 各阶段的**提示词骨架**。
# 谁用：① 后端补齐缺失环节（`_make_auto_node`）；② 后端合成整张图。
# ⚠️ 模型自己写的提示词永远优先 —— 这张表只是**兜底**，不是唯一真相。
_STAGE_PROMPT_TEMPLATES: Dict[str, str] = {
    "script": (
        "创作依据：{req}\n"
        "任务：把上面这条需求扩写成可直接拍摄的剧本 —— 开场钩子 → 主要冲突 → 结尾悬念；"
        "每场写清地点/时间/人物/动作/台词。{duration}"
    ),
    "directorCard": (
        "依据剧本与需求「{req}」产出导演卡：角色设定、场景设定、镜头语言规范、情绪基调；{style}。"
    ),
    "shot": (
        "依据导演卡与剧本逐镜拆解：镜号 / 景别 / 机位 / 画面内容 / 台词 / 时长 / 转场；"
        "覆盖剧本每一场，{duration}"
    ),
    "image": (
        "为每个镜头写一条画面提示词：{style}；角色形象、光影、构图保持全片一致；"
        "每镜写清主体 + 动作 + 环境 + 景别关键词（需求：{req}）"
    ),
    "video": (
        "把每张画面转成动态片段：动作过程 + 镜头运动 + 时长与分镜对齐；角色一致性不变"
    ),
    "storyboard": (
        "把镜头列表排成宫格分镜表：每格 = 缩略图 + 镜号 + 一句话内容"
    ),
    "shotlist": (
        "汇总分镜表：镜号 / 景别 / 时长 / 画面提示词 / 素材状态，导出可执行清单"
    ),
    "codeVideo": (
        "按分镜表与素材时长拼接成片：转场、配音、字幕、BGM；{duration}；导出成片"
    ),
}


def _synth_node_prompt(kind: str, *, req: str, style: str, duration: str) -> str:
    tpl = _STAGE_PROMPT_TEMPLATES.get(kind, "")
    if not tpl:
        return _AUTO_INTENT.get(kind, f"补齐「{_stage_label(kind)}」环节")
    text = tpl.format(
        req=req or "（用户未给细节，按通用漫剧生产补齐）",
        style=(f"{style}风格" if style else "风格沿用需求"),
        duration=(f"时长约 {duration}" if duration else ""),
    )
    return re.sub(r"[；;]\s*[；;]", "；", text).replace("；。", "。").strip()


def _make_auto_node(kind: str, goal: str, user_message: str = "") -> Dict[str, Any]:
    """构造一个「Agent 按标准流程补上」的节点（标 auto + 人话说明）。

    ⚠️ 提示词用**同一套骨架模板**（`_synth_node_prompt`）—— 和「合成整张图」
    走同一个出口 ⇒ 用户点名的「要生成提示词」这条诉求，后端补的环节也带真提示词，
    不是「把剧本拆成分镜：xx」这种一句话梗概。
    """
    label = _stage_label(kind)
    base = (goal or "").strip()
    ctx = f"{user_message} {goal}".strip()
    body = _synth_node_prompt(
        kind,
        req=base or user_message,
        style=_extract_style(ctx),
        duration=_extract_duration(ctx),
    )
    return {
        "key": "",
        "kind": kind,
        "title": label,
        "prompt": body,
        "intent": f"Agent 按标准流程补齐的「{label}」环节（可改）",
        "data": {"auto": True, "auto_stage": kind},
    }


def _unique_key(base: str, used: set) -> str:
    key = base
    i = 2
    while key in used:
        key = f"{base}_{i}"
        i += 1
    return key


# ═══════════════════════════════════════════════════════════════════════════
# 终点判定
# ═══════════════════════════════════════════════════════════════════════════
def detect_ceiling(text: str) -> Optional[str]:
    """从需求文本推断**流程终点**（标准路径的 key）。判不出返回 None。"""
    t = str(text or "")
    best: Optional[str] = None
    best_idx = -1
    for kw, kind in _SCOPE_MARKERS:
        if kw in t:
            idx = len(CANONICAL_PATHS.get(kind, ()))
            if idx > best_idx:
                best_idx = idx
                best = kind
    return best


def _should_complete(spec: Dict[str, Any], user_message: str) -> bool:
    """是否允许补全标准流程。

    判据（两条任一命中即允许）：
      ① LLM 自己在蓝图里声明 ``mode="workflow"``（提示词明确要求它标注）；
      ② 用户需求文本命中「完整流程」类关键词。
    ⇒ 单步需求（"给我一张图"）不会触发补全。
    """
    if spec.get("mode") in ("workflow", "full", "pipeline"):
        return True
    text = f"{user_message} {spec.get('goal') or ''}"
    return any(m in text for m in _WORKFLOW_MARKERS)


# ═══════════════════════════════════════════════════════════════════════════
# 标准流程补全
# ═══════════════════════════════════════════════════════════════════════════
def _complete_canonical_path(
    nodes: List[Dict[str, Any]],
    edges: List[Dict[str, str]],
    goal: str,
    ceiling: str,
    user_message: str = "",
) -> Tuple[List[Dict[str, Any]], List[Dict[str, str]], List[str]]:
    """沿**终点对应的标准路径**补齐缺失环节。

    规则：
      1. path = CANONICAL_PATHS[ceiling]；
      2. 蓝图里落在 path 上的 kind 叫「锚点」；一个锚点都没有 ⇒ 不补
         （用户要的东西跟标准链无关，别硬塞）；
      3. 补齐范围 = path[0 .. max(锚点下标, 终点下标)] —— 从链首补起，
         但**不越过**终点（终点由需求决定，不由 Agent 猜）；
      4. 沿 path 逐段连边，并**剔除被 path 覆盖的捷径边**（避免一条长线横穿画布）；
      5. 非 path 上的节点（prompt / character / config …）保留原样与原边。

    返回 ``(nodes, edges, inserted_keys)``。
    """
    from app.core.canvas_port_model import can_connect

    path = CANONICAL_PATHS.get(ceiling)
    if not path:
        return nodes, edges, []
    out_nodes = list(nodes)
    out_edges = [dict(e) for e in edges]
    inserted: List[str] = []

    kind_by_key = {n["key"]: n["kind"] for n in out_nodes}
    anchors = [i for i, k in enumerate(path) if k in set(kind_by_key.values())]
    if not anchors:
        return out_nodes, out_edges, inserted

    end = max(max(anchors), len(path) - 1)
    span = list(path[: end + 1])

    # ── 建缺失节点 ──
    present_kinds = set(kind_by_key.values())
    need = [k for k in span if k not in present_kinds]
    if not need:
        return out_nodes, out_edges, inserted
    used = set(kind_by_key)
    for kind in need:
        node = _make_auto_node(kind, goal, user_message)
        key = _unique_key(f"auto_{kind}", used)
        used.add(key)
        node["key"] = key
        out_nodes.append(node)
        inserted.append(key)

    kind_to_key: Dict[str, str] = {}
    for n in out_nodes:
        kind_to_key.setdefault(n["kind"], n["key"])

    # ── 剔除捷径边：两端都在 span 上且中间隔了环节 ──
    def is_shortcut(a_kind: str, b_kind: str) -> bool:
        if a_kind not in span or b_kind not in span:
            return False
        i, j = span.index(a_kind), span.index(b_kind)
        return j > i + 1

    kept: List[Dict[str, str]] = []
    for e in out_edges:
        ak = kind_by_key.get(e["from"], "")
        bk = kind_by_key.get(e["to"], "")
        if ak and bk and is_shortcut(ak, bk):
            continue
        kept.append(e)
    out_edges = kept

    # ── 沿 span 连边（过端口类型校验）──
    have = {f"{e['from']}→{e['to']}" for e in out_edges}
    for i in range(len(span) - 1):
        pk = kind_to_key.get(span[i])
        sk = kind_to_key.get(span[i + 1])
        if not pk or not sk or pk == sk:
            continue
        ek = f"{pk}→{sk}"
        if ek in have:
            continue
        v = can_connect(span[i], span[i + 1])
        if not v.get("ok"):
            logger.debug("[canvas_blueprint] 标准路径边类型不兼容，跳过：%s（%s）", ek, v.get("reason"))
            continue
        out_edges.append({"from": pk, "to": sk})
        have.add(ek)

    return out_nodes, out_edges, inserted


# ═══════════════════════════════════════════════════════════════════════════
# 后端合成（模型没吐蓝图时的兜底）——「整图合成」
# ═══════════════════════════════════════════════════════════════════════════
#
# 为什么必须有这一层（2026-10-31 真机实测）：
#   本机 Ollama（qwen3.5:4b）在 3501 字符 system 提示下真实往返，输出的是
#   「**执行计划** + 反问用户要剧本」，`parse_canvas_tools` 解析出 tools=[]。
#   ⇒ 光靠提示词赌模型会吐蓝图 = 赌小模型会听话；而用户的诉求是
#   「输入需求 ⇒ 拿到一整套规整工作流」，这条**必须由后端兜底保证**，
#   不能随模型心情波动。
#
# 触发条件（保守：宁可不多铺，也不乱铺）：
#   ① 需求命中「完整流程」类词（_WORKFLOW_MARKERS）⇒ 按终点合成；
#   ② 需求里点了**≥2 个不同环节**（同时说「分镜」和「视频」）⇒ 那是一条链；
#   单步需求（"帮我生张图"）⇒ 不合成。
#
# 合成时让位：模型零散的建图类动作会被**丢弃**（它们会在画布上另起一套
# 散点节点，正是用户抱怨的「杂乱」）⇒ 换成一条规整链。如实报告丢了什么。

# 合成时会被蓝图**替换掉**的动作（会另起散点节点 / 依赖主链节点 id）
_BLUEPRINT_SUPERSEDE_ACTIONS = frozenset({
    "addNode", "updateNode", "connectNodes", "deleteNode",
    "duplicateNode", "groupNodes", "breakdown", "fillStoryboardCell",
    "runGenerate", "setNodeImage", "importImage",
})


def synthesize_workflow_blueprint(user_message: str) -> Optional[Dict[str, Any]]:
    """模型没给蓝图、但用户要完整流程时，后端按标准路径**合成整张图**。

    返回 ``{"blueprint": spec, "ceiling": kind, "reason": str}``；
    不该合成时返回 ``None``（单步需求绝不乱铺）。

    ⚠️ 合成的提示词是**骨架**（用用户原话 + 阶段任务拼出来），
       不是模型写的成品 —— 报告里如实标 ``synthesized=True``。
    """
    text = str(user_message or "")
    if not text.strip():
        return None

    matched = _matched_scope_kinds(text)
    workflow_hit = any(m in text for m in _WORKFLOW_MARKERS)
    if not workflow_hit and len(matched) < 2:
        return None

    ceiling = detect_ceiling(text) or "codeVideo"
    path = CANONICAL_PATHS.get(ceiling)
    if not path or len(path) < 2:
        return None

    req = _extract_requirement(text)
    style = _extract_style(text)
    duration = _extract_duration(text)

    nodes: List[Dict[str, Any]] = []
    edges: List[Dict[str, str]] = []
    for i, kind in enumerate(path, start=1):
        key = f"n{i}"
        nodes.append({
            "key": key,
            "kind": kind,
            "title": _stage_label(kind),
            "prompt": _synth_node_prompt(kind, req=req, style=style, duration=duration),
            "intent": _AUTO_INTENT.get(kind, f"补齐「{_stage_label(kind)}」环节"),
            "data": {"auto": True, "auto_stage": kind},
        })
        if i > 1:
            edges.append({"from": f"n{i - 1}", "to": key})

    spec = {
        "goal": req,
        "mode": "workflow",
        "nodes": nodes,
        "edges": edges,
    }
    reason = (
        f"需求命中「完整流程」信号，终点判为「{_stage_label(ceiling)}」"
        if workflow_hit else
        f"需求里点了 {len(matched)} 个不同环节（{'、'.join(matched)}），判为一条链，"
        f"终点「{_stage_label(ceiling)}」"
    )
    return {"blueprint": spec, "ceiling": ceiling, "reason": reason}


def ensure_workflow_blueprint(
    tools: List[Dict[str, Any]],
    *,
    user_message: str = "",
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], Dict[str, Any]]:
    """确保「用户要完整流程」时**一定有一张蓝图**可落。

    三种情形：
      ① 模型已给 applyBlueprint ⇒ 原样返回（模型的提示词更好）；
      ② 模型只给零散 addNode ⇒ **丢弃零散动作** + 合成整张链；
      ③ 模型只给文字计划（tools=[]）⇒ 合成整张链。

    返回 ``(tools, reports, info)``；``info["synthesized"]`` 为真表示
    本次是后端兜底合成的（回复里要如实说明）。
    """
    out = list(tools or [])
    for item in out:
        if isinstance(item, dict) and str(item.get("action") or "") == "applyBlueprint":
            return out, [], {"synthesized": False}

    synth = synthesize_workflow_blueprint(user_message)
    if not synth:
        return out, [], {"synthesized": False}

    kept: List[Dict[str, Any]] = []
    dropped: List[str] = []
    for item in out:
        action = str(item.get("action") or "") if isinstance(item, dict) else ""
        if action in _BLUEPRINT_SUPERSEDE_ACTIONS:
            dropped.append(action)
            continue
        kept.append(item)

    spec, report = normalize_blueprint(synth["blueprint"], user_message=user_message)
    report["synthesized"] = True
    report["ceiling"] = synth["ceiling"]
    report["dropped_actions"] = dropped
    if not report.get("ok"):
        return out, [], {"synthesized": False}

    kept.append({"action": "applyBlueprint", "params": {"blueprint": spec}})
    info = {
        "synthesized": True,
        "ceiling": synth["ceiling"],
        "reason": synth["reason"],
        "node_count": report.get("node_count", 0),
        "edge_count": report.get("edge_count", 0),
        "dropped_actions": dropped,
    }
    return kept, [report], info


# ═══════════════════════════════════════════════════════════════════════════
# 蓝图归一化与校验
# ═══════════════════════════════════════════════════════════════════════════
def _blank_spec() -> Dict[str, Any]:
    return {"goal": "", "mode": "", "nodes": [], "edges": []}


def _clean_nodes(raw_nodes: Any, report: Dict[str, Any]) -> List[Dict[str, Any]]:
    """节点清洗：key 唯一 + kind 合法 + 规模上限。"""
    kinds = set(known_kinds())
    seen_keys: set = set()
    nodes: List[Dict[str, Any]] = []
    for n in raw_nodes if isinstance(raw_nodes, list) else []:
        if not isinstance(n, dict):
            report["problems"].append("忽略一个不是对象的节点")
            report["dropped_nodes"] += 1
            continue
        key = str(n.get("key") or "").strip()
        if not key:
            report["problems"].append("忽略一个没有 key 的节点")
            report["dropped_nodes"] += 1
            continue
        if key in seen_keys:
            report["problems"].append(f"忽略重复 key 的节点：{key}")
            report["dropped_nodes"] += 1
            continue
        kind = str(n.get("kind") or "").strip()
        if kind not in kinds:
            report["problems"].append(f"忽略未知节点类型：{kind or '(空)'}")
            report["dropped_nodes"] += 1
            continue
        seen_keys.add(key)
        node: Dict[str, Any] = {"key": key, "kind": kind}
        title = str(n.get("title") or "").strip()
        if title:
            node["title"] = title
        prompt = str(n.get("prompt") or "").strip()
        if prompt:
            node["prompt"] = prompt
        intent = str(n.get("intent") or "").strip()
        if intent:
            node["intent"] = intent
        data = n.get("data")
        if isinstance(data, dict) and data:
            node["data"] = data
        nodes.append(node)
    if len(nodes) > MAX_NODES:
        report["problems"].append(
            f"节点数超上限（{len(nodes)} > {MAX_NODES}），只保留前 {MAX_NODES} 个")
        report["dropped_nodes"] += len(nodes) - MAX_NODES
        nodes = nodes[:MAX_NODES]
    return nodes


def _clean_edges(
    raw_edges: Any,
    kind_by_key: Dict[str, str],
    report: Dict[str, Any],
) -> List[Dict[str, str]]:
    """边清洗：悬空 / 自环 / 重复 / 类型不兼容 ⇒ 剔除并如实报告。"""
    from app.core.canvas_port_model import can_connect

    edges: List[Dict[str, str]] = []
    seen: set = set()
    for e in raw_edges if isinstance(raw_edges, list) else []:
        if not isinstance(e, dict):
            report["dropped_edges"] += 1
            continue
        s = str(e.get("from") or "").strip()
        t = str(e.get("to") or "").strip()
        if s not in kind_by_key or t not in kind_by_key:
            report["problems"].append(f"忽略悬空边：{s or '?'} → {t or '?'}")
            report["dropped_edges"] += 1
            continue
        if s == t:
            report["problems"].append(f"忽略自环边：{s}")
            report["dropped_edges"] += 1
            continue
        ek = f"{s}→{t}"
        if ek in seen:
            report["problems"].append(f"忽略重复边：{ek}")
            report["dropped_edges"] += 1
            continue
        verdict = can_connect(kind_by_key[s], kind_by_key[t])
        if not verdict.get("ok"):
            report["problems"].append(
                f"忽略类型不兼容的边：{ek}（{verdict.get('reason') or '不兼容'}）")
            report["dropped_edges"] += 1
            continue
        seen.add(ek)
        edges.append({"from": s, "to": t})
    if len(edges) > MAX_EDGES:
        report["problems"].append(
            f"边数超上限（{len(edges)} > {MAX_EDGES}），只保留前 {MAX_EDGES} 条")
        report["dropped_edges"] += len(edges) - MAX_EDGES
        edges = edges[:MAX_EDGES]
    return edges


def _topo_order_nodes(
    nodes: List[Dict[str, Any]],
    edges: List[Dict[str, str]],
) -> List[Dict[str, Any]]:
    """按拓扑序重排节点列表（同层保持声明顺序 ⇒ 确定性）。

    为什么重排：补全环节是「追加」进来的，直接追加会让节点列表变成
    「剧本 → 成片 → 导演卡 → 镜头 → …」，人读起来不像一条流程，
    前端布局的同层次序也会跟着别扭。
    """
    index = {n["key"]: i for i, n in enumerate(nodes)}
    if not index:
        return list(nodes)
    indeg = dict.fromkeys(index, 0)
    adj = {k: [] for k in index}
    for e in edges:
        s, t = e.get("from"), e.get("to")
        if s in index and t in index and s != t:
            adj[s].append(t)
            indeg[t] += 1
    ready = sorted((k for k, d in indeg.items() if d == 0), key=lambda k: index[k])
    out: List[str] = []
    while ready:
        k = ready.pop(0)
        out.append(k)
        for m in adj.get(k, []):
            indeg[m] -= 1
            if indeg[m] == 0:
                ready.append(m)
                ready.sort(key=lambda x: index[x])
    placed = set(out)
    for k in sorted(index, key=lambda x: index[x]):
        if k not in placed:
            out.append(k)
    by_key = {n["key"]: n for n in nodes}
    return [by_key[k] for k in out if k in by_key]


def normalize_blueprint(
    raw: Any,
    *,
    user_message: str = "",
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """归一化 LLM 给的蓝图。

    返回 ``(spec, report)``：
      - spec：可直接下发给前端的蓝图（nodes/edges 已清洗）；
      - report：``{"problems": [...], "inserted": [...], "node_count": n, ...}``
        —— **如实报告**所有被丢弃/补上的东西（不静默）。
    """
    report: Dict[str, Any] = {
        "problems": [],
        "inserted": [],
        "dropped_nodes": 0,
        "dropped_edges": 0,
        "node_count": 0,
        "edge_count": 0,
        "ok": False,
    }
    spec = _blank_spec()
    if not isinstance(raw, dict):
        report["problems"].append("蓝图不是对象")
        return spec, report

    spec["goal"] = str(raw.get("goal") or "").strip()
    spec["mode"] = str(raw.get("mode") or "").strip().lower()

    nodes = _clean_nodes(raw.get("nodes"), report)
    kind_by_key = {n["key"]: n["kind"] for n in nodes}
    edges = _clean_edges(raw.get("edges"), kind_by_key, report)

    # ── 标准流程补全（只在用户要完整流程时）──
    if _should_complete(spec, user_message):
        text = f"{user_message} {spec.get('goal') or ''}"
        ceiling = detect_ceiling(text) or "codeVideo"
        nodes, edges, inserted = _complete_canonical_path(
            nodes, edges, spec.get("goal") or user_message, ceiling,
            user_message=user_message)
        if inserted:
            report["inserted"] = inserted
        kind_by_key = {n["key"]: n["kind"] for n in nodes}
        # 补出来的边也要过一遍类型校验
        edges = _clean_edges(edges, kind_by_key, report)
        report["ceiling"] = ceiling

    spec["nodes"] = _topo_order_nodes(nodes, edges)
    spec["edges"] = edges
    report["node_count"] = len(spec["nodes"])
    report["edge_count"] = len(edges)
    report["ok"] = bool(spec["nodes"])
    return spec, report


# ═══════════════════════════════════════════════════════════════════════════
# 提示词（给 LLM 的蓝图输出规范）
# ═══════════════════════════════════════════════════════════════════════════
def blueprint_prompt_block() -> str:
    """画布 Agent 提示词里的「工作流蓝图」段。

    ⚠️ 这段只在**画布快路径**注入（`project_agent_host._build_canvas_fast_messages`）。
    """
    cat = node_kind_catalog()
    lines = []
    for row in cat:
        acc = "/".join(row["accepts"])
        pro = "/".join(row["produces"])
        hint = row.get("hint") or ""
        lines.append(f"  - {row['kind']}（{row['label']}）：接受 {acc} → 产出 {pro}；{hint}")
    kinds_block = "\n".join(lines)

    stage_lines = []
    for kind, label in CANONICAL_STAGES:
        stage_lines.append(f"  - {label}({kind})")
    stages_block = "\n".join(stage_lines)

    path_lines = []
    for key, path in CANONICAL_PATHS.items():
        if len(path) < 2:
            continue
        path_lines.append(f"  - 到「{_stage_label(key)}」为止："
                          + " → ".join(_stage_label(k) for k in path))
    paths_block = "\n".join(path_lines)

    return (
        "\n[工作流蓝图 · 编排原语]\n"
        "当用户要「一整套流程 / 完整工作流 / 从剧本到成片 / 把节点串起来」时，"
        "**必须输出下面这条 applyBlueprint JSON，一次铺出整张图**；"
        "只写「执行计划」而不给 JSON = 没完成任务。\n"
        "格式（追加在中文说明后面）：\n"
        '{"canvas_tools":[{"action":"applyBlueprint","params":{"blueprint":{'
        '"goal":"这条流程要产出什么","mode":"workflow",'
        '"nodes":[{"key":"n1","kind":"script","title":"剧本","prompt":"…"}],'
        '"edges":[{"from":"n1","to":"n2"}]}}}]}\n'
        "硬规则：\n"
        "  1. nodes 里每张卡都必须写 title 和 prompt（prompt 是**真提示词正文**，"
        "写画面/动作/风格，不要写「待填」「TODO」）；\n"
        "  2. key 唯一；edges 用 key 互相引用；\n"
        "  3. **禁止输出 x/y 坐标** —— 画布坐标由本地拓扑引擎自动计算，"
        "你只管图结构；\n"
        "  4. 边的两端必须类型兼容（见下表），且**不得成环**；\n"
        "  5. 用户要完整流程时把 mode 设为 workflow；只做单步操作时**不要**发蓝图，"
        "直接发 addNode；\n"
        "  6. **信息不全也要先把结构铺全**：用户还没给剧本/素材时，"
        "照样按标准路径把环节一次给全，prompt 写成创作方向（不许空着），"
        "缺的东西在中文说明里问一次即可。\n"
        "可用节点（kind（中文名）：接受 → 产出）：\n"
        f"{kinds_block}\n"
        "标准流程阶段：\n"
        f"{stages_block}\n"
        "标准路径（用户要「到某一步」时就按对应路径串；缺环节系统会替你补）：\n"
        f"{paths_block}\n"
        "典型完整链示例（按需求增删）：\n"
        "  script(剧本) → directorCard(拆解) → shot(镜头) → image(画面) → video(片段)\n"
        "  script(剧本) → directorCard(拆解) → shot(镜头) → storyboard(宫格分镜) "
        "→ shotlist(分镜表) → codeVideo(成片)\n"
        "  prompt(风格提示词) → shot(镜头)（提示词可同时喂给 image / video）\n"
    )


# ═══════════════════════════════════════════════════════════════════════════
# 工具归一化入口（供 project_agent_host 调用）
# ═══════════════════════════════════════════════════════════════════════════
def normalize_canvas_tools(
    tools: List[Dict[str, Any]],
    *,
    user_message: str = "",
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """把 LLM 输出的 canvas_tools 里的 applyBlueprint 归一化。

    返回 ``(tools, reports)``；``reports`` 每项对应一个 applyBlueprint，
    供 Agent 在回复里如实告知用户「补了几张卡 / 丢了什么」。
    """
    out: List[Dict[str, Any]] = []
    reports: List[Dict[str, Any]] = []
    for item in tools or []:
        if not isinstance(item, dict):
            continue
        action = str(item.get("action") or "")
        if action != "applyBlueprint":
            out.append(item)
            continue
        params = dict(item.get("params") or {})
        raw = params.get("blueprint")
        if not isinstance(raw, dict):
            spec_raw = params.get("spec")
            raw = spec_raw if isinstance(spec_raw, dict) else None
        if not isinstance(raw, dict):
            reports.append({
                "ok": False, "problems": ["applyBlueprint 缺少 blueprint"],
                "inserted": [], "node_count": 0, "edge_count": 0,
            })
            out.append({**item, "params": {**params, "error": "applyBlueprint 缺少 blueprint"}})
            continue
        spec, report = normalize_blueprint(raw, user_message=user_message)
        params["blueprint"] = spec
        reports.append(report)
        out.append({**item, "params": params})
    return out, reports


def describe_report(report: Dict[str, Any]) -> str:
    """把归一化报告写成人话（放进 Agent 回复）。"""
    bits: List[str] = []
    n = int(report.get("node_count") or 0)
    e = int(report.get("edge_count") or 0)
    if n:
        if report.get("synthesized"):
            bits.append(f"已按标准流程铺出 {n} 个环节 / {e} 条连线")
        else:
            bits.append(f"{n} 个节点 / {e} 条连线")
    ins = report.get("inserted") or []
    if ins and not report.get("synthesized"):
        bits.append(f"按标准流程补了 {len(ins)} 个环节")
    dropped = report.get("dropped_actions") or []
    if dropped:
        bits.append(f"替换了 {len(dropped)} 条零散画布指令")
    problems = report.get("problems") or []
    if problems:
        bits.append(f"{len(problems)} 条校验提示")
    return "；".join(bits) if bits else "无有效节点"
