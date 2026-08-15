"""
统一 AI 调用引擎 (AIEngine)
============================

提供统一的 AI 模型调用接口，整合云端 API（16 个 provider）和本地 Ollama，
自动处理：智能路由、指数退避重试、LRU 缓存、熔断保护和 Token 费用追踪。

架构
----
调用入口:
  AIEngine.chat(provider, messages)
  AIEngine.chat_with_fallback(messages, providers=[...])
  AIEngine.session() → AISession

路由链:
  首选 provider → 备选 provider(s) → Ollama 本地 → 模板回退

已有调用方迁移路径:
  旧: cloud_api_service.chat("deepseek", messages, ...)
  新: ai_engine.chat("deepseek", messages, ...)                    [兼容]

  旧: ollama_client.chat(model, messages, ...)
  新: ai_engine.chat("ollama", messages, model=model, ...)        [兼容]

  旧: EditorModule._call_llm(system, user)
  新: ai_engine.chat_with_fallback(messages=[...], template=...)  [增强]

  旧: AIEnhanced.generate_content(type, prompt)
  新: ai_engine.chat_with_fallback(messages=[...], use_cache=True) [增强]

使用示例
--------
    from app.core.ai_engine import ai_engine

    # 1) 基础调用
    for chunk in ai_engine.chat("deepseek", [{"role":"user","content":"你好"}]):
        print(chunk, end="")

    # 2) 智能降级 (deepseek → doubao → ollama → 模板)
    result = ai_engine.chat_with_fallback(
        messages=[{"role":"user","content":"写个标题"}],
        providers=["deepseek", "doubao"],
        template=lambda: "默认标题"
    )

    # 3) 会话模式
    with ai_engine.session() as s:
        s.chat(user_message="分析这段视频")

    # 4) 查看统计
    print(ai_engine.get_usage_summary())
"""

import hashlib
import json
import logging
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Generator, List, Optional, Tuple
from enum import Enum

logger = logging.getLogger(__name__)


# ============================================================================
# 数据结构
# ============================================================================

@dataclass
class AICallRecord:
    """单次 AI 调用记录"""
    provider: str
    model: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    duration_ms: float = 0
    success: bool = True
    error: str = ""
    timestamp: float = field(default_factory=time.time)


@dataclass
class ProviderStats:
    """Provider 级别的累积统计 + 熔断计数器"""
    total_calls: int = 0
    success_calls: int = 0
    failed_calls: int = 0
    total_tokens: int = 0
    total_cost: float = 0.0
    last_error: str = ""
    last_error_time: float = 0
    consecutive_failures: int = 0


@dataclass
class CacheEntry:
    """缓存条目 (LRU + TTL)"""
    value: Any
    timestamp: float
    ttl: float


# ============================================================================
# Provider 费用定价 (元 / 百万 token)
# ============================================================================

_DEFAULT_PRICING: Dict[str, Tuple[float, float]] = {
    # provider: (input_price_per_1M, output_price_per_1M)
    "deepseek":    (1.0,  2.0),
    "doubao":      (0.8,  2.0),
    "openai":      (15.0, 60.0),
    "zhipu":       (1.0,  1.0),
    "qwen":        (2.0,  6.0),
    "wenxin":      (0.0,  0.0),
    "spark":       (0.0,  0.0),
    "kimi":        (12.0, 12.0),
    "baichuan":    (0.0,  0.0),
    "minimax":     (0.0,  0.0),
    "claude":      (3.0,  15.0),
    "groq":        (0.0,  0.0),
    "siliconflow": (1.0,  1.0),
    "stepfun":     (0.0,  0.0),
    "yi":          (1.0,  1.0),
    "ollama":      (0.0,  0.0),
}


# ============================================================================
# 统一 AI 引擎
# ============================================================================

