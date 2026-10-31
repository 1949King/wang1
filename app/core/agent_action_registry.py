"""
对话 Agent action 注册表（单一事实来源）
=====================================
对齐 OpenTake「工具可枚举」+ ClipSkills「决策/知识/执行」分层：
白名单 / 提示词 / capability 别名同出一处。

不改时间线真相源；不引入 Tauri/Dify/Wails。

跨层边界说明：
- 本文件定义的是**剪辑侧 action**（editor.split_clip / ext.run_extension 等 17 个），
  由后端 CapabilityDispatcher 执行。
- **画布侧 action**（addNode / updateNode / connectNodes / deleteNode / runGenerate /
  setNodeImage / setNodeVideo / importImage 等 9 个）硬编码在前端
  ``vendor/shiguang-canvas/src/AgentPanel.tsx`` 的 ``executeRemoteTask()`` 中，
  由前端直接操作 Zustand store 执行。
- 两侧通过 SSE ``task.create`` 事件（payload.action + payload.params）桥接，
  由后端 ``project_agent_host.push_to_canvas()`` 推送。
"""
from __future__ import annotations

import re

from typing import Dict, FrozenSet, List, Optional, Tuple

# (action, danger_level, capability_id|None, 给模型的一句话说明)
# danger_level: "safe" | "dangerous"
_AGENT_ACTION_ROWS: Tuple[Tuple[str, str, Optional[str], str], ...] = (
    ("answer", "safe", None, "仅回复咨询，不改时间线"),
    ("info", "safe", None, "同 answer"),
    ("get_media", "safe", "editor.inspect_media", "读取素材元信息（分辨率/场景/音频情绪）"),
    ("inspect_media", "safe", "editor.inspect_media", "get_media 别名（deep=true 追加语义/情绪）"),
    ("add_track", "safe", None, "新增轨道（本地 UI，无 capability）"),
    ("duplicate_clip", "safe", None, "复制片段（本地，无 capability）"),
    ("trim_clip", "safe", "editor.trim_clip", "裁剪时长/入点/出点（可撤销）"),
    ("split_clip", "safe", "editor.split_clip", "在指定时间切分"),
    ("add_transition", "safe", "editor.add_transition", "片段边缘转场"),
    ("transition", "safe", "editor.add_transition", "add_transition 别名"),
    ("add_effect", "safe", "editor.apply_filter", "滤镜/特效；滤镜走 apply_filter"),
    ("apply_filter", "safe", "editor.apply_filter", "命名滤镜"),
    ("call_extension", "safe", "ext.run_extension", "拓展/Skill/MCP"),
    ("call_model", "safe", "model.chat_with_fallback", "再调一次模型"),
    ("suggest_cleanup", "safe", "editor.suggest_cleanup", "去水词/静音建议+确认 UI"),
    ("canvas_sync_models", "safe", "canvas.sync_models", "同步模型管理渠道到画布"),
    ("canvas_open", "safe", "canvas.open", "打开 AI 画布模块"),
    # YuE（乐）全曲生成：本地/远程执行端（非云付费）⇒ safe；未配置时诚实失败
    ("yue_plan", "safe", "canvas.yue_plan",
     "YuE 符号规划：歌词+风格 → 可编辑的旋律+和弦乐谱（不出音频、不花钱；翻唱可先转录）"),
    ("yue_render", "safe", "canvas.yue_render",
     "YuE 渲染整曲：乐谱（可编辑）→ 48kHz 完整歌曲（耗时较长，首次需下模型）"),
    ("yue_transcribe", "safe", "canvas.yue_transcribe",
     "YuE 翻唱前置：参考曲 → 旋律乐谱（SheetSage2，只留旋律去和弦）"),
    ("remove_clip", "dangerous", None, "删除片段（本地）"),
    ("ripple_delete", "dangerous", "editor.ripple_delete_range", "无区间时降级为 remove_clip"),
    ("ripple_delete_range", "dangerous", "editor.ripple_delete_range", "波纹删 [t_in,t_out)"),
    ("move_clip", "safe", "editor.move_clip", "移动片段到新时间点（可撤销）"),
    ("change_speed", "safe", "editor.set_clip_properties", "变速/倒放（写 speed/reverse）"),
    ("add_keyframe", "safe", "editor.set_keyframes", "写入关键帧（单点或批量）"),
    ("set_keyframes", "safe", "editor.set_keyframes", "批量写入关键帧+插值+缓动"),
    ("reanchor_clips", "safe", "editor.reanchor_clips", "改文案后按新台词重排片段（默认只出计划）"),
    ("pinyin_lookup", "safe", "pipeline.pinyin_lookup", "汉字注音查询：逐字注音+多音字候选+生僻字（离线字典，不依赖 LLM）"),
    ("tts_polish", "safe", "pipeline.tts_polish", "长台词正音+切段（治配音长文本漂移；可回读质检）"),
    ("character_anchor", "safe", "pipeline.character_anchor", "角色一致性锚定+漂移检测（治人物跨镜头漂移）"),
    ("expression_clamp", "safe", "pipeline.expression_clamp", "表情幅度钳制+质检（治鼓腮等表情夸张）"),
    ("prop_consistency", "safe", "pipeline.prop_consistency", "手持道具守护（结构约束+握持描述，治武器结构畸形）"),
    ("guard_all", "safe", "pipeline.guard_all", "生成质量守护总入口（多守护一次跑+全量负面词）"),
    ("quote_cost", "safe", "pipeline.quote", "生成前报价（预计花费+可用渠道+配额健康，不生成）"),
    # V4.44「代码 × 扩散」混合视频：计划态只读 ⇒ safe（渲染 V4.45 落地后再评估级别）
    ("code_video_plan", "safe", "pipeline.code_video_plan",
     "代码×扩散混合视频规划：分镜表→CodeVideoSpec 草案（契约编译；计划态，不渲染）"),
    # V4.45：渲染写盘 + 长耗时（≤6 分钟）⇒ dangerous（collaborative 需确认；写操作不自动重试）
    ("code_video_render", "dangerous", "pipeline.code_video_render",
     "代码×扩散混合视频渲染：Chromium 逐帧 + ffmpeg 编码，产物落画布 inbox（长耗时，需确认）"),
    # 2026-10-20 精剪线：只读审计/计划 ⇒ safe
    ("precision_audit", "safe", "editor.precision_audit",
     "帧级精剪审计：非帧网格/次帧缝隙/重叠/音画偏移（只读）"),
    ("precision_align_plan", "safe", "editor.precision_align_plan",
     "帧对齐计划：吸附 start_time/duration 并同步 out_point（只出计划，不改时间线）"),
    ("precision_align_apply", "safe", "editor.precision_align_apply",
     "帧对齐写回：按计划改 store 并记一条 compound 撤销"),
    # 2026-10-20 治理线：只读判定 ⇒ safe
    ("aesthetic_gate", "safe", "pipeline.aesthetic_gate",
     "审美治理闸门：五维评分 → pass/review/block（估算维度默认复核）"),
    # P1-3 异步任务模型：提交会启动生成线（可能花钱）→ 危险动作走确认流；
    # 查询/取消只读/止盈止损 → safe。
    ("submit_pipeline", "dangerous", "pipeline.submit",
     "全链路异步提交（立即返回任务号，后台执行可取消；生成线可能花钱，需用户确认）"),
    ("job_status", "safe", "pipeline.job_status",
     "管线任务状态/进度/结果查询（无任务号则列近期任务+队列统计）"),
    ("job_cancel", "safe", "pipeline.job_cancel",
     "取消管线任务（排队真取消；运行中当前段跑完后生效、结果丢弃不落盘）"),
    ("llm_health", "safe", "pipeline.llm_health",
     "LLM 降级率查询（各站点近24h降级统计；高降级率=质量在暗处打折，只读）"),
)

