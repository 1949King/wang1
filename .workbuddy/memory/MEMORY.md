# 拾光剪影 — 项目长期记忆（核心事实）

> 结构化知识库（优先）：`docs/_archive/knowledge/INDEX.md`（00–19，**已归档到 `_archive/`**）
>   常查：00 概览 · 05 已知问题 · 08 冻结区 · 17 磁吸不变量 · 17 动捕设计 · 19 画布概论
> 版本历史：`docs/CHANGELOG.md`；逐轮明细：`.workbuddy/memory/YYYY-MM-DD.md`
> 本文件只留「北极星 + 核心不变量 + 用户偏好」摘要，细节一律查知识库。复核 **2026-09-21**
> 排查方法沉淀：`~/.workbuddy/skills/git-mass-deletion-triage/`（删定性）· `ast-scope-nameerror-hunt`（NameError 扫描）

## 一、产品北极星

闭环 7 阶段，V4.19.0 起「发布/数据采集/优化建议」随账号运营下线，活路径收敛为「剪辑精剪 + AI 画布」两条：精剪 → 人工改 → 文案 → 选题。
- C3 剪辑 workflow_hint ✅；仍缺：选题自动导入时间线 / 一键粗剪写 `_clips`
- 优先级：**先剪辑（稳→快→全→可维护），后 AI 闭环**

## 二、核心不变量（改动前必读，错了代价大）

1. **真相源** = `EditorModule._clips`；勿用 `AppState`/孤儿 `ExportRenderer`。`_clips` 跨线程共享、**必须持锁**：① 非原子替换整段 `with self._clips_lock:`；② 序列化/遍历用 `_clips_snapshot()`，绝不把 `self._clips` 引用交给 `json.dump`；③ 锁是 **RLock**。
2. **插件 = 两套**（别被同名类迷惑）：`ExtensionsRegistry`（`app/core/extension_base.py:332`）+ `PluginManager`（`app/core/plugin_manager.py:13`）。真家 `app/plugins/`；`plugin_*.py` 与旧 plugins 目录已归档、勿合并。
3. **冻结区 9 zone / 85 锁点**：守卫 `scripts/frozen_zone_guard.py`（仅 `--update`/`--list`，无 `--check`，无参即校验）。`canvas-magnetic-intent` 锁 33 整文件，画布改动无一例外需解冻。改 zone 同步 4 处：`frozen_zones.json` · `docs/现行技术文档.md` §5 · `.cursor/rules/frozen-zones.mdc`。
4. **两套独立版本号**：主程序 `app/version.py`；画布 `vendor/shiguang-canvas/src/canvasVersion.ts`。刻意不同步、各自递增。改画布版三件套：`canvasVersion.ts` → `package.json` → CHANGELOG。禁内联版本字符串。
5. **Agent 常量单一来源** = `app/core/agent_constants.py`（`STATUS_*` + `ERR_WAITING_APPROVAL`），禁裸字符串。
6. **能力元数据单一来源** = `app/core/agent_capability_catalog.py`；新增能力唯一入口 = 目录表加一行（`verify_catalog_consistency()` 守卫）。
7. **音画纠偏 ~280ms（冻结区）**，勿压回 80ms。
8. **内联样式 = 主题盲区**：每新增一个 `setStyleSheet` 内联控件，必须回 `set_theme()` 补刷新（对比度：深色底 `#edf3ff` / 浅色底 `#172033`）。
9. **静默 except 判定线**：UI 绘制 `pass` 可接受；状态机/资源路径 `pass` 不可接受（须 `logger.debug(..., exc_info=True)`）。例外 `except RuntimeError: pass` 有意保留。
10. **沙箱 wmic 黑名单**：import app 链触发 config_manager 的 wmic；验证脚本用 subprocess 包一层、写干净 UTF-8 再读。
11. **清理纪律（2026-09-21 血泪）**：临时文件**禁止用 `_*` 等宽 glob 清理**。必须① 显式列名单删除；② 删除前先 `git ls-files <候选>` 区分「项目自有 / 本次新建」；③ 未在 git 里的产物先确认有无副本（我曾用 `_*` 误删 6 个项目自有文件，3 个 git 跟踪的救回，3 个未跟踪 PNG 永久丢失）。
12. **git 已补-commit（2026-09-21）**：此前 HEAD 停在 2026-09-12（27 次提交），~9 天改动未提交。现已拆成 **10 个语义提交**固化（`d67f80a..5809fa3`）：config / vendor(openshot 移除 7309) / clean ×2 / core / editor / plugins / canvas / docs / verify。**只在本机，未 push**（`origin = github.com/1949King/shiguangjianying`）。四条踩坑纪律见下表。

   | 坑 | 后果 | 正解 |
