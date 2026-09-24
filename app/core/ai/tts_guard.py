"""TTS 正音守护（长文本分段 + 多音字注音 + 回读质检）
=====================================================

问题背景（用户实测）：AI 配音在**长片段**里会「前面正常、后面发音错 / 与字幕不符」。
根因不是多音字随机出错，而是两类长文本病：

  1. **长文本 TTS 注意力漂移** —— 自回归 TTS 在长序列上累积误差，前半段稳、后半段糊；
  2. **文本-音频对齐错位** —— 长音频的累积时间误差使「字幕在第 N 句、音频播第 N-1 句」。

对策是「两道防线」：

  * 生成前：**语义切段**（每段回到 TTS 的稳定长度 ≈ 一句话）+ **多音字注音**；
  * 生成后：**ASR 回读比对**原文本，定位不一致的段，定向重试。

本模块刻意**只读、只出计划**（纯函数 + LLM 可注入），不写任何状态、不 import app 包，
便于脱离 Qt / 硬件探测单测。落地（逐段调 TTS、拼音频、写时间线）由上层负责。

单一事实来源：本模块是 TTS 正音的**唯一实现**，`pipeline.tts_polish` capability 与
`_verify/check_tts_guard.py` 均直接调用，不自带第二套切段逻辑。
"""

from __future__ import annotations

import difflib
import logging
import re
from dataclasses import asdict, dataclass, field
from typing import Callable, Dict, List, Optional

from .guard_base import extract_json_array

logger = logging.getLogger("AI短剧编辑器.core.ai.tts_guard")

# ── 切分标点（标点归前一段，保证不丢字）──
_SENTENCE_END = "。！？!?；;\n\r"
_CLAUSE = "，,、：:"

# 默认每段最大字数：中文一句话约 40 字，TTS 在此长度内最稳
DEFAULT_MAX_CHARS = 40
# 合并阈值：短于此的段尝试并入相邻段，避免切得过碎
DEFAULT_MIN_CHARS = 8

# ASR 回读相似度阈值：低于此判为「发音与字幕不符」
DEFAULT_SIMILARITY_THRESHOLD = 0.9

# LLM 回调签名：(prompt) -> 模型回复文本；None 表示不接 LLM（只切段不注音）
LlmCall = Callable[[str], str]


@dataclass
class TtsSegment:
    """一个 TTS 播报段"""

    index: int
    text: str
    char_count: int
    # 注音文本（SSML）；未接 LLM 时由离线字典兜底（2026-09-25 起不再为空）
    annotated: str = ""
    # 多音字消歧记录：[{"word","char","pinyin","reason"}]
    polyphones: List[Dict] = field(default_factory=list)
    # 注音来源（2026-09-25 新增，便于审计与排查）：
    #   "llm"  = LLM 消歧产出；"dict" = 离线字典上下文消歧；"" = 无注音
    annotated_source: str = ""


# ═══════════════════════════════════════════════════════════
# 1) 切段：按句读边界把长台词切成短段（不丢字）
# ═══════════════════════════════════════════════════════════


def _split_keep_delims(text: str, delims: str) -> List[str]:
    """按 delims 里的字符切分，**标点归到前一段**（保证不丢字）。

    与 ``str.split`` 的区别：``split("。")`` 会把标点丢掉，
    导致「拼接 == 原文」这个不变量被破坏 —— 而 TTS 拼接后与字幕对不上，
    恰恰可能因切分丢字而加重。故此处逐字符扫描，遇界符即收段。
    """
    parts: List[str] = []
    buf: List[str] = []
    for ch in text:
        buf.append(ch)
        if ch in delims:
            seg = "".join(buf).strip()
            if seg:
                parts.append(seg)
            buf = []
    tail = "".join(buf).strip()
    if tail:
        parts.append(tail)
    return parts


def _hard_split(text: str, n: int) -> List[str]:
    """无标点长串的硬切；尽量不切在「数字/字母」中间（避免读断）。"""
    out: List[str] = []
    i = 0
    total = len(text)
    while i < total:
        j = min(i + n, total)
        # j 落在 alnum 中间 → 回退到最近的非 alnum 边界
        while 0 < j < total and text[j - 1].isalnum() and text[j].isalnum():
            j -= 1
        if j <= i:  # 回退过头（整串都是 alnum），强制切
            j = min(i + n, total)
        out.append(text[i:j])
        i = j
    return [s for s in out if s]


