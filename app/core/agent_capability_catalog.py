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
    # 2026-10-19：配方 —— Agent 第一次能真正改画布（铺卡片），而不只是给建议
    ("canvas.apply_recipe", "canvas", "canvas_write", False,
     "按配方铺开卡片（一句话 → 前端匹配并建节点）", "cc", "配方铺开",
     ["配方", "recipe", "铺开", "工作流"]),
    ("canvas.sync_models", "canvas", "read", False,
     "同步模型管理渠道到画布", "cc", "同步模型池", ["同步", "模型池"]),
    ("canvas.list_actions", "canvas", "read", False,
     "输出统一画布动作清单（单一事实来源）", "cc", "画布动作清单", ["画布动作", "清单"]),

    # ── 画布生成（Agent 可驱动后端 /host/* 生成链路，2026-09-15）──
    # effect=media_write：产媒体，协作模式需确认；generate_image/video 走模型广场付费渠道。
    ("canvas.generate_image", "canvas", "media_write", True,
     "画布生图（模型广场 AIGC 渠道；可传 seed 复现）", "right", "画布生图",
     ["生图", "画图", "图片生成", "文生图", "generate_image", "种子", "seed"]),
    ("canvas.generate_video", "canvas", "media_write", True,
     "画布生视频（模型广场 AIGC 渠道）", "right", "画布生视频",
     ["生视频", "视频生成", "文生视频", "generate_video"]),
    # 本地生图（刀 A1，2026-10-04）：自部署 SD1.5/SDXL 双栈引擎，零调用费 ⇒ paid=False。
    # 与 canvas.generate_image（云端付费渠道）刻意分列，语义同 /host/local-image-generate。
    ("canvas.local_generate_image", "canvas", "media_write", False,
     "本地生图（自部署 SD1.5/SDXL 双栈引擎，零调用费；可传 seed 复现）", "right", "本地生图",
     ["本地生图", "本地文生图", "local_generate_image", "SDXL", "SD1.5", "本地模型"]),
    # 刀 A2（2026-10-05）：抽卡闭环的「最后一环」——一次多张 + 代理分自动选优。
    # paid=True：每张都是一次真实云端调用（n 张 = n 次额度），故与云端生图同列。
    ("canvas.best_of_draw", "canvas", "media_write", True,
     "抽卡选优：一次生成 n 张（≤6）→ 代理分逐张评分 → 取最优 + 全量入账", "right", "抽卡选优",
     ["抽卡", "选优", "best_of", "best-of-n", "多张", "择优", "候选"]),
    ("canvas.repair_image", "canvas", "media_write", True,
     "局部重绘：自动定位坏区 → 蒙版 → inpaint → 合成（坏区外像素不动；会花一次额度）",
     "right", "局部重绘",
     ["局部重绘", "修图", "修复", "repair", "inpaint", "坏区", "重绘"]),
    ("canvas.comfyui_run", "canvas", "media_write", False,
     "运行 ComfyUI 工作流（本地引擎，支持 dry-run 演练）", "right", "ComfyUI 执行",
     ["comfyui", "工作流", "节点执行", "workflow"]),
    ("canvas.concat_videos", "canvas", "media_write", False,
     "拼接多段视频成片（FFmpeg）", "cc", "视频拼接",
     ["拼接", "合并", "成片", "concat", "视频拼接"]),
    ("canvas.image_to_video", "canvas", "media_write", False,
     "静帧图转伪视频（成片闭环用）", "cc", "图转视频",
     ["图转视频", "静帧", "still", "图片转视频"]),
    # ── LibTV 对标补强（2026-10-12）：引擎早已就绪、只差 Agent 接线 ──
    # 全部复用既有 /host/* 端点背后的同一实现；本地引擎非云付费 ⇒ paid=False。
    # 权重缺失时**诚实失败**（回传下载指引），绝不静默降级冒充（深度红线见 video_depth.py）。
    # 处理器独立成模块 capability_handlers_media.py（防 capability_handlers.py 破 2000 行守卫）。
    ("canvas.ai_upscale", "canvas", "media_write", False,
     "AI 超分放大：fast/standard 档走 OpenCV ESPCN 不下载，high 档 RealESRGAN 首次需下载",
     "right", "AI超分",
     ["超分", "放大", "高清", "upscale", "sharpen", "增强画质", "提分辨率"]),
    ("canvas.ai_matte", "canvas", "media_write", False,
     "AI 抠像换背景：主体分离 → 纯色底/透明底（如实回报实际引擎，降级必标注）",
     "right", "AI抠像",
     ["抠像", "抠图", "换背景", "matting", "cutout", "透明底", "去背景"]),
    ("canvas.video_depth", "canvas", "media_write", False,
     "深度视频提取：参考片 → 灰度深度视频（只搬运运动/运镜；模型缺失时诚实失败）",
     "right", "深度提取",
     ["深度", "depth", "深度视频", "深度动作", "运镜搬运", "深度图"]),
    ("canvas.reference_breakdown", "canvas", "file_write", False,
     "逐帧拉片 L1：参考片 → 结构化镜头表（切点/时长/关键帧落盘，ffmpeg+OpenCV 零权重）",
     "left", "逐帧拉片",
     ["拉片", "拆镜头", "镜头表", "breakdown", "切点", "参考片拆解", "逐帧"]),
    # ── 拉片 L2（2026-10-14 补缺）────────────────────────────────────
    # 与 L1 的边界：L1 给结构（切点/时长/指标）；L2 加**运镜**（深度图相位相关+缩放
    # 推断，置信度门槛内才进表格）与**景别/描述**（use_vision=True 走云端视觉模型，
    # 素材出域，paid=True；不显式开启则景别留空不编造）。
    ("canvas.reference_breakdown_l2", "canvas", "file_write", True,
     "逐帧拉片 L2：L1 + 运镜深度推断（推拉摇，置信度门槛如实标注）；"
     "可选云端视觉 enrich 景别/描述（素材出域，需显式开启）",
     "left", "拉片运动分析",
     ["拉片", "运镜", "镜头运动", "景别", "特写", "中景", "推拉摇移",
      "breakdown_l2", "参考片分析", "运镜分析"]),
    # ── 指令式视频编辑（2026-10-15）────────────────────────────────────
    # 与 segment_retake 边界：重拍=重新生成，编辑=改原片。Seedance 走 Base64 直传；
    # Kling 需显式公网 video_url（素材出域要知情）。失败保原镜，绝不产半成品冒充成品。
    ("canvas.video_edit", "canvas", "media_write", True,
     "指令式视频编辑：本地片段+指令（如「把外套改成红色，其余保持不变」）→ "
     "Seedance/Kling 双渠道执行；失败原片段保留并如实标注",
     "left", "指令式视频编辑",
     ["编辑视频", "指令式编辑", "video edit", "改颜色", "改服装", "局部修改",
      "保持不变", "omni", "base_video"]),
    ("canvas.segment_retake", "canvas", "media_write", False,
     "片段重拍：只替换视频指定时间段（保音轨/时长对齐，接缝风险如实报告）",
     "left", "片段重拍",
     ["重拍", "替换片段", "retake", "片段替换", "局部替换", "splice"]),
    # ── YuE（乐）全曲生成（2026-09-28；本地/远程执行端 ⇒ 非云付费，paid=False）──
    # 三段式对齐画布意图分层：plan 出可编辑谱=「你的意图」，render 出整曲=「系统的事」。
    # ⚠️ 执行端未配置时诚实失败（返回安装指引），不造假音频。
    ("canvas.yue_plan", "canvas", "read", False,
     "YuE 符号规划：歌词+风格 → 可编辑的旋律+和弦乐谱（不出音频、不花钱）", "right", "YuE 规划乐谱",
     ["谱面", "乐谱", "符号规划", "yue", "plan", "作曲", "写歌", "旋律"]),
    ("canvas.yue_render", "canvas", "media_write", False,
     "YuE 渲染整曲：乐谱（可被用户编辑）→ 48kHz 完整歌曲（含人声与伴奏）", "right", "YuE 渲染整曲",
     ["整曲", "全曲", "生成歌曲", "yue", "render", "出歌", "唱一首"]),
    ("canvas.yue_transcribe", "canvas", "read", False,
     "YuE 翻唱前置：参考曲 → 旋律乐谱（SheetSage2，只留旋律去和弦）", "right", "YuE 转录旋律",
     ["翻唱", "转录", "扒谱", "cover", "transcribe", "改编"]),

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

    # ── 剪辑 Skill 扩容（LibTV 对标第二刀，2026-10-14）──
    # 全部是 EditorModule 既有能力的薄接线（handlers 见 capability_handlers_editor_skills.py）。
    # 目标：editor.* 从 15 → 30，配合既有 canvas.* / pipeline.* 让 Agent 总能力面过 40。
    # 纪律：写操作默认「建议 + 确认」，不默认静默改时间线；诚实失败不假成功。
    # 删除片段（默认波纹）：与 ripple_delete_range 的区别是「按 id 删单个」而非「按区间删」。
    ("editor.delete_clip", "editor", "canvas_write", False,
     "删除片段（默认波纹；视频片连带同起点联动音频，一次撤销）", "left", "删除片段",
     ["删除", "删掉", "去掉片段", "delete", "移除片段"]),
    ("editor.duplicate_clip", "editor", "canvas_write", False,
     "复制片段（默认落在原片段后 1s，可撤销）", "left", "复制片段",
     ["复制", "拷贝", " duplication", "duplicate", "再来一个"]),
    ("editor.set_clip_volume", "editor", "canvas_write", False,
     "设置片段音量（0–200%，与轨道/总控音量相乘）", "left", "片段音量",
     ["音量", "声音大小", "volume", "响一点", "轻一点"]),
    ("editor.set_clip_speed", "editor", "canvas_write", False,
     "设置片段速度（0.1–10x，复用 set_clip_speed）", "left", "片段变速",
     ["变速", "速度", "快放", "慢放", "speed", "0.5x", "2x"]),
    ("editor.mute_clip", "editor", "canvas_write", False,
     "静音/取消静音片段（记住原音量，取消即恢复）", "left", "片段静音",
     ["静音", "消音", "取消静音", "mute", "没声音"]),
    ("editor.set_transition_all", "editor", "canvas_write", False,
     "批量给相邻片段统一加转场（复用 agent_apply_transition）", "right", "批量转场",
     ["批量转场", "统一转场", "都加转场", "transition_all", "整条加转场"]),
    ("editor.suggest_beat_cut", "editor", "read", False,
     "卡点切镜建议：按节拍给切点（默认只出计划，确认后才切）", "right", "卡点切镜",
     ["卡点", "踩点", "节拍切镜", "beat", "音乐卡点", "按拍子切"]),
    ("editor.suggest_scene_cut", "editor", "read", False,
     "场景切换切点建议（OpenCV 零权重；默认只出计划）", "left", "场景切点",
     ["场景切换", "换镜头", "scene", "自动切镜头", "按内容切"]),
    ("editor.suggest_silence_trim", "editor", "read", False,
     "长静音整理建议：复用去水词/静音检测（确认后才删）", "left", "静音整理",
     ["静音整理", "去静音", "长静音", "silence_trim", "气口"]),
    ("editor.burn_subtitles", "editor", "canvas_write", False,
     "字幕烧录：按当前字幕配置导出时烧录（无字幕诚实失败）", "cc", "字幕烧录",
     ["烧字幕", "硬字幕", "burn", "字幕压进视频", "内嵌字幕"]),
    ("editor.get_playhead", "editor", "read", False,
     "读取播放头位置与选中片段（Agent 自省）", "left", "播放头位置",
     ["播放头", "现在第几秒", "playhead", "光标位置"]),
    ("editor.seek_playhead", "editor", "canvas_write", False,
     "定位播放头到指定秒（就近片段 + 刷新预览）", "left", "定位播放头",
     ["跳到", "定位到", "seek", "去第几秒", "快进到"]),
    ("editor.undo_last", "editor", "canvas_write", False,
     "撤销上一步（复用 EditorModule._undo）", "left", "撤销",
     ["撤销", "回退一步", "undo", "退回去"]),
    ("editor.redo_last", "editor", "canvas_write", False,
     "重做（复用 EditorModule._redo）", "left", "重做",
     ["重做", "redo", "再来一次", "恢复撤销"]),
    ("editor.list_timeline_clips", "editor", "read", False,
     "列出时间线片段摘要（Agent 决策面前先自省）", "left", "片段清单",
     ["有哪些片段", "片段列表", "list_clips", "时间线有啥"]),

    # ── 剪辑 Skill 扩容 第三/四/五刀（字幕 6 + 序列 2 + 关键帧 2，2026-10-14）──
    # 复用 SubtitleManager 既有能力（list/split/merge/visible/import/export）、
    # _ripple_delete_gaps / 入出点标记（I/O 键同源）、关键帧读写入口；
    # UI 弹窗版见 editor_subtitle_panel.py，此处只做 Agent 能力面补齐，零新算法。
    ("editor.list_subtitles", "editor", "read", False,
     "列出字幕条目（id/文本/起止/可见性）", "left", "字幕清单",
     ["有哪些字幕", "字幕列表", "list_subtitles", "字幕都有啥"]),
    ("editor.split_subtitle", "editor", "canvas_write", False,
     "拆分字幕：在指定秒数处一分为二", "left", "拆分字幕",
     ["拆分字幕", "字幕拆开", "split_subtitle", "一条拆两条"]),
    ("editor.merge_subtitles", "editor", "canvas_write", False,
     "合并两条字幕（文本空格拼接、区间取并）", "left", "合并字幕",
     ["合并字幕", "字幕合上", "merge_subtitles", "两条并一条"]),
    ("editor.set_subtitle_visible", "editor", "canvas_write", False,
     "显隐单条字幕（不出现在成片里）", "left", "字幕显隐",
     ["隐藏字幕", "显示字幕", "字幕隐藏", "subtitle_visible"]),
    ("editor.import_subtitles", "editor", "file_write", False,
     "导入 SRT/VTT 字幕文件到当前工程", "left", "导入字幕",
     ["导入字幕", "srt", "vtt", "外挂字幕", "import_subtitles"]),
    ("editor.export_subtitles", "editor", "file_write", False,
     "导出字幕为 SRT（无字幕诚实失败）", "left", "导出字幕",
     ["导出字幕", "字幕另存", "export_subtitles", "保存字幕"]),
    ("editor.close_track_gaps", "editor", "canvas_write", False,
     "磁吸合缝：同轨片段前移贴齐（不删内容，一次撤销）", "left", "磁吸合缝",
     ["合缝", "贴齐", "去掉空隙", "close_gaps", "磁吸", "消间隙"]),
    ("editor.mark_sequence_in_out", "editor", "canvas_write", False,
     "标记序列入点/出点（action=in/out/clear，I/O 键同源）", "left", "序列入出点",
     ["入点", "出点", "标记区间", "mark_in", "mark_out", "序列范围"]),
    ("editor.get_keyframes", "editor", "read", False,
     "读取片段关键帧列表（prop/时间/数值/缓动）", "left", "关键帧读取",
     ["关键帧有哪些", "读关键帧", "get_keyframes", "动画现状"]),
    ("editor.add_keyframe_at_playhead", "editor", "canvas_write", False,
     "播放头处加关键帧（prop/value，同 prop 近点覆盖）", "left", "加关键帧",
     ["加关键帧", "打关键帧", "add_keyframe", "在这一秒加", "记录当前值"]),

    # ── 血缘查询（智能时间线 P1 · Agent 接线，2026-10-17）──
    # 与 GET /host/clip-lineage 同一实现：从 _clips 快照按需建索引、不落第二真相源；
    # effect=read 只读血缘记录（clip ↔ 画布节点 + 生成参数），无命中诚实空返回。
    ("editor.get_clip_lineage", "editor", "read", False,
     "片段血缘查询：按 clip_id/node_id 查片段↔画布节点关联+生成参数（只读，无命中诚实空）",
     "left", "片段血缘",
     ["血缘", "来源", "哪来的", "怎么生成的", "生成参数", "lineage", "画布节点关联"]),
    # ── 小白闭环自动粗剪合链（§6.9-P2 · 方案 1 纯 core 侧，2026-10-17）──
    # 三段式对齐「确认后执行」纪律：plan 只算不改（read）→ apply 写回可撤销（canvas_write）
    # → export 委托既有精剪出片入口（media_write）；全部复用 B1/B2，不动冻结区。
    ("editor.rough_cut_plan", "editor", "read", False,
     "粗剪提案：规则排轨 + B2 水词/静音检测 → 审核卡提案（只算不改数据，无 ASR/字幕片段如实跳过）",
     "left", "粗剪提案",
     ["粗剪", "排轨", "水词", "静音", "去口癖", "提案", "rough cut"]),
    ("editor.rough_cut_apply", "editor", "canvas_write", False,
     "粗剪写回：确认后排轨落时间线 + 波纹删除 + 磁吸合缝（一条 compound 撤销；未确认拒绝执行）",
     "left", "粗剪写回",
     ["粗剪", "写回", "应用", "波纹删除", "合缝", "rough_cut_apply"]),
    ("editor.rough_cut_export", "editor", "media_write", False,
     "粗剪导出成片：写回后委托既有精剪出片入口（零新渲染路径；未写回拒绝导出）",
     "cc", "粗剪导出",
     ["粗剪", "导出", "成片", "出片", "rough_cut_export"]),
    # ── 语义轨道原型（§6.9-P3 · 质量分/高光落 clip 元数据，2026-10-17）──
    # B4 形态：语义信号挂 clip["semantic"] 块（工程全量 dump 自动持久化），不动时间线架构；
    # 打分盖章由 pipeline.score 自动完成，本能力对只读查询/人工高光标记。
    ("editor.get_clip_semantic", "editor", "read", False,
     "查询片段语义元数据：五维质量分+高光标记（只读，无语义块如实空返回）",
     "left", "片段语义",
     ["语义", "质量分", "高光", "评分", "semantic", "分级"]),
    ("editor.mark_clip_highlight", "editor", "canvas_write", False,
     "显式标记片段高光：人工/Agent 标记覆盖自动判定，后续打分盖章不回改",
     "left", "标记高光",
     ["高光", "标记", "人工", "highlight", "mark_clip_highlight"]),

    # ── 多任务调度 ──
    ("workflow.submit_batch", "workflow", "file_write", False,
     "提交批量任务", "left", "批量任务", ["批量", "任务", "batch"]),

    # ── Agent 全链路闭环 ──
    ("pipeline.route", "pipeline", "read", False,
     "业务分流：AI生成/素材剪辑", "cc", "业务分流", ["分流", "路由", "判断"]),
    # ── 问题路由消费接线（智能时间线 P1 · ROUTER 后续刀，2026-10-17）──
    # 委托 problem_router.route_problem 纯函数规则表：只出修复通道建议，不执行任何通道。
    ("pipeline.route_problem", "pipeline", "read", False,
     "问题路由：五维评分/审核标记 → 修复通道建议（时间线内/指令编辑/重拍；只读不执行）",
     "left", "问题路由",
     ["问题路由", "返工", "怎么修", "重拍还是剪辑", "修复通道", "route_problem"]),
    # 粗剪合链异步入口（§6.9-P2）：一条队列跑「入库→排轨→检测→审核卡」，
    # 任务体在 waiting_for_review 正常暂停（paused 非失败），确认后走 apply/export 收尾。
    ("pipeline.rough_cut_chain", "pipeline", "media_write", False,
     "小白闭环粗剪合链：素材入库→规则排轨→水词/静音检测→审核卡（异步队列，确认后 apply+export）",
     "cc", "粗剪合链",
     ["粗剪", "闭环", "合链", "自动粗剪", "一键粗剪", "rough_cut_chain"]),
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
    # ── LibTV 对标补强 刀2（2026-10-12）：文本生剧本 / 导演结果落时间线 ──
    # 单一真源：script_writer.py / director_timeline.py（DirectorSkill 同源薄委托）。
    # script_write 走 LLM 云→Ollama→模板三级降级 ⇒ 云端有花费 paid=True；
    # 模板降级时 fallback=True 如实标注（绝不说成 LLM 原创）。
    ("pipeline.script_write", "pipeline", "read", True,
     "文本生剧本：主题/梗概 → LLM 完整剧本（场景/对白/动作/时长；降级如实标注）",
     "right", "文本生剧本",
     ["写剧本", "生成剧本", "剧本生成", "编剧", "screenplay", "script_write",
      "原创剧本", "改编"]),
    # effect=canvas_write：落轨写入 EditorModule._clips（时间线真相源）；
    # 剪辑模块未打开（无订阅者）时不发事件、如实报告（与 editor.send_selected_to_canvas 同类）。
    ("pipeline.director_apply_timeline", "pipeline", "canvas_write", False,
     "导演结果落时间线：分镜表+素材目录 → 按镜序入轨（无订阅者时如实报告）",
     "left", "导演落时间线",
     ["落时间线", "入轨", "分镜入轨", "素材入轨", "director_apply", "落轨",
      "分镜落时间线"]),
    # ── 「代码 × 扩散」混合视频（V4.44 契约刀，2026-10-19）──
    # effect=read：只出 spec 草案（计划态），不渲染、不写盘。
    # 渲染能力 code_video_render 在 V4.45 渲染引擎落地时同批注册
    # （目录 ↔ 注册双向守卫，禁止空登记占位）。
    ("pipeline.code_video_plan", "pipeline", "read", False,
     "代码×扩散混合视频规划：分镜表→CodeVideoSpec 草案（契约编译，计划态）",
     "left", "代码视频规划",
     ["代码视频", "混合视频", "代码做视频", "html视频", "code_video", "程序视频"]),
    # effect=file_write：本地 Chromium 逐帧 + ffmpeg 编码，产物落画布 inbox。
    # paid=False（无云成本）；长耗时且写盘 ⇒ action 表登记 dangerous（需确认）。
    ("pipeline.code_video_render", "pipeline", "file_write", False,
     "代码×扩散混合视频渲染：compiled spec → Chromium frame(t) → ffmpeg → inbox（诚实失败）",
     "left", "代码视频成片",
     ["代码视频成片", "混合视频渲染", "渲染代码视频", "code_video_render", "代码成片"]),
    # ── 精剪线（2026-10-20）：帧级审计 / 对齐计划，只读 ──
    ("editor.precision_audit", "editor", "read", False,
     "帧级精剪审计：非帧网格/次帧缝隙/重叠/音画偏移（只读，不写时间线）",
     "left", "精剪审计", ["精剪", "帧级", "帧网格", "次帧", "音画偏移", "审计"]),
    ("editor.precision_align_plan", "editor", "read", False,
     "帧对齐计划：吸附 start_time/duration 并同步 out_point（只出计划，不改时间线）",
     "left", "帧对齐计划", ["帧对齐", "吸附", "对齐计划", "微调", "精剪"]),
    ("editor.precision_align_apply", "editor", "canvas_write", False,
     "帧对齐写回：按计划改 store 并记一条 compound 撤销（重叠/大缝隙不自动修）",
     "left", "帧对齐写回", ["帧对齐写回", "对齐落地", "精剪写回", "precision_align_apply"]),
    # ── 治理线（2026-10-20）：评分 → 闸门判定，只读 ──
    ("pipeline.aesthetic_gate", "pipeline", "read", False,
     "审美治理闸门：五维评分 → pass/review/block（估算维度默认复核，不假通过）",
     "cc", "审美闸门", ["闸门", "治理", "拦截", "评级", "评审", "aesthetic_gate"]),
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
