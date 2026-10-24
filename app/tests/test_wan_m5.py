# -*- coding: utf-8 -*-
"""M5 Wan 真机验收后的回归（统一引擎，2026-10-24）。

真机已验收（Wan2.1-T2V-1.3B 出片：17帧480²/20步=58.5s，猫在草地上走）。
本文件锁死验收过程中修掉的四个坑，防回归：
  1. num_frames 必须 4k+1（时序 VAE 4× 压缩）—— 原 int(duration*16) 全不合法；
  2. 宽高必须 16 整除 —— 488（8 的倍数）被 check_inputs 拒；
  3. 类名必须是 diffusers 真实存在的（守卫 E 项已全局锁，这里锁 wan 的具体映射）；
  4. I2V 必须**在 import 重库之前**就诚实拒绝（0xC0000005 教训：测试里绝不触发
     diffusers lazy 面 ⇒ 拒绝路径若先 import，全量 pytest 可能整体崩）。
"""

import sys

import app.core.local_video_infer as L


# ── ① 帧数 4k+1 ────────────────────────────────────────────────────────
def test_wan_num_frames_is_4k_plus_1():
    for d in (1, 2, 3, 5, 10):
        n = L._wan_num_frames(d)
        assert (n - 1) % 4 == 0, (d, n)
        assert n >= 5, (d, n)
    # 与原公式 int(d*16) 的区别：那个给 16/32/48/80 —— 全部不合法
    assert all((int(d * 16) - 1) % 4 for d in (1, 2, 3, 5)), "旧公式确实全错"


def test_wan_num_frames_monotonic():
    assert L._wan_num_frames(1) < L._wan_num_frames(2) < L._wan_num_frames(5)


# ── ② 尺寸 16 整除 ─────────────────────────────────────────────────────
def test_wan_size_div16():
    assert L._wan_div_size("1280x720") == (1280, 720)  # 本来就合法
    assert L._wan_div_size("488x488") == (480, 480)  # 实测被拒的值 → 向下取整
    assert all(v % 16 == 0 for v in L._wan_div_size("1000x700"))
    assert all(v % 16 == 0 for v in L._wan_div_size("垃圾"))  # 不抛，回退默认


# ── ③ 类名真实（与守卫 E 双保险）───────────────────────────────────────
def test_wan_pipeline_class_is_real():
    import diffusers

    assert L.PIPELINE_CLASS_MAP["wan"] == "WanPipeline"
    assert "WanPipeline" in set(dir(diffusers)), "登记的类名必须真实存在"


# ── ④ I2V 拒绝路径不触发重库导入 ───────────────────────────────────────
def test_wan_i2v_rejects_before_heavy_import(monkeypatch):
    """拒绝必须发生在 import torch/diffusers 之前（0xC0000005 纪律 + fail fast）。"""

    # 用一个「一被 import 就炸」的假模块占位：若实现先去 import 它，本测试就会失败
    class _Boom:
        def __getattr__(self, _n):
            raise AssertionError("I2V 拒绝路径不该 import diffusers（应先 fail fast）")

    monkeypatch.setitem(sys.modules, "diffusers", _Boom())
    r = L._infer_wan(
        prompt="p",
        model_path="/nonexistent",
        device="cuda",
        vram_gb=8,
        duration=2,
        reference_image="data:image/png;base64,xx",
    )
    assert r["ok"] is False
    assert "T2V" in r["message"] and "I2V" in r["message"], "要如实说明缺什么"


# ── ⑤ 登记与真机事实一致（防「验证态」漂移）────────────────────────────
def test_wan_registered_as_verified_with_measured_note():
    from app.core.neural import model_family as MF

    s = MF.spec_of("wan")
    assert s.verification == MF.VERIFIED, "M5 已真机验收，登记必须跟上事实"
    assert s.min_vram_gb <= 8.0, "实测 8GB 卡可跑（两阶段），登记不得虚高"
    assert "58.5" in s.note or "两阶段" in s.note, "实测数据/关键约束必须进登记"