def _merge_short(parts: List[str], min_chars: int, max_chars: int) -> List[str]:
    """把过短的段并入相邻段（只要不超上限），避免切得过碎。"""
    if not parts:
        return []
    out: List[str] = [parts[0]]
    for p in parts[1:]:
        if len(out[-1]) < min_chars and len(out[-1]) + len(p) <= max_chars:
            out[-1] = out[-1] + p
        else:
            out.append(p)
    return out


def segment_text(text: str, max_chars: int = DEFAULT_MAX_CHARS) -> List[str]:
    """把长台词切成短段，每段尽量 ≤ ``max_chars``。

    切分优先级：句末标点(。！？；\\n) > 逗号(，、：) > 硬切。
    **不变量**：所有段拼接后，去掉空白字符应等于原文去掉空白字符（不丢字）。

    >>> segment_text("她走了。他还在等。")
    ['她走了。', '他还在等。']
    """
    text = (text or "").strip()
    if not text:
        return []
    if max_chars < 1:
        max_chars = DEFAULT_MAX_CHARS

    # 1) 先按句末标点切
    sentences = _split_keep_delims(text, _SENTENCE_END)

    # 2) 超长句按逗号再切
    parts: List[str] = []
    for s in sentences:
        if len(s) <= max_chars:
            parts.append(s)
        else:
            parts.extend(_split_keep_delims(s, _CLAUSE))

    # 3) 仍超长的硬切
    out: List[str] = []
    for p in parts:
        if len(p) <= max_chars:
            out.append(p)
        else:
            out.extend(_hard_split(p, max_chars))

    # 4) 合并过短段
    return _merge_short(out, DEFAULT_MIN_CHARS, max_chars)


# ═══════════════════════════════════════════════════════════
# 2) 注音：多音字消歧（LLM 可注入）+ SSML 生成
# ═══════════════════════════════════════════════════════════

_TONE_MAP = {
    "ā": ("a", 1), "á": ("a", 2), "ǎ": ("a", 3), "à": ("a", 4),
    "ē": ("e", 1), "é": ("e", 2), "ě": ("e", 3), "è": ("e", 4),
    "ī": ("i", 1), "í": ("i", 2), "ǐ": ("i", 3), "ì": ("i", 4),
    "ō": ("o", 1), "ó": ("o", 2), "ǒ": ("o", 3), "ò": ("o", 4),
    "ū": ("u", 1), "ú": ("u", 2), "ǔ": ("u", 3), "ù": ("u", 4),
    "ǖ": ("v", 1), "ǘ": ("v", 2), "ǚ": ("v", 3), "ǜ": ("v", 4),
}

_POLYPHONE_PROMPT = (
    "你是中文配音的『正音』助手。请找出下面台词中所有**多音字或易读错字**，"
    "给出它们在这句话语境下的正确读音。\n"
    "只输出 JSON 数组，不要任何解释、不要 markdown 代码块。\n"
    '格式：[{"word": "重庆", "char": "重", "pinyin": "chóng", "reason": "地名"}]\n'
    "（word 为该字所在的词，char 为单字，pinyin 带声调符号，reason 一句话说明）\n"
    "{constraints}"
    "若该句没有多音字，输出 []。\n\n"
    "台词：{text}"
)

# 批量版：一次处理多段（省 token + 跨段上下文），输出带 index
_BATCH_POLYPHONE_PROMPT = (
    "你是中文配音的『正音』助手。下面按段落编号给出多句台词。"
    "请找出每段中所有**多音字或易读错字**，给出它们在该句语境下的正确读音。\n"
    "只输出 JSON 数组，不要任何解释、不要 markdown 代码块。\n"
    '格式：[{"index": 0, "word": "重庆", "char": "重", "pinyin": "chóng", "reason": "地名"}]\n'
    "（index 为段落编号；word 为该字所在的词；pinyin 带声调符号；某段无多音字则不输出该段项）\n"
    "{constraints}"
    "若全部段落都没有多音字，输出 []。\n\n"
    "段落：\n{segments}"
)


