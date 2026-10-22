# -*- coding: utf-8 -*-
"""时间线乐观并发守卫（刀1 · revision/CAS，2026-10-23）

治理缺口：Agent 写时间线时**没有任何并发保护**——UI 正在编辑时 Agent 的
整段写入会静默覆盖（或反之），「写操作永不自动重试」这条纪律因此退化成
「靠机制缺失来保证」。本守卫把 FableCut 的 revision/409 模型落成可执行断言。

断言：
  ① 版本语义：初值 0；结构/字段写成功后单调 +1
  ② **无真实改动不 bump**：未命中的 remove/set_fields/update_where、
     对空列表 clear —— 不该让别人的 revision 失效
  ③ CAS 拒绝：`base_revision` 不匹配 ⇒ `RevisionConflict`，且**一个字节都不写**
  ④ 保守性：`base_revision=None` 保持历史行为（逐键不变）；非法类型 ⇒ TypeError
  ⑤ 冲突可诊断：异常带 expected/actual/op，消息里说明「本次未执行」
  ⑥ 接入在册：两个宿主写入口（agent_replace_timeline_clips / _apply_action）
     都接受 base_revision，前者冲突时返回 `code="conflict"`
  ⑦ 同一性不变量未被破坏：revision 改造不得换掉 live list 对象
  ⑧ 不得绕道：其它地方不许自建 revision 计数器（单一真相源）

用法（项目根执行）：python _verify/check_timeline_revision.py
退出码 0 = 通过；1 = 有漂移。
"""
from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

EDITOR_REL = "app/modules/lego/editor_module.py"
STORE_REL = "app/core/timeline_store.py"

problems = []


def _fail(msg: str) -> None:
    problems.append(msg)


def _clip(cid: str, **kw):
    row = {"id": cid, "path": f"/tmp/{cid}.mp4", "start_time": 0.0,
           "duration": 1.0, "track": 0, "type": "video"}
    row.update(kw)
    return row


# ── ①② 版本语义 + 不空转 ────────────────────────────────────────────

def check_version_semantics() -> None:
    from app.core.timeline_store import TimelineStore

    st = TimelineStore([])
    if st.revision() != 0:
        _fail(f"① 初值不是 0：{st.revision()}")

    st.add(_clip("a"))
    if st.revision() != 1:
        _fail(f"① add 后 revision 应为 1，实测 {st.revision()}")
    st.add(_clip("b"))
    if st.revision() != 2:
        _fail(f"① 第二次 add 后应为 2，实测 {st.revision()}")

    # ② 未命中不 bump
    before = st.revision()
    if st.remove_by_id("__nope__") != 0:
        _fail("② 移除不存在片段竟返回非 0")
    if st.revision() != before:
        _fail("② 未命中的 remove_by_id 不该 bump（会让别人 revision 失效）")
    if st.set_fields("__nope__", start_time=1.0) is not False:
        _fail("② 未命中的 set_fields 竟返回 True")
    if st.revision() != before:
        _fail("② 未命中的 set_fields 不该 bump")
    if st.update_where(lambda c: False, volume=0.1) != 0:
        _fail("② 全不匹配的 update_where 竟有命中")
    if st.revision() != before:
        _fail("② 零命中的 update_where 不该 bump")

    empty = TimelineStore([])
    empty.clear()
    if empty.revision() != 0:
        _fail("② 对空列表 clear 不该 bump（无真实改动）")


# ── ③ CAS 拒绝 + 不写 ────────────────────────────────────────────────

def check_cas_rejects_without_writing() -> None:
    from app.core.timeline_store import RevisionConflict, TimelineStore

    st = TimelineStore([])
    st.add(_clip("a"))
    stale = st.revision() - 1

    ops = [
        ("add", lambda: st.add(_clip("b"), base_revision=stale)),
        ("remove_by_id", lambda: st.remove_by_id("a", base_revision=stale)),
        ("set_fields", lambda: st.set_fields("a", start_time=9.9, base_revision=stale)),
        ("replace_all", lambda: st.replace_all([], base_revision=stale)),
        ("clear", lambda: st.clear(base_revision=stale)),
        ("update_where", lambda: st.update_where(lambda c: True, volume=0.0,
                                                 base_revision=stale)),
    ]
    snapshot_ids = [c["id"] for c in st.rows()]
    snapshot_start = st.find_by_id("a").get("start_time")
    for name, call in ops:
        try:
            call()
        except RevisionConflict:
            pass
        except Exception as exc:  # noqa: BLE001 - 守卫要抓非预期异常
            _fail(f"③ {name} 抛了非 RevisionConflict：{exc!r}")
            continue
        else:
            _fail(f"③ {name} 未抛 RevisionConflict（陈旧写被放行）")
        # 每次都要验证「确实一个字节都没写」
        if [c["id"] for c in st.rows()] != snapshot_ids:
            _fail(f"③ {name} 冲突后列表被改动：{[c['id'] for c in st.rows()]}")
            snapshot_ids = [c["id"] for c in st.rows()]
        if st.find_by_id("a") is not None and st.find_by_id("a").get("start_time") != snapshot_start:
            _fail(f"③ {name} 冲突后字段被改动")


