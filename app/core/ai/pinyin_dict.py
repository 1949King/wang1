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

import json
import logging
import os
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ── 注音风格 ──
STYLE_TONE = "tone"    # 带声调符号：zhōng guó
STYLE_TONE3 = "tone3"  # SAPI/数字式：zhong1 guo2
STYLE_NORMAL = "normal"  # 无声调：zhong guo

_VALID_STYLES = (STYLE_TONE, STYLE_TONE3, STYLE_NORMAL)

_IMPORT_ERR = ""

# 校订表注入状态（幂等；_apply_overrides 首次调用时写入）
_OVERRIDES_APPLIED = False
_OVERRIDE_STATS: Dict[str, Any] = {}

# ═══════════════════════════════════════════════════════════
# 人工校订表（2026-09-25 V4.39.1 补齐）
#
# 为什么需要（实测数据，2026-09-25）：
#   pypinyin 开箱实测专名错误率 **20%**（25 例错 5）——
#     大宛→dà wǎn(应 yuān)、皋陶→gāo táo(应 yáo)、
#     金日磾→jīn rì dī(应 mì dī)、樊於期→fán yú qī(应 wū jī)、
#     曹参→cáo cān(应 shēn)；易错词「削苹果」→xuē(应 xiāo)。
#   分区覆盖：基本区 99.7% / 扩展 A 87.7% / 扩展 B 31.1%。
#   古装剧本里古人名、地名、复姓密度极高 ⇒ 不校订会成片读错。
#
# 数据性质（诚实声明）：**人工校订表**，依据普通话异读词审音表 /
#   现代汉语词典常见条目，**非权威数据库**。条目可被外部覆盖：
#   ① 项目自定义：data/pinyin_overrides.json（优先级最高）
#   ② 直接改本表（改完跑 _verify/check_pinyin_dict.py 复核）
# 只收录**高置信度**条目 —— 拿不准的不写（宁可留空也不编造）。
# 格式：词组 → 空格分隔的带声调拼音，**字数必须与词组字数一致**
#   （不一致会在加载时报错，避免静默错位）。
# ═══════════════════════════════════════════════════════════

# ── 古人名 / 历史人物 ──
_PROPER_HISTORY = {
    "单于": "chán yú", "冒顿": "mò dú", "阏氏": "yān zhī",
    "皋陶": "gāo yáo", "郦食其": "lì yì jī", "金日磾": "jīn mì dī",
    "樊於期": "fán wū jī", "曹参": "cáo shēn", "李悝": "lǐ kuī",
    "华佗": "huà tuó", "范蠡": "fàn lǐ", "伍员": "wǔ yún",
    "乐羊": "yuè yáng", "郅都": "zhì dū", "毌丘俭": "guàn qiū jiǎn",
    "尉缭": "wèi liáo", "蔺相如": "lìn xiàng rú", "嫪毐": "lào ǎi",
    "蒯通": "kuǎi tōng", "郦道元": "lì dào yuán", "佛狸": "bì lí",
    "呼衍": "hū yǎn", "慕容": "mù róng", "宇文": "yǔ wén",
    "拓跋": "tuò bá", "独孤": "dú gū", "纳兰": "nà lán",
    "呼延": "hū yán", "赫连": "hè lián", "沮渠": "jǔ qú",
    "禚": "zhuó", "郗": "xī", "逄": "páng", "亓": "qí",
    "仉": "zhǎng", "佴": "nài", "缑": "gōu", "邝": "kuàng",
}

# ── 复姓（含常见单姓异读）──
_PROPER_SURNAME = {
    "尉迟": "yù chí", "万俟": "mò qí", "澹台": "tán tái",
    "亓官": "qí guān", "綦毋": "qí wú", "单父": "shàn fǔ",
    "长孙": "zhǎng sūn", "褚师": "chǔ shī", "公冶": "gōng yě",
    "召公": "shào gōng", "种师道": "chóng shī dào",
}

