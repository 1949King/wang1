"""兼容层：短剧爬虫引擎已迁入 `app.plugins.drama_finder_plugin.crawler`。

请优先从插件导入；本文件仅保留给 workflow / Playwright API 等旧路径。
"""

from app.plugins.drama_finder_plugin.crawler.drama_crawler import *  # noqa: F401,F403
from app.plugins.drama_finder_plugin.crawler.drama_crawler import (  # noqa: F401
    DATA_SOURCE_HEALTH,
    DramaCrawler,
    DramaInfo,
    drama_crawler,
)