# 画布侧 action（前端 executeRemoteTask 本地执行，无后端 capability）。
# 结构与剪辑侧一致：(action, danger_level, effect, 说明)。
# effect 与 agent_policy.py 的 EFFECT_* 语义对齐（read/canvas_write/media_write）。
# 单一事实来源：前端 agentPolicy.ts 的 CANVAS 映射、后端 agent_policy._CANVAS_TOOL_EFFECTS
# 均应由本表派生，避免「同一套 Agent 两套动作清单」越改越分裂。
_CANVAS_ACTION_ROWS: Tuple[Tuple[str, str, str, str], ...] = (
    # ── 只读 ──
    ("queryNodes", "safe", "read", "查询画布节点"),
    ("canvas_query", "safe", "read", "queryNodes 别名"),
    ("queryTimeline", "safe", "read", "查询时间线/分镜"),
    ("selectNode", "safe", "read", "选中节点"),
    ("canvas_select", "safe", "read", "selectNode 别名"),
    # ── 画布写 ──
    ("addNode", "safe", "canvas_write", "新增节点（kind/位置/title）"),
    ("updateNode", "safe", "canvas_write", "更新节点数据"),
    ("connectNodes", "safe", "canvas_write", "连接节点 source→target"),
    ("deleteNode", "dangerous", "canvas_write", "删除节点"),
    ("setNodeImage", "safe", "canvas_write", "设置节点图片"),
    ("setNodeVideo", "safe", "canvas_write", "设置节点视频"),
    ("importImage", "safe", "canvas_write", "导入图片/视频参考"),
    ("duplicateNode", "safe", "canvas_write", "复制节点"),
    ("canvas_duplicate_node", "safe", "canvas_write", "duplicateNode 别名"),
    ("groupNodes", "safe", "canvas_write", "节点成组"),
    ("canvas_group", "safe", "canvas_write", "groupNodes 别名"),
    ("bindShotlistFrame", "safe", "canvas_write", "绑定分镜帧"),
    ("canvas_bind_shotlist_frame", "safe", "canvas_write", "bindShotlistFrame 别名"),
    ("undo", "safe", "canvas_write", "撤销"),
    ("canvas_undo", "safe", "canvas_write", "undo 别名"),
    ("redo", "safe", "canvas_write", "重做"),
    ("canvas_redo", "safe", "canvas_write", "redo 别名"),
    ("breakdown", "safe", "canvas_write", "剧本文本 → 分镜拆解"),
    ("applyStoryboard", "safe", "canvas_write", "应用分镜表"),
    ("storyboardBreakdown", "safe", "canvas_write", "breakdown 别名"),
    ("canvas_breakdown", "safe", "canvas_write", "breakdown 别名"),
    # 工作流蓝图（2026-10-31）：Agent 的「编排器」原语。
    # 一次产出整张 DAG（多节点 + 多连线）而不是一条条 addNode；
    # 坐标由前端本地拓扑引擎算（LLM 不出像素）⇒ 摆放天然规整。
    ("applyBlueprint", "safe", "canvas_write",
     "应用工作流蓝图：一次铺出完整流程（多节点 + 连线 + 拓扑布局）"),
    # 文本 → 3D 粗模（仅机位档）：自然语言/剧本 → 机位+运镜计划 → 应用到 3D 导演台。
    # 复用既有「文本→分镜→机位」后端通道与既有 applyStage3dCameraPlan 消费端，不新增 3D 通道。
    ("stage3dTextPlan", "safe", "canvas_write", "文本 → 3D 机位：自然语言/剧本 → 机位+运镜计划并应用到 3D 导演台"),
    # 多角色配音编排（2026-10-15）：剧本 → 逐句角色路由 TTS → 配音时长反推镜头时长 →
    # 配音轨落时间线。复用既有 voice_generator 引擎链与唯一入轨通道，不新建第二条链路；
    # 查不到角色音色时诚实降级（degraded）用默认声线，不伪造。
    ("dubOrchestrate", "safe", "canvas_write",
     "剧本 → 多角色配音+配音时长反推镜头时长+配音轨落时间线"),
    ("fillStoryboardCell", "safe", "canvas_write", "填充分镜单元格"),
    ("canvas_fill_storyboard_cell", "safe", "canvas_write", "fillStoryboardCell 别名"),
    # ── 媒体生成（付费） ──
    ("runGenerate", "safe", "media_write", "单节点生成"),
    ("batchGenerate", "safe", "media_write", "批量生成"),
    ("runBatchGenerate", "safe", "media_write", "batchGenerate 别名"),
    ("canvas_batch_generate", "safe", "media_write", "batchGenerate 别名"),
)