# ── ④ 保守性 + 非法类型 ──────────────────────────────────────────────

def check_backward_compat() -> None:
    from app.core.timeline_store import TimelineStore

    st = TimelineStore([])
    st.add(_clip("a"))
    st.add(_clip("b"))
    st.set_fields("a", start_time=5.0)
    st.remove_by_id("b")
    if [c["id"] for c in st.rows()] != ["a"]:
        _fail("④ base_revision=None 的既有调用行为被改变")
    if st.revision() != 4:
        _fail(f"④ None 路径的 bump 计数应为 4，实测 {st.revision()}")

    try:
        st.add(_clip("c"), base_revision="1")
        _fail("④ 字符串 base_revision 竟被接受（应 TypeError，不猜）")
    except TypeError:
        pass
    except Exception as exc:  # noqa: BLE001
        _fail(f"④ 非法 base_revision 抛了非 TypeError：{exc!r}")
    try:
        st.add(_clip("c"), base_revision=True)
        _fail("④ bool 竟被当作合法 revision（应 TypeError）")
    except TypeError:
        pass


# ── ⑤ 冲突可诊断 ─────────────────────────────────────────────────────

def check_conflict_diagnostics() -> None:
    from app.core.timeline_store import RevisionConflict, TimelineStore

    st = TimelineStore([])
    st.add(_clip("a"))
    st.add(_clip("b"))
    try:
        st.add(_clip("c"), base_revision=0)
    except RevisionConflict as exc:
        if exc.expected != 0 or exc.actual != 2:
            _fail(f"⑤ 冲突字段不对：expected={exc.expected} actual={exc.actual}")
        if exc.op != "add":
            _fail(f"⑤ 冲突未标明操作：op={exc.op!r}")
        text = str(exc)
        if "未执行" not in text:
            _fail("⑤ 冲突消息未说明「本次写入未执行」（用户会以为写成功了）")
    else:
        _fail("⑤ 陈旧写未被拒绝")


# ── ⑥ 接入在册（两个宿主写入口） ─────────────────────────────────────

