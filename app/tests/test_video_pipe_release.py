# -*- coding: utf-8 -*-
"""常驻缓存的「内存礼貌」与回收正确性（V4.46.13）。

为什么用 weakref 而不是计时（2026-10-24 教训）：
  计时对比受笔记本热降频污染（本会话已两次被 475s/342s 假数据坑过），
  而「对象是否真被回收」是可以确定性验证的 —— 建弱引用，回收后弱引用必失效。

锁死三件事：
  ① _dispose 的引用顺序 bug 已修：以前在 dict 仍持引用时 gc.collect() ⇒ 收不掉；
     现在「先断全部引用 → 再统一 _gc_release」，weakref 可证。
  ② release_under_pressure 只在可用内存低于水位时才释放；宽裕时不动（保住常驻收益）。
  ③ 可用内存取不到时按「释放」处理（宁可多 reload，不可压爆内存）。
"""

import gc
import weakref

import pytest

import app.core.local_video_pipe_cache as C


class _Fake:
    """占位管线：用 __del__ 记录是否真被回收。"""

    def __init__(self, tag):
        self.tag = tag


@pytest.fixture(autouse=True)
def _clean():
    C.clear()
    yield
    C.clear()


def test_clear_actually_collects(monkeypatch):
    """clear() 必须真的让对象被回收（旧实现做不到：dict 还持引用时就 gc 了）。"""
    obj = _Fake("svd")
    ref = weakref.ref(obj)
    C.get_or_load(("svd", "/m"), lambda: obj)
    assert ref() is not None, "缓存期间对象必须活着"
    obj = None  # 断掉本测试的强引用（置 None 而非 del：del 会让 ruff 认为上方 lambda 引用未绑定名字）
    assert C.clear() == 1
    gc.collect()
    assert ref() is None, "clear() 后对象应被回收（引用未断干净 = 内存不降）"


def test_evict_actually_collects():
    obj = _Fake("e")
    ref = weakref.ref(obj)
    C.get_or_load(("svd", "/e"), lambda: obj)
    obj = None
    assert C.evict(("svd", "/e")) is True
    gc.collect()
    assert ref() is None, "evict()（OOM 让位路径）必须真回收"


def test_lru_evict_collects():
    obj = _Fake("old")
    ref = weakref.ref(obj)
    C.get_or_load(("svd", "/old"), lambda: obj)
    obj = None
    C.get_or_load(("svd", "/new"), lambda: _Fake("new"))  # 触发 LRU 淘汰
    gc.collect()
    assert ref() is None, "LRU 淘汰必须真回收，否则常驻内存只增不减"


def test_release_only_under_pressure(monkeypatch):
    """内存宽裕时**不该**释放（否则常驻白做）；吃紧时才让位。"""
    C.get_or_load(("svd", "/p"), lambda: _Fake("p"))
    monkeypatch.setattr(C, "available_ram_gb", lambda: 9.0)
    assert C.release_under_pressure(floor_gb=2.3) == 0
    assert C.cached_keys() == [("svd", "/p")]

    monkeypatch.setattr(C, "available_ram_gb", lambda: 1.0)
    assert C.release_under_pressure(floor_gb=2.3, reason="测试") == 1
    assert C.cached_keys() == []


def test_release_when_ram_unknown_is_conservative(monkeypatch):
    """取不到可用内存 ⇒ 按释放处理（宁可多 reload，不可压爆）。"""
    C.get_or_load(("svd", "/u"), lambda: _Fake("u"))
    monkeypatch.setattr(C, "available_ram_gb", lambda: None)
    assert C.release_under_pressure() == 1
    assert C.cached_keys() == []


def test_ram_probe_returns_a_number():
    """真实探测（不打桩）：必须返回合理 GB 数，否则让位判断永远失效。"""
    gb = C.available_ram_gb()
    assert gb is not None and 0.0 < gb < 1024.0, f"可用内存探测异常：{gb}"


def test_image_engine_load_calls_release():
    """接线证明：图像引擎加载前必须调用让位（否则跨引擎内存礼貌形同虚设）。"""
    import inspect

    from app.core.neural import diffusers_image as DIF

    src = inspect.getsource(DIF.DiffusersImageEngine.load)
    assert "release_under_pressure" in src, "图像引擎未接让位 ⇒ 常驻会拖累出图"


def test_release_floor_scales_with_model_size():
    """让位水位必须随「即将加载的权重大小」变，不能是拍脑袋的固定值。

    语义：可用内存低于「我要的量」才让位 —— 否则对方腾了地方还是不够。
    SDXL 6.46GB ⇒ 水位 ≈6.46×1.15+1.2 ≈ 8.6GB；SD1.5 3.97GB ⇒ ≈5.8GB。
    """
    import inspect

    from app.core.neural import diffusers_image as DIF

    src = inspect.getsource(DIF.DiffusersImageEngine.load)
    assert "size_gb" in src and "floor_gb=_floor" in src, (
        "让位水位未与模型权重大小挂钩（退回固定值 = 大模型腾不够、小模型白腾）"
    )
    # 数值自洽：SDXL 的水位必须高于 SD1.5 的水位
    sd_xl = DIF.DIFFUSERS_IMAGE_MODELS["sdxl-t2i"]["size_gb"]
    sd_15 = DIF.DIFFUSERS_IMAGE_MODELS["sd15-t2i"]["size_gb"]
    assert sd_xl * 1.15 + 1.2 > sd_15 * 1.15 + 1.2
