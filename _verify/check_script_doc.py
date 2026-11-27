# -*- coding: utf-8 -*-
"""ScriptDoc 长篇剧本结构守卫（WS-D D3，2026-10-23 刀0）

断言：
  ① 结构在册：ScriptDoc/Episode 字段齐 / 模块级薄封装在 / version 恒透传
  ② 纯模型纪律：无 PySide6/PyQt6/PyQt5/requests/sqlite3 / 无 print / 无文件 IO
  ③ 不猜集数：create_script_doc 的 episodes 恒为空；空 doc 合法但 validate 报「剧集为空」
  ④ 不猜集号：add_episode 收到 <=0 / 非 int / bool / 重复集号 ⇒ ValueError，
     **不重编号、不覆盖**
  ⑤ 不编造钩子/时长：hook 缺省 ""、duration_target 缺省 0.0 ⇒ 都进 errors（不补值）
  ⑥ 返回新对象：add_episode 不改入参，且结果按 number 升序
  ⑦ 序列化往返恒等 + 畸形输入不抛

用法（项目根执行）：python _verify/check_script_doc.py
退出码 0 = 通过；1 = 有漂移。
"""
from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

MODULE_REL = "app/core/script_doc.py"

problems = []


def _fail(msg: str) -> None:
    problems.append(msg)


def _src() -> str:
    with open(os.path.join(ROOT, MODULE_REL), "r", encoding="utf-8") as f:
        return f.read()