# 画布侧动作派生：危险级别集合 + effect/付费映射 + 统一清单（均以上表为单一事实来源）。
_CANVAS_SAFE_ACTIONS: FrozenSet[str] = frozenset(
    a for a, level, _, _ in _CANVAS_ACTION_ROWS if level == "safe"
)
_CANVAS_DANGEROUS_ACTIONS: FrozenSet[str] = frozenset(
    a for a, level, _, _ in _CANVAS_ACTION_ROWS if level == "dangerous"
)
_CANVAS_ALLOWED_ACTIONS: FrozenSet[str] = _CANVAS_SAFE_ACTIONS | _CANVAS_DANGEROUS_ACTIONS


def canvas_action_effect_paid() -> Dict[str, Tuple[str, bool]]:
    """由 _CANVAS_ACTION_ROWS 派生画布 action → (effect, paid) 映射。

    paid 仅由 effect 决定：media_write（生成媒体）计费，read/canvas_write 免费。
    供 agent_policy._CANVAS_TOOL_EFFECTS 派生，与前端 agentPolicy.ts 的 CANVAS 同源。
    """
    return {a: (eff, eff == "media_write") for a, _lvl, eff, _desc in _CANVAS_ACTION_ROWS}


def build_canvas_actions_list() -> List[Dict[str, str]]:
    """输出统一画布动作清单（action → 描述 → 执行域 → 危险级别），供 canvas.list_actions 消费。"""
    return [
        {"action": a, "effect": eff, "danger_level": lvl, "description": desc}
        for a, lvl, eff, desc in _CANVAS_ACTION_ROWS
    ]


