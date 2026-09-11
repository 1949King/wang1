# -*- coding: utf-8 -*-
"""短剧筛选 / 账号运营：只留接口壳，功能已卸须诚实失败。"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.core.capability_dispatcher import CapabilityRequest
from app.core.capability_handlers import AccountCapabilityHandlers

ROOT = Path(__file__).resolve().parents[2]
UNLOADED = "功能已卸"


@pytest.mark.unit
class TestCatalogShellsExist:
    def test_drama_finder_plugin_dir(self):
        p = ROOT / "app" / "plugins" / "drama_finder_plugin"
        assert p.is_dir()
        assert (p / "manifest.json").is_file()
        assert (p / "main.py").is_file()

    def test_account_ops_plugin_dir(self):
        p = ROOT / "app" / "plugins" / "account_ops_plugin"
        assert p.is_dir()
        assert (p / "manifest.json").is_file()
        assert (p / "main.py").is_file()


@pytest.mark.unit
class TestDramaFinderInterface:
    def test_drama_info_and_empty_fetch(self):
        from app.plugins.drama_finder_plugin.crawler.drama_crawler import (
            DramaCrawler,
            DramaInfo,
        )

        info = DramaInfo(id="x", title="t", platform="douyin", category="短剧")
        assert info.title == "t"
        crawler = DramaCrawler()
        items = crawler.fetch_dramas(content_type="drama", platform="all", page=1, page_size=20)
        assert items == []
        download = crawler.download_drama(info)
        assert download.get("success") is False
        assert UNLOADED in str(download.get("error") or "")

    def test_web_scraper_returns_no_list(self):
        from app.plugins.drama_finder_plugin.crawler.drama_web_scraper import DramaWebScraper

        rows = DramaWebScraper().fetch_hot_list(limit=5)
        assert rows == []


@pytest.mark.unit
class TestAccountCapabilitiesUnloaded:
    def test_collect_optimize_publish_honest_fail(self):
        handlers = AccountCapabilityHandlers()
        for cap in ("account.collect_data", "account.optimize_strategy", "account.publish"):
            method = cap.split(".", 1)[1]
            result = getattr(handlers, method)(CapabilityRequest(capability_id=cap))
            assert result.success is False, cap
            assert UNLOADED in (result.error or ""), cap
