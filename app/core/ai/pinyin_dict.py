"""汉字注音字典（离线确定性注音服务）
=======================================

定位：**给整个项目的「字 → 读音」提供唯一离线来源**，不依赖 LLM、可复现。

为什么需要它（真实痛点，2026-09-25 落地）：
    `app/core/ai/tts_guard.py` 原有的「多音字注音」是**让 LLM 现场猜拼音**的
    （提示词要求模型输出 ``[{"word","char","pinyin","reason"}]``）。后果：
      · LLM 不可用 / 调用失败 → 走「降级为不注音」→ **整段注音静默消失**；
      · 同一个字两次调用可能得到不同拼音 → 不可复现；
      · LLM 会编造拼音（无校验来源）。
    本模块把「确定性部分」（查字典 + 词组消歧）从 LLM 手里拿回来：
    字典能定的直接定；**只有真的需要语境判断时才交给 LLM**，且候选音由字典提供
    （LLM 只做选择题，不做填空题）。

能力边界（实测 2026-09-25，pypinyin 0.55.0）：
    ✓ 常用字 / 生僻字（含「龘靐齉爨彧羴猋麤」级别）/ 三叠字全部覆盖
    ✓ 词组级多音字消歧：重庆→chóng qìng、银行→yín háng、长大→zhǎng dà
    ✗ **CJK 扩展 B 区及以后（如 𠀋𠮷）查不到** —— 此类字**诚实标记为 unknown**，
      **绝不编造读音**（这是本模块的红线）。
    ✗ 拼音库缺失时（未安装 pypinyin）→ 全部接口返回 ``ok=False`` + 人话原因，
      不抛异常、不返回假数据。

设计纪律：纯模块（只 import 标准库 + 惰性 import pypinyin），
不 import ``app.*``（避免拉起硬件探测被沙箱拦截）；一切异常绝不抛出。
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ── 注音风格 ──
STYLE_TONE = "tone"    # 带声调符号：zhōng guó
STYLE_TONE3 = "tone3"  # SAPI/数字式：zhong1 guo2
STYLE_NORMAL = "normal"  # 无声调：zhong guo

_VALID_STYLES = (STYLE_TONE, STYLE_TONE3, STYLE_NORMAL)

_IMPORT_ERR = ""


def _load_pypinyin():
    """惰性载入 pypinyin；不可用时返回 (None, 原因)。只做一次。"""
    global _IMPORT_ERR
    try:
        import pypinyin  # type: ignore

        return pypinyin, ""
    except Exception as e:  # pragma: no cover - 环境缺失路径
        _IMPORT_ERR = f"注音库 pypinyin 不可用：{e}"
        logger.debug("[pinyin_dict] %s", _IMPORT_ERR, exc_info=True)
        return None, _IMPORT_ERR


def is_available() -> Tuple[bool, str]:
    """注音库是否可用。返回 ``(可用, 原因)``；不可用时原因为人话。"""
    mod, err = _load_pypinyin()
    if mod is None:
        return False, err or "注音库不可用"
    return True, ""


def _style_of(pypinyin, style: str):
    s = str(style or STYLE_TONE).lower()
    if s not in _VALID_STYLES:
        s = STYLE_TONE
    return {
        STYLE_TONE: pypinyin.Style.TONE,
        STYLE_TONE3: pypinyin.Style.TONE3,
        STYLE_NORMAL: pypinyin.Style.NORMAL,
    }[s]


def _is_cjk(ch: str) -> bool:
    """是否是需要注音的汉字（CJK 统一表意文字）。"""
    if not ch:
        return False
    cp = ord(ch)
    return (
        0x4E00 <= cp <= 0x9FFF        # 基本区
        or 0x3400 <= cp <= 0x4DBF     # 扩展 A
        or 0x20000 <= cp <= 0x2A6DF   # 扩展 B（pypinyin 未覆盖，会被标 unknown）
        or 0x2A700 <= cp <= 0x2EBEF   # 扩展 C-F
        or 0xF900 <= cp <= 0xFAFF     # 兼容表意文字
    )


# ═══════════════════════════════════════════════════════════
# 查字
# ═══════════════════════════════════════════════════════════

def candidates(char: str) -> List[str]:
    """单字**全部**读音候选（带声调）。查不到返回空列表。

    用途：把「填拼音」变成「选拼音」——喂给 LLM 消歧时限定候选范围，
    模型只能在这个集合里选，不能编造。
    """
    if len(char) != 1:
        return []
    mod, _ = _load_pypinyin()
    if mod is None:
        return []
    try:
        res = mod.pinyin(char, style=mod.Style.TONE, heteronym=True)
        if res and res[0]:
            return [str(x) for x in res[0]]
    except Exception:
        logger.debug("[pinyin_dict] 候选查询失败: %r", char, exc_info=True)
    return []


def is_polyphone(char: str) -> bool:
    """是否多音字（候选读音 > 1）。"""
    return len(candidates(char)) > 1


def annotate(text: str, *, style: str = STYLE_TONE) -> Dict[str, Any]:
    """整段注音（**按词组上下文消歧**，确定性、可复现）。

    Returns::

        {"ok", "text", "annotated": "chóng qìng", "pinyin_list": [...],
         "chars": [{"char","pinyin","known","polyphone"}],
         "unknowns": ["𠀋"], "coverage": 0.98, "message"}
    """
    raw = text or ""
    mod, err = _load_pypinyin()
    if mod is None:
        return {"ok": False, "text": raw, "annotated": "", "pinyin_list": [],
                "chars": [], "unknowns": [], "coverage": 0.0, "message": err}
    if not raw:
        return {"ok": False, "text": raw, "annotated": "", "pinyin_list": [],
                "chars": [], "unknowns": [], "coverage": 0.0,
                "message": "文本为空，无可注音内容"}
    st = _style_of(mod, style)
    try:
        py_list = [str(x) for x in mod.lazy_pinyin(raw, style=st)]
    except Exception as e:
        logger.debug("[pinyin_dict] 注音失败", exc_info=True)
        return {"ok": False, "text": raw, "annotated": "", "pinyin_list": [],
                "chars": [], "unknowns": [], "coverage": 0.0,
                "message": f"注音失败：{e}"}

    chars: List[Dict[str, Any]] = []
    unknowns: List[str] = []
    need = 0
    known = 0
    for ch, py in zip(raw, py_list):
        if not _is_cjk(ch):
            chars.append({"char": ch, "pinyin": "", "known": True,
                          "polyphone": False, "cjk": False})
            continue
        need += 1
        # pypinyin 对查不到的字会**原样返回字符**（不抛错）→ 以此判定未知
        is_known = bool(py) and py != ch
        if is_known:
            known += 1
        else:
            unknowns.append(ch)
        chars.append({"char": ch, "pinyin": py, "known": is_known,
                      "polyphone": is_polyphone(ch), "cjk": True})

    coverage = (known / need) if need else 1.0
    msg = f"已注音 {known}/{need} 个汉字"
    if unknowns:
        msg += (f"；{len(unknowns)} 个查不到（CJK 扩展区，字典未覆盖，"
                f"未编造读音）：{''.join(dict.fromkeys(unknowns))}")
    return {"ok": need == 0 or known > 0, "text": raw,
            "annotated": " ".join(x for x in py_list if x),
            "pinyin_list": py_list, "chars": chars, "unknowns": unknowns,
            "coverage": round(coverage, 4), "message": msg}


def lookup(text: str) -> Dict[str, Any]:
    """逐字释义：读音 + 候选 + 是否多音字（供 Agent 查询/UI 展示）。"""
    base = annotate(text, style=STYLE_TONE)
    if not base["ok"]:
        return base
    items = []
    for c in base["chars"]:
        if not c.get("cjk"):
            continue
        cand = candidates(c["char"]) if c["known"] else []
        items.append({
            "char": c["char"],
            "pinyin": c["pinyin"],
            "candidates": cand,
            "polyphone": c["polyphone"],
            "known": c["known"],
            "note": "" if c["known"] else "字典未收录（CJK 扩展区），不编造读音",
        })
    return {**base, "items": items,
            "polyphone_chars": [i["char"] for i in items if i["polyphone"]]}


# ═══════════════════════════════════════════════════════════
# 多音字（TTS 正音用）
# ═══════════════════════════════════════════════════════════

def polyphones(text: str) -> Dict[str, Any]:
    """列出文本中的多音字 + 字典消歧结果 + 全部候选。

    这是给 LLM 消歧用的**约束集**：LLM 只需在 ``candidates`` 里选，
    不能再凭空生成拼音。
    """
    ann = annotate(text, style=STYLE_TONE)
    if not ann["ok"]:
        return {"ok": False, "items": [], "count": 0,
                "message": ann.get("message", "注音不可用")}
    items: List[Dict[str, Any]] = []
    for c in ann["chars"]:
        if not c.get("cjk") or not c.get("polyphone"):
            continue
        items.append({
            "char": c["char"],
            "pinyin": c["pinyin"],            # 字典按上下文消歧后的确定音
            "candidates": candidates(c["char"]),
            "source": "dict",
        })
    return {"ok": True, "items": items, "count": len(items),
            "message": f"检出 {len(items)} 个多音字（读音来自字典上下文消歧）"
            if items else "未检出多音字"}


def to_sapi(text: str) -> Dict[str, Any]:
    """转 SAPI 数字式拼音串（``zhong1 guo2``），供 SSML/RHVoice 使用。"""
    ann = annotate(text, style=STYLE_TONE3)
    if not ann["ok"]:
        return ann
    ann["message"] = "已转 SAPI 数字式（style=tone3）"
    return ann


def to_ssml(text: str, *, only_polyphones: bool = True,
            alphabet: str = "pinyin") -> Dict[str, Any]:
    """按**位置**精确生成 SSML ``<phoneme>`` 标注（字典版，不依赖 LLM）。

    与 ``tts_guard.build_ssml`` 的关键差异：后者按「字符串首次出现」替换
    （同一字出现多次时只有第一处被标注），本函数**逐字按位置标注**，
    同一字不同位置可得到不同读音。

    ``only_polyphones=True``（默认）：只标注多音字 —— 单音字由 TTS 引擎
    自行处理，避免把整句包成 phoneme 导致 SSML 体积膨胀。
    """
    raw = text or ""
    if not raw:
        return {"ok": False, "ssml": "", "marked": 0, "message": "文本为空"}
    mod, err = _load_pypinyin()
    if mod is None:
        return {"ok": False, "ssml": raw, "marked": 0, "message": err}
    try:
        tone = [str(x) for x in mod.lazy_pinyin(raw, style=mod.Style.TONE)]
        tone3 = [str(x) for x in mod.lazy_pinyin(raw, style=mod.Style.TONE3)]
    except Exception as e:
        logger.debug("[pinyin_dict] SSML 生成失败", exc_info=True)
        return {"ok": False, "ssml": raw, "marked": 0, "message": f"生成失败：{e}"}

    parts: List[str] = []
    marked = 0
    for idx, ch in enumerate(raw):
        py = tone[idx] if idx < len(tone) else ""
        ph = tone3[idx] if idx < len(tone3) else ""
        known = bool(ph) and ph != ch
        want = known and (not only_polyphones or is_polyphone(ch))
        if want:
            parts.append(
                f'<phoneme alphabet="{alphabet}" ph="{ph}">{ch}</phoneme>')
            marked += 1
        else:
            parts.append(ch)
    if not marked:
        return {"ok": True, "ssml": raw, "marked": 0,
                "message": "无需标注（未检出多音字）"}
    return {"ok": True, "ssml": f"<speak>{''.join(parts)}</speak>",
            "marked": marked,
            "message": f"已按位置标注 {marked} 处多音字（字典确定性注音）"}


def stats() -> Dict[str, Any]:
    """字典可用性与覆盖自述（诊断/UI 展示）。"""
    ok, reason = is_available()
    if not ok:
        return {"available": False, "reason": reason, "backend": "pypinyin"}
    mod, _ = _load_pypinyin()
    ver = getattr(mod, "__version__", "unknown")
    return {
        "available": True, "backend": "pypinyin", "version": ver,
        "covers": ["CJK 基本区", "扩展 A", "常用/生僻/三叠字", "词组级多音字消歧"],
        "not_covers": ["CJK 扩展 B 区及以后（如 𠀋𠮷）→ 标 unknown，不编造读音"],
        "styles": list(_VALID_STYLES),
        "note": "离线确定性注音；LLM 仅在需要语境判断时参与，且候选音由本字典提供",
    }