|---|---|---|
   | `git add -A -f -- <目录>` | **穿透嵌套 .gitignore**，把 6462 个 node_modules + `__pycache__` + `dist/` 卷进历史（一次性 +236 万行） | 用 `git status -uall` 得到的**精确文件清单**，`-f` 是最后手段 |
   | `git check-ignore <已跟踪文件>` | 恒返回"未忽略"（默认跳过索引内的文件），误判成全都很干净 | 判历史性忽略要加 `--no-index`；其实 status 里的路径**本来就不被忽略** |
   | `git show --stat` | 长路径被截断成 `...`，统计严重失真 | 统计/审计一律用 `--numstat` + `-c core.quotePath=false` |
   | 逐文件调子进程 | 7856 次 `check-ignore` 跑了 17 分钟没出结果 | 用 `check-ignore -z --stdin` 一次批量；或把临时文件写 `tempfile.gettempdir()` |

   另记两个环境限制：沙箱**每轮最多 50 次删除**（超了连 `shutil.move` 都被拦，改用同盘 `os.rename` 或 `.git/info/exclude`）；跨盘 `rename` 会报 WinError 17。

## 三、用户习惯与偏好

- 核电管工转 AIGC；简体中文；指令极简；先看结论再展开
- 小白模式讲解：比喻 + 表格；迭代：规划→「开始」→汇总→「继续」
- 拒绝随机效果；前后端强绑定；情绪化时专业耐心推进、不回怼
- 素材库仅本机；素材网站直达在「帮助」；画布默认 `shiguang-canvas`

## 四、分区索引（细节查 `docs/_archive/knowledge/`，不在此展开）

- **磁吸系统不变量**（edge-gap 判据 / Bond 咬合 / 三段式手感 / 让位 reflow / 空间记忆 depth）→ `17-canvas-magnetic-invariants.md`（**专文**）+ `08-frozen-zones.md`
- **角色库字段模型**（一字段横跨 6 处，`visual` vs `inner` 流向）→ `_verify/check_character_schema.py`
- **画布桥接层**（`@_route_*` 注册、节点级后端化、SSE 桥、端口 18765）→ `19-canvas-design-review.md` + `05-known-issues.md`
- **参考视频驱动生视频 / 姿态解析（模式 A/B）** → `17-motion-ref-design.md`（§五已订正：**刀1/2/3 完成**，刀3=`stage3dPoseRetarget.ts`+Stage3D.tsx UI；**下一刀=刀4 录制白模视频**；刀5 通道就位、无模型支持 `video_motion`）
- **代码健康度基线**（2026-09-19 全库实测 228,583 行、`editor_module.py` 9,479 行）→ `docs/_reports/2026-09-19-全库代码评价报告.md`
- **Agent 定位「知心秘书」+ 温度开关** → `app/core/agent_persona.py`
- **冷启动性能**（MainWindow 8.24s→0.191s）→ `docs/冷启动性能诊断报告.md` + 技能 `~/.workbuddy/skills/python-coldstart-profiling/`
- **视频代码化 / 词锚定**（`timeline_dsl.py` 死代码 / `timeline_source.py` 工程源码层 / 阶段1 完成、阶段3 未做）→ `docs/_reports/2026-09-20-工程源码化与词锚定阶段1.md`（**尚未沉淀进知识库**）
