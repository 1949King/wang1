# -*- coding: utf-8 -*-
"""词锚定重锚 · Agent 链路端到端校验（阶段 5）。

为什么需要这个脚本
------------------
阶段 3/4 只证明了 ``plan_reanchor`` 纯函数正确、UI 能调。阶段 5 的**新增风险面**
完全不同，必须单独证明：

1. **默认必须是 dry_run** —— 漏传 dry_run 时若真改了时间线，Agent 会在用户
   没看到差异清单的情况下成批挪片段。这是本能力最危险的失效模式。
2. **落地是「一条」compound 撤销** —— 若每个片段压一条 undo，用户按一次 Ctrl+Z
   只回滚一个片，观感就是「撤销坏了」（本项目历史上真踩过这个坑）。
3. **无片段可动时绝不写撤销栈** —— 否则 Ctrl+Z 弹出一个「什么也没变」的撤销。
4. **锁纪律** —— 落地必须持 ``_clips_lock``；且必须先 ``_clips_snapshot()``
   拿稳定列表，不能把 ``self._clips`` 引用交给纯函数。
5. **spread 语义** —— 默认按新词区间改时长，且 ``out_point = in_point + duration``
   契约不被破坏。

本脚本用一个**最小 EditorModule 替身**（只实现重锚真正触碰的成员）跑这 5 条，
不拉起 Qt，故可在无 GUI 的沙箱里跑。替身刻意保留真实的锁与撤销栈结构，
使得「锁有没有取」「压了几条 undo」都是**可观测的真实行为**，而不是断言字面量。

用法：
    .venv312/Scripts/python.exe _verify/check_reanchor_capability.py
"""
from __future__ import annotations

import io
import sys
import threading
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.dialogue_anchor import fingerprint  # noqa: E402

PASS, FAIL = "✅", "❌"
_results: List[tuple] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    _results.append((name, ok, detail))
    print(f"{PASS if ok else FAIL} {name}" + (f"\n     {detail}" if detail else ""))


# ══════════════════════════════════════════════════════════════════
# 最小 EditorModule 替身 —— 只实现重锚真正触碰的成员
# ══════════════════════════════════════════════════════════════════
class FakeEditor:
    """保留真实的锁与撤销栈，使「取没取锁 / 压了几条」可被观测。"""

    def __init__(self, clips: List[Dict[str, Any]]):
        self._clips = clips
        self._clips_lock = threading.RLock()
        self._action_history: List[Dict[str, Any]] = []
        self._redo_history: List[Dict[str, Any]] = []
        self.sync_calls = 0
        # 观测：落地期间是否真的持有锁（别的线程能否抢到）
        self.lock_held_during_apply: List[bool] = []
        self.snapshot_used = False

    # ── 真实实现直接借用 EditorModule 的这两个「基础设施」方法 ──
    def _clips_snapshot(self) -> List[Dict[str, Any]]:
        self.snapshot_used = True
        with self._clips_lock:
            return list(self._clips or [])

    def _apply_clip_fields(self, clip: dict, fields: dict) -> None:
        if not clip or not fields:
            return
        for k, v in fields.items():
            clip[k] = v

    def _record_action(self, action: dict) -> None:
        self._action_history.append(action)
        self._redo_history.clear()

    def _sync_timeline_widget_state(self) -> None:
        self.sync_calls += 1

    def _sync_kernel_timeline(self) -> None:
        self.sync_calls += 1

    def _refresh_preview_with_effects(self) -> None:
        pass

    # ── 被测方法：从真实 EditorModule 上原样绑定 ──
    agent_reanchor_clips = None  # 运行时注入