# ═══════════════════════════════════════════════════════════════════
# 画布节点级 capability 派生（canvas_tools 后端化，2026-09-15）
# -----------------------------------------------------------------
# 节点状态存在前端 Zustand store，后端无法直接改；唯一通道是
# push_to_canvas("task.create") → 前端 executeRemoteTask → POST /host/agent/reply。
# 这里把画布节点级 action 映射成 backend capability（canvas.<snake_case>），
# 让 Agent 经 CapabilityDispatcher 统一调用，并纳入 list_capabilities /
# 脑神经元 / 记忆 trace 的单一事实来源（_CANVAS_ACTION_ROWS）。
# ═══════════════════════════════════════════════════════════════════

def _snake_case(name: str) -> str:
    """camelCase → snake_case（addNode → add_node，queryNodes → query_nodes）。"""
    return re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower()


def canvas_node_capabilities() -> List[Dict[str, str]]:
    """由 _CANVAS_ACTION_ROWS 派生画布节点级 capability 清单。

    跳过 media_write（runGenerate/batchGenerate 已由 canvas.generate_* 覆盖）与别名，
    只保留 canonical 节点操作。返回 [{capability_id, action, effect, danger_level, description}]。
    """
    out: List[Dict[str, str]] = []
    for action, level, effect, desc in _CANVAS_ACTION_ROWS:
        if effect == "media_write":
            continue
        if "别名" in desc:
            continue
        out.append(
            {
                "capability_id": "canvas." + _snake_case(action),
                "action": action,
                "effect": effect,
                "danger_level": level,
                "description": desc,
            }
        )
    return out


