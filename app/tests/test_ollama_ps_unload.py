# -*- coding: utf-8 -*-
"""Ollama `ps()` / `unload()` 测试 —— 资源让位的基石（P1 · 2026-10-28）。

为什么单独测这两个方法
======================
显存让位的整条链是「探测 → 卸载 → 复测」。**探测错了，后面全错**：
  · `ps()` 把"装着没加载"的模型当成"占着显存" ⇒ 会去卸一个本来就没占地方的模型，
    白花 5.5s，还让下一次对话冷启；反过来漏报 ⇒ 该卸的没卸，直接挤爆。
  · `unload()` 谎报成功（`ok=True` 但模型还在）⇒ 调用方以为腾出了 3.6GB，
    实际没腾，错误被推迟到真正分配显存的那一刻，现场离原因很远。

故这里锁三件事：
  ① **`ps()` 与 `list_models()` 是不同问题**（占着哪些 vs 装了哪些），不许混用；
  ② **卸载后必须复核**，"说卸了"不等于"卸了"；
  ③ **服务不可用/异常时优雅降级**（返回空/`ok=False`），绝不抛给调用方。

真机联调另有入口：`python scripts/verify_broker.py`（需要本机 Ollama 在跑）。
"""
from __future__ import annotations

import pytest

from app.modules.lego import ollama_client as OC


class _Resp:
    def __init__(self, status=200, payload=None, text=""):
        self.status_code = status
        self._payload = payload if payload is not None else {}
        self.text = text

    def json(self):
        return self._payload


class _Session:
    """记录请求并按序返回预设响应的假会话。

    ★ `script` **共享同一个列表**（不拷贝）：`unload()` 内部会多次新建 Session
      （ps → 逐个 generate → 复核 ps），响应顺序必须跨会话连续消费，
      各持一份拷贝会让第 2 个会话从头发起、把整条时序读错。
    """
    def __init__(self, script):
        self.script = script
        self.calls = []
        self.trust_env = True

    def get(self, url, timeout=None):
        self.calls.append(("GET", url))
        return self.script.pop(0) if self.script else _Resp()

    def post(self, url, json=None, timeout=None, **kw):
        self.calls.append(("POST", url, json))
        return self.script.pop(0) if self.script else _Resp()

    def close(self):
        pass


@pytest.fixture
def client(monkeypatch):
    """拿到单例并强制"服务可用"，避免依赖本机 Ollama。"""
    c = OC.OllamaClient()
    monkeypatch.setattr(OC.OllamaClient, "is_available",
                        lambda self, force_check=False: True, raising=True)
    return c


def _patch_sessions(monkeypatch, script):
    sessions = []

    def _factory():
        s = _Session(script)
        sessions.append(s)
        return s

    monkeypatch.setattr(OC.requests, "Session", _factory, raising=True)
    return sessions


# ══════════════════════════════════════════════════════════════════
# ps()
# ══════════════════════════════════════════════════════════════════

def test_ps_parses_loaded_models(monkeypatch, client):
    """按真实 /api/ps 响应解析（字段名取自 2026-10-28 实测返回）。"""
    _patch_sessions(monkeypatch, [_Resp(payload={"models": [{
        "name": "qwen3.5:4b",
        "size": 3136 * 1024 * 1024,
        "size_vram": 3136 * 1024 * 1024,
        "expires_at": "2026-10-28T04:06:46.4182398+14:00",
        "digest": "abc123",
    }]})])

    loaded = client.ps()

    assert len(loaded) == 1
    m = loaded[0]
    assert m.name == "qwen3.5:4b"
    assert m.size_gb == pytest.approx(3.06, abs=0.01)
    assert m.size_vram_gb == pytest.approx(3.06, abs=0.01)
    assert m.expires_at.endswith("+14:00")


def test_ps_empty_is_not_error(monkeypatch, client):
    """没有已加载模型 ⇒ 空列表（`{"models": []}` 是正常响应，不是 404）。"""
    _patch_sessions(monkeypatch, [_Resp(payload={"models": []})])
    assert client.ps() == []


def test_ps_tolerates_missing_fields(monkeypatch, client):
    """字段缺失不许抛：拿不到的当 0/空串，名字兜底取 model 字段。"""
    _patch_sessions(monkeypatch, [_Resp(payload={"models": [{"model": "llama3:8b"}]})])
    loaded = client.ps()
    assert loaded[0].name == "llama3:8b"
    assert loaded[0].size_bytes == 0


def test_ps_non_200_returns_empty(monkeypatch, client):
    _patch_sessions(monkeypatch, [_Resp(status=500)])
    assert client.ps() == []


def test_ps_unavailable_returns_empty_without_http(monkeypatch, client):
    """服务不可用 ⇒ 直接返回 []，连 HTTP 都不发。"""
    monkeypatch.setattr(OC.OllamaClient, "is_available",
                        lambda self, force_check=False: False)
    sessions = _patch_sessions(monkeypatch, [])
    assert client.ps() == []
    assert sessions == []


