# -*- coding: utf-8 -*-
"""契约层：本仓库自有、版本化（规范 §4）。

## 这个文件为什么一个字都不 import torch

规范 §3 硬线 H3：**`kernel/engine.py` 之外，内核层顶层不许 import torch**。
理由不是洁癖：契约要能被单测、被守卫、被前端诊断工具在没有显卡的机器上 import。
一旦顶层 `import torch`，`check_kernel_*.py` 这类静态守卫就得先装 2GB 依赖才能跑，
"契约校验"本身变成重操作，最后必然没人跑。

所以本文件只有：`dataclasses` / `typing` / `enum` 级别的纯 Python。
张量一律以 `Any` 标注 —— **故意不写 `torch.Tensor`**，那是上游类型，写进来就把
契约钉在上游上了（C2 契约所有权的反面）。

## 契约变更有版本号

`CONTRACT_VERSION` 是给下游看的：破坏性变更升 MAJOR（删字段/改语义/改必填），
新增可选字段升 MINOR。升了就要在 `docs/CHANGELOG.md` 写迁移说明（规范 §12）。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Tuple

#: 契约版本。规范 §4.1。
#: 1.0 → 1.1（2026-10-28）：新增可选字段 `GenRequest.batch` 与
#:   `KernelReport.breakdown` 的两个键，属 MINOR，不写迁移。
CONTRACT_VERSION = "1.1"

#: 内核自身的 loop_owner 值（三态见规范 §6.1）
LOOP_SHIGUANG = "shiguang"
LOOP_UPSTREAM = "upstream"

#: verified 三态（与 `model_family` 同词表，不另造）
VERIFIED = "verified"
UNVERIFIED = "unverified"
BLOCKED = "blocked"


# ══════════════════════════════════════════════════════════════════
# 请求
# ══════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class GenRequest:
    """一次生成请求，**族无关**（规范 §4.2）。

    纪律（写在类型里，不靠注释约束）：
      · 本结构只放"请求事实"，**不放实现参数**。`decode_chunk_size`、`branch_id`
        这类由策略算完再写进 RunState 的东西，一律不进来。
        原因是可复现性：实现参数进请求，同 seed 同 prompt 就会因为参数来源不同而漂。
      · 所有"0 表示取默认"的字段都在 adapter 里翻译，内核不解释默认值。
    """
    family: str
    model_id: str
    prompt: str = ""
    negative_prompt: str = ""
    image_path: str = ""
    width: int = 0
    height: int = 0
    steps: int = 0
    cfg: float = 0.0
    seed: int = 0
    preset: str = ""
    strength: float = 0.0
    # ── 视频族专属（图像族忽略）──
    frames: int = 0
    fps: int = 0
    motion_bucket_id: int = 0
    noise_aug_strength: float = 0.0
    # ── 通用 ──
    precision: str = "fp16"
    batch: int = 1
    out_path: str = ""

    def is_i2i(self) -> bool:
        return bool(self.image_path)


# ══════════════════════════════════════════════════════════════════
# 能力声明
# ══════════════════════════════════════════════════════════════════

#: cfg 组合方式的白名单（规范 §4.3）
CFG_MODES = ("cat", "two_pass", "none")
#: 潜变量缩放方式
LATENT_SCALES = ("init_noise_sigma", "none", "add_noise")
#: VAE 解码方式
VAE_DECODES = ("scalar_factor", "per_channel_mean_std", "chunked_temporal")
#: 调度族
SCHEDULER_FAMILIES = ("eps", "v_prediction", "edm", "flow_match")
#: 时间步形态
TIMESTEP_KINDS = ("scalar", "per_token")

#: 图像族（`latent_rank=4`、文生图）的 **parity 基线字段**（规范 §5.2 第 2 条）。
#:
#: 为什么放在契约层而不是各 adapter 里各写一份：守卫与单测都要判"这张表填完了没有"，
#: 若两处各有一份清单，加一项时只会改一处 —— 于是守卫绿、测试也绿，而实际没填。
#: 族可以有**额外**字段（SDXL 的 `added_cond_kwargs` / `time_ids_*`），但基线一个都不能少。
BASE_PARITY_FIELDS: Tuple[str, ...] = (
    "scale_model_input",
    "init_noise_sigma_once",
    "cfg_order",
    "clip_skip",
    "encode_delegate",
    "latent_scale",
    "randn_source",
    "timestep_cond",
    "vae_scale_before_decode",
    "decode_postprocess",
)


@dataclass(frozen=True)
class AdapterCaps:
    """族能力声明，**声明式**（规范 §4.3）。

    这些值不是注释，是内核据此决定 batch 维度、是否可合并 CFG、能不能预计算调度表的依据。
    默认值一律是"不声明的保守值"，**不是"支持"** —— 与 `EngineSpec` 的 5 字段同一口径。
    """
    cfg_mode: str = "none"
    cfg_batch_multiplier: int = 1
    allow_cfg_merge: bool = False
    cond_keys: Tuple[str, ...] = ()
    timestep_kind: str = "scalar"
    latent_rank: int = 4
    latent_scale: str = "none"
    vae_decode: str = "scalar_factor"
    scheduler_family: str = "eps"
    verified: str = UNVERIFIED

    def violations(self) -> List[str]:
        """自洽性检查。空列表 = 可跑。

        为什么放在契约层而不是守卫里：**内核要用它做运行时判断**。
        守卫只在提交时跑一次，运行时才是"每一张图都要过"的地方。
        """
        bad: List[str] = []
        if self.cfg_mode not in CFG_MODES:
            bad.append("cfg_mode=%r 不在白名单 %s" % (self.cfg_mode, CFG_MODES))
        if self.latent_scale not in LATENT_SCALES:
            bad.append("latent_scale=%r 不在白名单 %s" % (self.latent_scale, LATENT_SCALES))
        if self.vae_decode not in VAE_DECODES:
            bad.append("vae_decode=%r 不在白名单 %s" % (self.vae_decode, VAE_DECODES))
        if self.scheduler_family not in SCHEDULER_FAMILIES:
            bad.append("scheduler_family=%r 不在白名单 %s"
                       % (self.scheduler_family, SCHEDULER_FAMILIES))
        if self.timestep_kind not in TIMESTEP_KINDS:
            bad.append("timestep_kind=%r 不在白名单 %s"
                       % (self.timestep_kind, TIMESTEP_KINDS))
        if self.verified not in (VERIFIED, UNVERIFIED, BLOCKED):
            bad.append("verified=%r 不在三态里" % (self.verified,))

        # 跨字段自洽（规范 §5.2 第 1 条）
        if self.cfg_mode == "cat" and self.cfg_batch_multiplier != 2:
            bad.append("cfg_mode=cat 必须 cfg_batch_multiplier=2（当前 %d）"
                       % self.cfg_batch_multiplier)
        if self.cfg_mode == "none" and self.cfg_batch_multiplier != 1:
            bad.append("cfg_mode=none 必须 cfg_batch_multiplier=1（当前 %d）"
                       % self.cfg_batch_multiplier)
        if self.allow_cfg_merge and self.cfg_mode != "two_pass":
            bad.append("allow_cfg_merge 只对 two_pass 有意义")
        if self.latent_rank == 5 and self.vae_decode != "chunked_temporal":
            bad.append("latent_rank=5 必须 vae_decode=chunked_temporal（视频逐块解码）")
        if self.latent_rank not in (4, 5):
            bad.append("latent_rank=%r 只允许 4 或 5" % (self.latent_rank,))
        return bad


@dataclass(frozen=True)
class ParityContract:
    """等价性契约：把"漏了会掉 PSNR 但不报错"的语义逐条写成判据（规范 §4.4）。

    **这张表是验收判据的来源，不是注释。** 新族准入必须先填完它（§5.2 第 2 条）。
    """
    #: 字段名 → 期望值/说明。单测逐条对照，缺一条就算没填完。
    fields: Dict[str, Any] = field(default_factory=dict)
    #: 逐 step latents 张量对照容差
    tensor_rtol: float = 1e-3
    #: 出图对照 PSNR 下限（只在同后端内比较，规范 §6.4）
    psnr_min_db: float = 35.0

    def missing(self, required: Tuple[str, ...]) -> List[str]:
        """required 里有、本契约没填的字段名。"""
        return [k for k in required if k not in self.fields]


# ══════════════════════════════════════════════════════════════════
# 运行态
# ══════════════════════════════════════════════════════════════════

@dataclass
class RunState:
    """一次去噪运行的**全部可变状态**。

    为什么单独一个对象：`loop.py` 要保持族无关（H1），它不能知道
    "条件张量叫什么"。所有族相关的东西都塞进 `ctx`，循环只负责
    "拿步骤 → 前向 → 引导 → 推进"四件事，从不拆开 `ctx` 看里面。

    字段命名也刻意族无关：`latent_scale` 而不是 `vae_scale_factor`、
    `condition` 而不是 `prompt_embeds` —— 因为 H1 守卫扫的是**文件内容**，
    写一个 `vae` 进去就红了。
    """
    timesteps: Any
    latents: Any
    cfg_scale: float = 1.0
    do_guidance: bool = False
    guidance_rescale: float = 0.0
    extra_step_kwargs: Dict[str, Any] = field(default_factory=dict)
    latent_scale: int = 8
    #: adapter 私有负载（条件张量等），**内核不解释**
    ctx: Any = None
    #: 本次实际步数（供结果回报；与 len(timesteps) 可能因调度器 order 不同）
    steps: int = 0


# ══════════════════════════════════════════════════════════════════
# 结果
# ══════════════════════════════════════════════════════════════════

@dataclass
class KernelReport:
    """→ `result["kernel"]`（规范 §4.5）。

    铁律：`used=False` 时 **必须**有 `rejected_reason`。
    静默回退 = 缺陷（规范 §11 可观测门），所以这个字段不是可选的礼貌字段。
    """
    used: bool
    family: str = ""
    loop_owner: str = LOOP_UPSTREAM
    steps: int = 0
    rejected_reason: str = ""
    breakdown: Dict[str, Any] = field(default_factory=dict)
    contract_version: str = CONTRACT_VERSION

    def to_dict(self) -> Dict[str, Any]:
        if not self.used and not self.rejected_reason:
            # 自证式约束：宁可报一条明显的内部错误，也不许出现"用了 False 却没原因"
            self.rejected_reason = "内部错误：未使用内核但未给出 rejected_reason"
        return {
            "used": self.used,
            "family": self.family,
            "loop_owner": self.loop_owner,
            "steps": int(self.steps),
            "rejected_reason": self.rejected_reason,
            "breakdown": dict(self.breakdown),
            "contract_version": self.contract_version,
        }


@dataclass
class DenoiseOutput:
    """内核跑完的产物（解码前）。encoder 交给 adapter 做解码。"""
    latents: Any
    state: RunState
    cancelled: bool = False
    step_count: int = 0
