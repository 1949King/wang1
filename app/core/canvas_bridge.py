# -*- coding: utf-8 -*-
"""自研拾光导演台画布 ↔ 拾光剪影 本地桥。

职责：
- 接收画布导出的图片/视频（HTTP multipart 或本地路径）
- 落盘到 ~/.video_editor_cache/canvas_inbox/
- 可选写入角色库资产（CharacterStore）
- EventBus 推送到剪辑时间线（MATERIAL_TO_TIMELINE）
- 可选开启线性补帧标记（非神经网络）

不嵌入 React 内核；画布仍跑在 localhost WebView。
"""
from __future__ import annotations

import colorsys
import json
import logging
import os
import queue
import shutil
import sys
import threading
import time
import uuid
from collections import deque
from typing import Any, Callable, Deque, Dict, List, Optional
# AIGC / 模型配置 / 分镜层已拆到 canvas_aigc.py，此处 re-export 保持向后兼容


logger = logging.getLogger("AI短剧编辑器.canvas_bridge")

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 18765
CONFIG_STORE_KEY = "infinite-canvas:ai_config_store"

# 本机会话令牌（写入 inject.js；/host/* 校验）
_SESSION_TOKEN = uuid.uuid4().hex
_BRIDGE_PREFS: Dict[str, Any] = {
    "character_id": "",
    "character_name": "",
    "character_prompt": "",
    "enable_interpolation": False,
    "active_provider": "",
    "active_provider_label": "",
}
_EDITOR_OUTBOX: List[Dict[str, Any]] = []
_OUTBOX_LOCK = threading.Lock()
_TIMELINE_SNAPSHOT_PROVIDER: Optional[Callable[[], Dict[str, Any]]] = None


def set_timeline_snapshot_provider(fn: Optional[Callable[[], Dict[str, Any]]]) -> None:
    """EditorModule 注册只读时间线快照（避免桥直接 import 上帝类）。"""
    global _TIMELINE_SNAPSHOT_PROVIDER
    _TIMELINE_SNAPSHOT_PROVIDER = fn


def get_timeline_snapshot() -> Dict[str, Any]:
    fn = _TIMELINE_SNAPSHOT_PROVIDER
    if not callable(fn):
        return {
            "ok": True,
            "clip_count": 0,
            "clips": [],
            "gaps": [],
            "message": "剪辑模块未就绪",
        }
    try:
        ctx = fn() or {}
        if not isinstance(ctx, dict):
            ctx = {}
        ctx.setdefault("ok", True)
        return ctx
    except Exception as e:
        logger.warning("timeline snapshot 失败: %s", e)
        return {"ok": False, "clip_count": 0, "clips": [], "gaps": [], "message": str(e)}

# ── Agent ↔ Canvas 双向通信事件总线 ──────────────────────────────
_EVT_BUFFER: Deque[Dict[str, Any]] = deque(maxlen=200)    # 内存环形缓冲（断线补发）
_EVT_SUBS: List[queue.Queue] = []                         # 活跃 SSE 订阅者队列
_EVT_SUBS_LOCK = threading.Lock()
_EVT_REPLY_QUEUES: Dict[str, queue.Queue] = {}            # correlation_id → reply queue（画布回执）
_EVT_REPLY_LOCK = threading.Lock()

EVENT_BUFFER_MAX = 200

def make_agent_event(
    event_type: str,
    payload: Any,
    *,
    from_agent: str = "editor",
    to_agent: str = "canvas",
    correlation_id: Optional[str] = None,
    ack_required: bool = False,
) -> Dict[str, Any]:
    """构造一条标准化事件信封。"""
    return {
        "id": f"evt_{uuid.uuid4().hex[:8]}",
        "ts": time.time() * 1000,
        "from": from_agent,
        "to": to_agent,
        "type": event_type,
        "correlation_id": correlation_id or "",
        "payload": payload,
        "ack_required": ack_required,
    }

def broadcast_agent_event(evt: Dict[str, Any]) -> None:
    """把一条事件广播给所有活跃的 SSE 订阅者，并写入环形缓冲。"""
    _EVT_BUFFER.append(evt)
    with _EVT_SUBS_LOCK:
        dead: List[queue.Queue] = []
        for q in _EVT_SUBS:
            try:
                q.put_nowait(evt)
            except queue.Full:
                dead.append(q)
            except Exception:
                dead.append(q)
        for q in dead:
            try:
                _EVT_SUBS.remove(q)
            except ValueError:
                pass

def replay_agent_events(since_id: str) -> List[Dict[str, Any]]:
    """断线重连时回放 evt_id > since_id 的未投递事件。"""
    if not since_id:
        return list(_EVT_BUFFER)
    ids_in_buf = [e.get("id") for e in _EVT_BUFFER]
    if since_id not in ids_in_buf:
        # 缓冲区里都没有（太老了），全量回
        return list(_EVT_BUFFER)
    out: List[Dict[str, Any]] = []
    seen = False
    for e in _EVT_BUFFER:
        if seen:
            out.append(e)
        if e.get("id") == since_id:
            seen = True
    return out

def register_reply_queue(correlation_id: str) -> queue.Queue:
    """为某个 correlation_id 注册一个回执队列，供剪辑侧阻塞等待画布回复。"""
    q: queue.Queue = queue.Queue(maxsize=1)
    with _EVT_REPLY_LOCK:
        _EVT_REPLY_QUEUES[correlation_id] = q
    return q

def unregister_reply_queue(correlation_id: str) -> None:
    with _EVT_REPLY_LOCK:
        _EVT_REPLY_QUEUES.pop(correlation_id, None)