def test_ps_never_raises_on_broken_session(monkeypatch, client):
    """会话本身炸了也只返回 []（探测失败 ≠ 生成失败）。"""
    monkeypatch.setattr(OC.requests, "Session",
                        lambda: (_ for _ in ()).throw(RuntimeError("no net")))
    assert client.ps() == []


# ══════════════════════════════════════════════════════════════════
# unload()
# ══════════════════════════════════════════════════════════════════

def test_unload_all_sends_keep_alive_zero(monkeypatch, client):
    """卸载全部：对每个已加载模型发 keep_alive=0，且返回结果如实。"""
    sessions = _patch_sessions(monkeypatch, [
        _Resp(payload={"models": [{"name": "qwen3.5:4b", "size_vram": 1}]}),  # ps()
        _Resp(payload={}),                                                   # generate
        _Resp(payload={"models": []}),                                       # 复核 ps()
    ])

    res = client.unload()

    assert res["ok"] is True
    assert res["unloaded"] == ["qwen3.5:4b"]
    assert res["remaining"] == []
    # 每个请求都在自己的 Session 里，故跨会话汇总后再找 POST
    gen = [c for s in sessions for c in s.calls if c[0] == "POST"]
    assert gen and gen[0][2]["keep_alive"] == 0
    assert gen[0][2]["model"] == "qwen3.5:4b"


def test_unload_reports_remaining_as_not_ok(monkeypatch, client):
    """说卸了但复核还在 ⇒ **不许报 ok**（谎报成功是这条链最坏的失败）。"""
    _patch_sessions(monkeypatch, [
        _Resp(payload={"models": [{"name": "qwen3.5:4b", "size_vram": 1}]}),
        _Resp(payload={}),
        _Resp(payload={"models": [{"name": "qwen3.5:4b", "size_vram": 1}]}),  # 复核仍在
    ])

    res = client.unload()

    assert res["unloaded"] == ["qwen3.5:4b"]
    assert res["remaining"] == ["qwen3.5:4b"]
    assert res["ok"] is False
    assert "仍有 1 个加载中" in res["message"]


def test_unload_http_failure_goes_to_failed(monkeypatch, client):
    _patch_sessions(monkeypatch, [
        _Resp(payload={"models": [{"name": "m", "size_vram": 1}]}),
        _Resp(status=500),
        _Resp(payload={"models": [{"name": "m", "size_vram": 1}]}),
    ])

    res = client.unload()
    assert res["failed"] == ["m"]
    assert res["ok"] is False


def test_unload_specific_model(monkeypatch, client):
    """指定名字时只卸那一个，不去碰别的。"""
    sessions = _patch_sessions(monkeypatch, [
        _Resp(payload={"models": [{"name": "a", "size_vram": 1},
                                  {"name": "b", "size_vram": 1}]}),
        _Resp(payload={}),
        _Resp(payload={"models": [{"name": "b", "size_vram": 1}]}),
    ])

    res = client.unload("a")

    assert res["unloaded"] == ["a"]
    posts = [c for s in sessions for c in s.calls if c[0] == "POST"]
    assert len(posts) == 1 and posts[0][2]["model"] == "a"


def test_unload_nothing_loaded_is_ok(monkeypatch, client):
    """本来就没加载 ⇒ ok=True（"不需要做"不是失败）。"""
    _patch_sessions(monkeypatch, [_Resp(payload={"models": []})])

    res = client.unload()

    assert res["ok"] is True
    assert res["unloaded"] == []
    assert "无已加载模型" in res["message"]


def test_unload_unavailable_service(monkeypatch, client):
    monkeypatch.setattr(OC.OllamaClient, "is_available",
                        lambda self, force_check=False: False)
    res = client.unload()
    assert res["ok"] is False
    assert "不可用" in res["message"]


def test_unload_never_raises_when_post_explodes(monkeypatch, client):
    """POST 抛异常 ⇒ 记 failed，不向上抛（让位是优化不是前提）。"""
    _patch_sessions(monkeypatch, [_Resp(payload={"models": [{"name": "m"}]})])
    orig = OC.requests.Session

    calls = {"n": 0}

    def _factory():
        calls["n"] += 1
        s = orig()
        if calls["n"] == 2:      # 第 2 个会话（generate）炸
            s.post = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom"))
        return s

    monkeypatch.setattr(OC.requests, "Session", _factory)
    res = client.unload()
    assert res["failed"] == ["m"]
    assert res["ok"] is False


# ══════════════════════════════════════════════════════════════════
# 语义边界：ps 与 list_models 不是一回事
# ══════════════════════════════════════════════════════════════════

def test_ps_and_list_models_hit_different_endpoints(monkeypatch, client):
    """`ps()` 打 /api/ps，`list_models()` 打 /api/tags —— 两个问题不许混。"""
    sessions = _patch_sessions(monkeypatch, [
        _Resp(payload={"models": []}),                     # ps
        _Resp(payload={"models": []}),                     # tags
    ])
    client.ps()
    client.list_models(force_refresh=True)

    urls = [c[1] for s in sessions for c in s.calls if c[0] == "GET"]
    assert any(u.endswith("/api/ps") for u in urls)
    assert any(u.endswith("/api/tags") for u in urls)
