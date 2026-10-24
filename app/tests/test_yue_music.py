"""app/tests/test_yue_music.py — YuE（乐）全曲生成适配层回归（2026-09-28）。

覆盖核心纪律：**执行端不可用时诚实失败**（返回安装指引，绝不返回假音频），
以及请求组装与 cot 归一化。不依赖真实 YuE 安装。
"""

import pytest

from app.core.ai import yue_music as ym


@pytest.fixture(autouse=True)
def _no_yue_env(monkeypatch, tmp_path):
    """隔离环境：确保没有远程端点/本地引擎，并让路径探测落到空目录。"""
    monkeypatch.delenv(ym._ENV_ENDPOINT, raising=False)
    monkeypatch.delenv(ym._ENV_HOME, raising=False)
    # 把「项目根」指到临时目录，避免真实 thirdparty/YuE 干扰探测结果
    monkeypatch.setattr(ym, "_project_root", lambda: str(tmp_path))
    monkeypatch.setattr(ym.os.path, "expanduser", lambda p: str(tmp_path / "home"))
    yield


# ─────────────────────── 探测与诚实失败 ───────────────────────

def test_probe_unavailable_when_configured_nowhere():
    p = ym.probe_engine()
    assert p["available"] is False
    assert p["mode"] == ""
    assert p["hint"]  # 必须给安装指引，不能空手而归
    assert "SHIGUANG_YUE_ENDPOINT" in p["hint"]


def test_probe_remote_when_endpoint_set(monkeypatch):
    monkeypatch.setenv(ym._ENV_ENDPOINT, "http://gpu-box:9000/")
    p = ym.probe_engine()
    assert p["available"] is True
    assert p["mode"] == "remote"
    assert p["detail"] == "http://gpu-box:9000"  # 去掉尾斜杠


def test_probe_local_when_home_has_generate_py(monkeypatch, tmp_path):
    home = tmp_path / "YuE"
    (home / "examples").mkdir(parents=True)
    (home / "examples" / "generate.py").write_text("# stub", encoding="utf-8")
    monkeypatch.setenv(ym._ENV_HOME, str(home))
    p = ym.probe_engine()
    assert p["available"] is True
    assert p["mode"] == "local"


def test_plan_honest_failure_no_fake_score():
    r = ym.plan_song(lyrics="歌词", style="city pop")
    assert r["ok"] is False
    assert r.get("unavailable") is True
    assert "abc" not in r or not r["abc"]  # 绝不返回假谱
    assert r["hint"]


def test_render_honest_failure_no_fake_audio():
    r = ym.render_song(lyrics="歌词", style="pop")
    assert r["ok"] is False
    assert r.get("unavailable") is True
    assert "audio_url" not in r or not r["audio_url"]  # 绝不返回假音频
    assert r["hint"]


def test_empty_input_rejected_before_engine_probe():
    """歌词与风格都空 → 早退，不该报「引擎未配置」混淆视听。"""
    r = ym.plan_song(lyrics="  ", style="")
    assert r["ok"] is False
    assert "至少填一个" in r["message"]
    assert "unavailable" not in r


# ─────────────────────── 请求组装 ───────────────────────

def test_build_request_shape_and_cot_normalization():
    req = ym._build_request(lyrics=" L ", style=" S ", cot="bogus", seed=7)
    assert req["lyrics"] == "L"
    assert req["style"] == "S"
    assert req["cot"] == "full"      # 非法 cot 归一到默认
    assert req["seed"] == 7
    assert "abc" not in req           # 空谱不进请求（避免覆盖引擎自规划）


def test_build_request_includes_edited_abc():
    req = ym._build_request(lyrics="x", style="y", abc="X:1\nK:C\nCDEF|", cot="melody")
    assert req["abc"].startswith("X:1")
    assert req["cot"] == "melody"


def test_build_request_ignores_bad_seed():
    req = ym._build_request(lyrics="x", style="y", seed="not-a-number")
    assert "seed" not in req


def test_cot_modes_constant_matches_official_semantics():
    assert ym.COT_MODES == ("full", "melody", "off")
    assert ym.COT_DEFAULT == "full"


# ─────────────────────── 产物读取 ───────────────────────

def test_read_abc_finds_nested_score(tmp_path):
    nested = tmp_path / "song" / "plan"
    nested.mkdir(parents=True)
    (nested / "score.abc").write_text("X:1\nK:C\n", encoding="utf-8")
    assert ym._read_abc(str(tmp_path)).startswith("X:1")


def test_read_audio_prefers_known_extensions(tmp_path):
    (tmp_path / "notes.txt").write_text("x", encoding="utf-8")
    (tmp_path / "audio.flac").write_bytes(b"\x00" * 16)
    got = ym._read_audio(str(tmp_path))
    assert got and got.endswith("audio.flac")


def test_read_audio_none_when_absent(tmp_path):
    assert ym._read_audio(str(tmp_path)) is None