# ═══════════════════════════════════════════════════════════════════
# 候选约束（2026-09-25 V4.39.2）——把 LLM 的「填空」变成「选择题」
#
# 原实现让 LLM 直接"写出正确读音"（填空）：模型可能编造不存在的拼音，
# 且同一个字两次调用可能给出不同结果。现改为：
#   ① 由离线字典先检出文本中的多音字，并给出**全部合法候选读音**；
#   ② 提示词要求 LLM **只能从候选中选**；
#   ③ 返回后**判卷** —— 读音不在候选集内的一律丢弃（以字典为准）。
# 没有第 ③ 步，候选约束就只是提示词里的礼貌用语（LLM 未必遵守）。
# ═══════════════════════════════════════════════════════════════════

def _candidate_hint(text: str) -> str:
    """构造候选约束段。字典不可用/无多音字时返回空串（prompt 退化为旧版）。"""
    try:
        from .pinyin_dict import polyphones

        r = polyphones(text)
        lines = [
            f"  {it['char']} ∈ [{', '.join(it['candidates'])}]"
            for it in r.get("items", [])
            if it.get("candidates")
        ]
        if not lines:
            return ""
        return ("字典已检出下列多音字及其**全部合法读音**：\n"
                + "\n".join(lines) + "\n"
                "你的 pinyin **只能从上面给出的候选里选择**，"
                "不得使用候选之外的读音；未列出的字不要输出。\n")
    except Exception:
        logger.debug("[tts_guard] 候选约束生成失败（退化为无约束）", exc_info=True)
        return ""


def _validate_polys(items: List[Dict], text: str) -> List[Dict]:
    """判卷：丢弃读音越界的项（**以字典为准**，防 LLM 编造）。

    合法集合 = 单字候选（heteronym）∪ 字典对该句上下文消歧后的确定音。
    字典不可用时**原样放行**（诚实降级：不因守卫自身故障吃掉 LLM 结果）。
    """
    if not items:
        return items
    try:
        from .pinyin_dict import annotate as _ann
        from .pinyin_dict import candidates as _cand

        ann = _ann(text)
        dict_py = {str(c.get("char")): str(c.get("pinyin") or "")
                   for c in ann.get("chars", []) if c.get("cjk")}
    except Exception:
        logger.debug("[tts_guard] 判卷依赖不可用，原样放行", exc_info=True)
        return items

    out: List[Dict] = []
    for it in items:
        ch = str(it.get("char") or "")
        py = str(it.get("pinyin") or "").strip()
        if not ch or not py:
            continue
        # 字必须真出现在本段文本里 —— 防批量模式下 LLM 把别段的字标进本段
        # （批量 prompt 的候选约束是全局的，跨段串味是真实风险）
        if ch not in text:
            logger.info("[tts_guard] 丢弃不在本段的字：%s", ch)
            continue
        allowed = set(_cand(ch) or [])
        if dict_py.get(ch):
            allowed.add(dict_py[ch])
        if allowed and py not in allowed:
            logger.info("[tts_guard] 丢弃越界读音 %s→%s（合法候选：%s）",
                        ch, py, "、".join(sorted(allowed)))
            continue
        out.append(it)
    return out


def _to_sapi_pinyin(py: str) -> str:
    """带声调符号的拼音（chóng）→ SAPI 风格（chong2）；已是数字式则原样返回。"""
    py = (py or "").strip().lower()
    if not py:
        return ""
    tone = 0
    out: List[str] = []
    for ch in py:
        if ch in _TONE_MAP:
            base, t = _TONE_MAP[ch]
            out.append(base)
            tone = t
        else:
            out.append(ch)
    joined = "".join(out)
    # 末尾已是数字声调（chong2）→ 不重复加
    if tone and not joined[-1:].isdigit():
        return joined + str(tone)
    return joined


# 兼容别名：JSON 提取已收敛到 guard_base
_extract_json_array = extract_json_array