def _bind_real_method(fake: FakeEditor) -> None:
    """把真实 EditorModule.agent_reanchor_clips 绑到替身上。"""
    import ast

    src_path = ROOT / "app" / "modules" / "lego" / "editor_module.py"
    src = io.open(src_path, encoding="utf-8").read()
    tree = ast.parse(src)
    target = None
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) \
                and node.name == "agent_reanchor_clips":
            target = node
            break
    assert target is not None, "editor_module.py 里找不到 agent_reanchor_clips"

    lines = src.splitlines(keepends=True)
    start = target.lineno - 1
    end = getattr(target, "end_lineno", target.lineno)
    method_src = "".join(lines[start:end])
    # 去掉一级缩进，包成模块级函数
    dedented = "\n".join(
        ln[4:] if ln.startswith("    ") else ln for ln in method_src.splitlines()
    )
    ns: Dict[str, Any] = {}
    import logging
    ns["logger"] = logging.getLogger("reanchor_test")
    ns["threading"] = threading
    ns["Optional"] = __import__("typing").Optional
    ns["List"] = __import__("typing").List
    ns["Dict"] = __import__("typing").Dict
    ns["Any"] = __import__("typing").Any
    exec(compile(dedented, "<agent_reanchor_clips>", "exec"), ns)
    fake.agent_reanchor_clips = ns["agent_reanchor_clips"].__get__(fake, FakeEditor)


# ══════════════════════════════════════════════════════════════════
# 测试数据
# ══════════════════════════════════════════════════════════════════
def make_clips() -> List[Dict[str, Any]]:
    """3 个片段：两个有锚点（可重排）、一个无锚点（空镜，必须不动）。"""
    return [
        {
            "id": "c1", "start_time": 0.0, "duration": 2.0,
            "track": 0, "in_point": 0.0, "out_point": 2.0,
            "metadata": {
                "anchor": {
                    "kind": "dialogue",
                    "dialogue_id": "d0000",
                    "from_word": 0, "to_word": 2,
                    "text_fingerprint": fingerprint("你好世界"),
                    "fallback_range": [0.0, 2.0],
                }
            },
        },
        {
            "id": "c2", "start_time": 2.0, "duration": 1.5,
            "track": 0, "in_point": 0.0, "out_point": 1.5,
            "metadata": {
                "anchor": {
                    "kind": "dialogue",
                    "dialogue_id": "d0001",
                    "from_word": 0, "to_word": 2,
                    "text_fingerprint": fingerprint("我们走吧"),
                    "fallback_range": [2.0, 3.5],
                }
            },
        },
        {   # 空镜：无锚点，绝不能被挪走
            "id": "c3", "start_time": 3.5, "duration": 1.0,
            "track": 1, "in_point": 0.0, "out_point": 1.0,
        },
    ]


def make_dialogues_shifted() -> List[Dict[str, Any]]:
    """新台词：同样两句，但整体**后移**了（模拟改文案重跑 ASR 后时间变化）。

    每句给 4 个词，锚点要 [0,2) 所以只有前两个词参与 —— 区间长度随之变化。
    """
    return [
        {
            "id": "d0000", "text": "你好世界", "start_time": 5.0, "end_time": 7.4,
            "words": [
                {"text": "你", "start": 5.0, "end": 5.4},
                {"text": "好", "start": 5.4, "end": 5.8},
                {"text": "世", "start": 5.8, "end": 6.2},
                {"text": "界", "start": 6.2, "end": 7.4},
            ],
        },
        {
            "id": "d0001", "text": "我们走吧", "start_time": 7.4, "end_time": 9.0,
            "words": [
                {"text": "我", "start": 7.4, "end": 7.8},
                {"text": "们", "start": 7.8, "end": 8.2},
                {"text": "走", "start": 8.2, "end": 8.6},
                {"text": "吧", "start": 8.6, "end": 9.0},
            ],
        },
    ]