def session_token() -> str:
    return _SESSION_TOKEN


# ── 画布节点插件官方注册表（Qt 端维护，GET /host/plugins 返回给前端）──
# 铁律（2026-10-25 血泪）：**注册表里每一条 url 都必须真的能取到**。
# 此前这里声明了 4 条 `/plugins/*.js` 但产物根本不存在（public/ 与 dist/ 都没有）。
# 注意静态服务的 SPA 兜底（canvas_runtime._SPAHandler.do_GET）对缺文件**不返回 404**，
# 而是把 path 改写成 /index.html ⇒ 前端拿到 **200 + HTML**，再当 ESM import ⇒
# `SyntaxError: Unexpected token '<'`，每次进画布刷 4 条 sync install failed；
# 另有 2 条社区插件指向 `cdn.shiguang.io`（域名不存在）⇒ 必然 `Failed to fetch`。
# 现在：4 个官方插件是**真实 bundle**，落在
# `vendor/shiguang-canvas/public/plugins/*.js`（vite build 会同步到 dist/plugins/）；
# 守卫见 app/tests/test_canvas_plugin_assets.py（注册表 url → 必须有对应文件）。
# 社区插件需要真实可用的 CDN 再回归，宁可空着也不留假地址。
_BUILTIN_PLUGIN_REGISTRY: List[Dict[str, Any]] = [
    {
        "id": "builtin:sticky-note",
        "name": "便利贴",
        "version": "0.1.0",
        "description": "彩色便利贴节点，双击编辑内容",
        "nodes": [{"type": "builtin:sticky-note", "title": "便利贴", "icon": "📌"}],
        "url": "/plugins/sticky-note.js",
        "official": True,
    },
    {
        "id": "builtin:markdown",
        "name": "Markdown 文档",
        "version": "0.1.0",
        "description": "渲染 Markdown 文档节点（标题/列表/引用/代码块/粗体斜体行内码链接）",
        "nodes": [{"type": "builtin:markdown", "title": "Markdown", "icon": "📄"}],
        "url": "/plugins/markdown.js",
        "official": True,
    },
    {
        "id": "builtin:svg-viewer",
        "name": "SVG 查看器",
        "version": "0.1.0",
        "description": "嵌入 SVG 图形并缩放预览（sandbox iframe 渲染，禁脚本）",
        "nodes": [{"type": "builtin:svg-viewer", "title": "SVG", "icon": "🎨"}],
        "url": "/plugins/svg-viewer.js",
        "official": True,
    },
    {
        "id": "builtin:timeline-embed",
        "name": "时间线嵌入",
        "version": "0.1.0",
        # 只读预览：数据来自 GET /host/timeline-snapshot；双向跳转尚未实现，描述不吹
        "description": "只读预览剪辑时间线（片段/时长/轨道/空隙），数据来自 /host/timeline-snapshot",
        "nodes": [{"type": "builtin:timeline-embed", "title": "时间线", "icon": "🎬"}],
        "url": "/plugins/timeline-embed.js",
        "official": True,
    },
]

# Qt 端已安装插件 manifest 存储路径
_CANVAS_PLUGINS_JSON = os.path.join(
    os.path.expanduser("~"), ".video_editor_cache", "canvas_plugins.json"
)

# 已知死地址（域名从未存在 / 已下线）。2026-10-25：历史上 registry 里编造过两条
# `https://cdn.shiguang.io/plugins/*.js`（社区插件示例），它们被写进用户 manifest 后
# 每次进画布都触发 `Failed to fetch`；registry 已删，用户缓存里的残留也要清掉，
# 否则「改了代码但用户还是报错」——缓存迁移与代码修复同等重要。
_DEAD_PLUGIN_URL_PREFIXES = ("https://cdn.shiguang.io/",)


def _load_canvas_plugins_manifest() -> List[Dict[str, Any]]:
    """读取 Qt 端已安装画布节点插件列表（顺带清掉指向死地址的残留条目）。"""
    try:
        if os.path.isfile(_CANVAS_PLUGINS_JSON):
            with open(_CANVAS_PLUGINS_JSON, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list):
                kept = [
                    p
                    for p in data
                    if not (
                        isinstance(p, dict)
                        and str(p.get("url") or "").startswith(_DEAD_PLUGIN_URL_PREFIXES)
                    )
                ]
                if len(kept) != len(data):
                    dropped = [
                        str(p.get("id"))
                        for p in data
                        if isinstance(p, dict)
                        and str(p.get("url") or "").startswith(_DEAD_PLUGIN_URL_PREFIXES)
                    ]
                    logger.info("canvas_plugins.json 清理死地址条目: %s", dropped)
                    _save_canvas_plugins_manifest(kept)
                return kept
    except Exception as e:
        logger.warning("读取 canvas_plugins.json 失败: %s", e)
    return []