def detect_polyphones(text: str, llm: Optional[LlmCall]) -> List[Dict]:
    """调 LLM 做多音字消歧。

    **诚实降级**：llm 为 None、调用抛错、返回非 JSON —— 一律返回 ``[]``，
    绝不抛异常、绝不瞎猜读音（瞎猜 = 用户最反感的「随机效果」）。
    """
    if not text or llm is None:
        return []
    try:
        # 用 replace 而非 str.format：prompt 里的 JSON 示例含 {}，
        # format 会把 {"word": ...} 当占位符解析并抛 KeyError，
        # 导致注音在接真 LLM 时**静默失效**（本 bug 由 check 脚本抓出）。
        # 2026-09-25：先注入候选约束（字典检出多音字 + 合法候选），
        # 再注入文本 —— 顺序不可反（先填 constraints，避免其内容被二次替换）。
        prompt = (_POLYPHONE_PROMPT
                  .replace("{constraints}", _candidate_hint(text))
                  .replace("{text}", text))
        reply = llm(prompt)
    except Exception:
        logger.debug("[tts_guard] 多音字消歧 LLM 调用失败，降级为不注音", exc_info=True)
        return []
    # 判卷：读音越界 / 字不在文本中 → 丢弃（以字典为准）
    return _validate_polys(_extract_json_array(reply), text)


def detect_polyphones_batch(segments: List[str], llm: Optional[LlmCall]) -> List[List[Dict]]:
    """**一次调用**完成多段多音字消歧（省 token + 跨段上下文更准）。

    逐段调 LLM 的问题是：N 段 = N 次调用（token × N、延迟 × N），且每段看不到相邻句的语境。
    批量把全部段落编进一个 prompt，一次返回带 ``index`` 的数组。

    降级链（都诚实、都不瞎猜读音）：
      1. 批量成功且解析出项 → 按 ``index`` 回填；
      2. 批量失败 / 解析为空 → 全部返回空列表。**刻意不自动逐段重试** ——
         否则又退化成 N 次调用；需要更稳请在调用方显式用 ``detect_polyphones`` 兜底。
    """
    n = len(segments or [])
    empty: List[List[Dict]] = [[] for _ in range(n)]
    if n == 0 or llm is None:
        return empty
    body = "\n".join(f"[{i}] {s}" for i, s in enumerate(segments))
    # 候选约束用**全段合并文本**生成（跨段上下文更准）；判卷时再按段逐段校验
    hint = _candidate_hint("\n".join(segments))
    try:
        prompt = (_BATCH_POLYPHONE_PROMPT
                  .replace("{constraints}", hint)
                  .replace("{segments}", body))
        reply = llm(prompt)
    except Exception:
        logger.debug("[tts_guard] 批量多音字消歧失败，降级为不注音", exc_info=True)
        return empty
    rows = _extract_json_array(reply)
    if not rows:
        return empty
    out: List[List[Dict]] = [[] for _ in range(n)]
    for r in rows:
        try:
            idx = int(r.get("index", 0))
        except (TypeError, ValueError):
            idx = 0
        if 0 <= idx < n:
            out[idx].append({k: v for k, v in r.items() if k != "index"})
    # 判卷（逐段）：读音越界 / 字不在本段 → 丢弃（以字典为准）
    return [_validate_polys(out[i], segments[i]) for i in range(n)]


def build_ssml(text: str, polyphones: List[Dict], *, alphabet: str = "pinyin") -> str:
    """把多音字消歧结果转成 SSML ``<phoneme>`` 标注。

    按 ``word``（优先）或 ``char`` 在文本里**逐个替换首次出现**，
    每个替换项只处理一次，避免同一处被重复包裹。
    找不到的项静默跳过（诚实降级，不产出坏 SSML）。
    """
    if not text or not polyphones:
        return text
    out = text
    used: List[str] = []
    for p in polyphones:
        if not isinstance(p, dict):
            continue
        word = str(p.get("word") or "").strip()
        char = str(p.get("char") or "").strip()
        py = str(p.get("pinyin") or "").strip()
        if not py:
            continue
        target = word or char
        if not target or target not in out:
            continue
        ph = _to_sapi_pinyin(py)
        if not ph:
            continue
        marked = f'<phoneme alphabet="{alphabet}" ph="{ph}">{target}</phoneme>'
        # 仅替换首次出现；同一 target 不重复处理
        out = out.replace(target, marked, 1)
        used.append(target)
    if not used:
        return text
    return f"<speak>{out}</speak>"


