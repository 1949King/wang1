# -*- coding: utf-8 -*-
"""画布渠道配置 / Ollama 模型探测缓存（2026-10-20 · 启动提速）

从 `canvas_aigc.py` 抽出（该文件有 2000 行体积基线，缓存逻辑独立成模块便于测试/复用）。
纪律：纯标准库、零 Qt；探测失败不阻塞、不抛出；缓存读写全程加锁。
"""
from __future__ import annotations

import copy
import logging
import threading
import time
from typing import Any, Callable, Dict, List

logger = logging.getLogger("AI短剧编辑器.canvas_bridge")

OLLAMA_MODELS_TTL = 300.0
_OLLAMA_CACHE: Dict[str, Any] = {
    "ts": 0.0,
    "models": None,
    "refreshing": False,
    "lock": threading.Lock(),
}

DEFAULT_CONFIG_TTL = 2.0
_CONFIG_CACHE: Dict[str, Any] = {
    "ts": 0.0,
    "data": None,
    "lock": threading.Lock(),
}


def default_ollama_models() -> List[Dict[str, str]]:
    return [{"name": "llama3.2", "capability": "text"}]


def _refresh_ollama_models_bg(guess_capability: Callable[[str], str]) -> None:
    """后台刷新 Ollama 模型列表（不阻塞 HTTP；失败写默认+时间戳防线程风暴）。"""
    models: List[Dict[str, str]] = []
    try:
        from app.modules.lego.ollama_client import ollama_client

        listed = ollama_client.list_models(force_refresh=True) or []
        for item in listed:
            name = getattr(item, "name", None) or str(item)
            if name:
                models.append({"name": name, "capability": guess_capability(name)})
    except Exception as e:  # 探测失败不影响画布打开
        logger.debug("ollama background refresh failed: %s", e)
    finally:
        with _OLLAMA_CACHE["lock"]:
            _OLLAMA_CACHE["models"] = models or default_ollama_models()
            _OLLAMA_CACHE["ts"] = time.time()
            _OLLAMA_CACHE["refreshing"] = False


def ollama_models_fast(guess_capability: Callable[[str], str]) -> List[Dict[str, str]]:
    """立即返回模型列表：命中缓存直接用；否则返回默认并后台刷新（首击不再等 4s）。"""
    now = time.time()
    with _OLLAMA_CACHE["lock"]:
        cached = _OLLAMA_CACHE["models"]
        age = now - float(_OLLAMA_CACHE["ts"] or 0.0)
        need_refresh = cached is None or age > OLLAMA_MODELS_TTL
        if need_refresh and not _OLLAMA_CACHE["refreshing"]:
            _OLLAMA_CACHE["refreshing"] = True
            threading.Thread(
                target=_refresh_ollama_models_bg,
                args=(guess_capability,),
                name="OllamaModelRefresh",
                daemon=True,
            ).start()
        if cached:
            return [dict(m) for m in cached]
    return default_ollama_models()


def cached_config(
    builder: Callable[[], Dict[str, Any]],
    *,
    ttl: float = DEFAULT_CONFIG_TTL,
) -> Dict[str, Any]:
    """整份渠道配置短 TTL 缓存（返回深拷贝，调用方可安全修改）。"""
    now = time.time()
    with _CONFIG_CACHE["lock"]:
        cached = _CONFIG_CACHE["data"]
        if cached is not None and now - float(_CONFIG_CACHE["ts"] or 0.0) < ttl:
            return copy.deepcopy(cached)
    result = builder()
    with _CONFIG_CACHE["lock"]:
        _CONFIG_CACHE["data"] = copy.deepcopy(result)
        _CONFIG_CACHE["ts"] = time.time()
    return result


def clear_caches() -> None:
    """测试/配置变更时清空缓存。"""
    with _OLLAMA_CACHE["lock"]:
        _OLLAMA_CACHE.update({"ts": 0.0, "models": None, "refreshing": False})
    with _CONFIG_CACHE["lock"]:
        _CONFIG_CACHE.update({"ts": 0.0, "data": None})
