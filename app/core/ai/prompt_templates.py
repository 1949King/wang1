"""
智能剪辑 Prompt 模板库
======================
参考:
  - FunClip       (阿里达摩院)  LLM 智能裁剪 prompt
  - videocut-skills (CSDN 1.7k) 5-skill 拆解
  - 黄金3秒公式   (短剧开头钩子)
  - 三翻法         (30秒7信息点拆爆款)
  - OpusClip       (Hook/Flow/Value/Trend 4维)
  - TRAE 六维构建法

用法:
  from app.core.ai.prompt_templates import PROMPT_TEMPLATES, build_prompt
  full = build_prompt("extract_highlights", srt_text="...", user_hint="反转")
"""

from typing import Dict, Optional

# ============================================================
# 8 套 Prompt 模板
# ============================================================

PROMPT_TEMPLATES: Dict[str, Dict] = {

    # ---------- FunClip 风格：LLM 智能裁剪 ----------
    "extract_highlights": {
        "name": "提取精彩片段",
        "source": "FunClip 默认 prompt",
        "system": (
            "你是一个专业视频剪辑师。请分析以下视频字幕（包含时间戳），"
            "找出最精彩、最有爆款潜力的片段。"
        ),
        "user": (
            "以下是一段视频的 SRT 字幕文件，包含时间戳和文本内容：\n\n"
            "{srt_text}\n\n"
            "用户提示：{user_hint}\n\n"
            "请根据上面的字幕分析，返回你认为最精彩的 3-5 个片段。"
            "每个片段必须包含准确的时间段（格式: start → end），"
            "并附上一句话说明为什么选这段。\n"
            "只返回 JSON 数组，格式如下：\n"
            '[{{"start": "00:00:12,000", "end": "00:00:25,000", "reason": "..."}}, ...]\n'
            "不要返回其他任何文本。"
        ),
    },

    "summarize_core": {
        "name": "总结核心观点",
        "source": "FunClip 默认 prompt",
        "system": (
            "你是一个专业内容编辑。请分析以下视频字幕，提取核心观点"
            "和关键信息点所在的时间段。"
        ),
        "user": (
            "以下是一段视频的 SRT 字幕文件：\n\n"
            "{srt_text}\n\n"
            "用户提示：{user_hint}\n\n"
            "请找出视频中信息量最高、观点最核心的 3-5 个片段。"
            "只返回 JSON 数组：\n"
            '[{{"start": "HH:MM:SS,mmm", "end": "HH:MM:SS,mmm", "reason": "..."}}, ...]'
        ),
    },

    "topic_filter": {
        "name": "主题筛选",
        "source": "FunClip LLM 自定义 prompt",
        "system": (
            "你是一个精准的视频内容检索器。请从视频字幕中提取"
            "与用户指定主题相关的所有片段。"
        ),
        "user": (
            "以下是一段视频的 SRT 字幕文件：\n\n"
            "{srt_text}\n\n"
            "用户关心的主题：{user_hint}\n\n"
            "请返回所有与此主题相关的片段，按时间顺序排列。"
            "只返回 JSON 数组：\n"
            '[{{"start": "...", "end": "...", "reason": "..."}}, ...]'
        ),
    },

    # ---------- 黄金3秒公式 ----------
    "golden_3s_hook": {
        "name": "黄金3秒钩子评估",
        "source": "AI短剧黄金3秒公式 (搜狐 2026)",
        "system": (
            "你是短视频爆款分析师。抖音前 3 秒决定 80% 的完播率。"
            "请评估视频开头的钩子强度。\n"
            "标准公式：悬念前置(80%) + 身份代入(15%) + 视觉锚点(5%)\n"
            "4 类强钩子：冲突前置 / 悬念 / 反差 / 共鸣"
        ),
        "user": (
            "以下是一段视频的 SRT 字幕：\n\n"
            "{srt_text}\n\n"
            "请分析这段视频的前 3 秒（或开头部分），给出：\n"
            "1. 钩子强度评分（1-10）\n"
            "2. 属于哪种钩子类型（冲突/悬念/反差/共鸣）\n"
            "3. 优化建议（一句话）\n"
            "用纯文本回复，每条一行。"
        ),
    },

    # ---------- 三翻法 ----------
    "triple_flip": {
        "name": "三翻法结构分析",
        "source": "抖音百万播放拆解 (搜狐 2026)",
        "system": (
            "你是爆款短剧分析师。所有百万播放短剧都有一个共同节奏：\n"
            "翻节奏 / 翻开头 / 翻结尾（三翻法）。\n"
            "分析视频的结构：开场钩子(0-3s) → 第一反转(3-8s) "
            "→ 第二反转(8-12s) → 解释(12-15s) → 高潮(15-20s) "
            "→ 爆点(20-25s) → 余韵(25-30s)。\n"
            "标准：30 秒至少 7 个信息点。"
        ),
        "user": (
            "以下是一段视频的 SRT 字幕（含时间戳）：\n\n"
            "{srt_text}\n\n"
            "用户提示：{user_hint}\n\n"
            "请按「三翻法」分析这段视频的结构：\n"
            "1. 翻节奏：找出每个信息点所在的时间段\n"
            "2. 翻开头：评估前 3 秒的钩子强度\n"
            "3. 翻结尾：评估最后几秒的余韵/反转强度\n"
            "4. 建议：如果要切成 15 秒爆款，建议保留哪几段\n"
            "用简洁文本回复，每项一行。"
        ),
    },

    # ---------- OpusClip 风格 ----------
    "viral_score": {
        "name": "Virality 4维打分",
        "source": "OpusClip ClipAnything (opus.pro 16M用户)",
        "system": (
            "你是短视频爆款评估专家。按以下 4 个维度给视频打分（每项 1-10）：\n"
            "- Hook（开头吸引力）：前 3 秒是否抓人\n"
            "- Flow（流畅度）：节奏是否紧凑不拖沓\n"
            "- Value（信息价值）：内容是否有干货/情绪价值\n"
            "- Trend（话题性）：是否符合当下热榜趋势\n"
        ),
        "user": (
            "以下是一段视频的 SRT 字幕：\n\n"
            "{srt_text}\n\n"
            "用户提示：{user_hint}\n\n"
            "请给出 4 维评分（Hook/Flow/Value/Trend，各 1-10 分）"
            "和总分（加权: Hook×30% + Flow×25% + Value×20% + Trend×25%），"
            "格式：\n"
            "Hook: X/10\nFlow: X/10\nValue: X/10\nTrend: X/10\nTotal: X/10"
        ),
    },

    # ---------- AI 剪辑算法 ----------
    "ai_clip_algorithm": {
        "name": "AI 剪辑算法决策",
        "source": "FunClip + OpusClip 融合",
        "system": (
            "你是一个智能视频剪辑引擎。你需要根据视频字幕内容，"
            "自动决定应该保留哪些片段、删除哪些片段。\n\n"
            "剪辑原则：\n"
            "1. 保留「黄金3秒」级别的强钩子\n"
            "2. 保留反转/冲突/笑点/泪点等高能片段\n"
            "3. 删除停顿/重复/无信息量片段\n"
            "4. 最终视频不超过 {max_duration} 秒\n"
            "5. 片段之间要有叙事连贯性"
        ),
        "user": (
            "以下是一段视频的 SRT 字幕（含精确时间戳）：\n\n"
            "{srt_text}\n\n"
            "用户指令：{user_hint}\n\n"
            "你的任务：\n"
            "1. 删除所有停顿、重复、无信息量的片段\n"
            "2. 保留所有高能片段（冲突/反转/笑点/泪点/悬念）\n"
            "3. 最终总时长不超过 {max_duration} 秒\n"
            "4. 返回需要保留的时间段列表\n\n"
            "只返回 JSON 数组，每个元素包含 start 和 end：\n"
            '[{{"start": "HH:MM:SS,mmm", "end": "HH:MM:SS,mmm"}}, ...]\n'
            "不要返回其他文本。"
        ),
    },

    # ---------- 短剧结构 ----------
    "drama_structure": {
        "name": "短剧结构分析",
        "source": "2026 AI短剧保姆级教程 (头条) + 小云雀短剧Agent",
        "system": (
            "你是专业短剧编剧。短剧标准结构：\n"
            "- 0-3s: 强钩子（冲突/悬念/反差）\n"
            "- 3-20s: 身份+矛盾确立\n"
            "- 20-50s: 冲突升级+误会铺垫\n"
            "- 50-60s: 高能反转+留悬念\n"
            "5 大稳定赛道：家庭爽文/渣男打脸/古风逆袭/悬疑微短/职场逆袭"
        ),
        "user": (
            "以下是一段短剧的 SRT 字幕：\n\n"
            "{srt_text}\n\n"
            "用户提示：{user_hint}\n\n"
            "请分析：\n"
            "1. 属于哪个赛道？\n"
            "2. 结构是否完整（钩子/身份/冲突/反转/悬念是否有）？\n"
            "3. 每部分的时长占比是否合理？\n"
            "4. 有哪些可优化点？\n"
            "用简洁文本回复。"
        ),
    },
}

