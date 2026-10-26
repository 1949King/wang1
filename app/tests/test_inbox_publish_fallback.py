# -*- coding: utf-8 -*-
"""落箱失败兜底（2026-10-27）：inbox 不可写时引擎必须返回可显示的 data URL，不能只给空 URL。"""
from __future__ import annotations


import app.core.neural.video_gen as VG


def test_publish_to_inbox_surfaces_error(monkeypatch, tmp_path):
    """落箱失败必须带 error（此前静默返回 {} ⇒ 前端空 URL 白屏）。"""
    src = tmp_path / "a.png"
    src.write_bytes(b"x")
    monkeypatch.setattr("shutil.copy2", lambda *a, **k: (_ for _ in ()).throw(PermissionError("denied")))
    r = VG.publish_to_inbox(str(src))
    assert r.get("url", "") == ""
    assert "PermissionError" in str(r.get("error") or "")


def test_file_to_data_url_works_and_respects_limit(tmp_path):
    p = tmp_path / "b.png"
    p.write_bytes(b"\x89PNG" + b"0" * 32)
    url = VG.file_to_data_url(str(p), "image/png")
    assert url.startswith("data:image/png;base64,")
    # 超上限返回空（保护内存）
    assert VG.file_to_data_url(str(p), "image/png", max_mb=0.000001) == ""
    assert VG.file_to_data_url(str(tmp_path / "missing.png")) == ""


def test_generate_falls_back_to_data_url_when_publish_fails(monkeypatch, tmp_path):
    """端到端契约：publish 失败 ⇒ image_url 仍是可显示串 + warnings 说明原因。"""
    import app.core.neural.diffusers_image as DI

    out = tmp_path / "img.png"
    out.write_bytes(b"\x89PNG" + b"0" * 64)

    class FakePipe:
        pass

    eng = DI.DiffusersImageEngine()
    eng._pipe = FakePipe()
    eng._loaded_id = "sd15-t2i"

    class FakeImage:
        def save(self, path):
            out.write_bytes(b"\x89PNG" + b"0" * 64)

    def fake_t2i(**kwargs):
        return FakeImage(), {}

    monkeypatch.setattr(eng, "_t2i_image", fake_t2i)
    monkeypatch.setattr(eng, "_maybe_promote", lambda: None)
    monkeypatch.setattr(eng, "_record_telemetry", lambda *a, **k: None)
    monkeypatch.setattr(VG, "publish_to_inbox", lambda p: {"error": "PermissionError: denied"})

    res = eng.generate("sd15-t2i", prompt="x", width=64, height=64, steps=1, seed=1,
                       out_path=str(out))
    assert res.get("ok") is True, res
    assert str(res.get("image_url") or "").startswith("data:image/png;base64,")
    assert res.get("warnings"), "落箱失败必须有 warnings 如实说明"
