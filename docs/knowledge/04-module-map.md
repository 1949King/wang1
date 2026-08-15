# 04 — 模块地图

来源：`module_registry.py` + `功能模块清单与优化保留承诺_2026-07-22.md`  
承诺：**优化不删功能**（🟢保留增强 / 🔵接线激活 / 🟡重构保留）。  
复核：2026-08-04

## 注册表分级

### CORE（默认开，不可关）

| id | 名称 | 入口类 |
|----|------|--------|
| home | 首页 | `modules.HomeModule` |
| editor | 剪辑 | `editor_module.EditorModule` |
| settings | 设置 | `settings_module.SettingsModule` |
| help | 帮助 | `help_module.HelpModule` |

### ADVANCED（默认关）

copywriting · tasks · materials · models · **characters（AI 画布）** …

### EXPERIMENTAL

account（**已迁插件**，见下）· **extensions（拓展中心，默认开）** · performance（默认关）· ai_clip_flow（默认关）…

注册表内有 **`plugins` → `extensions` 迁移**逻辑；旧开关文件可能被改写。旧 `account` 开关会被丢弃。

**短剧筛选**：已从注册表移除；**仅插件**  
`app/plugins/drama_finder_plugin/`（含 `crawler/`）。  

**账号运营**：已从注册表移除（2026-08）；**仅插件**  
`app/plugins/account_ops_plugin/`（UI 仍复用 `account_ops_module.py`）。  
入口：拓展中心顶部「👤 账号运营」/ 首页快捷 / `MODULE_ACTIVATED{target:extensions, action:account_ops}`。  
`account_skills` + `account.*` capability 仍注册，供 Agent 调用。

开关持久化：QSettings + `app/data/module_switches.json`；变更发 `MODULE_CONFIG_CHANGED`。

## 非剪辑完善度速查（2026-08 复核）

| 档 | 模块 | 备注 |
|----|------|------|
| 可用 | settings · help · performance | 监控依赖 psutil / nvidia-smi |
| 半通 | copywriting · tasks · models · ai_clip_flow · extensions | 需 Provider / 重依赖；拓展中心默认开 |
| **AI 画布** | characters（原角色管理） | 镶嵌 infinite-canvas；静态 `:3001` / Vite `:3000`；桥 `:18765`；Agent `:17371` 自动预热；模型池含 **AIGC**（`shiguang-aigc`，优先 ChatGPT2API gpt-image-2 / 硅基 FLUX·Wan 等）；剪辑可「发送到画布」 |
| 易误导 | — | （原 materials 在线假目录已移除，见 05） |
| 插件 | 短剧筛选 drama_finder_plugin | 真榜单依赖 Playwright/TikHub；默认静态缓存 |
| 插件 | 账号运营 account_ops_plugin | **C1/C2 ✅**；无平台真播放 API；发布常降级本地队列 |
| 闭环 | account skills + viral | UI 在拓展中心；**C3 跳转 ✅（M1）**；**选题进时间线 ✅（M6）** |

冷启动导航（无覆盖）：home · editor · settings · help · **extensions**。

## 剪辑内标签（摘要）

属性 / 调色 / 特效 / 文字 / 贴纸 / 音频 / 角色 / AI（含 Agent）/ 导出  

（关键帧 / LUT / speed / 波形 / 字幕 B0–B2 见 05、03。）

## 相关文档

- 完整清单：根目录 `功能模块清单与优化保留承诺_2026-07-22.md`
- 拆分计划：`app/modules/lego/REFACTOR_PLAN.md`（**过时**，仍指向已删除大文件；以本库 00/06 为准）
- 帮助：`docs/help/editor.md`
- 已知问题：[05-known-issues.md](05-known-issues.md)