# 方便索引的元数据
TEMPLATE_META = {
    k: {"name": v["name"], "source": v["source"]}
    for k, v in PROMPT_TEMPLATES.items()
}


def build_prompt(
    template_key: str,
    srt_text: str = "",
    user_hint: str = "提取精彩片段",
    max_duration: int = 60,
) -> Optional[Dict]:
    """
    构建完整的 LLM 对话 prompt。

    Args:
        template_key:  模板键名（如 "extract_highlights"）
        srt_text:      视频的 SRT 字幕文本
        user_hint:     用户输入的提示词（自然语言）
        max_duration:  最大输出时长（秒）

    Returns:
        {"system": ..., "user": ...} 或 None（模板不存在）
    """
    tpl = PROMPT_TEMPLATES.get(template_key)
    if not tpl:
        return None
    return {
        "system": tpl["system"].format(
            max_duration=max_duration,
        ),
        "user": tpl["user"].format(
            srt_text=srt_text or "(字幕未生成，请先运行语音识别)",
            user_hint=user_hint or "提取精彩片段",
            max_duration=max_duration,
        ),
    }


def list_templates() -> Dict[str, str]:
    """返回所有可用模板的名称和来源"""
    return {k: f"{v['name']} ({v['source']})" for k, v in PROMPT_TEMPLATES.items()}
