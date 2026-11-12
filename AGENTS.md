# AGENTS.md — 拾光剪影

本仓库给编码 Agent 的入口说明。

## 唯一开发文档（单一事实源）

**只读这一份：** [`docs/现行技术文档.md`](docs/现行技术文档.md)

它已覆盖：产品定位与北极星 · 技术栈 · 架构分层与真相源 · 活路径（主/副/拓展） · 冻结区 · 发展方向与优先级 · 编码规范 · **代码收敛唯一真相源** · 代码体检与审查标准。

- 历史 / 深度细节已归档至 [`docs/_archive/`](docs/_archive/)，**不作为现行依据**，也不作为开发改动入口。
- 不要编辑多份开发文档；所有架构 / 活路径 / 已知问题 / 优先级变更，统一写回 `docs/现行技术文档.md`。

## 项目记忆（跨会话连续性 · 2026-11-12 加）

上面的技术文档是**架构的事实源**；下面这些是**人踩过坑之后的经验**，两者互补，都要读。

| 位置 | 内容 | 随 git？ |
|---|---|---|
| `.workbuddy/memory/MEMORY.md` | **项目长期记忆**：定位 · 核心不变量 · 持久约束（血泪） · 验证与提交纪律 · 团队协作现状 | ✅ 已入库，clone 即有 |
| `.workbuddy/memory/YYYY-MM-DD.md` | 每日工作日志：当天实测数据、失败尝试、结论 | ⚠️ 部分入库（见下） |
| `.workbuddy/memory/topics/*.md` | 深水区：`gguf-quant` / `agent-blueprint` / `canvas-bridge` | ✅ 已入库 |
| `docs/knowledge/*.json` | 机器基线：冻结区 / 稳定性 / ruff / 覆盖 | ✅ 已入库 |

🔴 **接手第一天先读 `MEMORY.md`，再读技术文档。** 它写的是「看着能改、实际不能改」那类事——
体积守卫顶格的两个文件、冻结区、静默失败陷阱、被验证过不能信的假指标。读完能省掉大半返工。

⚠️ `.workbuddy/` 整体在 `.gitignore` 里，能进库的文件都是 `git add -f` 强制的。
**入库范围是刻意的**：只收长期记忆与有结论价值的日志（2026-10-11 / 10-15 / 11-02 / 11-04 / 11-05 / 11-09 / 11-12），
9~10 月的过程日志留在原机器。新克隆的仓库拿不到那部分，需要时从原机器拷。

## 编码铁律

见 [`.trae/rules/0.md`、`1.md`、`2.md`](.trae/rules/)（工作区自动加载）。

## 零基础接手（非技术背景负责人）

- 学习路径与恶补计划：[`docs/零基础学习路径与恶补计划.md`](docs/零基础学习路径与恶补计划.md)
- 日常操作 / 红线 / 假警报速查：[`docs/接手速查卡.md`](docs/接手速查卡.md)
- 求职准备（技术面清单 + 角色定位）：[`docs/求职准备-技术面清单与角色定位.md`](docs/求职准备-技术面清单与角色定位.md)

## 任务收尾纪律（2026-11-13 用户要求）

每完成一个任务，**实时**更新：
1. [docs/现行技术文档.md](docs/现行技术文档.md) —— 问题 / 根因 / 修复 / 验证（§40.x 追加）；
2. .workbuddy/memory/YYYY-MM-DD.md —— 当天任务清单与实测数据；
3. .workbuddy/memory/MEMORY.md —— 只写跨会话有价值的持久约束（坑/铁律）。

判定：下一个会话只读文档即可复现结论，不必问人。

## 冻结区

未获用户「解冻 \<zone-id\>」前，禁止改 `frozen_zones.json` 所列符号与 `FROZEN:*` 标记块（清单见 `docs/knowledge/frozen_zones.json`，机器基线，勿移动）。

```bash
python scripts/frozen_zone_guard.py          # 检查
python scripts/frozen_zone_guard.py --update # 解冻改完后重写基线
```

## 多会话并行协作（2026-11-04 加 · 三次实际踩坑总结）

本仓库常有多条 AI 会话**同时改同一个工作区**。以下规则不是洁癖，是三次「提交被别人的文件拦住」换来的。

### 为什么会互相卡

`scripts/precommit_gates.sh` 的十几道门禁**口径不一致**：

| 门禁 | 扫描范围 |
|---|---|
| ruff 存量棘轮 | 只看**已暂存**文件 |
| `stability_gate` 稳定性 | **全量扫工作区** |
| `frozen_zone_guard` 冻结区 | **全量扫工作区** |

⇒ 别人**未提交**的新文件只要带一处 `print` 或 `except: pass`，就能让完全不相关的你提交不了。

### 提交前自检（开工与提交前各跑一次）

```bash
python scripts/stability_gate.py     # 8 类稳定性规则，全量
python scripts/frozen_zone_guard.py  # 冻结区哈希
```

### 自己新增文件时

新文件**必须零违规**（棘轮规则：存量可宽、新增必严）。命令行工具的输出、异常钩子里的防御性吞异常，都属于**规则误判**，按守卫自带机制标注，**不要动基线**：

```python
print("...")   # stability-gate: allow-print（CLI 工具，stdout 就是产品输出）
except Exception:
    pass       # stability-gate: allow-swallow（钩子内再抛会变成记日志引发记日志）
```

🔴 **禁止用 `--update` 把违规写进基线** —— 那是让门禁闭嘴，做一次门禁就废了。

### 被别人文件卡住时的三步

1. **核准**：那几行是否真的正当？（看过实际代码再判断，别猜）
2. **能独立成立的** → 单独提一个说明性 commit 补上。先例：`NodePalette.tsx` 补回「音乐」节点面板入口 **1 行**，不补则冻结区永久红、所有人无法提交。
3. **不能独立成立的**（别人功能写了一半） → **只加行内豁免，不代提该文件**，留给对方提交。

🔴 任何情况下都**不要 `git commit --no-verify`**。

### 暂存区是共享的

- 提交一律带**精确 pathspec**：`git commit -F msg.txt -- <我的路径>...`，只提交列出的路径；
- 禁用 `git add -A` / `git add .`；
- 提交后核对 `git show --name-only HEAD`，确认没夹带别人的文件。

### `--update` 的副作用要知道

`frozen_zone_guard.py --update` 是**全量重写基线**，会把别人正在改的冻结文件**当前状态**一并锁进去。所以：要么等对方提交后再重锁，要么在 `reason` / commit message 里写明「重锁时某文件正被别人修改」。

## 关键约定备忘

- 注册表 id 为 **`extensions`**（非旧 `plugins`）。
- 时间线真相源 = `EditorModule._clips`；勿误入未接线的 `AppState` / 孤儿 `ExportRenderer`。
- 剪辑改动优先 `docs/现行技术文档.md` §4「活路径」所列文件。