def _save_canvas_plugins_manifest(plugins: List[Dict[str, Any]]) -> None:
    """持久化已安装插件列表"""
    try:
        os.makedirs(os.path.dirname(_CANVAS_PLUGINS_JSON), exist_ok=True)
        with open(_CANVAS_PLUGINS_JSON, "w", encoding="utf-8") as f:
            json.dump(plugins, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.warning("写入 canvas_plugins.json 失败: %s", e)


def _upsert_canvas_plugin(plugin_id: str, **fields: Any) -> Dict[str, Any]:
    """增/改一个插件条目（返回合并后的完整条目）"""
    plugins = _load_canvas_plugins_manifest()
    existing = next((p for p in plugins if p.get("id") == plugin_id), None)
    entry: Dict[str, Any] = {"id": plugin_id, **fields}
    if existing:
        # 保留旧字段，新字段覆盖
        entry = {**existing, **{k: v for k, v in entry.items() if v is not None}}
        idx = plugins.index(existing)
        plugins[idx] = entry
    else:
        plugins.append(entry)
    _save_canvas_plugins_manifest(plugins)
    return entry


def _toggle_canvas_plugin_enabled(plugin_id: str, enabled: bool) -> bool:
    """切换插件启用/禁用"""
    plugins = _load_canvas_plugins_manifest()
    for p in plugins:
        if p.get("id") == plugin_id:
            p["enabled"] = bool(enabled)
            _save_canvas_plugins_manifest(plugins)
            return True
    return False


def _remove_canvas_plugin(plugin_id: str) -> bool:
    """卸载插件"""
    plugins = _load_canvas_plugins_manifest()
    new_list = [p for p in plugins if p.get("id") != plugin_id]
    if len(new_list) == len(plugins):
        return False
    _save_canvas_plugins_manifest(new_list)
    return True


# ── 捏脸参数（faceParams）→ 生图文字描述 ────────────────────────────────
# 结构 / 枚举 id / 色板的**唯一真相源**在画布侧 src/faceParams.ts（与 FaceCard.tsx 同源）。
# 本表只是「枚举 id → 中文」的镜像，改动需同步 faceParams.ts 与 FaceCard.tsx。
_FACE_BROW_LABELS = {
    "flat": "平眉", "arch": "挑眉", "angry": "剑眉",
    "sad": "八字眉", "thin": "细眉", "thick": "粗眉",
    # A 类扩展（2026-10-21 补齐：与 faceParams.ts BrowStyleId 对齐）
    "round": "柳眉", "short": "短眉",
}
_FACE_EYE_LABELS = {
    "round": "圆眼", "almond": "杏眼", "narrow": "细长眼",
    "upturned": "上挑眼", "droopy": "下垂眼", "big": "大眼",
    # A 类扩展（2026-10-21 补齐：与 faceParams.ts EyeStyleId 对齐）
    "cat": "猫眼", "sleepy": "睡眼",
}
_FACE_EYE_COLOR_LABELS = {
    "black": "黑色", "brown": "棕色", "amber": "琥珀色", "hazel": "榛色",
    "blue": "蓝色", "green": "绿色", "violet": "紫色", "red": "红色", "gold": "金色",
}
_FACE_LIP_LABELS = {
    "thin": "薄唇", "plump": "饱满唇", "wide": "宽唇",
    "small": "小口", "cupid": "丘比特唇", "neutral": "自然唇",
    # A 类扩展（2026-10-21 补齐：与 faceParams.ts LipStyleId 对齐）
    "pouty": "嘟唇", "sharp": "利落唇",
}
_FACE_ACCESSORY_LABELS = {
    "hairpin": "单簪", "hairpin_dual": "双簪", "ribbon": "发带",
    "ribbon_tail": "长飘带", "tiara": "冠冕", "flower": "花钿",
    "earring": "耳饰", "forehead_mark": "额饰", "veil": "头纱", "horns": "角",
    # A 类扩展（2026-10-21 补齐：与 faceParams.ts HairAccessoryId 对齐）
    "glasses": "眼镜", "flower_crown": "花环",
}
# 与 faceParams.SKIN_PALETTE 同源（8 档）
_FACE_SKIN_LABELS = {
    "#fdece4": "冷白", "#f8d9c9": "白皙", "#f0c3a8": "自然", "#e0a882": "小麦",
    "#c88a63": "蜜色", "#a86a45": "古铜", "#7d4c2e": "深棕", "#54321d": "黝黑",
}


def _face_num(v: Any) -> float:
    """容错取数值（脏值/缺字段一律 0.0 = 中性）。"""
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def _face_hex_hue_name(hex_color: Any) -> str:
    """#rrggbb → 中文色系（只作跨镜一致的视觉锚点，不追求精确命名）。"""
    h = str(hex_color or "").strip().lstrip("#")
    if len(h) != 6:
        return ""
    try:
        r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    except ValueError:
        return ""
    if max(r, g, b) - min(r, g, b) < 24:      # 低饱和 ⇒ 黑白灰
        if max(r, g, b) < 60:
            return "黑"
        return "白" if max(r, g, b) > 200 else "灰"
    hue = colorsys.rgb_to_hsv(r / 255.0, g / 255.0, b / 255.0)[0] * 360.0
    if hue < 15 or hue >= 345:
        return "红"
    if hue < 45:
        return "橙"
    if hue < 70:
        return "黄"
    if hue < 160:
        return "绿"
    if hue < 200:
        return "青"
    if hue < 260:
        return "蓝"
    if hue < 290:
        return "紫"
    return "品红"


def _face_params_to_text(raw: Any) -> str:
    """把捏脸卡片的 faceParams（JSON 串或 dict）转成一句可进生图提示词的外貌描述。

    设计（与 faceParams.ts 的分工一致）：
      - 只描述**静态身份特征**（头型 / 五官形状 / 瞳色 / 肤色 / 发饰 / 妆容）；
        表情是「每镜可变」的表演参数，写进跨镜一致性提示词会与分镜冲突，故刻意不取。
      - 坏 JSON / 空串 / 非 dict 一律返回 ""（缺省即合法，绝不抛给调用方）。
    """
    if isinstance(raw, dict):
        p: Dict[str, Any] = raw
    elif isinstance(raw, str) and raw.strip():
        try:
            parsed = json.loads(raw)
        except (ValueError, TypeError):
            return ""
        if not isinstance(parsed, dict):
            return ""
        p = parsed
    else:
        return ""

    parts: List[str] = []

    # 头型（Ruth2 式 shape sliders；阈值 0.15 以下视为「默认不明显」，不写进提示词）
    shape: List[str] = []
    hw, hh = _face_num(p.get("headWidth")), _face_num(p.get("headHeight"))
    jw, cb, ch = _face_num(p.get("jawWidth")), _face_num(p.get("cheekbone")), _face_num(p.get("chin"))
    if hw > 0.15:
        shape.append("脸型偏宽")
    elif hw < -0.15:
        shape.append("脸型偏窄")
    if hh > 0.15:
        shape.append("脸型偏长")
    elif hh < -0.15:
        shape.append("脸型偏短")
    if jw > 0.15:
        shape.append("下颌偏宽")
    elif jw < -0.15:
        shape.append("下颌偏窄")
    if cb > 0.15:
        shape.append("颧骨明显")
    elif cb < -0.15:
        shape.append("颧骨平缓")
    if ch > 0.15:
        shape.append("下巴偏长")
    elif ch < -0.15:
        shape.append("下巴偏短")
    if shape:
        parts.append("、".join(shape[:3]))     # 限 3 项防止描述过长

    # 五官形状与瞳色
    brow = _FACE_BROW_LABELS.get(str(p.get("browStyle") or ""), "")
    if brow:
        parts.append(brow)
    eye = _FACE_EYE_LABELS.get(str(p.get("eyeStyle") or ""), "")
    iris = _FACE_EYE_COLOR_LABELS.get(str(p.get("eyeColor") or ""), "")
    if eye and iris:
        parts.append(f"{iris}{eye}")
    elif eye:
        parts.append(eye)
    elif iris:
        parts.append(f"{iris}瞳孔")
    right_iris = _FACE_EYE_COLOR_LABELS.get(str(p.get("eyeColorRight") or ""), "")
    if right_iris:
        parts.append(f"右眼{right_iris}（异色瞳）")
    lip = _FACE_LIP_LABELS.get(str(p.get("lipStyle") or ""), "")
    if lip:
        parts.append(lip)

    # 肤色
    skin = _FACE_SKIN_LABELS.get(str(p.get("skinTone") or "").lower(), "")
    if skin:
        parts.append(f"肤色{skin}")

    # 发饰（含主色，是跨镜可辨识的视觉符号）
    acc = _FACE_ACCESSORY_LABELS.get(str(p.get("hairAccessory") or ""), "")
    if acc:
        acc_hue = _face_hex_hue_name(p.get("accessoryColor"))
        parts.append(f"发饰{acc}" + (f"（{acc_hue}色）" if acc_hue else ""))

    # 妆容（只报「有没有」，颜色交给美术自由发挥，避免提示词过载）
    makeup = [
        label for key, label in (
            ("blush", "腮红"), ("eyeshadow", "眼影"), ("lipColor", "唇彩"),
            ("eyeliner", "眼线"), ("faceMark", "面纹"),
        ) if p.get(key)
    ]
    if makeup:
        parts.append("妆容:" + "、".join(makeup))

    return "，".join(parts)


def build_character_prompt(char: Optional[Dict[str, Any]]) -> str:
    """把角色库字段压成生图一致性提示片段。"""
    if not char:
        return ""
    name = str(char.get("name") or "").strip()
    parts: List[str] = []
    if name:
        parts.append(f"角色「{name}」")
    gender = str(char.get("gender") or "").strip()
    if gender:
        parts.append(gender)
    age = str(char.get("age_range") or "").strip()
    if age:
        parts.append(f"年龄感{age}")
    tags = char.get("tags")
    if isinstance(tags, list) and tags:
        parts.append("标签:" + ",".join(str(t) for t in tags if t))
    elif isinstance(tags, str) and tags.strip():
        parts.append("标签:" + tags.strip())
    appearance = str(char.get("appearance") or "").strip()
    if appearance:
        parts.append("外貌:" + appearance[:240])
    # 捏脸卡片写回的 faceParams → 文字描述（静态身份特征，跨镜一致的脸）
    face_desc = _face_params_to_text(char.get("face_params"))
    if face_desc:
        parts.append("捏脸:" + face_desc[:200])
    temperament = str(char.get("temperament") or "").strip()
    if temperament:
        parts.append("气质倾向:" + temperament[:80])
    # 标志性符号：跨集保持同一视觉锚点，是长线剧集「认得出这个人」的关键
    memory_anchors = str(char.get("memory_anchors") or "").strip()
    if memory_anchors:
        parts.append("标志性符号:" + memory_anchors[:120])
    personality = str(char.get("personality") or "").strip()
    if personality:
        # 前缀由「气质」改为「性格」：新增 temperament 已占用「气质」语义，
        # 两个词并存会互相稀释；本字段 schema 标签本就是「性格特征」
        parts.append("性格:" + personality[:120])
    return "，".join(parts)


def set_bridge_prefs(
    *,
    character_id: str = "",
    character_name: str = "",
    character_prompt: Optional[str] = None,
    enable_interpolation: Optional[bool] = None,
    active_provider: Optional[str] = None,
    active_provider_label: Optional[str] = None,
) -> None:
    if character_id is not None:
        _BRIDGE_PREFS["character_id"] = str(character_id or "")
    if character_name is not None:
        _BRIDGE_PREFS["character_name"] = str(character_name or "")
    if character_prompt is not None:
        _BRIDGE_PREFS["character_prompt"] = str(character_prompt or "")
    if enable_interpolation is not None:
        _BRIDGE_PREFS["enable_interpolation"] = bool(enable_interpolation)
    if active_provider is not None:
        _BRIDGE_PREFS["active_provider"] = str(active_provider or "")
    if active_provider_label is not None:
        _BRIDGE_PREFS["active_provider_label"] = str(active_provider_label or "")


def canvas_inbox_dir() -> str:
    root = os.path.join(os.path.expanduser("~"), ".video_editor_cache", "canvas_inbox")
    os.makedirs(root, exist_ok=True)
    return root


def canvas_outbox_dir() -> str:
    root = os.path.join(canvas_inbox_dir(), "from_editor")
    os.makedirs(root, exist_ok=True)
    return root


# ── 批量任务注册表：V2/V3 分镜→批量生成→拼接 编排层 ──
_BATCH_JOBS: Dict[str, Any] = {}
import threading as _threading
_BATCH_LOCK = _threading.Lock()

# ── 单视频后处理任务注册表：超分/补帧后台执行，前端轮询进度与最终产物 ──
_POSTPROCESS_JOBS: Dict[str, Any] = {}
_POSTPROCESS_LOCK = _threading.Lock()

# ── 本地模型预载任务注册表：GFPGAN 等后台下载，前端轮询进度（非阻塞） ──
_MODEL_PRELOAD_JOBS: Dict[str, Any] = {}
_MODEL_PRELOAD_LOCK = _threading.Lock()
_GFPGAN_ONNX_REPO = "hacksider/deep-live-cam"
# 不同版本仓库内模型文件名不同，按序尝试
_GFPGAN_ONNX_FILES = ("GFPGANv1.4.onnx", "gfpgan-1024.onnx")


def start_gfpgan_preload() -> str:
    """保证 GFPGAN ONNX 后台预载；幂等，返回 job_id 供前端轮询进度。"""
    with _MODEL_PRELOAD_LOCK:
        for jid, job in _MODEL_PRELOAD_JOBS.items():
            if job.get("kind") == "gfpgan":
                return jid

    job_id = uuid.uuid4().hex[:12]
    with _MODEL_PRELOAD_LOCK:
        _MODEL_PRELOAD_JOBS[job_id] = {
            "job_id": job_id,
            "kind": "gfpgan",
            "status": "processing",
            "progress": 0,
            "message": "等待模型预载...",
            "ready": False,
            "created_at": time.time(),
            "updated_at": time.time(),
        }

    def _report(pct: int, message: str) -> None:
        with _MODEL_PRELOAD_LOCK:
            job = _MODEL_PRELOAD_JOBS.get(job_id)
            if job:
                job["progress"] = int(pct)
                job["message"] = message or ""
                job["updated_at"] = time.time()

    def _finish(ready: bool, message: str) -> None:
        with _MODEL_PRELOAD_LOCK:
            job = _MODEL_PRELOAD_JOBS.get(job_id)
            if job:
                job["status"] = "done"
                job["ready"] = bool(ready)
                job["progress"] = 100
                job["message"] = message
                job["updated_at"] = time.time()

    def _run() -> None:
        try:
            from app.core.neural_engine import get_neural_engine

            eng = get_neural_engine()
            if not getattr(eng, "is_available", False):
                _finish(False, "无可用神经网络后端")
                return
            # 任一候选文件已缓存即视为就绪
            for filename in _GFPGAN_ONNX_FILES:
                if eng.get_cached_model_path(_GFPGAN_ONNX_REPO, filename):
                    _finish(True, "GFPGAN 已就绪（缓存命中）")
                    return
            _report(10, "开始预载 GFPGAN（首次约 300MB，后续秒开）...")
            for filename in _GFPGAN_ONNX_FILES:
                try:
                    downloaded = eng.download_model(
                        _GFPGAN_ONNX_REPO,
                        filename=filename,
                        progress_cb=lambda msg, _f=filename: _report(40, f"[{_f}] {msg}"),
                    )
                except Exception as exc:
                    logger.debug("[ModelPreload] GFPGAN 下载失败 %s: %s", filename, exc)
                    downloaded = None
                if downloaded and os.path.isfile(downloaded):
                    _finish(True, "GFPGAN 预载完成")
                    return
            _finish(False, "GFPGAN 下载失败（将回退区域超分）")
        except Exception as exc:
            logger.debug("[ModelPreload] GFPGAN 预载异常: %s", exc)
            _finish(False, "GFPGAN 预载异常")

    threading.Thread(target=_run, daemon=True, name="gfpgan-preload").start()
    return job_id


def _ffmpeg_bin() -> str:
    import shutil as _shutil
    found = _shutil.which("ffmpeg")
    return found if found else "ffmpeg"


def _ffprobe_bin() -> str:
    import shutil as _shutil
    found = _shutil.which("ffprobe")
    return found if found else "ffprobe"


def _probe_duration(path: str) -> float:
    """用 ffprobe 获取媒体时长（秒），失败返回 0。"""
    if not path or not os.path.isfile(path):
        return 0.0
    try:
        import subprocess as _subprocess
        cmd = [
            _ffprobe_bin(),
            "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            path,
        ]
        flags = _subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
        r = _subprocess.run(cmd, capture_output=True, text=True, timeout=15, creationflags=flags)
        if r.returncode == 0 and r.stdout.strip():
            return float(r.stdout.strip())
    except Exception as e:
        logger.debug("_probe_duration 失败 %s: %s", os.path.basename(path), e)
    return 0.0


def _run_concat_demuxer(video_paths: List[str], output_path: str) -> Optional[str]:
    """FFmpeg concat demuxer（-c copy，不重编码，极快）。
    要求所有输入编码/分辨率/帧率一致，否则自动降级到 concat filter。"""
    if not video_paths:
        return None
    import subprocess as _subprocess
    # 写 concat list file
    list_path = output_path + ".concat.txt"
    try:
        with open(list_path, "w", encoding="utf-8") as f:
            for p in video_paths:
                # ffmpeg concat demuxer 对单引号敏感，用转义
                safe = p.replace("'", "'\\''")
                f.write(f"file '{safe}'\n")
        cmd = [
            _ffmpeg_bin(), "-y",
            "-f", "concat",
            "-safe", "0",
            "-i", list_path,
            "-c", "copy",
            "-movflags", "+faststart",
            output_path,
        ]
        flags = _subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
        r = _subprocess.run(cmd, capture_output=True, timeout=3600, creationflags=flags)
        if r.returncode == 0 and os.path.isfile(output_path) and os.path.getsize(output_path) > 1024:
            return output_path
        logger.warning("concat demuxer 失败，降级 concat filter: %s", (r.stderr or b"")[:300])
    except Exception as e:
        logger.warning("concat demuxer 异常，降级 concat filter: %s", e)
    finally:
        try:
            os.remove(list_path)
        except Exception as err:
            logger.debug("清理 concat 临时列表文件失败: %s", err, exc_info=True)
    # 降级：concat filter（重编码，兼容性强）
    try:
        n = len(video_paths)
        if n == 0:
            return None
        inputs_args: List[str] = []
        for p in video_paths:
            inputs_args += ["-i", p]
        filter_parts = []
        for i in range(n):
            filter_parts.append(f"[{i}:v]scale=trunc(iw/2)*2:trunc(ih/2)*2,setsar=1,fps=30[v{i}];")
        concat_inputs = "".join(f"[v{i}]" for i in range(n))
        filter_parts.append(f"{concat_inputs}concat=n={n}:v=1:a=0[vout]")
        cmd = (
            [_ffmpeg_bin(), "-y"]
            + inputs_args
            + [
                "-filter_complex", "".join(filter_parts),
                "-map", "[vout]",
                "-r", "30",
                "-pix_fmt", "yuv420p",
                "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
                "-movflags", "+faststart",
                output_path,
            ]
        )
        flags = _subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
        r = _subprocess.run(cmd, capture_output=True, timeout=3600, creationflags=flags)
        if r.returncode == 0 and os.path.isfile(output_path) and os.path.getsize(output_path) > 1024:
            return output_path
        logger.warning("concat filter 也失败了: %s", (r.stderr or b"")[:300])
    except Exception as e:
        logger.warning("concat filter 异常: %s", e)
    return None


def _run_concat_xfade(video_paths: List[str], output_path: str, transition_sec: float = 0.5) -> Optional[str]:
    """带 xfade 转场的拼接。比 concat filter 更慢但画面过渡平滑。"""
    if len(video_paths) < 2:
        return _run_concat_demuxer(video_paths, output_path)
    import subprocess as _subprocess
    durations = [_probe_duration(p) for p in video_paths]
    # xfade 需要精确 offset = cumulative duration - transition_sec
    try:
        n = len(video_paths)
        inputs_args: List[str] = []
        for p in video_paths:
            inputs_args += ["-i", p]
        # filter_complex: 两两 xfade
        fc_parts: List[str] = []
        # scale + fps + sar normalize for all
        norm = []
        for i in range(n):
            norm.append(f"[{i}:v]scale=trunc(iw/2)*2:trunc(ih/2)*2,setsar=1,fps=30[v{i}n];")
        fc_parts.extend(norm)
        cur_label = "v0n"
        offset = durations[0] - transition_sec
        if offset < 0:
            offset = 0
        for i in range(1, n):
            next_label = f"v{i}n"
            out_label = f"v{i}xf" if i < n - 1 else "vout"
            fc_parts.append(f"[{cur_label}][{next_label}]xfade=transition=fade:duration={transition_sec}:offset={offset}[{out_label}];")
            cur_label = out_label
            offset += durations[i] - transition_sec
        cmd = (
            [_ffmpeg_bin(), "-y"]
            + inputs_args
            + [
                "-filter_complex", "".join(fc_parts),
                "-map", "[vout]",
                "-r", "30",
                "-pix_fmt", "yuv420p",
                "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
                "-movflags", "+faststart",
                output_path,
            ]
        )
        flags = _subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
        r = _subprocess.run(cmd, capture_output=True, timeout=3600, creationflags=flags)
        if r.returncode == 0 and os.path.isfile(output_path) and os.path.getsize(output_path) > 1024:
            return output_path
        logger.warning("xfade 失败，降级 concat filter: %s", (r.stderr or b"")[:300])
    except Exception as e:
        logger.warning("xfade 异常，降级 concat filter: %s", e)
    return _run_concat_demuxer(video_paths, output_path)


def canvas_characters_media_dir(char_id: str = "default") -> str:
    root = os.path.join(
        os.path.expanduser("~"), ".video_editor_cache", "characters", "media", char_id
    )
    os.makedirs(root, exist_ok=True)
    return root


def _safe_filename(name: str) -> str:
    base = os.path.basename(name or "asset.bin").replace("..", "_")
    keep = "".join(c for c in base if c.isalnum() or c in "._- ()[]")
    return keep or f"asset_{uuid.uuid4().hex[:8]}.bin"


def ingest_local_file(
    src_path: str,
    *,
    title: str = "",
    character_id: str = "",
    character_name: str = "",
    send_to_editor: bool = True,
    enable_interpolation: bool = False,
    source: str = "infinite_canvas",
    duration_sec: float = 0.0,
    canvas_node_id: str = "",
    canvas_kind: str = "",
    generation: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """复制本地文件到 inbox，可选入轨 / 挂角色资产。

    ``generation``：画布节点生成参数血缘块（可选，缺省零行为变化）；
    随 MATERIAL_TO_TIMELINE 载荷透传，由剪辑侧盖章进 clip["generation"]。
    """
    inbox = os.path.abspath(canvas_inbox_dir())
    path = os.path.abspath(src_path)
    if not os.path.isfile(path):
        return {"success": False, "message": f"文件不存在: {path}"}

    ext = os.path.splitext(path)[1].lower()
    dest_name = os.path.basename(path)
    if os.path.dirname(path) == inbox:
        dest = path
    else:
        dest_name = f"{int(time.time())}_{_safe_filename(os.path.basename(path))}"
        dest = os.path.join(inbox, dest_name)
        try:
            shutil.copy2(path, dest)
        except Exception as e:
            return {"success": False, "message": f"复制失败: {e}"}

    asset = {
        "id": f"canvas_{uuid.uuid4().hex[:12]}",
        "path": dest,
        "title": title or os.path.basename(path),
        "ext": ext,
        "kind": "video" if ext in (".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v") else "image",
        "character_id": character_id or "",
        "character_name": character_name or "",
        "source": source,
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "enable_interpolation": bool(enable_interpolation),
        "duration_sec": float(duration_sec) if duration_sec else None,
    }

    if character_id:
        try:
            media_dir = canvas_characters_media_dir(character_id)
            linked = os.path.join(media_dir, dest_name)
            if not os.path.isfile(linked):
                shutil.copy2(dest, linked)
            asset["character_media_path"] = linked
            _append_character_asset(character_id, asset)
        except Exception as e:
            logger.warning("挂角色资产失败: %s", e)

    result: Dict[str, Any] = {
        "success": True,
        "message": f"已入库: {os.path.basename(dest)}",
        "asset": asset,
        "file_path": dest,
    }

    if send_to_editor:
        send_res = emit_canvas_to_editor(
            dest,
            title=asset["title"],
            source=source,
            enable_interpolation=enable_interpolation,
            kind=asset["kind"],
            duration_sec=float(duration_sec) if duration_sec else 0.0,
            canvas_node_id=canvas_node_id,
            canvas_kind=canvas_kind or asset["kind"],
            generation=generation,
        )
        result["editor"] = send_res
        if not send_res.get("success"):
            result["message"] = send_res.get("message") or result["message"]
            result["success"] = bool(send_res.get("success"))

    return result


def _append_character_asset(character_id: str, asset: Dict[str, Any]) -> None:
    try:
        from app.modules.lego.character_management_module import CharacterStore
    except ImportError:
        from modules.lego.character_management_module import CharacterStore  # type: ignore

    store = CharacterStore()
    char = store.get(character_id)
    if not char:
        return
    assets = list(char.get("generated_assets") or [])
    assets.append(
        {
            "id": asset.get("id"),
            "path": asset.get("character_media_path") or asset.get("path"),
            "kind": asset.get("kind"),
            "title": asset.get("title"),
            "created_at": asset.get("created_at"),
            "source": asset.get("source"),
        }
    )
    # 保留最近 50 条
    store.update(character_id, {"generated_assets": assets[-50:]})


def _image_to_still_video(image_path: str, duration_sec: float = 3.0) -> Optional[str]:
    """把静图转成短视频，便于入时间线。失败返回 None。"""
    ext = os.path.splitext(image_path)[1].lower()
    if ext not in (".png", ".jpg", ".jpeg", ".webp", ".bmp"):
        return None
    out = os.path.join(
        canvas_inbox_dir(),
        f"{int(time.time())}_{_safe_filename(os.path.splitext(os.path.basename(image_path))[0])}.still.mp4",
    )
    ffmpeg = "ffmpeg"
    try:
        import shutil

        found = shutil.which("ffmpeg")
        if found:
            ffmpeg = found
    except Exception as exc:
        logger.debug("探测 ffmpeg 路径失败，回退到默认 'ffmpeg': %s", exc, exc_info=True)
    cmd = [
        ffmpeg,
        "-y",
        "-loop",
        "1",
        "-i",
        image_path,
        "-t",
        str(max(0.5, float(duration_sec))),
        "-vf",
        "scale=trunc(iw/2)*2:trunc(ih/2)*2",
        "-pix_fmt",
        "yuv420p",
        "-r",
        "30",
        out,
    ]
    try:
        import subprocess
        import sys

        flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
        r = subprocess.run(cmd, capture_output=True, timeout=60, creationflags=flags)
        if r.returncode == 0 and os.path.isfile(out):
            return out
        logger.warning("静图转视频失败: %s", (r.stderr or b"")[:200])
    except Exception as e:
        logger.warning("静图转视频异常: %s", e)
    return None


def emit_canvas_to_editor(
    file_path: str,
    *,
    title: str = "",
    source: str = "infinite_canvas",
    enable_interpolation: bool = False,
    kind: str = "",
    duration_sec: float = 0.0,
    canvas_node_id: str = "",
    canvas_kind: str = "",
    generation: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """推送到剪辑模块。

    ``generation``：生成参数血缘块（可选，缺省零行为变化）；非空才进载荷，
    剪辑侧 ``extra_from_material_payload`` 白名单清洗后盖章进 clip。
    """
    path = os.path.abspath(file_path)
    if not os.path.isfile(path):
        return {"success": False, "message": f"文件不存在: {path}"}

    resolved_kind = kind
    if not resolved_kind:
        ext = os.path.splitext(path)[1].lower()
        resolved_kind = (
            "video"
            if ext in (".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v")
            else "image"
        )

    timeline_path = path
    if resolved_kind == "image":
        dur = float(duration_sec) if duration_sec and float(duration_sec) > 0 else 3.0
        still = _image_to_still_video(path, duration_sec=dur)
        if still:
            timeline_path = still
            resolved_kind = "video"
        else:
            return {
                "success": False,
                "message": "图片入轨需要 ffmpeg 转成短视频，未找到可用 ffmpeg",
                "file_path": path,
            }

    try:
        from app.modules.lego.core import EventBus, EventType
    except ImportError:
        from modules.lego.core import EventBus, EventType  # type: ignore

    bus = EventBus.get_instance()
    bus.emit(
        EventType.MODULE_ACTIVATED,
        {
            "target": "editor",
            "hint": f"画布素材已发送到剪辑：{title or os.path.basename(path)}",
            "source": source,
        },
        source=source,
    )
    payload = {
        "file_path": timeline_path,
        "title": title,
        "source": source,
        "kind": resolved_kind,
        "enable_interpolation": bool(enable_interpolation),
        "original_path": path,
    }
    if duration_sec and float(duration_sec) > 0:
        payload["duration_hint"] = float(duration_sec)
    if canvas_node_id:
        payload["canvas_node_id"] = str(canvas_node_id)
        payload["node_id"] = str(canvas_node_id)
    if canvas_kind:
        payload["canvas_kind"] = str(canvas_kind)
    if generation:
        # 生成参数血缘块：非空才进载荷（缺省零行为变化），剪辑侧白名单清洗
        payload["generation"] = dict(generation)
    bus.emit(
        EventType.MATERIAL_TO_TIMELINE,
        payload,
        source=source,
    )
    return {
        "success": True,
        "message": f"已发送到剪辑：{os.path.basename(timeline_path)}",
        "file_path": timeline_path,
        "enable_interpolation": bool(enable_interpolation),
        "duration_sec": float(duration_sec) if duration_sec else None,
    }




def push_editor_to_canvas(
    src_path: str,
    *,
    title: str = "",
    source: str = "editor",
    extra: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """剪辑 → 画布 outbox（供 inject / React 拉取并自动落源节点）。"""
    path = os.path.abspath(src_path)
    if not os.path.isfile(path):
        return {"success": False, "message": f"文件不存在: {path}"}

    dest_name = f"{int(time.time())}_{_safe_filename(os.path.basename(path))}"
    dest = os.path.join(canvas_outbox_dir(), dest_name)
    try:
        shutil.copy2(path, dest)
    except Exception as e:
        return {"success": False, "message": f"复制失败: {e}"}

    item = {
        "id": f"ed_{uuid.uuid4().hex[:10]}",
        "path": dest,
        "title": title or os.path.basename(path),
        "filename": dest_name,
        "ext": os.path.splitext(path)[1].lower(),
        "source": source,
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "url": f"/editor_file/{dest_name}",
    }
    if extra:
        for k, v in extra.items():
            if v is None or v == "":
                continue
            item[k] = v
    with _OUTBOX_LOCK:
        _EDITOR_OUTBOX.append(item)
        # 保留最近 30
        while len(_EDITOR_OUTBOX) > 30:
            _EDITOR_OUTBOX.pop(0)

    try:
        from app.modules.lego.core import EventBus, EventType
    except ImportError:
        from modules.lego.core import EventBus, EventType  # type: ignore

    bus = EventBus.get_instance()
    bus.emit(
        EventType.MODULE_ACTIVATED,
        {
            "target": "characters",
            "hint": f"剪辑素材已推送到画布：{item['title']}",
            "source": source,
        },
        source=source,
    )
    if hasattr(EventType, "TIMELINE_TO_CANVAS"):
        bus.emit(
            EventType.TIMELINE_TO_CANVAS,
            item,
            source=source,
        )

    return {
        "success": True,
        "message": f"已推送到画布：{item['title']}",
        "item": item,
    }




def list_editor_outbox() -> List[Dict[str, Any]]:
    with _OUTBOX_LOCK:
        return list(_EDITOR_OUTBOX)

# HTTP 服务层（_BridgeHandler / CanvasBridgeServer / inject.js）已拆到 canvas_server.py，
# 此处 re-export 保持向后兼容。
# 2026-10-09 改为**懒 re-export**（PEP 562 __getattr__）：顶层 from-import 在
# 「bridge 先于 server 完成 import」的进程里会撞 partially-initialized（实测：
# _verify/check_poweron_e2e.py 新进程必炸）。懒导只在**属性首次访问**时发生，
# 那时两个模块都已初始化完毕 —— 两种导入顺序都能活。
_BRIDGE_REEXPORTS = ("_check_host_token", "_BridgeHandler", "_build_inject_js",
                     "CanvasBridgeServer", "get_canvas_bridge")


def __getattr__(name: str):
    if name in _BRIDGE_REEXPORTS:
        import app.core.canvas_server as _cs
        return getattr(_cs, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

