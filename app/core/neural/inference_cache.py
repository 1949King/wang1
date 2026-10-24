# -*- coding: utf-8 -*-
"""P0 推理缓存三件套 + 统一门控（2026-10-25，V4.47.0）—— 单一新文件，不抬主文件基线。

设计依据：`docs/_reports/2026-10-24-DeepSeek推理理念移植至diffusers栈设计方案.md`
（下称「设计稿」）。本模块是该设计稿 §3.1 的落地：DeepSeek 三项推理理念
（MLA 低秩压缩 / PagedAttention 块池与前缀缓存 / MoE 专家卸载）在扩散栈里的
对应物，全部收敛在这一个文件里，主引擎只做薄接线。

五个组件（与设计稿 §3.1 逐字对应）
================================
1. ``StepFeatureCache``     DeepCache 移植：U-Net up-blocks 前向短路式步间特征缓存。
                            attach(pipe, arch, interval, branch_id) → detach，stats 遥测。
2. ``LowRankFeatureCache``  MLA 三件套移植（设计稿 §10）：缓存特征低秩 + 折叠/重建。
3. ``EncoderOutputCache``   prefix cache 对应物：文本编码输出 LRU（键含全部变量）。
4. ``VramBlockPool``        paged allocation 对应物：固定块池 + release_vram_sequence()。
5. ``cache_gate``           统一门控：arch 白名单 × 质量档位 × 环境开关，返回决策+理由。

纪律（与项目其余引擎一致）
========================
1. **默认关、显式开**（设计稿决策点 C）：步缓存有质量风险 ⇒ SHIGUANG_STEP_CACHE 默认空；
   编码器缓存零质量风险但同样默认关（SHIGUANG_ENCODER_CACHE=1 开启），浸泡后再议默认开。
2. **诚实失败**：arch 不在白名单 / 包缺失 / 结构不符 ⇒ 禁用 + reasons 留痕，
   绝不静默降级成「你以为在用缓存」。
3. **零新依赖**：torch 只在函数内 import（顶层零重依赖，同 memory_policy 戒律）；
   无 GPU 环境全部组件可单测（假 UNet / CPU 张量）。
4. **官方倍率只作预期**：DeepCache 2.3×/2.6×/1.7× 是 A5000 无 offload 口径，
   项目结论一律本机重测（见 .workbuddy/memory 实测纪律）。
5. **与 accelerate offload 的关系**：短路只换 forward 不算数——reuse 步 accelerate 的
   pre/post hook 仍会把块搬上搬下（PCIe 税照付），compute 省掉。实测收益以标定为准。

★ 对设计稿的一处实测修正（2026-10-25 读 diffusers 0.40 源码确认）
==============================================================
设计稿 §10.3 假设「h 的唯一消费者是收尾的 conv_out」，可把 U_r 直接折进 conv_out 权重。
**真实结构不是这样**：UNet2DConditionModel.forward 的结尾是
``conv_norm_out(GroupNorm) → conv_act(SiLU) → conv_out`` —— GroupNorm 是 per-group
非线性归一化，折不过去。因此低秩组件在真实 U-Net（SD1.5/SDXL/SVD 都有 conv_norm_out）
上走「压缩存储 + 消费时一次重建」：缓存显存 ×(C/r) 的收益保留，解压税 = 一次
einsum（r×H×W×C MAC，约几十 ms 级，实测计量）。``fold_into``（吸收式零解压）
保留给 ``conv_norm_out is None`` 的 U-Net 变体，并有单测覆盖——不是死代码，
是条件可用路径。
"""

from __future__ import annotations

import hashlib
import logging
import os
import threading
import time
from collections import OrderedDict
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ────────────────────── 门控矩阵（档位矩阵的单一真相源）──────────────────────
# 步缓存 arch 白名单：三个都经**源码级结构核实**（up_blocks + conv_out + 标准循环）：
#   sd15/sdxl → UNet2DConditionModel；svd → UNetSpatioTemporalConditionModel。
# 未核实的 arch（wan 等 DiT）一律不进——DiT 的对应物是 diffusers 0.40 内置 FBCache，
# 属后续探针，不在这张表里冒充。
STEP_CACHE_ARCHS: frozenset = frozenset({"sd15", "sdxl", "svd"})
# 步缓存可用档位：草稿档可开；final/best 保持纯净（抽卡对细节敏感，LCM 偏软是前车之鉴）。
# 视频侧 preview/fast 同构；balanced 是默认档，不进白名单。
STEP_CACHE_PRESETS: frozenset = frozenset({"fast", "high", "preview"})
# 编码器缓存 arch 白名单：**以公开 encode_prompt 存在为前提**（实测签名见
# encode_prompt_embeds）。SVD 无公开 encode_prompt（私有 _encode_prompt + CLIP，
# 编码占比小）⇒ 不接，宁缺勿假。
ENCODER_CACHE_ARCHS: frozenset = frozenset({"sd15", "sdxl"})

_ENV_STEP = "SHIGUANG_STEP_CACHE"           # "" | off | deepcache | auto
_ENV_ENCODER = "SHIGUANG_ENCODER_CACHE"     # "" | 0 | 1
_ENV_INTERVAL = "SHIGUANG_STEP_CACHE_INTERVAL"   # ≥2，默认 3
_ENV_BRANCH = "SHIGUANG_STEP_CACHE_BRANCH"       # ≥0，默认 0
_ENV_LOWRANK = "SHIGUANG_STEP_CACHE_LOWRANK"     # "" | 0.125 | 0.25 | 0.5
_ENV_POOL = "SHIGUANG_CACHE_POOL"                # "" | 1（缓存特征走块池）

_DEFAULT_INTERVAL = 3
_DEFAULT_BRANCH = 0


def _env_int(name: str, default: int, lo: int, hi: int) -> int:
    """读环境变量为 int，越界/非法回落默认（不猜、不炸）。"""
    raw = (os.environ.get(name) or "").strip()
    if not raw:
        return default
    try:
        v = int(raw)
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, v))


def _env_float(name: str, default: float, lo: float, hi: float) -> float:
    raw = (os.environ.get(name) or "").strip()
    if not raw:
        return default
    try:
        v = float(raw)
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, v))


