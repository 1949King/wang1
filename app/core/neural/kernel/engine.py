# -*- coding: utf-8 -*-
"""内核引擎：把组件袋 + 适配器 + 循环串起来（规范 §3 后端层）。

## 本模块是唯一"知道全部环节"的地方

```
pipe（未加载则先由调用方加载）
  ↓ ComponentBag.from_pipe      —— 取零件，不调 pipe()
adapter.bind(bag)               —— 中性 key 映射
adapter.validate()              —— 不行就说原因，不抛
adapter.encode()                —— 条件（委托上游编码工具保证 bit 一致）
schedule.build_timesteps()      —— 时间轴
adapter.init_latents()          —— 初始潜变量
loop.denoise()                  —— ★ 循环在这里，且只在这里
adapter.decode()                —— 解码成图
```

## 三态开关（规范 §8）

| `SHIGUANG_KERNEL` | 行为 |
|---|---|
| `off`（默认） | 不碰内核，走原 pipe 路径。**必须**在返回里留下原因 |
| `on` | 走内核；失败则回退 pipe 并写明原因 |
| `shadow` | 两条都跑，比较 PSNR 后返回内核结果（用来攒证据，不对外改变画质） |

`SHIGUANG_KERNEL_FAMILIES=sd15,sdxl` 可把内核限定在指定族，其余回退 —— 灰度用。

## 为什么"拒绝"比"尽力而为"重要

`verified != verified` 的族一律拒绝（除非显式 `SHIGUANG_KERNEL_ALLOW_UNVERIFIED=1`）。
理由是项目最反感的那种失败：**能跑但画质悄悄掉了**。没有 parity 数据支撑就跑内核，
等于把"看起来正常"当成"正确"，等用户发现糊了再回查，成本高十倍。
"""
from __future__ import annotations

import logging
import os
from typing import Any, Callable, Dict, List, Optional, Tuple

from app.core.neural.kernel import grad_mode as GRAD
from app.core.neural.kernel import loop as LOOP
from app.core.neural.kernel import schedule as SCHED
from app.core.neural.kernel.adapters.base import BaseAdapter, ComponentBag, UnverifiedAdapter
from app.core.neural.kernel.adapters.sd15 import SD15Adapter
from app.core.neural.kernel.adapters.sdxl import SDXLAdapter
from app.core.neural.kernel.contracts import (
    CONTRACT_VERSION, LOOP_SHIGUANG, GenRequest, KernelReport, RunState, VERIFIED,
)
from app.core.neural.kernel.hooks import Hooks, NullHooks
from app.core.neural.kernel.instrument import Instrument

logger = logging.getLogger(__name__)

#: 模式取值
MODE_OFF = "off"
MODE_ON = "on"
MODE_SHADOW = "shadow"
_MODES = (MODE_OFF, MODE_ON, MODE_SHADOW)

#: 已实现 adapter 的族（**没实现的一律拒绝**，不做"通用兜底"）
_ADAPTERS: Dict[str, Callable[[], BaseAdapter]] = {
    "sd15": SD15Adapter,
    "sdxl": SDXLAdapter,
}


def mode() -> str:
    """当前模式。非法值按 `off` 处理并记 warning（不因为拼错把内核开起来）。"""
    raw = str(os.environ.get("SHIGUANG_KERNEL", MODE_OFF)).strip().lower()
    if raw not in _MODES:
        if raw:
            logger.warning("[kernel] SHIGUANG_KERNEL=%r 非法，按 off 处理（合法：%s）",
                           raw, _MODES)
        return MODE_OFF
    return raw


def allowed_families() -> Optional[Tuple[str, ...]]:
    """`SHIGUANG_KERNEL_FAMILIES` 白名单；None = 不限。"""
    raw = str(os.environ.get("SHIGUANG_KERNEL_FAMILIES", "")).strip()
    if not raw:
        return None
    return tuple(x.strip().lower() for x in raw.split(",") if x.strip())


def family_allowed(family: str) -> bool:
    allow = allowed_families()
    return True if allow is None else (str(family).lower() in allow)


