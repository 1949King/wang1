# AI 短剧编辑器 · 跨领域协调会纪要

| 项目 | 内容 |
| --- | --- |
| 会议时间 | 2026-06-06 (Asia/Shanghai) |
| 会议主持 | 技术项目经理 (PM Agent) |
| 召开形式 | 跨领域协调会 (架构 / 前端 / AI / 数据 / 测试 / 部署) |
| 输入资料 | `CONTEXT.md` · `DEVELOPMENT_REPORT.md` · `ROADMAP_320W.md` · `PHASE1_WEEK1_SUMMARY.md` |
| 验证产物 | `app/temp/verify_output.txt` (43/43 通过, 0 失败) |

---

## 一、跨领域现状评估 (As-Is Snapshot)

### 1.1 架构 (System-Architect)
- **PyQt6 桌面端主体**: `app/main_qt6.py` 启动 → `app/modules/lego/main_window.py` 调度 → `app/modules/lego/modules.py` 渲染模块
- **核心/界面分层清晰**: `app/core/*` 处理状态/数据, `app/ui` / `modules.py` 只渲染, 无架构违反
- **新爬虫架构**: `app/modules/lego/stealth_browser.py` (底层) → `douyin_playwright_api.py` / `bilibili_playwright_api.py` (平台层) → `drama_crawler.py` (注入层)
- **风险点**: TikHub 与 Playwright 共存时 fetch 路径优先级偶发混乱 (已在 `_premium_apis` 拆分)

### 1.2 前端 (frontend-dev)
- **短剧筛选模块** (`DramaFinderModule`, `modules.py:7442`) 已实现多平台筛选 + 5 分钟自动刷新
- **本次补强**: 顶部加 "⚠️ 数据为模拟" 红条 + "❓ 数据源帮助" 按钮
- **未做**: 拖拽排序、深色/亮色主题切换、移动端适配 (短期 P2)

### 1.3 AI (ai-engineer)
- **AI 短剧理解**: `app/modules/lego/drama_understanding_engine.py` 已接入 (drama_understanding 状态机)
- **AI 脚本生成**: 已在主面板第 4 模块占位, 后端 Ollama 缺包时自动降级到本地模板
- **本次未涉及**: AI 模块代码, 仅消费 AI 数据源健康度

### 1.4 数据 (db-engineer / crawler)
- **持久化**: `app/data/store/` 目录下, `user_prefs_store.py` 实现 JSON 读写
- **数据源健康度**: `DATA_SOURCE_HEALTH` 字典 + `get_data_source_health()` 公开方法
- **真实爬虫矩阵** (本次新增):
  - 抖音: `DouyinPlaywrightAPI` (免费)
  - B 站: `BilibiliPlaywrightAPI` (免费)
  - 抖音备选: `TikHubDouyinAPI` (付费, 需 TIKHUB_API_TOKEN)
- **模拟数据 fallback**: `DouyinAPI` / `KuaishouAPI` / `BilibiliAPI` (随机生成, 仅 UI 演示)

### 1.5 测试 (qa-engineer)
- **本次验证脚本**: `app/temp/verify_playwright_crawler.py` (5 大类, 43 项)
- **首轮结果**: 40/43 通过, 3 失败
  - `douyin.health.real 注入时为 True` (FAIL)
  - `source 含 Playwright 或 TikHub` (FAIL)
  - B 站 `cover` 字段 (FAIL)
- **修复后**: 43/43 通过 ✅

### 1.6 部署 / 工程化
- **打包**: `app/packaging_env/` + `dist/` (PyInstaller 方向)
- **依赖**: `pip install playwright && playwright install chromium` (启动前必装, 失败有 fallback)
- **CI/CD**: 暂未接入, 验证脚本 `python app/temp/verify_playwright_crawler.py` 即可回归

---

## 二、本次已完成项 (Done)

