# -*- coding: utf-8 -*-
"""app/tests/test_model_registry.py — 模型仓库 / 懒加载 / 显存水位守卫 的诚实性回归（2026-10-09）。

本模块的红线：
  ① acquire 前查显存，够才加载，不够**LRU 驱逐**再试，仍不够**诚实失败**（不 OOM、不假装成功）；
  ② 显存探测失败（无 CUDA）⇒ 诚实失败，**不编数字**；
  ③ LRU 驱逐只动"最久未用"的，且排除正在 acquire 的那个；
  ④ 命中缓存不重复加载（cached=True，不触发 loader）。
"""

from app.core.ai import model_registry as mr


def _fake_free(free_map):
    """造一个可控的显存探测函数：返回给定值。"""
    return lambda: free_map["free"]


def _spec(mid, vram, loads=None):
    loaded = {"n": 0}

    def loader():
        loaded["n"] += 1
        return f"model:{mid}"

    return mr.ModelSpec(model_id=mid, vram_mb=vram, loader=loader), loaded


def test_acquire_hits_cache_without_reloading():
    reg = mr.ModelRegistry(free_vram_mb=_fake_free({"free": 10000}))
    spec, loaded = _spec("a", 100)
    reg.register(spec)
    r1 = reg.acquire("a")
    r2 = reg.acquire("a")
    assert r1.ok and r1.model == "model:a" and not r1.cached
    assert r2.ok and r2.cached is True
    assert loaded["n"] == 1, "命中缓存不应重新加载"


def test_acquire_unknown_model_fails_honestly():
    reg = mr.ModelRegistry(free_vram_mb=_fake_free({"free": 10000}))
    r = reg.acquire("nope")
    assert r.ok is False and "未注册" in r.reason


def test_acquire_fails_when_vram_probe_fails():
    """显存探测失败 ⇒ 诚实失败，不编"够用"的假数字。"""
    def boom():
        raise RuntimeError("无 CUDA")

    reg = mr.ModelRegistry(free_vram_mb=boom)
    spec, _ = _spec("a", 100)
    reg.register(spec)
    r = reg.acquire("a")
    assert r.ok is False and "无法探测显存" in r.reason


def test_acquire_evicts_lru_when_vram_low():
    """显存不足 ⇒ 驱逐最久未用的模型腾空间，再加载。

    关键：fake 显存必须**反映已加载模型的占用**（总显存 − 已加载模型），
    这样"驱逐 a"才会让空闲显存自然回升 —— 死值不会，那是假场景。
    """
    total = 200   # 只够装一个 120MB 模型（120*1.15=138），装不下两个
    reg = mr.ModelRegistry()

    def free():
        used = sum(reg.spec(m).vram_mb for m in reg.loaded_models())
        return total - used

    reg._free_vram = free
    sa, _ = _spec("a", 120)
    sb, _ = _spec("b", 120)
    reg.register(sa)
    reg.register(sb)
    assert reg.acquire("a").ok          # 装 a：free=200 ≥ 138 ✓，装完 used=120
    r = reg.acquire("b")                 # 装 b：free=80 < 138 ⇒ 驱逐 a，free 回升 200 ≥ 138 ✓
    assert r.ok
    assert "a" in r.evicted, "应驱逐最久未用的 a"
    assert "a" not in reg.loaded_models()
    assert "b" in reg.loaded_models()


def test_acquire_honest_fail_when_eviction_not_enough():
    """驱逐后仍不够 ⇒ 诚实失败，不 OOM。"""
    free_map = {"free": 20}   # 永远不够
    reg = mr.ModelRegistry(free_vram_mb=_fake_free(free_map))
    spec, _ = _spec("big", 1000)
    reg.register(spec)
    r = reg.acquire("big")
    assert r.ok is False
    assert "显存不足" in r.reason


def test_lru_does_not_evict_self():
    """驱逐时排除正在 acquire 的模型（自己还没进缓存，但保险）。"""
    free_map = {"free": 50}
    reg = mr.ModelRegistry(free_vram_mb=_fake_free(free_map))
    sa, _ = _spec("a", 100)
    reg.register(sa)
    reg.acquire("a")  # 会失败（50 < 115），但不应尝试驱逐自己
    assert reg._lru_victim(exclude="a") is None


def test_release_returns_vram():
    reg = mr.ModelRegistry(free_vram_mb=_fake_free({"free": 10000}))
    spec, _ = _spec("a", 100)
    reg.register(spec)
    reg.acquire("a")
    assert "a" in reg.loaded_models()
    assert reg.release("a") is True
    assert "a" not in reg.loaded_models()
    assert reg.release("a") is False   # 二次释放返回 False


def test_release_calls_release_callback():
    released = {"n": 0}
    reg = mr.ModelRegistry(free_vram_mb=_fake_free({"free": 10000}))

    def loader():
        return object()

    def release(m):
        released["n"] += 1

    reg.register(mr.ModelSpec("a", 100, loader, release))
    reg.acquire("a")
    reg.release("a")
    assert released["n"] == 1


def test_thread_safe_acquire_returns_consistent():
    """并发 acquire 同一模型：不会重复加载（锁 + 缓存）。"""
    import threading

    reg = mr.ModelRegistry(free_vram_mb=_fake_free({"free": 10000}))
    spec, loaded = _spec("a", 100)
    reg.register(spec)
    results = []

    def worker():
        results.append(reg.acquire("a"))

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert all(r.ok for r in results)
    assert loaded["n"] == 1, "并发下也只应加载一次"