def _allow_unverified() -> bool:
    return str(os.environ.get("SHIGUANG_KERNEL_ALLOW_UNVERIFIED", "")).strip().lower() \
        in ("1", "true", "yes", "on")


def adapter_for(family: str) -> BaseAdapter:
    """按族名取 adapter；不认识就返回一个"一定拒绝"的占位。"""
    factory = _ADAPTERS.get(str(family).lower())
    if factory is None:
        return UnverifiedAdapter(str(family), "族 %s 无内核 adapter 实现" % family)
    return factory()


def supported_families() -> List[str]:
    return sorted(_ADAPTERS)


# ══════════════════════════════════════════════════════════════════
# 主入口
# ══════════════════════════════════════════════════════════════════

def run(
    *,
    pipe: Any,
    req: GenRequest,
    generator: Any = None,
    hooks: Any = None,
    adapter: Optional[BaseAdapter] = None,
    measure_vram: bool = True,
) -> Dict[str, Any]:
    """跑一次内核生成。

    返回::

        {"ok": bool, "image": PIL|None, "report": KernelReport,
         "breakdown": dict, "cancelled": bool, "message": str, "warnings": [...]}

    **永不抛异常**：所有失败都变成 `ok=False` + `report.rejected_reason`。
    调用方（`diffusers_image.generate`）据此回退到 pipe 路径。
    """
    warnings: List[str] = []
    ad = adapter or adapter_for(req.family)

    rep = KernelReport(used=False, family=req.family)
    # 1) 开关与族白名单
    if mode() == MODE_OFF:
        rep.rejected_reason = "SHIGUANG_KERNEL=off（内核未启用）"
        return _fail(rep, "内核未启用")
    if not family_allowed(req.family):
        rep.rejected_reason = "族 %s 不在 SHIGUANG_KERNEL_FAMILIES 白名单" % req.family
        return _fail(rep, rep.rejected_reason)

    # 2) 契约体检（顺序：caps 自洽 → verified → 绑定 → 组件齐全）
    bad = ad.validate_caps()
    if bad:
        rep.rejected_reason = "适配器拒绝：" + "；".join(bad)
        return _fail(rep, rep.rejected_reason)
    if ad.caps.verified != VERIFIED and not _allow_unverified():
        rep.rejected_reason = ("族 %s 未验收（verified=%s）；如确需试跑请设 "
                               "SHIGUANG_KERNEL_ALLOW_UNVERIFIED=1"
                               % (req.family, ad.caps.verified))
        return _fail(rep, rep.rejected_reason)

    ins = Instrument(measure_vram=measure_vram).start()
    try:
        # 3) 绑定组件袋
        bag = ComponentBag.from_pipe(pipe, extras={
            "scheduler": getattr(pipe, "scheduler", None),
        })
        ad.bind(bag)
        bad = ad.validate()
        if bad:
            rep.rejected_reason = "绑定后体检失败：" + "；".join(bad)
            return _fail(rep, rep.rejected_reason)

        # 4) 是否做 CFG（**唯一判据**）
        do_guidance = _do_guidance(req, bag)

        # 5) 条件编码
        #    推理态：文本编码器权重带梯度，不关图的话 embeds 会带一张图进循环。
        with GRAD.inference():
            cond = ad.encode(req, do_guidance)
        ins.lap("encode")

        # 6) 时间轴
        steps_req = int(req.steps) if req.steps else _default_steps(bag)
        timesteps, n_eff = SCHED.build_timesteps(
            bag.require("scheduler"), steps_req, device=ad._device(),
            strength=(float(req.strength) if req.is_i2i() and req.strength else 1.0))

        # 7) 初始潜变量
        latents = ad.init_latents(req, cond, generator=generator,
                                 scheduler=bag.require("scheduler"))

        # 8) 运行态
        state = RunState(
            timesteps=timesteps, latents=latents,
            cfg_scale=float(req.cfg or 1.0), do_guidance=do_guidance,
            guidance_rescale=0.0,
            extra_step_kwargs=SCHED.extra_step_kwargs(
                bag.require("scheduler"), generator=generator),
            latent_scale=ad._latent_scale(),
            ctx=cond,
            steps=n_eff,
        )

        hook = hooks if hooks is not None else NullHooks()
        out = LOOP.denoise(ad, state, hooks=hook, instrument=ins)
        ins.lap("loop")

        if out.cancelled:
            rep.used = True
            rep.steps = out.step_count
            rep.breakdown = ins.breakdown().to_dict()
            return {"ok": False, "image": None, "report": rep,
                    "breakdown": rep.breakdown, "cancelled": True,
                    "message": "已取消（完成 %d/%d 步）" % (out.step_count, n_eff),
                    "warnings": warnings}

        # 9) 解码
        #    推理态：**必须**。VAE 权重带梯度 ⇒ 不关图时出图带 requires_grad，
        #    而 `image_processor.postprocess` 内部 `numpy()` 会直接抛
        #    "Can't call numpy() on Tensor that requires grad"。
        with GRAD.inference():
            image = ad.decode(out.latents)
        ins.lap("decode")

        rep.used = True
        rep.loop_owner = LOOP_SHIGUANG
        rep.steps = out.step_count
        rep.breakdown = ins.breakdown().to_dict()
        if ad.notes:
            warnings.extend(ad.notes)
        return {"ok": True, "image": image, "report": rep,
                "breakdown": rep.breakdown, "cancelled": False,
                "message": "内核生成完成（%d 步）" % out.step_count,
                "warnings": warnings}

    except Exception as e:  # stability-gate: allow-swallow（内核是新增路径：任何异常都必须降级为"回退 pipe"而不是中断用户生成）
        logger.debug("[kernel] 运行失败", exc_info=True)
        rep.rejected_reason = "内核异常：%s: %s" % (type(e).__name__, e)
        return _fail(rep, rep.rejected_reason)


