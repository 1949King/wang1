"""app/tests/test_frame_cache.py — 预览帧缓存的 LRU 语义与 dict 兼容（刀 A3.5，2026-10-05）。

**修的两个方向性错误**（不是"慢一点"，是"策略用错"）：
  ① `raw_frame_cache` 原用 `min(keys())` 淘汰**最小帧号** ⇒ 往回拖动时**恰好丢掉
     用户正要去的帧**（原注释「min() 淘汰顺序才正确」实际相反）；每次插入还多一次 O(n) 扫描。
  ② `preview_cache` 原命中**不提权** ⇒ 实为 **FIFO**，来回拖动反复淘汰「刚用过、
     马上又要用」的帧。

**接入方式（重要）**：没有改动冻结符号 `preview_manager.get_frame_at` 的任何字符 ——
冻结的是那段「怎么用缓存」的文本，而「缓存怎么实现」在协作对象里。
换掉协作对象即可改善，且可一行回退。本文件同时**锁住这一点**（见最后一节）。
"""
import threading

from app.core.frame_cache import FrameCache


# ─────────────────────── ① LRU 语义（判别性用例）───────────────────────

def test_hit_promotes_entry():
    """命中即提权 —— 这是 LRU 与 FIFO 的唯一分界。"""
    c = FrameCache(3)
    c["a"] = 1
    c["b"] = 2
    c["c"] = 3
    _ = c.get("a")          # a 变成最近使用
    c["d"] = 4              # 满 ⇒ 淘汰最久未用
    assert "b" not in c, "应淘汰 b（最久未用）；若淘汰 a 说明是 FIFO"
    assert set(c.keys()) == {"a", "c", "d"}


def test_evicts_least_recently_used_not_lowest_key():
    """帧号乱序时也必须按**访问新旧**淘汰，不按 key 大小。

    这正是原 `raw_frame_cache` 的错：`min(keys())` 只看数值大小。
    """
    c = FrameCache(3)
    for k in (500, 501, 502):
        c[k] = None
    _ = c.get(500)          # 500 最近用过
    c[503] = None           # 应淘汰 501（最久未用），而 min() 策略会淘汰 500
    assert 500 in c and 501 not in c


def test_backward_scrub_keeps_frames_ahead_of_playhead():
    """回归真实场景：往回拖动时，缓存应保留**即将访问**的更低帧号。

    原 min() 策略会一个个丢掉它们（越往小拖越先丢小的）—— 这里用「命中率」量化。
    """
    cap = 20
    c = FrameCache(cap)
    # 先正向预载 100..119（模拟播放到 119）。存真值 —— 存 None 无法区分命中与缺失。
    for i in range(100, 120):
        c[i] = i
    # 往回拖动 30 帧：前 20 帧应**全部命中**（缓存里正好有），后 10 帧才开始解码
    hits = sum(1 for i in range(119, 89, -1) if c.get(i) is not None)
    assert hits >= 20, f"往回拖动命中 {hits} 帧，应 ≥20（容量 20 全部可用）"


def test_popitem_last_false_is_lru_end():
    """`popitem(last=False)` 与 OrderedDict 同义（冻结代码就是这么调的）。"""
    c = FrameCache(2)
    c["x"] = 1
    c["y"] = 2
    _ = c.get("x")
    k, _v = c.popitem(last=False)
    assert k == "y", "last=False 应取最久未用端"


# ─────────────────────── ② dict / OrderedDict 兼容面 ───────────────────────

def test_dict_compatible_surface():
    c = FrameCache(4)
    c["k"] = "v"
    assert c["k"] == "v"
    assert c.get("nope") is None
    assert c.get("nope", "d") == "d"
    assert "k" in c and len(c) == 1
    assert c.keys() == ["k"] and c.values() == ["v"] and c.items() == [("k", "v")]
    assert list(iter(c)) == ["k"]
    assert c.pop("k") == "v"
    assert c.pop("k", "d") == "d"
    c["a"] = 1
    c.move_to_end("a")
    del c["a"]
    assert len(c) == 0
    c["z"] = 9
    c.clear()
    assert len(c) == 0