def canvas_action_to_capability() -> Dict[str, str]:
    """所有画布节点 action（含别名）→ capability_id，供 ACTION_TO_CAPABILITY 派生。

    别名描述形如「queryNodes 别名」，反查回 canonical action 后映射其 capability。
    media_write 生成类（runGenerate/batchGenerate）不在此映射内。
    """
    canonical = {c["action"]: c["capability_id"] for c in canvas_node_capabilities()}
    out: Dict[str, str] = dict(canonical)
    for action, _lvl, effect, desc in _CANVAS_ACTION_ROWS:
        if effect == "media_write":
            continue
        target = desc.split("别名")[0].strip() if "别名" in desc else action
        if target in canonical and action != target:
            out[action] = canonical[target]
    return out


def canvas_capability_to_action() -> Dict[str, str]:
    """capability_id → camelCase 画布 action（供 capability handler 反向映射）。"""
    return {c["capability_id"]: c["action"] for c in canvas_node_capabilities()}


def canvas_generation_actions() -> FrozenSet[str]:
    """media_write 生成类 action（runGenerate/batchGenerate 及别名），仍走 SSE 桥前端触发。"""
    return frozenset(a for a, _lvl, eff, _d in _CANVAS_ACTION_ROWS if eff == "media_write")


_AGENT_SAFE_ACTIONS: FrozenSet[str] = frozenset(
    a for a, level, _, _ in _AGENT_ACTION_ROWS if level == "safe"
)
_AGENT_DANGEROUS_ACTIONS: FrozenSet[str] = frozenset(
    a for a, level, _, _ in _AGENT_ACTION_ROWS if level == "dangerous"
)
_AGENT_ALLOWED_ACTIONS: FrozenSet[str] = _AGENT_SAFE_ACTIONS | _AGENT_DANGEROUS_ACTIONS

ACTION_TO_CAPABILITY: Dict[str, str] = {
    a: cap for a, _, cap, _ in _AGENT_ACTION_ROWS if cap
}
# 画布节点级 action（含别名）→ capability：canvas_tools 后端化，让
# _make_dispatcher_executor 统一走 dispatcher，而非分散在前端 executeRemoteTask。
ACTION_TO_CAPABILITY.update(canvas_action_to_capability())

# OpenTake 风格工具 → 本仓库状态（文档/测试用）
OPENTAKE_GAP_ROWS: Tuple[Tuple[str, str, str], ...] = (
    ("get_timeline", "editor.get_timeline_context", "ok"),
    ("get_media", "editor.inspect_media", "ok"),
    ("inspect_media", "editor.inspect_media", "ok"),
    ("add_clips", "", "blocked"),
    ("import_media", "", "blocked"),
    ("split_clip", "editor.split_clip", "ok"),
    ("set_clip_properties", "editor.set_clip_properties", "ok"),
    ("set_keyframes", "editor.set_keyframes", "ok"),
    ("ripple_delete_ranges", "editor.ripple_delete_range", "ok"),
)


def get_safe_actions() -> FrozenSet[str]:
    return _AGENT_SAFE_ACTIONS


def get_dangerous_actions() -> FrozenSet[str]:
    return _AGENT_DANGEROUS_ACTIONS


def get_allowed_actions() -> FrozenSet[str]:
    return _AGENT_ALLOWED_ACTIONS


def build_agent_actions_prompt_line() -> str:
    return ", ".join(sorted(_AGENT_ALLOWED_ACTIONS))


def build_clipskills_layers_block() -> str:
    """ClipSkills / Dify 式分层：决策→知识→执行（仅约束提示词，不改执行器）。"""
    return (
        "\n[能力分层 · ClipSkills 风格]\n"
        "L0 决策：优先 suggest_cleanup；Plan 只规划；协作 B 对删除二次确认；自主 C 自动执行白名单。"
        "破坏性删除用 ripple_delete_range；不确定时用 answer 反问。\n"
        "L1 知识：参考下方[长期记忆]与[项目/多集]备注（漫剧节奏、竖屏、平台），不要编造未提供的剧情事实。\n"
        "L2 执行：输出常用白名单 action，或[全能力目录]中的 capability_id（执行层同样校验）；"
        "执行结果必须能写回时间线或仅回答。"
        "精剪动作（move_clip/change_speed/add_keyframe/set_keyframes）已开放，"
        "reanchor_clips 可整批重排（默认 dry_run 只出计划，须用户确认再落地），"
        "pinyin_lookup 可查汉字读音（逐字注音+多音字候选，离线字典确定性注音），"
        "tts_polish 可对长台词正音切段（配音前处理，治长文本漂移），"
        "character_anchor/expression_clamp/prop_consistency 三守护可治人物漂移/表情夸张/武器畸形，"
        "guard_all 是它们与 tts_polish 的总入口，"
        "仍禁止 add_clip/import_media。\n"
    )


