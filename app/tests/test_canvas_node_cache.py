"""app/tests/test_canvas_node_cache.py — 画布节点增量缓存回归（2026-09-28）。

覆盖三条核心纪律：
① 指纹**确定性**（键序无关）且**排除输出字段**（否则生成一次就永不命中）；
② 指纹**含上游**（改上游 → 下游失效）；
③ 读写/失效/清空/统计；异常绝不抛出。
"""

import pytest

from app.core import canvas_node_cache as c


@pytest.fixture(autouse=True)
def _isolated_store(monkeypatch, tmp_path):
    """把缓存落到临时目录，绝不污染 data/canvas_node_cache.json。"""
    monkeypatch.setenv(c._STORE_ENV, str(tmp_path / "cache.json"))
    yield


# ─────────────────────── 指纹 ───────────────────────

def test_fingerprint_key_order_independent():
    a = c.node_fingerprint("image", {"prompt": "一只猫", "duration": 5})
    b = c.node_fingerprint("image", {"duration": 5, "prompt": "一只猫"})
    assert a == b


def test_fingerprint_excludes_output_fields():
    """生成产物回写后指纹必须不变，否则缓存永不命中。"""
    base = {"prompt": "一只猫", "duration": 5}
    with_out = {**base, "imageUrl": "http://x/a.png", "status": "done",
                "proxyScore": 0.9, "lastSeed": 42, "progress": 100}
    assert c.node_fingerprint("image", base) == c.node_fingerprint("image", with_out)


def test_fingerprint_changes_on_param_change():
    a = c.node_fingerprint("image", {"prompt": "猫"})
    b = c.node_fingerprint("image", {"prompt": "狗"})
    assert a != b


def test_fingerprint_changes_on_kind_change():
    assert c.node_fingerprint("image", {"prompt": "x"}) != \
        c.node_fingerprint("video", {"prompt": "x"})


def test_fingerprint_includes_upstream():
    p = {"prompt": "x"}
    assert c.node_fingerprint("image", p, ["aaaa"]) != \
        c.node_fingerprint("image", p, ["bbbb"])


def test_fingerprint_upstream_order_independent():
    p = {"prompt": "x"}
    assert c.node_fingerprint("video", p, ["a", "b"]) == \
        c.node_fingerprint("video", p, ["b", "a"])


def test_fingerprint_ignores_empty_upstream():
    """空/None 上游不应改变指纹（上游是可选语义）。"""
    p = {"prompt": "x"}
    assert c.node_fingerprint("image", p) == \
        c.node_fingerprint("image", p, [""]) == \
        c.node_fingerprint("image", p, [None])


def test_fingerprint_unserializable_value_is_deterministic():
    """个别值不可 JSON 序列化时仍须确定性（退化 repr），不得抛异常。"""
    def fn(x):          # 刻意传一个「不可 JSON 序列化」的值
        return x
    a = c.node_fingerprint("image", {"prompt": "x", "cb": fn})
    b = c.node_fingerprint("image", {"cb": fn, "prompt": "x"})
    assert a == b


# ─────────────────────── 读写 ───────────────────────

def test_store_lookup_roundtrip(tmp_path):
    s = c.NodeCacheStore(store_path=str(tmp_path / "s.json"))
    assert s.lookup("deadbeef") is None
    s.store("deadbeef", {"url": "a.png", "seed": 7}, kind="image")
    hit = s.lookup("deadbeef")
    assert hit == {"url": "a.png", "seed": 7}


def test_lookup_returns_copy_not_reference(tmp_path):
    """返回浅拷贝：外部改动不应污染缓存内部状态。"""
    s = c.NodeCacheStore(store_path=str(tmp_path / "s.json"))
    s.store("fp1", {"url": "a.png"})
    got = s.lookup("fp1")
    got["url"] = "TAMPERED"
    assert s.lookup("fp1")["url"] == "a.png"


def test_persist_across_instances(tmp_path):
    p = str(tmp_path / "s.json")
    a = c.NodeCacheStore(store_path=p)
    a.store("fp1", {"url": "a.png"})
    b = c.NodeCacheStore(store_path=p)
    assert b.lookup("fp1") == {"url": "a.png"}


def test_invalidate_and_clear(tmp_path):
    s = c.NodeCacheStore(store_path=str(tmp_path / "s.json"))
    s.store("fp1", {"u": "1"})
    s.store("fp2", {"u": "2"})
    assert s.invalidate("fp1") is True
    assert s.lookup("fp1") is None
    assert s.invalidate("fp1") is False       # 再删已不存在
    assert s.clear() == 1                     # 只剩 fp2
    assert s.lookup("fp2") is None


def test_empty_fingerprint_never_matches(tmp_path):
    s = c.NodeCacheStore(store_path=str(tmp_path / "s.json"))
    s.store("", {"u": "1"})                   # 空指纹应被忽略
    assert s.lookup("") is None


def test_none_output_not_stored(tmp_path):
    s = c.NodeCacheStore(store_path=str(tmp_path / "s.json"))
    s.store("fp1", None)
    assert s.lookup("fp1") is None


def test_ttl_zero_never_expires(tmp_path):
    """ttl_days=0 表示永不过期。"""
    s = c.NodeCacheStore(store_path=str(tmp_path / "s.json"), ttl_days=0)
    s.store("fp1", {"u": "1"})
    assert s.lookup("fp1") is not None


def test_ttl_negative_clamped_to_zero(tmp_path):
    """负 TTL 无语义 → 夹到 0（=不过期），不得抛异常。"""
    s = c.NodeCacheStore(store_path=str(tmp_path / "s.json"), ttl_days=-1)
    s.store("fp1", {"u": "1"})
    assert s.lookup("fp1") is not None


def test_ttl_expiry_on_stale_entry(tmp_path):
    """真实过期：last_used 久远 → 不命中；但**只影响命中，不删数据**。"""
    s = c.NodeCacheStore(store_path=str(tmp_path / "s.json"), ttl_days=1)
    s.store("fp1", {"u": "1"})
    s._ensure_loaded()
    s._entries["fp1"]["last_used"] = 0.0        # 1970 年 → 必然过期
    assert s.lookup("fp1") is None
    assert "fp1" in s._entries                  # 过期不删数据（与 draw_book 同纪律）


def test_stats_shape(tmp_path):
    s = c.NodeCacheStore(store_path=str(tmp_path / "s.json"))
    s.store("fp1", {"u": "1"})
    s.lookup("fp1")
    s.lookup("nope")
    st = s.stats()
    assert st["entries"] == 1
    assert st["hits"] == 1
    assert st["misses"] == 1
    assert st["hit_rate"] == 0.5


def test_lru_eviction(tmp_path):
    s = c.NodeCacheStore(store_path=str(tmp_path / "s.json"), max_entries=10)
    for i in range(20):
        s.store(f"fp{i}", {"u": str(i)})
    assert s.stats()["entries"] <= 10


def test_corrupt_store_starts_empty(tmp_path):
    """缓存文件损坏不得抛异常，按空缓存启动。"""
    p = tmp_path / "bad.json"
    p.write_text("{ this is not json", encoding="utf-8")
    s = c.NodeCacheStore(store_path=str(p))
    assert s.lookup("anything") is None
    s.store("fp1", {"u": "1"})                # 仍可正常写入
    assert s.lookup("fp1") is not None


def test_get_store_singleton():
    assert c.get_store() is c.get_store()