# ── 古国 / 古族 / 地名 ──
_PROPER_PLACE = {
    "大宛": "dà yuān", "龟兹": "qiū cí", "月氏": "yuè zhī",
    "大月氏": "dà yuè zhī", "吐蕃": "tǔ bō", "吐谷浑": "tǔ yù hún",
    "可汗": "kè hán", "阿房宫": "ē páng gōng", "渑池": "miǎn chí",
    "番禺": "pān yú", "蚌埠": "bèng bù", "六安": "lù ān",
    "铅山": "yán shān", "丽水": "lí shuǐ", "台州": "tāi zhōu",
    "涪陵": "fú líng", "盱眙": "xū yí", "邗江": "hán jiāng",
    "犍为": "qián wéi", "郫县": "pí xiàn", "邛崃": "qióng lái",
    "砀山": "dàng shān", "单县": "shàn xiàn", "乐亭": "lào tíng",
    "蠡县": "lǐ xiàn", "郓城": "yùn chéng", "郯城": "tán chéng",
    "歙县": "shè xiàn", "黟县": "yī xiàn", "鄞州": "yín zhōu",
    "嵊州": "shèng zhōu", "鄄城": "juàn chéng", "郾城": "yǎn chéng",
    "藁城": "gǎo chéng", "犍陀罗": "jiān tuó luó", "于阗": "yú tián",
    "龟山": "guī shān", "会稽": "kuài jī", "阆中": "làng zhōng",
    "婺源": "wù yuán", "番阳": "pó yáng",
}

# ── 常见易错词（多音字语境）──
_TRICKY_WORDS = {
    "削苹果": "xiāo píng guǒ", "削铅笔": "xiāo qiān bǐ",
    "削皮": "xiāo pí", "模样": "mú yàng", "模子": "mú zi",
    "角色": "jué sè", "血泊": "xuè pō", "一模一样": "yī mú yī yàng",
    "大模大样": "dà mú dà yàng", "装模作样": "zhuāng mú zuò yàng",
    "螳臂当车": "táng bì dāng chē", "安步当车": "ān bù dàng chē",
    "自怨自艾": "zì yuàn zì yì", "方兴未艾": "fāng xīng wèi ài",
    "长歌当哭": "cháng gē dàng kū", "当头棒喝": "dāng tóu bàng hè",
    "博闻强识": "bó wén qiáng zhì", "标识": "biāo zhì",
    "倔强": "jué jiàng", "强词夺理": "qiǎng cí duó lǐ",
    "牵强附会": "qiān qiǎng fù huì", "呼天抢地": "hū tiān qiāng dì",
    "数见不鲜": "shuò jiàn bù xiān", "屡见不鲜": "lǚ jiàn bù xiān",
    "鲜为人知": "xiǎn wéi rén zhī", "载歌载舞": "zài gē zài wǔ",
    "怨声载道": "yuàn shēng zài dào", "千载难逢": "qiān zǎi nán féng",
    "三年五载": "sān nián wǔ zǎi", "下载": "xià zài", "记载": "jì zǎi",
    "审时度势": "shěn shí duó shì", "度德量力": "duó dé liàng lì",
    "以己度人": "yǐ jǐ duó rén", "拐弯抹角": "guǎi wān mò jiǎo",
    "抹布": "mā bù", "抹墙": "mò qiáng", "乳臭未干": "rǔ xiù wèi gān",
    "无色无臭": "wú sè wú xiù", "臭名昭著": "chòu míng zhāo zhù",
    "对称": "duì chèn", "称心如意": "chèn xīn rú yì",
    "相称": "xiāng chèn", "牌坊": "pái fāng", "磨坊": "mò fáng",
    "作坊": "zuō fang", "别墅": "bié shù", "嫔妃": "pín fēi",
    "亵渎": "xiè dú", "呱呱坠地": "gū gū zhuì dì",
    "绿林": "lù lín", "绿营": "lù yíng", "鸭绿江": "yā lù jiāng",
    "般若": "bō rě", "阿弥陀佛": "ē mí tuó fó",
    "刹那": "chà nà", "宝刹": "bǎo chà", "忏悔": "chàn huǐ",
    "缱绻": "qiǎn quǎn", "旖旎": "yǐ nǐ", "氤氲": "yīn yūn",
    "饕餮": "tāo tiè", "耄耋": "mào dié", "魑魅魍魉": "chī mèi wǎng liǎng",
    "觊觎": "jì yú", "龃龉": "jǔ yǔ", "踟蹰": "chí chú",
    "参差": "cēn cī", "荏苒": "rěn rǎn", "纨绔": "wán kù",
    "妊娠": "rèn shēn", "怔忡": "zhēng chōng", "狡黠": "jiǎo xiá",
    "皴裂": "cūn liè", "蓦地": "mò dì", "罹难": "lí nàn",
    "骠骑": "piào qí", "骠勇": "piào yǒng", "黄骠马": "huáng biāo mǎ",
}

