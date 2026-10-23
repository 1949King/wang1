# -*- coding: utf-8 -*-
"""本地视频管线进程级缓存（V4.46.10 视频侧用法感知）。

锁死：命中/未命中语义、LRU 上限、失败不写缓存、OOM 淘汰、并发只加载一次。
全部用假 loader（不碰 torch/diffusers/GPU）。
"""
import threading

import pytest

import app.core.local_video_pipe_cache as C


@pytest.fixture(autouse=True)
def _clean():
    C.clear()
    yield
    C.clear()


def test_miss_then_hit():
    calls = {"n": 0}

    def loader():
        calls["n"] += 1
        return object()

    k = ("svd", "/m/x")
    p1, s1 = C.get_or_load(k, loader)
    p2, s2 = C.get_or_load(k, loader)
    assert s1 == "miss" and s2 == "hit"
    assert p1 is p2
    assert calls["n"] == 1, "第二次必须复用，不再加载"


def test_lru_evicts_oldest():
    # 默认上限 1：载入第二个应淘汰第一个
    a, _ = C.get_or_load(("svd", "/a"), lambda: "A")
    b, _ = C.get_or_load(("svd", "/b"), lambda: "B")
    assert C.cached_keys() == [("svd", "/b")]
    # 再取 /a 应是 miss（被淘汰了）
    _a2, s = C.get_or_load(("svd", "/a"), lambda: "A2")
    assert s == "miss"


def test_failure_not_cached():
    def boom():
        raise RuntimeError("load failed")

    with pytest.raises(RuntimeError):
        C.get_or_load(("svd", "/bad"), boom)
    assert C.cached_keys() == [], "加载失败绝不能写进缓存"


def test_evict_returns_truth():
    C.get_or_load(("svd", "/e"), lambda: "E")
    assert C.evict(("svd", "/e")) is True
    assert C.evict(("svd", "/e")) is False   # 已没了


def test_status_shape():
    C.get_or_load(("svd", "/s"), lambda: "S")
    C.get_or_load(("svd", "/s"), lambda: "S")   # 一次命中
    st = C.status()
    assert st["cached"] == 1
    assert st["entries"][0]["hits"] == 1
    assert st["max_pipes"] >= 1


def test_concurrent_loads_once():
    """并发同 key：loader 只应被调用一次（锁内串行）。"""
    calls = {"n": 0}
    lock = threading.Lock()

    def slow_loader():
        with lock:
            calls["n"] += 1
        # 制造交错窗口
        for _ in range(1000):
            pass
        return object()

    results = []

    def worker():
        results.append(C.get_or_load(("svd", "/c"), slow_loader))

    ts = [threading.Thread(target=worker) for _ in range(5)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert calls["n"] == 1, f"loader 被调用 {calls['n']} 次，应只 1 次"
    assert all(r[0] is results[0][0] for r in results), "并发拿到的必须是同一管线"
