"""
AI 视频生成客户端 (VideoGenerationClient)
=========================================
统一封装 AI 视频生成服务（火山 Seedance / 智谱 CogVideo / 本地占位）。

设计原则：
  - 单例，线程安全；调用方应在 worker 线程调用，本模块不阻塞 Qt 主线程。
  - 优先调用真实云端/本地生成服务；失败自动回退到本地占位生成（FFmpeg 色块）。
  - 只输出文件路径，不写 UI 逻辑；UI 由 pipeline 层通过 EventBus 驱动。
  - 失败通过 EventBus 广播 GENERATION_INSPECTION_FAILED，由 AgentFeedbackBridge 回流。

架构位置：
  AgentPipelineRouter → AIVideoGenerationPipeline → VideoGenerationClient
"""
from __future__ import annotations
import logging
import os
import shutil
import subprocess
import tempfile
import threading
import time
import uuid
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

# P1-3 取消异常：任务线程内逐段检查抛出；伪包/独立加载时无任务底座，
# 空元组 except 子句永不匹配（等价于没有这个 except），普通调用零影响。
try:
    from app.core.canvas_gen_jobs import GenCancelled as _GenCancelled
except Exception:  # noqa: BLE001 - 独立加载场景（_verify 伪包）不可能出现取消
    _GenCancelled = ()  # type: ignore[assignment]


def _raise_if_cancelled() -> None:
    """gen-jobs 任务线程内已取消 → 抛 GenCancelled；普通调用（无令牌）零影响。

    ⚠️ 调用点不要包进 catch-all try（会把取消控制流吞成普通失败）。
    """
    try:
        from .pipeline_jobs import raise_if_cancelled as _ric
    except Exception:  # noqa: BLE001 - 伪包加载：无任务底座
        return
    _ric()


# 占位片段默认参数
_DEFAULT_FPS = 30
_DEFAULT_RESOLUTION = (1280, 720)  # 720p 占位
_DEFAULT_DURATION = 5.0


