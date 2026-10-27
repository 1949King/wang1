# -*- coding: utf-8 -*-
"""资源仲裁真机验收：`python scripts/verify_broker.py`（P1 · 2026-10-28）。

## 这个脚本回答什么问题

P1 的门槛是「**真实 Ollama 场景下，LLM 卸载 → 可用显存上升**实测成立」。
单测只能证明代码逻辑（用假来源），证明不了"这台机器上真的能腾出显存"。
两者都需要：单测锁行为，本脚本锁事实。

## 它验证的四件事

1. **两个读数确实不一致**：torch `mem_get_info()` 与 nvidia-smi 差多少
   （实测：空载差 ~0.55GB；LLM 加载后差 ~4.2GB，因为 torch 对别的进程占显存基本无感）。
2. **LLM 加载后可用显存真的下降**（不是"Ollama 说它占了"）。
3. **`ensure_capacity()` 真的会触发卸载，且卸载后可用显存回升**。
4. **自报 vs 实测的偏差**：Ollama `size_vram` 比实占小多少（实测 ~0.70GB）。

## 安全

- 只读 + 一次卸载 + 结束时再卸载一次（不留下"为测试而常驻"的模型）。
- 显式打印每一步的原始读数，**结论可被读者自行复核**，不需要相信脚本的判断。
- 任何一步失败都不算"通过"：本脚本宁可报失败，也不把"跑不动"当"已验证"。
"""
from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.neural import resource_broker as RB
from app.modules.lego.ollama_client import OllamaClient

_PROBE = "检测机"    # 只用于打印，无逻辑意义


def _row(label, **kw):
    parts = ["%-26s" % label]
    for k, v in kw.items():
        parts.append("%s=%s" % (k, "?" if v is None else v))
    print("  " + "  ".join(parts))


def _readings():
    vram, detail = RB.read_pool(RB.POOL_VRAM)
    return vram, detail


def _load_llm(model: str, keep_alive: str = "5m") -> bool:
    """让 Ollama 真的把模型加载进显存。用 /api/generate 发一个最小请求。"""
    try:
        import requests

        s = requests.Session()
        s.trust_env = False
        r = s.post("http://127.0.0.1:11434/api/generate", json={
            "model": model, "prompt": "ok", "stream": False,
            "keep_alive": keep_alive, "options": {"num_predict": 4},
        }, timeout=180)
        s.close()
        return r.status_code == 200
    except Exception as e:  # stability-gate: allow-swallow（验收脚本：失败即报红，不静默继续）
        print("  ! 加载 LLM 失败：%s" % e)
        return False


def main() -> int:
    ap = argparse.ArgumentParser(description="资源仲裁真机验收")
    ap.add_argument("--model", default="qwen3.5:4b", help="用于占显存的 LLM")
    ap.add_argument("--need", type=float, default=5.0,
                    help="模拟要申请的显存（GB），应大于 LLM 加载后的可用量")
    args = ap.parse_args()

    fails = []
    print("=" * 62)
    print("资源仲裁真机验收（%s）" % _PROBE)
    print("=" * 62)

    client = OllamaClient()
    if not client.is_available(force_check=True):
        print("✗ Ollama 不可用 —— 本验收无法进行（这不是通过，是未验证）")
        return 2

    models = [m.name for m in client.list_models(force_refresh=True)]
    print("已安装模型：%s" % (models or "（无）"))
    if args.model not in models and not any(args.model in m for m in models):
        print("✗ 本机没有 %s，请先用 --model 指定一个已安装模型" % args.model)
        return 2

    # 干净起点：先全部卸载
    client.unload()

    # ── 步骤 1：空载基线 ─────────────────────────────────────────
    print("\n[1] 空载基线")
    free0, d0 = _readings()
    _row("read_pool", 决策值=free0, torch=d0.get("torch"), smi=d0.get("smi"))
    if d0.get("torch") is not None and d0.get("smi") is not None:
        gap = round(float(d0["torch"]) - float(d0["smi"]), 2)
        _row("两读数差", torch_减_smi="%+.2fGB" % gap)
        print("    → torch 偏乐观时，只信它就会「以为够」（方向危险）")

    # ── 步骤 2：加载 LLM ─────────────────────────────────────────
    print("\n[2] 加载 LLM 占显存：%s" % args.model)
    if not _load_llm(args.model):
        fails.append("LLM 加载失败")
        free1, d1 = _readings()
    else:
        free1, d1 = _readings()
        loaded = client.ps()
        _row("read_pool", 决策值=free1, torch=d1.get("torch"), smi=d1.get("smi"))
        for m in loaded:
            _row("ps: %s" % m.name,
                 自报vram="%.2fGB" % m.size_vram_gb,
                 估算占用="%.2fGB" % (m.size_vram_gb + RB.CUDA_CTX_OVERHEAD_GB))
        if free0 is not None and free1 is not None:
            drop = round(float(free0) - float(free1), 2)
            _row("可用显存下降", 值="%.2fGB" % drop)
            if drop <= 0:
                fails.append("LLM 加载后可用显存没有下降（%.2fGB）" % drop)
            else:
                print("    → LLM 确实占住了 %.2fGB，关卡成立" % drop)

    # ── 步骤 3：申请显存，触发让位 ───────────────────────────────
    print("\n[3] ensure_capacity(%.2fGB) —— 应触发卸载" % args.need)
    dec = RB.ensure_capacity(args.need, reason="验收：模拟加载大模型")
    print("  %s" % dec.describe())
    for r in dec.reclaimed:
        _row("reclaimed: %s" % r.name,
             est=("?" if r.estimated_gb is None else "%.2f" % r.estimated_gb),
             actual=("?" if r.actual_gb is None else "%.2f" % r.actual_gb),
             bias=("?" if r.bias_gb is None else "%+.2f" % r.bias_gb),
             ok=r.ok)
        print("      note: %s" % (r.note or "-"))

    if dec.action != "released":
        fails.append("未进入 released（实际 %s）" % dec.action)
    if dec.freed_gb <= 0:
        fails.append("实测腾出量不是正数（%.2fGB）" % dec.freed_gb)

    # ── 步骤 4：复核 LLM 真的走了 ───────────────────────────────
    print("\n[4] 复核")
    still = [m.name for m in client.ps()]
    _row("ps() 仍有", 值=str(still or "（空）"))
    if still:
        fails.append("让位后 LLM 仍加载中：%s" % still)

    free2, d2 = _readings()
    _row("read_pool（让位后）", 决策值=free2, torch=d2.get("torch"), smi=d2.get("smi"))
    if free0 is not None and free2 is not None:
        back = round(float(free2) - float(free0), 2)
        _row("相对空载基线", 差="%+.2fGB" % back)
        if back < -0.3:
            fails.append("让位后仍比空载基线少 %.2fGB（未真正回到基线）" % (-back))

    # 收尾：不留常驻
    client.unload()

    print("\n" + "=" * 62)
    if fails:
        print("✗ 验收未通过（%d 条）：" % len(fails))
        for f in fails:
            print("   - %s" % f)
        return 1
    print("✓ 验收通过：LLM 让位后可用显存回升，实测口径成立")
    print(json.dumps({"freed_gb": dec.freed_gb, "action": dec.action},
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