| 序号 | 模块 | 内容 | 产物 |
| --- | --- | --- | --- |
| 1 | 反爬基建 | `StealthBrowser` (单例 + stealth.js + 高斯延迟) | `stealth_browser.py` |
| 2 | 抖音爬虫 | `DouyinPlaywrightAPI` (page.route 拦截 /aweme/post/) | `douyin_playwright_api.py` |
| 3 | B 站爬虫 | `BilibiliPlaywrightAPI` (page.route 拦截 /x/web-interface/) | `bilibili_playwright_api.py` |
| 4 | 备选付费 | `TikHubDouyinAPI` 改为高级 fallback | `tiktokhub_douyin_api.py` |
| 5 | 持久化 | `user_prefs_store.py` (偏好/收藏/历史) | `user_prefs_store.py` |
| 6 | 注入改造 | `DramaCrawler._init_apis` 顺序: Playwright > TikHub > Mock | `drama_crawler.py` |
| 7 | 缓存防抖 | `is_playwright_available()` 加 `_playwright_avail_cache` | `stealth_browser.py` |
| 8 | 健康度即时 | 抖音/B 站 API 在 `__init__` 即写 `DATA_SOURCE_HEALTH` | 双 API 文件 |
| 9 | UI 红条 | `DramaFinderModule` 顶部 "⚠️ 数据为模拟" 红色标签 | `modules.py:7583` |
| 10 | UI 帮助 | `DramaFinderModule` "❓ 数据源帮助" 弹窗入口 | `modules.py:7593` |
| 11 | 验证 | 修复 `verify_playwright_crawler.py` 3 个失败项 | `verify_playwright_crawler.py` |

---

## 三、待办与风险 (To-Do & Risk)

### 3.1 待办 (按优先级)

| 级别 | 描述 | 责任人 | 备注 |
| --- | --- | --- | --- |
| P0 | 真实爬虫在断网环境首次启动时, Chromium 未装好直接 fallback, 用户无感知 | qa-engineer | 启动时加 1 行日志告知 |
| P0 | 抖音反爬升级时 `_scrape_search` 静默返回 None, UI 暂无错误 Toast | frontend-dev | 接 `DramaCrawler.get_last_errors()` 到主窗口 statusBar |
| P1 | TikHub 与 Playwright 共存时, 高质量数据应优先 TikHub | backend-dev | 评估 `_premium_apis` 切换策略 |
| P1 | 帮助弹窗目前用 `QMessageBox`, 不支持超链接和滚动 | frontend-dev | 后续换 `QDialog + QTextEdit` |
| P1 | 持久化文件 `app/data/store/drama_prefs.json` 未做并发锁 | db-engineer | 评估 `fcntl` / `filelock` |
| P2 | Playwright 启动慢 (3-5s), 首次进入短剧筛选会卡 | system-architect | 改为懒加载 + splash 进度 |
| P2 | 模拟数据字典 `DRAMAS` 在 `modules.py` 写死, 真实爬虫数据未灌入 | backend-dev | 评估 `DramaCrawler.fetch_dramas()` 全量替换 |
| P2 | CI 缺位, 验证脚本未接入 pre-commit | qa-engineer | GitHub Actions 待加 |

### 3.2 风险

1. **抖音反爬风险**: Playwright 方案平均 1-2 周被反爬升级命中, 需预留 TikHub 兜底
2. **Chromium 版本耦合**: `playwright install chromium` 在低配 Windows 上偶尔失败, fallback 路径必须稳定
3. **UI 状态条闪烁**: 每次 `_refresh()` 都调 `_refresh_data_status()`, 频繁刷新会闪, 待优化为 throttle
4. **测试与生产数据不一致**: `verify_playwright_crawler.py` 用的是硬编码字典, 真实 API 字段变更时测试不会先红, 需引入 schema 校验
5. **Playwright 与 PyQt 事件循环共存**: StealthBrowser 同步 API 阻塞 Qt 线程, 长时间爬取时 UI 卡顿, 待评估 QThread 异步化

---

## 四、下 1-2 周行动清单 (Action Items)

### 4.1 第 1 周 (P0 必交付)

| ID | 行动 | 优先级 | 责任人 / Agent | 验收标准 |
| --- | --- | --- | --- | --- |
| A1 | 真实爬虫 fallback 时, 主窗口 statusBar 显示 "⚠️ 抖音数据源不可用, 已切换模拟" | P0 | frontend-dev | statusBar 出现并自动消失 |
| A2 | `DramaCrawler.get_last_errors()` 接到 UI, 错误超过 1 个时显示 Toast | P0 | frontend-dev | Toast 不阻塞, 5s 自动消失 |
| A3 | 启动日志中加 "Playwright Chromium 路径: xxx" 行, 便于排查 | P0 | backend-dev | `_init_apis` 阶段日志输出 |
| A4 | `verify_playwright_crawler.py` 接入 pre-commit 钩子 | P0 | qa-engineer | `.git/hooks/pre-commit` 写入 |
| A5 | 短剧筛选模块的 `DRAMAS` 硬编码, 改为调 `DramaCrawler.fetch_dramas()` | P0 | backend-dev | 真实数据可见, 性能可接受 |

