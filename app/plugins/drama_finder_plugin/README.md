# 短剧筛选插件

> 分类: 运营工具 | 版本: 1.1.0 | 作者: 官方  
> **唯一产品入口**：插件中心（已从模块注册表移除独立「短剧筛选」模块）

---

## 功能简介

智能筛选热门短剧，分析热度与佣金。支持多平台榜单浏览与多维筛选。

### 核心能力

| 能力 | 说明 |
|------|------|
| 🎯 多平台榜单 | 抖音/快手/B站等（Playwright / TikHub / Web 兜底） |
| 🔍 多维度筛选 | 平台 × 类型 × 分类 × 关键字 × 排序 |
| 📊 双数据源 | `DramaCrawler` 真实数据 > 静态/模拟回退（有提示） |
| ⏱ 自动刷新 | 约每 5 分钟刷新 |
| 🩺 数据源监控 | 顶部状态条显示健康状态 |

---

## 插件结构

```
drama_finder_plugin/
├── __init__.py
├── main.py                 # Plugin + DramaFinderWidget
├── crawler/                # 爬虫引擎（已从 modules/lego 迁入）
│   ├── __init__.py
│   ├── drama_crawler.py
│   └── drama_web_scraper.py
├── manifest.json
└── README.md
```

Playwright 平台适配仍位于 `app/modules/lego/*_playwright_api.py`，由爬虫懒加载注入。

---

## 使用方法

1. 打开 **插件中心**
2. 启用 / 运行 **🎭 短剧筛选**
3. 在面板中筛选、刷新榜单

兼容导入（旧路径 shim）：

```python
from app.modules.lego.drama_crawler import DramaCrawler  # → 转发到插件 crawler
from app.plugins.drama_finder_plugin.crawler import DramaCrawler  # 推荐
```

---

## 更新日志

### v1.1.1 (2026-07-25)
- 无 Playwright 时优先 `app/data/drama_data.json` 静态缓存，不再被随机假 API 抢先
- WebScraper 缓存路径修正为 `app/data`
- UI 区分：真实爬取 / 静态缓存 / 模拟数据
- 验收：`test_drama_crawler_static.py`

### v1.1.0 (2026-07-25)
- 爬虫引擎打包进插件 `crawler/`
- 移除导航「短剧筛选」独立模块，仅保留插件入口

### v1.0.0 (2026-06-28)
- 首次发布为独立插件
