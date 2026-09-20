"""额度池调度（P0-1）
==========================================
问题（对照鲸影学到的）：`VideoGenerationClient` 此前**一次调用 = 一次赌**——
没有任何账号/配额/健康概念，撞上死号整段失败，只能落 ffmpeg 占位片。

本模块给生成链路加**多账号额度池**：

    账号条目 = {
        "account_id":  "seedance_free_01",
        "provider":    "seedance",
        "credential":  "key 引用名（不存明文）",
        "daily_quota": 100,          # 每日配额
        "used_today":  12,           # 今日已用（跨天自动清零）
        "quality_tier": 0,           # 0=免费档 1=低价 2=高价（越大越贵越稳）
        "health":      "ok",         # ok / cooling
        "cooldown_until": 0.0,       # 退避截止时间戳
        "consecutive_failures": 0,
        "last_used_at": 0.0,
    }

选路顺序（同 provider 内）：
    ① quality_tier 降序（免费档参与轮换，但不优先）
    ② daily_quota > used_today（配额未耗尽）
    ③ last_used_at 升序（最久未用优先，均衡消耗）

失败处理：
    * 指数退避：60s 起 → 120 → 240 … 封顶 30min；
    * 当场换号：``pick_next_after_failure()`` = 标记 cooling → 立刻取下一个健康号。

设计纪律：
  - **纯逻辑、不 import app 包**（同 guard_base / provider_caps，便于单测）；
  - 持久化 ``~/.shiguang/accounts.json``：**0600 权限 + 原子写**（临时文件 + os.replace）；
  - credential 只存**引用名**（如 "seedance_free_01"），明文 Key 由未来接入的真实
    provider 客户端自行从环境变量/密钥库解析——池子只管选路与记账，不碰密钥；
  - 每次选号/淘汰都写**审计日志**（logger + 内存环形缓冲，可查「为什么选它」）；
  - 池子为空（未配置任何账号）时一切方法**诚实降级为透传**，不改变现有行为。
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
import threading
import time
import uuid
from collections import deque
from typing import Any, Deque, Dict, List, Optional

logger = logging.getLogger("AI短剧编辑器.core.ai.provider_pool")

# 持久化路径（与项目 ~/.shiguang 约定一致）
DEFAULT_STORE = ("~", ".shiguang", "accounts.json")

# 指数退避：60s 起，封顶 30min
BACKOFF_BASE = 60.0
BACKOFF_CAP = 1800.0

# 内存审计环形缓冲条数
MAX_AUDIT = 50


def _mask(credential: str) -> str:
    """凭证引用名脱敏（接口只回掩码，不回原文）。"""
    s = str(credential or "")
    if len(s) <= 4:
        return "*" * len(s)
    return s[:2] + "***" + s[-2:]


class ProviderPool:
    """多账号额度池（线程安全；懒加载持久化）。"""

    def __init__(self, store_path: str = ""):
        self._lock = threading.RLock()
        self._store = store_path or os.path.join(
            os.path.expanduser(DEFAULT_STORE[0]), *DEFAULT_STORE[1:])
        self._accounts: List[Dict[str, Any]] = []
        self._loaded = False
        self._audit: Deque[Dict[str, Any]] = deque(maxlen=MAX_AUDIT)
        # provider → 本轮已选中的账号（report_* 的记账目标）
        self._last_pick: Dict[str, Dict[str, Any]] = {}

    # ══════════════════════════════════════════
    # 持久化（0600 + 原子写）
    # ══════════════════════════════════════════

    def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        with self._lock:
            if self._loaded:
                return
            try:
                with open(self._store, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, list):
                    self._accounts = [a for a in data if isinstance(a, dict)]
            except FileNotFoundError:
                self._accounts = []
            except (OSError, ValueError):
                logger.warning("[provider_pool] 账号池文件损坏，按空池启动（%s）",
                               self._store, exc_info=True)
                self._accounts = []
            self._loaded = True

    def _save_locked(self) -> None:
        """原子写（调用方须已持锁）。失败只记日志——记账丢失可接受，别阻断生成。"""
        try:
            d = os.path.dirname(self._store) or "."
            os.makedirs(d, exist_ok=True)
            fd, tmp = tempfile.mkstemp(prefix="accounts_", suffix=".tmp", dir=d)
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    json.dump(self._accounts, f, ensure_ascii=False, indent=2)
                os.chmod(tmp, 0o600)  # Windows 下近似 no-op，尽力而为
                os.replace(tmp, self._store)  # 原子替换
            finally:
                if os.path.exists(tmp):
                    try:
                        os.remove(tmp)
                    except OSError:
                        pass
        except OSError:
            logger.warning("[provider_pool] 账号池写盘失败", exc_info=True)

    # ══════════════════════════════════════════
    # 账号管理
    # ══════════════════════════════════════════

    def add_account(self, provider: str, *, credential: str = "",
                    daily_quota: int = 100, quality_tier: int = 0,
                    account_id: str = "") -> Dict[str, Any]:
        """添加账号（credential 传引用名即可，池子不存明文 Key）。"""
        now = time.time()
        account = {
            "account_id": account_id or f"{provider}_{uuid.uuid4().hex[:6]}",
            "provider": str(provider or ""),
            "credential": str(credential or ""),
            "daily_quota": max(1, int(daily_quota)),
            "used_today": 0,
            "used_date": time.strftime("%Y-%m-%d", time.localtime(now)),
            "quality_tier": max(0, int(quality_tier)),
            "health": "ok",
            "cooldown_until": 0.0,
            "consecutive_failures": 0,
            "last_used_at": 0.0,
            "created_at": now,
        }
        with self._lock:
            self._ensure_loaded()
            self._accounts.append(account)
            self._save_locked()
        self._audit_log("add", account["account_id"], f"配额{daily_quota}/tier{quality_tier}")
        return account

    def remove_account(self, account_id: str) -> bool:
        with self._lock:
            self._ensure_loaded()
            before = len(self._accounts)
            self._accounts = [a for a in self._accounts
                              if a.get("account_id") != account_id]
            removed = len(self._accounts) < before
            if removed:
                self._save_locked()
                self._last_pick.pop(account_id, None)
        if removed:
            self._audit_log("remove", account_id, "")
        return removed

    def list_accounts(self, provider: str = "") -> List[Dict[str, Any]]:
        """列出账号（credential 一律掩码）。"""
        with self._lock:
            self._ensure_loaded()
            rows = []
            for a in self._accounts:
                if provider and a.get("provider") != provider:
                    continue
                rows.append({**a, "credential": _mask(str(a.get("credential") or ""))})
            return rows

    def count(self, provider: str = "") -> int:
        with self._lock:
            self._ensure_loaded()
            if not provider:
                return len(self._accounts)
            return sum(1 for a in self._accounts if a.get("provider") == provider)

    # ══════════════════════════════════════════
    # 选路
    # ══════════════════════════════════════════

    @staticmethod
    def _rollover(account: Dict[str, Any], today: str) -> None:
        """跨天自动清零当日用量。"""
        if account.get("used_date") != today:
            account["used_date"] = today
            account["used_today"] = 0

    @staticmethod
    def _healthy(account: Dict[str, Any], now: float) -> bool:
        """健康 = 未在退避期 + 当日配额未耗尽（退避到期自动恢复 ok）。"""
        if float(account.get("cooldown_until") or 0.0) > now:
            return False
        if account.get("health") == "cooling":
            account["health"] = "ok"   # 退避期已过，恢复
            account["consecutive_failures"] = 0
        if int(account.get("used_today") or 0) >= int(account.get("daily_quota") or 1):
            return False
        return True

    def pick(self, provider: str, *, now: Optional[float] = None,
             remember: bool = True) -> Optional[Dict[str, Any]]:
        """选一个账号：tier 降序 → 配额未耗尽 → 最久未用优先。

        返回**内部引用**（记账用），对外展示请走 ``list_accounts()``（掩码）。
        没有健康账号时返回 None（诚实降级，不抛错）。
        ``remember=False`` 供**报价 / 预演**用 —— 不占用 ``_last_pick`` 记账位，
        避免并发生成时的成功/失败被记到报价预演的账号上。
        """
        ts = float(now if now is not None else time.time())
        today = time.strftime("%Y-%m-%d", time.localtime(ts))
        with self._lock:
            self._ensure_loaded()
            candidates = [a for a in self._accounts if a.get("provider") == provider]
            for a in candidates:
                self._rollover(a, today)
            healthy = [a for a in candidates if self._healthy(a, ts)]
            if not healthy:
                if candidates:
                    self._audit_log("pick_miss", provider, "无健康账号（退避中/配额尽）")
                return None
            healthy.sort(key=lambda a: (
                -int(a.get("quality_tier") or 0),           # ① tier 降序
                float(a.get("last_used_at") or 0.0),        # ③ 最久未用优先
            ))
            best = healthy[0]
            if remember:
                self._last_pick[provider] = best
            quota_left = int(best.get("daily_quota") or 0) - int(best.get("used_today") or 0)
            self._audit_log(
                "pick", provider,
                f"选中 {best.get('account_id')}：tier={best.get('quality_tier')}"
                f"，配额余{quota_left}，最久未用={not best.get('last_used_at')}")
            return best

    def reorder_providers(self, order: List[str], *,
                          now: Optional[float] = None,
                          remember: bool = True) -> List[str]:
        """按额度池重排 provider 顺序（与 provider_caps 组合用）。

        规则：**有健康账号的 provider 排前面**（按其最优账号的 tier 降序），
        没有账号的保持原有相对顺序跟在后面；``local`` 永远最后（终端兜底）。
        顺带为每个有账号的 provider 记住本轮选中账号（report_* 的记账目标；
        ``remember=False`` 时只排序不记账 —— 供报价用）。
        """
        if not order:
            return list(order)
        with self._lock:
            rest = [p for p in order if p != "local"]
            with_acct: List[tuple] = []   # (best_tier, idx, provider)
            without: List[str] = []
            for i, p in enumerate(rest):
                acct = self.pick(p, now=now, remember=remember)
                if acct is not None:
                    with_acct.append((-int(acct.get("quality_tier") or 0), i, p))
                else:
                    without.append(p)
            with_acct.sort()
            result = [p for _, _, p in with_acct] + without
            if "local" in order:
                result.append("local")
            return result

    def resolve_order(self, provider: str = "auto",
                      spec: Optional[Dict[str, Any]] = None,
                      *, remember: bool = True) -> List[str]:
        """组合入口：能力声明筛选（P0-3）→ 额度池重排（P0-1）。

        ``provider_caps`` 不可用时降级为只做池内重排。
        ``remember=False`` 供报价 / 预演（不动记账位）。
        """
        try:
            from .provider_caps import resolve_order as caps_resolve

            order = caps_resolve(provider, spec=spec)
        except Exception:
            logger.debug("[provider_pool] 能力路由不可用，仅做池内重排", exc_info=True)
            order = [provider, "local"] if provider and provider != "auto" \
                else ["seedance", "cogvideo", "local"]
        return self.reorder_providers(order, remember=remember)

    def quote(self, provider: str = "auto", *, count: int = 1,
              spec: Optional[Dict[str, Any]] = None,
              now: Optional[float] = None) -> Dict[str, Any]:
        """**报价 + 账号可用性**（P1-1）：谁会接单 / 花多少 / 配额够不够。

        语义与真实生成一致：能力筛选 → 池内重排（有健康账号的排前）→ 取首选；
        **零额度 / 退避中的死号直接跳过**（与 reorder_providers 同一套规则）。
        只读预演（``remember=False``），不动记账位、不消耗配额。

        Returns::
            {"ok", "provider", "account_id", "tier", "price_per_clip", "count",
             "cost_estimate", "currency", "quota_remaining", "cloud_available",
             "dead_providers": [有号但全不健康的渠道], "reason", "note"}
        """
        ts = float(now if now is not None else time.time())
        n = max(1, int(count or 1))
        # ① 能力声明链 + 单价
        try:
            from .provider_caps import quote as caps_quote, resolve_order as caps_resolve

            chain = [p for p in caps_resolve(provider, spec=spec) if p != "local"]
            base = caps_quote(provider, count=n, spec=spec)
        except Exception:
            logger.debug("[provider_pool] 声明报价不可用，按 local 报", exc_info=True)
            chain, base = [], {"price_per_clip": 0.0}

        # ② 池内预演：有健康账号的优先，死号跳过（不 remember、不记账）
        chosen, chosen_acct = "", None
        dead: List[str] = []
        with_acct: List[Dict[str, Any]] = []
        without_acct: List[str] = []
        for p in chain:
            acct = self.pick(p, now=ts, remember=False)
            if acct is not None:
                with_acct.append((p, acct))
            elif self.count(p) > 0:
                dead.append(p)   # 有账号但全在退避/配额尽 → 死号，跳过
            else:
                without_acct.append(p)  # 没配账号（可能走环境变量 Key，仍可用）
        if with_acct:
            chosen, chosen_acct = with_acct[0]
        elif without_acct:
            chosen = without_acct[0]
        else:
            chosen = "local"

        # ③ 组装报价
        price = float(base.get("price_per_clip") or 0.0)
        if chosen != (base.get("provider") or ""):
            # 池把首选换了（如声明首选是死号）→ 按实际接单渠道的单价重算
            try:
                from .provider_caps import quote as caps_quote

                price = float((caps_quote(chosen, count=n, spec=spec)
                               .get("price_per_clip")) or 0.0)
            except Exception:
                price = 0.0
        quota_left = 0
        tier = 0
        account_id = ""
        if chosen_acct is not None:
            quota_left = (int(chosen_acct.get("daily_quota") or 0)
                          - int(chosen_acct.get("used_today") or 0))
            tier = int(chosen_acct.get("quality_tier") or 0)
            account_id = str(chosen_acct.get("account_id") or "")
        reason = ""
        if chosen == "local":
            if provider and provider != "auto":
                reason = "指定渠道不可用（死号/能力不符/未配置），将回退本地占位"
            elif dead:
                reason = f"云端全死号（{','.join(dead)}），将回退本地占位"
            else:
                reason = "未配置云端渠道，本地占位生成"
        return {
            "ok": True,   # 报价本身总是成功（local 恒可兜底）
            "provider": chosen,
            "account_id": account_id,
            "tier": tier,
            "price_per_clip": price,
            "count": n,
            "cost_estimate": round(price * n, 2),
            "currency": "CNY",
            "quota_remaining": quota_left,
            "cloud_available": chosen != "local",
            "dead_providers": dead,
            "reason": reason,
            "note": "估算值（声明单价×段数）；实际以渠道账单为准",
        }

    # ══════════════════════════════════════════
    # 记账
    # ══════════════════════════════════════════

    def _account_for_report(self, provider: str) -> Optional[Dict[str, Any]]:
        """取该 provider 本轮选中的账号（pick 时记下）；没有则返回 None（纯审计）。"""
        acct = self._last_pick.get(provider)
        if acct is not None and acct in self._accounts:
            return acct
        return None

    def report_success(self, provider: str, *, segments: int = 1,
                       now: Optional[float] = None) -> None:
        """成功：清失败计数 / 恢复健康 / 记用量。无账号则只写审计。"""
        ts = float(now if now is not None else time.time())
        today = time.strftime("%Y-%m-%d", time.localtime(ts))
        with self._lock:
            self._ensure_loaded()
            acct = self._account_for_report(provider)
            if acct is not None:
                self._rollover(acct, today)
                acct["used_today"] = int(acct.get("used_today") or 0) + max(1, int(segments))
                acct["consecutive_failures"] = 0
                acct["health"] = "ok"
                acct["cooldown_until"] = 0.0
                acct["last_used_at"] = ts
                self._save_locked()
                self._audit_log("success", provider,
                                f"{acct.get('account_id')} +{segments} 段")
            else:
                self._audit_log("success", provider, "（无账号，仅审计）")

    def report_failure(self, provider: str, *, error: str = "",
                       now: Optional[float] = None) -> None:
        """失败：指数退避（60s→…→30min 封顶）+ 标记 cooling。无账号则只写审计。"""
        ts = float(now if now is not None else time.time())
        with self._lock:
            self._ensure_loaded()
            acct = self._account_for_report(provider)
            if acct is not None:
                fails = int(acct.get("consecutive_failures") or 0) + 1
                backoff = min(BACKOFF_BASE * (2 ** (fails - 1)), BACKOFF_CAP)
                acct["consecutive_failures"] = fails
                acct["health"] = "cooling"
                acct["cooldown_until"] = ts + backoff
                self._save_locked()
                self._audit_log(
                    "failure", provider,
                    f"{acct.get('account_id')} 第{fails}次失败，退避{backoff:.0f}s"
                    f"（{error[:60]}）")
            else:
                self._audit_log("failure", provider, f"（无账号）{error[:60]}")

    def pick_next_after_failure(self, provider: str, *, error: str = "",
                                now: Optional[float] = None) -> Optional[Dict[str, Any]]:
        """**当场换号**：标记失败 → 立刻取下一个健康号重提。"""
        self.report_failure(provider, error=error, now=now)
        return self.pick(provider, now=now)

    # ══════════════════════════════════════════
    # 健康 / 审计
    # ══════════════════════════════════════════

    def health(self, provider: str, *, now: Optional[float] = None) -> Dict[str, Any]:
        """渠道健康概况（供 UI 健康灯）。"""
        ts = float(now if now is not None else time.time())
        today = time.strftime("%Y-%m-%d", time.localtime(ts))
        with self._lock:
            self._ensure_loaded()
            accounts = [a for a in self._accounts if a.get("provider") == provider]
            for a in accounts:
                self._rollover(a, today)
            healthy = sum(1 for a in accounts if self._healthy(a, ts))
            quota_left = sum(
                max(0, int(a.get("daily_quota") or 0) - int(a.get("used_today") or 0))
                for a in accounts)
            return {
                "ok": healthy > 0,
                "accounts": len(accounts),
                "healthy": healthy,
                "quota_remaining": quota_left,
            }

    def _audit_log(self, event: str, provider: str, reason: str) -> None:
        entry = {"time": time.time(), "event": event,
                 "provider": provider, "reason": reason}
        self._audit.append(entry)
        logger.info("[provider_pool] %s %s：%s", event, provider, reason)

    def audit(self, limit: int = 20) -> List[Dict[str, Any]]:
        """最近 N 条选号/记账审计（新→旧）。"""
        with self._lock:
            return list(self._audit)[-limit:][::-1]


# ═══════════════════════════════════════════════════════════
# 模块级单例（懒加载，避免 import 时读盘）
# ═══════════════════════════════════════════════════════════

_pool_instance: Optional[ProviderPool] = None
_pool_lock = threading.Lock()


def get_pool() -> ProviderPool:
    """全局额度池单例（路径固定 ~/.shiguang/accounts.json）。"""
    global _pool_instance
    if _pool_instance is None:
        with _pool_lock:
            if _pool_instance is None:
                _pool_instance = ProviderPool()
    return _pool_instance


def reset_pool_for_test(store_path: str) -> ProviderPool:
    """测试专用：独立路径的新池子（不污染全局单例）。"""
    return ProviderPool(store_path=store_path)