class AIEngine:
    """统一 AI 调用引擎 — 线程安全单例

    整合 CloudAPIService (16 云端 provider) + OllamaClient (本地模型)，
    提供 chat()/chat_with_fallback() 统一入口。

    关键特性:
      - 指数退避重试（默认 2 次，可配置）
      - LRU 内存缓存 + 可配置 TTL（默认 5 分钟）
      - 熔断器：连续 5 次失败自动隔离 60 秒
      - 粗略 Token 计数 + 费用估算
      - session() 上下文管理器（自动管理对话历史）
    """

    _instance: Optional['AIEngine'] = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if getattr(self, "_initialized", False):
            return
        self._initialized = True

        # ── 客户端引用（延迟加载） ──
        self._cloud_api = None
        self._ollama_client = None
        self._clients_loaded = False

        # ── 统计 ──
        self._stats: Dict[str, ProviderStats] = {}
        self._call_history: List[AICallRecord] = []
        self._max_history = 500

        # ── 预算追踪（AI NG 预算 / 成本仪表盘） ──
        self._budget_limit: float = 0.0          # 0 = 不限制
        self._project_budget: float = 0.0        # 单项目预算上限，0 = 不限制
        self._ng_budget_total: int = 0           # 生成图片/视频的 NG 总次数（调用方可增量更新）

        # ── 缓存 ──
        self._cache: OrderedDict[str, CacheEntry] = OrderedDict()
        self._max_cache_size = 100
        self._default_cache_ttl = 300  # 秒

        # ── 熔断 ──
        self._circuit_breaker_threshold = 5
        self._circuit_breaker_timeout = 60  # 秒
        self._circuit_open: Dict[str, float] = {}

        # ── 默认配置 ──
        self._default_providers = [
            "deepseek", "doubao", "zhipu", "qwen", "openai", "siliconflow",
        ]

        # ── 定价 ──
        self._pricing = dict(_DEFAULT_PRICING)

        logger.info("[AIEngine] 引擎初始化完成")

    @classmethod
    def get_instance(cls) -> 'AIEngine':
        """返回全局单例（与模块级 `ai_engine` 是同一对象）。

        供仍在用 `AIEngine.get_instance()` 旧写法的调用方使用；
        新代码优先 `from app.core.ai_engine import ai_engine`。
        """
        if cls._instance is None:
            cls()
        return cls._instance

    # ────────────────────────────────────────────────────────────────
    # 延迟加载
    # ────────────────────────────────────────────────────────────────

    def _ensure_clients(self):
        """延迟加载 AI 客户端（首次调用时初始化）"""
        if getattr(self, "_clients_loaded", False):
            return
        # 旧单例若曾错误初始化，补齐缺失属性
        if not hasattr(self, "_cloud_api"):
            self._cloud_api = None
        if not hasattr(self, "_ollama_client"):
            self._ollama_client = None
        if not hasattr(self, "_stats"):
            self._stats = {}
        if not hasattr(self, "_call_history"):
            self._call_history = []
        if not hasattr(self, "_cache"):
            self._cache = OrderedDict()
        if not hasattr(self, "_circuit_open"):
            self._circuit_open = {}
        if not hasattr(self, "_default_providers"):
            self._default_providers = [
                "deepseek", "doubao", "zhipu", "qwen", "openai", "siliconflow",
            ]
        if not hasattr(self, "_pricing"):
            self._pricing = dict(_DEFAULT_PRICING)
        if not hasattr(self, "_max_cache_size"):
            self._max_cache_size = 100
        if not hasattr(self, "_default_cache_ttl"):
            self._default_cache_ttl = 300
        if not hasattr(self, "_circuit_breaker_threshold"):
            self._circuit_breaker_threshold = 5
        if not hasattr(self, "_circuit_breaker_timeout"):
            self._circuit_breaker_timeout = 60
        if not hasattr(self, "_max_history"):
            self._max_history = 500

        try:
            from app.modules.lego.cloud_api import cloud_api_service
            self._cloud_api = cloud_api_service
        except ImportError as e:
            logger.warning(f"[AIEngine] CloudAPIService 未找到: {e}")

        try:
            from app.modules.lego.ollama_client import ollama_client
            self._ollama_client = ollama_client
        except ImportError as e:
            logger.warning(f"[AIEngine] OllamaClient 未找到: {e}")

        self._clients_loaded = True

    # ────────────────────────────────────────────────────────────────
    # 可用性检测
    # ────────────────────────────────────────────────────────────────

    def get_available_providers(self) -> List[str]:
        """返回当前所有可用的提供者列表"""
        self._ensure_clients()
        available: List[str] = []

        if self._ollama_client and self._ollama_client.is_available():
            available.append("ollama")

        if self._cloud_api:
            for p in self._default_providers:
                try:
                    if self._cloud_api.get_provider(p):
                        available.append(p)
                except Exception as e:
                    logger.debug(f"[AIEngine] 获取提供者 {p} 失败: {e}")

        # 去重并保持顺序
        seen: set = set()
        result = []
        for p in available:
            if p not in seen:
                seen.add(p)
                result.append(p)
        return result

    def is_provider_available(self, provider: str) -> bool:
        """检测指定提供者是否可用（考虑熔断状态）"""
        # 检查熔断
        if provider in self._circuit_open:
            if time.time() < self._circuit_open[provider]:
                return False
            del self._circuit_open[provider]

        if provider == "ollama":
            self._ensure_clients()
            return (
                self._ollama_client is not None
                and self._ollama_client.is_available()
            )

        self._ensure_clients()
        if not self._cloud_api:
            return False
        try:
            return self._cloud_api.get_provider(provider) is not None
        except Exception:
            return False

    # ────────────────────────────────────────────────────────────────
    # 熔断器
    # ────────────────────────────────────────────────────────────────

    def _on_failure(self, provider: str, error: str):
        """记录失败，连续失败超阈值则熔断"""
        stats = self._stats.setdefault(provider, ProviderStats())
        stats.total_calls += 1
        stats.failed_calls += 1
        stats.consecutive_failures += 1
        stats.last_error = error
        stats.last_error_time = time.time()

        if stats.consecutive_failures >= self._circuit_breaker_threshold:
            self._circuit_open[provider] = (
                time.time() + self._circuit_breaker_timeout
            )
            logger.warning(
                f"[AIEngine] 熔断: {provider} "
                f"(连续 {stats.consecutive_failures} 次失败, "
                f"{self._circuit_breaker_timeout}s 后恢复)"
            )

    # ────────────────────────────────────────────────────────────────
    # Token 估算 & 费用
    # ────────────────────────────────────────────────────────────────

    @staticmethod
    def _estimate_tokens(text: str) -> int:
        """粗略 token 估算: 中文 ~0.6 token/字, 非中文 ~0.3 token/字"""
        if not text:
            return 0
        chinese = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
        other = len(text) - chinese
        return int(chinese * 0.6 + other * 0.3)

    def _estimate_cost(
        self, provider: str, prompt_tokens: int, completion_tokens: int
    ) -> float:
        """估算单次调用费用"""
        if provider not in self._pricing:
            return 0.0
        input_price, output_price = self._pricing[provider]
        cost = (
            (prompt_tokens / 1_000_000) * input_price
            + (completion_tokens / 1_000_000) * output_price
        )
        return round(cost, 6)

    # ────────────────────────────────────────────────────────────────
    # 预算追踪（AI NG 预算 / 成本仪表盘）
    # ────────────────────────────────────────────────────────────────

    def set_budget_limit(self, limit: float, project_limit: float = 0.0) -> None:
        """设置全局 / 单项目预算上限（单位：元）。0 = 不限制。"""
        self._budget_limit = max(0.0, float(limit))
        self._project_budget = max(0.0, float(project_limit))

    def check_budget(self) -> Dict[str, Any]:
        """返回当前预算使用情况 + 是否超支标记。"""
        total_cost = sum(s.total_cost for s in self._stats.values())
        return {
            "total_cost": round(total_cost, 4),
            "budget_limit": self._budget_limit,
            "project_budget": self._project_budget,
            "over_budget": bool(self._budget_limit > 0 and total_cost >= self._budget_limit),
            "ng_count": self._ng_budget_total,
            "providers": {
                p: {
                    "calls": s.total_calls,
                    "cost": round(s.total_cost, 4),
                    "tokens": s.total_tokens,
                    "success_rate": round(
                        s.success_calls / max(1, s.total_calls), 3
                    ),
                }
                for p, s in self._stats.items()
            },
        }

    def increment_ng_count(self, delta: int = 1) -> int:
        """增加生成图片/视频的 NG 次数（失败/不满意都算）。返回新总数。"""
        self._ng_budget_total += max(0, int(delta))
        return self._ng_budget_total

    def get_recent_calls(self, limit: int = 20) -> List[Dict[str, Any]]:
        """返回最近 N 次调用记录（供前端仪表盘展示）。"""
        recents = self._call_history[-max(1, limit):]
        return [
            {
                "provider": r.provider,
                "model": r.model,
                "prompt_tokens": r.prompt_tokens,
                "completion_tokens": r.completion_tokens,
                "duration_ms": round(r.duration_ms, 1),
                "success": r.success,
                "cost": round(
                    self._estimate_cost(r.provider, r.prompt_tokens, r.completion_tokens),
                    4,
                ),
                "timestamp": round(r.timestamp, 3),
            }
            for r in recents
        ]

    # ────────────────────────────────────────────────────────────────
    # 缓存
    # ────────────────────────────────────────────────────────────────

    def _cache_key(
        self, provider: str, messages: List[Dict], kwargs: Dict
    ) -> str:
        """生成缓存键: MD5(provider + messages + kwargs)"""
        raw = json.dumps({
            "p": provider,
            "m": messages,
            "k": {
                k: v for k, v in sorted(kwargs.items())
                if k not in ("stream",)
            },
        }, ensure_ascii=False, sort_keys=True)
        return hashlib.md5(raw.encode('utf-8')).hexdigest()

    def _cache_get(self, key: str) -> Optional[Any]:
        """从 LRU 缓存读取，自动淘汰过期条目"""
        if key not in self._cache:
            return None
        entry = self._cache[key]
        if time.time() - entry.timestamp > entry.ttl:
            del self._cache[key]
            return None
        self._cache.move_to_end(key)
        return entry.value

    def _cache_set(self, key: str, value: Any, ttl: Optional[float] = None):
        """写入 LRU 缓存"""
        if ttl is None:
            ttl = self._default_cache_ttl
        if len(self._cache) >= self._max_cache_size:
            self._cache.popitem(last=False)
        self._cache[key] = CacheEntry(
            value=value, timestamp=time.time(), ttl=ttl
        )

    def clear_cache(self):
        """清空所有缓存"""
        count = len(self._cache)
        self._cache.clear()
        logger.info(f"[AIEngine] 缓存已清空 ({count} 条)")

    # ────────────────────────────────────────────────────────────────
    # 核心: chat()
    # ────────────────────────────────────────────────────────────────

    def chat(
        self,
        provider: str,
        messages: List[Dict[str, str]],
        model: Optional[str] = None,
        stream: bool = False,
        use_cache: bool = True,
        retries: int = 2,
        **kwargs,
    ) -> Generator[str, None, None]:
        """调用指定 AI 提供者，自动重试 + 缓存。

        Args:
            provider:   提供者 ID ("deepseek", "doubao", "ollama", ...)
            messages:   消息列表 [{"role":"user","content":"..."}]
            model:      模型名（可选；不传则用 provider 默认模型）
            stream:     是否流式返回
            use_cache:  是否启用缓存（仅 stream=False 时生效）
            retries:    失败重试次数（指数退避: 1s/2s/4s）
            **kwargs:   透传给底层（temperature, max_tokens, top_p ...）

        Yields:
            字符串块（流式）或单个完整结果（非流式）
        """
        self._ensure_clients()

        # ── 熔断检查 ──
        if provider in self._circuit_open:
            if time.time() < self._circuit_open[provider]:
                remaining = int(self._circuit_open[provider] - time.time())
                yield f"错误: {provider} 已熔断，{remaining}s 后恢复"
                return
            del self._circuit_open[provider]

        # ── 缓存 ──
        if use_cache and not stream:
            cache_key = self._cache_key(provider, messages, kwargs)
            cached = self._cache_get(cache_key)
            if cached is not None:
                yield cached
                return
        else:
            cache_key = ""

        # ── Ollama 本地 ──
        if provider == "ollama":
            if not self._ollama_client:
                yield "错误: Ollama 客户端未初始化"
                return
            if not self._ollama_client.is_available():
                yield "错误: Ollama 服务不可用，请确认已安装并运行"
                return
            if not model:
                try:
                    available_models = self._ollama_client.list_models()
                except Exception:
                    yield "错误: 无法获取 Ollama 模型列表"
                    return
                if not available_models:
                    yield "错误: 未检测到本地 Ollama 模型"
                    return
                model = available_models[0].name

        # ── 云端 provider 前置检查 ──
        else:
            if not self._cloud_api:
                yield "错误: 云端 API 服务不可用"
                return
            if not self._cloud_api.get_provider(provider):
                yield f"错误: 提供者 {provider} 未配置或 API Key 缺失"
                return

        # ── 重试循环 ──
        last_error = ""
        for attempt in range(retries + 1):
            try:
                start_time = time.time()
                result_chunks: List[str] = []
                prompt_text = "".join(
                    m.get("content", "") for m in messages
                )
                prompt_tokens = self._estimate_tokens(prompt_text)

                # ═══ 实际调用 ═══
                if provider == "ollama":
                    gen = self._ollama_client.chat(
                        model, messages, stream=stream, **kwargs
                    )
                else:
                    gen = self._cloud_api.chat(
                        provider, messages, model=model,
                        stream=stream, **kwargs
                    )

                for chunk in gen:
                    if chunk.startswith("错误") or chunk.startswith("API 错误"):
                        raise RuntimeError(chunk)
                    result_chunks.append(chunk)
                    if stream:
                        yield chunk

                # ── 成功：记录统计 ──
                full_result = "".join(result_chunks)
                completion_tokens = self._estimate_tokens(full_result)
                cost = self._estimate_cost(
                    provider, prompt_tokens, completion_tokens
                )
                duration_ms = (time.time() - start_time) * 1000

                stats = self._stats.setdefault(provider, ProviderStats())
                stats.total_calls += 1
                stats.success_calls += 1
                stats.consecutive_failures = 0
                stats.total_tokens += prompt_tokens + completion_tokens
                stats.total_cost += cost

                self._call_history.append(AICallRecord(
                    provider=provider,
                    model=model or "default",
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    duration_ms=duration_ms,
                    success=True,
                ))
                if len(self._call_history) > self._max_history:
                    self._call_history = self._call_history[
                        -self._max_history:
                    ]

                logger.debug(
                    f"[AIEngine] ✓ {provider} "
                    f"({prompt_tokens}+{completion_tokens} tokens, "
                    f"¥{cost:.6f}, {duration_ms:.0f}ms)"
                )

                # 写入缓存
                if use_cache and not stream and cache_key:
                    self._cache_set(cache_key, full_result)

                if not stream:
                    yield full_result
                return

            except Exception as e:
                last_error = str(e)
                if attempt < retries:
                    wait = 2 ** attempt
                    logger.warning(
                        f"[AIEngine] ✗ {provider} 失败 "
                        f"(尝试 {attempt + 1}/{retries + 1}): "
                        f"{e[:100]}，{wait}s 后重试..."
                    )
                    time.sleep(wait)
                else:
                    self._on_failure(provider, last_error)
                    logger.error(
                        f"[AIEngine] ✗ {provider} 最终失败 "
                        f"({retries + 1} 次尝试): {last_error[:200]}"
                    )

        yield f"错误: {last_error[:200]}"

    # ────────────────────────────────────────────────────────────────
    # 智能降级: chat_with_fallback()
    # ────────────────────────────────────────────────────────────────

    def chat_with_fallback(
        self,
        messages: List[Dict[str, str]],
        providers: Optional[List[str]] = None,
        model: Optional[str] = None,
        stream: bool = False,
        use_cache: bool = True,
        template: Optional[Callable[[], str]] = None,
        **kwargs,
    ) -> Generator[str, None, None]:
        """多级降级调用：首选 → 备选 → Ollama → 模板。

        降级链: providers[0] → providers[1] → ... → ollama → template()

        Args:
            messages:   消息列表
            providers:  首选提供者列表 (默认取 _default_providers)
            model:      模型名
            stream:     是否流式返回
            use_cache:  是否使用缓存
            template:   全部失败时的回退回调，返回字符串
            **kwargs:   透传给底层调用

        Yields:
            内容字符串
        """
        self._ensure_clients()

        if providers is None:
            providers = list(self._default_providers)

        # 构建降级链（排除熔断/不可用的 provider）
        fallback_chain: List[str] = []
        seen: set = set()
        for p in providers:
            if p not in seen and self.is_provider_available(p):
                fallback_chain.append(p)
                seen.add(p)

        if "ollama" not in seen and self.is_provider_available("ollama"):
            fallback_chain.append("ollama")

        if not fallback_chain:
            if template:
                yield template()
            else:
                yield "错误: 没有可用的 AI 提供者"
            return

        # 缓存（以第一个 provider 为 key）
        if use_cache and not stream:
            cache_key = self._cache_key(fallback_chain[0], messages, kwargs)
            cached = self._cache_get(cache_key)
            if cached is not None:
                yield cached
                return
        else:
            cache_key = ""

        # 逐个尝试
        final_result = ""
        succeeded = False
        for provider in fallback_chain:
            logger.info(
                f"[AIEngine] 降级尝试: {provider} "
                f"({fallback_chain.index(provider) + 1}/{len(fallback_chain)})"
            )
            partial = ""
            failed = False
            for chunk in self.chat(
                provider, messages, model=model, stream=False,
                use_cache=False, retries=1, **kwargs
            ):
                if chunk.startswith("错误"):
                    failed = True
                    break
                partial += chunk

            if not failed and partial.strip():
                final_result = partial
                succeeded = True
                break

        if succeeded:
            if use_cache and not stream and cache_key:
                self._cache_set(cache_key, final_result)

            if stream:
                for ch in final_result:
                    yield ch
            else:
                yield final_result
        elif template:
            yield template()
        else:
            yield "错误: 所有 AI 提供者调用均失败"

    # ────────────────────────────────────────────────────────────────
    # 会话模式
    # ────────────────────────────────────────────────────────────────

    def session(self) -> 'AISession':
        """创建 AI 会话（上下文管理器，自动管理对话历史）"""
        return AISession(self)

    # ────────────────────────────────────────────────────────────────
    # 统计 & 诊断
    # ────────────────────────────────────────────────────────────────

    def get_stats(self) -> Dict[str, Dict]:
        """获取所有提供者的使用统计"""
        result: Dict[str, Dict] = {}
        for provider, stats in self._stats.items():
            result[provider] = {
                "total_calls": stats.total_calls,
                "success_calls": stats.success_calls,
                "failed_calls": stats.failed_calls,
                "success_rate": round(
                    stats.success_calls / max(stats.total_calls, 1) * 100, 1
                ),
                "total_tokens": stats.total_tokens,
                "total_cost_rmb": round(stats.total_cost, 4),
                "circuit_open": provider in self._circuit_open,
                "last_error": (
                    stats.last_error[:100] if stats.last_error else ""
                ),
            }
        return result

    def get_usage_summary(self) -> str:
        """获取可读的使用摘要"""
        stats = self.get_stats()
        if not stats:
            return "暂无 AI 调用记录"

        lines = ["═══ AI 调用统计 ═══"]
        total_cost = 0.0
        for provider, s in sorted(stats.items()):
            circuit = " [熔断]" if s['circuit_open'] else ""
            lines.append(
                f"  {provider:15s}  "
                f"调用:{s['total_calls']:>4d}  "
                f"成功率:{s['success_rate']:>5.1f}%  "
                f"Token:{s['total_tokens']:>8d}  "
                f"¥{s['total_cost_rmb']:.4f}{circuit}"
            )
            total_cost += s['total_cost_rmb']
        lines.append(f"  {'─' * 60}")
        lines.append(f"  累计费用: ¥{total_cost:.4f}")
        return "\n".join(lines)

    def set_pricing(
        self, provider: str, input_price: float, output_price: float
    ):
        """自定义 provider 定价 (元/百万token)"""
        self._pricing[provider] = (input_price, output_price)

    def reset_stats(self):
        """重置所有统计信息"""
        self._stats.clear()
        self._call_history.clear()
        self._circuit_open.clear()
        logger.info("[AIEngine] 统计已重置")

    def set_default_providers(self, providers: List[str]):
        """设置默认的 provider 优先级列表"""
        self._default_providers = list(providers)

    def configure(
        self,
        *,
        cache_ttl: Optional[float] = None,
        cache_size: Optional[int] = None,
        max_retries: Optional[int] = None,
        circuit_threshold: Optional[int] = None,
        circuit_timeout: Optional[float] = None,
    ):
        """全局配置调参"""
        if cache_ttl is not None:
            self._default_cache_ttl = cache_ttl
        if cache_size is not None:
            self._max_cache_size = cache_size
        if circuit_threshold is not None:
            self._circuit_breaker_threshold = circuit_threshold
        if circuit_timeout is not None:
            self._circuit_breaker_timeout = circuit_timeout
        logger.info(f"[AIEngine] 配置已更新: cache_ttl={cache_ttl}, ...")


