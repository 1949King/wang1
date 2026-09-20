# -*- coding: utf-8 -*-
"""回归：AgentBrain 决策咨询 + Orchestrator 大脑路由（学习回路闭合）。

自包含执行（不依赖 pytest）：沙箱下 pytest 启动链会触发硬件探测被拦截。

覆盖：
  A. 冷启动无数据 → 恒选默认分支（行为与接入前一致）
  B. 学到「重生成更好」→ 改走重生成
  C. 学到「重生成更差」→ 回到默认
  D. 平票 → 默认项胜出（稳定，不抖动）
  E. Orchestrator._consult_brain 接线：有数据/无数据/总开关关闭
  F. PipelineSession 序列化带 brain_advice
  G. _try_regenerate_failed 无失败片段时返回 0（不产生副作用）

安全：脚本会临时禁用 memory_store.record，避免把测试用突触写进真实记忆库。
"""
from __future__ import annotations

import io
import os
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.agent_brain import agent_brain  # noqa: E402
import app.core.memory_store as ms_mod  # noqa: E402
import app.core.agent_pipeline_orchestrator as orch_mod  # noqa: E402

PRE = "pipeline.preview_validate"
CONTINUE = orch_mod._BRANCH_CONTINUE      # pipeline.score（默认 = 现状行为）
REGEN = orch_mod._BRANCH_REGENERATE       # pipeline.regenerate_clip

_failures = []


def check(cond, msg):
    if cond:
        print(f"  ✓ {msg}")
    else:
        print(f"  ✗ {msg}")
        _failures.append(msg)


# ── 隔离真实记忆库 ──
_real_record = ms_mod.memory_store.record
ms_mod.memory_store.record = lambda *a, **k: None
_syn_snapshot = dict(agent_brain._synapses)

try:
    print("[A] 冷启动：无学习数据")
    agent_brain._synapses.pop((PRE, CONTINUE), None)
    agent_brain._synapses.pop((PRE, REGEN), None)
    advice = agent_brain.suggest_next(PRE, [CONTINUE, REGEN], default=CONTINUE)
    check(advice["choice"] == CONTINUE, f"无数据时选默认（{advice['choice']}）")
    check(advice["learned"] is False, "learned=False（等于没学，行为与旧版一致）")
    check(advice["changed"] is False, "changed=False")
    check(set(advice["weights"]) == {CONTINUE, REGEN}, "两个候选都给了中性权重")

    print("[B] 学到「重生成更好」")
    for _ in range(3):
        agent_brain.reinforce_path([PRE, REGEN], success=True)
    advice = agent_brain.suggest_next(PRE, [CONTINUE, REGEN], default=CONTINUE)
    check(advice["choice"] == REGEN, f"改走重生成（{advice['choice']}）")
    check(advice["learned"] is True, "learned=True")
    check(advice["changed"] is True, "changed=True")
    check(advice["weights"][REGEN] > advice["weights"][CONTINUE],
          f"权重 {advice['weights'][REGEN]} > {advice['weights'][CONTINUE]}")

    print("[C] 学到「重生成更差」")
    for _ in range(6):
        agent_brain.reinforce_path([PRE, REGEN], success=False)
    advice = agent_brain.suggest_next(PRE, [CONTINUE, REGEN], default=CONTINUE)
    check(advice["choice"] == CONTINUE, f"负反馈后回到默认（{advice['choice']}）")
    check(advice["weights"][REGEN] < 0.5,
          f"重生成权重被压到 {advice['weights'][REGEN]} < 中性 0.5")

    print("[D] 平票：默认项必须胜出（稳定，不抖动）")
    from app.core.agent_brain import Synapse  # noqa: E402
    agent_brain._synapses[(PRE, CONTINUE)] = Synapse(pre=PRE, post=CONTINUE, weight=0.7)
    agent_brain._synapses[(PRE, REGEN)] = Synapse(pre=PRE, post=REGEN, weight=0.7)
    advice = agent_brain.suggest_next(PRE, [CONTINUE, REGEN], default=CONTINUE)
    check(advice["choice"] == CONTINUE, "同权重时选默认（传入次序中的第一项）")
    advice2 = agent_brain.suggest_next(PRE, [CONTINUE, REGEN], default=REGEN)
    check(advice2["choice"] == REGEN, "默认项改为重生成时，平票选重生成 ⇒ 完全由 default 决定")

    print("[E] Orchestrator 接线")
    orch = orch_mod.agent_pipeline_orchestrator
    agent_brain._synapses[(PRE, REGEN)] = Synapse(pre=PRE, post=REGEN, weight=0.8)  # 重生成更优
    adv = orch._consult_brain(2)
    check(adv.get("failed_count") == 2, "failed_count 透传")
    check(adv["choice"] == REGEN, f"有数据时咨询结果=重生成（{adv['choice']}）")

    agent_brain._synapses.pop((PRE, CONTINUE), None)
    agent_brain._synapses.pop((PRE, REGEN), None)
    check(orch._consult_brain(1)["choice"] == CONTINUE, "清掉数据后回到默认")

    saved = orch_mod.BRAIN_ROUTING_ENABLED
    orch_mod.BRAIN_ROUTING_ENABLED = False
    check(orch._consult_brain(1)["choice"] == CONTINUE, "SG_BRAIN_ROUTE 关闭时恒为默认")
    orch_mod.BRAIN_ROUTING_ENABLED = saved

    print("[F] 会话序列化")
    sess = orch_mod.PipelineSession(session_id="test")
    sess.brain_advice = {"choice": REGEN}
    d = sess.to_dict()
    check("brain_advice" in d, "to_dict 带 brain_advice")
    check(d["brain_advice"]["choice"] == REGEN, "brain_advice 内容正确")

    print("[G] _try_regenerate_failed 无失败片段时")
    n = orch._try_regenerate_failed([{"clip_id": "x", "path": "y"}], max_clips=3)
    check(n == 0, f"返回 0（实际 {n}），不会误触发真实重生成")
finally:
    ms_mod.memory_store.record = _real_record
    agent_brain._synapses.clear()
    agent_brain._synapses.update(_syn_snapshot)

print()
if _failures:
    print(f"✗ 失败 {len(_failures)} 项：")
    for f in _failures:
        print("   -", f)
    sys.exit(1)
print("OK 大脑路由全部断言通过")
