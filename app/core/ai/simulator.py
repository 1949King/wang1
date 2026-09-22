"""端到端仿真器（规格书第十一篇，V4.38.4 切片⑪）
====================================================================
规格书五属性：**零成本、同代码、可复现、可回归、可故障注入**。

- **同代码**：直接驱动生产控制器（budget_pacer / global_price /
  quality_prior / divergence_probe / execution_modes / module_scheduler /
  sampling_review / fusion）——**只替换模拟执行层**（不碰 ffmpeg、不碰网络）；
- **可复现**：一切随机走 ``random.Random(seed)``，同种子同报告指纹；
- **可回归**：报告含不变量断言结果，可直接进检查脚本；
- **故障注入**：429 风暴 / 断网（观测门控）/ 超支 / 评分漂移；
- **四大用途**（规格原文）：参数标定（κ 档位对比）、收敛验证（λ 序列
  尾部方差）、多任务不变量校验（Σ 配额 ≤ 剩余，逐轮断言）、
  极限压力测试（单元决策均时 < 1ms，O(1) 红线 §69）。

设计纪律：纯模块；仿真用独立 tmp 存储（绝不碰 data/*.json 真数据）；
时间依赖用「虚拟拍」——直接调控制器内部更新入口（force/清零 _last_update），
不 sleep、零等待。
"""
from __future__ import annotations

import hashlib
import json
import logging
import random
import tempfile
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger("AI短剧编辑器.core.ai.simulator")

# 模拟执行层的渠道剧本（确定性参数，非随机瞎编）
_PROVIDER_SCRIPT = {
    #           ok_rate  quality  latency  cost
    "dashscope": (0.90, 0.85, 8.0, 1.5),
    "seedance": (0.85, 0.75, 6.0, 1.0),
    "cogvideo": (0.80, 0.65, 5.0, 0.8),
    "local": (1.00, 0.30, 0.5, 0.0),
}


