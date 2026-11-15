# -*- coding: utf-8 -*-
"""镜头作用（叙事层）—— 拆镜时给每一镜猜一个「它是干嘛的」

## 为什么单独成文件

`canvas_aigc.py` 已 2900+ 行且顶格在体积守卫容差内，再加 70 行直接超限。
按守卫提示的指引抽成独立模块：本文件只放「作用推测与归一」这一件事，
`canvas_aigc.storyboard_breakdown` 只 import 调用。

## 四档含义（与前端 `ShotPurpose` 的 key 严格对齐）

| key | 中文 | 意思 |
|---|---|---|
| setup | 铺垫 | 交代环境 / 人物 / 关系 |
| advance | 推进 | 让情节往前走 |
| turn | 转折 | 打破观众预期 |
| close | 收尾 | 落幅 / 留钩子 |

## 为什么值得做

用户从零想「这一镜该是什么作用」很难，**改一个现成的判断很容易**。
拆镜时顺手猜一个，比让用户对着 10 张空卡逐张点选要省 10 次点击。
猜错也没关系 —— 它是起点，不是结论。
"""
from typing import Any

#: 作用名归一表。收录中文是因为 LLM 很可能直接输出「转折」而不是 `turn`；
#: 前端只认四个英文 key，所以在后端统一。
_SHOT_PURPOSE_ALIAS = {
    "setup": "setup", "铺垫": "setup", "开场": "setup", "交代": "setup", "建立": "setup",
    "advance": "advance", "推进": "advance", "发展": "advance", "递进": "advance",
    "turn": "turn", "转折": "turn", "反转": "turn", "突变": "turn",
    "close": "close", "收尾": "close", "结尾": "close", "落幅": "close",
}

#: 转折提示词：命中即判为转折镜。
#: 为什么优先于位置：位置只能猜结构（首=铺垫、末=收尾），
#: 而转折词能读到语义 ——「她推开门，突然发现屋里没人」这种才是真转折。
_TURN_HINTS = (
    "突然", "没想到", "原来", "其实", "竟然", "却不", "但是", "然而",
    "猛地", "忽然", "谁知道", "不料",
)


def normalize_shot_purpose(value: Any) -> str:
    """把 LLM 可能输出的中文/英文作用名归一成前端 `ShotPurpose` 的 key。

    无法识别时返回**空串**（调用方据此回落到 `infer_shot_purpose`）。
    刻意不在这里回落到 advance —— 那样会把「LLM 没给」伪装成「真是推进」。
    """
    key = str(value or "").strip().lower()
    return _SHOT_PURPOSE_ALIAS.get(key, "")


def infer_shot_purpose(index: int, total: int, text: str) -> str:
    """按位置 + 转折词推测镜头作用。

    判定顺序：转折词 → 首镜铺垫 → 末镜收尾 → 其余推进。
    单镜时返回 setup（否则整条片子连铺垫都没有）。
    """
    t = text or ""
    if any(w in t for w in _TURN_HINTS):
        return "turn"
    if index <= 0:
        return "setup"
    if index >= max(1, total - 1):
        return "close"
    return "advance"
