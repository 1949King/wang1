# -*- coding: utf-8 -*-
"""prompt-image 失败负缓存（整改 P1-①，现行技术文档 §2d.3）

覆盖 helper 层全部语义：
- 未标记 → 不在负缓存期
- 标记后 TTL 内 → 命中（端点不再重试）
- 标记文件 mtime 超过 TTL → 不命中（允许重试，远端恢复可自愈）
- 拉取成功后清除标记 → 不再命中
- 标记/清除本身出错不抛（装饰性 IO，宁可重试不可炸端点）
- 判定出错（目录不可读等）→ 不拦

端点行为（canvas_server.py /host/prompt-image，review 级保证 3 行改动）：
负缓存命中 → 502 + 明确 message，不调 _fetch_remote_bytes；
fetch 异常 → _mark_prompt_image_failed 后原样 502；
fetch 成功 → _clear_prompt_image_failed 自愈。
"""
from __future__ import annotations

import os
import time

import app.core.canvas_bridge  # noqa: F401  # 先全量初始化桥接层（其顶部 import
# canvas_server 完整后再 re-export），避免直接 import canvas_server 触发
# 「部分初始化模块」循环导入。
import app.core.canvas_server as cs


URL_A = "https://pbs.twimg.com/media/example_a.jpg"
URL_B = "https://cdn.jsdelivr.net/gh/example/b.png"


def _use_tmp_cache(tmp_path, monkeypatch):
    """把缓存目录指到 pytest 临时目录，互不污染。"""
    monkeypatch.setattr(cs, "_PROMPT_IMAGE_CACHE_DIR", tmp_path / "prompt_images")
    return cs._PROMPT_IMAGE_CACHE_DIR


def test_unmarked_url_not_in_negative_cache(tmp_path, monkeypatch):
    _use_tmp_cache(tmp_path, monkeypatch)
    assert cs._prompt_image_failed_recently(URL_A) is False


def test_mark_then_hit_within_ttl(tmp_path, monkeypatch):
    _use_tmp_cache(tmp_path, monkeypatch)
    cs._mark_prompt_image_failed(URL_A)
    assert cs._prompt_image_failed_recently(URL_A) is True
    # 不同 URL 互不影响
    assert cs._prompt_image_failed_recently(URL_B) is False


def test_expired_mark_not_hit(tmp_path, monkeypatch):
    _use_tmp_cache(tmp_path, monkeypatch)
    cs._mark_prompt_image_failed(URL_A)
    fp = cs._prompt_image_fail_path(URL_A)
    old = time.time() - (cs._PROMPT_IMAGE_FAIL_TTL_SEC + 60)
    os.utime(fp, (old, old))
    assert cs._prompt_image_failed_recently(URL_A) is False


def test_clear_after_success(tmp_path, monkeypatch):
    _use_tmp_cache(tmp_path, monkeypatch)
    cs._mark_prompt_image_failed(URL_A)
    assert cs._prompt_image_failed_recently(URL_A) is True
    cs._clear_prompt_image_failed(URL_A)
    assert cs._prompt_image_failed_recently(URL_A) is False
    # 重复清除不抛（missing_ok）
    cs._clear_prompt_image_failed(URL_A)


def test_mark_is_idempotent_and_refresh(tmp_path, monkeypatch):
    _use_tmp_cache(tmp_path, monkeypatch)
    cs._mark_prompt_image_failed(URL_A)
    fp = cs._prompt_image_fail_path(URL_A)
    old = time.time() - (cs._PROMPT_IMAGE_FAIL_TTL_SEC + 60)
    os.utime(fp, (old, old))
    assert cs._prompt_image_failed_recently(URL_A) is False
    # 重新标记刷新 mtime → 又回到 TTL 内
    cs._mark_prompt_image_failed(URL_A)
    assert cs._prompt_image_failed_recently(URL_A) is True


def test_judgement_error_fails_open(tmp_path, monkeypatch):
    """缓存目录指向非法路径 → 判定出错 → 不拦（宁可重试不可误判）。"""
    monkeypatch.setattr(cs, "_PROMPT_IMAGE_CACHE_DIR", tmp_path / "不存在的嵌套/更深")
    assert cs._prompt_image_failed_recently(URL_A) is False
    # 标记写入失败也只是 debug 日志，不抛
    monkeypatch.setattr(cs, "_PROMPT_IMAGE_CACHE_DIR", tmp_path / "\0非法")
    cs._mark_prompt_image_failed(URL_A)  # 不应抛异常
