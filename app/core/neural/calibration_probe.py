# -*- coding: utf-8 -*-
"""真实 probe_run 实现：用 diffusers 跑一次最小推理，量出该档位的峰值显存与耗时。

分工
----
``calibration.py``   纯逻辑、零 torch、可单测
**本文件**           执行层，碰 torch / diffusers，只在标定被触发时执行

为什么单列一个文件：`calibration.py` 要能在画布 HTTP 线程里安全 import，
而这里必须 import torch。混在一起就把纯逻辑模块污染了。

测量口径（三条，都有实测教训在后面）
------------------------------------
1. **峰值必须覆盖 load + generate 全过程**。
   `whole_gpu` 档的权重是在 `load()` 时上卡的，若只统计 generate 阶段，
   整卡档会显得比 offload 还省 —— 结论会完全反过来。
2. **每档试跑前先 `unload()` + `empty_cache()` + `reset_peak_memory_stats()`**。
   否则上一档的残留会被算进本档峰值。卸载走 `release_vram_sequence()`（项目单一真源），
   不内联重排步骤 —— 见 `diffusers_image.py:614` 的碎片教训。
3. **走 `_t2i_image()` 而不是 `generate()`**。
   `generate()` 会落盘、写 telemetry、并触发 `_maybe_promote()` 热提升
   （`diffusers_image.py:740`），那个会偷偷改档位，污染测量。
   `_t2i_image()` 是纯出图，正合适。

⚠️ 已知未验证项
---------------
显存读数用 ``torch.cuda.max_memory_allocated()``。在摩尔线程等第三方后端上，
该 API 是否被 ``torchada`` 重定向**尚未验证**（见 `verify_torchada_coverage.py`
的 unverified 清单）。非 NVIDIA 后端首次使用前必须先跑那个脚本确认。
"""

from __future__ import annotations

import logging
import time
from typing import Any, Callable, Dict

from app.core.neural import calibration as CAL

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "sd15-t2i"
DEFAULT_PX = 512
DEFAULT_STEPS = 4
DEFAULT_CFG = 7.0
DEFAULT_PROMPT = "a red apple on a wooden table"
#: 预热档位。选 model_offload 而非 whole_gpu：后者在窄显存卡上可能 OOM，
#: 而预热失败虽不阻断，却会让首档继续含冷启动成本（见 make_image_warmup）。
WARMUP_MODE = CAL.MODE_MODEL_OFFLOAD


# ══════════════════════════════════════════════════════════════════════════
# 档位强制
# ══════════════════════════════════════════════════════════════════════════


def force_mode_policy(mode: str, chunk: int = 1) -> Callable[..., Dict[str, Any]]:
    """构造一个符合 ``pick_memory_policy`` 签名的假策略，强制指定档位。

    返回值结构与 `memory_policy._policy()` 保持一致（键集合稳定），
    免得下游拿到缺键的 dict。
    """
    def _f(*_a: Any, **_kw: Any) -> Dict[str, Any]:
        return {
            "mode": mode,
            "offload": mode != CAL.MODE_WHOLE_GPU,
            "decode_chunk_size": int(chunk),
            "quant": "fp16",
            "floor_gb": None,
            "free_vram_gb": 0.0,
            "total_vram_gb": 0.0,
            "reasons": ["标定探针强制档位 %s" % mode],
            "planned_modes": [],
        }
    return _f


class ModeOverride:
    """上下文管理器：临时把 `memory_policy.pick_memory_policy` 换成强制档位。

    复用手法见 `diffusers_image.py:1083-1093`：`load()` 内部是函数级
    ``from ... import pick_memory_policy``，所以替换**模块属性**能生效。
    退出时无条件恢复，异常也不留下脏 patch。
    """

    def __init__(self, mode: str, chunk: int = 1) -> None:
        self.mode = mode
        self.chunk = chunk
        self._mp: Any = None
        self._orig: Any = None

    def __enter__(self) -> "ModeOverride":
        from app.core.neural import memory_policy as mp
        self._mp = mp
        self._orig = mp.pick_memory_policy
        mp.pick_memory_policy = force_mode_policy(self.mode, self.chunk)
        return self

    def __exit__(self, *exc: Any) -> bool:
        if self._mp is not None and self._orig is not None:
            self._mp.pick_memory_policy = self._orig
        self._mp = None
        self._orig = None
        return False


