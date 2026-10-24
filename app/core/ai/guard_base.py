"""生成质量守护 · 共享基座
============================

`tts_guard` / `character_anchor` / `expression_guard` / `prop_guard` 四个守护模块的公共设施。

**抽出来的动机**：四模块曾各自实现 `_norm` / 指纹 / `diff_*`（4 份近似代码），
改一处要改四处 —— 与项目「单一事实来源」纪律相悖。本模块把共性收敛到一处。

提供：

  ==========================  ============================================
  ``normalize_text``          特征值归一化（list 拼接 / 去空白 / None → ""）
  ``normalize_traits``        按字段表提取特征（空值不收录）
  ``stable_fingerprint``      稳定指纹（排序后 sha1 前 N 位）
  ``diff_traits``             特征漂移比对（drifted / detail / 前后指纹 / reason）
  ``to_float``                数值安全转换（含 NaN → 0.0）
  ``extract_json_array``      从 LLM 回复提取 JSON 数组（容忍 markdown 包裹）
  ``merge_unique``            去重保序
  ==========================  ============================================

设计纪律：**只依赖标准库、不 import app 包**（保证可脱离 Qt / 硬件探测单测）。

导入约定：本模块被同目录模块以 **相对导入** 引用（``from .guard_base import ...``）。
`_verify/` 下的脚本要测这些模块时，须先用「伪包」方式加载（见
`_verify/check_guard_base.py` 的 ``_load_ai_module``）—— 这样相对导入可用，
又不会把 `app` 包拉进来。
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from typing import Any, Dict, Iterable, List, Sequence

logger = logging.getLogger("AI短剧编辑器.core.ai.guard_base")

_WS = re.compile(r"\s+")
_JSON_ARRAY = re.compile(r"\[.*\]", re.S)


# ═══════════════════════════════════════════════════════════
# 归一化
# ═══════════════════════════════════════════════════════════


def normalize_text(v: Any) -> str:
    """特征值归一化：list/tuple 逗号拼接，其余转字符串并**去空白**。

    去空白是刻意的：仅空格 / 换行的差异不应算作「漂移」（否则误报刷屏）。
    """
    if v is None:
        return ""
    if isinstance(v, (list, tuple)):
        return ",".join(normalize_text(x) for x in v if normalize_text(x))
    return _WS.sub("", str(v)).strip()


def normalize_traits(src: Any, keys: Sequence[str]) -> Dict[str, str]:
    """按 ``keys`` 从 ``src`` 提取特征；**空值不收录**（空字段不该参与漂移判定）。

    >>> normalize_traits({"name": "林晚", "appearance": "长发红衣"}, ("name", "appearance", "x"))
    {'name': '林晚', 'appearance': '长发红衣'}
    """
    if not isinstance(src, dict) or not src:
        return {}
    out: Dict[str, str] = {}
    for key in keys:
        val = normalize_text(src.get(key))
        if val:
            out[key] = val
    return out


# ═══════════════════════════════════════════════════════════
# 指纹 + 漂移
# ═══════════════════════════════════════════════════════════


def stable_fingerprint(traits: Any, *, length: int = 12) -> str:
    """稳定指纹：对 traits 排序后取 sha1 前 ``length`` 位。内容变则指纹变。"""
    if not isinstance(traits, dict) or not traits:
        return ""
    payload = "|".join(f"{k}={traits[k]}" for k in sorted(traits))
    n = max(1, int(length or 12))
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:n]


def diff_traits(before: Any, after: Any) -> Dict[str, Any]:
    """特征漂移比对（两个「特征字典」之间）。

    Returns::

        {"ok", "drifted": [key...], "detail": {key: {"before","after"}},
         "fingerprint_before", "fingerprint_after", "reason"}
    """
    b = before if isinstance(before, dict) else {}
    a = after if isinstance(after, dict) else {}
    drifted: List[str] = []
    detail: Dict[str, Dict[str, str]] = {}
    for key in sorted(set(b) | set(a)):
        bv, av = b.get(key, ""), a.get(key, "")
        if bv != av:
            drifted.append(key)
            detail[key] = {"before": bv, "after": av}
    return {
        "ok": not drifted,
        "drifted": drifted,
        "detail": detail,
        "fingerprint_before": stable_fingerprint(b),
        "fingerprint_after": stable_fingerprint(a),
        "reason": "" if not drifted else f"{len(drifted)} 项特征漂移: {', '.join(drifted)}",
    }


# ═══════════════════════════════════════════════════════════
# 数值 / LLM / 工具
# ═══════════════════════════════════════════════════════════


def to_float(v: Any) -> float:
    """安全转 float；非法值 / NaN 一律降级 ``0.0``（不抛异常）。"""
    try:
        f = float(v)
    except (TypeError, ValueError):
        return 0.0
    if f != f:  # NaN
        return 0.0
    return f


def extract_json_array(text: Any) -> List[Dict[str, Any]]:
    """从 LLM 回复里稳健提取 JSON 数组（容忍 ```json 包裹 / 前后废话）。

    非数组 / 解析失败 / 元素非 dict —— 一律过滤，返回可用的 dict 列表。
    """
    if not text:
        return []
    m = _JSON_ARRAY.search(str(text))
    if not m:
        return []
    try:
        data = json.loads(m.group(0))
    except (ValueError, TypeError):
        return []
    if not isinstance(data, list):
        return []
    return [d for d in data if isinstance(d, dict)]


def merge_unique(items: Any) -> List[str]:
    """字符串去重（**保序**，跳过空值）。用于合并多处负面词。"""
    out: List[str] = []
    seen = set()
    for it in (items or []):
        s = str(it).strip() if it is not None else ""
        if s and s not in seen:
            seen.add(s)
            out.append(s)
    return out