# ── 单字校订（词组表无法覆盖时兜底）──
_SINGLE_OVERRIDES = {
    "龘": "dá", "靐": "bìng", "齉": "nàng", "爨": "cuàn",
    "羴": "shān", "猋": "biāo", "麤": "cū", "毳": "cuì",
    "囧": "jiǒng", "烎": "yín", "砳": "lè", "嘦": "jiào",
    "勥": "jiàng", "巭": "bū", "恏": "hào", "兲": "tiān",
    "氼": "nì", "嫑": "báo", "嘂": "jiào", "圐": "kū",
    "圙": "lüè", "玊": "sù", "孖": "mā", "冚": "kǎn",
}

_DEFAULT_OVERRIDES_PATH = "data/pinyin_overrides.json"


def _overrides_path() -> str:
    """项目自定义读音表路径（相对项目根）。"""
    try:
        root = os.path.dirname(os.path.dirname(os.path.dirname(
            os.path.dirname(os.path.abspath(__file__)))))
        return os.path.join(root, _DEFAULT_OVERRIDES_PATH)
    except Exception:
        return ""


def _parse_phrase(pinyin_str: str, word: str) -> Optional[List[List[str]]]:
    """把 ``"chán yú"`` 解析成 pypinyin 需要的 ``[["chán"], ["yú"]]``。

    **字数校验**：拼音音节数必须等于词字数，否则返回 None（宁可跳过，
    绝不静默错位把整句读错）—— 这是本表最容易出错的环节。
    """
    parts = [p for p in str(pinyin_str or "").split() if p]
    if not parts or len(parts) != len(word):
        logger.warning("[pinyin_dict] 校订条目字数不符，已跳过：%r → %r",
                       word, pinyin_str)
        return None
    return [[p] for p in parts]