# ══════════════════════════════════════════════════════════════════════════
# 探针工厂
# ══════════════════════════════════════════════════════════════════════════


def make_image_probe(*, model_id: str = DEFAULT_MODEL,
                     px: int = DEFAULT_PX,
                     steps: int = DEFAULT_STEPS,
                     chunk: int = 1,
                     cfg: float = DEFAULT_CFG,
                     prompt: str = DEFAULT_PROMPT,
                     engine: Any = None,
                     device: str = "cuda") -> CAL.ProbeRun:
    """返回一个可注入 ``Calibrator`` 的 probe_run 回调。

    参数
    ----
    model_id  探针用的模型。默认 SD1.5 —— 小、快、本机已下载。
    px        探针分辨率。标定用小规格省时间，结果靠 ``extrapolate()`` 外推。
    steps     探针步数。4 步足够测显存，不必跑满。
    engine    复用已有引擎实例（内部单例也走过载保护，多档复用时更稳）。

    返回
    ----
    ``(mode, probe_px) -> Trial``。**任何异常都转成 ok=False 的 Trial**，
    绝不向调用方抛出 —— 标定是增强，不是前置依赖（D-A3）。
    """
    cached_engine: Dict[str, Any] = {} if engine is None else {"e": engine}

    def _get_engine() -> Any:
        if "e" not in cached_engine:
            from app.core.neural import diffusers_image as DI
            cached_engine["e"] = DI.get_diffusers_image_engine()
        return cached_engine["e"]

    def _probe(mode: str, probe_px: int) -> CAL.Trial:
        try:
            import torch
        except Exception as e:
            return CAL.Trial(mode=mode, ok=False, error="import torch 失败: %r" % e)

        try:
            from app.core.neural import diffusers_image as DI
        except Exception as e:
            return CAL.Trial(mode=mode, ok=False, error="import diffusers_image 失败: %r" % e)

        if not DI.DiffusersImageEngine.is_downloaded(model_id):
            return CAL.Trial(mode=mode, ok=False,
                             error="模型未下载：%s" % model_id)

        use_px = int(probe_px or px)
        eng = _get_engine()

        # ① 清场：清掉上一档的残留，否则峰值会串档
        try:
            eng.unload()
        except Exception:
            logger.debug("[calibration_probe] 预清理 unload 失败（继续）", exc_info=True)
        torch.cuda.synchronize()
        torch.cuda.empty_cache()
        torch.cuda.reset_peak_memory_stats()

        t0 = time.time()
        outcome: CAL.Trial
        try:
            with ModeOverride(mode, chunk):
                t_load0 = time.time()
                r = eng.load(model_id)
                dt_load = time.time() - t_load0
                if not isinstance(r, dict) or not r.get("ok"):
                    msg = (r or {}).get("message") if isinstance(r, dict) else ""
                    return CAL.Trial(mode=mode, ok=False,
                                     error="load 失败：%s" % (msg or "未知"))

                gen = torch.Generator(device=device).manual_seed(0)
                # 走底层 _t2i_image：不落盘、不 promote、不写 telemetry
                t_gen0 = time.time()
                eng._t2i_image(
                    prompt=prompt, negative_prompt="", cfg=float(cfg),
                    width=use_px, height=use_px, steps=int(steps),
                    generator=gen, model_id=model_id, preset="",
                )
                dt_gen = time.time() - t_gen0
            torch.cuda.synchronize()
            dt = time.time() - t0
            peak = torch.cuda.max_memory_allocated() / 1024 ** 3
            reserved = torch.cuda.max_memory_reserved() / 1024 ** 3
            outcome = CAL.Trial(
                mode=mode, ok=True,
                peak_gb=round(float(peak), 2),
                # seconds 记「首图总耗时」（load+generate）—— 这才是用户感知值，
                # 且各档位的加载耗时差异很大（项目实测 offload 31s vs 整卡 55.7s）。
                # 分项在下面日志里分开打，用于区分「稳态快」与「首次快」。
                seconds=round(float(dt), 2),
                # reserved 一并上报：实测 1024² 下它比 allocated 高 70%，
                # 水位判定由 calibration.effective_peak_gb() 取二者较大值。
                reserved_gb=round(float(reserved), 2),
                # 分项也存下来：预热是否真的消掉了冷启动，只能靠这两个数证明。
                load_seconds=round(float(dt_load), 2),
                gen_seconds=round(float(dt_gen), 2),
            )
            logger.info(
                "[calibration_probe] %s @ %dpx：峰值 %.2fGB（reserved %.2fGB）"
                "｜总 %.2fs = 加载 %.2fs + 生成 %.2fs",
                mode, use_px, peak, reserved, dt, dt_load, dt_gen)
        except Exception as e:
            outcome = CAL.Trial(mode=mode, ok=False, error=repr(e)[:160])
            logger.info("[calibration_probe] %s @ %dpx 失败：%s", mode, use_px, e)
        finally:
            # ② 无论成败都清场，保证下一档从干净状态起步（D-A3）
            try:
                eng.unload()
            except Exception:
                logger.debug("[calibration_probe] 收尾 unload 失败", exc_info=True)
            try:
                torch.cuda.empty_cache()
            except Exception:  # stability-gate: allow-swallow（GPU 缓存清理失败不影响标定结论）
                pass
        return outcome

    return _probe


