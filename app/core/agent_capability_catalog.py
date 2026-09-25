# -*- coding: utf-8 -*-
"""Agent 能力目录 —— capability 元数据的单一事实来源。

为什么需要这个文件
--------------------
此前同一个 capability 要散落在 4 处各写一份、靠人工对齐：
  1. ``capability_handlers.py`` 的 ``dispatcher.register(...)``（运行时真相）
  2. ``agent_policy._CAPABILITY_EFFECTS``（effect / paid 映射）
  3. ``agent_brain._NEURON_TAXONOMY``（左右脑归属 / 标签 / 关键词）
  4. ``agent_action_registry`` 的 action 行（对话面，与 capability 的映射）

漏写任何一处都不报错、只表现为「静默失效」——历史已踩过：
  - ``editor.inspect_media`` / ``editor.get_media`` 注册了却没进 policy 的
    ``_CAPABILITY_EFFECTS``，策略引擎把它们当成「未登记 = FILE_WRITE」兜底，
    读素材被误判成写文件（协作模式会错误地要求确认）；
  - ``memory.suggest`` 在 policy 里有 effect 却从未注册 handler；
  - 9 个已注册能力没有脑归属，靠 ``sync_from_dispatcher`` 兜底成无标签的胼胝体神经元。

本文件把「capability → (category, effect, paid, description, 脑归属, 标签, 关键词)」
收敛成一张表，其余三处全部由此派生：
  - ``agent_policy._CAPABILITY_EFFECTS`` = ``capability_effect_paid()``
  - ``agent_brain._NEURON_TAXONOMY``  = ``neuron_taxonomy()``
  - ``capability_handlers.register_builtin_handlers`` 末尾用
    ``verify_catalog_consistency()`` 做双向对齐守卫（漏注册 / 漏登记都会告警）。

新增能力时的唯一入口：在本表加一行，其余三处自动跟上。不要再各写一份。

effect 语义（与 agent_policy.EFFECT_* 一致）：
  read / canvas_write / file_write / media_write / memory_write
hemisphere 语义（字符串，agent_brain 负责转成 BrainHemisphere 枚举）：
  right（创意）/ left（逻辑）/ cc（胼胝体·混合）
"""
from __future__ import annotations

from typing import Dict, List, Optional, Tuple

# ═══════════════════════════════════════════════════════════════════
# 单一事实来源表
# (capability_id, category, effect, paid, description, hemisphere, label, keywords)
# ═══════════════════════════════════════════════════════════════════


def _canvas_node_catalog_rows() -> List[Tuple[str, str, str, bool, str, str, str, List[str]]]:
    """画布节点级 capability 目录行（canvas_tools 后端化，2026-09-15）。

    由 ``agent_action_registry._CANVAS_ACTION_ROWS`` 派生（画布动作的单一事实来源），
    避免「画布动作清单」与「能力目录」两处手写越改越分裂。节点状态在前端，
    后端只能经 SSE task.create 桥接执行，故 effect 沿用动作表的 read / canvas_write。
    """
    from app.core.agent_action_registry import canvas_node_capabilities

    rows: List[Tuple[str, str, str, bool, str, str, str, List[str]]] = []
    for c in canvas_node_capabilities():
        cap_id = c["capability_id"]
        effect = c["effect"]
        desc = c["description"]
        label = desc.split("（")[0].strip()
        rows.append(
            (
                cap_id,
                "canvas",
                effect,
                False,
                f"画布节点操作：{desc}",
                "cc",
                label,
                [c["action"], label],
            )
        )
    return rows


