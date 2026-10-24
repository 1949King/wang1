# -*- coding: utf-8 -*-
"""数字人「口型成片」诚实合成管线单测（V4.46.4）。

锁四件事：
1. 降级判据纯函数（输入齐备度 → 路径 / 缺什么）；
2. 媒体引用解析的**安全边界**（拒绝任意绝对路径 = 防本机任意文件读取）；
3. 合成失败不留半成品、成功必带 mouth_moved=False（不冒充对口型）；
4. 真 ffmpeg 冒烟（装了才跑，没装诚实 skip）。
"""
import os
import shutil
import struct
import zlib

import pytest

from app.core.digital_human_talking import (
    PATH_STILL_VIDEO, PATH_UNAVAILABLE,
    make_talking_video, missing_inputs, plan_talking,
    resolve_media_ref, synthesize_still_video, _safe_name,
)

_HAS_FFMPEG = shutil.which("ffmpeg") is not None


# ── 1. 降级判据（纯函数）────────────────────────────────────────

def test_plan_talking_matrix():
    assert plan_talking(has_image=True, has_audio=True) == PATH_STILL_VIDEO
    assert plan_talking(has_image=False, has_audio=True) == PATH_UNAVAILABLE
    assert plan_talking(has_image=True, has_audio=False) == PATH_UNAVAILABLE
    assert plan_talking(has_image=False, has_audio=False) == PATH_UNAVAILABLE


def test_missing_inputs_names_both_gaps():
    m = missing_inputs(has_image=False, has_audio=False)
    assert len(m) == 2 and any("形象" in x for x in m) and any("配音" in x for x in m)
    assert len(missing_inputs(has_image=True, has_audio=False)) == 1
    assert missing_inputs(has_image=True, has_audio=True) == []


# ── 2. 安全边界 ────────────────────────────────────────────────

def test_resolve_rejects_absolute_path(tmp_path):
    """绝对路径必须拒 —— 否则本机任意进程能借 ffmpeg 读磁盘任意文件。"""
    secret = tmp_path / "secret.png"
    secret.write_bytes(b"\x89PNG")
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    path, err = resolve_media_ref(str(secret), str(inbox))
    assert path == "", "绝对路径不得解析成功"
    assert err, "绝对路径必须报错"


def test_resolve_rejects_traversal_and_empty(tmp_path):
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    for bad in ("", "   ", "/inbox_file/", "data:image/png;base64,!!!",
                "data:application/x-msdownload;base64,AAAA"):
        path, err = resolve_media_ref(bad, str(inbox))
        assert path == "" and err, f"{bad!r} 应被拒"


def test_resolve_rejects_missing_inbox_file(tmp_path):
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    path, err = resolve_media_ref("/inbox_file/nope.png", str(inbox))
    assert path == "" and "不存在" in err


def test_resolve_accepts_inbox_url_and_bare_name(tmp_path):
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    (inbox / "a.png").write_bytes(b"x")
    for ref in ("/inbox_file/a.png", "http://127.0.0.1:18765/inbox_file/a.png", "a.png"):
        path, err = resolve_media_ref(ref, str(inbox))
        assert err == "" and os.path.basename(path) == "a.png", ref
    # 穿越尝试：basename 后落到 inbox 内不存在的名字 ⇒ 拒（不是逃出目录）
    path, err = resolve_media_ref("/inbox_file/..%2F..%2Fwindows.png", str(inbox))
    assert path == "" and err


def test_resolve_dataurl_decodes_to_inbox(tmp_path):
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    # 1x1 PNG
    png = _make_png()
    import base64
    url = "data:image/png;base64," + base64.b64encode(png).decode()
    path, err = resolve_media_ref(url, str(inbox))
    assert err == "" and os.path.isfile(path) and path.endswith(".png")
    assert open(path, "rb").read() == png


def test_safe_name_blocks_separators():
    assert _safe_name("a.png") == "a.png"
    assert _safe_name("../../etc/passwd") in ("passwd", "")  # basename 后仍要过白名单
    assert _safe_name("") == ""
    assert _safe_name("a\nb") == ""


# ── 3. 合成失败不留半成品 / 成功必标 mouth_moved ───────────────

def test_make_talking_video_honest_when_inputs_missing(tmp_path):
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    res = make_talking_video("", "", "out.mp4", str(inbox))
    assert res["ok"] is False
    assert res["path"] == PATH_UNAVAILABLE
    assert res["mouth_moved"] is False
    assert len(res["missing"]) == 2
    assert res.get("lipsync_note"), "必须带真·口型引擎说明"
    assert not (inbox / "out.mp4").exists()


def test_synthesize_rejects_nonexistent_files(tmp_path):
    r = synthesize_still_video(str(tmp_path / "no.png"), str(tmp_path / "no.mp3"),
                               str(tmp_path / "o.mp4"))
    assert r["ok"] is False and ("不存在" in r["error"] or "ffmpeg" in r["error"])


@pytest.mark.skipif(not _HAS_FFMPEG, reason="本机未装 ffmpeg，跳过真合成")
def test_real_synthesis_produces_playable_mp4(tmp_path):
    """真跑 ffmpeg：静图 + 正弦音 → mp4（含音轨），并校验诚实标注。"""
    img = tmp_path / "p.png"
    img.write_bytes(_make_png(w=64, h=64))
    aud = tmp_path / "a.wav"
    _write_sine_wav(aud, seconds=0.6)
    out = tmp_path / "o.mp4"
    r = synthesize_still_video(str(img), str(aud), str(out))
    assert r["ok"], r.get("error")
    assert out.stat().st_size > 1024

    inbox = tmp_path / "inbox"
    inbox.mkdir()
    import shutil as sh
    sh.copy2(img, inbox / "p.png")
    sh.copy2(aud, inbox / "a.wav")
    res = make_talking_video(str(inbox / "p.png"), str(inbox / "a.wav"), "t.mp4", str(inbox))
    assert res["ok"] is True, res
    assert res["path"] == PATH_STILL_VIDEO
    assert res["mouth_moved"] is False, "静帧合成绝不能标口型已动"
    assert "口型未动" in res["note"] or "口型" in res["note"]


@pytest.mark.skipif(not _HAS_FFMPEG, reason="本机未装 ffmpeg")
def test_failed_synthesis_leaves_no_half_file(tmp_path):
    """喂坏音频 ⇒ 失败且不留半成品冒充成功。"""
    img = tmp_path / "p.png"
    img.write_bytes(_make_png())
    bad = tmp_path / "bad.wav"
    bad.write_bytes(b"not audio at all")
    out = tmp_path / "o.mp4"
    r = synthesize_still_video(str(img), str(bad), str(out))
    assert r["ok"] is False
    assert not out.exists(), "失败必须清理半成品"


# ── 测试素材构造（零外部依赖）──────────────────────────────────

def _make_png(w: int = 8, h: int = 8) -> bytes:
    def chunk(tag: bytes, data: bytes) -> bytes:
        return (struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))

    raw = b"".join(b"\x00" + bytes([200, 120, 60] * w) for _ in range(h))
    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw))
            + chunk(b"IEND", b""))


def _write_sine_wav(path, seconds: float = 0.5, rate: int = 8000) -> None:
    import math
    import wave
    n = int(rate * seconds)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"".join(
            struct.pack("<h", int(12000 * math.sin(2 * math.pi * 440 * i / rate)))
            for i in range(n)
        ))