def _fail(rep: KernelReport, message: str) -> Dict[str, Any]:
    return {"ok": False, "image": None, "report": rep, "breakdown": {},
            "cancelled": False, "message": message, "warnings": []}


def _do_guidance(req: GenRequest, bag: ComponentBag) -> bool:
    """CFG 判据：`cfg > 1` **且** 主网络没有 `time_cond_proj_dim`。

    与上游一致（`pipeline_*.py` 的 `do_classifier_free_guidance` 属性）。
    第二条不是"顺带"：带 `time_cond_proj_dim` 的模型（如 LCM）把引导强度
    编码进 `timestep_cond`，此时再拼 batch 会**双重引导**。
    """
    if float(req.cfg or 0.0) <= 1.0:
        return False
    net = bag.get("net") or bag.get("unet") or bag.get("transformer")
    cfg = getattr(net, "config", None)
    return getattr(cfg, "time_cond_proj_dim", None) is None


def _default_steps(bag: ComponentBag) -> int:
    sch = bag.get("scheduler")
    return int(getattr(sch, "num_inference_steps", 20) or 20)


# ══════════════════════════════════════════════════════════════════
# 诊断
# ══════════════════════════════════════════════════════════════════

def describe() -> Dict[str, Any]:
    """只读快照（诊断面板 / 体检脚本用）。"""
    return {
        "contract_version": CONTRACT_VERSION,
        "mode": mode(),
        "families_allowed": allowed_families(),
        "builtin_families": supported_families(),
        "allow_unverified": _allow_unverified(),
        "adapters": {
            fam: {"caps": dict(ad_vars(adapter_for(fam)))}
            for fam in supported_families()
        },
    }


def ad_vars(ad: BaseAdapter) -> Dict[str, Any]:
    c = ad.caps
    return {
        "cfg_mode": c.cfg_mode,
        "latent_rank": c.latent_rank,
        "latent_scale": c.latent_scale,
        "vae_decode": c.vae_decode,
        "scheduler_family": c.scheduler_family,
        "verified": c.verified,
        "violations": c.violations(),
    }


def make_hooks(cancel_token: Any = None,
               progress: Any = None,
               collect_steps: bool = False) -> Hooks:
    """便捷构造。取消 token 传 None 时不会取消（但仍然可控）。"""
    return Hooks(cancel_token=cancel_token, progress=progress,
                 collect_steps=collect_steps)
