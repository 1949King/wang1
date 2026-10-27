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
DEFAULT_MIN_PSNR_DB = 35.0


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
        reason="能跑通（apply_fp8_quantization 已在 load() 接线），但本机 "
               "torch._scaled_mm 报 CUBLAS_STATUS_NOT_SUPPORTED ⇒ 走反量化回退，无加速；"
               "画质/显存对照尚未做 ⇒ 停在 unverified，不得当卖点。",
        source="torchao_check.py（float8 动态量化项）+ 独立 venv 直测 _scaled_mm",
        measured_at="2026-10-27",
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
)


def descriptor(scheme: str) -> Optional[QuantDescriptor]:
    """按 scheme 取描述符；未知返回 None（调用方必须如实失败）。"""
    return _DESC_BY_SCHEME.get(str(scheme or "").strip().lower())


def evidence_for(scheme: str) -> List[QuantEvidence]:
    """某 scheme 的全部实测证据。"""
    s = str(scheme or "").strip().lower()
    return [e for e in EVIDENCE if e.scheme == s]


def verdict(scheme: str) -> Tuple[str, str]:
    """返回 (判定态, 理由)。取最坏态；无证据 = unverified。"""
    evs = evidence_for(scheme)
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
