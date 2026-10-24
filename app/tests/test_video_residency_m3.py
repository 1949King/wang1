# -*- coding: utf-8 -*-
"""M3 驻留合一 + 参数单源 回归（统一引擎，2026-10-24）。

锁死三件事（全部不加载真权重：假 pipeline + 预填缓存）：
1. ④ video_gen.load("svd-xt-i2v") 必须走共享缓存（local_video_pipe_cache），
   第二次加载（另一个引擎实例）⇒ 命中、不重复 from_pretrained —— 双驻留 8.4GB 的病根在此断掉；
2. unload() 必须连带 evict 共享缓存 —— 只断 self._pipe 而缓存还持着 = 假卸载
   （V4.46.13 的 weakref 教训：卸载语义要能被观察到）；
3. ③ _infer_svd 的生成参数必须随 TUNED 变（改表 ⇒ 两条实现同时生效）——
   参数单源从「注释说抄 TUNED」升级为「代码真读 TUNED」。
"""

import os

import app.core.local_video_pipe_cache as VPC
from app.core.neural import video_gen as VG

_SVD_DIR = VG.VideoGenEngine.local_dir("svd-xt-i2v")
_SVD_KEY = ("svd", os.path.abspath(_SVD_DIR))


class _FakePipe:
    """够用的假管线：load 路径只碰 offload 开关与属性。"""

    def __init__(self):
        self.calls = {}

    def enable_model_cpu_offload(self):
        self._off = "model"

    def enable_sequential_cpu_offload(self):
        self._off = "sequential"

    def to(self, _dev):
        return self

    def __call__(self, **kw):
        self.calls.update(kw)

        class _R:
            frames = [[object()]]

        return _R()


def _fake_pipeline_cls(made):
    class _FakePipeline:
        @classmethod
        def from_pretrained(cls, *a, **k):
            made["n"] = made.get("n", 0) + 1
            return _FakePipe()

    return _FakePipeline


def _patch_diffusers_names(request, made, names):
    """把假类直接写进 diffusers 包 __dict__（绕开 lazy import 链）。

    ★ 0xC0000005 复盘（V4.46.16，全量 pytest 两次崩在本文件）：对 diffusers 包做
    `getattr(pkg, "DiffusionPipeline")` ——**包括 monkeypatch.setattr 的隐式取旧值**——
    会触发 diffusers 的 lazy import，在 peft×transformers 已加载的全量上下文里原生崩溃。
    唯一安全姿势：`pkg.__dict__[name] = fake`（写入不走 __getattr__）；被测代码
    `from diffusers import X` 先查 __dict__ ⇒ 命中假类，整条 lazy 链根本不执行。
    教训与前作同源（lcm_status 用 find_spec 不 import peft）：**测试里绝不触发重库 lazy 面**。
    """
    import sys

    import diffusers  # noqa: F401  仅确保包对象存在（包 __init__ 是 lazy 设计，轻量）

    mod = sys.modules["diffusers"]
    saved = {n: (n in mod.__dict__, mod.__dict__.get(n)) for n in names}
    fake = _fake_pipeline_cls(made)
    for n in names:
        mod.__dict__[n] = fake

    def _undo():
        for n, (had, old) in saved.items():
            if had:
                mod.__dict__[n] = old
            else:
                mod.__dict__.pop(n, None)

    request.addfinalizer(_undo)


def test_svd_load_shares_cache_across_instances(request):
    """④ 的两个实例（模拟 ③ 先建、④ 后用）必须共享同一条常驻管线。"""
    VPC.clear()
    made = {}
    _patch_diffusers_names(request, made, ["DiffusionPipeline"])

    eng1 = VG.VideoGenEngine()
    r1 = eng1.load("svd-xt-i2v")
    assert r1["ok"], r1.get("message")
    assert r1.get("pipe_source") == "miss"
    assert made.get("n") == 1

    eng2 = VG.VideoGenEngine()
    r2 = eng2.load("svd-xt-i2v")
    assert r2["ok"], r2.get("message")
    assert r2.get("pipe_source") == "hit", "第二次必须命中共享缓存（不再 from_pretrained）"
    assert made.get("n") == 1, "命中还重建 = 双驻留病根未断"
    assert eng2._pipe is eng1._pipe, "两条实现持有的必须是同一个对象"
    assert eng2._shared_key == _SVD_KEY

    # offload 状态随管线走（命中时 loader 没跑，不能误报 none）
    assert eng2._offload in ("model", "sequential", "none")
    assert eng2._offload == eng1._offload
    VPC.clear()


