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

copywriting · tasks · materials · models · characters …

### EXPERIMENTAL

account（默认关）· **extensions（拓展中心，默认开）** · performance（默认关）· ai_clip_flow（默认关）…

注册表内有 **`plugins` → `extensions` 迁移**逻辑；旧开关文件可能被改写。

**短剧筛选**：已从注册表移除；**仅插件**  
`app/plugins/drama_finder_plugin/`（含 `crawler/`）。  
运行时入口：拓展中心打开 / `plugin.run()` → `DramaFinderWidget`。  
`modules/lego/drama_crawler.py` 为兼容 shim。  
`plugins_module.py` 仍含常驻标签实现，但**未注册**，勿当主入口。

开关持久化：QSettings + `app/data/module_switches.json`；变更发 `MODULE_CONFIG_CHANGED`。

## 非剪辑完善度速查（2026-08 复核）

| 档 | 模块 | 备注 |
|----|------|------|
| 可用 | settings · help · performance | 监控依赖 psutil / nvidia-smi |
| 半通 | copywriting · tasks · models · characters · ai_clip_flow · extensions | 需 Provider / 重依赖；拓展中心默认开 |
| 易误导 | materials（在线） | 仍随机造卡 / MOCK 下载 |
| 插件 | 短剧筛选 drama_finder_plugin | 真榜单依赖 Playwright/TikHub；默认静态缓存 |
| 闭环 | account + viral | **C1/C2 ✅**；**C3 剪辑跳转 ✅**；**C3 短剧跳转 ⚠️**（仍 `target=plugins`，与 registry 不一致）；自动选题导入 ❌ |

冷启动导航（无覆盖）：home · editor · settings · help · **extensions**。

## 剪辑内标签（摘要）

属性 / 调色 / 特效 / 文字 / 贴纸 / 音频 / 角色 / AI（含 Agent）/ 导出  

（关键帧 / LUT / speed / 波形 / 字幕 B0–B2 见 05、03。）

## 相关文档

- 完整清单：根目录 `功能模块清单与优化保留承诺_2026-07-22.md`
- 拆分计划：`app/modules/lego/REFACTOR_PLAN.md`（**过时**，仍指向已删除大文件；以本库 00/06 为准）
- 帮助：`docs/help/editor.md`
- 已知问题：[05-known-issues.md](05-known-issues.md)