# ============================================================================
# 会话
# ============================================================================

class AISession:
    """AI 会话 — 自动管理对话历史

    用例:
        with ai_engine.session() as s:
            s.chat(user_message="你好，帮我起个标题")
            s.chat(user_message="换一种风格")
            print(s.history)  # 查看完整对话
    """

    def __init__(self, engine: AIEngine):
        self._engine = engine
        self._history: List[Dict[str, str]] = []
        self._provider: Optional[str] = None

    def __enter__(self) -> 'AISession':
        return self

    def __exit__(self, *args):
        self._history.clear()

    def chat(
        self,
        provider: Optional[str] = None,
        messages: Optional[List[Dict[str, str]]] = None,
        user_message: Optional[str] = None,
        system_prompt: Optional[str] = None,
        **kwargs,
    ) -> Generator[str, None, None]:
        """会话内聊天，自动追加对话历史。

        三种调用方式:
          1) s.chat("deepseek", messages=[...])
          2) s.chat(user_message="你好")
          3) s.chat("deepseek", user_message="继续")
        """
        if messages is None:
            if user_message:
                self._history.append({
                    "role": "user", "content": user_message
                })
                default_system = (
                    system_prompt
                    or "你是一个专业的视频创作助手。"
                )
                messages = [
                    {"role": "system", "content": default_system}
                ] + list(self._history)
            else:
                yield "错误: 请提供 messages 或 user_message"
                return
        else:
            self._history = list(messages)

        if provider is None:
            provider = self._provider

        full = ""
        for chunk in self._engine.chat(
            provider or "deepseek", messages, **kwargs
        ):
            if not chunk.startswith("错误"):
                full += chunk
            yield chunk

        if full and not full.startswith("错误"):
            self._history.append({"role": "assistant", "content": full})

    def clear_history(self):
        """清空对话历史"""
        self._history.clear()

    @property
    def history(self) -> List[Dict[str, str]]:
        """返回当前对话历史的副本"""
        return list(self._history)


