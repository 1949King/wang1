"""AI 辅助人工抽检子系统（规格书第十四篇 §70-76，V4.38.2 切片⑨）
====================================================================
子系统定位（§70，一句话）：**AI 负责大批量抽样、预审、预标注；人工保留
真值裁定、边界案例校准、一票否决权**。AI 打分永远不能直接作为真值用于
闭环更新——只有人工确认后的样本，才允许校正评分权重与质量先验库。

流水线（§73）：
    单元完成 → 机器打分记录特征 → 【抽样器】P_sample 判定 →
    【预审】规则检查+风险等级 → 人工复核（AI 预填表单）→ 真值标签 →
    残差入库 → 校正先验 → 残差超标 → 冻结闭环 + 告警

落地映射（桌面单机版，诚实边界）：
  1. **自适应分层抽样**（§71.1）：P = clamp(p_base×(1+α_r·r̂+α_d·Δ̂), p_min, 1)；
     新模型版本 / 新题材强制必检；用 unit_id 哈希做**确定性抽样**
     （同单元永远同决定，可复现可审计）。
  2. **规则预审**（§71.2）：确定性规则优先（无模型、零成本）——缺失文件 /
     时长异常 / 体积异常 / Schema 缺字段 / 空文本。输出 低/中/高 风险 +
     uncertain 标记（识别不了就上交，不硬判）。
  3. **预标注表单**（§71.3）：机器分 / 预测 / 分歧度 / 执行模式 / 模型版本
     一次填好，人工只需判 合格/不合格/存疑。
  4. **漂移监控**（§71.4 + §29）：残差 |y−ŷ| 的 EMA 均值/方差；
     均值 >0.15 → 告警（权重校正位）；**>0.30 → 冻结闭环**（机器观测
     不再写先验库），仅人工标签可解冻。
  5. **重复样本过滤**（§71.5）：归一化 prompt 签名 24h 内重复 → 不入池。
  6. **红线**（§72/§76）：``submit_ai_score`` 只记风险、**永不写先验**；
     先验写入只走 ``submit_human_label``。

设计纪律：纯模块、不 import app 包、RLock、JSON 原子写、异常不抛。
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import tempfile
import threading
import time
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger("AI短剧编辑器.core.ai.sampling_review")

# ── 抽样参数（§71.1） ──
_P_BASE = 0.02            # 基础抽样概率（普通样本低采样率）
_P_MIN = 0.005            # 抽样概率下限（永不完全停检）
_ALPHA_R = 4.0            # 预测残差放大系数
_ALPHA_D = 2.0            # 分歧度放大系数
_DEDUP_WINDOW = 86400.0   # 重复样本过滤窗口（24h，§71.5）
# ── 漂移门限（§29/§71.4） ──
_DRIFT_WARN = 0.15        # 残差均值 >0.15 → 告警（自动权重校正位）
_DRIFT_FREEZE = 0.30      # 残差均值 >0.30 → 冻结闭环、切静态降级
_MIN_SAMPLES_FOR_DRIFT = 5   # 漂移判定最小样本数（防小样本误冻结）
# ── 残差 EMA ──
_ALPHA = 0.3

_DEFAULT_STORE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__))))),
    "data", "sampling_review.json")

# 测试隔离：SAMPLING_REVIEW_STORE_PATH 存在时优先使用（缺省仍是 data/sampling_review.json）。
# 与 draw_book / quality_prior / budget_pacer 同款纪律：测试不得写入正式账本。
_STORE_ENV = "SAMPLING_REVIEW_STORE_PATH"


def _resolve_store_path() -> str:
    """解析账本路径：环境变量 > 默认（data/sampling_review.json）。"""
    env = os.environ.get(_STORE_ENV)
    return env.strip() if env and env.strip() else _DEFAULT_STORE


def _stable_hash(text: str) -> float:
    """unit_id → [0,1) 确定性哈希（抽样可复现的关键）。"""
    h = hashlib.md5(text.encode("utf-8", errors="replace")).hexdigest()
    return int(h[:12], 16) / float(0xFFFFFFFFFFFF)


class SamplingReview:
    """AI 辅助抽检：抽样 → 预审 → 表单 → 真值 → 漂移 → 冻结/解冻。"""

    def __init__(self, store_path: str = "",
                 prior_writer: Optional[Callable[[str, float], None]] = None):
        self._path = store_path or _resolve_store_path()
        self._lock = threading.RLock()
        self._loaded = False
        # prior_writer：人工真值写先验库的唯一通道（注入式，保持纯模块）
        self._prior_writer = prior_writer
        # 持久化状态
        self._pool: Dict[str, Dict[str, Any]] = {}   # 抽检池（待人工复核）
        self._labels: List[Dict[str, Any]] = []      # 人工标签历史（截断 500）
        self._residual_mean = 0.0
        self._residual_var = 0.0
        self._residual_n = 0
        self._frozen = False                          # 闭环冻结（§29）
        self._alerts: List[Dict[str, Any]] = []       # 告警历史（截断 100）
        self._seen: Dict[str, float] = {}             # prompt 签名 → 时间（去重）
        # 指标计数（§74）
        self._n_sampled = 0
        self._n_units = 0
        self._n_ai_flagged = 0      # AI 判高风险
        self._n_true_defect = 0     # 人工确认缺陷
        self._n_flagged_defect = 0  # AI 高风险且人工确认缺陷（TP）
        self._n_unflagged_defect = 0  # AI 未标但人工判缺陷（FN，仅抽检可见）

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
                        self._pool = dict(d.get("pool") or {})
                        self._labels = list(d.get("labels") or [])
                        self._residual_mean = float(d.get("residual_mean") or 0.0)
                        self._residual_var = float(d.get("residual_var") or 0.0)
                        self._residual_n = int(d.get("residual_n") or 0)
                        self._frozen = bool(d.get("frozen") or False)
                        self._alerts = list(d.get("alerts") or [])
                        self._seen = dict(d.get("seen") or {})
                        for k in ("_n_sampled", "_n_units", "_n_ai_flagged",
                                  "_n_true_defect", "_n_flagged_defect",
                                  "_n_unflagged_defect"):
                            setattr(self, k, int(d.get(k.lstrip("_"), 0)
                                                 or d.get(k, 0)))
            except Exception:
                logger.debug("[sampling_review] 加载失败，按初始状态启动", exc_info=True)
            self._loaded = True

    def _save_locked(self) -> None:
        try:
            d = os.path.dirname(self._path)
            os.makedirs(d, exist_ok=True)
            fd, tmp = tempfile.mkstemp(prefix="sr_", suffix=".tmp", dir=d)
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    json.dump({
                        "pool": self._pool,
                        "labels": self._labels[-500:],
                        "residual_mean": round(self._residual_mean, 6),
                        "residual_var": round(self._residual_var, 6),
                        "residual_n": self._residual_n,
                        "frozen": self._frozen,
                        "alerts": self._alerts[-100:],
                        "seen": self._seen,
                        "n_sampled": self._n_sampled,
                        "n_units": self._n_units,
                        "n_ai_flagged": self._n_ai_flagged,
                        "n_true_defect": self._n_true_defect,
                        "n_flagged_defect": self._n_flagged_defect,
                        "n_unflagged_defect": self._n_unflagged_defect,
                    }, f, ensure_ascii=False, indent=1)
                os.replace(tmp, self._path)
            finally:
                if os.path.exists(tmp):
                    try:
                        os.remove(tmp)
                    except OSError:
                        logger.debug("忽略异常（原为 pass）: sampling_review.py", exc_info=True)
        except Exception:
            logger.debug("[sampling_review] 持久化失败（不阻断）", exc_info=True)

    # ────────────── ① 自适应分层抽样（§71.1） ──────────────

    def should_sample(self, unit_id: str, kind: str,
                      residual: float = 0.0, divergence: float = 0.0,
                      new_version: bool = False, new_genre: bool = False,
                      prompt_sig: str = "") -> Dict[str, Any]:
        """P = clamp(p_base×(1+α_r·r̂+α_d·Δ̂), p_min, 1)；确定性哈希判定。

        新模型版本 / 新题材**强制必检**（§71.1/§76 分布外强开高阶预审精神）；
        24h 内重复 prompt 签名 → 过滤（§71.5）。
        """
        with self._lock:
            self._ensure_loaded()
            self._n_units += 1
            reasons: List[str] = []
            if prompt_sig:
                self._purge_seen_locked()
                if prompt_sig in self._seen:
                    self._save_locked()
                    return {"sample": False, "p": 0.0,
                            "reasons": ["重复样本过滤（24h 内同签名）"]}
                self._seen[prompt_sig] = time.time()
            if new_version or new_genre:
                self._n_sampled += 1
                self._save_locked()
                why = "新模型版本" if new_version else "新题材"
                return {"sample": True, "p": 1.0,
                        "reasons": [f"{why}强制必检"]}
            r = min(1.0, max(0.0, float(residual)))
            dv = min(1.0, max(0.0, float(divergence)))
            p = _P_BASE * (1.0 + _ALPHA_R * r + _ALPHA_D * dv)
            p = min(1.0, max(_P_MIN, p))
            if r > 0.0:
                reasons.append(f"残差放大 ×{1 + _ALPHA_R * r:.2f}")
            if dv > 0.0:
                reasons.append(f"分歧放大 ×{1 + _ALPHA_D * dv:.2f}")
            hit = _stable_hash(str(unit_id)) < p
            if hit:
                self._n_sampled += 1
            self._save_locked()
            return {"sample": hit, "p": round(p, 4),
                    "reasons": reasons or ["基础抽样率"]}

    def _purge_seen_locked(self) -> None:
        cutoff = time.time() - _DEDUP_WINDOW
        stale = [k for k, t in self._seen.items() if t < cutoff]
        for k in stale:
            del self._seen[k]

    # ────────────── ② 规则预审（§71.2 确定性优先） ──────────────

    def prescreen(self, unit: Dict[str, Any]) -> Dict[str, Any]:
        """确定性规则检查（无模型、零成本），输出风险等级 + 预填表单。

        unit: {"unit_id", "kind": "video|audio|text", "path"(可选),
               "duration"(可选), "expected_duration"(可选),
               "fields"(文本可选), "required_fields"(可选),
               "machine_score", "divergence", "mode", "model_version",
               "provider", "prompt_sig"}
        """
        defects: List[str] = []
        kind = str(unit.get("kind", "video"))
        path = str(unit.get("path") or "")
        if path:
            if not os.path.isfile(path):
                defects.append("产物文件缺失")
            else:
                try:
                    size = os.path.getsize(path)
                    if kind == "video" and size < 10 * 1024:
                        defects.append(f"视频体积异常（{size}B，疑似黑屏/崩坏）")
                    if kind == "audio" and size < 1024:
                        defects.append(f"音频体积异常（{size}B，疑似静音/截断）")
                except OSError:
                    defects.append("产物不可读")
        dur = float(unit.get("duration") or 0.0)
        exp = float(unit.get("expected_duration") or 0.0)
        if dur > 0 and exp > 0 and abs(dur - exp) / max(exp, 0.1) > 0.2:
            defects.append(f"时长偏差 {dur:.1f}s vs 预期 {exp:.1f}s（>20%）")
        if kind == "text":
            fields = unit.get("fields")
            req = unit.get("required_fields") or []
            if isinstance(fields, dict):
                missing = [k for k in req if k not in fields or fields[k] in (None, "")]
                if missing:
                    defects.append(f"Schema 缺字段：{','.join(missing)}")
            elif req:
                defects.append("文本产物非结构化（无法校验 Schema）")
        machine = float(unit.get("machine_score", 0.5))
        if machine < 0.3:
            defects.append(f"机器分过低（{machine:.2f}）")

        high_rules = ("产物文件缺失", "Schema 缺字段", "产物不可读")
        if any(any(h in d for h in high_rules) for d in defects):
            risk = "高"
        elif defects or machine < 0.5:
            risk = "中"
        else:
            risk = "低"
        uncertain = (not defects) and (0.4 <= machine <= 0.6)  # 可判可不判 → 上交
        if risk == "高":
            self._n_ai_flagged += 1
        form = {
            "unit_id": str(unit.get("unit_id", "")),
            "kind": kind,
            "machine_score": machine,
            "divergence": float(unit.get("divergence", 0.0)),
            "mode": str(unit.get("mode", "")),
            "model_version": str(unit.get("model_version", "")),
            "provider": str(unit.get("provider", "")),
            "defects": defects,
            "risk": risk,
            "uncertain": uncertain,
            "suggested": "不合格" if risk == "高" else ("存疑" if uncertain else "合格"),
            "created_at": time.time(),
        }
        return {"risk": risk, "defects": defects, "uncertain": uncertain,
                "form": form}

    # ────────────── ③ 入池 + AI 打分（红线：永不写先验） ──────────────

    def submit_ai_score(self, unit: Dict[str, Any]) -> Dict[str, Any]:
        """AI 预审打分 → 入抽检池（§73 第 2-3 步）。

        **红线（§72/§76）：本函数只输出风险提示，绝不写质量先验库。**
        """
        with self._lock:
            self._ensure_loaded()
            verdict = self.prescreen(unit)
            uid = str(unit.get("unit_id", "")) or f"u_{int(time.time()*1000)}"
            self._pool[uid] = verdict["form"]
            # 池容量保护：超 200 条清最旧
            if len(self._pool) > 200:
                oldest = sorted(self._pool.items(),
                                key=lambda kv: kv[1].get("created_at", 0))[:50]
                for k, _ in oldest:
                    del self._pool[k]
            self._save_locked()
            return {"unit_id": uid, **verdict}

    def pending_reviews(self, high_first: bool = True) -> List[Dict[str, Any]]:
        """待人工复核清单（高风险优先，§73「高风险优先推送人工」）。"""
        with self._lock:
            self._ensure_loaded()
            items = list(self._pool.values())
            rank = {"高": 0, "中": 1, "低": 2}
            if high_first:
                items.sort(key=lambda f: (rank.get(f.get("risk", "低"), 3),
                                          f.get("created_at", 0)))
            return items

    # ────────────── ④ 人工真值（唯一可写先验的通道） ──────────────

    def submit_human_label(self, unit_id: str, label: str,
                           ai_score: Optional[float] = None,
                           provider: str = "") -> Dict[str, Any]:
        """人工真值标签（§72 红线：仅人工确认标签允许校正权重与先验库）。

        label: "合格"(y=1.0) / "存疑"(y=0.5) / "不合格"(y=0.0)。
        动作：残差 |y−ŷ| 入库（EMA）→ 漂移判定（告警/冻结）→ 写先验库
        （经注入的 prior_writer）→ 出池。
        """
        y_map = {"合格": 1.0, "存疑": 0.5, "不合格": 0.0}
        if label not in y_map:
            return {"ok": False, "error": f"非法标签 {label}（须为 合格/存疑/不合格）"}
        y = y_map[label]
        with self._lock:
            self._ensure_loaded()
            form = self._pool.pop(str(unit_id), None)
            was_flagged = bool(form and form.get("risk") == "高")
            ai = float(ai_score) if ai_score is not None else float(
                (form or {}).get("machine_score", 0.5))
            residual = abs(y - ai)
            # 残差 EMA（§71.4：r = |y − ŷ|）
            d = residual - self._residual_mean
            self._residual_mean += _ALPHA * d
            self._residual_var = (1 - _ALPHA) * (self._residual_var
                                                 + _ALPHA * d * d)
            self._residual_n += 1
            # 指标计数（§74）
            defect = y < 1.0
            if defect:
                self._n_true_defect += 1
                if was_flagged:
                    self._n_flagged_defect += 1
                else:
                    self._n_unflagged_defect += 1
            self._labels.append({"unit_id": str(unit_id), "label": label,
                                 "y": y, "ai_score": ai, "residual": residual,
                                 "at": time.time()})
            self._labels = self._labels[-500:]
            # 漂移判定（§29）：够样本才判，防小样本误冻结
            drift = None
            if self._residual_n >= _MIN_SAMPLES_FOR_DRIFT:
                if self._residual_mean > _DRIFT_FREEZE and not self._frozen:
                    self._frozen = True
                    drift = "freeze"
                    self._alert_locked("freeze",
                        f"残差均值 {self._residual_mean:.3f} > {_DRIFT_FREEZE}："
                        f"闭环已冻结（机器观测停写先验），需人工复核后解冻")
                elif self._residual_mean > _DRIFT_WARN:
                    drift = "warn"
                    self._alert_locked("warn",
                        f"残差均值 {self._residual_mean:.3f} > {_DRIFT_WARN}："
                        f"建议校正评分权重")
            # 写先验库（唯一通道，经注入 writer；无 writer 只记标签）
            wrote_prior = False
            if self._prior_writer is not None and provider:
                try:
                    self._prior_writer(provider, y)
                    wrote_prior = True
                except Exception:
                    logger.debug("[sampling_review] 先验写入失败（不阻断）",
                                 exc_info=True)
            self._save_locked()
            return {"ok": True, "y": y, "residual": round(residual, 4),
                    "residual_mean": round(self._residual_mean, 4),
                    "drift": drift, "frozen": self._frozen,
                    "wrote_prior": wrote_prior}

    def unfreeze(self, operator: str = "") -> Dict[str, Any]:
        """人工解冻闭环（§72：重大变更审批权在人工——解冻也只能人工做）。"""
        with self._lock:
            self._ensure_loaded()
            was = self._frozen
            self._frozen = False
            self._residual_mean = 0.0   # 重新校准基线（人工已介入裁定）
            self._residual_var = 0.0
            self._residual_n = 0
            if was:
                self._alert_locked("unfreeze",
                    f"人工（{operator or '未署名'}）解冻闭环，残差基线重置")
            self._save_locked()
            return {"ok": True, "was_frozen": was}

    def _alert_locked(self, kind: str, message: str) -> None:
        self._alerts.append({"kind": kind, "message": message,
                             "at": time.time()})
        self._alerts = self._alerts[-100:]
        logger.warning("[sampling_review] %s", message)

    # ────────────── ⑤ 状态 / 指标（§74） ──────────────

    def is_frozen(self) -> bool:
        """闭环是否冻结（**管线机器观测写先验前必须查这个**）。"""
        with self._lock:
            self._ensure_loaded()
            return self._frozen

    def drift_status(self) -> Dict[str, Any]:
        with self._lock:
            self._ensure_loaded()
            return {"frozen": self._frozen,
                    "residual_mean": round(self._residual_mean, 4),
                    "residual_var": round(self._residual_var, 4),
                    "residual_n": self._residual_n,
                    "warn_threshold": _DRIFT_WARN,
                    "freeze_threshold": _DRIFT_FREEZE,
                    "alerts": list(self._alerts[-10:])}

    def metrics(self) -> Dict[str, Any]:
        """§74 评估指标：召回率 / 精确率 / 人工减负率。"""
        with self._lock:
            self._ensure_loaded()
            tp = self._n_flagged_defect
            fn = self._n_unflagged_defect
            recall = tp / (tp + fn) if (tp + fn) > 0 else None
            precision = (tp / self._n_ai_flagged) if self._n_ai_flagged > 0 else None
            labor = 1.0 - (self._n_sampled / self._n_units) \
                if self._n_units > 0 else None
            return {"recall": None if recall is None else round(recall, 4),
                    "precision": None if precision is None else round(precision, 4),
                    "labor_reduction": None if labor is None else round(labor, 4),
                    "targets": {"recall": "≥0.80", "labor_reduction": "0.70~0.90"},
                    "counts": {"units": self._n_units, "sampled": self._n_sampled,
                               "ai_flagged": self._n_ai_flagged,
                               "true_defect": self._n_true_defect,
                               "tp": tp, "fn": fn}}


# ═══════════════════════════════════════════════════════════
# 单例
# ═══════════════════════════════════════════════════════════

_REVIEW: Optional[SamplingReview] = None
_REVIEW_LOCK = threading.Lock()


def get_review() -> SamplingReview:
    """进程级单例；prior_writer 默认接 quality_prior（人工标签写 quality 桶）。"""
    global _REVIEW
    if _REVIEW is None:
        with _REVIEW_LOCK:
            if _REVIEW is None:
                writer = None
                try:
                    from .quality_prior import get_store

                    def writer(provider: str, y: float) -> None:
                        get_store().record_outcome(provider, ok=True,
                                                   quality=y, kind="quality")
                except Exception:
                    logger.debug("[sampling_review] 先验写入器不可用（只记标签）",
                                 exc_info=True)
                _REVIEW = SamplingReview(prior_writer=writer)
    return _REVIEW