CAPABILITY_ROWS: List[Tuple[str, str, str, bool, str, str, str, List[str]]] = [
    # ── 拓展 ──
    ("ext.run_extension", "extension", "file_write", False,
     "运行拓展中心插件/Skill/MCP", "right", "拓展插件", ["插件", "拓展", "效果"]),
    ("ext.run_skill", "extension", "file_write", False,
     "通过 SkillEngine 执行 Skill", "right", "技能执行", ["技能", "skill", "导演"]),
    ("ext.list_tools", "extension", "read", False,
     "列出所有可用拓展工具", "cc", "拓展工具列表", ["工具", "列表"]),

    # ── 模型 ──
    ("model.chat", "model", "read", True,
     "调用指定 AI 提供者", "right", "AI 对话", ["对话", "聊天", "问答", "生成文案"]),
    ("model.chat_with_fallback", "model", "read", True,
     "智能降级调用 AI", "right", "AI 智能降级", ["降级", "回退", "智能调用"]),
    ("model.list_models", "model", "read", False,
     "列出可用 AI 提供者", "cc", "模型列表", ["模型", "列表", "可用"]),

    # ── 画布 ──
    ("canvas.open", "canvas", "read", False,
     "打开 AI 画布模块", "cc", "打开画布", ["画布", "打开"]),
    ("canvas.sync_models", "canvas", "read", False,
     "同步模型管理渠道到画布", "cc", "同步模型池", ["同步", "模型池"]),
    ("canvas.list_actions", "canvas", "read", False,
     "输出统一画布动作清单（单一事实来源）", "cc", "画布动作清单", ["画布动作", "清单"]),

    # ── 画布生成（Agent 可驱动后端 /host/* 生成链路，2026-09-15）──
    # effect=media_write：产媒体，协作模式需确认；generate_image/video 走模型广场付费渠道。
    ("canvas.generate_image", "canvas", "media_write", True,
     "画布生图（模型广场 AIGC 渠道）", "right", "画布生图",
     ["生图", "画图", "图片生成", "文生图", "generate_image"]),
    ("canvas.generate_video", "canvas", "media_write", True,
     "画布生视频（模型广场 AIGC 渠道）", "right", "画布生视频",
     ["生视频", "视频生成", "文生视频", "generate_video"]),
    ("canvas.comfyui_run", "canvas", "media_write", False,
     "运行 ComfyUI 工作流（本地引擎，支持 dry-run 演练）", "right", "ComfyUI 执行",
     ["comfyui", "工作流", "节点执行", "workflow"]),
    ("canvas.concat_videos", "canvas", "media_write", False,
     "拼接多段视频成片（FFmpeg）", "cc", "视频拼接",
     ["拼接", "合并", "成片", "concat", "视频拼接"]),
    ("canvas.image_to_video", "canvas", "media_write", False,
     "静帧图转伪视频（成片闭环用）", "cc", "图转视频",
     ["图转视频", "静帧", "still", "图片转视频"]),

    # ── 剪辑 ──
    ("editor.split_clip", "editor", "canvas_write", False,
     "切分片段", "left", "片段切分", ["切分", "切割", "split"]),
    ("editor.apply_filter", "editor", "canvas_write", False,
     "应用滤镜", "left", "应用滤镜", ["滤镜", "调色", "filter"]),
    ("editor.add_transition", "editor", "canvas_write", False,
     "添加转场", "left", "添加转场", ["转场", "过渡", "transition"]),
    ("editor.get_timeline_context", "editor", "read", False,
     "获取时间线上下文", "left", "时间线上下文", ["时间线", "上下文", "轨道"]),
    ("editor.inspect_media", "editor", "read", False,
     "读取素材元信息（分辨率/场景/音频情绪）", "left", "素材元信息",
     ["素材", "元信息", "inspect", "分辨率"]),
    ("editor.get_media", "editor", "read", False,
     "读取素材元信息（inspect_media 别名）", "left", "素材元信息",
     ["素材", "元信息", "get_media"]),
    ("editor.set_clip_properties", "editor", "canvas_write", False,
     "设置片段属性（变速/倒放等）", "left", "片段属性",
     ["属性", "变速", "倒放", "speed"]),
    ("editor.set_keyframes", "editor", "canvas_write", False,
     "批量写入关键帧（含插值/缓动）", "left", "关键帧写入",
     ["关键帧", "keyframe", "插值"]),
    ("editor.ripple_delete_range", "editor", "canvas_write", False,
     "波纹删除时间线区间", "left", "波纹删除区间",
     ["波纹删", "波纹删除", "ripple"]),
    ("editor.trim_clip", "editor", "canvas_write", False,
     "裁剪片段（时长/入点/出点，可撤销）", "left", "裁剪片段",
     ["裁剪", "修剪", "trim", "缩短"]),
    ("editor.move_clip", "editor", "canvas_write", False,
     "移动片段到新时间点（可撤销）", "left", "移动片段",
     ["移动", "挪动", "换位", "move"]),
    ("editor.suggest_cleanup", "editor", "read", False,
     "建议去水词/静音并确认后执行", "left", "去水词建议确认",
     ["去水词", "清静音", "填充词", "suggest_cleanup"]),
    ("editor.send_selected_to_canvas", "editor", "canvas_write", False,
     "选中片段推到 AI 画布", "cc", "送画布", ["送画布", "推画布", "roundtrip"]),
    ("editor.suggest_canvas_roundtrip", "editor", "read", False,
     "建议哪些片送到画布做变体", "cc", "建议送画布",
     ["建议送画布", "变体", "roundtrip"]),
    ("editor.reanchor_clips", "editor", "canvas_write", False,
     "按新台词重锚片段（默认只出计划，确认后落地）", "left", "重锚片段",
     ["重锚", "锚定", "改文案", "重新对齐", "reanchor", "词锚定"]),

    # ── 多任务调度 ──
    ("workflow.submit_batch", "workflow", "file_write", False,
     "提交批量任务", "left", "批量任务", ["批量", "任务", "batch"]),

    # ── Agent 全链路闭环 ──
    ("pipeline.route", "pipeline", "read", False,
     "业务分流：AI生成/素材剪辑", "cc", "业务分流", ["分流", "路由", "判断"]),
    ("pipeline.generate", "pipeline", "media_write", True,
     "AI视频生成业务线", "right", "AI 视频生成", ["生成", "视频", "抽卡", "画面"]),
    ("pipeline.quote", "pipeline", "read", False,
     "生成前报价：预计花费+可用渠道+配额健康", "left", "生成报价",
     ["报价", "花费", "成本", "额度", "配额"]),
    ("pipeline.preview_validate", "pipeline", "read", False,
     "预览校验：轨道排布+画面质检", "left", "预览校验", ["预览", "校验", "质检"]),
    ("pipeline.regenerate_clip", "pipeline", "media_write", True,
     "局部重生成替换片段", "left", "局部重生成", ["重生成", "替换", "局部"]),
    ("pipeline.score", "pipeline", "read", False,
     "五维量化打分+分级筛选", "cc", "五维打分", ["打分", "评分", "等级"]),
    ("pipeline.generate_script", "pipeline", "read", True,
     "剪辑创意脚本生成", "right", "剪辑脚本生成", ["脚本", "创意", "镜头顺序", "配乐"]),
    ("pipeline.execute_editing", "pipeline", "canvas_write", False,
     "精修剪辑+成片输出", "left", "精剪成片", ["精剪", "成片", "导出", "剪辑"]),
    ("pipeline.run_full", "pipeline", "file_write", True,
     "全链路一键执行", "cc", "全链路执行", ["全链路", "一键", "完整"]),
    # ── P1-3 异步任务模型（submit/status/fetch/cancel）──
    ("pipeline.submit", "pipeline", "file_write", True,
     "全链路异步提交：立即返回任务号，进度可查、可取消", "cc", "提交管线任务",
     ["提交任务", "异步执行", "后台任务", "submit", "跑起来"]),
    ("pipeline.job_status", "pipeline", "read", False,
     "管线任务状态/进度/结果查询（不给任务号则列近期任务）", "left", "任务状态",
     ["任务状态", "进度", "查询任务", "job_status", "跑到哪了"]),
    ("pipeline.job_cancel", "pipeline", "read", False,
     "取消管线任务：排队真取消；运行中段间生效、结果丢弃", "left", "取消任务",
     ["取消任务", "中止任务", "别生成了", "job_cancel"]),
    ("pipeline.llm_health", "pipeline", "read", False,
     "LLM 降级率：各站点近24h降级统计", "left", "LLM降级率",
     ["降级", "降级率", "LLM健康", "关键词匹配", "质量打折"]),
    # ── 汉字注音（离线确定性字典，2026-09-25）──
    # effect=read：只查表不写数据。左脑（语言/逻辑类，与 tts_polish 的 right 区分）
    ("pipeline.pinyin_lookup", "pipeline", "read", False,
     "汉字注音查询：逐字注音 + 多音字候选 + 生僻字，离线字典不依赖 LLM", "left", "注音查询",
     ["注音", "拼音", "怎么读", "读音", "多音字", "生僻字", "念什么", "pinyin",
      "注音字典", "发音"]),
    # ── 生成质量守护（治 AI 生成「长文本漂移 / 表情夸张 / 人物漂移 / 武器畸形」）──
    # effect=read：只出计划不写数据（切段/注音/回读质检均为只读计算）
    ("pipeline.tts_polish", "pipeline", "read", False,
     "TTS 正音：长台词语义切段 + 多音字注音，治配音长文本漂移", "right", "TTS正音",
     ["配音", "正音", "多音字", "读音", "切段", "tts", "字幕不符", "长文本"]),
    ("pipeline.character_anchor", "pipeline", "read", False,
     "角色一致性锚定：跨镜头特征卡 + 漂移检测，治人物形象漂移", "right", "角色锚定",
     ["人物漂移", "角色一致", "锚定", "跨镜头", "长相不一致", "character_anchor"]),
    ("pipeline.expression_clamp", "pipeline", "read", False,
     "表情幅度守护：权重钳制 + 帧间限幅 + 幅度质检，治表情夸张", "right", "表情幅度",
     ["表情夸张", "鼓腮", "幅度", "钳制", "clamp", "面部扭曲", "expression_clamp"]),
    ("pipeline.prop_consistency", "pipeline", "read", False,
     "手持道具守护：结构约束 + 握持描述 + 道具漂移检测，治武器结构畸形", "right", "道具守护",
     ["武器畸形", "道具", "握持", "结构", "三通", "分支", "prop_consistency"]),
    ("pipeline.guard_all", "pipeline", "read", False,
     "生成质量守护总入口：一次跑多个守护 + 合并全量负面词", "cc", "守护总入口",
     ["守护", "质检", "生成质量", "负面词", "guard_all"]),
    # ── 导演分身·可调用能力（LibTV 对标，2026-09-26）──
    # effect=read：只拆解/规划，不写画布、不落时间线（落地走 ext.run_skill director 的
    # source_dir 通路或画布节点）。与画布 /host/storyboard-* 同一实现。
    ("pipeline.director_breakdown", "pipeline", "read", False,
     "导演分身·拆分镜：剧本→结构化分镜表（默认启发式零成本，可选 LLM）", "right", "导演拆分镜",
     ["拆分镜", "分镜", "拉片", "拆解", "导演", "breakdown", "storyboard", "director"]),
    ("pipeline.director_camera_plan", "pipeline", "read", False,
     "导演分身·机位/运镜规划：分镜表→机位+运镜路径（可喂 Stage3D）", "left", "导演机位规划",
     ["机位", "运镜", "相机", "提示词", "camera", "camera_plan", "导演", "导演分身"]),
] + _canvas_node_catalog_rows()