### 4.2 第 2 周 (P1 体验优化)

| ID | 行动 | 优先级 | 责任人 / Agent | 验收标准 |
| --- | --- | --- | --- | --- |
| B1 | 帮助弹窗改 `QDialog + QTextEdit`, 支持超链接 + 滚动 + 复制 | P1 | frontend-dev | 弹窗可滚动 480 像素以上 |
| B2 | `_refresh_data_status()` 加 30s throttle, 避免频繁闪烁 | P1 | frontend-dev | 5 分钟内红条最多切换 2 次 |
| B3 | TikHub 高质量优先策略: `is_tikhub_configured()` 时, douyin 走 `_premium_apis` | P1 | backend-dev | 配 Token 后抖音数据更新更快 |
| B4 | `user_prefs_store.py` 加 `filelock` 并发保护 | P1 | db-engineer | 两个进程同时写不丢数据 |
| B5 | Playwright StealthBrowser 异步化 (QThread), 不阻塞 UI | P1 | system-architect | 抓取时主窗口可拖动 |
| B6 | `verify_playwright_crawler.py` 加 "无网络模式" 用例 (mocked 路由) | P1 | qa-engineer | CI 中无网络也能跑 |

### 4.3 第 3-4 周 (P2 规划)

| ID | 行动 | 优先级 | 责任人 / Agent | 验收标准 |
| --- | --- | --- | --- | --- |
| C1 | 接入 GitHub Actions, 跑 verify 脚本 + flake8 + mypy | P2 | qa-engineer | PR 自动检查 |
| C2 | 短剧筛选模块支持拖拽排序列 | P2 | frontend-dev | 列顺序可记忆到 user_prefs |
| C3 | 暗色/亮色主题切换, 不破坏现有样式 | P2 | frontend-dev | 主题切换不闪退 |
| C4 | 评估并接入快手 Playwright 真实爬虫 (目前仅抖音/B 站) | P2 | ai-engineer | `KuaishouPlaywrightAPI` 可用 |
| C5 | PyInstaller 打包成单 exe, 内嵌 Chromium | P2 | system-architect | 60 MB 以内可双击运行 |

---

## 五、跨领域分工一览 (RACI 简化)

| 任务类型 | 主责 Agent | 协作 Agent | 备注 |
| --- | --- | --- | --- |
| 爬虫实现 / 解析 | backend-dev | ai-engineer | 抖音/B 站/快手 |
| UI 接入 / 弹窗 | frontend-dev | backend-dev | 状态条/Toast/帮助 |
| 持久化 / 数据存储 | db-engineer | backend-dev | JSON / 后续 SQLite |
| 测试 / 验证 | qa-engineer | backend-dev | 单元/集成/E2E |
| 架构 / 性能 | system-architect | backend-dev | 异步化 / 缓存 |
| 进度协调 / 风险 | product-manager | 全部 | 本会议纪要即由 PM 主持 |

---

## 六、本次会议结论

1. **验证脚本 43/43 通过, 0 失败** ✅ — 详见 `app/temp/verify_output.txt`
2. **真实数据源矩阵就绪**: 抖音 Playwright / B 站 Playwright / 抖音 TikHub 备选
3. **UI 端"⚠️ 数据为模拟"提示与帮助弹窗** 已接入 DramaFinderModule
4. **下 1-2 周重点**: P0 错误可见性 (statusBar / Toast) + P1 体验优化 (弹窗升级 / 异步化)
5. **下次例会**: 2026-06-13 (周五), 主题 "A1-A5 收尾 + B1-B3 启动"

---

*文档归属*: `app/temp/MEETING_MINUTES_2026-06-06.md`
*产出 Agent*: 技术项目经理
*复核 Agent*: system-architect / qa-engineer
