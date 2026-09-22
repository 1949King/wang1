"""PI 预算影子价格控制器（Budget Pacer）
==========================================
来源：《异构动态协作引擎规格书》v4.3 第六篇 C 模块的最小落地（切片④）。

规格书的核心论断：**静态 λ 是 v4.0 的缺陷**（长期饱和 → 要么永远选最贵、
要么永远选最便宜）。本项目 V4.37.4 引入收益函数时 λ_c 写死 0.2——本模块
把它变成连续调节的影子价格：

    花得太快（预算消耗曲线跑在时间曲线前面）→ λ_c 升 → 路由偏好便宜渠道
    花得太慢（预算富余）                      → λ_c 降 → 路由偏好质量渠道

误差信号（规格 §31 剩余法，无量纲天然归一化——规格 §33 的灵敏度归一化
在单预算池场景下由比值天然成立，多池场景待后续）：

    e = 剩余预算比 − 剩余时间比 = (B_left/B) − (T_left/T)

    e < 0：预算跑得比时间快 → 超支趋势 → λ 应上调
    e > 0：预算富余 → λ 可下调

PI 迭代（规格 §32，周期锁死为惰性求值：读 λ 时距上次更新 ≥T_update 才迭代）：

    λ ← clamp(λ + Kp·(e − e_prev) + Ki·(−e)·dt_norm, λ_min, λ_max)

    注意符号：e<0 是超支 → 需要 λ 增大 → 积分项作用于 −e。

抗饱和/抗卷绕（规格 §34）：λ 撞到上下界时**冻结积分累积**（条件积分），
防止积压后反向爆冲。

观测门控（规格 §35）：无新花费事件且距上次更新不足 T_update → 不迭代，
直接返回当前 λ（读操作零副作用窗口期）。

窗口：按自然日滚动（与额度池 daily_quota 的 used_date 同语义）；
跨日自动结转——预算重置、λ 指数回退向初始值靠拢（规格 §35 恢复用
指数回退而非清零，杜绝阶跃抖动）。

持久化：JSON + 原子写（data/budget_pacer.json）；一切异常绝不抛出——
控制器是优化项，挂了用静态 λ 兜底，绝不能拖垮生成主链路。

设计纪律：纯模块（不 import app 包），可独立加载/单测。
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
import threading
import time
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger(__name__)

# ── 默认参数（可用构造参数覆盖；整定原则见规格 §36-37：Ki 预留 2 倍工程余量）──
_DEFAULT_BUDGET = 50.0        # 日预算（元）
_LAMBDA_INIT = 0.2            # 初始 λ（= provider_caps 原静态值，无缝接管）
_LAMBDA_MIN = 0.05            # λ 下界（预算再富余也给成本留基本权重）
_LAMBDA_MAX = 1.0             # λ 上界（抗饱和；超过后成本项压死一切非免费渠道）
_KP = 0.5                     # 比例增益
_KI = 0.1                     # 积分增益（预留 2 倍稳定余量）
_UPDATE_INTERVAL = 30.0       # 最小更新周期（秒，规格「周期锁死」）
_ROLLOVER_RELAX = 0.5         # 跨日 λ 回退系数：λ ← init + (λ−init)×0.5（指数回退）

_DEFAULT_STORE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__))))),
    "data", "budget_pacer.json")


def _today() -> str:
    return time.strftime("%Y-%m-%d", time.localtime())


def _day_progress() -> float:
    """今日已过去的时间比例 [0,1)。"""
    lt = time.localtime()
    return (lt.tm_hour * 3600 + lt.tm_min * 60 + lt.tm_sec) / 86400.0


class BudgetPacer:
    """日预算 PI 影子价格控制器（线程安全，RLock——公开方法嵌套持锁）。"""

    def __init__(self, budget: float = _DEFAULT_BUDGET,
                 store_path: str = "",
                 kp: float = _KP, ki: float = _KI,
                 update_interval: float = _UPDATE_INTERVAL):
        self._budget = max(1.0, float(budget))
        self._kp = float(kp)
        self._ki = float(ki)
        self._interval = max(1.0, float(update_interval))
        self._path = store_path or _DEFAULT_STORE
        self._lock = threading.RLock()
        self._loaded = False
        # 持久化状态
        self._date = _today()
        self._spent = 0.0
        self._lam = _LAMBDA_INIT
        self._e_prev = 0.0
        self._last_update = 0.0
        self._pi_ready = False  # 首次迭代只建误差基线不动作（防启动比例踢，规格 §35）

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
                        self._date = str(d.get("date") or _today())
                        self._spent = float(d.get("spent") or 0.0)
                        self._lam = float(d.get("lambda") or _LAMBDA_INIT)
                        self._e_prev = float(d.get("e_prev") or 0.0)
                        self._pi_ready = True  # 有持久化状态 = 控制器已在跑，无需再建基线
            except Exception:
                logger.debug("[budget_pacer] 加载失败，按初始状态启动", exc_info=True)
            self._rollover_locked()
            self._loaded = True

    def _save_locked(self) -> None:
        try:
            d = os.path.dirname(self._path)
            os.makedirs(d, exist_ok=True)
            fd, tmp = tempfile.mkstemp(prefix="bp_", suffix=".tmp", dir=d)
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    json.dump({
                        "date": self._date,
                        "budget": self._budget,
                        "spent": round(self._spent, 4),
                        "lambda": round(self._lam, 6),
                        "e_prev": round(self._e_prev, 6),
                    }, f, ensure_ascii=False, indent=1)
                os.replace(tmp, self._path)
            finally:
                if os.path.exists(tmp):
                    try:
                        os.remove(tmp)
                    except OSError:
                        pass
        except Exception:
            logger.debug("[budget_pacer] 持久化失败（不阻断主链路）", exc_info=True)

    def _rollover_locked(self) -> None:
        """跨日结转：预算重置、λ 指数回退（不清零，杜绝阶跃抖动，规格 §35）。"""
        today = _today()
        if self._date != today:
            logger.info("[budget_pacer] 跨日结转：%s → %s（花费 %.2f 归档，λ %.3f 回退）",
                        self._date, today, self._spent, self._lam)
            self._date = today
            self._spent = 0.0
            self._lam = _LAMBDA_INIT + (self._lam - _LAMBDA_INIT) * _ROLLOVER_RELAX
            self._e_prev = 0.0

    # ────────────── 记账 ──────────────

    def record_spend(self, amount: float) -> None:
        """记录一笔实际花费（元）。异常绝不抛出。"""
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

    # ────────────── 误差与 PI ──────────────

    def _error_locked(self) -> float:
        """剩余法误差 e = 剩余预算比 − 剩余时间比（e<0 = 超支趋势）。"""
        budget_left_ratio = max(0.0, (self._budget - self._spent) / self._budget)
        time_left_ratio = max(0.02, 1.0 - _day_progress())  # 防日末除零失真
        return budget_left_ratio - time_left_ratio

    def _update_locked(self, force: bool = False) -> None:
        """PI 迭代（观测门控：间隔不足且无新花费则不迭代）。"""
        now = time.time()
        if not force and (now - self._last_update) < self._interval:
            return
        self._last_update = now
        e = self._error_locked()
        if not self._pi_ready:
            # 首次迭代：只建立误差基线，不动作——杜绝启动时 e_prev=0 造成的
            # 比例踢（λ 阶跃抖动，规格 §35「恢复用回退而非阶跃」同精神）
            self._e_prev = e
            self._pi_ready = True
            return
        # 符号约定：e<0 = 超支趋势 → λ 需上调 ⇒ 比例与积分都作用于 −e
        delta = self._kp * (self._e_prev - e) + self._ki * (-e)
        new_lam = self._lam + delta
        clamped = min(_LAMBDA_MAX, max(_LAMBDA_MIN, new_lam))
        # 抗卷绕（规格 §34）：撞界时冻结积分——e_prev 不更新，阻断积分继续累积
        if abs(clamped - new_lam) < 1e-12:
            self._e_prev = e
        else:
            logger.debug("[budget_pacer] λ 撞界 %.3f→clamped，积分冻结", new_lam)
        if abs(clamped - self._lam) > 1e-6:
            logger.info("[budget_pacer] λ %.3f → %.3f（e=%.3f, spent=%.2f/%.0f）",
                        self._lam, clamped, e, self._spent, self._budget)
        self._lam = clamped
        self._save_locked()

    # ────────────── 公共接口 ──────────────

    def get_lambda(self) -> float:
        """当前影子价格 λ_c（供收益函数 V = q̂ − λ_c·price 使用）。"""
        try:
            with self._lock:
                self._ensure_loaded()
                self._rollover_locked()
                self._update_locked()
                return self._lam
        except Exception:
            logger.debug("[budget_pacer] get_lambda 异常，返回初始值", exc_info=True)
            return _LAMBDA_INIT

    def status(self) -> Dict[str, Any]:
        """控制器状态快照（诊断/UI/Agent 查询用）。"""
        try:
            with self._lock:
                self._ensure_loaded()
                self._rollover_locked()
                e = self._error_locked()
                return {
                    "date": self._date,
                    "budget": self._budget,
                    "spent": round(self._spent, 4),
                    "remaining": round(max(0.0, self._budget - self._spent), 4),
                    "spend_ratio": round(self._spent / self._budget, 4),
                    "time_ratio": round(_day_progress(), 4),
                    "error": round(e, 4),
                    "over_pacing": e < 0,
                    "lambda": round(self._lam, 4),
                    "lambda_bounds": [_LAMBDA_MIN, _LAMBDA_MAX],
                    "note": "λ 升=预算紧张偏便宜渠道；λ 降=预算富余偏质量渠道",
                }
        except Exception:
            logger.debug("[budget_pacer] status 异常", exc_info=True)
            return {"lambda": _LAMBDA_INIT, "note": "控制器异常，静态 λ 兜底"}

    def set_budget(self, budget: float) -> None:
        """调整日预算（即时生效，不动已花费与 λ）。"""
        try:
            with self._lock:
                self._ensure_loaded()
                self._budget = max(1.0, float(budget))
                self._save_locked()
        except Exception:
            logger.debug("[budget_pacer] set_budget 失败", exc_info=True)

    def _reset_for_tests(self) -> None:
        with self._lock:
            self._date = _today()
            self._spent = 0.0
            self._lam = _LAMBDA_INIT
            self._e_prev = 0.0
            self._last_update = 0.0
            self._loaded = True


_PACER: Optional[BudgetPacer] = None
_PACER_LOCK = threading.Lock()


def get_pacer() -> BudgetPacer:
    """进程级单例（默认 data/budget_pacer.json，日预算 ¥50）。"""
    global _PACER
    if _PACER is None:
        with _PACER_LOCK:
            if _PACER is None:
                _PACER = BudgetPacer()
    return _PACER
