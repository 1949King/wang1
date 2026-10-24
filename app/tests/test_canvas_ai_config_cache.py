# -*- coding: utf-8 -*-
"""画布配置缓存单测（2026-10-20 启动提速）。"""
from app.core import canvas_ai_config_cache as cache


def setup_function():
    cache.clear_caches()


def test_cached_config_hits_cache_and_deep_copies():
    calls = {"n": 0}

    def builder():
        calls["n"] += 1
        return {"channels": [{"id": "a", "models": []}]}

    first = cache.cached_config(builder, ttl=10)
    first["channels"][0]["id"] = "mutated"
    second = cache.cached_config(builder, ttl=10)
    assert calls["n"] == 1
    assert second["channels"][0]["id"] == "a"


def test_cached_config_ttl_expires():
    calls = {"n": 0}

    def builder():
        calls["n"] += 1
        return {"n": calls["n"]}

    assert cache.cached_config(builder, ttl=0)["n"] == 1
    assert cache.cached_config(builder, ttl=0)["n"] == 2


def test_clear_caches_resets_config():
    calls = {"n": 0}

    def builder():
        calls["n"] += 1
        return {"n": calls["n"]}

    cache.cached_config(builder, ttl=10)
    cache.clear_caches()
    assert cache.cached_config(builder, ttl=10)["n"] == 2


def test_ollama_models_fast_returns_immediately():
    models = cache.ollama_models_fast(lambda name: "text")
    assert models and models[0]["name"] == "llama3.2"


def test_default_models_shape():
    assert cache.default_ollama_models() == [{"name": "llama3.2", "capability": "text"}]