# ═══════════════════════════════════════════════════════════
# 3) 回读质检：ASR 结果 vs 原台词（定位需重生成的段）
# ═══════════════════════════════════════════════════════════

_NON_CONTENT = re.compile(r"[\s，。！？、；：,.!?;:\"'“”‘’（）()【】\[\]—\-…·~`]+")


def _normalize(s: str) -> str:
    """归一化：去标点与空白，只留「内容字符」。
    ASR 回读通常不加标点，必须去标点后再比对，否则相似度被无意义拉低。"""
    return _NON_CONTENT.sub("", s or "")


def diff_readback(
    asr_text: str,
    original: str,
    threshold: float = DEFAULT_SIMILARITY_THRESHOLD,
) -> Dict:
    """比对单段 ASR 回读文本与原文，返回相似度 + 不一致区间。

    Returns::

        {"similarity": float, "ok": bool, "mismatches": [{"tag","original","asr"}],
         "reason": str}

    ``ok=False`` 表示这段「发音与字幕不符」，应定向重生成。
    """
    a = _normalize(asr_text)
    b = _normalize(original)
    if not b:
        return {"similarity": 0.0, "ok": False, "mismatches": [], "reason": "原文为空"}
    if not a:
        return {"similarity": 0.0, "ok": False, "mismatches": [], "reason": "回读为空"}
    ratio = difflib.SequenceMatcher(None, b, a).ratio()
    mismatches: List[Dict] = []
    sm = difflib.SequenceMatcher(None, b, a)
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag != "equal":
            mismatches.append({
                "tag": tag,              # replace / delete / insert
                "original": b[i1:i2],
                "asr": a[j1:j2],
                "orig_pos": i1,          # 在原文（归一化后）中的位置，便于定位
            })
    return {
        "similarity": round(ratio, 4),
        "ok": ratio >= threshold,
        "mismatches": mismatches,
        "reason": "" if ratio >= threshold else f"相似度 {ratio:.2f} < {threshold}",
    }


def verify_segments(
    asr_texts: List[str],
    originals: List[str],
    threshold: float = DEFAULT_SIMILARITY_THRESHOLD,
) -> Dict:
    """逐段回读质检，定位需要**定向重生成**的段。

    分段 TTS 的关键收益：一段出错只重生成那一段，不必整条重来。
    长度不一致时按较短者比对（诚实：多出的段标记为待确认）。
    """
    n = min(len(asr_texts), len(originals))
    seg_results: List[Dict] = []
    retry: List[int] = []
    for i in range(n):
        r = diff_readback(asr_texts[i], originals[i], threshold)
        r["index"] = i
        seg_results.append(r)
        if not r["ok"]:
            retry.append(i)
    # 长度不齐：多出的原始段视为「未回读」，一并重试
    if len(originals) > n:
        for i in range(n, len(originals)):
            seg_results.append({
                "index": i, "similarity": 0.0, "ok": False,
                "mismatches": [], "reason": "无对应回读",
            })
            retry.append(i)
    return {
        "ok": not retry,
        "segments": seg_results,
        "retry_indices": retry,
        "checked": n,
    }


# ═══════════════════════════════════════════════════════════════════
# 4) 离线字典兜底（2026-09-25）——注音不再随 LLM 一起消失
#
# 此前：注音 100% 来自 LLM 消歧，LLM 不可用/失败即「降级为不注音」
#       ⇒ 长台词一旦没注音，配音发音与字幕不符的问题**静默复发**。
# 现在：字典先给确定性注音（词组级消歧，可复现），LLM 只在有字典**候选**
#       约束时参与语境判断；LLM 缺席也有注音，只是少了语境兜底。
# 红线：字典查不到的字（CJK 扩展区）标 unknown，**绝不编造读音**。
# ═══════════════════════════════════════════════════════════════════