# 策略层专属工具：只在 agent_policy 有 effect/paid，**没有** dispatcher handler，
# 由 memory_store 直接调用 decide() 判定是否允许写入用户偏好。不在神经元表里。
POLICY_ONLY_TOOLS: Dict[str, Tuple[str, bool]] = {
    "memory.suggest": ("memory_write", False),
}

_VALID_EFFECTS = {"read", "canvas_write", "file_write", "media_write", "memory_write"}
_VALID_HEMI = {"right", "left", "cc"}


def capability_effect_paid() -> Dict[str, Tuple[str, bool]]:
    """由本表派生 capability_id → (effect, paid)，含 policy-only 工具。

    供 agent_policy._CAPABILITY_EFFECTS 使用 —— 与旧版硬编码表逐项等价，
    但补上了此前漏登记的 editor.inspect_media / editor.get_media（read）。
    """
    out: Dict[str, Tuple[str, bool]] = {}
    for cid, _cat, eff, paid, _desc, _hemi, _label, _kw in CAPABILITY_ROWS:
        out[cid] = (eff, paid)
    out.update(POLICY_ONLY_TOOLS)
    return out


def neuron_taxonomy() -> List[Tuple[str, str, str, List[str]]]:
    """由本表派生神经元表：(capability_id, hemisphere, label, keywords)。

    hemisphere 用字符串（right/left/cc），agent_brain 负责转成 BrainHemisphere 枚举，
    避免本模块 import agent_brain 造成循环依赖。
    """
    return [
        (cid, hemi, label, list(kw))
        for cid, _cat, _eff, _paid, _desc, hemi, label, kw in CAPABILITY_ROWS
    ]