# ══════════════════════════════════════════════════════════════════
# 主流程
# ══════════════════════════════════════════════════════════════════
def main() -> int:
    print("=" * 68)
    print("词锚定重锚 · Agent 链路端到端校验（阶段 5）")
    print("=" * 68)

    # ── 用例 1：dry_run 默认值 ──
    f1 = FakeEditor(make_clips())
    _bind_real_method(f1)
    before = [(c["id"], c["start_time"], c["duration"]) for c in f1._clips]
    r1 = f1.agent_reanchor_clips(make_dialogues_shifted())  # 刻意不传 dry_run

    after = [(c["id"], c["start_time"], c["duration"]) for c in f1._clips]
    check("1a 不传 dry_run 时 applied=False", r1.get("applied") is False,
          f"applied={r1.get('applied')!r}")
    check("1b 不传 dry_run 时时间线零改动", before == after,
          f"before==after → {before == after}")
    check("1c 不传 dry_run 时撤销栈为空", len(f1._action_history) == 0,
          f"history={len(f1._action_history)}")
    check("1d 计划里确实有可重排片段（非空转）", r1.get("matched", 0) > 0,
          f"matched={r1.get('matched')} orphaned={r1.get('orphaned')}")

    # ── 用例 2：落地 ──
    f2 = FakeEditor(make_clips())
    _bind_real_method(f2)
    r2 = f2.agent_reanchor_clips(make_dialogues_shifted(), dry_run=False)

    check("2a applied=True", r2.get("applied") is True, f"applied={r2.get('applied')!r}")
    check("2b 恰好压入 1 条撤销（compound 整包）",
          len(f2._action_history) == 1,
          f"history={len(f2._action_history)}")
    act = f2._action_history[0] if f2._action_history else {}
    check("2c 撤销类型是 compound 且带 label",
          act.get("type") == "compound" and act.get("label") == "reanchor_clips",
          f"type={act.get('type')!r} label={act.get('label')!r}")
    n_steps = len(act.get("steps") or [])
    check("2d compound 步骤数 == moved 数",
          n_steps == r2.get("moved"),
          f"steps={n_steps} moved={r2.get('moved')}")

    by_id = {c["id"]: c for c in f2._clips}
    check("2e c1 已被移到新时间（5.0）",
          abs(by_id["c1"]["start_time"] - 5.0) < 1e-6,
          f"c1.start_time={by_id['c1']['start_time']}")
    check("2f c2 已被移到新时间（7.4）",
          abs(by_id["c2"]["start_time"] - 7.4) < 1e-6,
          f"c2.start_time={by_id['c2']['start_time']}")

    # ── 用例 3：无锚点片段绝不动 ──
    check("3a 空镜 c3 时间零改动",
          abs(by_id["c3"]["start_time"] - 3.5) < 1e-6
          and abs(by_id["c3"]["duration"] - 1.0) < 1e-6,
          f"c3=({by_id['c3']['start_time']},{by_id['c3']['duration']})")

    # ── 用例 4：spread 语义 + out_point 契约 ──
    spread_dur = by_id["c1"]["duration"]
    in_p = by_id["c1"]["in_point"]
    out_p = by_id["c1"]["out_point"]
    check("4a spread=True 时按新词区间改时长（[0,2) → 5.0~5.8）",
          abs(spread_dur - 0.8) < 1e-6,
          f"duration={spread_dur}（期望 0.8）")
    check("4b out_point = in_point + duration 契约保持",
          abs(out_p - (in_p + spread_dur)) < 1e-6,
          f"out_point={out_p} in_point+dur={in_p + spread_dur}")

    # spread=False → 时长不变
    f3 = FakeEditor(make_clips())
    _bind_real_method(f3)
    r3 = f3.agent_reanchor_clips(make_dialogues_shifted(), dry_run=False, spread=False)
    c1b = {c["id"]: c for c in f3._clips}["c1"]
    check("4c spread=False 时仅平移、时长保持",
          abs(c1b["duration"] - 2.0) < 1e-6 and abs(c1b["start_time"] - 5.0) < 1e-6,
          f"c1=({c1b['start_time']},{c1b['duration']})")

    # ── 用例 5：并发观测 —— 落地期间是否持锁 ──
    # ⚠️ 必须用**另一个线程**来探锁。_clips_lock 是 RLock（可重入），
    # 同线程 acquire 永远成功，用它探测会得到假阴性 —— 这正是本用例第一版
    # 误报失败的原因。只有别的线程抢不到，才证明当前线程真的持有它。
    f4 = FakeEditor(make_clips())
    _bind_real_method(f4)
    acquired_by_other: List[bool] = []

    orig_apply = f4._apply_clip_fields

    def spy_apply(clip, fields):
        probe: List[bool] = []
        t = threading.Thread(
            target=lambda: probe.append(f4._clips_lock.acquire(blocking=False))
        )
        t.start()
        t.join()
        if probe and probe[0]:
            f4._clips_lock.release()
        acquired_by_other.extend(probe)
        return orig_apply(clip, fields)

    f4._apply_clip_fields = spy_apply
    f4.agent_reanchor_clips(make_dialogues_shifted(), dry_run=False)
    check("5a 落地写入期间持 _clips_lock（他线程抢不到）",
          bool(acquired_by_other) and not any(acquired_by_other),
          f"他线程每次能否抢到锁 = {acquired_by_other}（全 False 才是持锁）")
    check("5b 走的是 _clips_snapshot()（未直接暴露 self._clips 引用）",
          f4.snapshot_used is True, f"snapshot_used={f4.snapshot_used}")

    # ── 用例 6：无可重排 → 不写撤销栈 ──
    f5 = FakeEditor(make_clips())
    _bind_real_method(f5)
    r5 = f5.agent_reanchor_clips(
        [{"id": "d0099", "text": "完全无关的一句台词",
          "start_time": 0.0, "end_time": 1.0,
          "words": [{"text": "无", "start": 0.0, "end": 1.0}]}],
        dry_run=False,
    )
    check("6a 全部失配时 applied=False", r5.get("applied") is False,
          f"applied={r5.get('applied')!r} msg={r5.get('message','')[:60]}")
    check("6b 无改动时撤销栈为空（不留空撤销）",
          len(f5._action_history) == 0, f"history={len(f5._action_history)}")
    check("6c 全部片段保持原时间",
          all(abs(c["start_time"] - o["start_time"]) < 1e-6
              for c, o in zip(f5._clips, make_clips())),
          f"starts={[c['start_time'] for c in f5._clips]}")

    # ── 用例 7：坏锚点不炸 ──
    bad = make_clips()
    bad[0]["metadata"]["anchor"] = "这是一个被写坏的字符串锚点"
    f6 = FakeEditor(bad)
    _bind_real_method(f6)
    try:
        r6 = f6.agent_reanchor_clips(make_dialogues_shifted(), dry_run=False)
        ok6 = isinstance(r6, dict) and "success" in r6
        det6 = f"success={r6.get('success')} applied={r6.get('applied')}"
    except Exception as e:  # noqa: BLE001
        ok6 = False
        det6 = f"抛异常: {type(e).__name__}: {e}"
    check("7a 字符串坏锚点不崩溃、返回结构化结果", ok6, det6)

    # ── 用例 8：参数校验 ──
    f7 = FakeEditor(make_clips())
    _bind_real_method(f7)
    r7 = f7.agent_reanchor_clips(make_dialogues_shifted(), dry_run=False, threshold="abc")
    check("8a threshold 非数值时诚实报错",
          r7.get("success") is False and "threshold" in str(r7.get("message", "")),
          f"msg={r7.get('message')!r}")

    f8 = FakeEditor(make_clips())
    _bind_real_method(f8)
    r8 = f8.agent_reanchor_clips([])
    check("8b 空台词序列时诚实报错（不静默成功）",
          r8.get("success") is False,
          f"msg={str(r8.get('message',''))[:70]}")

    # ── 汇总 ──
    print("=" * 68)
    n_pass = sum(1 for _, ok, _ in _results if ok)
    n_all = len(_results)
    print(f"结果：{n_pass}/{n_all} 通过")
    if n_pass != n_all:
        print("失败项：")
        for name, ok, detail in _results:
            if not ok:
                print(f"  {FAIL} {name}  {detail}")
    print("=" * 68)
    return 0 if n_pass == n_all else 1


if __name__ == "__main__":
    sys.exit(main())