def cache_gate(*, arch: str = "", preset: str = "",
               component: str = "step_cache") -> Dict[str, Any]:
    """统一门控：这次生成要不要启用某缓存组件。纯函数，无副作用，可单测。

    返回 ``{ok, component, arch, preset, reasons, params}``：
      ok=False 时 reasons 说明**为什么不开**（决策必须可见，同 R9 精神）；
      params 是调用方直接可用的参数（interval/branch_id/lowrank/pool）。
    """
    a = (arch or "").strip().lower()
    p = (preset or "").strip().lower()
    reasons: List[str] = []
    params: Dict[str, Any] = {}

    if component == "encoder_cache":
        enabled = (os.environ.get(_ENV_ENCODER) or "").strip() in ("1", "true", "on")
        if not enabled:
            reasons.append("编码器缓存默认关（SHIGUANG_ENCODER_CACHE=1 开启；"
                           "零质量风险，浸泡后可议默认开）")
        if a not in ENCODER_CACHE_ARCHS:
            reasons.append(
                "arch %r 无公开 encode_prompt（白名单 %s）⇒ 不接编码器缓存"
                % (a, sorted(ENCODER_CACHE_ARCHS)))
        ok = enabled and a in ENCODER_CACHE_ARCHS
        return {"ok": ok, "component": component, "arch": a, "preset": p,
                "reasons": reasons, "params": {}}

    # ── step_cache ──
    raw = (os.environ.get(_ENV_STEP) or "").strip().lower()
    if raw in ("", "off", "0", "none"):
        reasons.append("步缓存默认关（SHIGUANG_STEP_CACHE=deepcache 开启；"
                       "质量风险前置，final/best 永不开）")
    elif raw not in ("deepcache", "auto"):
        reasons.append("SHIGUANG_STEP_CACHE=%r 无法识别（可用 off/deepcache）⇒ 按关处理" % raw)
    if a not in STEP_CACHE_ARCHS:
        reasons.append(
            "arch %r 未经步缓存结构核实（白名单 %s；DiT 走 FBCache 探针，不在此表）"
            % (a, sorted(STEP_CACHE_ARCHS)))
    if p not in STEP_CACHE_PRESETS:
        reasons.append(
            "档位 %r 不进步缓存白名单 %s（草稿档可开，final/best/空档保持纯净）"
            % (p, sorted(STEP_CACHE_PRESETS)))
    ok = (raw in ("deepcache", "auto")) and a in STEP_CACHE_ARCHS and p in STEP_CACHE_PRESETS
    if ok:
        params = {
            "interval": _env_int(_ENV_INTERVAL, _DEFAULT_INTERVAL, 2, 20),
            "branch_id": _env_int(_ENV_BRANCH, _DEFAULT_BRANCH, 0, 8),
            "lowrank": _env_float(_ENV_LOWRANK, 0.0, 0.05, 0.9),
            "pool": (os.environ.get(_ENV_POOL) or "").strip() in ("1", "true", "on"),
        }
        reasons.append("门控通过：arch=%s preset=%s interval=%d branch=%d lowrank=%.3f pool=%s"
                       % (a, p, params["interval"], params["branch_id"],
                          params["lowrank"], params["pool"]))
    return {"ok": ok, "component": component, "arch": a, "preset": p,
            "reasons": reasons, "params": params}


# ══════════════════════════════════════════════════════════════════════
# 1. StepFeatureCache —— DeepCache 移植
# ══════════════════════════════════════════════════════════════════════

