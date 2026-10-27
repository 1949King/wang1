# -*- coding: utf-8 -*-
"""适配器基类 + 组件袋（规范 §3 组件层 / §5 族适配器规范）。

## 组件袋的纪律：把 pipeline 当零件箱，**绝不调 `pipe()`**

一旦调 `pipe()`，执行控制权就回到上游手里，C1 当场失效 —— 而且不会有任何报错，
只会在某天你想"在循环里插一件事"时发现无处落手。所以这里只 `getattr` 组件。

## `validate()` 返回原因，不抛异常

规范 §5.1 明确禁止"用异常代替返回原因"。原因很实在：拒绝路径天天走
（显存不足、模型未下载、族未 verified），抛异常会让调用方只能写 `try/except`
然后丢掉原因，最后用户看到的是"生成失败"，而不是"这个族还没验收"。

## 编码为什么复用上游 `encode_prompt`

C1 要的是**执行控制权**（循环归我们），不是把 tokenizer 也重写一遍。
自己实现 `encode_prompt` 的唯一后果是"多一处与上游漂移的可能"，
而它在 `ParityContract` 里是最难测的一项（tokenizer 细节、clip_skip、pooled 来源）。
这里的选择是：**编码委托上游、循环归本仓库**，并在 `ParityContract` 里
把"编码走了上游"写成显式字段（`encode_delegate=True`），
这样将来真要换编码器（比如断供），契约上看得见这一项要重做。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from app.core.neural.kernel import cfg as CFG
from app.core.neural.kernel import latents as LAT
from app.core.neural.kernel import schedule as SCHED
from app.core.neural.kernel.contracts import (
    AdapterCaps, GenRequest, ParityContract, RunState, UNVERIFIED,
)

logger = logging.getLogger(__name__)


class ComponentBag:
    """从一个已加载的 pipeline 里取零件，**不调用 pipeline 本身**。

    用法::

        bag = ComponentBag.from_pipe(pipe, extras={"scheduler": pipe.scheduler})
        net = bag.require("net")      # 名字由 adapter 给，这里只认 key

    为什么用中性 key（`net` / `decoder` / `encoder`）而不是上游组件名：
    上游改名时（`unet` → `transformer` 已经发生过一次）只需要改 adapter 的一行映射，
    内核与 loop 完全不动 —— 这正是 C3 要的可替换性。
    """

    def __init__(self, parts: Optional[Dict[str, Any]] = None) -> None:
        self._parts: Dict[str, Any] = dict(parts or {})

    @classmethod
    def from_pipe(cls, pipe: Any, extras: Optional[Dict[str, Any]] = None) -> "ComponentBag":
        """按**上游组件名**取值，再由 adapter 用中性 key 注册。"""
        parts: Dict[str, Any] = {}
        for name in ("unet", "transformer", "vae", "text_encoder", "text_encoder_2",
                     "tokenizer", "tokenizer_2", "scheduler", "image_processor",
                     "feature_extractor"):
            obj = getattr(pipe, name, None)
            if obj is not None:
                parts[name] = obj
        if extras:
            parts.update(extras)
        # 保留 pipe 引用仅供 adapter 调上游**编码工具**（encode_prompt / add_time_ids），
        # 明确禁止用它调 `__call__` —— 见本模块 docstring
        bag = cls(parts)
        bag._pipe = pipe
        return bag

    # ── 访问 ──
    def get(self, key: str, default: Any = None) -> Any:
        return self._parts.get(key, default)

    def has(self, key: str) -> bool:
        return self._parts.get(key) is not None

    def require(self, key: str) -> Any:
        obj = self._parts.get(key)
        if obj is None:
            raise KeyError("组件袋缺少 %r（已注册：%s）" % (key, sorted(self._parts)))
        return obj

    def register(self, key: str, obj: Any) -> None:
        self._parts[key] = obj

    @property
    def pipe(self) -> Any:
        """上游 pipeline 引用。**只允许用于编码等工具方法，不许 `__call__`。**"""
        return getattr(self, "_pipe", None)

    def keys(self) -> List[str]:
        return sorted(self._parts)

    def execution_device(self) -> Any:
        """本次运行**真正该把张量放上去**的设备。

        ## 为什么不能只看 `next(model.parameters()).device`

        这个函数的旧实现就是这么写的，而它在 `offload=model` 下拿到的是 **cpu**：
        组件权重常驻 CPU，diffusers 靠 accelerate 的 `CpuOffload` 钩子在 `forward`
        前把模块搬到卡上、结束后搬回去。于是：

          · 我们按"cpu"造 latents / 编码条件；
          · 调 `net(...)` 时钩子照常触发 ⇒ 输出在 **cuda**；
          · `scheduler.step` 里 `sample - sigma * model_output` 当场 device 不匹配。

        报错点在调度器，根因在"设备判据取错了地方"—— 这就是 SDXL 首跑失败的原因
        （SD1.5 走 `whole_gpu`，权重本来就在卡上，所以只跑 SD1.5 时这个坑完全不显形）。

        `_execution_device` 是上游为这件事专门提供的属性（`pipeline_utils.py:1152`），
        注释里写得很直白：offload 之后**只能**从 accelerate 钩子推断。
        """
        pipe = self.pipe
        if pipe is not None:
            try:
                dev = getattr(pipe, "_execution_device", None)
            except Exception:  # stability-gate: allow-swallow（个别自定义 pipeline 上取不到 ⇒ 走权重兜底）
                dev = None
            if dev is not None:
                return dev
        for key in ("net", "unet", "transformer"):
            obj = self._parts.get(key)
            if obj is not None:
                try:
                    return next(iter(obj.parameters())).device
                except (StopIteration, AttributeError):
                    continue
        return "cpu"


@dataclass
class PreparedStep:
    """一步的"模型输入"打包。`raw` 是推进调度器要用的**未缩放**潜变量。

    为什么要分开存：`scale_model_input` 是给网络看的（scale 后），
    而 `scheduler.step` 要的是 scale 前的。混用一个变量的话，
    某些调度器（Euler 系 scale=1 时看不出差别）会一直正常，
    换到 LCM / DPMSolver 才开始慢慢糊 —— 最难定位的那种。
    """
    model_input: Any
    timestep: Any
    raw: Any
    extra: Dict[str, Any] = field(default_factory=dict)


class BaseAdapter:
    """族适配器基类。子类必须填 `family` / `caps` / `parity` 并实现抽象方法。

    默认实现全部是**拒绝**而不是"勉强能跑"：没实现的族应当明确说"不行"，
    而不是用一套通用逻辑跑出一个看起来能看的图。
    """

    family: str = ""
    caps: AdapterCaps = AdapterCaps()
    parity: ParityContract = ParityContract()

    def __init__(self) -> None:
        self.bag: Optional[ComponentBag] = None
        self.pipe: Any = None
        self.notes: List[str] = []

    # ── 绑定 / 体检 ────────────────────────────────────────────
    def bind(self, bag: ComponentBag) -> None:
        """绑定组件袋。**不在这里加载权重**（加载归引擎，规范 §5.1）。"""
        self.bag = bag
        self.pipe = bag.pipe

    def validate_caps(self) -> List[str]:
        """**绑定前**能查的部分：族声明 + caps 跨字段自洽。

        为什么必须与 `validate()` 分开：引擎的顺序是「先体检、后绑定」
        （绑定要先把 pipe 拆成零件袋，而族都认不出来的 adapter 连该拆什么都不知道）。
        如果只有一个 `validate()` 且它头一条就查 `bag is None`，
        那么首次调用必然被拒 —— 这是一个"永远拒绝"的死锁，不是保守。
        """
        bad: List[str] = []
        if not self.family:
            bad.append("adapter 未声明 family")
        bad.extend(self.caps.violations())
        return bad

    def validate(self) -> List[str]:
        """**绑定后**完整体检。返回不可跑的原因；空列表 = 可跑。"""
        if self.bag is None:
            return ["未 bind 组件袋"]
        return self.validate_caps()

    # ── 条件编码（子类实现）────────────────────────────────────
    def encode(self, req: GenRequest, do_guidance: bool = True) -> Any:
        """条件编码。返回 adapter 私有的 cond 对象（内核不解释其结构）。

        `do_guidance` 由引擎按"cfg > 1 且模型支持"算好再传进来 ——
        adapter 不重复判定一次，避免两处判据漂移（判据只能有一个真源）。
        """
        raise NotImplementedError

    # ── 时间轴 ────────────────────────────────────────────────
    def make_timesteps(self, req: GenRequest, cond: Any,
                       scheduler: Any = None) -> Tuple[Any, int]:
        """默认：按步数建表，i2i 按 strength 截尾。子类可覆盖（视频族要按 fps）。"""
        sch = scheduler or (self.bag.require("scheduler") if self.bag else None)
        strength = float(req.strength) if (req.is_i2i() and req.strength) else 1.0
        return SCHED.build_timesteps(
            sch, req.steps or 1,
            device=self._device(), strength=strength)

    # ── 初始潜变量 ────────────────────────────────────────────
    def init_latents(self, req: GenRequest, cond: Any, generator: Any = None,
                     scheduler: Any = None) -> Any:
        net = self.bag.require(self._net_key()) if self.bag else None
        channels = int(getattr(getattr(net, "config", None), "in_channels", 4))
        sch = scheduler or (self.bag.require("scheduler") if self.bag else None)
        sigma = 1.0
        if self.caps.latent_scale == "init_noise_sigma":
            sigma = SCHED.init_noise_sigma(sch)
        return LAT.make(
            batch=max(1, int(req.batch)),
            channels=channels,
            height=req.height, width=req.width,
            latent_scale=self._latent_scale(),
            generator=generator,
            device=self._device(),
            dtype=self._dtype(),
            init_noise_sigma=sigma,
        )

    # ── 每步四件事：默认用通用实现，子类只需覆盖 _net_kwargs ──
    def prepare_step(self, latents: Any, t: Any, state: RunState) -> PreparedStep:
        model_input = CFG.expand_for_guidance(
            latents, self.caps.cfg_batch_multiplier if state.do_guidance else 1)
        sch = self.bag.require("scheduler") if self.bag else None
        if sch is not None and hasattr(sch, "scale_model_input"):
            model_input = sch.scale_model_input(model_input, t)
        return PreparedStep(model_input=model_input, timestep=t, raw=latents)

    def forward(self, prepared: PreparedStep, state: RunState) -> Any:
        net = self.bag.require(self._net_key())
        kwargs = self._net_kwargs(state, prepared)
        out = net(prepared.model_input, prepared.timestep, return_dict=False, **kwargs)
        return out[0]

    def guide(self, noise: Any, prepared: PreparedStep, state: RunState) -> Any:
        if not state.do_guidance:
            # 判据由引擎唯一算过一次（run_state.do_guidance），这里只消费不重判。
            # 少这一步的后果：batch=1 的噪声去 chunk(2) 会 ValueError，
            # 被 combine 的兜底吞掉后"看起来正常"—— 静默降级，正是项目禁止的那种。
            return noise
        return CFG.combine(
            noise,
            mode=self.caps.cfg_mode,
            scale=state.cfg_scale,
            rescale=state.guidance_rescale,
        )

    def step(self, noise: Any, t: Any, prepared: PreparedStep, state: RunState) -> Any:
        sch = self.bag.require("scheduler")
        return sch.step(noise, t, prepared.raw, return_dict=False,
                        **state.extra_step_kwargs)[0]

    # ── 解码（子类实现）──────────────────────────────────────
    def decode(self, latents: Any) -> Any:
        raise NotImplementedError

    # ── 缓存键 ────────────────────────────────────────────────
    def cache_key(self, req: GenRequest) -> tuple:
        """条件缓存键。**必须含全部影响条件的字段**，漏一个就会串图。"""
        return (self.family, self.caps.cond_keys, req.prompt, req.negative_prompt,
                req.width, req.height, int(req.batch))

    # ── 子类可覆盖的小钩子 ────────────────────────────────────
    def _net_key(self) -> str:
        return "net"

    def _net_kwargs(self, state: RunState, prepared: PreparedStep) -> Dict[str, Any]:
        return {}

    def _latent_scale(self) -> int:
        """潜变量相对像素的压缩倍率（SD 系 = 8）。

        取值优先级：pipe 上算好的 `vae_scale_factor` → 2**(len(vae.config.block_out_channels)-1) → 8。
        **不硬编码 8 了事**：将来接 16× 压缩的族（如某些 SD3 变体）时，
        硬编码会让潜变量尺寸错一倍，而尺寸错**不一定报错**（卷积能跑），只会出糊图。
        """
        pipe_factor = getattr(self.pipe, "vae_scale_factor", None)
        if isinstance(pipe_factor, int) and pipe_factor > 0:
            return pipe_factor
        dec = self.bag.get("vae") if self.bag else None
        blocks = getattr(getattr(dec, "config", None), "block_out_channels", None)
        if blocks:
            try:
                return max(1, 2 ** (len(blocks) - 1))
            except Exception:  # stability-gate: allow-swallow（配置异常时退回 SD 系默认 8）
                pass
        return 8

    def _device(self) -> Any:
        """执行设备。**必须**走 `ComponentBag.execution_device()`（offload 下才是对的）。"""
        if self.bag is not None:
            return self.bag.execution_device()
        return "cpu"

    def _dtype(self) -> Any:
        for key in ("net", "unet", "transformer"):
            obj = self.bag.get(key) if self.bag else None
            if obj is not None:
                try:
                    return next(iter(obj.parameters())).dtype
                except StopIteration:
                    continue
        return None


class UnverifiedAdapter(BaseAdapter):
    """未验收族的占位：`validate()` 一定返回原因，内核据此拒绝而不是硬跑。"""

    def __init__(self, family: str, reason: str = "") -> None:
        super().__init__()
        self.family = family
        self.caps = AdapterCaps(verified=UNVERIFIED)
        self._reason = reason or ("族 %s 尚未接入内核（无 adapter 实现）" % family)

    def validate_caps(self) -> List[str]:
        return [self._reason]

    def validate(self) -> List[str]:
        return [self._reason]