class VideoGenerationClient:
    """
    AI 视频生成客户端 —— 单例

    使用方式：
        from app.core.ai.video_generation_client import video_generation_client
        paths = video_generation_client.generate(prompt="...", duration=5.0, count=3)
    """
    _instance: Optional['VideoGenerationClient'] = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        self._providers: Dict[str, Optional[Callable]] = {}  # 延迟加载缓存
        # 线程局部：记录「本线程最近一次 generate 实际用了哪个 provider」——
        # 切片② 质量真值回写的归因依据（Provenance）；多并发生成任务互不串扰
        self._tls = threading.local()
        self._output_dir = os.path.join(tempfile.gettempdir(), "shiguangyx_ai_gen")
        try:
            os.makedirs(self._output_dir, exist_ok=True)
        except Exception as e:
            logger.warning(f"[VideoGenerationClient] 创建输出目录失败: {e}")

    @classmethod
    def get_instance(cls) -> 'VideoGenerationClient':
        return cls()

    # ────────────── 公共接口 ──────────────

    def generate(self, prompt: str, duration: float = _DEFAULT_DURATION,
                 count: int = 1, provider: str = "auto",
                 width: int = _DEFAULT_RESOLUTION[0],
                 height: int = _DEFAULT_RESOLUTION[1],
                 spec: Optional[Dict[str, Any]] = None,
                 mode: Optional[str] = None,
                 allow_dual: bool = False) -> List[str]:
        """
        生成视频片段

        参数：
            prompt:    标准化提示词（中英文均可）
            duration:  单段时长（秒）
            count:     生成段数
            provider:  生成器；auto 表示按能力声明 + 优先级依次尝试
            width/height: 分辨率
            spec:      本次请求的**能力需求**（如 first_last_frame=True /
                       image_to_video=True / resolution="1080p"）；未提的字段不参与筛选
            mode:      显式执行模式（切片⑤/⑦）："D" 强制双路；None=按既有链
            allow_dual: 允许自动双路（切片⑦）——True 且模式计划选中 D 且探针
                       判候选时执行本地+云端双路融合；默认 False（双路=双倍
                       云端花费，必须显式开）

        返回：
            生成的视频文件路径列表（全部失败返回空列表）
        """
        _raise_if_cancelled()  # P1-3：入口即响应取消（排队期被取消的任务不再起跑）
        results: List[str] = []
        providers = self._resolve_provider_order(provider, spec=spec,
                                                 duration=duration,
                                                 width=width, height=height)
        # ── D 双路模式（V4.38.0 切片⑦）：显式 mode="D"，或 allow_dual 且
        # 模式计划选中 D（探针已判候选）时走双路融合通道；失败内部回退单路链。
        if mode == "D" or (allow_dual and mode is None):
            plan = getattr(self._tls, "last_mode_plan", None)
            if mode == "D" or (isinstance(plan, dict) and plan.get("mode") == "D"):
                dual = self._execute_dual(prompt=prompt, duration=duration,
                                          count=count, width=width, height=height,
                                          providers=providers)
                if dual:
                    return dual[:count]
                if mode == "D":
                    logger.warning("[VideoGenerationClient] 显式 D 双路失败，回退单路链")
        # 额度池重排（P0-1）：有健康账号的 provider 优先；无账号配置时透传
        pool = None
        try:
            from .provider_pool import get_pool

            pool = get_pool()
            providers = pool.reorder_providers(providers)
        except Exception:
            logger.debug("[VideoGenerationClient] 额度池不可用，跳过重排", exc_info=True)
        last_error = ""
        failures: List[tuple] = []  # (provider, error_class) —— L3 降质重试的判据
        session = None
        try:
            from .degradation import DegradationSession

            session = DegradationSession()
        except Exception:
            logger.debug("[VideoGenerationClient] 降级追踪不可用", exc_info=True)
        first_real_provider = ""  # 首个非 local 渠道（L3 重试目标）
        used_fallback_provider = False  # 非首选真实渠道成功 → L2
        for name in providers:
            _raise_if_cancelled()  # P1-3：provider 尝试之间响应取消
            # ── L3 质量降级（V4.37.6）：在本地兜底之前最后一搏——全部真实渠道
            # 失败、含资源类错误（超时/OOM/429——降分辨率可能救回来）、原请求
            # 高于 480p 时，用首个真实渠道 480p 重试**一次**（只试一次只降一档）。
            if name == "local" and not results and first_real_provider \
                    and min(width, height) > 480 \
                    and any(cls == "resource" for _, cls in failures):
                handler_l3 = self._get_provider(first_real_provider)
                if handler_l3 is not None:
                    try:
                        logger.info(f"[VideoGenerationClient] L3 质量降级：{first_real_provider} 480p 重试")
                        paths = handler_l3(prompt=prompt, duration=duration, count=count,
                                           width=854, height=480)
                        if paths:
                            results.extend(paths)
                            if pool is not None:
                                pool.report_success(first_real_provider, segments=len(paths))
                            self._record_prior(first_real_provider, ok=True)
                            self._record_spend(first_real_provider, len(paths))
                            self._tls.last_provider = first_real_provider
                            if session is not None:
                                session.mark(3, f"{first_real_provider} 480p 重试成功")
                            break
                    except _GenCancelled:
                        raise
                    except Exception as e:
                        logger.warning(f"[VideoGenerationClient] L3 480p 重试仍失败: {e}")
                        last_error = str(e)
                        if pool is not None:
                            pool.report_failure(first_real_provider, error=str(e))
                        self._record_prior(first_real_provider, ok=False)
            handler = self._get_provider(name)
            if handler is None:
                continue
            if name != "local":
                if not first_real_provider:
                    first_real_provider = name
                elif not results:
                    used_fallback_provider = True  # 走到非首选真实渠道 = 云端降级
            try:
                paths = handler(prompt=prompt, duration=duration, count=count,
                                width=width, height=height)
                if paths:
                    results.extend(paths)
                    if pool is not None:
                        pool.report_success(name, segments=len(paths))
                    self._record_prior(name, ok=True)
                    self._record_spend(name, len(paths))  # 切片④：实际花费记账
                    self._tls.last_provider = name  # 归因：本线程实际用了谁
                    # local 兜底在链内交付：被动降级记 L6（显式选 local 是主动选择不记）
                    if name == "local" and provider != "local" and session is not None:
                        session.mark(6, f"本地占位兜底（{last_error[:80]}）")
                    logger.info(f"[VideoGenerationClient] {name} 成功生成 {len(paths)} 段")
                    break  # 成功即停止尝试后续 provider
                if pool is not None and name != "local":
                    pool.report_failure(name, error="返回空结果")
                if name != "local":
                    failures.append((name, "unknown"))
                self._record_prior(name, ok=False)
            except _GenCancelled:
                raise  # 取消是控制流，不记 provider 失败（P1-3）
            except Exception as e:
                logger.warning(f"[VideoGenerationClient] {name} 执行失败: {e}")
                last_error = str(e)
                if name != "local":
                    try:
                        from .degradation import classify_error

                        failures.append((name, classify_error(str(e))))
                    except Exception:
                        failures.append((name, "unknown"))
                if pool is not None and name != "local":
                    pool.report_failure(name, error=str(e))
                self._record_prior(name, ok=False)

        # 所有真实 provider 失败 → 回退本地占位生成（保证业务流程可演示；
        # 注意：provider 链正常含 local，占位通常已在循环内交付，这里是
        # 「local 返回空 / 链中无 local」的安全网）
        if not results:
            _raise_if_cancelled()  # P1-3：占位生成前响应取消（不白跑 ffmpeg）
            if provider not in ("local",):
                logger.warning(f"[VideoGenerationClient] 真实 provider 全部失败，回退占位生成 ({last_error})")
            results = self._call_local_fallback(prompt=prompt, duration=duration,
                                                count=count, width=width, height=height)
            self._tls.last_provider = "local"  # 归因：兜底层也要标清来源
            # 显式 provider="local" 是用户主动选择，不算降级（规格：降级是被动行为）
            if session is not None and results and provider != "local":
                session.mark(6, f"本地占位兜底（{last_error[:80]}）")

        # ── 降级终态定级 + 统计 + 本线程可查（V4.37.6 切片③） ──
        if session is not None:
            if results:
                if len(results) < max(1, int(count)):
                    session.mark(5, f"部分交付 {len(results)}/{count} 段")
                elif used_fallback_provider and session.final_level == 0:
                    session.mark(2, "非首选渠道交付")
            try:
                from .degradation import get_stats

                get_stats().record(session.final_level)
                self._tls.last_degradation = session.summary()
            except Exception:
                logger.debug("[VideoGenerationClient] 降级统计失败（不阻断）", exc_info=True)

        # 广播生成完成（便于 pipeline 层追踪）
        self._emit_generation_done(results, prompt=prompt)

        # 切片⑤：记录**实际**执行模式（与计划对照，审计用）
        try:
            used = str(getattr(self._tls, "last_provider", "") or "")
            if used == "local" and provider == "local":
                executed = "L"
            elif used == "local":
                executed = "C→L"  # 云端失败后回退本地
            elif used:
                executed = "C"
            else:
                executed = ""
            self._tls.last_mode_executed = executed
        except Exception:
            logger.debug("忽略异常（原为 pass）: video_generation_client.py", exc_info=True)

        return results[:count] if results else []

    def last_used_provider(self) -> str:
        """本线程最近一次 generate 实际使用的 provider（切片② 归因查询）。

        调用方必须在**同一线程**的 generate 之后立刻读（生成管线正是如此）；
        未曾生成过返回空字符串。
        """
        return str(getattr(self._tls, "last_provider", "") or "")

    def last_degradation(self) -> Dict[str, Any]:
        """本线程最近一次 generate 的降级终态（切片③ 可观测性查询）。

        Returns:: {"level", "level_name", "level_label", "events"}；
        未曾生成过返回 {"level": 0, ...} 完整交付。
        """
        d = getattr(self._tls, "last_degradation", None)
        if isinstance(d, dict):
            return dict(d)
        return {"level": 0, "level_name": "full",
                "level_label": "完整交付（首选渠道按原规格出齐）", "events": []}

    def last_mode_plan(self) -> Dict[str, Any]:
        """本线程最近一次 generate 的**模式计划**（切片⑤，规格书 §10-12）。

        Returns:: {"mode", "label", "scores", "kept", "dropped", "baseline",
        "lambda_c", ...}；未曾计划过返回空 dict。
        """
        p = getattr(self._tls, "last_mode_plan", None)
        return dict(p) if isinstance(p, dict) else {}

    def last_execution_mode(self) -> str:
        """本线程最近一次 generate **实际执行**的模式（"C"/"C→L"/"L"）。

        与 last_mode_plan() 对照可审计「计划 vs 实际」偏差；未曾生成返回 ""。
        """
        return str(getattr(self._tls, "last_mode_executed", "") or "")

    def list_providers(self) -> List[Dict[str, Any]]:
        """列出可用生成器及其可用状态 + 能力/单价/健康摘要（供 UI 展示）"""
        try:
            from .provider_caps import get_caps
        except Exception:
            get_caps = None  # type: ignore[assignment]
        pool = None
        try:
            from .provider_pool import get_pool

            pool = get_pool()
        except Exception:
            logger.debug("[VideoGenerationClient] 额度池不可用，健康信息缺省", exc_info=True)
        rows: List[Dict[str, Any]] = []
        for pid, name in (
            ("kling", "可灵 Kling（快手开放平台）"),
            ("dashscope", "阿里云百炼 万相（Wan）"),
            ("seedance", "火山引擎 Seedance"),
            ("cogvideo", "智谱 CogVideo"),
            ("local", "本地占位生成（FFmpeg 色块）"),
        ):
            row: Dict[str, Any] = {
                "id": pid, "name": name,
                "available": self._get_provider(pid) is not None,
            }
            if get_caps is not None:
                caps = get_caps(pid)
                if caps:
                    row["caps"] = {
                        k: caps.get(k)
                        for k in ("text_to_video", "image_to_video",
                                  "first_last_frame", "lip_sync",
                                  "max_duration", "resolutions", "quality_tier")
                    }
                    row["price_per_clip"] = float(caps.get("price_per_clip") or 0.0)
            if pool is not None:
                try:
                    row["health"] = pool.health(pid)
                except Exception:
                    logger.debug("[VideoGenerationClient] %s 健康查询失败", pid, exc_info=True)
            rows.append(row)
        return rows

    # ────────────── 报价（P1-1）──────────────

    def quote(self, provider: str = "auto", *, count: int = 1,
              duration: float = 0.0, width: int = 0, height: int = 0,
              spec: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """**生成前报价**：沿真实路由链预估本次生成花费 + 谁接单 + 配额健康。

        与 ``generate()`` 同一套决策（能力筛选 → 池内重排 → handler 可用性），
        但**只读预演**：不生成、不记账、不消耗配额。
        候选链里「客户端封装加载不出」的渠道会被跳过（与 generate 循环一致）。

        Returns（池可用时）::
            {"ok", "provider", "account_id", "tier", "price_per_clip", "count",
             "cost_estimate", "currency", "quota_remaining", "cloud_available",
             "dead_providers", "reason", "note"}
        池不可用时退化为声明表估算（provider/cost_estimate/count/note）。
        """
        merged: Dict[str, Any] = {}
        try:
            from .provider_caps import normalize_spec

            merged = normalize_spec(spec, duration=duration, width=width, height=height)
        except Exception:
            logger.debug("[VideoGenerationClient] spec 规范化失败，按空 spec 报价", exc_info=True)

        # ① 池视角报价（含账号/配额/死号跳过）
        try:
            from .provider_pool import get_pool

            q = get_pool().quote(provider, count=count, spec=merged or None)
        except Exception:
            logger.debug("[VideoGenerationClient] 池报价不可用，退化为声明估算", exc_info=True)
            q = {}

        # ② 校验「池认为的首选」handler 是否真的加载得出（与 generate 循环一致）
        chosen = str(q.get("provider") or "")
        if chosen and chosen != "local" and self._get_provider(chosen) is None:
            # 池不可用时 chosen 为空 → 走 ③ 的声明链兜底；
            # 池可用但首选封装缺失 → 沿池的重排链找下一个 handler 可用的
            fallback = self._resolve_provider_order(provider, spec=spec,
                                                    duration=duration,
                                                    width=width, height=height)
            chosen = next((p for p in fallback
                           if p != "local" and self._get_provider(p) is not None), "local")
            if chosen != q.get("provider"):
                q = dict(q)
                q["provider"] = chosen
                q["cloud_available"] = chosen != "local"
                q["account_id"] = ""
                q["quota_remaining"] = 0
                if chosen == "local":
                    q["cost_estimate"] = 0.0
                    q["price_per_clip"] = 0.0
                    q["reason"] = "云端客户端封装不可用，将回退本地占位"

        if q:
            return q

        # ③ 池完全不可用：声明表估算 + handler 可用性修正
        try:
            from .provider_caps import quote as caps_quote

            q = dict(caps_quote(provider, count=count, spec=merged or None))
            if q.get("provider") != "local" and \
                    self._get_provider(str(q.get("provider"))) is None:
                q["provider"] = "local"
                q["cost_estimate"] = 0.0
                q["price_per_clip"] = 0.0
            return q
        except Exception:
            return {"ok": True, "provider": "local", "count": max(1, int(count or 1)),
                    "cost_estimate": 0.0, "currency": "CNY",
                    "note": "报价模块不可用，按本地占位（免费）报"}

    # ────────────── Provider 解析 ──────────────

    def _resolve_provider_order(self, provider: str,
                                spec: Optional[Dict[str, Any]] = None,
                                duration: float = 0.0,
                                width: int = 0, height: int = 0) -> List[str]:
        """解析 provider 调用顺序。

        V4.35.0 起走**能力声明路由**（provider_caps.resolve_order）：
        按本次请求 spec 筛掉不支持的 provider，再排序，local 永远兜底。
        V4.37.4 起排序升级为**收益函数**（规格书切片）：q̂ − λ_c·price，
        q̂ 来自 quality_prior 质量先验库；先验库不可用则退回 tier 排序。
        声明模块不可用时**诚实降级**回旧的名字顺序。
        """
        try:
            from .provider_caps import normalize_spec, resolve_order

            # 合并：显式 spec 优先，未提的字段由 generate() 的 duration/分辨率补上
            merged = normalize_spec(spec, duration=duration, width=width, height=height)
            priors: Optional[Dict[str, float]] = None
            lam: Optional[float] = None
            try:
                from .quality_prior import get_store

                store = get_store()
                snap = store.summary()
                if snap:
                    # route_mean：quality 真值桶优先，default 可用性桶兜底（切片②）
                    providers = {k.split("::", 1)[0] for k in snap}
                    priors = {p: store.route_mean(p) for p in providers}
            except Exception:
                logger.debug("[VideoGenerationClient] 质量先验库不可用，退回 tier 排序", exc_info=True)
            try:
                from .budget_pacer import get_pacer

                lam = get_pacer().get_lambda()  # L1 任务层 λ^τ（切片④）
            except Exception:
                logger.debug("[VideoGenerationClient] 预算控制器不可用，静态 λ 兜底", exc_info=True)
            # 切片⑧（V4.38.1）：λ_eff = λ^G + λ^τ（§2 有效价格叠加规则）——
            # L0 全局层管月度账单，积分主导慢环；两层正交各自归因。
            try:
                from .global_price import get_global_price

                lam = (lam if lam is not None else 0.2) + get_global_price().get_lambda()
            except Exception:
                logger.debug("[VideoGenerationClient] 全局价格层不可用（仅 L1）",
                             exc_info=True)
            # 切片⑤（V4.37.8）：六模式收益打分 + 可行集投影，产出**可归因**的
            # 模式计划（观测用；D/L→C 执行体在后续切片接线，当前执行语义
            # 仍是既有 provider 链 = C→L 回退）。打分不改分、投影只删项。
            try:
                from .execution_modes import MODE_D, choose_mode, collect_infeasible
                from .provider_caps import PROVIDER_CAPS

                chain_preview = resolve_order(provider, spec=merged,
                                              priors=priors, lambda_price=lam)
                first_real = next((p for p in chain_preview if p != "local"), "")
                q_cloud = float((priors or {}).get(first_real, 0.5)) if first_real else 0.0
                cost_cloud = float((PROVIDER_CAPS.get(first_real) or {})
                                   .get("price_per_clip") or 0.0)
                infeasible = collect_infeasible(cloud_available=bool(first_real))
                # 切片⑥（V4.37.9）：A 模块分歧度探针——Δ 未超自适应阈值时
                # 把 D 投影删除（探针只筛候选，不改打分；§16「不直接决策路由」
                # 指的是不改收益分，删候选走投影层，归因可查）。
                probe_verdict: Dict[str, Any] = {}
                try:
                    from .divergence_probe import get_probe

                    verdict = get_probe().is_dual_candidate("video")
                    probe_verdict = verdict
                    if not verdict.get("candidate") and MODE_D not in infeasible:
                        infeasible[MODE_D] = "探针：" + str(verdict.get("reason", ""))
                except Exception:
                    logger.debug("[VideoGenerationClient] 分歧探针不可用（不阻断）",
                                 exc_info=True)
                plan = choose_mode(
                    q_local=0.3,  # 本地占位质量低但成本=0（基线锚点）
                    q_cloud=q_cloud,
                    cost_local=0.0,
                    cost_cloud=cost_cloud,
                    lambda_c=float(lam) if lam is not None else 0.2,
                    infeasible=infeasible,
                )
                if probe_verdict:
                    plan["probe"] = probe_verdict
                self._tls.last_mode_plan = plan
            except Exception:
                logger.debug("[VideoGenerationClient] 模式计划不可用（不阻断）", exc_info=True)
            return resolve_order(provider, spec=merged, priors=priors, lambda_price=lam)
        except Exception:
            logger.debug("[VideoGenerationClient] 能力路由不可用，回退名字顺序", exc_info=True)
            if provider and provider != "auto":
                return [provider, "local"]
            return ["seedance", "cogvideo", "local"]

    def _get_provider(self, name: str) -> Optional[Callable]:
        """延迟加载 provider，加载失败返回 None"""
        if name == "local":
            return self._call_local_fallback
        if name in self._providers:
            return self._providers[name]
        handler: Optional[Callable] = None
        try:
            if name == "seedance":
                handler = self._load_seedance()
            elif name == "cogvideo":
                handler = self._load_cogvideo()
            elif name == "dashscope":
                handler = self._load_dashscope()
            elif name == "kling":
                handler = self._load_kling()
        except Exception as e:
            logger.debug(f"[VideoGenerationClient] 加载 {name} 失败: {e}")
        self._providers[name] = handler
        return handler

    def _load_seedance(self) -> Optional[Callable]:
        """加载火山引擎 Seedance 客户端（项目内若有封装则用，否则返回 None）"""
        # 尝试项目内可能的封装路径；不存在则静默回退
        try:
            from app.core.ai.byted_seedance import generate_videos as _seed  # type: ignore
            return _seed
        except Exception as e:
            logger.debug(f"[VideoGenClient] 加载Seedance封装失败: {e}")
        try:
            from app.core.ai.byted_seedance_client import SeedanceClient  # type: ignore
            client = SeedanceClient()

            def _seed(prompt, duration, count, width, height):
                return client.generate(prompt=prompt, duration=duration, count=count)
            return _seed
        except Exception as e:
            logger.debug(f"[VideoGenClient] 加载SeedanceClient失败: {e}")
            return None

    def _load_cogvideo(self) -> Optional[Callable]:
        """加载智谱 CogVideo 客户端"""
        try:
            from app.core.ai.cogvideo_client import CogVideoClient  # type: ignore
            client = CogVideoClient()

            def _cog(prompt, duration, count, width, height):
                return client.generate(prompt=prompt, duration=duration, count=count)
            return _cog
        except Exception:
            return None

    def _load_dashscope(self) -> Optional[Callable]:
        """加载阿里云百炼万相（Wan）客户端。

        key 缺失时返回 None（路由自动跳过该渠道，走 seedance/cogvideo/local）；
        key 存在但模型未开通时 generate_videos 抛 RuntimeError，
        由 generate() 记为 provider 失败进额度池（指数退避），不静默。
        """
        try:
            from app.core.ai.dashscope_video import generate_videos as _wan
            from app.core.ai.dashscope_video import get_api_key
            if not get_api_key():
                logger.info("[VideoGenClient] DASHSCOPE_API_KEY 未配置，跳过 dashscope")
                return None
            return _wan
        except Exception as e:
            logger.debug(f"[VideoGenClient] 加载 DashScope 万相失败: {e}")
            return None

    def _load_kling(self) -> Optional[Callable]:
        """加载可灵 Kling 客户端（2026-10-14 起为 auto 默认首选渠道）。

        复用画布 AIGC 既有 host 链路（``canvas_aigc.generate_video_via_host``），
        kling 分支在 L1857 附近按 base_url/model 识别后走 submit + poll。
        key 未配置（模型广场无可用 AIGC 渠道）时返回 None，路由自动顺延
        dashscope → seedance → cogvideo → local，绝不假成功。
        """
        try:
            from app.core.canvas_aigc import (
                _resolve_aigc_channel,
                generate_video_via_host,
            )
            ch, default_model, _patch = _resolve_aigc_channel(capability="video")
            if ch is None:
                logger.info("[VideoGenClient] 模型广场无可用 AIGC 渠道，跳过 kling")
                return None
            channel_id = str(ch.get("id") or "")

            def _kling(prompt, duration, count, width, height):
                # generate() 期望「路径列表」；host 链路返回 dict，
                # 失败必须**抛异常**（不能返回空列表假装成功）才能让路由顺延下一渠道。
                res = generate_video_via_host(
                    prompt=prompt,
                    model=default_model,
                    channel_id=channel_id,
                    duration=duration,
                    size=f"{int(width)}x{int(height)}" if width and height else "",
                )
                if not isinstance(res, dict) or not res.get("ok"):
                    msg = (res or {}).get("message", "未知错误") if isinstance(res, dict) else str(res)
                    raise RuntimeError(f"Kling 生成失败: {msg}")
                path = str(res.get("video_path") or "")
                if not path:
                    raise RuntimeError("Kling 返回成功但无 video_path")
                return [path]
            return _kling
        except Exception as e:
            logger.debug(f"[VideoGenClient] 加载 Kling 客户端失败: {e}")
            return None

    def _record_prior(self, name: str, ok: bool) -> None:
        """回写质量先验（V4.37.4，规格书 §14 切片）。

        local 占位不记录（占位成功 ≠ 质量信号）；先验库异常绝不抛出。
        当前观测样本是执行成败（1.0/0.0）；待 B 模块评分器接入后
        改为经 record_outcome(quality=五维分) 喂真值，路由无需改动。
        """
        if name == "local":
            return
        try:
            from .quality_prior import get_store

            get_store().record_outcome(name, ok)
        except Exception:
            logger.debug("[VideoGenerationClient] 质量先验回写失败（不阻断主链路）",
                         exc_info=True)

    def _record_spend(self, name: str, segments: int) -> None:
        """实际花费记账（V4.37.7 切片④）：price_per_clip × 段数 → budget_pacer。

        local 占位免费不记；金额取自能力声明表的估算单价（实际以渠道账单为准，
        账单回写属后续 A2 方向）；控制器异常绝不抛出。
        """
        if name == "local" or segments <= 0:
            return
        try:
            from .budget_pacer import get_pacer
            from .provider_caps import get_caps

            caps = get_caps(name) or {}
            price = float(caps.get("price_per_clip") or 0.0)
            if price > 0:
                amount = price * segments
                get_pacer().record_spend(amount)
                # 切片⑧：同一笔花费同步进 L0 全局账单（两层各算各的误差）
                try:
                    from .global_price import get_global_price

                    get_global_price().record_spend(amount)
                except Exception:
                    logger.debug("[VideoGenerationClient] 全局账单记账失败（不阻断）",
                                 exc_info=True)
                # 切片⑥：单元成本进探针预算分母（§16.1 探针成本 ≤2% 单元成本）
                try:
                    from .divergence_probe import get_probe

                    get_probe().note_unit_cost(price * segments)
                except Exception:
                    logger.debug("[VideoGenerationClient] 探针成本记账失败（不阻断）",
                                 exc_info=True)
        except Exception:
            logger.debug("[VideoGenerationClient] 花费记账失败（不阻断主链路）",
                         exc_info=True)

    # ────────────── D 双路执行体（V4.38.0 切片⑦）──────────────

    def _execute_dual(self, prompt: str, duration: float, count: int,
                      width: int, height: int,
                      providers: Optional[List[str]] = None) -> List[str]:
        """D 模式：本地+云端双路 → 分歧度实测入库 → 融合（关键帧择优+时序拼接）。

        规格书 §10 D 定义：分歧高、关键单元启用。桌面单机版用**顺序双路**
        （本地占位秒出，云端异步本来就慢）替代并行——语义等价、实现可靠。

        云端失败 → 退化为本地单路（记 C→L，不冒充 D 交付）；
        融合后溯源存 ``last_fusion()``；任一环异常 → 返回 [] 让调用方回退单路链。
        """
        try:
            from .divergence_probe import get_probe, media_divergence
            from .fusion import plan_video_fusion
        except Exception:
            logger.debug("[VideoGenerationClient] 双路依赖不可用", exc_info=True)
            return []
        order = providers or self._resolve_provider_order("auto")
        first_real = next((p for p in order if p != "local"), "")
        cloud = self._get_provider(first_real) if first_real else None
        local = self._get_provider("local")
        if local is None:
            return []
        # 本地路（快，先跑；占位生成就是基线锚点）
        local_paths: List[str] = []
        try:
            local_paths = local(prompt=prompt, duration=duration, count=count,
                                width=width, height=height) or []
        except _GenCancelled:
            raise
        except Exception as e:
            logger.warning(f"[VideoGenerationClient] 双路-本地路失败: {e}")
        # 云端路
        cloud_paths: List[str] = []
        if cloud is not None:
            try:
                cloud_paths = cloud(prompt=prompt, duration=duration, count=count,
                                    width=width, height=height) or []
            except _GenCancelled:
                raise
            except Exception as e:
                logger.warning(f"[VideoGenerationClient] 双路-云端路失败: {e}")
                self._record_prior(first_real, ok=False)
                try:
                    from .provider_pool import get_pool

                    get_pool().report_failure(first_real, error=str(e))
                except Exception:
                    logger.debug("忽略异常（原为 pass）: video_generation_client.py", exc_info=True)
        if not cloud_paths:
            # 云端挂 → 双路退化为本地单路（诚实标记 C→L，不冒充 D）
            if local_paths:
                self._tls.last_provider = "local"
                self._tls.last_mode_executed = "C→L"
                try:
                    from .degradation import DegradationSession, get_stats

                    s = DegradationSession()
                    s.mark(6, "D 双路云端失败，退化本地单路")
                    get_stats().record(s.final_level)
                    self._tls.last_degradation = s.summary()
                except Exception:
                    logger.debug("忽略异常（原为 pass）: video_generation_client.py", exc_info=True)
            return local_paths
        # ── 双路都成：分歧实测（成本门控内才入库，§18） ──
        probe = get_probe()
        delta = media_divergence(local_paths[0], cloud_paths[0],
                                 duration, duration) if local_paths else 1.0
        try:
            if probe.cost_gate(0.0).get("allowed", True):
                probe.record("video", delta)
        except Exception:
            logger.debug("[VideoGenerationClient] 分歧入库失败（不阻断）", exc_info=True)
        # ── 融合：逐槽关键帧择优 + 时序拼接计划（§42 视频算子） ──
        q_cloud = 0.5
        try:
            from .quality_prior import get_store

            q_cloud = get_store().route_mean(first_real)
        except Exception:
            logger.debug("忽略异常（原为 pass）: video_generation_client.py", exc_info=True)
        segments: List[Dict[str, Any]] = []
        for i in range(max(1, int(count))):
            if i < len(cloud_paths):
                segments.append({"slot": i, "source": "cloud",
                                 "path": cloud_paths[i], "quality": q_cloud,
                                 "duration": duration, "keyframe_ok": True})
            if i < len(local_paths):
                segments.append({"slot": i, "source": "local",
                                 "path": local_paths[i], "quality": 0.3,
                                 "duration": duration, "keyframe_ok": True})
        plan, provenance = plan_video_fusion(segments, prefer="cloud")
        out = [p["path"] for p in plan if p.get("path")]
        if not out:
            return cloud_paths
        # ── 记账 / 归因 / 溯源 ──
        self._record_prior(first_real, ok=True)
        self._record_spend(first_real, len(cloud_paths))
        try:
            from .provider_pool import get_pool

            get_pool().report_success(first_real, segments=len(cloud_paths))
        except Exception:
            logger.debug("忽略异常（原为 pass）: video_generation_client.py", exc_info=True)
        self._tls.last_provider = first_real
        self._tls.last_mode_executed = "D"
        self._tls.last_fusion = provenance
        self._emit_generation_done(out, prompt=prompt)
        chosen = [f"{p['slot']}:{p['source']}" for p in plan]
        logger.info(f"[VideoGenerationClient] D 双路融合完成 Δ={delta:.2f} 选源 {chosen}")
        return out

    def last_fusion(self) -> Dict[str, Any]:
        """本线程最近一次 D 双路融合的溯源（§42 Provenance）；未融合过返回 {}。"""
        f = getattr(self._tls, "last_fusion", None)
        return dict(f) if isinstance(f, dict) else {}

    # ────────────── 本地占位生成 ──────────────

    def _call_local_fallback(self, prompt: str, duration: float = _DEFAULT_DURATION,
                             count: int = 1, width: int = _DEFAULT_RESOLUTION[0],
                             height: int = _DEFAULT_RESOLUTION[1],
                             **_: Any) -> List[str]:
        """
        本地占位生成：用 FFmpeg 生成色块 + hue 渐变 + 文字标识的占位片段。
        保证无网络/无云端 Key 时业务流程仍可演示。
        失败回退到无文字的纯色块版本。
        """
        ffmpeg = self._find_ffmpeg()
        if not ffmpeg:
            logger.error("[VideoGenerationClient] 未找到 ffmpeg，无法占位生成")
            return []

        paths: List[str] = []
        safe_prompt = (prompt or "AI生成")[:20].replace(" ", "_").replace(":", "_")
        for i in range(count):
            _raise_if_cancelled()  # P1-3：占位段与段之间响应取消
            out_path = os.path.join(
                self._output_dir,
                f"gen_{int(time.time())}_{uuid.uuid4().hex[:6]}_{safe_prompt}_{i + 1}.mp4"
            )
            hue = (i * 60) % 360  # 不同片段用不同色相，便于区分
            label = self._escape_drawtext(f"AI Gen #{i + 1} | {(prompt or '')[:24]}")
            if self._generate_with_text(ffmpeg, out_path, label, hue, duration, width, height):
                paths.append(out_path)
            elif self._generate_plain(ffmpeg, out_path, hue, duration, width, height):
                paths.append(out_path)
            else:
                logger.warning(f"[VideoGenerationClient] 占位生成第 {i + 1} 段失败")
        return paths

    def _generate_with_text(self, ffmpeg: str, out_path: str, label: str,
                            hue: int, duration: float, width: int, height: int) -> bool:
        """带文字标识的占位生成（需要字体支持）"""
        filter_str = (
            f"color=c=0x223355:s={width}x{height}:d={duration}:r={_DEFAULT_FPS},"
            f"format=yuv420p,"
            f"drawtext=text='{label}':fontcolor=white:fontsize=32:"
            f"x=(w-text_w)/2:y=(h-text_h)/2,"
            f"hue=h={hue}:s=1"
        )
        return self._run_ffmpeg(ffmpeg, filter_str, duration, out_path)

    def _generate_plain(self, ffmpeg: str, out_path: str, hue: int,
                        duration: float, width: int, height: int) -> bool:
        """无文字的纯色块占位生成（字体不支持时回退）"""
        filter_str = (
            f"color=c=0x223355:s={width}x{height}:d={duration}:r={_DEFAULT_FPS},"
            f"format=yuv420p,hue=h={hue}:s=1"
        )
        return self._run_ffmpeg(ffmpeg, filter_str, duration, out_path)

    def _run_ffmpeg(self, ffmpeg: str, filter_str: str,
                    duration: float, out_path: str) -> bool:
        """执行 ffmpeg 命令生成片段"""
        cmd = [
            ffmpeg, "-y", "-loglevel", "error",
            "-f", "lavfi", "-i", filter_str,
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-t", str(duration),
            out_path,
        ]
        try:
            proc = subprocess.run(
                cmd, capture_output=True, timeout=60,
                creationflags=self._subprocess_flags(),
            )
            return proc.returncode == 0 and os.path.exists(out_path) \
                and os.path.getsize(out_path) > 0
        except Exception as e:
            logger.debug(f"[VideoGenerationClient] ffmpeg 执行异常: {e}")
            return False

    # ────────────── 工具方法 ──────────────

    @staticmethod
    def _escape_drawtext(text: str) -> str:
        """转义 drawtext 文本中的特殊字符"""
        # drawtext 对冒号/单引号/反斜杠敏感
        return (text.replace("\\", "\\\\")
                    .replace(":", "\\:")
                    .replace("'", "\\'"))

    @staticmethod
    def _find_ffmpeg() -> Optional[str]:
        """优先复用项目 ffmpeg_utils（含 thirdparty/ffmpeg/bin/ 查找），回退本地候选 + 系统 PATH"""
        # 1. 项目统一 ffmpeg 查找逻辑（禁止重复造轮子）
        try:
            from app.core.ffmpeg_utils import find_ffmpeg
            path = find_ffmpeg()
            if path and os.path.isfile(path):
                return path
        except Exception as e:
            logger.debug(f"[VideoGenerationClient] ffmpeg_utils 查找失败: {e}")
        # 2. 本地候选（兼容兜底）
        candidates = [
            os.path.join(os.getcwd(), "thirdparty", "ffmpeg", "bin", "ffmpeg.exe"),
            os.path.join(os.getcwd(), "ffmpeg", "ffmpeg.exe"),
            os.path.join(os.getcwd(), "bin", "ffmpeg.exe"),
            os.path.join(os.getcwd(), "tools", "ffmpeg.exe"),
        ]
        for c in candidates:
            if os.path.isfile(c):
                return c
        return shutil.which("ffmpeg") or shutil.which("ffmpeg.exe")

    @staticmethod
    def _subprocess_flags() -> int:
        """Windows 下隐藏控制台窗口，避免弹出黑框"""
        try:
            import sys
            if sys.platform == "win32":
                return 0x08000000  # CREATE_NO_WINDOW
        except Exception as e:
            logger.debug(f"[VideoGenClient] 获取子进程标志失败: {e}")
        return 0

    def _emit_generation_done(self, paths: List[str], prompt: str) -> None:
        """广播生成完成事件（便于 pipeline 层追踪，不强制依赖 EventBus）"""
        try:
            from app.modules.lego.core import EventBus, EventType
            bus = EventBus.get_instance()
            bus.emit(
                EventType.CUSTOM,
                {
                    "subtype": "video_generation_done",
                    "count": len(paths),
                    "paths": paths,
                    "prompt": prompt[:80],
                },
                source="VideoGenerationClient",
            )
        except Exception as e:
            logger.debug(f"[VideoGenerationClient] emit 失败: {e}")


# 全局单例便捷引用
video_generation_client = VideoGenerationClient.get_instance()
