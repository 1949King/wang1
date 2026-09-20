# -*- coding: utf-8 -*-
"""记忆强度机制验证（memory_store 升级 · 2026-09-13）。

覆盖：
  1. 兼容性：旧 JSONL 行缺 recall_count / last_recalled 时由默认值补齐
  2. strength_at：召回越多衰减越慢；搁置越久强度越低；score=0 直接 0；与公式吻合
  3. reinforce：+1 并刷新 last_recalled；新版落盘（后行覆盖前行的恢复语义）
  4. query 排序开关：默认 = 旧行为不变；开启后按强度排序
  5. _compress：带 error 的 trace / brain_synapse / 核心类别保留，普通 trace 清除
  6. latest_per_key：同一逻辑键取 timestamp 最新（load_synapses 的修复基础）
  7. get_agent_context：被注入的条目获得 reinforce（命中≠注入，query 不强化）
  8. 真实数据对照（只读）：开启强度排序前后，注入候选的差异

用法（项目根执行）：
    .venv312\\Scripts\\python.exe _verify/check_memory_strength.py
"""

from __future__ import annotations

import importlib.util
import json
import math
import os
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "app", "core", "memory_store.py")
REAL_DATA = os.path.join(ROOT, "data", "agent_memory.jsonl")

failures: list[str] = []


def check(condition: bool, message: str) -> None:
    if not condition:
        failures.append(message)


def load_module():
    spec = importlib.util.spec_from_file_location("memory_store_under_test", SRC)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["memory_store_under_test"] = mod
    spec.loader.exec_module(mod)
    return mod


def fresh_store(ms):
    """绕过单例 + 指向临时文件，得到完全隔离的存储实例。"""
    ms.MemoryStore._instance = None
    ms._STORAGE_PATH = os.path.join(
        tempfile.mkdtemp(prefix="sg_mem_test_"), "test_memory.jsonl"
    )
    return ms.MemoryStore()