def make_image_warmup(probe: CAL.ProbeRun, *,
                      mode: str = WARMUP_MODE,
                      px: int = DEFAULT_PX) -> Callable[[], Any]:
    """构造**丢弃式预热**动作（2026-10-28，消冷启动偏差）。

    为什么需要它
    ------------
    阶梯固定从保守档爬到激进档，于是第一档总是替冷启动背锅：
    首次加载要付模型文件冷读、cuDNN/cuBLAS 句柄初始化、分配器首次扩张。
    两次实测的加载耗时 16.62→15.02 / 6.90→4.01 / 2.73→1.07 / 2.52→1.28
    —— 第二次整体快一个量级，那是缓存差异不是档位差异。

    做法：**在阶梯之前跑一次完整的 load + generate 然后丢掉结果**。
    选 ``model_offload`` 做预热（而非 whole_gpu）是为了**安全**：
    whole_gpu 在窄显存卡上可能直接 OOM，预热失败虽是「不阻断」，
    但会留下没暖透的状态；model_offload 是注册表里所有模型的定稿档，
    在过了 8GB 准入的卡上几乎必然成功。

    返回 ``() -> Optional[float]``：成功给该次耗时（秒），失败给 None。
    调用方 ``Calibrator`` 只记账、不参与裁决。
    """
    def _warm() -> Any:
        t = probe(mode, int(px))
        if not isinstance(t, CAL.Trial) or not t.ok:
            return None
        return float(t.seconds or 0.0)

    return _warm


# ══════════════════════════════════════════════════════════════════════════
# 命令行自检（单档探测，不做完整标定）
# ══════════════════════════════════════════════════════════════════════════