def build_agent_actions_help_block() -> str:
    catalog_line = build_catalog_capabilities_line()
    lines = [
        "优先使用下列常用 action（带参数说明，见下）；"
        "未列出的需求可改用「[全能力目录]」中的 capability_id 直接执行"
        "（同样走策略闸门；add_clip / import_media 仍未开放，禁止输出）：",
        build_agent_actions_prompt_line() + "。",
        "读素材请用 get_media / inspect_media，参数: {\"clip_id\":\"...\" 或 \"clip_index\":0,\"deep\":true}（deep 追加场景/情绪）。",
        "删除区间请用 ripple_delete_range，参数: {\"t_in\":秒,\"t_out\":秒,\"track\":可选}。",
        "remove_clip 参数: {\"clip_index\":0} 或 {\"clip_id\":\"...\"}。",
        "split_clip 参数: {\"clip_index\":0,\"split_time\":秒}（时间线绝对时间或片内相对，以实现为准）。",
        "move_clip 参数: {\"clip_index\":0,\"new_start_time\":秒}。",
        "change_speed 参数: {\"clip_index\":0,\"speed\":1.5,\"reverse\":false}。",
        "add_keyframe 参数: {\"clip_index\":0,\"time\":1.0,\"prop\":\"scale_x\",\"value\":1.5,\"easing\":\"linear\"}。",
        "set_keyframes 参数: {\"clip_index\":0,\"keyframes\":[{\"time\":1.0,\"prop\":\"opacity\",\"value\":0.5,\"easing\":\"ease_in_out\"}]}。",
        "reanchor_clips 参数: {\"dry_run\":true}（改文案后用新台词重排片段；dry_run 默认 true 只出计划，"
        "确认后再传 dry_run:false 落地，Ctrl+Z 一次整包撤销）。",
        "pinyin_lookup 参数: {\"text\":\"要注音的字/词/句\",\"mode\":\"lookup|annotate|sapi|ssml\","
        "\"style\":\"tone|tone3|normal\"}（查汉字读音：默认逐字+多音字候选；"
        "annotate 出整段注音串、sapi 出数字式 chong2、ssml 出按位置标注的 SSML；"
        "离线字典确定性注音，不依赖 LLM；CJK 扩展区查不到会标 unknown 不编造）。",
        "tts_polish 参数: {\"text\":\"台词原文\",\"max_chars\":40,\"use_llm\":true}（长台词先切段+多音字注音再配音，"
        "治长视频「后面发音错/与字幕不符」；可选传 asr_texts:[\"...\"] 回读质检，返回需重生成的段）。",
        "character_anchor 参数: {\"character\":{角色字段},\"shot_prompts\":[\"镜头1提示词\",…]}"
        "（跨镜头保持同一角色；返回特征指纹+防漂移负面词+漏拼校验；可选传 anchor 做漂移比对）。",
        "expression_clamp 参数: {\"frames\":[{表情维度:0~1},…],\"profile\":\"natural\",\"emotion\":\"生气\"}"
        "（表情维度用 ARKit blendshape 名，鼓腮=cheekPuff；返回钳制后序列+幅度质检+防夸张负面词）。",
        "prop_consistency 参数: {\"prop_type\":\"spear\",\"grip\":\"two_hand\",\"hand\":\"both\"}"
        "（道具结构约束+握持描述，治武器「一横一竖」等结构畸形；可选传 anchor 做道具漂移比对、"
        "hand_points 传 21 点手部关键点跑合理性规则）。",
        "guard_all 参数: {\"kinds\":[\"tts\",\"prop\"],\"params\":{\"tts\":{\"text\":\"台词\"},"
        "\"prop\":{\"prop_type\":\"spear\"}}}（生成前后一道调用多个守护；不传 params 也可取回全量负面词）。",
        "quote_cost 参数: {\"provider\":\"auto\",\"target_duration\":30,\"clip_duration\":5}"
        "（生成前报价：谁接单/预计¥多少/配额健康；也可直接给 {\"count\":6}；只读不生成）。",
        "submit_pipeline 参数: {\"creative_brief\":\"...\",\"target_duration\":30,"
        "\"clip_duration\":5,\"provider\":\"auto\",\"materials\":[]}"
        "（全链路异步提交：立即返回 job_id，用 job_status 查进度、job_cancel 取消；"
        "生成线可能花钱，须用户确认后才执行）。",
        "job_status 参数: {\"job_id\":\"...\"}"
        "（查单任务状态/进度/结果，done 时附完整产出；不给 job_id 则列近期任务+队列统计）。",
        "job_cancel 参数: {\"job_id\":\"...\"}"
        "（取消任务：排队中真取消；运行中当前段跑完后生效、结果丢弃不落盘，已花的钱不退）。",
        "llm_health 参数: {}"
        "（查各 LLM 站点近24h降级率；高降级率=LLM 常不可用、在用关键词降级兜底，"
        "该查 Ollama/模型渠道了）。",
        "code_video_plan 参数: {\"storyboard\":[{\"shot\":1,\"description\":\"镜头描述\",\"duration\":6.0},…],"
        "\"width\":1080,\"height\":1920,\"fps\":30,\"spec_id\":\"可选\"}"
        "（「代码 × 扩散」混合视频规划：分镜表 → CodeVideoSpec 草案，片头/字幕走 html:// 代码层、"
        "镜头走 asset:// 扩散素材位；只出计划态不渲染；缺 duration 的镜头会进 warnings 不猜默认值；"
        "确认后用 code_video_render 落地）。",
        "code_video_render 参数: {\"spec\":{…CodeVideoSpec…},\"storyboard\":[…],"
        "\"output_name\":\"可选\",\"qc\":true}"
        "（「代码 × 扩散」混合视频渲染：Chromium 逐帧 + ffmpeg 编码，产物落画布 inbox；"
        "spec 与 storyboard 二选一；长耗时（≤6 分钟）且写盘，collaborative 模式需用户确认；"
        "失败带 stage（compile/security/resolve_assets/render/encode/publish/qc），不交付半成品）。",
        "precision_audit 参数: {\"fps\":30,\"tolerance_frames\":0.5,\"include_av\":true}"
        "（帧级精剪审计：非帧网格/次帧缝隙/重叠/音画偏移；只读，不改时间线）。",
        "precision_align_plan 参数: {\"fps\":30,\"max_changes\":200}"
        "（帧对齐计划：吸附 start_time/duration 并同步 out_point；只出 before/after 计划，不改时间线）。",
        "precision_align_apply 参数: {\"fps\":30,\"max_changes\":200}"
        "（帧对齐写回：按计划改 store 并记一条 compound 撤销；重叠/大缝隙不自动修）。",
        "aesthetic_gate 参数: {\"item\":{…五维评分…}} 或 {\"items\":[…],\"policy\":{…}}"
        "（审美闸门：pass/review/block；估算维度默认 review；拦截带原因码，不静默丢）。",
        "yue_plan 参数: {\"lyrics\":\"歌词\",\"style\":\"city pop, female vocal\",\"cot\":\"full|melody|off\","
        "\"seed\":42}（YuE 符号规划：只出**可编辑的旋律+和弦乐谱**，不出音频、不花钱；"
        "先用它把「你的意图」给用户看，确认后再 yue_render）。",
        "yue_render 参数: {\"lyrics\":\"歌词\",\"style\":\"风格\",\"abc\":\"X:1…（可留空）\","
        "\"cot\":\"full|melody|off\",\"title\":\"曲名\",\"seed\":42}"
        "（渲染完整歌曲；传 abc = 按用户改过的谱渲染（YuE2 编辑模式）；"
        "不传 abc 由引擎自规划。**耗时较长**，首次会下模型；"
        "cot 语义：full=旋律+和弦（新歌默认）/ melody=旋律+自由伴奏（翻唱）/ off=直接生成）。",
        "yue_transcribe 参数: {\"audio\":\"参考曲（本地路径 / inbox URL / data URL）\","
        "\"melody_only\":true}（**翻唱第一步**：参考曲 → 旋律乐谱，只留旋律去和弦；"
        "拿到 abc 后必须让用户审阅（转录错误会带进翻唱），再用 "
        "yue_render 传该 abc + cot:\"melody\" 出翻唱）。",
        "⚠️ YuE 系列需先配置执行端（环境变量 SHIGUANG_YUE_ENDPOINT 远程 或 SHIGUANG_YUE_HOME 本地）；"
        "未配置时会返回安装指引——**如实转告用户，不要假装生成成功或改用 Suno 顶替**。",
        "禁止生成 add_clip / import_media（尚未开放）。",
        "咨询类用 answer，params.message 写给人看的说明。",
        build_clipskills_layers_block(),
    ]
    if catalog_line:
        lines.append(
            "[全能力目录]\n"
            "下列 capability_id 可直接作为 action 输出（dispatcher 已注册、策略已把关；"
            "写类操作协作模式会先给用户勾选确认）：\n" + catalog_line
        )
    return "\n".join(lines)