def _dict_ssml(text: str) -> Dict:
    """离线字典生成 SSML（按位置精确标注多音字）。失败返回空结果，绝不抛。"""
    try:
        from .pinyin_dict import to_ssml

        return to_ssml(text)
    except Exception:
        logger.debug("[tts_guard] 字典 SSML 不可用（跳过字典兜底）", exc_info=True)
        return {"ok": False, "ssml": text, "marked": 0, "message": "字典不可用"}


def _dict_available() -> bool:
    """离线注音字典是否可用（不可用时 message 要诚实说明"仅切段"）。"""
    try:
        from .pinyin_dict import is_available

        return bool(is_available()[0])
    except Exception:
        return False


def _dict_polys(text: str) -> List[Dict]:
    """离线字典检出的多音字（与 LLM 输出同格式，便于上层统一消费）。"""
    try:
        from .pinyin_dict import polyphones

        r = polyphones(text)
        out: List[Dict] = []
        for it in r.get("items", []):
            out.append({
                "word": it.get("char", ""),      # 字典已按整句上下文消歧
                "char": it.get("char", ""),
                "pinyin": it.get("pinyin", ""),
                "reason": "离线字典上下文消歧",
                "candidates": it.get("candidates", []),
            })
        return out
    except Exception:
        logger.debug("[tts_guard] 字典多音字查询不可用", exc_info=True)
        return []


# ═══════════════════════════════════════════════════════════
# 5) 统一入口：生成 TTS 计划（切段 + 注音）
# ═══════════════════════════════════════════════════════════


def plan_tts(
    text: str,
    *,
    max_chars: int = DEFAULT_MAX_CHARS,
    llm: Optional[LlmCall] = None,
) -> Dict:
    """生成 TTS 正音计划：切段 + （可选）多音字注音。

    Args:
        text: 台词原文
        max_chars: 每段最大字数
        llm: 多音字消歧回调；None 时只切段不注音（仍可用）

    Returns::

        {"ok", "segments": [{index,text,char_count,annotated,polyphones}],
         "segment_count", "total_chars", "max_chars", "used_llm", "polyphone_total"}

    **只出计划、不改数据** —— 落地（逐段调 TTS）由上层 handler / 服务负责。
    """
    text = text or ""
    raw_segments = segment_text(text, max_chars)
    # 批量消歧：**一次** LLM 调用处理全部段落（原实现是逐段调用 —— N 段 = N 次）
    poly_lists = detect_polyphones_batch(raw_segments, llm)
    segments: List[TtsSegment] = []
    poly_total = 0
    llm_marked = 0
    dict_marked = 0
    for i, s in enumerate(raw_segments):
        seg = TtsSegment(index=i, text=s, char_count=len(s))
        polys = poly_lists[i] if i < len(poly_lists) else []
        if polys:
            seg.polyphones = polys
            seg.annotated = build_ssml(s, polys)
            seg.annotated_source = "llm"
            poly_total += len(polys)
            llm_marked += len(polys)
        else:
            # 离线字典兜底（2026-09-25）：LLM 未产出 / 未接 LLM 时，
            # 仍给多音字确定注音 —— 注音不随 LLM 一起消失
            ds = _dict_ssml(s)
            if ds.get("marked"):
                seg.annotated = ds["ssml"]
                seg.polyphones = _dict_polys(s)
                seg.annotated_source = "dict"
                poly_total += len(seg.polyphones)
                dict_marked += len(seg.polyphones)
        segments.append(seg)
    if poly_total:
        detail = []
        if llm_marked:
            detail.append(f"LLM {llm_marked} 处")
        if dict_marked:
            detail.append(f"字典 {dict_marked} 处")
        msg = f"已切分为 {len(segments)} 段，标注 {poly_total} 处多音字（{' + '.join(detail)}）"
    else:
        msg = (f"已切分为 {len(segments)} 段"
               + ("（未检出多音字）" if llm is not None or _dict_available()
                  else "（注音字典不可用，仅切段）"))
    return {
        "ok": bool(segments),
        "segments": [asdict(s) for s in segments],
        "segment_count": len(segments),
        "total_chars": len(text),
        "max_chars": max_chars,
        "used_llm": llm is not None,
        "polyphone_total": poly_total,
        "llm_annotated": llm_marked,
        "dict_annotated": dict_marked,
        "message": msg,
    }