def main() -> int:
    ms = load_module()
    MemoryEntry = ms.MemoryEntry
    now = time.time()

    # ---- 1. 旧 JSONL 行兼容 ----
    legacy = {
        "entry_id": "old1", "category": "feedback",
        "content": {"platform": "douyin"}, "timestamp": now - 100,
        "tags": ["x"], "score": 0.7,
    }
    entry = MemoryEntry(**legacy)
    check(entry.recall_count == 0 and entry.last_recalled == 0.0,
          "旧 JSONL 行未获默认值补齐（向后兼容被破坏）")

    # ---- 2. strength_at ----
    old_unused = MemoryEntry(score=0.8, timestamp=now - 720 * 3600)
    old_used = MemoryEntry(score=0.8, timestamp=now - 720 * 3600,
                           recall_count=10, last_recalled=now - 24 * 3600)
    fresh_low = MemoryEntry(score=0.6, timestamp=now)
    s_unused = ms.MemoryStore.strength_at(old_unused, now=now)
    s_used = ms.MemoryStore.strength_at(old_used, now=now)
    s_fresh = ms.MemoryStore.strength_at(fresh_low, now=now)
    check(s_used > s_unused, "同 score 同搁置时长，被召回过的应更耐忘")
    check(s_fresh > s_unused, "新写入的低分应胜过搁置 30 天的高分（强度排序的意义）")
    check(ms.MemoryStore.strength_at(MemoryEntry(score=0.0), now=now) == 0.0,
          "score=0 应直接为 0")
    expected = 0.8 * math.exp(-0.001 * (1.0 - 0.6 * 1.0) * 24.0)
    check(abs(s_used - expected) < 1e-9,
          f"strength_at 与公式不符: {s_used} vs {expected}")

    # ---- 3/4/6：隔离实例上的行为 ----
    store = fresh_store(ms)
    eid = store.record(category="feedback", content={"platform": "douyin"}, score=0.7)
    rows = store.query(category="feedback")
    check(len(rows) == 1, "query 基本过滤失效")
    check(rows[0].recall_count == 0, "被 query 扫到不应强化（命中不等于注入）")

    # 默认排序 = 旧行为（静态 score 优先）
    store.record(category="feedback", content={"platform": "bili"}, score=0.95)
    default_rows = store.query(category="feedback")
    check(default_rows[0].score == 0.95, "默认排序应保持静态 score 优先（行为未变）")

    # 开启强度排序：搁置 30 天的 0.95 应让位给刚写入的 0.7
    store._entries[default_rows[0].entry_id].timestamp = now - 720 * 3600
    ms.set_strength_ranking(True)
    try:
        strength_rows = store.query(category="feedback")
    finally:
        ms.set_strength_ranking(False)
    check(strength_rows[0].entry_id == eid,
          "强度排序应让新低分胜过搁置的高分")

    # reinforce：存在性过滤 + 落盘新版
    touched = store.reinforce([eid, "nonexistent"])
    check(touched == 1, "reinforce 应只对存在的条目生效")
    entry_after = store._entries[eid]
    check(entry_after.recall_count == 1 and entry_after.last_recalled > 0,
          "reinforce 未累加 recall_count / 刷新 last_recalled")
    with open(ms._STORAGE_PATH, encoding="utf-8") as f:
        disk_rows = [json.loads(x) for x in f if x.strip()]
    same_id = [d for d in disk_rows if d["entry_id"] == eid]
    check(len(same_id) == 2 and same_id[-1]["recall_count"] == 1,
          "reinforce 应追加带巩固状态的新版（后行覆盖前行的恢复语义）")

    # latest_per_key：取最新版本而非最低分旧版
    store.record(category="brain_synapse",
                 content={"pre": "a", "post": "b", "weight": 0.2}, score=0.2)
    time.sleep(0.01)
    store.record(category="brain_synapse",
                 content={"pre": "a", "post": "b", "weight": 0.9}, score=0.9)
    latest = store.latest_per_key(category="brain_synapse")
    check(len(latest) == 1 and latest[0].content.get("weight") == 0.9,
          "latest_per_key 应取最新版本（load_synapses 修复的基础）")

    # ---- 5. _compress 保留策略 ----
    store.record(category="execution_trace", content={"error": "boom"}, score=0.4)
    store.record(category="execution_trace", content={"stage": "ok"}, score=0.4)
    store.record(category="brain_synapse",
                 content={"pre": "x", "post": "y", "weight": 0.05}, score=0.05)
    store._compress()
    remaining = list(store._entries.values())
    traces = [e for e in remaining if e.category == "execution_trace"]
    check(len(traces) == 1 and (traces[0].content or {}).get("error") == "boom",
          "压缩后应只保留带 error 的 trace（消费层依赖项）")
    syns = [e for e in remaining if e.category == "brain_synapse"]
    # 压缩前共 3 条：a→b 的两个历史版本 + x→y。_compress 不做逻辑键去重
    # （去重是 latest_per_key 的职责），因此全部保留 = 3。
    check(len(syns) == 3, "brain_synapse 应全部保留（学习状态），实际剩 %d" % len(syns))

    # ---- 7. get_agent_context：注入即强化 ----
    store2 = fresh_store(ms)
    fb = store2.record(category="feedback",
                       content={"platform": "douyin", "views": 15000}, score=0.6)
    ctx = store2.get_agent_context(top_k=5)
    check("douyin" in ctx and ctx.strip() != "", "get_agent_context 未产出内容")
    check(store2._entries[fb].recall_count >= 1, "被注入的 feedback 未获得强化")

    if failures:
        print("FAIL 记忆强度机制 %d 项不符预期：" % len(failures))
        for item in failures:
            print("  -", item)
        return 1

    print("OK 记忆强度机制全部断言通过")
    print("  strength_at: 搁置30天 unused=%.3f used=%.3f 新写入0.6=%.3f"
          % (s_unused, s_used, s_fresh))

    # ---- 8. 真实数据对照（只读，不动运行时） ----
    if os.path.exists(REAL_DATA):
        latest_by_id: dict = {}
        with open(REAL_DATA, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    d = json.loads(line)
                except Exception:
                    continue
                latest_by_id[d.get("entry_id")] = d
        entries = []
        for d in latest_by_id.values():
            try:
                entries.append(MemoryEntry(**d))
            except Exception:
                continue
        print("\n[真实数据对照] 共 %d 条（同 id 取最新）" % len(entries))
        for cat in ("feedback", "learned_rule"):
            pool = [e for e in entries if e.category == cat]
            if not pool:
                continue
            by_score = sorted(pool, key=lambda e: (e.score, e.timestamp),
                              reverse=True)[:5]
            by_strength = sorted(pool, key=lambda e: ms.MemoryStore.strength_at(e),
                                  reverse=True)[:5]
            print("  %s（%d 条）静态排序前5: %s" % (
                cat, len(pool),
                ", ".join(e.entry_id for e in by_score)))
            print("  %s（%d 条）强度排序前5: %s" % (
                cat, len(pool),
                ", ".join(e.entry_id for e in by_strength)))
    else:
        print("\n[真实数据对照] 未找到 data/agent_memory.jsonl，跳过")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