def list_opentake_gaps(status_filter: Optional[str] = None) -> List[Dict[str, str]]:
    rows = []
    for tool, mapping, status in OPENTAKE_GAP_ROWS:
        if status_filter and status != status_filter:
            continue
        rows.append({"opentake": tool, "mapping": mapping, "status": status})
    return rows


def list_editor_capabilities_for_prompt(max_items: int = 45) -> list:
    try:
        from app.core.capability_dispatcher import capability_dispatcher

        caps = capability_dispatcher.list_capabilities() or []
        prefer = ("editor.", "model.", "ext.")
        filtered = [
            {
                "capability_id": c.get("capability_id"),
                "description": c.get("description"),
            }
            for c in caps
            if str(c.get("capability_id") or "").startswith(prefer)
        ]
        return filtered[:max_items]
    except Exception:
        return []


def build_catalog_capabilities_line() -> str:
    """全能力目录清单（V4.46.2 Agent 全能力可达刀）。

    对话白名单只有 ~45 action，但能力目录注册了 126 个 —— 本行把**全部
    capability_id** 如实告诉模型：目录 id 可直接当 action 输出，执行层经
    dispatcher + policy 双重把关（写类协作模式仍需用户勾选确认 / Plan 拒绝）。

    真源 = agent_capability_catalog.CAPABILITY_ROWS（静态表，零副作用；
    dispatcher.list_capabilities() 在首次 invoke 前是空的，不能用它）。
    按前缀分组压缩 token（只列 id；参数说明仍由 help block 的 pipeline.*
    条目承担，守卫 check_action_wiring ⑥ 盯着）。

    失败返回空串（提示词缺该行 ≠ 不可用，诚实降级不硬拦）。
    """
    try:
        from app.core.agent_capability_catalog import CAPABILITY_ROWS

        groups: Dict[str, List[str]] = {}
        for row in CAPABILITY_ROWS:
            cid = str(row[0] or "")
            if not cid:
                continue
            prefix = cid.split(".", 1)[0] if "." in cid else "other"
            groups.setdefault(prefix, []).append(cid)
        parts = []
        for prefix in sorted(groups):
            parts.append(f"{prefix}.*: " + ", ".join(sorted(groups[prefix])))
        return "\n".join(parts)
    except Exception:
        # 诚实降级：清单缺失不影响对话（执行层闸门仍在），不硬拦不炸
        return ""