def test_unload_evicts_shared_cache(request):
    """unload 必须连带 evict：只断本侧引用 = 假卸载（缓存还持 4.2GB）。"""
    VPC.clear()
    made = {}
    _patch_diffusers_names(request, made, ["DiffusionPipeline"])
    eng = VG.VideoGenEngine()
    assert eng.load("svd-xt-i2v")["ok"]
    assert _SVD_KEY in VPC.cached_keys(), "load 后共享缓存应持有该管线"
    eng.unload()
    assert _SVD_KEY not in VPC.cached_keys(), "unload 后缓存必须真放手"
    assert eng._pipe is None and eng._shared_key is None
    VPC.clear()


def test_infer_svd_params_follow_tuned(monkeypatch, request):
    """③ 的生成参数必须来自 tuned_for（改 TUNED ⇒ ③ 同步生效 = 单源证明）。"""
    from app.core import local_video_infer as L

    # _infer_svd 顶部 `from diffusers import StableVideoDiffusionPipeline` 也会走 lazy 链
    # ⇒ 同样注入假名（缓存已预填，假类根本不会被调用，只为让 import 语句安全通过）。
    _patch_diffusers_names(request, {}, ["StableVideoDiffusionPipeline"])
    VPC.clear()
    fake = _FakePipe()
    VPC.get_or_load(_SVD_KEY, lambda: fake)  # 预填缓存 ⇒ _infer_svd 走 hit
    monkeypatch.setattr(L, "_load_input_image", lambda _s: object())
    monkeypatch.setattr(L, "_save_video_frames", lambda *a, **k: {"ok": True, "path": "x.mp4"})

    tun = VG.tuned_for("svd-xt-i2v")
    r = L._infer_svd(
        model_path=_SVD_DIR, device="cuda", vram_gb=8, duration=2, reference_image="whatever.png"
    )
    assert r["ok"] and r.get("pipe_source") == "hit"
    assert fake.calls["num_inference_steps"] == int(tun["steps"])
    assert fake.calls["motion_bucket_id"] == int(tun["motion_bucket_id"])
    assert fake.calls["decode_chunk_size"] == int(tun["decode_chunk_size"])
    assert fake.calls["min_guidance_scale"] == float(tun["cfg_min"])
    assert fake.calls["max_guidance_scale"] == float(tun["cfg_max"])
    assert fake.calls["num_frames"] == max(2, int(round(2 * 7)))

    # 单源证明：改表 ⇒ ③ 的调用参数同步变（旧硬编码写法做不到这一点）
    monkeypatch.setitem(VG.TUNED["svd-xt-i2v"], "motion_bucket_id", 999)
    L._infer_svd(
        model_path=_SVD_DIR, device="cuda", vram_gb=8, duration=2, reference_image="whatever.png"
    )
    assert fake.calls["motion_bucket_id"] == 999, "参数仍走硬编码 = 第二真源未消灭"
    VPC.clear()


def test_infer_svd_steps_override_still_wins(monkeypatch, request):
    """显式 steps 参数优先于 TUNED（语义与改动前一致，档位入口不能被单源吃掉）。"""
    from app.core import local_video_infer as L

    _patch_diffusers_names(request, {}, ["StableVideoDiffusionPipeline"])
    VPC.clear()
    fake = _FakePipe()
    VPC.get_or_load(_SVD_KEY, lambda: fake)
    monkeypatch.setattr(L, "_load_input_image", lambda _s: object())
    monkeypatch.setattr(L, "_save_video_frames", lambda *a, **k: {"ok": True, "path": "x.mp4"})
    L._infer_svd(
        model_path=_SVD_DIR,
        device="cuda",
        vram_gb=8,
        duration=2,
        reference_image="whatever.png",
        steps=4,
    )
    assert fake.calls["num_inference_steps"] == 4
    VPC.clear()
