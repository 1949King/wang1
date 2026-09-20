# 18 · 代码库体检与优先级（2026-09-13 快照）

> 触发：用户问「哪些需要功能升级迭代/优化？哪些需要完善使用体验？」
> 方法：**实测优先于文档**——本文所有数字由脚本扫当前代码得出，不是转抄规划文档。
> 用途：作为基线快照，下次重测后对比「哪些真的动了」。

---

## 一、总判断

**这个项目不缺功能蓝图，缺的是「验证」和「让失败可见」。**

规划侧已经很扎实：知识库 21 篇 + 冻结区 9 zone / 82 锁点 + 守卫脚本 + 明确的「明确不做」清单。
短板不在想得不够，而在**工程品质闭环**：失败被吞掉、改动靠人工过 tab、类型错误可以常驻。

⇒ 下一步的最优投入**不是加功能**，而是抬高地板。

## 二、实测数据

| 项 | 实测值 | 判读 |
|---|---|---|
| `app/modules/lego/editor_module.py` | **9,078 行** | 峰值 13,321 → 已降。拆分是真做了，仍是最大文件 |
| 第二梯队大文件 | `settings_module` 2794 · `video_processor` 2732 · `canvas_aigc` 2414 · `canvas_server` 2401 · `extensions_module` 2304 · `drama_understanding_engine` 2046 · `modules.py` 1903 | **都不在拆分计划内**；「抽多少长多少」会在这批重演 |
| **`except: pass` 吞异常** | **172 处**（`editor_module` 51 · `clip_widget` 16 · `timeline_widget` 12 · `editor_agent_runtime_mixin` 6 · `local_video_infer` 6） | 与「地基①清创已完成」矛盾。**这是用户感知「点了没反应」的根源** |
| 裸 `except:` / FIXME / HACK | 0 / 0 / 0 | 卫生度其实不错 |
| TODO | 6（5 在 `deformity_repair_skill.py`） | 极少 |
| 「未实现/占位」字样 | 155 | 多为**「诚实失败」设计**，不算债 |
| 测试文件 | 33 个（`app/tests`） | 有单测，**无自动化 UI / 端到端回归** |
| `app/**/*.py` | 378 个 | |
| 画布 `src/**/*.ts(x)` | 84 个；TODO / FIXME / 未实现 = **0 / 0 / 0** | 前端很干净 |
| 画布 `as any` | **72 处**（`stores/templates.ts` 28 · `CanvasShell.tsx` 17 · `AgentPanel.tsx` 12） | 重灾区正是核心文件 |
| `tsc --noEmit` 存量错误 | **40 个，全在冻结区文件**：`riggedHumanoid.ts` 21 · `Stage3D.tsx` 16 · `bridge.ts` 3 | 不解冻就改不了；`vite build` 不做类型检查，所以不拦构建 |
| 自评体验（2026-08-11 口径） | 日常精剪 **8.0 / 10** · 可维护 **6.0** · 对标剪映 **6.5** | **可维护 6.0 是真正的洼地** |

## 三、Agent 能力面：**未达项目自定门槛**

`06-roadmap.md §E` 自定硬门槛：**≥8 个真能改 `_clips` 且可撤销的 `editor.*`**。
实测 `EditorCapabilityHandlers`（`app/core/capability_handlers.py`）：

| 类别 | 数量 | 名单 |
|---|--:|---|
| **写（改 `_clips`）** | **6** | `split_clip` · `apply_filter` · `add_transition` · `ripple_delete_range` · `set_clip_properties` · `set_keyframes` |
| 读 / 建议 | 6 | `get_timeline_context` · `inspect_media` · `get_media`(别名) · `suggest_cleanup` · `send_selected_to_canvas` · `suggest_canvas_roundtrip` |

⇒ **6 / 8，差 2 个**。

**另有一处清单不一致**：`capability_handlers.py` 注册 **34** 个能力，
而 `app/core/agent_action_registry.py` 只列 **15** 个（缺 `editor.get_media`、
`editor.send_selected_to_canvas`、`editor.suggest_canvas_roundtrip` 等）。
白名单与实现面会脱节 ⇒ **建议两者从同一来源生成，而不是各写一份**。

## 四、优先级

### ① 立刻做（影响大 · 成本低）

| 项 | 为什么 | 怎么算完成 |
|---|---|---|
| **172 处 `except: pass` → 日志/状态条** | 直接消灭「点了没反应」；同时涨「体验」与「可维护」两项分，且不动架构 | 长尾路径上的失败能在日志/状态条看到 |
| **长对白 scrub 真压测** | 现在只有冒烟（`test_long_dialogue_smoke.py`），没有压测数据 | 有前后对比或日志证据 |

### ② 值得规划（影响大 · 成本高）

| 项 | 为什么 | 注意 |
|---|---|---|
| **一条端到端冒烟**：导入 → 切 → 预览 → 导出 | 项目自称「无自动化 UI 测试，需人工过一遍」——这是「可维护 6.0」的真正原因，**比继续拆文件更能涨分** | 能命令行跑通即可，不必上 CI |
| **Agent 写能力补到 8 + 清单归一** | 项目自己设的门槛，未达就不该加大总控投入 | 候选：`editor.trim_clip` / `editor.move_clip` |
| **给第二梯队上帝类定规矩** | 否则 `editor_module` 省下的行数会被 `settings_module` / `video_processor` / `canvas_server` 吃掉 | 沿用 10 号文档的「低风险先抽（UI 构建）」打法 |

### ③ 先别碰（高风险或低收益）

| 项 | 理由 |
|---|---|
| **时间线核心状态机重构**（`_render_timeline_frame` / `_apply_action` / `__init__`） | 拆了等于重新设计生命周期，不是搬方法体 |
| **口型驱动成片** | 等外部形象驱动模型；项目已正确标注「无模型不假成功」 |
| **画布 `as any` / tsc 存量错误收敛** | 目标文件在 `stage3d-core` 冻结区内，要先解冻 |

### ④ 要保住的优点（别在重构中弄丢）

- **诚实失败**：不写假成功。这是很正确的产品判断，比"看起来能跑"值钱。
- **冻结区机制**：2026-09-13 两次解冻都靠它拦住盲改（还发现 2 个 zone 漏登记）。
- **知识库体系**：21 篇 + SSOT + 守卫脚本，个人项目里罕见。

## 五、需要用户拍板的一件事

`riggedHumanoid.ts`(21) / `Stage3D.tsx`(16) / `bridge.ts`(3) 的 **40 个类型错误全在冻结区**。
两条路，必须选一条：

1. **解冻修** → 修完 `frozen_zone_guard.py --update` 重锁（有回归风险，但能把 3D 导演台拉回类型安全）；
2. **接受现状** → 明确记录「3D 台带着 40 个类型错误长期运行」，后续新增代码不得再引入类型错误。

不清不楚地挂着是最差选项：类型错误会持续掩盖真 bug，而且 `vite build` 不会拦。

## 六、复测方法（下次对比用）

```python
# 吞异常计数
re.findall(r'except[^\n]*:\s*\n\s*pass\b', 源码)
# tsc 存量错误
cd vendor/shiguang-canvas && node node_modules/typescript/bin/tsc --noEmit
# 能力面
capability_handlers.py 内 dispatcher.register("editor.*") 的条数
# 冻结区
python scripts/frozen_zone_guard.py
```
