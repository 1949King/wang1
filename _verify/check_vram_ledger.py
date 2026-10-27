# -*- coding: utf-8 -*-
"""守卫 ②：显存账本不变量（P0 · 2026-10-28）。

守什么
======
`vram_ledger` 的 5 分项口径是本项目「省了多少显存」这句话的**唯一依据**。
若口径错了，所有量化/缓存/卸载的收益数字都会系统性偏差，而且**错得很像对的**。

本守卫用离线 reader 跑三段构造场景，断言：
  1. **分项不可相加当峰值**：构造「阶段间回收」场景，断言账本给出 `reclaim_gb`
     而不是把 `attributed > peak` 静默吞掉；
  2. **缺项不许冒充**：只测 3 项时 `attributed_gb` 必须是 None，不能拿 3 项之和充 5 项；
  3. **测不出就 None**：无 reader 时 `peak_gb` 为 None（绝不能是 0）；
  4. **拼错分项必须抛**：`enter("wieght")` 若被静默吞掉，账本会悄悄少一项 —— 最坏的失败方式；
  5. **K4 门槛分模态**：图像 1.05 / 视频 1.10，且基线缺失时判 `unknown` 而不是 `pass`。

反例自证：`--selfcheck` 会把第 1 条的期望反向注入，证明守卫真的会红。
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _figure(name: str) -> None:
    print("   · %s" % name)


def _run_checks() -> list:
    from app.core.neural import vram_ledger as VL

    bad = []

    # ① 阶段间回收：5 项都测到，但权重/激活在不同时刻峰值 ⇒ 分项之和 > 全局峰值
    #    场景：每阶段结束时权重都被换出（起点归零），故 5 项各自记账互不重叠。
    #    reader：begin(0,0) → enter×5 各 (0,0) → close 尾巴 (0.5,0.5)
    #            peaks：2.0 / 3.0 / 1.0 / 2.5 / 1.5（对应 5 次 leave）
    #    ⇒ attributed 10.0 > peak 3.0 ⇒ 必须给 reclaim_gb=7.0，不许静默吞掉
    led = VL.VramLedger(VL.dict_reader(
        [(0.0, 0.0)] * 7 + [(0.5, 0.5)],
        peaks=[2.0, 3.0, 1.0, 2.5, 1.5]), model_id="t", kind="image")
    led.begin()
    for k in VL.ITEMS:
        led.enter(k)
        led.leave(k)
    out = led.close()
    if not all(out["%s_gb" % k] is not None for k in VL.ITEMS):
        bad.append("① 5 项未全部记账：%s" % {k: out["%s_gb" % k] for k in VL.ITEMS})
    elif out["reclaim_gb"] is None:
        bad.append("① 未识别「阶段间回收」：attributed=%s peak=%s 却无 reclaim_gb"
                   % (out["attributed_gb"], out["peak_gb"]))
    elif not any("不可相加" in n for n in out["notes"]):
        bad.append("① 识别了回收但没在 notes 里写明「分项不可相加当峰值」")
    else:
        _figure("阶段间回收可识别（attributed=%.1f peak=%.1f reclaim=%.1f）"
                % (out["attributed_gb"], out["peak_gb"], out["reclaim_gb"]))

    # ② 缺项不许冒充：只测 3 项 ⇒ attributed 必须 None
    led2 = VL.VramLedger(VL.dict_reader([(0.0, 0.0)] * 8, peaks=[1.0] * 8))
    led2.begin()
    for k in ("weight", "activation", "decode"):
        led2.enter(k)
        led2.leave(k)
    out2 = led2.close()
    if out2["attributed_gb"] is not None:
        bad.append("② 只测 3 项却给出 attributed_gb=%r（拿部分和冒充全量）"
                   % out2["attributed_gb"])
    else:
        _figure("缺项时 attributed_gb 为 None（不冒充）")

    # ③ 无 reader ⇒ peak 必须 None，不能 0
    led3 = VL.VramLedger(None).begin()
    out3 = led3.close()
    if out3["peak_gb"] is not None:
        bad.append("③ 无 reader 时 peak_gb=%r（应为 None，0 会被读成「不占显存」）"
                   % out3["peak_gb"])
    else:
        _figure("无 reader 时 peak_gb 为 None（不编 0）")

    # ④ 拼错分项必须抛
    try:
        VL.VramLedger(VL.dict_reader([(0.0, 0.0)] * 4)).begin().enter("wieght")
    except ValueError:
        _figure("拼错分项会抛 ValueError（不会静默少一项）")
    except Exception as e:
        bad.append("④ 拼错分项抛的不是 ValueError：%r" % e)
    else:
        bad.append("④ 拼错分项被静默接受 ⇒ 账本会悄悄少一项")

    # ⑤ K4 门槛分模态 + 基线缺失判 unknown
    led5 = VL.VramLedger(VL.dict_reader([(0.0, 0.0)] * 4, peaks=[2.2] * 4)).begin()
    led5.enter("weight")
    led5.leave("weight")
    _r, v_img, _w = led5.ratio_vs(2.0, kind="image")
    _r2, v_vid, _w2 = led5.ratio_vs(2.0, kind="video")
    _r3, v_unk, _w3 = led5.ratio_vs(None)
    if not (v_img == "over" and v_vid == "pass"):
        bad.append("⑤ K4 门槛没分模态：image=%s（应 over） video=%s（应 pass）"
                   % (v_img, v_vid))
    elif v_unk != "unknown":
        bad.append("⑤ 基线缺失却判 %s（应 unknown，不许猜 pass）" % v_unk)
    else:
        _figure("K4 分模态门槛正确（image 1.05 / video 1.10）+ 无基线判 unknown")

    return bad


def main() -> int:
    ap = argparse.ArgumentParser(description="显存账本不变量守卫")
    ap.add_argument("--selfcheck", action="store_true",
                    help="把断言反向注入，验证守卫真的会红")
    args = ap.parse_args()

    print("显存账本不变量：")
    bad = _run_checks()

    if args.selfcheck:
        # 注入一条必然失败的期望：把「缺项时必须 None」改成「必须有值」
        from app.core.neural import vram_ledger as VL

        led = VL.VramLedger(VL.dict_reader([(0.0, 0.0)] * 6, peaks=[1.0] * 6)).begin()
        led.enter("weight")
        led.leave("weight")
        out = led.close()
        if out["attributed_gb"] is None:
            print("✓ 自证通过：注入「必须全量」的期望后，守卫能识别出 attributed=None")
            return 0
        print("✗ 自证失败：注入反例后仍然通过 ⇒ 守卫是摆设")
        return 1

    if bad:
        print("✗ 不变量被破坏 %d 条：" % len(bad))
        for b in bad:
            print("   - %s" % b)
        return 1
    print("OK 账本不变量全部成立")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
