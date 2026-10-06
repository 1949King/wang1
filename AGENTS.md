# AGENTS.md — 拾光剪影

本仓库给编码 Agent 的入口说明。

## 唯一开发文档（单一事实源）

**只读这一份：** [`docs/现行技术文档.md`](docs/现行技术文档.md)

它已覆盖：产品定位与北极星 · 技术栈 · 架构分层与真相源 · 活路径（主/副/拓展） · 冻结区 · 发展方向与优先级 · 编码规范 · **代码收敛唯一真相源** · 代码体检与审查标准。

- 历史 / 深度细节已归档至 [`docs/_archive/`](docs/_archive/)，**不作为现行依据**，也不作为开发改动入口。
- 不要编辑多份开发文档；所有架构 / 活路径 / 已知问题 / 优先级变更，统一写回 `docs/现行技术文档.md`。

## 编码铁律

见 [`.trae/rules/0.md`、`1.md`、`2.md`](.trae/rules/)（工作区自动加载）。

## 零基础接手（非技术背景负责人）

- 学习路径与恶补计划：[`docs/零基础学习路径与恶补计划.md`](docs/零基础学习路径与恶补计划.md)
- 日常操作 / 红线 / 假警报速查：[`docs/接手速查卡.md`](docs/接手速查卡.md)
- 求职准备（技术面清单 + 角色定位）：[`docs/求职准备-技术面清单与角色定位.md`](docs/求职准备-技术面清单与角色定位.md)

## 冻结区

未获用户「解冻 \<zone-id\>」前，禁止改 `frozen_zones.json` 所列符号与 `FROZEN:*` 标记块（清单见 `docs/knowledge/frozen_zones.json`，机器基线，勿移动）。

```bash
python scripts/frozen_zone_guard.py          # 检查
python scripts/frozen_zone_guard.py --update # 解冻改完后重写基线
```

## 关键约定备忘

- 注册表 id 为 **`extensions`**（非旧 `plugins`）。
- 时间线真相源 = `EditorModule._clips`；勿误入未接线的 `AppState` / 孤儿 `ExportRenderer`。
- 剪辑改动优先 `docs/现行技术文档.md` §4「活路径」所列文件。