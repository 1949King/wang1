# -*- coding: utf-8 -*-
"""IdeaCard 立意卡模型守卫（WS-D D4，2026-10-23 刀0）

断言：
  ① 结构在册：三态 draft/ready/blocked / IdeaCard 字段齐 / 模块级薄封装在
  ② 纯模型纪律：无 PyQt6/requests/sqlite3 / 无 print / 无文件 IO
  ③ 不猜题材受众：create_idea_card 缺省留空，validate 必须报错（不自动补值）
  ④ status 三值硬：set_status 非法值 ValueError；from_dict 遇到非法字符串**原样保留**
     （交给 validate 报错，不静默回落成 draft）
  ⑤ blocked 必须有合规备注：status=blocked 且备注为空 ⇒ 进 errors（不臆造备注）
  ⑥ 返回新对象：set_status / replace 不改入参（撤销与快照的前提）
  ⑦ 序列化往返恒等 + 畸形输入不抛

用法（项目根执行）：python _verify/check_idea_card.py
退出码 0 = 通过；1 = 有漂移。
"""
from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

MODULE_REL = "app/core/idea_card.py"

problems = []


def _fail(msg: str) -> None:
    problems.append(msg)


def _src() -> str:
    with open(os.path.join(ROOT, MODULE_REL), "r", encoding="utf-8") as f:
        return f.read()


def _code_only() -> str:
    """剥掉注释与字符串字面量，只留会执行的代码。

    文档字符串里正常会写「不 import PyQt6」这类说明，全文 grep 会把说明
    当成依赖（本守卫首跑即误报）。
    """
    import tokenize

    kept = []
    try:
        with open(os.path.join(ROOT, MODULE_REL), "rb") as f:
            for tok in tokenize.tokenize(f.readline):
                if tok.type in (tokenize.COMMENT, tokenize.STRING):
                    continue
                if tok.type in (tokenize.NL, tokenize.NEWLINE, tokenize.INDENT,
                                tokenize.DEDENT, tokenize.ENCODING, tokenize.ENDMARKER):
                    continue
                kept.append(tok.string)
    except (tokenize.TokenError, OSError, SyntaxError) as exc:
        raise AssertionError(f"源码无法分词（语法错误？）：{exc!r}") from exc
    return " ".join(kept)


# ── ① 结构在册 ────────────────────────────────────────────────────────

def check_surface() -> None:
    from app.core import idea_card as m

    if tuple(getattr(m, "IDEA_CARD_STATUSES", ())) != ("draft", "ready", "blocked"):
        _fail(f"① IDEA_CARD_STATUSES 漂移：{getattr(m, 'IDEA_CARD_STATUSES', None)!r}")
    for name in ("IdeaCard", "create_idea_card", "validate_idea_card",
                 "set_status", "to_dict", "from_dict"):
        if not hasattr(m, name):
            _fail(f"① 公开件被删/改名：{name}")
    data = m.create_idea_card("测试").to_dict()
    for key in ("card_id", "title", "logline", "genre", "audience",
                "tone", "compliance_notes", "status"):
        if key not in data:
            _fail(f"① IdeaCard.to_dict 缺字段：{key}")


# ── ② 纯模型纪律 ──────────────────────────────────────────────────────

def check_purity() -> None:
    src = _code_only()
    for token in ("PyQt6", "requests", "sqlite3", "subprocess", "QApplication"):
        if token in src:
            _fail(f"② 纯模型模块出现运行时依赖：{token}")
    if "print" in src:
        _fail("② 纯模型模块出现 print")
    for token in ("open", "makedirs", "fsync"):
        if token in src:
            _fail(f"② 纯模型模块出现文件 IO：{token}")


# ── ③ 不猜题材受众 ────────────────────────────────────────────────────

def check_no_guessing() -> None:
    from app.core.idea_card import create_idea_card, validate_idea_card

    card = create_idea_card("只有标题")
    if card.genre != "" or card.audience != "":
        _fail("③ genre/audience 缺省被自动填了值（不猜纪律被破坏）")
    errors = validate_idea_card(card)
    if not any("题材" in e for e in errors):
        _fail("③ 空题材未进 errors（可能被静默接受）")
    if not any("受众" in e for e in errors):
        _fail("③ 空受众未进 errors")
    # logline 同样是硬性要求
    if not any("logline" in e for e in errors):
        _fail("③ 空 logline 未进 errors")
    # tone 允许留空：填齐其它项后不应因 tone 报错
    full = create_idea_card("标题", logline="立意", genre="悬疑", audience="大众", tone="")
    tone_errs = [e for e in validate_idea_card(full) if "tone" in e.lower() or "风格" in e]
    if tone_errs:
        _fail(f"③ tone 留空却报错（风格未定不算错误）：{tone_errs}")
    if validate_idea_card(full) != []:
        _fail(f"③ 填齐的卡仍有 errors：{validate_idea_card(full)}")


# ── ④ status 三值硬 ──────────────────────────────────────────────────

