# -*- coding: utf-8 -*-
"""量化描述符 + 实测质量台账 —— 设计稿 §12.4「标准 4」的落地（2026-10-27）

为什么要有这个文件
==================
`docs/_reports/2026-10-24-DeepSeek推理理念移植至diffusers栈设计方案.md` §12.3 写的是
**预期**（SDXL 6.46GB → ~3.3GB），而 2026-10-27 真机实测是：

    SDXL  UNet 4.78GB → 2.71GB（-43.4%，显存目标成立）
          但 PSNR **5.29 dB**，输出整张全黑（mean=0, std=0）⇒ 画质崩

没有台账时，这种「省了显存但废了出图」的方案只能靠记忆传播，下一个人（或下一个 agent）
还会再试一遍、再崩一次。本文件把「方案 + 实测证据 + 判定」固化成代码资产。

三条纪律
========
1. **描述符是唯一真相源**：scheme / group_size / version 等参数只在这里定义，
   调用点禁止各自硬编码（否则又是「三种量化三套配置」的孤岛）。
2. **每条证据必须带实测数字与来源脚本**，禁止写「预计」「据说」。测不出就写 unverified。
3. **判定三态**：``rejected`` > ``unverified`` > ``verified``，取最坏态。
   只有 ``verified`` 才允许进主路径；``rejected`` 方案除非有新的实测证据推翻，否则不得启用。

本模块**纯 stdlib、零 torch 依赖**（与 engine_registry 同戒律：画布 HTTP 线程可安全调用），
也不做任何量化执行——执行在 diffusers_image / 未来 quant_exec，本模块只做「准入裁决」。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

# ── 判定态 ──────────────────────────────────────────────────────────
VERDICT_VERIFIED = "verified"        # 有实测、质量过门槛 ⇒ 可进主路径
VERDICT_UNVERIFIED = "unverified"    # 实现存在但没实测过 ⇒ 默认不得启用
VERDICT_REJECTED = "rejected"        # 有实测且不合格 ⇒ 禁止启用

_SEVERITY = {VERDICT_VERIFIED: 0, VERDICT_UNVERIFIED: 1, VERDICT_REJECTED: 2}

#: 进主路径的最低画质门槛（PSNR, dB）。同 prompt 同 seed 对照 fp16 基线。
#: 35dB 是业界常用「肉眼难辨」线；低于 30dB 基本能看出差别。
#:
#: ⚠️ 2026-11-01 实证修正：**这条门槛不适用于扩散模型的权重量化**。
#:    扩散去噪会把权重里 0.4% 的扰动放大成完全不同的高频细节，
#:    实测「fp16 + 0.4% 随机噪声」同 seed 出图的 PSNR 只有 14.12dB（低于 35dB 门槛一大截），
#:    而 GGUF Q8_0 是 17.14dB —— 两者同量级，说明 dB 数反映的是**扩散模型的敏感度**，
#:    不是「量化实现好不好」。因此判量化该看 :attr:`QuantEvidence.lowfreq_psnr_db`
#:    （低频结构）+ 肉眼观感；PSNR 只保留给非扩散场景（如 VAE 重建、图像滤镜）使用。
DEFAULT_MIN_PSNR_DB = 35.0

#: 扩散模型专用门槛：k× 降采样后的低频 PSNR（dB）。
#:
#: 为什么单独一条：逐像素 PSNR 在扩散采样上无效（见上），而「结构有没有崩」是可以量的。
#: 取 20dB 的依据是本机实测的**对照组**而不是拍脑袋：
#:   · fp16 + 0.4% 高斯噪声（完全不用量化）同 seed 出图 ⇒ 低频 17.95dB
#:   · GGUF Q8_0 ⇒ 低频 21.31dB   · FP8 ⇒ 低频 24.56dB
#: 即「比随机微扰更好」这条线落在 20dB 附近。⚠️ 样本只有 1 张图 / 1 个 seed，
#: 依据偏薄——所以两条准入函数并存，调用方自己选口径，别把这条当金标准。
DEFAULT_MIN_LOWFREQ_PSNR_DB = 20.0


@dataclass(frozen=True)
class QuantDescriptor:
    """标准 4：量化描述符（单一真相源）。"""

    scheme: str                      # fp16 | fp8 | int8wo | int4wo | nf4
    scope: str = "weights"           # weights | weights+act
    group_size: Optional[int] = None
    calibration: str = "none"        # none | static | dynamic
    backend: str = "torchao"         # torchao | native | gguf | nunchaku
    config_expr: str = ""            # 实际传入 torchao 的构造表达式（可读即文档）
    note: str = ""


@dataclass(frozen=True)
class QuantEvidence:
    """一次真机实测。所有数字都是跑出来的，不是估的。"""

    scheme: str
    model_id: str
    unet_gb_before: float
    unet_gb_after: float
    peak_gb_before: Optional[float]  # None = 该项未测
    peak_gb_after: Optional[float]   # None = 该项未测
    wall_ratio: Optional[float]      # 量化耗时 / 基线耗时（1.0 = 持平；None = 未测）
    psnr_db: Optional[float]         # 同 prompt 同 seed 对照 fp16；None = 尚未做画质对照
    verdict: str
    reason: str
    source: str                      # 产出这条数据的脚本（可复跑）
    measured_at: str
    #: k× 平均池化后的低频 PSNR —— 只看构图/色彩/明暗，忽略高频相位。
    #: 为什么需要它：扩散采样的去噪过程会把「权重 0.4% 的扰动」放大成完全不同的
    #: 高频细节，逐像素 PSNR 因此必然极低（实测 14~17dB，**与扰动来自哪里无关**）。
    #: 拿 PSNR 卡扩散量化等于用尺子量温度。低频指标才反映「结构有没有崩」。
    lowfreq_psnr_db: Optional[float] = None
    #: 该条证据的结论是否已被后续实测**推翻**（环境变了 / 测法有误）。
    #: 标记为 True 后不再参与准入裁决，但仍留在台账里供追溯——
    #: 删掉历史会让下一个人再踩一遍同样的坑。
    superseded: bool = False


# ── 描述符登记（唯一真相源）──────────────────────────────────────────
DESCRIPTORS: Tuple[QuantDescriptor, ...] = (
    QuantDescriptor(
        scheme="fp16", scope="weights", calibration="none", backend="native",
        config_expr="dtype=torch.float16（引擎默认）",
        note="基线。diffusers 默认精度，无额外依赖。",
    ),
    QuantDescriptor(
        scheme="fp8", scope="weights", calibration="dynamic", backend="torchao",
        config_expr="quantize_(pipe.unet, Float8WeightOnlyConfig())",
        note="已在 diffusers_image.load() 接线（apply_fp8_quantization）。"
             "⚠️ sm89 上 torch._scaled_mm 报 CUBLAS_STATUS_NOT_SUPPORTED，走反量化回退，无加速。",
    ),
    QuantDescriptor(
        scheme="int8wo", scope="weights", group_size=None, calibration="dynamic",
        backend="torchao",
        config_expr="quantize_(pipe.unet, Int8WeightOnlyConfig(version=1))",
        note="PerRow 粒度。只作用于 nn.Linear，Conv2d 不动 ⇒ 收益上限受卷积占比限制。",
    ),
    QuantDescriptor(
        scheme="int8wo_v2", scope="weights", group_size=None, calibration="dynamic",
        backend="torchao",
        config_expr="quantize_(pipe.unet, Int8WeightOnlyConfig(version=2))",
        note="存储走 qdata(int8)+scale。注意 torchao 0.16 断言："
             "version=2 只支持 group_size=None（传 32 会 AssertionError）。",
    ),
    QuantDescriptor(
        scheme="int4wo", scope="weights", group_size=128, calibration="dynamic",
        backend="torchao",
        config_expr="quantize_(pipe.unet, Int4WeightOnlyConfig(group_size=128))",
        note="⚠️ Windows 上不可用：torchao 0.16 的 int4 走 mslk，"
             "而 mslk 的 win 轮子是纯 Python 空壳（0 个 .pyd）且强依赖 triton。实测装上即崩 torchao 导入。",
    ),
    QuantDescriptor(
        scheme="gguf_q8_0", scope="weights", calibration="dynamic", backend="gguf",
        config_expr="gguf_loader.apply_to_unet(unet, path)（命名转换走 diffusers 官方 convert_ldm_unet_checkpoint）",
        note="纯 Python、零编译、跨设备通吃（不挑 GPU 代际，这是 fp8 做不到的）。"
             "**已接进生产加载路径**：`DiffusersImageEngine.request_gguf(path)` → `load()` 内装填。"
             "两种模式：eager（默认，省硬盘/下载量，**不省显存**）与 lazy"
             "（`gguf_lazy.apply_to_unet_lazy`，权重以量化字节常驻、forward 时 GPU 还原，"
             "实测 SD1.5 峰值 2.81→1.07GB **省 62%**，代价慢 2.63×，输出与 eager 逐位相同）。",
    ),
    QuantDescriptor(
        scheme="gguf_q4_k", scope="weights", calibration="dynamic", backend="gguf",
        config_expr="同上，只是权重文件换成 Q4_K",
        note="内核已逐元素对齐（rel=0），但**未做端到端装填与画质验收** ⇒ 只登记不启用。"
             "理论显存账：SDXL UNet 2.39G 参数 × 0.5625 B ≈ 1.34GB（fp16 为 4.78GB）。",
    ),
)

_DESC_BY_SCHEME: Dict[str, QuantDescriptor] = {d.scheme: d for d in DESCRIPTORS}


# ── 实测证据台账（2026-10-27 真机，RTX 4060 Laptop 8GB / torch 2.6.0+cu124 / torchao 0.16.0）──
#    复跑：D:/拾光剪影/.venv312/Scripts/python.exe <工作目录>/verify_int8_diffusers.py [sd15-t2i|sdxl-t2i]
EVIDENCE: Tuple[QuantEvidence, ...] = (
    QuantEvidence(
        scheme="fp8", model_id="sdxl-t2i（未出图，只验证算子在不在）",
        unet_gb_before=4.78, unet_gb_after=4.78,
        peak_gb_before=None, peak_gb_after=None,
        wall_ratio=None, psnr_db=None,
        verdict=VERDICT_UNVERIFIED,
        reason="【已被 2026-11-01 实测推翻，superseded】当时结论：能跑通但 "
               "torch._scaled_mm 报 CUBLAS_STATUS_NOT_SUPPORTED ⇒ 走反量化回退、无加速。"
               "真因后来查明是 **torchao 0.16.0 的 cpp extensions 没编译**"
               "（导入时就报 `Skipping import of cpp extensions due to incompatible torch version`），"
               "不是 torch/CUBLAS 不支持 sm89。降到 torchao 0.12.0 后 _scaled_mm 直接跑通。"
               "此条仅作追溯保留，不参与准入。",
        source="torchao_check.py（float8 动态量化项）+ 独立 venv 直测 _scaled_mm",
        measured_at="2026-10-27",
        superseded=True,
    ),
    QuantEvidence(
        scheme="fp8", model_id="sd15-t2i（512²·20步·同 seed·whole-GPU）",
        unet_gb_before=1.72, unet_gb_after=1.45,
        peak_gb_before=2.81, peak_gb_after=2.54,
        wall_ratio=0.90, psnr_db=17.73,
        verdict=VERDICT_UNVERIFIED,
        reason="2026-11-01 重测（torchao 0.16.0 → 0.12.0 之后）：**FP8 真的能用了，且是净收益**。"
               "① `torch._scaled_mm` 在 sm89 上执行成功（不再 CUBLAS_NOT_SUPPORTED）；"
               "② 出图耗时 3.92s → 3.54s（**快 10%**）；③ 峰值显存 2.81 → 2.54GB（**-9.6%**）；"
               "④ 画质 PSNR 17.73dB / 低频(8×) 24.56dB —— 与 GGUF Q8_0（21.31dB）同档，"
               "且都优于「fp16 + 0.4% 噪声」对照组的 17.95dB。"
               "只省 9.6% 是因为 Float8WeightOnlyConfig **只作用 nn.Linear**，"
               "SD1.5 UNet 里 Conv2d 占 1.10GB 未被量化（与 int8 那条同根因）。"
               "按 PSNR 门槛判 unverified，但按扩散专用低频口径（24.56dB）是达标的。",
        source=".workbuddy/tmp/verify_fp8.py（算子）+ verify_fp8_e2e.py（出图/显存/耗时）",
        measured_at="2026-11-01",
        lowfreq_psnr_db=24.56,
    ),
    QuantEvidence(
        scheme="int8wo_v2", model_id="sdxl-t2i",
        unet_gb_before=4.78, unet_gb_after=2.71,
        peak_gb_before=5.21, peak_gb_after=4.07,
        wall_ratio=0.96, psnr_db=5.29,
        verdict=VERDICT_REJECTED,
        reason="输出整张全黑（像素 mean=0/std=0）。显存目标达成（-43.4%）但画质完全失效；"
               "Linear 743/743 全部量化，说明不是覆盖率不足，而是数值路径不成立。",
        source="verify_int8_diffusers.py sdxl-t2i（SHIGUANG_QVER=v2）",
        measured_at="2026-10-27",
    ),
    QuantEvidence(
        scheme="int8wo_v2", model_id="sd15-t2i",
        unet_gb_before=1.60, unet_gb_after=1.35,
        peak_gb_before=2.02, peak_gb_after=1.76,
        wall_ratio=1.09, psnr_db=27.44,
        verdict=VERDICT_REJECTED,
        reason="只省 15.7%（Linear 仅 0.50GB，Conv2d 1.10GB 未量化），却付出 27.44dB 的画质代价；"
               "收益/代价比不成立。",
        source="verify_int8_diffusers.py sd15-t2i（SHIGUANG_QVER=v2）",
        measured_at="2026-10-27",
    ),
    QuantEvidence(
        scheme="int8wo", model_id="sd15-t2i",
        unet_gb_before=1.60, unet_gb_after=1.60,
        peak_gb_before=2.02, peak_gb_after=1.76,
        wall_ratio=1.12, psnr_db=27.44,
        verdict=VERDICT_REJECTED,
        reason="version=1 在本组合下未产生可测的权重压缩（权重字节 0% 变化），"
               "且输出与 v2 完全一致 ⇒ 不构成独立可选项。",
        source="verify_int8_diffusers.py sd15-t2i（SHIGUANG_QVER=v1）",
        measured_at="2026-10-27",
    ),
    QuantEvidence(
        scheme="gguf_q8_0", model_id="sd15-t2i（512²·20步·同 seed）",
        unet_gb_before=1.72, unet_gb_after=0.91,
        peak_gb_before=None, peak_gb_after=None,
        wall_ratio=0.85, psnr_db=17.14,
        verdict=VERDICT_UNVERIFIED,
        reason="权重层面完全正确（686 层 100% 装入零缺失、30 层抽样最大相对误差 4.05e-03、"
               "conv_in/time_embedding 落在 UNet 内且非零）；出图层面：PSNR 17.14dB / SSIM 0.72 / "
               "低频(8×) PSNR 21.31dB，**肉眼观感与 fp16 基线一致**（构图/色彩/物体位置全对，只有砖缝与辐条等高频细节不同）。"
               "★ 关键对照实验（psnr_control.py）：**完全不用 GGUF**，仅给 fp16 权重加 0.4% 高斯扰动，"
               "同 seed 出图 PSNR = 14.12dB —— **比 GGUF 还低** ⇒ 十几 dB 是扩散采样对权重微扰的固有放大，"
               "不是量化实现问题。结论：PSNR 这把尺子对扩散模型无效，故本条不按 PSNR 门槛判定；"
               "但「同 seed 不可逐像素复现」是事实，**不能声称无损**。"
               "⚠️ eager 模式只省硬盘/下载量，**不省显存**；省显存走 gguf_lazy。"
               "★ 生产接线验收（同日）：`request_gguf(<q8_0.gguf>)` → `load('sd15-t2i')` 返回 ok=True、"
               "`gguf_status.loaded=686`、dominant_type=Q8_0，装填 20.9s，随后 `generate()` 4.0s 出 512² 图；"
               "负例路径不存在时 ok=False 且原因写明路径（不静默退回 fp16 假装量化）。",
        source=".workbuddy/tmp/psnr_gguf.py（PSNR/SSIM）+ psnr_control.py（扰动对照）+ e2e_final.py（权重闭环）"
               " + verify_gguf_wired.py（生产路径接线）",
        measured_at="2026-11-01",
        lowfreq_psnr_db=21.31,
    ),
)


def descriptor(scheme: str) -> Optional[QuantDescriptor]:
    """按 scheme 取描述符；未知返回 None（调用方必须如实失败）。"""
    return _DESC_BY_SCHEME.get(str(scheme or "").strip().lower())


def evidence_for(scheme: str) -> List[QuantEvidence]:
    """某 scheme 的全部实测证据（含已被推翻的，供追溯）。"""
    s = str(scheme or "").strip().lower()
    return [e for e in EVIDENCE if e.scheme == s]


def _effective(scheme: str) -> List[QuantEvidence]:
    """参与裁决的证据（排除 superseded）。"""
    return [e for e in evidence_for(scheme) if not e.superseded]


def verdict(scheme: str) -> Tuple[str, str]:
    """返回 (判定态, 理由)。取最坏态；无证据 = unverified。"""
    evs = _effective(scheme)
    if not evs:
        return VERDICT_UNVERIFIED, "无实测证据（登记过 ≠ 验证过）"
    worst = max(evs, key=lambda e: _SEVERITY.get(e.verdict, 1))
    if worst.verdict == VERDICT_REJECTED:
        return VERDICT_REJECTED, f"{worst.model_id}: {worst.reason}"
    ok = [e for e in evs if e.verdict == VERDICT_VERIFIED and e.psnr_db is not None]
    if ok:
        return VERDICT_VERIFIED, f"{len(ok)} 条实测通过（最差 PSNR {min(e.psnr_db for e in ok):.1f}dB）"
    return VERDICT_UNVERIFIED, "有证据但无一条通过验收"


def is_admissible(scheme: str, *, min_psnr_db: float = DEFAULT_MIN_PSNR_DB) -> Tuple[bool, str]:
    """准入裁决：该方案能否进主路径。

    · fp16 永远准入（基线，不需要证据）；
    · 其余必须 verified 且最差 PSNR ≥ 门槛；
    · rejected 一律拒绝，除非将来有新的证据把判定翻过来（本函数只看台账，不猜）。
    """
    s = str(scheme or "").strip().lower()
    if s in ("", "fp16", "float16", "half", "none"):
        return True, "基线精度，无需准入"
    d = descriptor(s)
    if d is None:
        return False, f"未登记的量化方案: {s}（标准 4 要求先登记描述符）"
    state, why = verdict(s)
    if state == VERDICT_REJECTED:
        return False, f"{s} 已被实测否决：{why}"
    if state == VERDICT_UNVERIFIED:
        return False, f"{s} 未验证：{why}"
    evs = [e for e in evidence_for(s) if e.psnr_db is not None]
    if not evs:
        return False, f"{s} 无画质对照证据，不能证明不掉级"
    worst = min(e.psnr_db for e in evs)
    if worst < float(min_psnr_db):
        return False, f"{s} 最差 PSNR {worst:.1f}dB 低于门槛 {min_psnr_db:.1f}dB"
    return True, f"{s} 通过（最差 PSNR {worst:.1f}dB ≥ {min_psnr_db:.1f}dB）"


def is_admissible_diffusion(scheme: str, *,
                            min_lowfreq_db: float = DEFAULT_MIN_LOWFREQ_PSNR_DB
                            ) -> Tuple[bool, str]:
    """**扩散模型专用**准入裁决：看低频结构，不看逐像素 PSNR。

    与 :func:`is_admissible` 并存而不替换它——原函数的口径（35dB）对非扩散场景
    （VAE 重建、滤镜、超分）仍然正确，只是套到扩散采样上会永远不通过。
    这里换一把尺子，但把「为什么换」写在 :data:`DEFAULT_MIN_LOWFREQ_PSNR_DB` 里，
    包括「样本只有一张图」这个弱点，不藏。
    """
    s = str(scheme or "").strip().lower()
    if s in ("", "fp16", "float16", "half", "none"):
        return True, "基线精度，无需准入"
    d = descriptor(s)
    if d is None:
        return False, f"未登记的量化方案: {s}"
    state, why = verdict(s)
    if state == VERDICT_REJECTED:
        return False, f"{s} 已被实测否决：{why}"
    evs = [e for e in evidence_for(s) if e.lowfreq_psnr_db is not None]
    if not evs:
        return False, f"{s} 无低频结构证据（登记过 ≠ 验证过）"
    worst = min(e.lowfreq_psnr_db for e in evs)
    if worst < float(min_lowfreq_db):
        return False, f"{s} 最差低频 PSNR {worst:.1f}dB 低于门槛 {min_lowfreq_db:.1f}dB"
    return True, f"{s} 通过（最差低频 PSNR {worst:.1f}dB ≥ {min_lowfreq_db:.1f}dB）"


def summary() -> Dict[str, Any]:
    """给 capabilities / 诊断页用的一页账。"""
    rows = []
    for d in DESCRIPTORS:
        state, why = verdict(d.scheme)
        ok, ok_why = is_admissible(d.scheme)
        rows.append({
            "scheme": d.scheme,
            "backend": d.backend,
            "group_size": d.group_size,
            "verdict": state,
            "admissible": ok,
            "detail": ok_why,
            "evidence_n": len(evidence_for(d.scheme)),
        })
    return {
        "min_psnr_db": DEFAULT_MIN_PSNR_DB,
        "admissible": [r["scheme"] for r in rows if r["admissible"]],
        "rejected": [r["scheme"] for r in rows if r["verdict"] == VERDICT_REJECTED],
        "rows": rows,
    }


def describe() -> str:
    """人类可读的一页账（CLI / 日志用）。"""
    s = summary()
    lines = [f"量化准入（门槛 PSNR ≥ {s['min_psnr_db']:.0f}dB）",
             f"  可进主路径: {', '.join(s['admissible']) or '（无）'}",
             f"  已否决: {', '.join(s['rejected']) or '（无）'}"]
    for r in s["rows"]:
        lines.append(f"  · {r['scheme']:<12} {r['verdict']:<10} evidence={r['evidence_n']}  {r['detail']}")
    return "\n".join(lines)


if __name__ == "__main__":
    print(describe())  # stability-gate: allow-print（__main__ CLI 入口，输出给人看）