class StepFeatureCache:
    """U-Net 步间特征缓存（DeepCache 原生 hook 实现，零新依赖）。

    机制（与官方论文同口径，非照搬包）：
      · 每个去噪步 = 一次 unet.forward。步计数挂在 unet 的 forward_pre_hook 上。
      · **全量步**（第 1, 1+I, 1+2I, … 步）：正常计算，缓存全部 up_blocks 输出。
      · **复用步**（其余 I-1 步）：down/mid 照算，``up_blocks[i >= branch_id]``
        前向**短路**返回上一全量步的缓存 ⇒ 真跳过上采样支路计算。
      · 第 1 步必为全量步（缓存从第一步就有内容）⇒ 不存在「缓存缺失还硬跳」。

    ★ 与 accelerate offload 的相互作用（实测结论，勿改）：
      reuse 步被短路的块，accelerate 的 pre/post hook **仍会触发**（块搬上卡再搬回，
      PCIe 税照付）——本实现省的是 compute 不是搬运。8GB 卡上 SDXL 的搬运占比高
      （实测 offload 固定开销 ~7s/25s ≈ 28%）⇒ 端到端收益以标定为准，不满诛。

    ★ 短路的实现方式：替换 block.forward 实例属性（nn.Module.__call__ 查实例
      dict 优先于类方法）。attach 时保存原 forward，detach 时逐个还原——
      **还原列表与包裹列表必须一一对应**（漏一个 = 下一次 generate 双倍短路）。
    """

    def __init__(self) -> None:
        self._pipe: Any = None
        self._unet: Any = None
        self._arch = ""
        self._interval = _DEFAULT_INTERVAL
        self._branch_id = _DEFAULT_BRANCH
        self._n_up = 0
        self._wrapped: List[Tuple[Any, int, Any]] = []   # (block, idx, orig_forward)
        self._step_hook: Any = None                       # unet forward_pre hook 句柄
        self._mode = "off"                                # off | full | reuse
        self._active = False
        self._step = 0
        self._full_steps = 0
        self._reuse_steps = 0
        self._reuse_hits = 0          # 实际命中缓存（真跳过）的块次数
        self._reuse_fallbacks = 0     # 缓存缺失诚实降级真算的次数
        self._cached: Dict[int, Any] = {}
        self._handles: Dict[int, Any] = {}   # 池块句柄（pool 模式）
        self._cached_bytes = 0
        self._pool: Optional["VramBlockPool"] = None
        self._lowrank: Optional["LowRankFeatureCache"] = None
        self._absorbed = False        # 低秩吸收式（conv_norm_out is None 时才可用）
        self._folded = False          # 吸收式折叠是否真的装上（fold_into 成功才算）
        self._report: Dict[str, Any] = {}

    # ── 挂载 / 卸载 ──
    def attach(self, pipe: Any, *, arch: str, interval: int = _DEFAULT_INTERVAL,
               branch_id: int = _DEFAULT_BRANCH, pool: Any = None,
               lowrank: Any = None) -> Dict[str, Any]:
        """给 pipeline 装步缓存（**不激活**；activate() 后才跳步）。

        返回 CacheReport：{ok, arch, n_up_blocks, interval, branch_id, reasons}。
        结构不符（无 unet / 无 up_blocks / interval<2 / branch 越界）⇒ ok=False + 原因，
        **绝不半挂起状态**（要么全挂要么全不挂）。
        """
        rep: Dict[str, Any] = {"ok": False, "arch": arch, "n_up_blocks": 0,
                               "interval": int(interval), "branch_id": int(branch_id),
                               "reasons": []}
        if self._pipe is not None:
            rep["reasons"].append("已 attach 过（先 detach 再 attach）")
            return rep
        if int(interval) < 2:
            rep["reasons"].append("interval=%d < 2 ⇒ 没有复用步，缓存无意义" % int(interval))
            return rep
        unet = getattr(pipe, "unet", None)
        blocks = getattr(unet, "up_blocks", None) if unet is not None else None
        if unet is None or blocks is None:
            rep["reasons"].append("pipeline 无 unet.up_blocks（arch=%r 结构不符）" % arch)
            return rep
        try:
            n_up = len(blocks)
        except TypeError:
            rep["reasons"].append("up_blocks 不是序列（结构不符）")
            return rep
        if n_up <= 0:
            rep["reasons"].append("up_blocks 为空（结构不符）")
            return rep
        if not (0 <= int(branch_id) < n_up):
            rep["reasons"].append(
                "branch_id=%d 越界（0 ≤ branch < %d）" % (int(branch_id), n_up))
            return rep

        self._pipe = pipe
        self._unet = unet
        self._arch = arch
        self._interval = int(interval)
        self._branch_id = int(branch_id)
        self._n_up = n_up
        self._pool = pool
        self._lowrank = lowrank
        # 低秩吸收式仅在「尾部无 GroupNorm」时可行（见模块 docstring 的实测修正）
        self._absorbed = bool(lowrank is not None
                              and getattr(unet, "conv_norm_out", None) is None)

        for idx in range(n_up):
            block = blocks[idx]
            orig = block.forward
            block.forward = self._make_wrapped(block, idx, orig)   # type: ignore[method-assign]
            self._wrapped.append((block, idx, orig))
        self._step_hook = unet.register_forward_pre_hook(self._on_unet_pre)

        rep.update({"ok": True, "n_up_blocks": n_up})
        rep["reasons"].append(
            "已挂载 %d 个 up_block 短路 + 步计数 hook（interval=%d branch=%d%s）"
            % (n_up, self._interval, self._branch_id,
               " · 低秩吸收式" if self._absorbed else
               (" · 低秩压缩存储+重建" if lowrank is not None else "")))
        self._report = rep
        return rep

    def _make_wrapped(self, block: Any, idx: int, orig: Any):
        """生成单个 up_block 的短路前向（闭包持有 cache 自身）。"""
        cache = self

        def wrapped(*args: Any, **kwargs: Any) -> Any:
            if (cache._active and cache._mode == "reuse"
                    and idx >= cache._branch_id):
                out = cache._cached_out(idx)
                if out is not None:
                    cache._reuse_hits += 1
                    return out
                # 缓存缺失（理论上不会发生：第 1 步必全量）⇒ 诚实降级真算
                cache._reuse_fallbacks += 1
                return orig(*args, **kwargs)
            out = orig(*args, **kwargs)
            if cache._active and cache._mode == "full":
                return cache._store(idx, out)
            return out

        return wrapped

    def _on_unet_pre(self, _module: Any, _args: Any) -> None:
        """unet 每次前向 = 一个去噪步：计数 + 定模态。未激活时零开销。"""
        if not self._active:
            return
        self._step += 1
        if (self._step - 1) % self._interval == 0:
            self._mode = "full"
            self._full_steps += 1
        else:
            self._mode = "reuse"
            self._reuse_steps += 1

    def activate(self) -> None:
        """激活跳步（attach 后到 activate 前，所有前向原样放行）。"""
        self._active = True

    def deactivate(self) -> None:
        self._active = False
        self._mode = "off"

    def detach(self) -> Dict[str, Any]:
        """还原全部 forward + 摘 hook + 清缓存。返回最终 stats（调用方可直接记遥测）。"""
        stats = self.stats()
        for block, _idx, orig in self._wrapped:
            try:
                block.forward = orig    # type: ignore[method-assign]
            except Exception:  # stability-gate: allow-swallow（还原是 best-effort：块已被 GC 时无后果）
                logger.debug("[StepFeatureCache] forward 还原失败", exc_info=True)
        self._wrapped = []
        if self._step_hook is not None:
            try:
                self._step_hook.remove()
            except Exception:  # stability-gate: allow-swallow（hook 已随模块销毁时 remove 失败无后果）
                logger.debug("[StepFeatureCache] hook 移除失败", exc_info=True)
            self._step_hook = None
        self._release_cached()
        self._active = False
        self._mode = "off"
        self._pipe = None
        self._unet = None
        return stats

    # ── 缓存存取 ──
    def _store(self, idx: int, out: Any) -> Any:
        """全量步存储 up_blocks[idx] 输出，**返回本步应向下游传递的值**。

        末块特殊处理：先喂低秩样本；已校准则存投影 M（absorbed 模式同样投影——
        那时 conv_out 已折叠成消费 M）。池模式把树复制进固定块，cached 只存**视图**
        （原树随即可被 GC，杜绝「原始 + 池拷贝」双倍驻留）。

        ★ 返回契约（absorbed 模式的关键，2026-10-25 自查修复）：
          · 折叠已装上（_folded）⇒ conv_out 消费的是 M（r 通道），本步必须把
            投影 M 传向尾部，否则通道不匹配当场崩；
          · 其余一切情况（未校准 / 折叠失败 / 非 absorbed）⇒ 尾部没动，
            照传原始 out（h 走完 conv_norm_out→conv_act→conv_out，缓存里存 M）。
        """
        self._release_slot(idx)
        stored = out
        downstream = out
        if self._lowrank is not None and idx == self._n_up - 1:
            h_in = out[0] if isinstance(out, (tuple, list)) and out else out
            self._lowrank.add_sample(h_in)
            if not self._lowrank.calibrated and self._lowrank.samples_enough():
                r = self._lowrank.calibrate()
                logger.info("[StepFeatureCache] 低秩校准：%s", r)
                if (self._absorbed and self._lowrank.calibrated
                        and getattr(self._unet, "conv_out", None) is not None):
                    new_conv, why = self._lowrank.fold_into(self._unet.conv_out)
                    if new_conv is not None:
                        self._unet.conv_out = new_conv
                        self._folded = True
                        logger.info("[StepFeatureCache] 吸收式折叠完成：%s", why)
                    else:
                        logger.warning("[StepFeatureCache] 吸收式折叠失败：%s（"
                                       "本步起尾部仍消费 h，缓存照存 M 走重建路径）", why)
            if self._lowrank.calibrated:
                stored = self._lowrank.project_tree(out)
                if self._folded:
                    downstream = stored
        if self._pool is not None:
            handle = self._pool.store_tree(stored)
            if handle is not None:
                self._handles[idx] = handle
                self._cached[idx] = handle.as_tree(stored)
                self._cached_bytes += handle.n_bytes
                return downstream
        self._cached[idx] = stored
        self._cached_bytes += _tree_nbytes(stored)
        return downstream

    def _cached_out(self, idx: int) -> Any:
        """复用步取缓存。

        低秩**重建**模式（缓存存 M、尾部未折叠）⇒ 末块先重建 h̃ 再返回；
        吸收式已折叠（_folded）⇒ 尾部直接消费 M，原样返回（零解压税）。
        未校准 ⇒ 缓存就是原始 h，原样返回。
        """
        out = self._cached.get(idx)
        if (out is not None and self._lowrank is not None
                and self._lowrank.calibrated and not self._folded
                and idx == self._n_up - 1):
            out = self._lowrank.reconstruct_tree(out)
        return out

    def _release_slot(self, idx: int) -> None:
        h = self._handles.pop(idx, None)
        if h is not None and self._pool is not None:
            self._pool.release(h)
            self._cached_bytes -= h.n_bytes
            self._cached.pop(idx, None)   # 池模式 cached 是池内视图，字节账由 handle 管
            return
        self._cached_bytes -= _tree_nbytes(self._cached.get(idx))
        self._cached.pop(idx, None)

    def _release_cached(self) -> None:
        for idx in list(self._cached.keys()):
            self._release_slot(idx)

    # ── 低秩样本累计由 _store 内部完成（全量步自动喂样本/校准/折叠）──

    def stats(self) -> Dict[str, Any]:
        total = self._full_steps + self._reuse_steps
        branched = max(1, self._n_up - self._branch_id)
        return {
            "attached": self._pipe is not None,
            "active": self._active,
            "arch": self._arch,
            "interval": self._interval,
            "branch_id": self._branch_id,
            "n_up_blocks": self._n_up,
            "steps": self._step,
            "full_steps": self._full_steps,
            "reuse_steps": self._reuse_steps,
            "reuse_hits": self._reuse_hits,
            "reuse_fallbacks": self._reuse_fallbacks,
            # 跳步率 = 复用步占比（≤1）；块命中率 = 命中/(复用步×短路块数)（≤1）
            "skip_ratio": round(self._reuse_steps / total, 4) if total else 0.0,
            "block_hit_ratio": (round(self._reuse_hits / (self._reuse_steps * branched), 4)
                                if self._reuse_steps else 0.0),
            "cached_slots": len(self._cached),
            "cached_bytes": self._cached_bytes,
            "lowrank": self._lowrank.stats() if self._lowrank is not None else None,
            "absorbed": self._absorbed,
            "folded": self._folded,
        }