# ============================================================================
# AI 生成类型枚举
# ============================================================================

class AIGenerateType(Enum):
    """AI 生成类型"""
    TEXT = "text"
    IMAGE = "image"
    VIDEO = "video"
    AUDIO = "audio"
    SPEECH = "speech"


# ============================================================================
# AI 工具适配器接口
# ============================================================================

class AIToolAdapter:
    """AI 工具适配器基类 - 统一适配不同类型的 AI 能力"""

    def get_type(self) -> str:
        """返回适配器类型"""
        raise NotImplementedError

    def is_available(self) -> bool:
        """检查是否可用"""
        return False

    def generate(self, **kwargs) -> Generator[Any, None, None]:
        """执行生成操作"""
        raise NotImplementedError


class ImageGenerationAdapter(AIToolAdapter):
    """图像生成适配器"""

    def get_type(self) -> str:
        return "image"

    def generate(
        self,
        prompt: str,
        negative_prompt: str = "",
        width: int = 1024,
        height: int = 1024,
        model: str = "",
        **kwargs,
    ) -> Generator[Any, None, None]:
        """生成图像"""
        raise NotImplementedError


class VideoGenerationAdapter(AIToolAdapter):
    """视频生成适配器"""

    def get_type(self) -> str:
        return "video"

    def generate(
        self,
        prompt: str,
        negative_prompt: str = "",
        duration: float = 10.0,
        width: int = 1024,
        height: int = 576,
        fps: int = 24,
        model: str = "",
        **kwargs,
    ) -> Generator[Any, None, None]:
        """生成视频"""
        raise NotImplementedError