def registered_capability_ids() -> List[str]:
    """本目录覆盖的（应被 dispatcher 注册的）capability id 列表。"""
    return [cid for cid, *_rest in CAPABILITY_ROWS]


def verify_catalog_consistency(registered_ids: Optional[set]) -> List[str]:
    """双向对齐守卫：目录 ↔ 真实注册，返回问题清单（空 = 一致）。

    - 目录里有、没注册 → 运行时 ``invoke`` 会报「未知能力」
    - 注册了、目录里没有 → 该能力没有 effect/脑归属，会落「未登记 = FILE_WRITE」兜底
      （这正是 editor.inspect_media 曾经踩过的坑）
    """
    problems: List[str] = []
    registered = set(registered_ids or [])
    catalog_ids = set(registered_capability_ids())

    missing_reg = sorted(catalog_ids - registered)
    for cid in missing_reg:
        problems.append(f"目录登记但未注册：{cid}（invoke 会报未知能力）")

    missing_cat = sorted(registered - catalog_ids)
    for cid in missing_cat:
        problems.append(
            f"已注册但目录缺失：{cid}（无 effect/脑归属，策略会落 FILE_WRITE 兜底）"
        )

    # 目录自身字段合法性
    for cid, _cat, eff, _paid, desc, hemi, _label, _kw in CAPABILITY_ROWS:
        if eff not in _VALID_EFFECTS:
            problems.append(f"{cid} effect 非法：{eff!r}")
        if hemi not in _VALID_HEMI:
            problems.append(f"{cid} hemisphere 非法：{hemi!r}")
        if not desc:
            problems.append(f"{cid} 缺少 description")

    return problems
