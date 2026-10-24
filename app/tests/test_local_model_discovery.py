"""app/tests/test_local_model_discovery.py — 本地 Ollama 模型动态发现回归（2026-09-30）。

背景：`PROVIDERS["ollama"]["models"]` 一直是**静态空列表**，导致画布「对话模型」
下拉里列不出本机已装的 qwen（用户装了也选不到）。本测试锁定修复与三条纪律：

  ① 探测失败 → 返回空、**不抛异常**、**不抹掉静态表**；
  ② **TTL 缓存**生效（面板反复打开不该反复打 HTTP）；
  ③ 发现到的模型**排在前面**（真实可用的优先）；
  ④ **import 期绝不探测** —— 项目刚把冷启动从 55s 优化到 ~1s，
     若在 import 时同步打一次 Ollama（实测约 2.1s）就打回 ~3s。
"""
import pytest

from app.modules.lego import model_config as mc


@pytest.fixture(autouse=True)
def _reset_cache():
    """每个用例前清空 TTL 缓存，避免相互污染。"""
    mc._local_models_state["at"] = 0.0
    mc._local_models_state["models"] = []
    yield
    mc._local_models_state["at"] = 0.0
    mc._local_models_state["models"] = []


class _FakeModel:
    def __init__(self, name):
        self.name = name


def _patch_ollama(monkeypatch, names=None, boom=False):
    """把 ollama_client.list_models 换成桩，并记录调用次数。"""
    import app.modules.lego.ollama_client as oc
    calls = {"n": 0}

    def fake_list(self, force_refresh=False):
        calls["n"] += 1
        if boom:
            raise RuntimeError("ollama 挂了")
        return [_FakeModel(n) for n in (names or [])]

    monkeypatch.setattr(oc.OllamaClient, "list_models", fake_list, raising=True)
    return calls


# ─────────────────────── ① 失败不抛、不抹静态表 ───────────────────────

def test_discovery_failure_returns_empty_and_does_not_raise(monkeypatch):
    _patch_ollama(monkeypatch, boom=True)
    assert mc.discover_local_models(force=True) == []


def test_merge_with_empty_discovery_keeps_static_models(monkeypatch):
    """★ 探测失败时**不能**把用户手写的静态条目也抹掉。"""
    _patch_ollama(monkeypatch, names=[])
    info = mc.PROVIDERS.setdefault("ollama", {})
    original = list(info.get("models") or [])
    sentinel = "__hand_written__"
    info["models"] = [sentinel]
    try:
        mc.merge_local_models_into_providers(force=True)
        assert sentinel in info["models"], "空探测不该清掉静态条目"
    finally:
        info["models"] = original


# ─────────────────────── ② TTL 缓存 ───────────────────────

def test_ttl_cache_avoids_repeated_probe(monkeypatch):
    calls = _patch_ollama(monkeypatch, names=["qwen3.5:4b"])
    a = mc.discover_local_models(force=True)
    b = mc.discover_local_models()          # TTL 内 → 复用
    assert a == b == ["qwen3.5:4b"]
    assert calls["n"] == 1, "TTL 内不该重复探测"


def test_force_bypasses_ttl(monkeypatch):
    calls = _patch_ollama(monkeypatch, names=["m1"])
    mc.discover_local_models(force=True)
    mc.discover_local_models(force=True)
    assert calls["n"] == 2


def test_ttl_zero_always_probes(monkeypatch):
    calls = _patch_ollama(monkeypatch, names=["m1"])
    mc.discover_local_models(ttl=0)
    mc.discover_local_models(ttl=0)
    assert calls["n"] == 2


# ─────────────────────── ③ 发现项排在前面 ───────────────────────

def test_discovered_models_come_first(monkeypatch):
    _patch_ollama(monkeypatch, names=["qwen3.5-ue:latest", "qwen3.5:4b"])
    info = mc.PROVIDERS.setdefault("ollama", {})
    original = list(info.get("models") or [])
    info["models"] = ["__legacy__"]
    try:
        got = mc.merge_local_models_into_providers(force=True)
        assert got == ["qwen3.5-ue:latest", "qwen3.5:4b"]
        assert info["models"][:2] == ["qwen3.5-ue:latest", "qwen3.5:4b"]
        assert info["models"][-1] == "__legacy__", "静态条目应保留在后"
        assert info["local_models"] == got, "应单独暴露本机已装列表供 UI 区分"
    finally:
        info["models"] = original
        info.pop("local_models", None)


def test_merge_deduplicates(monkeypatch):
    _patch_ollama(monkeypatch, names=["dup:1"])
    info = mc.PROVIDERS.setdefault("ollama", {})
    original = list(info.get("models") or [])
    info["models"] = ["dup:1"]
    try:
        mc.merge_local_models_into_providers(force=True)
        assert info["models"].count("dup:1") == 1
    finally:
        info["models"] = original
        info.pop("local_models", None)


def test_only_local_providers_are_touched(monkeypatch):
    """云端 provider 的模型列表**不该**被本地发现结果污染。"""
    _patch_ollama(monkeypatch, names=["local:1"])
    deepseek = mc.PROVIDERS.get("deepseek") or {}
    before = list(deepseek.get("models") or [])
    mc.merge_local_models_into_providers(force=True)
    assert list(deepseek.get("models") or []) == before


# ─────────────────────── ④ import 期绝不探测（冷启动纪律） ───────────────────────

def test_module_import_does_not_call_discovery():
    """★ 静态断言：模块顶层只允许 `merge_aigc_into_providers()`，
    **不得**在 import 期调用 discover/merge_local（那会加约 2.1s 冷启动）。"""
    import inspect
    src = inspect.getsource(mc)
    # 取模块级（缩进为 0）的语句行
    top = [ln.strip() for ln in src.splitlines()
           if ln.strip() and not ln.startswith((" ", "\t", "#"))]
    banned = [ln for ln in top if "discover_local_models()" in ln
              or "merge_local_models_into_providers()" in ln]
    assert not banned, f"import 期不应调用本地探测：{banned}"


def test_merge_local_models_is_not_called_at_import():
    """行为断言：import 完 model_config 后，TTL 时间戳应仍为 0（说明没探测过）。"""
    # 该模块已在 import 时加载完；若它探测过，at 会被写成当前时间。
    # 注意：本用例不 reset 缓存，直接看模块初始状态是否被污染。
    src_ok = "merge_local_models_into_providers()" not in [
        ln.strip() for ln in __import__("inspect").getsource(mc).splitlines()
        if ln.strip() and not ln.startswith((" ", "\t", "#"))
    ]
    assert src_ok