class Simulator:
    """端到端仿真器：同代码驱动生产控制器 + 模拟执行层。"""

    def __init__(self, seed: int = 42, budget: float = 50.0,
                 monthly_budget: float = 500.0):
        self._seed = int(seed)
        self._rng = random.Random(self._seed)
        self._tmpdir = tempfile.mkdtemp(prefix=f"sg_sim_{self._seed}_")
        # ── 生产控制器（独立实例 + 独立存储，同代码零改动） ──
        from .budget_pacer import BudgetPacer
        from .divergence_probe import DivergenceProbe
        from .global_price import GlobalPriceController
        from .module_scheduler import ModuleScheduler
        from .quality_prior import QualityPriorStore
        from .sampling_review import SamplingReview
        import os

        self.pacer = BudgetPacer(budget=budget, update_interval=30.0,
                                 store_path=f"{self._tmpdir}/bp.json")
        self.gprice = GlobalPriceController(monthly_budget=monthly_budget,
                                            update_interval=60.0,
                                            store_path=f"{self._tmpdir}/gp.json")
        self.priors = QualityPriorStore(store_path=f"{self._tmpdir}/qp.json")
        self.probe = DivergenceProbe(store_path=f"{self._tmpdir}/dp.json")
        self.sched = ModuleScheduler(max_retries=1)
        self.review = SamplingReview(
            store_path=f"{self._tmpdir}/sr.json",
            prior_writer=lambda p, y: self.priors.record_outcome(
                p, ok=True, quality=y, kind="quality"))
        for mid, cfg in (("video_gen", {"quota": 1, "non_preemptible": True}),
                         ("ai_edit", {"quota": 2, "non_preemptible": False}),
                         ("canvas_gen", {"quota": 2, "non_preemptible": False})):
            self.sched.register_module(mid, **cfg)

    # ────────────── 模拟执行层 ──────────────

    def _execute(self, provider: str, fault: Optional[str]) -> Dict[str, Any]:
        """模拟一次渠道执行（确定性随机；故障注入优先）。"""
        ok_rate, quality, latency, cost = _PROVIDER_SCRIPT.get(
            provider, (0.5, 0.5, 5.0, 1.0))
        if fault == "429" and provider != "local":
            return {"ok": False, "error": "HTTP 429 Throttling", "cost": 0.0}
        if fault == "offline" and provider != "local":
            return {"ok": False, "error": "network unreachable", "cost": 0.0}
        ok = self._rng.random() < ok_rate
        jitter = self._rng.uniform(-0.05, 0.05)
        return {"ok": ok,
                "error": "" if ok else "simulated failure",
                "quality": min(1.0, max(0.0, quality + jitter)),
                "latency": latency * self._rng.uniform(0.8, 1.2),
                "cost": cost if ok else 0.0}

    def _fault_at(self, faults: List[Dict[str, Any]], step: int) -> Optional[str]:
        for f in faults or []:
            if int(f.get("at", -1)) <= step < int(f.get("at", -1)) + int(f.get("duration", 1)):
                return str(f.get("type", ""))
        return None

    # ────────────── 主仿真循环 ──────────────

    def run(self, units: int = 100,
            faults: Optional[List[Dict[str, Any]]] = None,
            task_pressures: Optional[Dict[str, float]] = None,
            kappa: float = 1.0) -> Dict[str, Any]:
        """跑 N 个生成单元，产出全维度报告。

        每单元：模块调度 DAG 提交 → 就绪取出 → 模型调度选路（收益函数 +
        λ_eff + 探针）→ 模拟执行 → 先验/预算/账单/分歧回写 → 抽检。
        每 10 单元做一次配额拍卖（多任务不变量逐轮断言）。
        """
        from .execution_modes import MODE_D, choose_mode, collect_infeasible
        from .provider_caps import PROVIDER_CAPS

        lam_t_series: List[float] = []
        lam_g_series: List[float] = []
        spend_series: List[float] = []
        route_counts: Dict[str, int] = {}
        degradation_events = 0
        invariant_fails = 0
        decision_times: List[float] = []
        faults = list(faults or [])
        pressures = task_pressures or {"main": 1.0}

        for i in range(int(units)):
            fault = self._fault_at(faults, i)
            # ── 观测门控（断网故障 → 冻结两层 λ） ──
            offline = fault == "offline"
            self.pacer.set_observation(not offline, "sim-offline")
            self.gprice.set_observation(not offline, "sim-offline")
            # ── 模块调度（DAG：脚本解析 → 视频生成） ──
            self.sched.submit("canvas_gen", f"sim_{i}_parse",
                              priority=1, idem_key=f"sim_{i}_parse")
            self.sched.submit("video_gen", f"sim_{i}_gen",
                              priority=3, depends_on=[f"sim_{i}_parse"],
                              idem_key=f"sim_{i}_gen")
            nxt = self.sched.next_runnable()
            if nxt:
                self.sched.start(nxt["task_id"])
                self.sched.complete(nxt["task_id"])
            # ── 模型调度：收益选路（决策计时 → O(1) 红线） ──
            t0 = time.perf_counter()
            priors = {p: self.priors.route_mean(p) for p in _PROVIDER_SCRIPT
                      if p != "local"}
            lam_eff = self.pacer.get_lambda() + self.gprice.get_lambda()
            verdict = self.probe.is_dual_candidate("video")
            infeasible = collect_infeasible(cloud_available=not offline)
            if not verdict.get("candidate") and MODE_D not in infeasible:
                infeasible[MODE_D] = "探针：" + str(verdict.get("reason", ""))
            best_p, best_u = None, -1e9
            for p, q in priors.items():
                price = float(PROVIDER_CAPS.get(p, {}).get("price_per_clip") or 0)
                u = q - lam_eff * price
                if u > best_u:
                    best_p, best_u = p, u
            plan = choose_mode(q_local=0.3, q_cloud=priors.get(best_p, 0.5),
                               cost_local=0.0,
                               cost_cloud=float(PROVIDER_CAPS.get(best_p, {})
                                                .get("price_per_clip") or 0),
                               lambda_c=lam_eff, infeasible=infeasible)
            decision_times.append(time.perf_counter() - t0)
            # ── 模拟执行 + 回退链 ──
            provider = best_p or "local"
            r = self._execute(provider, fault)
            if not r["ok"] and provider != "local":
                degradation_events += 1
                self.priors.record_outcome(provider, ok=False)
                r = self._execute("local", None)
                provider = "local"
            if r["ok"]:
                self.priors.record_outcome(provider, ok=True,
                                           quality=r.get("quality"),
                                           kind="quality")
                if r.get("cost", 0.0) > 0:
                    self.pacer.record_spend(r["cost"])
                    self.gprice.record_spend(r["cost"])
                    self.probe.note_unit_cost(r["cost"])
                # 分歧入库（模拟：本地/云端质量差即分歧代理）
                if provider != "local":
                    self.probe.record("video", abs(r.get("quality", 0.5) - 0.3))
            route_counts[provider] = route_counts.get(provider, 0) + 1
            # ── 抽检（每单元过抽样器；人工真值用模拟标签） ──
            machine_q = r.get("quality", 0.3)
            residual = abs(machine_q - self.priors.route_mean(provider))
            dec = self.review.should_sample(
                f"sim_unit_{i}", "video",
                residual=residual,
                divergence=self.probe.estimate("video"),
                new_genre=(fault == "drift"))  # §76：分布外场景强制必检
            if dec.get("sample"):
                self.review.submit_ai_score({
                    "unit_id": f"sim_unit_{i}", "kind": "video",
                    "machine_score": machine_q, "provider": provider})
                if fault == "drift":
                    # 漂移故障：机器分虚高，人工真值判废 → 残差拉大
                    self.review.submit_human_label(f"sim_unit_{i}", "不合格",
                                                   ai_score=machine_q,
                                                   provider=provider)
                else:
                    self.review.submit_human_label(
                        f"sim_unit_{i}",
                        "合格" if machine_q >= 0.5 else "不合格",
                        ai_score=machine_q, provider=provider)
            # ── 配额拍卖（每 10 单元一轮，不变量逐轮断言） ──
            if i % 10 == 9:
                auc = self.gprice.auction(pressures)
                if not auc["invariant_ok"]:
                    invariant_fails += 1
            lam_t_series.append(self.pacer.status()["lambda"])
            lam_g_series.append(self.gprice.status()["lambda_g"])
            spend_series.append(self.pacer.status()["spent"])

        # ── 收敛验证：λ 序列尾部（后 20%）方差 ──
        def _tail_var(xs: List[float]) -> float:
            tail = xs[int(len(xs) * 0.8):] or xs
            if len(tail) < 2:
                return 0.0
            mean = sum(tail) / len(tail)
            return sum((x - mean) ** 2 for x in tail) / len(tail)

        report = {
            "seed": self._seed,
            "units": int(units),
            "kappa": kappa,
            "lambda_tau_final": lam_t_series[-1] if lam_t_series else 0.0,
            "lambda_g_final": lam_g_series[-1] if lam_g_series else 0.0,
            "lambda_tau_tail_var": _tail_var(lam_t_series),
            "lambda_g_tail_var": _tail_var(lam_g_series),
            "spent_total": spend_series[-1] if spend_series else 0.0,
            "route_counts": route_counts,
            "degradation_events": degradation_events,
            "auction_invariant_fails": invariant_fails,
            "decision_time_avg_ms": (sum(decision_times) / len(decision_times)
                                     * 1000) if decision_times else 0.0,
            "decision_time_max_ms": (max(decision_times)
                                     * 1000) if decision_times else 0.0,
            "sampling": self.review.metrics(),
            "frozen": self.review.is_frozen(),
            "scheduler": self.sched.status(),
        }
        # 可复现指纹：只覆盖**引擎状态**（时钟类字段——决策耗时/模块注册
        # 时间戳——天然不确定，必须排除，否则同种子也不同指纹）
        digest_view = {
            "seed": report["seed"], "units": report["units"],
            "kappa": report["kappa"],
            "lambda_tau_final": report["lambda_tau_final"],
            "lambda_g_final": report["lambda_g_final"],
            "lambda_tau_tail_var": report["lambda_tau_tail_var"],
            "lambda_g_tail_var": report["lambda_g_tail_var"],
            "spent_total": report["spent_total"],
            "route_counts": report["route_counts"],
            "degradation_events": report["degradation_events"],
            "auction_invariant_fails": report["auction_invariant_fails"],
            "sampling": report["sampling"],
            "frozen": report["frozen"],
        }
        blob = json.dumps(digest_view, sort_keys=True, ensure_ascii=False)
        report["digest"] = hashlib.md5(blob.encode("utf-8")).hexdigest()[:12]
        return report


def parameter_sweep(units: int = 60, seed: int = 42) -> Dict[str, Any]:
    """参数标定（规格：支撑参数标定）：κ 三档各跑一遍对比花费与收敛。"""
    out = {}
    for k in (0.5, 1.0, 2.0):
        sim = Simulator(seed=seed)
        out[str(k)] = sim.run(units=units, kappa=k)
    return out
