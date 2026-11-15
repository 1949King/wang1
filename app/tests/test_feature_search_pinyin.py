# -*- coding: utf-8 -*-
"""功能搜索的拼音表守卫。

背景（2026-11-15 修）：`_PINYIN_MAP` 里有 **43 处重复键** ——
Python 的 dict 字面量遇到重复键**不报错、后者覆盖前者**，所以这是「静默丢数据」的
典型形态：`"乐": "le"` 和 `"乐": "yue"` 同时存在时，只有后面那个生效，
拼音搜索里就少了一种读法。另有 `"暖": "uan"` 漏了首字母 n 的错字。

这些断言全部不依赖 UI：拼音表是纯数据，直接查即可。
"""
from __future__ import annotations

import ast
import inspect
import re

from app.modules.lego import feature_search as FS


def _map_pairs() -> list[tuple[str, str]]:
    """从源码 AST 取 `_PINYIN_MAP` 的全部键值对（**含重复的**）。

    不用 `FS._PINYIN_MAP` 直接查 —— 运行时那个 dict 已经把重复键合并掉了，
    看不到问题本身。
    """
    tree = ast.parse(inspect.getsource(FS))
    for n in ast.walk(tree):
        if isinstance(n, ast.AnnAssign) and getattr(n.target, "id", "") == "_PINYIN_MAP":
            keys, vals = n.value.keys, n.value.values
            return [
                (k.value, v.value)
                for k, v in zip(keys, vals)
                if isinstance(k, ast.Constant) and isinstance(v, ast.Constant)
            ]
    raise AssertionError("源码里找不到 _PINYIN_MAP")


def test_pinyin_map_has_no_duplicate_keys() -> None:
    """重复键 = 静默覆盖，必须为 0。"""
    pairs = _map_pairs()
    keys = [k for k, _ in pairs]
    dup = {k for k in keys if keys.count(k) > 1}
    assert not dup, "拼音表存在重复键（后者会静默覆盖前者）：%s" % sorted(dup)


def test_every_pinyin_value_is_plain_lowercase() -> None:
    """值必须是纯小写字母。`uan`（漏 n）这类错字只有格式断言能抓。"""
    bad = [(k, v) for k, v in _map_pairs() if not re.fullmatch(r"[a-z]+", v)]
    assert not bad, "拼音值不是纯小写字母：%s" % bad


def test_warm_typo_is_fixed() -> None:
    assert FS._PINYIN_MAP["暖"] == "nuan"
    assert "nuan" in FS._get_pinyin_full("暖色")


def test_polyphonic_le_keeps_both_readings() -> None:
    """「乐」既要能按 yue 搜到，也要能按 le 搜到（主表只能放一个读音）。"""
    py = FS._get_pinyin_full("音乐")
    assert "yinyue" in py, py          # 主读音仍在原位，不破坏连续匹配
    assert "le" in py, py             # 备选读音追加在尾部


def test_polyphonic_does_not_corrupt_normal_words() -> None:
    """不该被多音字表污染的普通词，拼音必须逐字连续。"""
    assert FS._get_pinyin_full("调色") == "diaose"
    assert FS._get_pinyin_full("删除") == "shanchu"
    assert " " not in FS._get_pinyin_full("删除")


def test_index_search_hits_by_both_readings() -> None:
    """端到端：索引里的拼音搜索域同时覆盖两种读法。"""
    idx = FS.FeatureIndex()
    idx.add(FS.FeatureItem(name="音乐配乐", tab_index=0))
    for q in ("yinyue", "le", "yy"):
        assert idx.search(q), "查询 %r 没命中" % q


def test_initials_stay_single_letter_per_char() -> None:
    """首字母串不能被备选读音撑长（否则「yy」会变成「yyle」之类）。"""
    assert FS._get_pinyin_initials("音乐") == "yy"