def check_entrypoints_wired() -> None:
    import inspect

    from app.modules.lego.editor_module import EditorModule

    for name in ("agent_replace_timeline_clips", "_apply_action"):
        fn = getattr(EditorModule, name, None)
        if fn is None:
            _fail(f"⑥ 找不到写入口 {name}（被改名？需同步本守卫）")
            continue
        params = inspect.signature(fn).parameters
        if "base_revision" not in params:
            _fail(f"⑥ {name} 未接受 base_revision（并发保护未接入）")
        elif params["base_revision"].default is not inspect.Parameter.empty:
            # 缺省 None 是刻意的：既有 UI 调用方不传，行为须不变
            if params["base_revision"].default is not None:
                _fail(f"⑥ {name} 的 base_revision 缺省不是 None"
                      "（会让既有调用方突然开始校验）")

    src = open(os.path.join(ROOT, EDITOR_REL), "r", encoding="utf-8").read()
    start = src.find("def agent_replace_timeline_clips")
    end = src.find("def agent_apply_storyboard_durations", start)
    body = src[start:end] if end > start else ""
    # 载荷结构在 store（`conflict_payload`）：本文件受单文件规模守卫约束，
    # 宿主侧只允许一行闸门调用，故断言「调了闸」而不是「在这里拼了 dict」。
    if "stale_or_none(base_revision)" not in body:
        _fail("⑥ agent_replace_timeline_clips 未调用并发闸 stale_or_none"
              "（并发保护未接入写入口）")
    if "return busy" not in body:
        _fail("⑥ 冲突时未把 store 的冲突载荷原样返回（上层拿不到 code=conflict）")

    # 冲突载荷的形状断言在 store 侧做
    store_src = open(os.path.join(ROOT, STORE_REL), "r", encoding="utf-8").read()
    for token in ('"code": "conflict"', "current_revision", "expected_revision"):
        if token not in store_src:
            _fail(f"⑥ store.conflict_payload 缺字段 `{token}`"
                  "（上层无法区分冲突与一般失败，Agent 也无法重读重试）")

    # CAS 必须在 clear() 之前，且全函数**只有一次** clear() 调用。
    # 判据演进（两次踩坑记录）：
    #   * 首版用 `find(check) < find(clear)` —— 注入「clear 后再校验」时
    #     `find(check)` 仍命中前面原本那处，漏过；
    #   * 二版加「clear 出现次数 == 1」—— 注入点没加第二个 clear，仍漏过；
    #   * 现在用**区间扫描**：clear() 之后到函数末尾之间的文本里，
    #     不允许再出现任何 revision 读取/校验。这才是「校验早于写入」的等价判据。
    idx_clear = body.find("self._timeline_store.clear()")
    clear_count = body.count("self._timeline_store.clear()")
    if "stale_or_none" not in body:
        _fail("⑥ 找不到并发闸调用（并发保护未落地）")
    elif idx_clear < 0:
        _fail("⑥ 找不到 clear()（写入口被改名？需同步本守卫）")
    else:
        tail = body[idx_clear:]
        for token in ("stale_or_none(", "conflict_payload(", "RevisionConflict",
                      "check_revision(", ".revision()"):
            if token in tail:
                _fail(f"⑥ clear() 之后仍出现 `{token}`"
                      "（校验必须早于写入——先清空再校验等于时间线已被破坏才报错）")
                break
    if clear_count > 1:
        _fail(f"⑥ agent_replace_timeline_clips 内出现 {clear_count} 次 clear()"
              "（校验与写入必须同一个原子段，多次清空会破坏撤销栈）")


# ── ⑦ 同一性不变量 ───────────────────────────────────────────────────

def check_identity_preserved() -> None:
    from app.core.timeline_store import TimelineStore

    st = TimelineStore([])
    live = st.rows()
    st.add(_clip("a"))
    st.replace_all([_clip("b")])
    st.clear()
    if st.rows() is not live:
        _fail("⑦ revision 改造换掉了 live list 对象（数百读点会失联）")


# ── ⑧ 单一计数器 ─────────────────────────────────────────────────────

def check_single_counter() -> None:
    with open(os.path.join(ROOT, STORE_REL), "r", encoding="utf-8") as f:
        store_src = f.read()
    if "self._revision = 0" not in store_src:
        _fail("⑧ store 内找不到 revision 初始化（分母被改名？需同步本守卫）")
    # 其它模块自建 revision 计数器即视为第二套真相源
    offenders = []
    for dirpath, dirnames, filenames in os.walk(os.path.join(ROOT, "app")):
        dirnames[:] = [d for d in dirnames
                       if d not in ("__pycache__", "temp", "node_modules", ".venv312")]
        for name in filenames:
            if not name.endswith(".py"):
                continue
            full = os.path.join(dirpath, name)
            rel = os.path.relpath(full, ROOT).replace("\\", "/")
            if rel == STORE_REL or rel.startswith("app/tests/"):
                continue
            try:
                with open(full, "r", encoding="utf-8", errors="ignore") as f:
                    text = f.read()
            except OSError:
                continue
            if "self._revision = 0" in text or "def revision(self)" in text:
                offenders.append(rel)
    if offenders:
        _fail(f"⑧ 出现第二套 revision 计数器（单一真相源被破坏）：{offenders}")


def main() -> int:
    check_version_semantics()
    check_cas_rejects_without_writing()
    check_backward_compat()
    check_conflict_diagnostics()
    check_entrypoints_wired()
    check_identity_preserved()
    check_single_counter()
    if problems:
        for p in problems:
            print(f"FAIL  {p}")
        return 1
    print("PASS  时间线乐观并发：版本语义/不空转/CAS拒绝且不写/None兼容+非法TypeError/"
          "冲突可诊断/两入口接线/同一性保持/单一计数器")
    return 0


if __name__ == "__main__":
    sys.exit(main())
