# 08 — 冻结区（已修好功能锁死）

> **目的**：防止后续改动回退已验证的音画/变换/插件能力。  
> **机器校验**：`python scripts/frozen_zone_guard.py`

## 清单

机器可读：[`frozen_zones.json`](frozen_zones.json)  
哈希基线：[`frozen_zones.hashes.json`](frozen_zones.hashes.json)（由 guard `--update` 生成）

| zone-id | 标题 |
|---------|------|
| `playback-av` | 时间线播放 · 音画同步（2026-08-07 解冻接 speed_ramp 后已重锁） |
| `exit-media` | 关程序停声 · 防幽灵音频 |
| `clip-transform` | 归一化变换模型 |
| `transform-bake` | 变换关键帧导出 bake |
| `canvas-transform` | 预览画布变换交互 |
| `plugin-host-ui` | 插件宿主常驻 UI 入口（短剧筛选功能已卸，宿主打开/关闭仍冻结） |
| `plugin-store-catalog` | 插件商店真实目录 |
| `stage3d-core` | 3D导演台 · 模型渲染与桥接（2026-08-20 冻结：GLB 加载/骨骼/材质/端口/桥接整文件哈希） |
| `canvas-magnetic-intent` | 画布磁吸意图系统 · 导演卡 + L1 参数（2026-09-12 冻结：磁吸/六向槽位/导演卡拆解/L1 参数整文件哈希） |

共 **9** 个 zone（与 `frozen_zones.json` 一致；`stage3d-core` 为 2026-08-20 新增、锁 7 个整文件；`canvas-magnetic-intent` 为 2026-09-12 新增、锁 22 个整文件；JSON 中 id 为 `plugin-host-ui` 而非旧名 `drama-finder-ui`；guard 锁定数以脚本输出为准）。

### 宿主漂移备注（2026-08-19）

- 冻结符号只覆盖 `plugins_module.py` 的 `_plugin_offers_widget_ui` / `_ensure_plugin_initialized` / `_open_plugin_ui`。
- 运行时主入口仍是 **`extensions_module._open_drama_finder`**；`drama_ui.py` 现为占位页，不在冻结符号表。
- 商店目录冻结仍约束「只上架 `app/plugins` 真实项」；卸空后目录仍在，勿删 `drama-finder` / `account-ops` 条目。

## 解冻流程（仅当用户明确要求）

1. 用户说：「解冻 playback-av」等
2. 修改对应代码
3. `python scripts/frozen_zone_guard.py --update`
4. 用户确认后视为重新上锁

## Agent / 人

- Cursor 规则：[`.cursor/rules/frozen-zones.mdc`](../../.cursor/rules/frozen-zones.mdc)
- 编码规则摘要见 [`07-coding-rules.md`](07-coding-rules.md)