def _apply_overrides() -> Dict[str, Any]:
    """把校订表注入 pypinyin（幂等，只做一次）。

    返回统计：``{"phrases": n, "singles": m, "user_phrases": k, "skipped": [...]}``
    """
    global _OVERRIDE_STATS, _OVERRIDES_APPLIED
    if _OVERRIDES_APPLIED:
        return _OVERRIDE_STATS
    mod, _ = _load_pypinyin()
    stats = {"phrases": 0, "singles": 0, "user_phrases": 0, "skipped": []}
    if mod is None:
        _OVERRIDE_STATS = stats
        return stats

    merged: Dict[str, str] = {}
    merged.update(_PROPER_HISTORY)
    merged.update(_PROPER_SURNAME)
    merged.update(_PROPER_PLACE)
    merged.update(_TRICKY_WORDS)

    # 项目自定义表（优先级最高，可覆盖内置条目）
    user: Dict[str, Any] = {}
    path = _overrides_path()
    if path and os.path.isfile(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                user = data
        except Exception:
            logger.debug("[pinyin_dict] 自定义读音表读取失败（忽略）", exc_info=True)

    phrase_dict: Dict[str, List[List[str]]] = {}
    for word, py in merged.items():
        parsed = _parse_phrase(py, word)
        if parsed is None:
            stats["skipped"].append(word)
            continue
        phrase_dict[word] = parsed
    stats["phrases"] = len(phrase_dict)

    user_phrase = user.get("phrases") if isinstance(user, dict) else None
    if isinstance(user_phrase, dict):
        for word, py in user_phrase.items():
            parsed = _parse_phrase(str(py or ""), str(word))
            if parsed is None:
                stats["skipped"].append(str(word))
                continue
            phrase_dict[str(word)] = parsed
            stats["user_phrases"] += 1

    single: Dict[str, str] = dict(_SINGLE_OVERRIDES)
    user_chars = user.get("chars") if isinstance(user, dict) else None
    if isinstance(user_chars, dict):
        for ch, py in user_chars.items():
            if len(str(ch)) == 1 and str(py or "").strip():
                single[str(ch)] = str(py).strip()

    try:
        if phrase_dict:
            mod.load_phrases_dict(phrase_dict)
        if single:
            mod.load_single_dict(single, style=mod.Style.TONE)
        stats["singles"] = len(single)
        logger.info("[pinyin_dict] 校订表已注入：词组 %d（含用户 %d）+ 单字 %d",
                    stats["phrases"], stats["user_phrases"], stats["singles"])
    except Exception:
        logger.debug("[pinyin_dict] 校订表注入失败（用原始字典）", exc_info=True)

    _OVERRIDE_STATS = stats
    _OVERRIDES_APPLIED = True
    return stats


def _ensure_ready():
    """所有注音入口的统一前置：注入校订表（幂等）。"""
    _apply_overrides()


def _load_ready():
    """载入 pypinyin 并确保校订表已注入（入口统一走这里）。

    注意与 ``_load_pypinyin`` 的分工：后者只做裸导入，供 ``_apply_overrides``
    内部使用 —— 若在裸导入里调注入，注入又调裸导入，会无限递归。
    """
    mod, err = _load_pypinyin()
    if mod is not None and not _OVERRIDES_APPLIED:
        _apply_overrides()
    return mod, err



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
    mod, _ = _load_ready()
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
    mod, err = _load_ready()
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
    mod, err = _load_ready()
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
    """字典可用性 / 校订表 / 实测覆盖（诊断与 UI 展示）。

    覆盖率是 **2026-09-25 实测值**，不是估计——用于诚实暴露能力边界。
    """
    ok, reason = is_available()
    if not ok:
        return {"available": False, "reason": reason, "backend": "pypinyin"}
    mod, _ = _load_pypinyin()
    ov = _apply_overrides()
    ver = getattr(mod, "__version__", "unknown")
    user_path = _overrides_path()
    return {
        "available": True, "backend": "pypinyin", "version": ver,
        "overrides": {
            "phrases": ov.get("phrases", 0),
            "singles": ov.get("singles", 0),
            "user_phrases": ov.get("user_phrases", 0),
            "skipped": ov.get("skipped", []),
            "user_table": user_path if (user_path and os.path.isfile(user_path)) else "",
            "note": "人工校订表（依据普通话异读词审音表常见条目）；"
                    "可用 data/pinyin_overrides.json 覆盖",
        },
        "coverage_measured_2026_09_25": {
            "CJK 基本区": "99.7%（20924/20992，缺口多为度量衡合字如 兙兡嗧）",
            "扩展 A 区": "87.7%（5779/6592）",
            "扩展 B 区": "31.1%（抽样；未覆盖字标 unknown，不编造读音）",
            "专名（姓氏/地名/古人名）": "校订前 80% → 校订后经检查脚本断言",
        },
        "covers": ["CJK 基本区", "扩展 A 大部", "常用/生僻/三叠字",
                   "词组级多音字消歧", "古人名/地名/复姓人工校订"],
        "not_covers": ["CJK 扩展 B 区及以后（如 𠀋𠮷）→ 标 unknown，不编造读音"],
        "styles": list(_VALID_STYLES),
        "note": "离线确定性注音；LLM 仅在需要语境判断时参与，且候选音由本字典提供",
    }


def override_template() -> Dict[str, Any]:
    """项目自定义读音表模板（放到 ``data/pinyin_overrides.json`` 即生效）。

    用途：剧中人名 / 门派名 / 招式名的读音**全项目统一**（短剧高频需求）。
    格式：``phrases`` = {"词": "空格分隔带声调拼音"}（**字数必须一致**，
    否则该条被跳过并记入 ``stats()["overrides"]["skipped"]``）；
    ``chars`` = {"单字": "拼音"}。
    """
    return {
        "phrases": {
            "南宫婉": "nán gōng wǎn",
            "萧炎": "xiāo yán",
            "示例门派": "shì lì mén pài",
        },
        "chars": {"龘": "dá"},
    }
