"""兼容层：转发 `app.plugins.drama_finder_plugin.crawler` 接口壳。

爬虫功能已卸；本文件只给 workflow / 旧导入路径保留 DramaInfo 等名字。
"""

from app.plugins.drama_finder_plugin.crawler.drama_crawler import *  # noqa: F401,F403
from app.plugins.drama_finder_plugin.crawler.drama_crawler import (  # noqa: F401
    DATA_SOURCE_HEALTH,
    DramaCrawler,
    DramaInfo,
    drama_crawler,
)
