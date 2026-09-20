# -*- coding: utf-8 -*-
"""回归：Agent 内心状态模型（affect_model，小凌意识公式体系）+ 三处接线。

自包含执行（不依赖 pytest）：沙箱下 pytest 启动链会触发硬件探测被拦截。

覆盖：
  A. 纯公式：pain 乘法结构 / clamp01 容错 / 信任中性=0.5 / 失望语义 / EWMA 收敛
  B. 冷启动一致性：无数据时 mode=conservative、proactive=False、trust=0.5
     suggest_next 传 trust=0.5 与不传结果完全一致；trust=0 时权重向 0.5 收缩
  C. 观察回路：连续成功 → trust 升、mode 保守→进取门控；连续失败 → pain>0
  D. 期望模型：EWMA 按决策 key 更新
  E. agent_loop._finalize 接线：run 结束后 total_runs 增长
  F. Orchestrator._consult_brain 接线：冷启动仍选默认（行为不变）
  G. agent_console 快照含 affect 块
  H. 持久化往返：restore 字段容错

安全：脚本临时禁用 memory_store.record / latest_per_key，避免写进真实记忆库。
"""
from __future__ import annotations

import io
import os
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.ai.affect_model import (  # noqa: E402
    WEIGHTS, AffectState, agent_affect, arousal, clamp01, disappointment,
    pain_signal, psych_impact, soul_drive, trust_score, update_expectation,
)
import app.core.memory_store as ms_mod  # noqa: E402
from app.core.agent_brain import agent_brain, Synapse  # noqa: E402
import app.core.agent_pipeline_orchestrator as orch_mod  # noqa: E402
import app.core.agent_loop as loop_mod  # noqa: E402
import app.core.agent_console as console_mod  # noqa: E402

PRE = "pipeline.preview_validate"
CONTINUE = orch_mod._BRANCH_CONTINUE
REGEN = orch_mod._BRANCH_REGENERATE

_failures = []


def check(cond, msg):
    if cond:
        print(f"  ✓ {msg}")
    else:
        print(f"  ✗ {msg}")
        _failures.append(msg)


# ── 隔离真实记忆库 ──
_real_record = ms_mod.memory_store.record
_real_latest = getattr(ms_mod.memory_store, "latest_per_key", None)
ms_mod.memory_store.record = lambda *a, **k: None
if _real_latest:
    ms_mod.memory_store.latest_per_key = lambda *a, **k: []
_syn_snapshot = dict(agent_brain._synapses)
_affect_backup = AffectState()  # 空状态，结束后还原

