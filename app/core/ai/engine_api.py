"""异构协作引擎对外接口规范（规格书第十篇，V4.38.5 切片⑫）
====================================================================
规格书第十篇：标准化**任务创建、单元提交、路由回调、资源上报** +
**完整错误码体系**，适配内外系统对接。

本模块是引擎九大部件之上的**统一门面**：

    create_task()      任务创建（模块调度器 DAG 提交）
    submit_unit()      单元提交（模型调度：选路→执行→归因）
    route_callback()   路由回调（计划 vs 实际全归因）
    resource_report()  资源上报（预算/账单/调度/抽检四视图）

统一响应信封::

    {"ok": bool, "code": "err_xxx", "message": 人话, "data": {...}}

错误码单一来源 = 本文件 ERR_* 常量（与项目 agent_constants 同款纪律，
禁裸字符串）。纯模块、不 import app 包（执行层经惰性导入接线）、
异常不抛——门面层把一切异常翻译成错误码。
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger("AI短剧编辑器.core.ai.engine_api")

# ═══════════════════════════════════════════════════════════
# 错误码体系（单一来源；新增错误在这里加常量）
# ═══════════════════════════════════════════════════════════

ERR_OK = "ok"
ERR_INVALID_PARAM = "err_invalid_param"           # 参数非法/缺失
ERR_CAPABILITY_UNSUPPORTED = "err_capability_unsupported"  # 能力不满足（声明表筛除）
ERR_MODULE_UNHEALTHY = "err_module_unhealthy"     # 模块暂停/不健康
ERR_DEPENDENCY_CYCLE = "err_dependency_cycle"     # 依赖成环
ERR_DUPLICATE_TASK = "err_duplicate_task"         # 幂等命中重复提交
ERR_BUDGET_EXHAUSTED = "err_budget_exhausted"     # 月度账单耗尽（L0 硬拒）
ERR_LOOP_FROZEN = "err_loop_frozen"               # 闭环冻结中（抽检漂移超标）
ERR_PROVIDER_UNAVAILABLE = "err_provider_unavailable"  # 全部渠道不可用
ERR_CANCELLED = "err_cancelled"                   # 任务被取消
ERR_INTERNAL = "err_internal"                     # 未分类内部错误（兜底）

_ERR_LABELS = {
    ERR_OK: "成功",
    ERR_INVALID_PARAM: "参数非法或缺失",
    ERR_CAPABILITY_UNSUPPORTED: "能力不满足本次请求",
    ERR_MODULE_UNHEALTHY: "模块暂停或不健康",
    ERR_DEPENDENCY_CYCLE: "任务依赖成环",
    ERR_DUPLICATE_TASK: "重复任务（幂等命中）",
    ERR_BUDGET_EXHAUSTED: "月度账单耗尽",
    ERR_LOOP_FROZEN: "质量闭环冻结中（残差漂移超标，待人工解冻）",
    ERR_PROVIDER_UNAVAILABLE: "全部生成渠道不可用",
    ERR_CANCELLED: "任务已取消",
    ERR_INTERNAL: "内部错误",
}


def err_label(code: str) -> str:
    return _ERR_LABELS.get(code, code)


def _resp(ok: bool, code: str, message: str = "",
          data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """统一响应信封（第十篇标准化 payload）。"""
    return {"ok": bool(ok), "code": code,
            "message": message or err_label(code),
            "data": data or {}}


# ═══════════════════════════════════════════════════════════
# 引擎门面
# ═══════════════════════════════════════════════════════════

class EngineAPI:
    """异构协作引擎统一门面（RLock；路由回调记录内存留存最近 200 条）。"""

    def __init__(self):
        self._lock = threading.RLock()
        self._callbacks: Dict[str, Dict[str, Any]] = {}  # unit_id → 路由归因

    # ────────────── ① 任务创建（模块调度器） ──────────────

    def create_task(self, module_id: str, task_id: str,
                    payload: Optional[Dict[str, Any]] = None,
                    priority: int = 3,
                    depends_on: Optional[List[str]] = None,
                    idem_key: str = "") -> Dict[str, Any]:
        """标准化任务创建：模块校验 → DAG 提交 → 信封返回。"""
        try:
            from .module_scheduler import get_scheduler
        except Exception:
            return _resp(False, ERR_INTERNAL, "模块调度器不可用")
        if not module_id or not task_id:
            return _resp(False, ERR_INVALID_PARAM, "module_id/task_id 不能为空")
        sched = get_scheduler()
        mods = sched.status()["modules"]
        m = mods.get(module_id)
        if m is None:
            return _resp(False, ERR_INVALID_PARAM,
                         f"未注册模块 {module_id}（已注册：{sorted(mods)}）")
        if m["paused"] or not m["healthy"]:
            return _resp(False, ERR_MODULE_UNHEALTHY,
                         f"模块 {module_id} {'已暂停' if m['paused'] else '不健康'}")
        try:
            task = sched.submit(module_id, task_id, payload=payload,
                                priority=priority, depends_on=depends_on,
                                idem_key=idem_key)
        except ValueError as e:
            return _resp(False, ERR_DEPENDENCY_CYCLE, str(e))
        if task is None:
            return _resp(False, ERR_DUPLICATE_TASK,
                         f"幂等命中：{idem_key or task_id} 已提交过")
        return _resp(True, ERR_OK, data={"task": task})

    # ────────────── ② 单元提交（模型调度） ──────────────

    def submit_unit(self, prompt: str, duration: float = 3.0,
                    count: int = 1, provider: str = "auto",
                    spec: Optional[Dict[str, Any]] = None,
                    mode: Optional[str] = None,
                    allow_dual: bool = False,
                    unit_id: str = "") -> Dict[str, Any]:
        """标准化单元提交：预算硬闸 → 生成 → 全归因入库 → 信封返回。

        归因 data 含：实际渠道 / 执行模式 / 降级终态 / 模式计划 /
        融合溯源（D 模式）——路由回调（③）凭 unit_id 取同一份。
        """
        if not prompt or not str(prompt).strip():
            return _resp(False, ERR_INVALID_PARAM, "prompt 不能为空")
        uid = unit_id or f"unit_{int(time.time() * 1000)}"
        # 预算硬闸（L0 月度账单耗尽 → 硬拒；日预算软性，由 λ 调节不硬拦）
        try:
            from .global_price import get_global_price

            g = get_global_price().status()
            if g.get("remaining", 1.0) <= 0:
                return _resp(False, ERR_BUDGET_EXHAUSTED,
                             f"月度账单耗尽（{g.get('spent')}/{g.get('budget')} 元）")
        except Exception:
            logger.debug("[engine_api] 预算闸查询失败（放行，软约束兜底）",
                         exc_info=True)
        # 闭环冻结提示（不硬拒：生成是业务主链路，冻结只停先验回写）
        frozen_note = ""
        try:
            from .sampling_review import get_review

            if get_review().is_frozen():
                frozen_note = err_label(ERR_LOOP_FROZEN)
        except Exception:
            pass
        try:
            from .video_generation_client import VideoGenerationClient

            client = VideoGenerationClient.get_instance()
            paths = client.generate(
                prompt=prompt, duration=duration, count=count,
                provider=provider, spec=spec, mode=mode,
                allow_dual=allow_dual)
        except Exception as e:
            logger.warning("[engine_api] 单元执行异常: %s", e)
            return _resp(False, ERR_INTERNAL, f"执行异常：{e}")
        attribution = {
            "unit_id": uid,
            "provider": client.last_used_provider(),
            "mode_executed": client.last_execution_mode(),
            "mode_plan": client.last_mode_plan(),
            "degradation": client.last_degradation(),
            "fusion": client.last_fusion(),
        }
        with self._lock:
            self._callbacks[uid] = attribution
            if len(self._callbacks) > 200:  # LRU 截断
                for k in list(self._callbacks)[:50]:
                    del self._callbacks[k]
        if not paths:
            return _resp(False, ERR_PROVIDER_UNAVAILABLE,
                         "全部渠道失败（含本地兜底）",
                         data=attribution)
        data = dict(attribution)
        data["paths"] = paths
        if frozen_note:
            data["frozen_note"] = frozen_note
        return _resp(True, ERR_OK, data=data)

    # ────────────── ③ 路由回调 ──────────────

    def route_callback(self, unit_id: str) -> Dict[str, Any]:
        """按 unit_id 取路由全归因（计划 vs 实际 vs 降级 vs 溯源）。"""
        if not unit_id:
            return _resp(False, ERR_INVALID_PARAM, "unit_id 不能为空")
        with self._lock:
            att = self._callbacks.get(unit_id)
        if att is None:
            return _resp(False, ERR_INVALID_PARAM,
                         f"无此单元的路由记录（{unit_id}）")
        return _resp(True, ERR_OK, data=dict(att))

    # ────────────── ④ 资源上报 ──────────────

    def resource_report(self) -> Dict[str, Any]:
        """四视图资源上报：日预算（L1）/ 月账单（L0）/ 模块调度 / 抽检漂移。"""
        data: Dict[str, Any] = {}
        try:
            from .budget_pacer import get_pacer

            data["budget_l1"] = get_pacer().status()
        except Exception:
            data["budget_l1"] = {"error": "不可用"}
        try:
            from .global_price import get_global_price

            data["bill_l0"] = get_global_price().status()
        except Exception:
            data["bill_l0"] = {"error": "不可用"}
        try:
            from .module_scheduler import get_scheduler

            data["scheduler"] = get_scheduler().status()
        except Exception:
            data["scheduler"] = {"error": "不可用"}
        try:
            from .sampling_review import get_review

            data["review"] = get_review().drift_status()
            data["review_metrics"] = get_review().metrics()
        except Exception:
            data["review"] = {"error": "不可用"}
        return _resp(True, ERR_OK, data=data)


# ═══════════════════════════════════════════════════════════
# 单例
# ═══════════════════════════════════════════════════════════

_API: Optional[EngineAPI] = None
_API_LOCK = threading.Lock()


def get_engine_api() -> EngineAPI:
    global _API
    if _API is None:
        with _API_LOCK:
            if _API is None:
                _API = EngineAPI()
    return _API