class SpeechGenerationAdapter(AIToolAdapter):
    """语音生成适配器"""

    def get_type(self) -> str:
        return "speech"

    def generate(
        self,
        text: str,
        voice: str = "",
        language: str = "zh",
        rate: float = 1.0,
        volume: float = 1.0,
        **kwargs,
    ) -> Generator[Any, None, None]:
        """生成语音"""
        raise NotImplementedError


# ============================================================================
# AI 引擎增强 - 统一多模态生成接口
# ============================================================================

class AIEngineEnhanced(AIEngine):
    """增强版 AI 引擎 (v2.0)
    参考马上短剧 ai_engine 模式，统一 LLM/图像/视频/音频适配层

    核心改进：
    - 统一多模态生成接口
    - AI 工具适配器注册机制
    - 异步调用支持
    - 任务追踪与回调
    """

    def __init__(self):
        super().__init__()
        self._adapters: Dict[str, List[AIToolAdapter]] = {}
        self._task_callbacks: Dict[str, Dict[str, Callable]] = {}
        self._init_default_adapters()

    def _init_default_adapters(self):
        """初始化默认 AI 工具适配器"""
        try:
            from app.core.voice_generator import AIVoiceGenerator, VoiceGenerator
            _TTS = VoiceGenerator if VoiceGenerator is not None else AIVoiceGenerator

            class TTSAdapter(SpeechGenerationAdapter):
                def __init__(self):
                    self._tts = _TTS()

                def is_available(self) -> bool:
                    return hasattr(self._tts, "generate_audio")

                def generate(self, text: str, voice: str = "", language: str = "zh",
                            rate: float = 1.0, volume: float = 1.0, **kwargs):
                    output_path = kwargs.get("output_path", "")
                    result = self._tts.generate_audio(
                        text,
                        output_path=output_path,
                        voice_profile_id=voice,
                        language=language,
                        rate=rate,
                        volume=volume,
                    )
                    if result.get("success"):
                        yield {"success": True, "audio_path": result.get("audio_path", "")}
                    else:
                        yield {"success": False, "error": result.get("error", "TTS 生成失败")}

            self.register_adapter(TTSAdapter())
        except Exception as e:
            logger.debug(f"[AIEngineEnhanced] TTS 适配器初始化失败: {e}")

        try:
            from app.core.ai_enhanced import AIEnhanced
            class ImageAdapter(ImageGenerationAdapter):
                def __init__(self):
                    self._ai_enhanced = AIEnhanced()

                def is_available(self) -> bool:
                    return True

                def generate(self, prompt: str, negative_prompt: str = "",
                            width: int = 1024, height: int = 1024,
                            model: str = "", **kwargs):
                    result = self._ai_enhanced.generate_content(
                        "image", prompt, negative_prompt=negative_prompt
                    )
                    if result.get("success"):
                        yield {"success": True, "image_path": result.get("output_path", "")}
                    else:
                        yield {"success": False, "error": result.get("error", "图像生成失败")}

            self.register_adapter(ImageAdapter())
        except Exception as e:
            logger.debug(f"[AIEngineEnhanced] 图像适配器初始化失败: {e}")

    def register_adapter(self, adapter: AIToolAdapter):
        """注册 AI 工具适配器"""
        adapter_type = adapter.get_type()
        if adapter_type not in self._adapters:
            self._adapters[adapter_type] = []
        self._adapters[adapter_type].append(adapter)
        logger.info(f"[AIEngineEnhanced] 已注册适配器: {adapter_type}")

    def unregister_adapter(self, adapter_type: str, index: int = 0):
        """注销指定类型的适配器"""
        if adapter_type in self._adapters and index < len(self._adapters[adapter_type]):
            removed = self._adapters[adapter_type].pop(index)
            logger.info(f"[AIEngineEnhanced] 已注销适配器: {adapter_type}")
            return removed
        return None

    def get_available_adapters(self, adapter_type: str) -> List[AIToolAdapter]:
        """获取指定类型的可用适配器"""
        return [a for a in self._adapters.get(adapter_type, []) if a.is_available()]

    def generate_image(
        self,
        prompt: str,
        negative_prompt: str = "",
        width: int = 1024,
        height: int = 1024,
        model: str = "",
        provider: str = "",
        **kwargs,
    ) -> Generator[Dict[str, Any], None, None]:
        """统一图像生成接口"""
        adapters = self.get_available_adapters("image")
        if not adapters:
            yield {"success": False, "error": "没有可用的图像生成适配器"}
            return

        for adapter in adapters:
            try:
                for result in adapter.generate(
                    prompt=prompt,
                    negative_prompt=negative_prompt,
                    width=width,
                    height=height,
                    model=model,
                    **kwargs,
                ):
                    if isinstance(result, dict) and result.get("success"):
                        yield result
                        return
                    elif isinstance(result, dict):
                        logger.debug(f"[AIEngineEnhanced] 图像生成失败: {result.get('error')}")
            except Exception as e:
                logger.warning(f"[AIEngineEnhanced] 图像生成错误: {e}")

        yield {"success": False, "error": "所有图像生成适配器调用均失败"}

    def generate_video(
        self,
        prompt: str,
        negative_prompt: str = "",
        duration: float = 10.0,
        width: int = 1024,
        height: int = 576,
        fps: int = 24,
        model: str = "",
        provider: str = "",
        **kwargs,
    ) -> Generator[Dict[str, Any], None, None]:
        """统一视频生成接口"""
        adapters = self.get_available_adapters("video")
        if not adapters:
            yield {"success": False, "error": "没有可用的视频生成适配器"}
            return

        for adapter in adapters:
            try:
                for result in adapter.generate(
                    prompt=prompt,
                    negative_prompt=negative_prompt,
                    duration=duration,
                    width=width,
                    height=height,
                    fps=fps,
                    model=model,
                    **kwargs,
                ):
                    if isinstance(result, dict) and result.get("success"):
                        yield result
                        return
                    elif isinstance(result, dict):
                        logger.debug(f"[AIEngineEnhanced] 视频生成失败: {result.get('error')}")
            except Exception as e:
                logger.warning(f"[AIEngineEnhanced] 视频生成错误: {e}")

        yield {"success": False, "error": "所有视频生成适配器调用均失败"}

    def generate_speech(
        self,
        text: str,
        voice: str = "",
        language: str = "zh",
        rate: float = 1.0,
        volume: float = 1.0,
        output_path: str = "",
        **kwargs,
    ) -> Generator[Dict[str, Any], None, None]:
        """统一语音生成接口"""
        adapters = self.get_available_adapters("speech")
        if not adapters:
            yield {"success": False, "error": "没有可用的语音生成适配器"}
            return

        for adapter in adapters:
            try:
                for result in adapter.generate(
                    text=text,
                    voice=voice,
                    language=language,
                    rate=rate,
                    volume=volume,
                    output_path=output_path,
                    **kwargs,
                ):
                    if isinstance(result, dict) and result.get("success"):
                        yield result
                        return
                    elif isinstance(result, dict):
                        logger.debug(f"[AIEngineEnhanced] 语音生成失败: {result.get('error')}")
            except Exception as e:
                logger.warning(f"[AIEngineEnhanced] 语音生成错误: {e}")

        yield {"success": False, "error": "所有语音生成适配器调用均失败"}

    def generate_audio(
        self,
        prompt: str,
        duration: float = 5.0,
        model: str = "",
        **kwargs,
    ) -> Generator[Dict[str, Any], None, None]:
        """统一音频生成接口（背景音乐等）"""
        yield {"success": False, "error": "音频生成适配器尚未实现"}

    def add_task_callback(self, task_id: str, callback_type: str, callback: Callable):
        """添加任务回调（进度/完成/失败）"""
        if task_id not in self._task_callbacks:
            self._task_callbacks[task_id] = {}
        self._task_callbacks[task_id][callback_type] = callback

    def remove_task_callback(self, task_id: str, callback_type: str = ""):
        """移除任务回调"""
        if task_id in self._task_callbacks:
            if callback_type:
                self._task_callbacks[task_id].pop(callback_type, None)
            else:
                del self._task_callbacks[task_id]

    def _notify_callback(self, task_id: str, callback_type: str, **kwargs):
        """触发任务回调"""
        if task_id in self._task_callbacks and callback_type in self._task_callbacks[task_id]:
            try:
                self._task_callbacks[task_id][callback_type](**kwargs)
            except Exception as e:
                logger.warning(f"[AIEngineEnhanced] 回调执行失败: {e}")

    def generate_async(
        self,
        generate_type: str,
        callback: Callable = None,
        **kwargs,
    ) -> str:
        """异步生成任务"""
        task_id = f"{generate_type}_{int(time.time() * 1000)}"

        def _run():
            results = []
            try:
                if generate_type == "image":
                    gen = self.generate_image(**kwargs)
                elif generate_type == "video":
                    gen = self.generate_video(**kwargs)
                elif generate_type == "speech":
                    gen = self.generate_speech(**kwargs)
                elif generate_type == "audio":
                    gen = self.generate_audio(**kwargs)
                else:
                    gen = iter([{"success": False, "error": "未知生成类型"}])

                for result in gen:
                    results.append(result)
            except Exception as e:
                results.append({"success": False, "error": str(e)})

            if callback:
                try:
                    callback(results[-1] if results else {"success": False, "error": "无结果"})
                except Exception as e:
                    logger.warning(f"[AIEngineEnhanced] 异步回调失败: {e}")

        import threading
        t = threading.Thread(target=_run, daemon=True)
        t.start()

        return task_id

    def get_adapter_info(self) -> Dict[str, Any]:
        """获取所有适配器信息"""
        info = {}
        for adapter_type, adapters in self._adapters.items():
            info[adapter_type] = {
                "count": len(adapters),
                "available": len([a for a in adapters if a.is_available()]),
                "types": [type(a).__name__ for a in adapters],
            }
        return info


# ============================================================================
# 全局单例
# ============================================================================

ai_engine = AIEngineEnhanced()