def _main() -> int:
    import argparse
    import os

    ap = argparse.ArgumentParser(description="标定探针：单档自检 或 --full 跑完整阶梯")
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--mode", default=CAL.MODE_MODEL_OFFLOAD)
    ap.add_argument("--px", type=int, default=DEFAULT_PX)
    ap.add_argument("--steps", type=int, default=DEFAULT_STEPS)
    ap.add_argument("--chunk", type=int, default=1)
    ap.add_argument("--full", action="store_true",
                    help="跑完整阶梯标定并写档（耗时约 4×单档）")
    ap.add_argument("--no-warmup", action="store_true",
                    help="跳过预热（对比冷启动偏差用；正常标定不要关）")
    args = ap.parse_args()

    os.chdir(r"D:/拾光剪影")
    logging.basicConfig(level=logging.INFO,
                        format="%(levelname)s %(name)s: %(message)s")

    if args.mode not in CAL.LADDER:
        print("非法档位 %r，可选：%s" % (args.mode, ", ".join(CAL.LADDER)))  # stability-gate: allow-print（CLI 标定入口：输出给人看，无调用方消费 stdout）
        return 2

    probe = make_image_probe(model_id=args.model, px=args.px,
                             steps=args.steps, chunk=args.chunk)

    if args.full:
        import torch

        from app.core.neural import device_profile
        prof = device_profile.probe()
        ok, why = CAL.admit(prof)
        print("准入：%s ｜ %s" % (ok, why))  # stability-gate: allow-print（CLI 标定入口：输出给人看，无调用方消费 stdout）
        if not ok:
            return 1
        store = CAL.CalibrationStore()
        # ★ torch 版本必须真传进来，否则档案 key 里是 "?"，
        #   torch 升级后旧档案不会失效（AC-6 的漏洞）。本模块是唯一
        #   允许 import torch 的地方，所以由这里负责填充。
        # ★ 预热：稳定标定默认开（消冷启动偏差），--no-warmup 只在做对照实验时用。
        warm = None if args.no_warmup else make_image_warmup(
            probe, mode=WARMUP_MODE, px=args.px)
        cal = CAL.Calibrator(store, prof, probe_run=probe, probe_px=args.px,
                             torch_version=getattr(torch, "__version__", ""),
                             warmup_run=warm)
        print("水位线：%.2fGB ｜ 探针 %dpx ｜ 预热 %s"  # stability-gate: allow-print（CLI 标定入口：输出给人看，无调用方消费 stdout）
              % (cal.water_line_gb or 0, args.px, "关" if warm is None
                 else "%s@%dpx" % (WARMUP_MODE, args.px)))  # stability-gate: allow-print（CLI 标定入口：输出给人看，无调用方消费 stdout）
        entry = cal.calibrate(args.model, (args.px, args.px), force=True)
        print("=" * 58)  # stability-gate: allow-print（CLI 标定入口：输出给人看，无调用方消费 stdout）
        if entry is None:
            print("标定未产出档案（全档位失败或未准入）")  # stability-gate: allow-print（CLI 标定入口：输出给人看，无调用方消费 stdout）
            return 1
        print("预热耗时 : %s" % ("未预热" if cal.warmup_seconds is None  # stability-gate: allow-print（CLI 标定入口：输出给人看，无调用方消费 stdout）
                                else "%.2fs" % cal.warmup_seconds
                                + ("（失败：%s）" % cal.warmup_error
                                   if cal.warmup_error else "")))  # stability-gate: allow-print（CLI 标定入口：输出给人看，无调用方消费 stdout）
        print("选中档位 : %s" % entry.mode)  # stability-gate: allow-print（CLI 标定入口：输出给人看，无调用方消费 stdout）
        print("占用记账 : %.2fGB（allocated/reserved 取大）" % entry.peak_gb)  # stability-gate: allow-print（CLI 标定入口：输出给人看，无调用方消费 stdout）
        print("首图耗时 : %.2fs" % entry.seconds)  # stability-gate: allow-print（CLI 标定入口：输出给人看，无调用方消费 stdout）
        print("来源     : %s ｜ 可信度 %s" % (entry.source, entry.verdict))  # stability-gate: allow-print（CLI 标定入口：输出给人看，无调用方消费 stdout）
        print("试过     : %s" % ", ".join(entry.tried))  # stability-gate: allow-print（CLI 标定入口：输出给人看，无调用方消费 stdout）
        print("被拒     : %s" % ("；".join(entry.rejected) or "无"))  # stability-gate: allow-print（CLI 标定入口：输出给人看，无调用方消费 stdout）
        print("档案     : %s" % store.path)  # stability-gate: allow-print（CLI 标定入口：输出给人看，无调用方消费 stdout）
        print("=" * 58)  # stability-gate: allow-print（CLI 标定入口：输出给人看，无调用方消费 stdout）
        return 0

    t = probe(args.mode, args.px)
    print("-" * 58)  # stability-gate: allow-print（CLI 标定入口：输出给人看，无调用方消费 stdout）
    print("mode=%-22s ok=%s" % (t.mode, t.ok))  # stability-gate: allow-print（CLI 标定入口：输出给人看，无调用方消费 stdout）
    if t.ok:
        print("peak_gb=%-6s reserved_gb=%-6s seconds=%-6s"  # stability-gate: allow-print（CLI 标定入口：输出给人看，无调用方消费 stdout）
              % (t.peak_gb, t.reserved_gb, t.seconds))
    else:
        print("error=%s" % t.error)  # stability-gate: allow-print（CLI 标定入口：输出给人看，无调用方消费 stdout）
    print("-" * 58)  # stability-gate: allow-print（CLI 标定入口：输出给人看，无调用方消费 stdout）
    return 0 if t.ok else 1


if __name__ == "__main__":
    raise SystemExit(_main())
