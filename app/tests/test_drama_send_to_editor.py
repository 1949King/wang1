# -*- coding: utf-8 -*-
"""M6：选题解析本地路径（纯数据层）。"""

from __future__ import annotations

import os

import pytest

from app.modules.lego.drama_send_to_editor import resolve_local_media_path


@pytest.mark.unit
class TestResolveDramaLocalPath:
    def test_missing_item(self):
        path, err = resolve_local_media_path(None)
        assert path is None
        assert "未选中" in err

    def test_metadata_only_honest_fail(self):
        path, err = resolve_local_media_path({
            "title": "重生之豪门千金",
            "platform": "douyin",
            "source_url": "https://example.com/x",
        })
        assert path is None
        assert "没有本地成片" in err
        assert "重生之豪门千金" in err

    def test_valid_local_path(self, tmp_path):
        f = tmp_path / "a.mp4"
        f.write_bytes(b"fake")
        path, err = resolve_local_media_path({
            "title": "测试剧",
            "local_path": str(f),
        })
        assert err == ""
        assert path == os.path.abspath(str(f))
        assert os.path.isfile(path)

    def test_invalid_path_key(self, tmp_path):
        missing = tmp_path / "gone.mp4"
        path, err = resolve_local_media_path({
            "title": "缺文件",
            "video_path": str(missing),
        })
        assert path is None
        assert "不存在" in err