# ══════════════════════════════════════════════════════════════════════
# 2. LowRankFeatureCache —— MLA 三件套移植（设计稿 §10）
# ══════════════════════════════════════════════════════════════════════

class LowRankFeatureCache:
    """缓存特征的低秩压缩（原则②低秩化 + 原则⑤免训练恢复；③吸收条件可用）。

    对象：DeepCache 缓存步得到的末个 up_block 输出 h ∈ (B,C,H,W)。
    做法：累计 h 的**通道 Gram 矩阵**（C×C，MB 级，不存原始样本），
    calibrate() 用 `torch.svd_lowrank` 求 top-r 通道子空间 U_r ∈ (C,r)：
      · project:   M = U_rᵀh          （C×H×W → r×H×W，压缩比 C/r）
      · reconstruct: h̃ = U_r·M        （消费时一次重建，GroupNorm 挡路的真实代价）
      · fold_into:  W̃ = Σ_c W·U_r     （吸收式，仅尾部纯 conv_out 时可用）

    ★ 结构性保险（设计稿 §10.3）：每 cache_interval 步全量刷新 ⇒ 低秩误差
    **不跨周期累积**，上界 = 单次近似误差。
    """

    _MAX_GRAM_SAMPLES = 8

    def __init__(self, rank_ratio: float = 0.25) -> None:
        if not (0.05 <= rank_ratio <= 0.9):
            raise ValueError("rank_ratio 需在 [0.05, 0.9]：%r" % rank_ratio)
        self._ratio = float(rank_ratio)
        self._gram: Any = None          # (C,C) float32 累加器
        self._n_samples = 0
        self._C = 0
        self._U: Any = None             # (C,r)
        self._rank = 0
        self._energy = 0.0
        self._calibrated = False
        self._calibrated_at = 0
        self._project_calls = 0
        self._reconstruct_calls = 0

    # ── 采样 ──
    def add_sample(self, h: Any) -> bool:
        """累计一个 h 样本的通道 Gram（h: (B,C,H,W) 或 (C,H,W) 张量）。

        位置维子采样到 ≤4096（stride 确定性，无 RNG 状态污染）。
        返回 False = 样本已满或形状不符（留痕不炸）。
        """
        if self._n_samples >= self._MAX_GRAM_SAMPLES:
            return False
        try:
            import torch

            if not torch.is_tensor(h) or h.dim() < 3:
                return False
            x = h.reshape(-1, h.shape[-3], h.shape[-2] * h.shape[-1]) \
                if h.dim() == 4 else h.reshape(h.shape[0], -1)
            x = x[0] if x.dim() == 3 else x            # 取 batch 0 ⇒ (C, P)
            n_pos = x.shape[1]
            if n_pos > 4096:
                step = (n_pos + 4095) // 4096
                x = x[:, ::step]
            xf = x.to(torch.float32)
            g = xf @ xf.t()
            if self._gram is None:
                self._gram = g
                self._C = int(x.shape[0])
            else:
                if int(x.shape[0]) != self._C:
                    return False
                self._gram += g
            self._n_samples += 1
            return True
        except Exception:  # stability-gate: allow-swallow（采样失败只少一个样本，不影响正确性）
            logger.debug("[LowRankFeatureCache] add_sample 失败", exc_info=True)
            return False

    def samples_enough(self) -> bool:
        return self._n_samples >= 3

    @property
    def calibrated(self) -> bool:
        """是否已求出 U_r（公有只读访问器；_store/_cached_out 依此定行为）。"""
        return self._calibrated

    @property
    def rank(self) -> int:
        return self._rank

    # ── 校准 ──
    def calibrate(self) -> Dict[str, Any]:
        """对累计 Gram 做 svd_lowrank，得 U_r。幂等；样本不足 ⇒ ok=False。"""
        if self._calibrated:
            return {"ok": True, "rank": self._rank, "energy": self._energy,
                    "reason": "已校准（幂等跳过）"}
        if self._gram is None or self._n_samples < 3:
            return {"ok": False, "rank": 0, "energy": 0.0,
                    "reason": "样本不足（%d/3）⇒ 不校准，继续全精度缓存"
                              % (self._n_samples or 0)}
        try:
            import torch

            r = max(1, int(round(self._C * self._ratio)))
            U, S, _V = torch.svd_lowrank(self._gram, q=min(r, self._C))
            sv = torch.clamp(S, min=0.0)
            total = float(sv.sum())
            self._energy = round(float(sv[:r].sum()) / total, 4) if total > 0 else 0.0
            self._U = U[:, :r].contiguous()
            self._rank = r
            self._calibrated = True
            self._calibrated_at = self._n_samples
            logger.info("[LowRankFeatureCache] 校准完成：C=%d r=%d energy=%.4f（%d 样本）",
                        self._C, r, self._energy, self._n_samples)
            return {"ok": True, "rank": r, "energy": self._energy,
                    "reason": "C=%d r=%d energy=%.4f" % (self._C, r, self._energy)}
        except Exception as e:  # stability-gate: allow-swallow（校准失败 ⇒ 保持全精度，宁慢不糊）
            logger.debug("[LowRankFeatureCache] calibrate 失败", exc_info=True)
            return {"ok": False, "rank": 0, "energy": 0.0,
                    "reason": "校准异常 %s: %s ⇒ 保持全精度缓存" % (type(e).__name__, e)}

    # ── 投影 / 重建 ──
    def project_tree(self, tree: Any) -> Any:
        """对 (可能 tuple/list 的) 张量树的第 0 个张量做低秩投影。"""
        if not self._calibrated:
            return tree
        return self._map_first(tree, self.project)

    def reconstruct_tree(self, tree: Any) -> Any:
        if not self._calibrated:
            return tree
        return self._map_first(tree, self.reconstruct)

    @staticmethod
    def _map_first(tree: Any, fn: Any) -> Any:
        if isinstance(tree, (tuple, list)) and tree:
            head = fn(tree[0])
            return type(tree)((head,) + tuple(tree[1:]))
        return fn(tree)

    def project(self, h: Any) -> Any:
        """h (B,C,H,W) → M (B,r,H,W)。"""
        import torch

        self._project_calls += 1
        return torch.einsum("cr,bchw->brhw", self._U.to(h.dtype), h)

    def reconstruct(self, m: Any) -> Any:
        """M (B,r,H,W) → h̃ (B,C,H,W)。"""
        import torch

        self._reconstruct_calls += 1
        return torch.einsum("cr,brhw->bchw", self._U.to(m.dtype), m)

    # ── 吸收（条件可用：尾部纯 conv_out）──
    def fold_into(self, conv_out: Any) -> Tuple[Optional[Any], str]:
        """把 U_r 折进 conv_out 权重，返回 (新卷积模块或 None, 原因)。

        数学：y[o] = Σ_c W[o,c,Δ,δ]·h[c]，h[c] = Σ_j U[c,j]·M[j]
        ⇒ W̃[o,j,Δ,δ] = Σ_c W[o,c,Δ,δ]·U[c,j]（输入通道 C→r，其余超参原样拷贝）。
        仅当 unet 尾部**没有** conv_norm_out 时成立（GroupNorm 折不过去，
        见模块 docstring 实测修正；conv_norm_out is None ⇒ conv_act 同为 None，
        尾部 = 纯 conv_out，diffusers unet_2d_condition.py:1227-1229 已核实）。
        **返回新模块，由调用方安装**（本函数不改父模块，保持「谁持有谁安装」）。
        ★ nn.Conv2d.weight 形状是 (out, in, kh, kw)——不是 (in, out, ...)
        （2026-10-25 冒烟测试逮到并修正：按反的 einsum 下标直接 RuntimeError）。
        """
        if not self._calibrated:
            return None, "未校准 ⇒ 不折叠"
        try:
            import torch
            import torch.nn as nn

            w = conv_out.weight                       # (out, in=C, kh, kw)
            if w.dim() != 4:
                return None, "conv_out.weight 不是 4 维（结构不符）"
            if int(w.shape[1]) != self._C:
                return None, ("conv_out 输入通道 %d != 校准通道 %d（结构不符）"
                              % (int(w.shape[1]), self._C))
            u = self._U.to(w.dtype)                   # (C, r)
            w_new = torch.einsum("ocdk,cr->ordk", w, u).contiguous()
            new_conv = nn.Conv2d(self._rank, w.shape[0], w.shape[2],
                                 stride=conv_out.stride, padding=conv_out.padding,
                                 dilation=conv_out.dilation, groups=conv_out.groups,
                                 bias=conv_out.bias is not None)
            new_conv.weight = nn.Parameter(w_new)
            if conv_out.bias is not None:
                new_conv.bias = nn.Parameter(conv_out.bias.data.clone())
            new_conv = new_conv.to(device=w.device, dtype=w.dtype)
            return new_conv, "折叠完成：输入 %d→%d 通道" % (int(w.shape[1]), self._rank)
        except Exception as e:  # stability-gate: allow-swallow（折叠失败 ⇒ 调用方走重建路径）
            logger.debug("[LowRankFeatureCache] fold_into 失败", exc_info=True)
            return None, "折叠异常 %s: %s" % (type(e).__name__, e)

    def stats(self) -> Dict[str, Any]:
        return {"ratio": self._ratio, "calibrated": self._calibrated,
                "C": self._C, "rank": self._rank, "energy": self._energy,
                "samples": self._n_samples, "project_calls": self._project_calls,
                "reconstruct_calls": self._reconstruct_calls,
                "compress_ratio": round(self._C / self._rank, 2) if self._rank else 0.0}