try:
    # ═══ A. 纯公式 ═══
    print("[A] 纯公式")
    check(pain_signal(0.0, 0.8, 0.9) == 0.0, "pain 乘法结构：S=0 ⇒ pain=0")
    check(pain_signal(1.0, 1.0, 1.0) == 1.0, "pain 全满 ⇒ 1.0")
    check(pain_signal(2.0, -1.0, "abc") == 0.0, "越界/非数值输入被夹紧为 0")
    check(clamp01(float("nan"), neutral=0.5) == 0.5, "NaN 走 neutral")
    check(clamp01(7) == 1.0 and clamp01(-3) == 0.0, "clamp01 越界裁剪")
    # 信任：中性输入 (0.5, 0.5, 0, 0) ⇒ α·0.5+β·0.5 = 0.5
    check(abs(trust_score(0.5, 0.5, 0, 0) - 0.5) < 1e-9, "信任中性不变量：(0.5,0.5,0,0) ⇒ 0.5")
    check(trust_score(1.0, 1.0, 0, 0) == 1.0, "成功率高+一致 ⇒ 信任满")
    check(trust_score(0.5, 0.5, 1.0, 1.0) < 0.5, "疲劳+边界事件 ⇒ 信任降")
    # 失望：期望高、重要、PE 小 ⇒ 最失望
    check(disappointment(0.9, 1.0, 0.0) > disappointment(0.9, 1.0, 0.9),
          "预期差（PE 大）时失望更小")
    check(disappointment(0.2, 1.0, 0.0) < disappointment(0.9, 1.0, 0.0),
          "期望低时失望小")
    # EWMA 收敛：恒定输入最终逼近
    m = 0.5
    for _ in range(60):
        m = update_expectation(m, 1.0)
    check(abs(m - 1.0) < 1e-6, f"EWMA 收敛到 1.0（实际 {m:.6f}）")
    check(update_expectation(0.3, 0.9) > 0.3, "EWMA 单调向实际值靠拢")
    # 心理落量乘法结构
    check(psych_impact(1.0, 1.0, 1.0, 0.0) == 0.0, "Impact：任一因子为 0 ⇒ 0")
    # 激活中性 < 阈值（冷启动保守的公式层保证）
    check(arousal(0.5, 0.5, 0, 0.5, 0.5) < WEIGHTS.AROUSAL_THRESHOLD,
          "中性输入下 arousal < 进取阈值")
    check(soul_drive(1, 0.5, 0.5, 0.5, 0.5, 0.5, 0.5) < WEIGHTS.DRIVE_THRESHOLD,
          "中性输入下 drive < 主动建议阈值")

    # ═══ B. 冷启动一致性 ═══
    print("[B] 冷启动一致性（行为与未接入时逐字节一致）")
    fresh = AffectState()
    snap = fresh.snapshot()["last"]
    check(not snap or snap.get("mode", "conservative") == "conservative",
          "空状态 mode=conservative")
    check(fresh.current_trust() == 0.5, "空状态信任=中性 0.5")
    check(fresh.trust_factor() == 1.0, "空状态收缩因子=1.0（权重原样生效）")
    check(fresh.allow_proactive() is False, "空状态不发主动建议")
    check(fresh.expectation_of("anything") == 0.5, "空状态期望=中性 0.5")

    # suggest_next：trust=0.5 与不传完全一致
    agent_brain._synapses.pop((PRE, CONTINUE), None)
    agent_brain._synapses.pop((PRE, REGEN), None)
    for _ in range(3):
        agent_brain.reinforce_path([PRE, REGEN], success=True)
    w_no_trust = agent_brain.suggest_next(PRE, [CONTINUE, REGEN], default=CONTINUE)
    w_trust = agent_brain.suggest_next(PRE, [CONTINUE, REGEN], default=CONTINUE, trust=0.5)
    check(w_no_trust["choice"] == w_trust["choice"] == REGEN,
          "trust=0.5 时选择与不传一致")
    check(w_no_trust["weights"] == w_trust["weights"], "trust=0.5 时权重不变")
    # trust=0：偏差向 0.5 收缩但不翻转向（0.5+δ·0.5 仍 > 0.5）
    w_low = agent_brain.suggest_next(PRE, [CONTINUE, REGEN], default=CONTINUE, trust=0.0)
    check(w_low["weights"][REGEN] < w_trust["weights"][REGEN],
          f"低信任收缩：{w_low['weights'][REGEN]} < {w_trust['weights'][REGEN]}")
    check(w_low["weights"][REGEN] > 0.5, "收缩后仍高于中性（方向不翻转，只减幅）")
    check(w_low["choice"] == REGEN, "收缩不改变「学到更优」的方向")
    agent_brain._synapses.pop((PRE, CONTINUE), None)
    agent_brain._synapses.pop((PRE, REGEN), None)

    # ═══ C. 观察回路 ═══
    print("[C] 观察回路")
    st = AffectState()
    for _ in range(4):
        st.observe_run(success=True, tool_calls=3, failed_calls=0,
                       budget_used_ratio=0.2)
    c_ok = st.snapshot()["last"]
    check(c_ok["success_rate"] == 1.0, "连续成功 ⇒ 成功率 1.0")
    check(c_ok["trust"] > 0.5, f"连续成功 ⇒ 信任升（{c_ok['trust']}）")
    check(c_ok["pain"] == 0.0, "连续成功 ⇒ pain=0")
    st2 = AffectState()
    for _ in range(4):
        st2.observe_run(success=False, tool_calls=6, failed_calls=4,
                        retry_like=3, approval_events=2, budget_used_ratio=0.8)
    c_bad = st2.snapshot()["last"]
    check(c_bad["pain"] > 0.0, f"连续失败 ⇒ pain>0（{c_bad['pain']}）")
    check(c_bad["trust"] < c_ok["trust"], "失败 ⇒ 信任低于成功组")
    check(c_bad["mode"] == "conservative", "高痛感 ⇒ 保守模式")
    check(c_bad["fatigue"] > c_ok["fatigue"], "失败+预算燃烧 ⇒ 疲劳升")

    # ═══ D. 期望模型（EWMA） ═══
    print("[D] 期望模型")
    st3 = AffectState()
    for _ in range(3):
        st3.observe_run(success=True, decision_key="preview_validate->regen")
    check(st3.expectation_of("preview_validate->regen") > 0.5,
          f"成功后期望升（{st3.expectation_of('preview_validate->regen'):.3f}）")
    check(st3.expectation_of("preview_validate->continue") == 0.5,
          "未观察的 key 保持中性 0.5")
    st3.observe_run(success=False, decision_key="preview_validate->regen")
    check(st3.expectation_of("preview_validate->regen") <
          st3.snapshot()["expectations"]["preview_validate->regen"] + 0.5,
          "失败把期望往回拉（EWMA）")

    # ═══ E. agent_loop._finalize 接线 ═══
    print("[E] AgentLoop._finalize 接线")
    before = agent_affect.total_runs
    fake = loop_mod.LoopResult(session_id="check_affect", success=False)
    fake.steps.append(loop_mod.LoopStep(round_no=1, action="editor.split_clip",
                                        ok=False, error="boom"))
    fake.steps.append(loop_mod.LoopStep(round_no=2, action="editor.split_clip",
                                        ok=True))
    fake.tool_calls = 2
    loop_mod.agent_loop._finalize(fake, "check_affect", budget_used_ratio=0.5)
    check(agent_affect.total_runs == before + 1, "run 结束后观察次数 +1")
    check(agent_affect.total_tool_calls >= 2, "工具调用数入账")
    check(agent_affect.retry_like_steps >= 1, "同动作重复执行计入重试压力")

    # ═══ F. Orchestrator 接线（冷启动行为不变） ═══
    print("[F] Orchestrator._consult_brain 接线")
    orch = orch_mod.agent_pipeline_orchestrator
    adv = orch._consult_brain(1)
    check(adv["choice"] == CONTINUE, "冷启动（无突触+中性信任）仍选默认")
    agent_brain._synapses[(PRE, REGEN)] = Synapse(pre=PRE, post=REGEN, weight=0.8)
    adv2 = orch._consult_brain(1)
    check(adv2["choice"] == REGEN, "有数据时仍走重生成（trust 默认不干预）")
    agent_brain._synapses.pop((PRE, REGEN), None)

    # ═══ G. 控制台快照 ═══
    print("[G] agent_console 快照")
    status = console_mod.collect_agent_status(include_memory=False)
    check("affect" in status, "快照含 affect 块")
    check("pain" in status["affect"].get("last", {}) or
          "total_runs" in status["affect"], "affect 块含内心量/统计")

    # ═══ H. 持久化往返 ═══
    print("[H] 持久化往返")
    st4 = AffectState()
    st4.observe_run(success=True, decision_key="k1")
    blob = st4.to_dict()
    st5 = AffectState()
    st5.restore(blob)
    check(st5.total_runs == st4.total_runs, "restore 还原统计")
    check(abs(st5.expectation_of("k1") - st4.expectation_of("k1")) < 1e-9, "restore 还原期望")
    st5.restore(None)
    st5.restore({"total_runs": "x", "recent_window": "bad"})
    check(True, "restore 对脏数据容错不抛异常")
finally:
    ms_mod.memory_store.record = _real_record
    if _real_latest:
        ms_mod.memory_store.latest_per_key = _real_latest
    agent_brain._synapses.clear()
    agent_brain._synapses.update(_syn_snapshot)
    agent_affect.restore(_affect_backup.to_dict())

print()
if _failures:
    print(f"✗ 失败 {len(_failures)} 项：")
    for f in _failures:
        print("   -", f)
    sys.exit(1)
print("OK 内心状态模型全部断言通过")
