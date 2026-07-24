# 短剧筛选插件

> 分类: 运营工具 | 版本: 1.0.0 | 作者: 官方

---

## 功能简介

智能筛选热门短剧，分析热度与佣金。支持 **10+ 平台**（抖音/快手/腾讯/爱奇艺/优酷/B站/小红书/芒果/西瓜）的短剧榜单浏览。

### 核心能力

| 能力 | 说明 |
|------|------|
| 🎯 多平台榜单 | 覆盖 10+ 主流平台的短剧/漫剧/电影/电视剧数据 |
| 🔍 多维度筛选 | 按平台 × 类型 × 分类 × 关键字 × 排序 组合筛选 |
| 📊 双数据源 | `DramaCrawler` 真实 API > 120 条静态缓存回退 |
| ⏱ 自动刷新 | 每 5 分钟自动刷新榜单数据 |
| 💰 佣金透视 | 展示预估佣金与播放量对比 |
| 🩺 数据源监控 | 顶部状态条实时显示数据源健康状态 |

---

## 插件结构

```
drama_finder_plugin/
├── __init__.py        # 插件入口 + PLUGIN_INFO 元信息
├── main.py            # Plugin 类 + DramaFinderWidget UI 组件
├── manifest.json       # 插件配置文件
└── README.md          # 本文档
```

---

## 使用方法

### 方式 1: 在 APP 内启用

1. 打开 **设置 → 模块管理**
2. 找到 **🎭 短剧筛选**，勾选启用
3. 导航栏中出现 [短剧筛选] 入口

### 方式 2: 作为独立插件使用

```python
from app.plugins.drama_finder_plugin import Plugin, DramaFinderWidget

# 创建插件实例
plugin = Plugin()
plugin.initialize({"parent_widget": main_window})

# 获取 UI 组件
widget = plugin.create_widget()
layout.addWidget(widget)

# 关闭
plugin.shutdown()
```

---

## 插件接口

```python
class Plugin(IPlugin):
    @property
    def plugin_info(self) -> PluginInfo: ...
    def initialize(self, context: dict) -> bool: ...
    def shutdown(self) -> bool: ...
    def get_ui_config(self) -> dict: ...
    def run(self, data=None) -> QWidget: ...
```

---

## 依赖

- **drama_crawler**: `app/modules/lego/drama_crawler.py` — 数据爬虫引擎
- **PyQt6**: `>= 6.0` — UI 框架
- **requests**: HTTP 请求库（drama_crawler 依赖）

---

## 配置参数

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `refresh_interval` | int | 300 | 数据自动刷新间隔(秒) |
| `auto_fetch` | bool | True | 是否自动获取真实数据 |

---

## 更新日志

### v1.0.0 (2026-06-28)
- 🎉 首次发布
- 从内部模块拆分为独立插件
- 实现 IPlugin 接口, 支持完整生命周期管理
- 遵循 PLUGIN_STANDARD.md v1.0.0 规范
