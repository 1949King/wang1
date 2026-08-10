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
| `drama-finder-ui` | 短剧筛选可视化 |
| `plugin-store-catalog` | 插件商店真实目录 |

共 **7** 个 zone（与 `frozen_zones.json` 一致；guard 锁定数以脚本输出为准）。

### 宿主漂移备注（2026-08-04）

- `drama-finder-ui` 冻结符号仍覆盖 `plugins_module.py` 若干方法 + `drama_ui.py`。
- 运行时主入口已迁至 **`extensions_module`**（弹窗打开短剧）；`plugins` 不在注册表。
- 改短剧 UI 时：优先解冻后改 `drama_ui.py`；若动拓展中心宿主，勿 silently 回退已修的 initialize/`_widget` 自愈逻辑。
- 商店目录冻结仍约束「只上架 `app/plugins` 真实项」。

## 解冻流程（仅当用户明确要求）

1. 用户说：「解冻 playback-av」等
2. 修改对应代码
3. `python scripts/frozen_zone_guard.py --update`
4. 用户确认后视为重新上锁

## Agent / 人

- Cursor 规则：[`.cursor/rules/frozen-zones.mdc`](../../.cursor/rules/frozen-zones.mdc)
- 编码规则摘要见 [`07-coding-rules.md`](07-coding-rules.md)