def check_status_strict() -> None:
    from app.core.idea_card import IdeaCard, create_idea_card, set_status

    card = create_idea_card("标题")
    if card.status != "draft":
        _fail("④ 新建卡 status 不是 draft")
    try:
        set_status(card, "done")
        _fail("④ set_status 接受非法 status（应 ValueError，不猜业务状态）")
    except ValueError:
        pass
    except Exception as exc:  # noqa: BLE001
        _fail(f"④ set_status 抛了非 ValueError：{exc!r}")
    # 合法三态都能设
    for value in ("draft", "ready", "blocked"):
        try:
            set_status(card, value)
        except Exception as exc:  # noqa: BLE001
            _fail(f"④ 合法 status {value!r} 竟被拒：{exc!r}")
    # from_dict 保留非法字符串（交给 validate，不静默回落）
    restored = IdeaCard.from_dict({"title": "t", "status": "weird"})
    if restored.status != "weird":
        _fail(f"④ from_dict 把非法 status 静默改成了 {restored.status!r}（应原样保留待报错）")
    # 缺 status 才用 draft
    if IdeaCard.from_dict({"title": "t"}).status != "draft":
        _fail("④ from_dict 缺 status 未落回新建态 draft")


# ── ⑤ blocked 必须有合规备注 ──────────────────────────────────────────

def check_blocked_requires_notes() -> None:
    from app.core.idea_card import create_idea_card, set_status, validate_idea_card

    card = create_idea_card("标题", logline="立意", genre="悬疑", audience="大众")
    blocked = set_status(card, "blocked")
    if not any("compliance_notes" in e for e in validate_idea_card(blocked)):
        _fail("⑤ blocked 无合规备注竟通过校验（不臆造备注的纪律被破坏）")
    # 空白备注不算填了
    with_blank = create_idea_card("标题", logline="立意", genre="悬疑",
                                  audience="大众", compliance_notes=["   ", ""])
    blocked2 = set_status(with_blank, "blocked")
    if not any("compliance_notes" in e for e in validate_idea_card(blocked2)):
        _fail("⑤ 纯空白备注被当成已填写")
    # 真备注则通过
    with_note = create_idea_card("标题", logline="立意", genre="悬疑",
                                 audience="大众", compliance_notes=["涉及真实案件，需法务复核"])
    if validate_idea_card(set_status(with_note, "blocked")) != []:
        _fail("⑤ 填了真备注的 blocked 卡仍报错")


# ── ⑥ 返回新对象不改入参 ──────────────────────────────────────────────

def check_immutability() -> None:
    from app.core.idea_card import create_idea_card, set_status

    card = create_idea_card("标题")
    original_status = card.status
    new_card = set_status(card, "ready")
    if card.status != original_status:
        _fail("⑥ set_status 改动了入参卡（应返回新对象）")
    if new_card is card:
        _fail("⑥ set_status 返回了同一个对象（撤销/快照会互相污染）")
    if new_card.status != "ready":
        _fail("⑥ set_status 未返回新状态")
    # 列表隔离：to_dict 的 compliance_notes 必须是副本
    c2 = create_idea_card("t", compliance_notes=["a"])
    dumped = c2.to_dict()
    dumped["compliance_notes"].append("b")
    if c2.compliance_notes != ["a"]:
        _fail("⑥ to_dict 返回了内部列表引用（外部改动污染卡）")
    # set_status 非 IdeaCard 入参要 TypeError
    try:
        set_status("not-a-card", "ready")
        _fail("⑥ set_status 接受非 IdeaCard 入参（应 TypeError，不猜、不重建）")
    except TypeError:
        pass
    except Exception as exc:  # noqa: BLE001
        _fail(f"⑥ set_status 对错类型抛了非 TypeError：{exc!r}")


# ── ⑦ 序列化往返 ──────────────────────────────────────────────────────

def check_roundtrip() -> None:
    from app.core.idea_card import IdeaCard, create_idea_card

    card = create_idea_card("标题", logline="立意", genre="悬疑",
                            audience="大众", tone="冷峻",
                            compliance_notes=["备注一", "备注二"])
    first = card.to_dict()
    second = IdeaCard.from_dict(first).to_dict()
    if first != second:
        _fail("⑦ to_dict → from_dict → to_dict 不恒等")
    try:
        broken = IdeaCard.from_dict("not-a-dict")
        if broken.title != "" or broken.status != "draft":
            _fail("⑦ 非 dict 输入未落回空卡 + draft")
    except Exception as exc:  # noqa: BLE001
        _fail(f"⑦ from_dict 对非 dict 抛异常：{exc!r}")
    try:
        if IdeaCard.from_dict({"compliance_notes": "a-string"}).compliance_notes != []:
            _fail("⑦ 字符串 compliance_notes 未落回空列表（可能把整串当一条备注）")
    except Exception as exc:  # noqa: BLE001
        _fail(f"⑦ compliance_notes 畸形输入抛异常：{exc!r}")


def main() -> int:
    check_surface()
    check_purity()
    check_no_guessing()
    check_status_strict()
    check_blocked_requires_notes()
    check_immutability()
    check_roundtrip()
    if problems:
        for p in problems:
            print(f"FAIL  {p}")
        return 1
    print("PASS  IdeaCard 立意卡：结构在册/纯模型/不猜题材受众/三态硬/blocked需合规备注/返回新对象/往返恒等")
    return 0


if __name__ == "__main__":
    sys.exit(main())
