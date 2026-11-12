# -*- coding: utf-8 -*-
"""服务端"已同意"记录（2026-11-12）：跨重启记住，坏文件按未同意。"""
import json

import app.core.compliance_accept as CA


def test_write_then_read(tmp_path, monkeypatch):
    p = tmp_path / "acc.json"
    monkeypatch.setattr(CA, "state_path", lambda: str(p))
    assert CA.read_state()["accepted"] is False
    assert CA.write_state("2026-11-12.1", "2026-11-12T10:00:00") is True
    st = CA.read_state()
    assert st["accepted"] is True
    assert st["version"] == "2026-11-12.1"
    assert st["at"].startswith("2026-11-12")


def test_corrupt_file_means_not_accepted(tmp_path, monkeypatch):
    p = tmp_path / "acc.json"
    p.write_text("{broken", encoding="utf-8")
    monkeypatch.setattr(CA, "state_path", lambda: str(p))
    assert CA.read_state()["accepted"] is False


def test_missing_dir_is_created(tmp_path, monkeypatch):
    p = tmp_path / "sub" / "acc.json"
    monkeypatch.setattr(CA, "state_path", lambda: str(p))
    assert CA.write_state("v", "t") is True
    assert json.loads(p.read_text(encoding="utf-8"))["accepted"] is True