def test_setdefault_and_missing_key():
    c = FrameCache(2)
    assert c.setdefault("a", 1) == 1
    assert c.setdefault("a", 2) == 1
    try:
        c["missing"]
        raise AssertionError("应抛 KeyError")
    except KeyError:
        pass


def test_maxsize_shrinks_immediately():
    c = FrameCache(5)
    for i in range(5):
        c[i] = None
    c.maxsize = 2
    assert len(c) == 2 and set(c.keys()) == {3, 4}   # 保留最近使用的两个
    c.maxsize = 0
    assert len(c) == 0


def test_capacity_zero_never_stores():
    c = FrameCache(0)
    c["a"] = 1
    assert len(c) == 0 and c.get("a") is None


# ─────────────────────── ③ 统计与回调 ───────────────────────

def test_stats_counts():
    c = FrameCache(2)
    c["a"] = 1
    _ = c.get("a")        # hit
    _ = c.get("zzz")      # miss
    c["b"] = 2
    c["d"] = 3            # evict
    s = c.stats()
    assert s["hits"] == 1 and s["misses"] == 1 and s["evictions"] >= 1
    assert 0.0 <= s["hit_rate"] <= 1.0
    c.reset_stats()
    assert c.stats()["hits"] == 0


def test_on_evict_callback_and_exception_is_swallowed():
    seen = []
    c = FrameCache(1, on_evict=lambda k, v: seen.append(k))
    c["a"] = 1
    c["b"] = 2
    assert seen == ["a"]
    # 回调抛异常绝不能拖垮预览
    c2 = FrameCache(1, on_evict=lambda k, v: (_ for _ in ()).throw(RuntimeError("boom")))
    c2["a"] = 1
    c2["b"] = 2
    assert len(c2) == 1


# ─────────────────────── ④ 线程安全 ───────────────────────

def test_concurrent_read_write_no_corruption():
    """预加载线程写 + UI 线程读：不得越界、不得抛异常。"""
    c = FrameCache(50)
    errors = []

    def writer():
        try:
            for i in range(4000):
                c[i % 300] = i
        except Exception as e:      # pragma: no cover
            errors.append(e)

    def reader():
        try:
            for i in range(4000):
                c.get(i % 300)
                len(c)
                c.keys()
        except Exception as e:      # pragma: no cover
            errors.append(e)

    ts = [threading.Thread(target=writer), threading.Thread(target=reader),
          threading.Thread(target=writer), threading.Thread(target=reader)]
    for t in ts:
        t.start()
    for t in ts:
        t.join(timeout=20)
    assert not errors, errors
    assert len(c) <= 50


# ─────────────────────── ⑤ 接线与「冻结函数未改」锁 ───────────────────────

def test_preview_manager_uses_frame_cache():
    import pathlib
    src = (pathlib.Path(__file__).resolve().parents[1]
           / "core" / "preview_manager.py").read_text(encoding="utf-8")
    assert "from app.core.frame_cache import FrameCache" in src
    assert "self.preview_cache = FrameCache(self.max_cache_size)" in src
    assert "self.raw_frame_cache = FrameCache(self.max_raw_cache_size)" in src
    # 旧的 min() 淘汰必须已消失（它正是往回拖动丢帧的根因）
    assert "min(self.raw_frame_cache.keys())" not in src
    assert "OrderedDict()" not in src


def test_get_frame_at_text_unchanged():
    """★ 冻结纪律：`get_frame_at`（playback-av 冻结符号）内部对缓存的用法**一字未改**。

    本次只换协作对象（缓存实现），不改冻结代码 —— 这条断言防止后人误以为
    "动缓存就得解冻"，也防止有人顺手改坏那段文本。
    """
    import pathlib
    src = (pathlib.Path(__file__).resolve().parents[1]
           / "core" / "preview_manager.py").read_text(encoding="utf-8")
    fn = src.split("def get_frame_at(", 1)[1].split("\n    def ", 1)[0]
    for probe in (
        "cached = self.preview_cache.get(cache_key)",
        "raw_frame = self.raw_frame_cache.get(frame_idx)",
        "self.preview_cache[cache_key] = qimage",
        "self.preview_cache.popitem(last=False)",
    ):
        assert probe in fn, f"get_frame_at 内的缓存用法被改动：{probe}"
