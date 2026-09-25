"""L0 全局价格层 + 配额拍卖（规格书 §2/§39-41，V4.38.1 切片⑧）
====================================================================
规格书三层价格体系的 L0 全局层（L1 任务层 = budget_pacer，已在 V4.37.7 落地）：

    λ_eff(u,τ) = λ^G + λ^τ        （有效价格叠加规则，§2）

职责切分（规格表）：
    L0 全局层：保障**月度账单上限**；误差=全局实际支出 vs 全局预算曲线；
               **积分主导、慢而稳**（T=60s）；**变化率限制 |Δλ^G| ≤ 0.1/周期**；
               支持全局一键降级。
    L1 任务层：比例主导、快而轻（budget_pacer，T=30s）。
    → 分层频域解耦（§41 共振抑制第二件套：慢积分 + 快比例）。

§41 共振抑制三件套落地：
    1. 全局公共误差因子剥离——L0 误差只算全局账单，不看单任务；
    2. L0 积分稳 / L1 比例快（增益配置即频域解耦）；
    3. 全局 λ 最大单步限幅 0.1。

§39 配额拍卖（多任务核心不变量）：
    - 高压力任务优先拿余量（按压力占比分配）；
    - 超支任务自动扣款（下期配额先抵扣欠账）；
    - 关键任务配额下界保护（key 任务保底 key_floor 比例）；
    - **永久不变量：Σ 分配 ≤ 全局剩余预算**（断言守护）。

§35 观测门控：断网/暂停时冻结 λ 更新（两层共用语义）；恢复后首个周期
只建基线不动作（指数回退精神：杜绝阶跃抖动）。

§33 灵敏度归一化：无量纲 κ 三档 {0.5, 1.0, 2.0} 整体缩放增益——
不同任务敏感度差异不再导致参数爆炸。

设计纪律：纯模块、不 import app 包、RLock、JSON 原子写、异常不抛。
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
import threading
import time
from typing import Any, Dict, Optional

logger = logging.getLogger("AI短剧编辑器.core.ai.global_price")

# ── L0 参数（积分主导、慢而稳；§36-37 预留 2 倍工程余量）──
_DEFAULT_MONTHLY_BUDGET = 500.0   # 月度账单上限（元）
_LG_INIT = 0.0                    # λ^G 初始（全局层从 0 起步：无压力不加价）
_LG_MIN = 0.0
_LG_MAX = 0.5                     # λ^G 上界（全局加价幅度天花板）
_KP_G = 0.1                       # 比例增益（小——积分主导）
_KI_G = 0.3                       # 积分增益（主导项）
_UPDATE_INTERVAL_G = 60.0         # T_g = 60s（周期锁死）
_RATE_LIMIT_G = 0.1               # |Δλ^G| ≤ 0.1/周期（§2/§41 第三件套）
_ROLLOVER_RELAX = 0.5             # 跨月 λ^G 指数回退
_KAPPA_GEARS = (0.5, 1.0, 2.0)    # §33 灵敏度三档

_DEFAULT_STORE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__))))),
    "data", "global_price.json")


def _month() -> str:
    return time.strftime("%Y-%m", time.localtime())


def _month_progress() -> float:
    """本月已过去的时间比例 [0,1)。"""
    lt = time.localtime()
    if lt.tm_mon == 12:
        nxt = (lt.tm_year + 1, 1, 1, 0, 0, 0, 0, 1, -1)
    else:
        nxt = (lt.tm_year, lt.tm_mon + 1, 1, 0, 0, 0, 0, 1, -1)
    start = time.mktime((lt.tm_year, lt.tm_mon, 1, 0, 0, 0, 0, 1, -1))
    end = time.mktime(nxt)
    return min(0.999, max(0.0, (time.time() - start) / max(1.0, end - start)))


class GlobalPriceController:
    """L0 全局影子价格 + 多任务配额拍卖（线程安全，RLock）。"""

    def __init__(self, monthly_budget: float = _DEFAULT_MONTHLY_BUDGET,
                 store_path: str = "",
                 kappa: float = 1.0,
                 update_interval: float = _UPDATE_INTERVAL_G):
        self._budget = max(1.0, float(monthly_budget))
        self._kappa = min(_KAPPA_GEARS, key=lambda k: abs(k - float(kappa)))
        self._interval = max(1.0, float(update_interval))
        self._path = store_path or _DEFAULT_STORE
        self._lock = threading.RLock()
        self._loaded = False
        # 持久化状态
        self._month = _month()
        self._spent = 0.0
        self._lam = _LG_INIT
        self._i_term = 0.0          # 积分项显式持有（积分主导 + 撞界冻结）
        self._e_prev = 0.0
        self._last_update = 0.0
        self._pi_ready = False
        self._obs_valid = True      # §35 观测门控
        # 配额拍卖状态（内存态即可：任务是会话级的）
        self._debts: Dict[str, float] = {}   # 任务欠账（超支扣款）

    # ────────────── 持久化 ──────────────

    def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        with self._lock:
            if self._loaded:
                return
            try:
                if os.path.exists(self._path):
                    with open(self._path, "r", encoding="utf-8") as f:
                        d = json.load(f)
                    if isinstance(d, dict):
                        self._month = str(d.get("month") or _month())
                        self._spent = float(d.get("spent") or 0.0)
                        self._lam = float(d.get("lambda") or _LG_INIT)
                        self._i_term = float(d.get("i_term") or 0.0)
                        self._e_prev = float(d.get("e_prev") or 0.0)
                        self._pi_ready = True
            except Exception:
                logger.debug("[global_price] 加载失败，按初始状态启动", exc_info=True)
            self._rollover_locked()
            self._loaded = True

    def _save_locked(self) -> None:
        try:
            d = os.path.dirname(self._path)
            os.makedirs(d, exist_ok=True)
            fd, tmp = tempfile.mkstemp(prefix="gp_", suffix=".tmp", dir=d)
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    json.dump({
                        "month": self._month,
                        "budget": self._budget,
                        "spent": round(self._spent, 4),
                        "lambda": round(self._lam, 6),
                        "i_term": round(self._i_term, 6),
                        "e_prev": round(self._e_prev, 6),
                    }, f, ensure_ascii=False, indent=1)
                os.replace(tmp, self._path)
            finally:
                if os.path.exists(tmp):
                    try:
                        os.remove(tmp)
                    except OSError:
                        logger.debug("忽略异常（原为 pass）: global_price.py", exc_info=True)
        except Exception:
            logger.debug("[global_price] 持久化失败（不阻断）", exc_info=True)

    def _rollover_locked(self) -> None:
        """跨月结转：账单重置、λ^G 指数回退（不清零，§35）。"""
        m = _month()
        if self._month != m:
            logger.info("[global_price] 跨月结转：%s → %s（λ^G %.3f 回退）",
                        self._month, m, self._lam)
            self._month = m
            self._spent = 0.0
            self._lam = _LG_INIT + (self._lam - _LG_INIT) * _ROLLOVER_RELAX
            self._i_term = 0.0
            self._e_prev = 0.0

    # ────────────── 记账 ──────────────

    def record_spend(self, amount: float) -> None:
        """记录一笔全局账单花费（与 L1 同步记账，各算各的误差）。"""
        try:
            amt = max(0.0, float(amount))
        except (TypeError, ValueError):
            return
        if amt <= 0.0:
            return
        with self._lock:
            self._ensure_loaded()
            self._rollover_locked()
            self._spent += amt
            self._save_locked()

    # ────────────── 观测门控（§35） ──────────────

    def set_observation(self, valid: bool, reason: str = "") -> None:
        """断网/暂停 → 冻结 λ 更新；恢复后首个周期只建基线（防阶跃）。

        恢复时把 _pi_ready 置 False：下一次迭代只重采 e_prev、不动作——
        与「指数回退而非清零」同精神（冻结期间的误差跳变不进控制器）。
        """
        with self._lock:
            was = self._obs_valid
            self._obs_valid = bool(valid)
            if was and not valid:
                logger.info("[global_price] 观测无效（%s）→ λ^G 冻结", reason)
            elif valid and not was:
                self._pi_ready = False  # 恢复首拍只建基线
                logger.info("[global_price] 观测恢复 → 首拍建基线（防阶跃）")

    # ────────────── PI（积分主导） ──────────────

    def _error_locked(self) -> float:
        """全局剩余法误差：剩余预算比 − 剩余时间比（e<0 = 账单超支趋势）。"""
        left = max(0.0, (self._budget - self._spent) / self._budget)
        return left - max(0.02, 1.0 - _month_progress())

    def _update_locked(self) -> None:
        now = time.time()
        if (now - self._last_update) < self._interval:
            return
        self._last_update = now
        if not self._obs_valid:          # §35 门控：冻结但不推进状态
            return
        e = self._error_locked()
        if not self._pi_ready:
            self._e_prev = e
            self._pi_ready = True
            return
        k = self._kappa                   # §33 灵敏度归一化
        # 比例（小）+ 积分（主导），均作用于 −e（e<0 超支 → λ^G 升）
        p_term = _KP_G * k * (self._e_prev - e)
        i_new = self._i_term + _KI_G * k * (-e)
        raw = _LG_INIT + i_new + p_term
        # 变化率限制（§2/§41 第三件套）：单步 |Δλ^G| ≤ 0.1
        step = raw - self._lam
        if abs(step) > _RATE_LIMIT_G:
            step = _RATE_LIMIT_G if step > 0 else -_RATE_LIMIT_G
        new_lam = self._lam + step
        clamped = min(_LG_MAX, max(_LG_MIN, new_lam))
        # 抗卷绕（§34）：λ 停在界上**且原始目标越界** → 冻结积分
        # （不采纳本次积分增量，阻断积压后反向爆冲）
        at_bound = clamped >= _LG_MAX - 1e-12 or clamped <= _LG_MIN + 1e-12
        raw_beyond = raw > _LG_MAX or raw < _LG_MIN
        if at_bound and raw_beyond:
            logger.debug("[global_price] λ^G 撞界（raw=%.3f 越界），积分冻结", raw)
        else:
            self._i_term = i_new
            self._e_prev = e
        if abs(clamped - self._lam) > 1e-6:
            logger.info("[global_price] λ^G %.3f → %.3f（e=%.3f, 月支出 %.2f/%.0f）",
                        self._lam, clamped, e, self._spent, self._budget)
        self._lam = clamped
        self._save_locked()

    # ────────────── 公共接口 ──────────────

    def get_lambda(self) -> float:
        """λ^G（全局加价）；与 L1 的 λ^τ 叠加进收益函数（§2 有效价格规则）。"""
        try:
            with self._lock:
                self._ensure_loaded()
                self._rollover_locked()
                self._update_locked()
                return self._lam
        except Exception:
            logger.debug("[global_price] get_lambda 异常，返回初始值", exc_info=True)
            return _LG_INIT

    def status(self) -> Dict[str, Any]:
        try:
            with self._lock:
                self._ensure_loaded()
                self._rollover_locked()
                e = self._error_locked()
                return {
                    "month": self._month,
                    "budget": self._budget,
                    "spent": round(self._spent, 4),
                    "remaining": round(max(0.0, self._budget - self._spent), 4),
                    "month_progress": round(_month_progress(), 4),
                    "error": round(e, 4),
                    "over_pacing": e < 0,
                    "lambda_g": round(self._lam, 4),
                    "lambda_g_bounds": [_LG_MIN, _LG_MAX],
                    "rate_limit": _RATE_LIMIT_G,
                    "kappa": self._kappa,
                    "observation_valid": self._obs_valid,
                }
        except Exception:
            logger.debug("[global_price] status 异常", exc_info=True)
            return {"lambda_g": _LG_INIT, "note": "控制器异常，静态兜底"}

    # ────────────── 配额拍卖（§39） ──────────────

    def auction(self, pressures: Dict[str, float],
                key_tasks: Optional[Dict[str, float]] = None
                ) -> Dict[str, Any]:
        """多任务配额拍卖：把全局剩余预算按压力分给各任务。

        参数：
            pressures: {task_id: 压力} —— 压力 = 任务紧迫度（越大越优先）；
            key_tasks: {task_id: 保底比例} —— 关键任务配额下界（0~1，相对
                       全局剩余预算）。

        规则（§39）：
          1. 关键任务先扣保底（下界保护）；
          2. 欠账任务自动扣款（配额先抵 debt）；
          3. 余量按压力占比分配（高压优先）；
          4. **永久不变量：Σ 分配 ≤ 剩余预算**（违反即断言）。

        Returns:: {"quotas": {task: 配额}, "remaining": 全局剩余,
                   "invariant_ok": bool, "debts": {task: 欠账}}
        """
        with self._lock:
            self._ensure_loaded()
            self._rollover_locked()
            remaining = max(0.0, self._budget - self._spent)
            quotas = {t: 0.0 for t in (pressures or {})}
            keys = dict(key_tasks) if isinstance(key_tasks, dict) else {}
            pool = remaining
            # 1. 关键任务保底
            for t, floor_ratio in keys.items():
                if t not in quotas:
                    quotas[t] = 0.0
                floor = min(pool, remaining * min(1.0, max(0.0, floor_ratio)))
                quotas[t] += floor
                pool -= floor
            # 2. 欠账扣款（从上期超支里扣）
            for t in list(quotas):
                debt = self._debts.get(t, 0.0)
                if debt > 0 and quotas[t] > 0:
                    pay = min(debt, quotas[t])
                    quotas[t] -= pay
                    self._debts[t] = debt - pay
            # 3. 余量按压力占比
            total_p = sum(max(0.0, float(p)) for p in (pressures or {}).values())
            if total_p > 0 and pool > 0:
                for t, p in (pressures or {}).items():
                    share = pool * max(0.0, float(p)) / total_p
                    quotas[t] = quotas.get(t, 0.0) + share
                    # 压力分配部分也先抵欠账
                    debt = self._debts.get(t, 0.0)
                    if debt > 0 and share > 0:
                        pay = min(debt, share)
                        quotas[t] -= pay
                        self._debts[t] = debt - pay
            # 4. 不变量
            total_alloc = sum(quotas.values())
            invariant_ok = total_alloc <= remaining + 1e-9
            assert invariant_ok, f"配额拍卖不变量破坏：Σ={total_alloc} > {remaining}"
            return {"quotas": quotas, "remaining": round(remaining, 4),
                    "invariant_ok": invariant_ok,
                    "debts": dict(self._debts)}

    def report_task_spend(self, task_id: str, amount: float,
                          quota: float) -> None:
        """任务回报实际花费：超配额部分记欠账（下期自动扣款，§39）。"""
        over = max(0.0, float(amount) - max(0.0, float(quota)))
        if over <= 0:
            return
        with self._lock:
            self._debts[task_id] = self._debts.get(task_id, 0.0) + over


# ═══════════════════════════════════════════════════════════
# 单例
# ═══════════════════════════════════════════════════════════

_GLOBAL: Optional[GlobalPriceController] = None
_GLOBAL_LOCK = threading.Lock()


def get_global_price() -> GlobalPriceController:
    """进程级单例（data/global_price.json，月预算 ¥500）。"""
    global _GLOBAL
    if _GLOBAL is None:
        with _GLOBAL_LOCK:
            if _GLOBAL is None:
                _GLOBAL = GlobalPriceController()
    return _GLOBAL