def _code_only() -> str:
    """剥掉注释与字符串字面量，只留会执行的代码。

    文档字符串里正常会写「不 import Qt 绑定」这类说明，全文 grep 会把说明
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
    from app.core import script_doc as m

    for name in ("ScriptDoc", "Episode", "create_script_doc", "add_episode",
                 "validate_script_doc", "to_dict", "from_dict"):
        if not hasattr(m, name):
            _fail(f"① 公开件被删/改名：{name}")
    doc_data = m.create_script_doc("标题").to_dict()
    for key in ("doc_id", "title", "logline", "genre", "episodes", "version", "created_at"):
        if key not in doc_data:
            _fail(f"① ScriptDoc.to_dict 缺字段：{key}")
    ep_data = m.Episode(number=1, title="第一集").to_dict()
    for key in ("number", "title", "synopsis", "beats", "hook", "duration_target"):
        if key not in ep_data:
            _fail(f"① Episode.to_dict 缺字段：{key}")
    if doc_data.get("version") != 1:
        _fail("① 新建 doc version 不是 1")


# ── ② 纯模型纪律 ──────────────────────────────────────────────────────

def check_purity() -> None:
    src = _code_only()
    for token in ("PySide6", "PyQt6", "PyQt5", "requests", "sqlite3", "subprocess", "QApplication"):
        if token in src:
            _fail(f"② 纯模型模块出现运行时依赖：{token}")
    if "print" in src:
        _fail("② 纯模型模块出现 print")
    for token in ("open", "makedirs", "fsync"):
        if token in src:
            _fail(f"② 纯模型模块出现文件 IO：{token}")


# ── ③ 不猜集数 ────────────────────────────────────────────────────────

def check_no_episode_guessing() -> None:
    from app.core.script_doc import create_script_doc, validate_script_doc

    doc = create_script_doc("标题")
    if doc.episodes != []:
        _fail(f"③ 新建 doc 竟自带剧集（不猜集数被破坏）：{len(doc.episodes)} 集")
    errors = validate_script_doc(doc)
    if not any("剧集为空" in e for e in errors):
        _fail("③ 空 doc 未报「剧集为空」（空是合法对象，但必须如实提示）")
    if not any("标题" in e for e in validate_script_doc(create_script_doc(""))):
        _fail("③ 空标题未进 errors")


# ── ④ 不猜集号 ────────────────────────────────────────────────────────

def check_no_number_guessing() -> None:
    from app.core.script_doc import add_episode, create_script_doc

    doc = create_script_doc("标题")
    for bad in (0, -1, "1", 1.5, True):
        try:
            add_episode(doc, number=bad)
            _fail(f"④ add_episode 接受了非法集号 {bad!r}（应 ValueError）")
        except ValueError:
            pass
        except Exception as exc:  # noqa: BLE001
            _fail(f"④ 集号 {bad!r} 抛了非 ValueError：{exc!r}")
    # 重复集号：不覆盖、不重编号
    doc1 = add_episode(doc, number=1, title="一")
    try:
        add_episode(doc1, number=1, title="覆盖尝试")
        _fail("④ 重复集号未被拦（可能静默覆盖既有集）")
    except ValueError:
        pass
    except Exception as exc:  # noqa: BLE001
        _fail(f"④ 重复集号抛了非 ValueError：{exc!r}")
    # 非 ScriptDoc 入参 TypeError
    try:
        add_episode("not-a-doc", number=1)
        _fail("④ add_episode 接受非 ScriptDoc（应 TypeError）")
    except TypeError:
        pass
    except Exception as exc:  # noqa: BLE001
        _fail(f"④ 错类型入参抛了非 TypeError：{exc!r}")
    # beats 类型硬约束：整段字符串不许拆字
    try:
        add_episode(doc, number=2, beats="一整段文本")
        _fail("④ beats 传字符串竟被接受（可能被拆成单字）")
    except ValueError:
        pass


# ── ⑤ 不编造钩子/时长 ────────────────────────────────────────────────

def check_no_fabrication() -> None:
    from app.core.script_doc import add_episode, create_script_doc, validate_script_doc

    doc = add_episode(create_script_doc("标题"), number=1, title="第一集")
    errors = validate_script_doc(doc)
    if not any("hook" in e for e in errors):
        _fail("⑤ 空 hook 未进 errors（可能被自动编造钩子）")
    if not any("duration_target" in e for e in errors):
        _fail("⑤ 缺省 duration_target=0 未进 errors（可能被按常见集长补值）")
    # 正常填齐应通过
    good = add_episode(create_script_doc("标题"), number=1, title="第一集",
                       hook="悬念钩子", duration_target=90.0)
    if validate_script_doc(good) != []:
        _fail(f"⑤ 填齐的一集仍报错：{validate_script_doc(good)}")


# ── ⑥ 返回新对象 + 升序 ───────────────────────────────────────────────

def check_immutability_and_order() -> None:
    from app.core.script_doc import add_episode, create_script_doc

    doc = create_script_doc("标题")
    doc2 = add_episode(doc, number=2, title="二")
    if doc.episodes != []:
        _fail("⑥ add_episode 改动了入参 doc（应返回新对象）")
    if doc2 is doc:
        _fail("⑥ add_episode 返回了同一对象（撤销/快照会互相污染）")
    doc3 = add_episode(doc2, number=1, title="一")
    if [ep.number for ep in doc3.episodes] != [1, 2]:
        _fail(f"⑥ 插集后未按 number 升序：{[ep.number for ep in doc3.episodes]}")
    # 乱序直接构造要能被 validate 抓出
    from app.core.script_doc import Episode, ScriptDoc, validate_script_doc
    messy = ScriptDoc(doc_id="x", title="t", episodes=[
        Episode(number=2, title="二", hook="h", duration_target=10.0),
        Episode(number=1, title="一", hook="h", duration_target=10.0),
    ])
    if not any("升序" in e for e in validate_script_doc(messy)):
        _fail("⑥ 手工构造的乱序 episodes 未被 validate 报出")


# ── ⑦ 序列化往返 ──────────────────────────────────────────────────────

def check_roundtrip() -> None:
    from app.core.script_doc import ScriptDoc, add_episode, create_script_doc

    doc = add_episode(create_script_doc("长夜拾光", logline="梗概", genre="悬疑"),
                      number=1, title="第一集", synopsis="提要",
                      beats=["动作一", "动作二"], hook="钩子", duration_target=95.0)
    first = doc.to_dict()
    second = ScriptDoc.from_dict(first).to_dict()
    if first != second:
        _fail("⑦ to_dict → from_dict → to_dict 不恒等")
    try:
        broken = ScriptDoc.from_dict({"episodes": "not-a-list"})
        if broken.episodes != []:
            _fail("⑦ 畸形 episodes 未落回空列表")
    except Exception as exc:  # noqa: BLE001
        _fail(f"⑦ from_dict 对畸形输入抛异常：{exc!r}")
    try:
        mixed = ScriptDoc.from_dict({"episodes": [{"number": 1}, "junk", 42]})
        if len(mixed.episodes) != 1:
            _fail(f"⑦ 非 dict 的 episode 条目未被跳过：{len(mixed.episodes)} 条")
    except Exception as exc:  # noqa: BLE001
        _fail(f"⑦ 混合 episode 输入抛异常：{exc!r}")


def main() -> int:
    check_surface()
    check_purity()
    check_no_episode_guessing()
    check_no_number_guessing()
    check_no_fabrication()
    check_immutability_and_order()
    check_roundtrip()
    if problems:
        for p in problems:
            print(f"FAIL  {p}")
        return 1
    print("PASS  ScriptDoc 长篇结构：结构在册/纯模型/不猜集数/不猜集号/不编造钩子时长/返回新对象且升序/往返恒等")
    return 0


if __name__ == "__main__":
    sys.exit(main())