# ══════════════════════════════════════════════════════════════════════
# 3. EncoderOutputCache —— prefix cache 对应物
# ══════════════════════════════════════════════════════════════════════

def make_cache_key(*, arch: str, model_id: str, prompt: str, negative_prompt: str,
                   lora_set: str = "", max_length: int = 77) -> str:
    """缓存键：sha256(schema | arch | model_id | prompt | negative | lora_set | max_length)。

    ★ 键必须含**全部**影响编码输出的变量——少一个字段就是「换 LoRA 出旧图」级 bug。
    schema 版本前缀防将来键格式演进时误命中。
    """
    raw = "|".join(["v1", str(arch), str(model_id), str(prompt),
                    str(negative_prompt), str(lora_set), str(int(max_length))])
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


class EncoderOutputCache:
    """文本编码输出 LRU（进程内，随引擎单例；unload 时清空）。

    驻留策略（VRAM 感知）：put 时空闲显存 ≥ 张量字节×2 + 1GB ⇒ 驻 GPU，否则驻 CPU。
    容量双闸：条数 + 总字节，LRU 淘汰。键构造见 make_cache_key。
    """

    def __init__(self, max_entries: int = 64, max_bytes: int = 2 * 1024 ** 3) -> None:
        self._max_entries = int(max_entries)
        self._max_bytes = int(max_bytes)
        self._store: "OrderedDict[str, Dict[str, Any]]" = OrderedDict()
        self._bytes = 0
        self._hits = 0
        self._misses = 0
        self._evictions = 0
        self._puts = 0
        self._lock = threading.RLock()

    def make_key(self, **kw: Any) -> str:
        return make_cache_key(**kw)

    def get(self, key: str, device: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """命中返回 {prompt_embeds, negative_prompt_embeds[, pooled...]}；未命中 None。"""
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                self._misses += 1
                return None
            self._store.move_to_end(key)      # LRU 刷新
            self._hits += 1
            tensors = entry["tensors"]
            if device:
                return {k: (v.to(device) if hasattr(v, "to") else v)
                        for k, v in tensors.items()}
            return dict(tensors)

    def put(self, key: str, tensors: Dict[str, Any], device: str = "auto") -> bool:
        """存入（device="auto" ⇒ VRAM 感知选驻留；传 "cpu"/"cuda" 强制）。"""
        if not tensors:
            return False
        try:
            nbytes = sum(int(t.numel() * t.element_size())
                         for t in tensors.values() if hasattr(t, "numel"))
        except Exception:  # stability-gate: allow-swallow（字节数算不出 ⇒ 不让缓存进，宁缺勿假）
            logger.debug("[EncoderOutputCache] 字节数计算失败", exc_info=True)
            return False
        if device == "auto":
            device = self._pick_residency(nbytes)
        moved: Dict[str, Any] = {}
        for k, v in tensors.items():
            moved[k] = v.to(device) if (hasattr(v, "to") and device) else v
        with self._lock:
            old = self._store.pop(key, None)
            if old is not None:
                self._bytes -= old["bytes"]
            self._store[key] = {"tensors": moved, "bytes": nbytes,
                                "device": device, "ts": time.time()}
            self._bytes += nbytes
            self._puts += 1
            self._evict_locked()
        return True

    def _pick_residency(self, nbytes: int) -> str:
        """空闲显存够就驻 GPU（阈值 = 张量×2 + 1GB 余量），否则 CPU。"""
        try:
            from app.core.neural.memory_policy import probe_vram

            v = probe_vram()
            if v and float(v.get("free_gb") or 0) * (1024 ** 3) >= nbytes * 2 + 1024 ** 3:
                return "cuda"
        except Exception:  # stability-gate: allow-swallow（探测失败 ⇒ 保守驻 CPU）
            logger.debug("[EncoderOutputCache] 显存探测失败", exc_info=True)
        return "cpu"

    def _evict_locked(self) -> None:
        while (len(self._store) > self._max_entries
               or self._bytes > self._max_bytes) and self._store:
            _k, entry = self._store.popitem(last=False)   # 淘汰最旧
            self._bytes -= entry["bytes"]
            self._evictions += 1

    def clear(self) -> int:
        with self._lock:
            n = len(self._store)
            self._store.clear()
            self._bytes = 0
            return n

    def stats(self) -> Dict[str, Any]:
        with self._lock:
            total = self._hits + self._misses
            return {"entries": len(self._store), "bytes": self._bytes,
                    "hits": self._hits, "misses": self._misses, "puts": self._puts,
                    "evictions": self._evictions,
                    "hit_rate": round(self._hits / total, 4) if total else 0.0,
                    "max_entries": self._max_entries, "max_bytes": self._max_bytes}


_ENCODER_SINGLETON: Optional[EncoderOutputCache] = None
_ENCODER_LOCK = threading.Lock()


def encoder_cache() -> EncoderOutputCache:
    """进程级单例（引擎 unload 时 clear，不跨会话）。"""
    global _ENCODER_SINGLETON
    with _ENCODER_LOCK:
        if _ENCODER_SINGLETON is None:
            _ENCODER_SINGLETON = EncoderOutputCache()
        return _ENCODER_SINGLETON


# ══════════════════════════════════════════════════════════════════════
# 4. VramBlockPool —— paged allocation 对应物
# ══════════════════════════════════════════════════════════════════════

_MIN_CLASS = 1 * 1024 ** 2        # 1MB 最小块
_MAX_CLASS = 1 * 1024 ** 3        # 1GB 以上不按桶（fallback 精确定尺寸）


def _size_class(n: int) -> int:
    """向上取到 2 的幂（1MB~1GB）。"""
    cls = _MIN_CLASS
    while cls < n and cls < _MAX_CLASS:
        cls *= 2
    return min(cls, _MAX_CLASS)


class BlockHandle:
    """池块句柄：一块定长字节缓冲 + copy_from / as_tensor。

    ★ capacity vs n_bytes：缓冲按 **size-class 定容**（复用更大请求不溢出），
    n_bytes 只是本次请求的逻辑长度（copy_from/as_tree 按它切片）。
    """

    __slots__ = ("n_bytes", "device", "size_class", "capacity", "_buf", "_pool", "_freed")

    def __init__(self, buf: Any, n_bytes: int, device: str, size_class: int,
                 pool: "VramBlockPool") -> None:
        self.n_bytes = int(n_bytes)
        self.device = device
        self.size_class = int(size_class)
        self.capacity = int(buf.numel())
        self._buf = buf
        self._pool = pool
        self._freed = False

    def copy_from(self, tree: Any) -> None:
        """把张量（或张量树）的字节复制进本块（n_bytes 必须相等）。"""
        if self._freed:
            raise RuntimeError("池块已 release，禁止再 copy_from")
        import torch

        flat = self._buf[: self.n_bytes]
        off = 0
        for t in _iter_tensors(tree):
            if not t.is_contiguous():
                t = t.contiguous()
            nb = t.numel() * t.element_size()
            flat[off: off + nb].copy_(t.view(torch.uint8).reshape(-1))
            off += nb
        if off != self.n_bytes:
            raise ValueError("池块尺寸不匹配：块 %d vs 树 %d" % (self.n_bytes, off))

    def as_tree(self, template: Any) -> Any:
        """按 template 的张量树形状，把池块字节还原成张量树（view，零拷贝）。"""
        flat = self._buf[: self.n_bytes]
        off = 0

        def _rebuild(node: Any) -> Any:
            nonlocal off
            if isinstance(node, (tuple, list)):
                return type(node)(_rebuild(x) for x in node)
            nb = node.numel() * node.element_size()
            t = flat[off: off + nb].view(node.dtype).reshape(node.shape)
            off += nb
            return t

        return _rebuild(template)

    def release(self) -> None:
        if not self._freed:
            self._freed = True
            self._pool._recycle(self)

    def _mark_reused(self) -> None:
        """从 free list 被重新 acquire 时复位释放标记（池复用路径专用）。"""
        self._freed = False


class VramBlockPool:
    """固定块池（size-class 自由列表）。

    acquire(n_bytes) → BlockHandle；release(handle) 归还复用。
    统计：hit/miss/live_bytes/fallback（>1GB 精确定尺寸，不进桶）。
    """

    def __init__(self, device: str = "cuda") -> None:
        self._device = device
        self._free: Dict[int, List[BlockHandle]] = {}
        self._live: List[BlockHandle] = []
        self._lock = threading.RLock()
        self._acquires = 0
        self._releases = 0
        self._hits = 0
        self._misses = 0
        self._fallbacks = 0
        self._live_bytes = 0

    @property
    def device(self) -> str:
        return self._device

    def acquire(self, n_bytes: int, device: Optional[str] = None) -> BlockHandle:
        dev = device or self._device
        n = int(n_bytes)
        if n <= 0:
            raise ValueError("acquire 需要 n_bytes > 0")
        cls = _size_class(n)
        fallback = n > _MAX_CLASS
        with self._lock:
            self._acquires += 1
            bucket = self._free.get(cls)
            if bucket:
                h = bucket.pop()
                if h.capacity >= n:
                    # 容量是 size_class，逻辑长度随本次请求更新
                    h.n_bytes = n
                    h._mark_reused()         # 复位释放标记（否则 copy_from 被 _freed 拦）
                    self._hits += 1
                    self._live.append(h)
                    self._live_bytes += n
                    return h
                # 容量不足（不该发生：桶键=size-class=容量）⇒ 放回桶尾另分配，
                # 宁可多一块也不溢出写坏别人数据
                bucket.append(h)
            self._misses += 1
            if fallback:
                self._fallbacks += 1
        import torch

        # 桶内块按 size-class 定容（复用同桶更大请求不溢出）；fallback 精确定尺寸
        buf = torch.empty(cls if not fallback else n, dtype=torch.uint8, device=dev)
        h = BlockHandle(buf, n, dev, cls, self)
        with self._lock:
            self._live.append(h)
            self._live_bytes += n
        return h

    def store_tree(self, tree: Any, device: Optional[str] = None) -> Optional[BlockHandle]:
        """把张量树整体存进一个池块，返回句柄（调用方持有模板即可 as_tree 还原）。"""
        nbytes = _tree_nbytes(tree)
        if nbytes <= 0:
            return None
        h = self.acquire(nbytes, device=device or _tree_device(tree) or self._device)
        h.copy_from(tree)
        return h

    def _recycle(self, h: BlockHandle) -> None:
        with self._lock:
            self._releases += 1
            if h in self._live:
                self._live.remove(h)
                self._live_bytes -= h.n_bytes
            # 只回收「容量==size-class」的规整块；fallback 精确定尺寸块不进桶
            # （容量漂移的混合源：1GB 桶里混进 2GB 块会让后续 acquire 溢出判断失真）
            if h.capacity == h.size_class:
                self._free.setdefault(h.size_class, []).append(h)

    def release(self, h: BlockHandle) -> None:
        h.release()

    def clear(self) -> int:
        with self._lock:
            n = len(self._live)
            self._live = []
            self._free = {}
            self._live_bytes = 0
            return n

    def stats(self) -> Dict[str, Any]:
        with self._lock:
            return {"device": self._device, "acquires": self._acquires,
                    "releases": self._releases, "hits": self._hits,
                    "misses": self._misses, "fallbacks": self._fallbacks,
                    "live_blocks": len(self._live), "live_bytes": self._live_bytes,
                    "free_classes": len(self._free),
                    "hit_rate": round(self._hits / self._acquires, 4) if self._acquires else 0.0}


_POOL_SINGLETON: Optional[VramBlockPool] = None
_POOL_LOCK = threading.Lock()


def default_pool(device: str = "cuda") -> VramBlockPool:
    """进程级默认池（首次调用定设备；之后忽略 device 参数防语义漂移）。"""
    global _POOL_SINGLETON
    with _POOL_LOCK:
        if _POOL_SINGLETON is None:
            _POOL_SINGLETON = VramBlockPool(device=device)
        return _POOL_SINGLETON


def release_vram_sequence(*, collect: bool = True) -> Dict[str, Any]:
    """卸载序列收口：gc → synchronize → empty_cache（+ ipc_collect best-effort）。

    ★ 为什么收口（2026-10-24 实测教训）：SD1.5 整卡常驻 → unload → 再 load SDXL，
      显存碎片换页卡死 >22min。正确顺序是「先 gc 掉引用、再 synchronize、
      最后 empty_cache」。该三步骤此前散落在 diffusers_image.unload() 与
      local_video_pipe_cache 两处——本函数是唯一真源，两边都调它。
    """
    out: Dict[str, Any] = {"gc": False, "synced": False, "emptied": False,
                           "ipc": False, "reason": ""}
    if collect:
        try:
            import gc

            gc.collect()
            out["gc"] = True
        except Exception:  # stability-gate: allow-swallow（gc 尽力而为）
            out["reason"] = "gc 失败"
    try:
        import torch

        if torch.cuda.is_available():
            torch.cuda.synchronize()
            out["synced"] = True
            torch.cuda.empty_cache()
            out["emptied"] = True
            try:
                torch.cuda.ipc_collect()
                out["ipc"] = True
            except Exception:  # stability-gate: allow-swallow（IPC 回收是 best-effort：老版本无此 API/无 IPC 句柄时失败无后果）
                pass
        else:
            out["reason"] = "CUDA 不可用（无缓存可清）"
    except Exception as e:  # stability-gate: allow-swallow（torch 未装时无缓存可清）
        out["reason"] = "%s: %s" % (type(e).__name__, e)
    return out


# ══════════════════════════════════════════════════════════════════════
# 5. 引擎侧薄助手：encode_prompt 的 SD/SDXL 签名分流
# ══════════════════════════════════════════════════════════════════════

def encode_prompt_embeds(pipe: Any, *, arch: str, prompt: str, negative_prompt: str,
                         do_cfg: bool, device: Optional[str] = None
                         ) -> Tuple[Optional[Dict[str, Any]], str]:
    """用 pipeline 自己的 encode_prompt 拿 embeds（**实测签名分流，勿猜**）。

    实测（diffusers 0.40.0，.venv312）：
      · SD  : encode_prompt(prompt, device, num_images_per_prompt,
                            do_classifier_free_guidance, negative_prompt=None, ...)
              → (prompt_embeds, negative_prompt_embeds)
      · SDXL: encode_prompt(prompt, prompt_2=None, device=None, ..., negative_prompt=None,
                            negative_prompt_2=None, ...)
              → (prompt_embeds, negative_prompt_embeds, pooled, negative_pooled)
    返回 (dict 或 None, 失败原因)。arch 不在白名单 ⇒ (None, 原因)（诚实失败）。
    """
    a = (arch or "").strip().lower()
    if a not in ENCODER_CACHE_ARCHS:
        return None, "arch %r 无公开 encode_prompt（白名单 %s）" % (
            a, sorted(ENCODER_CACHE_ARCHS))
    dev = device or getattr(pipe, "_execution_device", None) or "cpu"
    try:
        if a == "sdxl":
            pe, npe, pooled, npooled = pipe.encode_prompt(
                prompt=prompt, prompt_2=None, device=dev, num_images_per_prompt=1,
                do_classifier_free_guidance=bool(do_cfg),
                negative_prompt=negative_prompt, negative_prompt_2=None)
            return {"prompt_embeds": pe, "negative_prompt_embeds": npe,
                    "pooled_prompt_embeds": pooled,
                    "negative_pooled_prompt_embeds": npooled}, ""
        pe, npe = pipe.encode_prompt(
            prompt=prompt, device=dev, num_images_per_prompt=1,
            do_classifier_free_guidance=bool(do_cfg),
            negative_prompt=negative_prompt)
        return {"prompt_embeds": pe, "negative_prompt_embeds": npe}, ""
    except Exception as e:  # stability-gate: allow-swallow（编码失败由调用方回退 prompt 原路径）
        logger.debug("[inference_cache] encode_prompt_embeds 失败", exc_info=True)
        return None, "%s: %s" % (type(e).__name__, e)


def pipe_call_with_embeds(pipe: Any, *, arch: str, embeds: Dict[str, Any],
                          guidance_scale: float, height: int, width: int,
                          num_inference_steps: int, generator: Any = None) -> Any:
    """用缓存 embeds 调 pipeline（替代 prompt= 入口；返回 images[0]）。

    SDXL 必须带 pooled 四件套；SD 两件套。签名与 generate() 里的原调用逐键对齐。
    """
    kw: Dict[str, Any] = {
        "prompt_embeds": embeds["prompt_embeds"],
        "negative_prompt_embeds": embeds["negative_prompt_embeds"],
        "guidance_scale": float(guidance_scale),
        "height": int(height), "width": int(width),
        "num_inference_steps": int(num_inference_steps),
    }
    if (arch or "").strip().lower() == "sdxl":
        kw["pooled_prompt_embeds"] = embeds["pooled_prompt_embeds"]
        kw["negative_pooled_prompt_embeds"] = embeds["negative_pooled_prompt_embeds"]
    if generator is not None:
        kw["generator"] = generator
    return pipe(**kw).images[0]


# ══════════════════════════════════════════════════════════════════════
# 内部工具（张量树遍历 / 字节账）
# ══════════════════════════════════════════════════════════════════════

def _iter_tensors(tree: Any) -> List[Any]:
    out: List[Any] = []
    if isinstance(tree, (tuple, list)):
        for x in tree:
            out.extend(_iter_tensors(x))
    elif hasattr(tree, "numel"):
        out.append(tree)
    return out


def _tree_nbytes(tree: Any) -> int:
    return sum(int(t.numel() * t.element_size()) for t in _iter_tensors(tree))


def _tree_device(tree: Any) -> Optional[str]:
    for t in _iter_tensors(tree):
        try:
            return str(t.device)
        except Exception:  # stability-gate: allow-swallow（取不到设备 ⇒ 由调用方默认）
            continue
    return None
