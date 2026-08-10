# 10 — `editor_module.py` 拆分方案（量化分析 + 提案，未执行代码拆分）

> 状态：**分析 + 方案文档**。本轮只做量化分析与方案设计，**不直接对 13k 行宿主做拆分操作**——
> 该文件是活路径核心且贴近 `playback-av`/`clip-transform` 两个冻结区，任何拆分都必须先经用户确认范围与顺序再动手，一次性大改风险远高于收益。

## 一、量化现状（AST 实测，2026-08-11）

```
文件总行数：13,321
EditorModule 类体：12,855 行（占全文件 96.5%）
类内直接定义的方法数：423 个
方法体行数合计：12,281 行（类体中剩余 ~574 行为类属性/文档字符串/空行）
```

对照文档历史记录：2026-07-28 抽出 `editor_subtitle_panel.py` 后号称"约 10.8k 行"，2026-08-05 P0 拆分后记录"10424 行"。**实测已达 13,321 行**——即使算上两次 Mixin 抽出，宿主净增长约 2,900 行，说明**新功能进入速度远快于拆分速度**，拆分工作在过去几轮里事实上处于"抽多少长多少"的负增长状态。

## 二、按职责分组统计（423 个方法，正则前缀/关键词归类，非人工猜测）

| 分组 | 方法数 | 行数 | 占比 |
|---|--:|--:|--:|
| 时间线编辑（clip/trim/split/cut/track/ripple/snap/select/drag） | 79 | 2249 | 17.4% |
| AI/Agent 工具（ai_/agent_/llm/funclip/autoclip/fusion/lora/viral/character/deform） | 61 | 2117 | 16.4% |
| 预览/渲染（preview/render/gl_/frame/letterbox/scrub） | 51 | 1966 | 15.2% |
| 事件回调（`_on_*`/`eventFilter`/`_handle`） | 32 | 869 | 6.7% |
| 特效/滤镜/调色/转场（filter/effect/color/lut/transition/keyframe） | 29 | 624 | 4.8% |
| UI 构建（`_create_*`/`_make_*`/`*_panel`/`*_tab`/toolbar/shortcut） | 10 | 792 | 6.1% |
| 贴纸/画布/PiP（sticker/canvas/pip/overlay） | 15 | 376 | 2.9% |
| 导出（export/build_edited/multitrack/ffmpeg） | 14 | 350 | 2.7% |
| 工程 IO（project/autosave/import/export_project） | 8 | 254 | 2.0% |
| 音频（audio/bgm/volume/waveform） | 11 | 211 | 1.6% |
| 字幕（subtitle/burn/ass/srt） | 16 | 240 | 1.9% |
| **未归类（核心机制，见下）** | 97 | 2233 | 17.3% |

未归类里最大的方法（核心状态机/生命周期，**不建议移动**）：`__init__`（192）、`_apply_action`（113，撤销/重做统一入口）、`_detect_beats`（72）、`_sync_timeline_widget_state`（70）、`_heal_linked_av_duration_mismatch`（68）、`_apply_curves`（66）、`_sync_kernel_timeline`（59）、`_apply_chroma_key`（54）、`_import_video`（52）、`_load_video`（50）。

**关键发现**：此前几轮拆分（`ai_agent_panel.py` Mixin）只抽出了 6 个"对话式 Agent 指令"方法（242 行），但真正膨胀的是 **61 个"AI 工具按钮"方法共 2117 行**（FunClip/AutoClip/Fusion/LoRA/五维打分/形变修复/角色面板刷新等）——这批此前完全没有被纳入任何一轮拆分范围，是文档"仍抽 UI Mixin，宿主仍膨胀"现象的主因之一。

## 三、候选提取分组的风险分级

| 候选分组 | 行数 | 风险 | 理由 |
|---|--:|---|---|
| **UI 构建（10 方法/792 行）** | 792 | 🟢 低 | 纯 `QWidget`/`QLayout` 搭建（如 `_create_params_tab`/`_create_timeline_panel`/`_make_effect_tab`），已验证不是薄包装而是完整实现；不碰 `_clips`/播放时钟；抽出模式与已完成的 `editor_subtitle_panel.py` 完全一致 |
| **AI 工具方法（61 方法/2117 行）** | 2117 | 🟡 中 | 多数是独立按钮回调（`_funclip_process`/`_autoclip_process`/`_predict_viral`/`_refresh_character_panel`），但部分与 `_add_clip_to_timeline`/`_apply_action` 有数据面耦合，需要逐个确认调用方向后再定去留；`ai_agent_panel.py` 已有先例可复用同一 Mixin 或新建 `editor_ai_tools_panel.py` |
| **贴纸/画布/PiP（15 方法/376 行）** | 376 | 🟡 中 | 部分方法与预览合成路径共享 `_render_timeline_frame` 内部状态，抽出需保证不改变合成顺序 |
| **特效/滤镜/调色/转场（29 方法/624 行）** | 624 | 🟡 中 | 部分方法（`_apply_curves`/`_apply_chroma_key`）与 GL 预览路径耦合，需确认是否触碰 `canvas-transform` 冻结区 |
| **预览/渲染（51 方法/1966 行）** | 1966 | 🔴 高 | `_render_timeline_frame`（250 行，全文件最大单方法）是播放/scrub 共用合成核心，紧邻 `FROZEN:playback-av` 符号，未解冻禁止改动边界 |
| **时间线编辑（79 方法/2249 行）** | 2249 | 🔴 高 | 单选/多选/框选/吸附/跨轨等手感是过去 8 轮加固的重灾区（`08-frozen-zones.md` 之外但改动史最长），拆分收益需与回归测试成本对比后再定 |
| **事件回调/核心机制（97+32 方法/3102 行）** | 3102 | 🔴 高 | `__init__`/`_apply_action`/`_sync_kernel_timeline` 等是类状态机骨架，拆分即等于重新设计生命周期，明确排除在本方案范围外 |

## 四、建议执行顺序（分期，每期独立验收，不要求锁定终态）

### 第一期（低风险，建议下一步就做）— UI 构建

- 新建 `editor_ui_builder.py`（或按 tab 拆多个文件，参考已有 `editor_color_panel.py`/`editor_props_panel.py` 命名习惯），迁移 10 个 `_create_*`/`_make_*` 方法（792 行）。
- 验收标准：`compileall` 通过；`.venv312` 下 `editor_module` 实际 import 通过；手工打开编辑器全部 tab 渲染无回归（无自动化 UI 测试，需人工过一遍）；`frozen_zone_guard.py` 无 drift（这批方法不在冻结区）。
- 预期收益：宿主 -792 行（≈6%）。

### 第二期（中风险）— AI 工具方法

- 逐个确认 61 个方法里哪些是"纯按钮回调"（可直接搬，如 `_funclip_process`/`_autoclip_process`/`_predict_viral`），哪些对 `_clips`/`_apply_action` 有写操作（需要像 `ai_agent_panel.py` 一样保留在 Mixin 但整理到独立文件，或者改造成通过 `edit_commands.py` 一类公开接口调用，而不是直接闭包访问 `self._clips`）。
- 新建 `editor_ai_tools_panel.py`（区别于已有的对话式 `ai_agent_panel.py`），先移不碰数据面的方法，再视情况处理耦合方法。
- 验收标准：`app/tests/test_p0a_public_interfaces.py` 一类"公开接口而非私有方法"约束测试无回归；手工跑一遍 FunClip/AutoClip/五维打分。
- 预期收益：宿主再 -1000~1500 行（视耦合方法去留而定）。

### 第三期及以后（中高风险，需用户逐项确认再排期）

- 贴纸/画布/PiP、特效/滤镜/调色/转场：需先确认是否触碰 `canvas-transform`/`clip-transform` 冻结区，若是则走"解冻→改→`--update`→用户确认重锁"流程。
- 预览/渲染、时间线编辑、核心机制：**本方案不建议在近期排期**，理由见上表"🔴 高风险"——这三块合计约 7,300 行（占全文件 55%），是宿主"骨架"本身，真正的可维护性改善可能需要架构级重新设计（例如把 `_clips` 状态管理从 UI 类中抽成独立的 `TimelineController`），而非搬运方法体，这是比"拆文件"更大的决策，超出本次技术债务清理的范围，建议单独立项讨论。

## 五、明确不做

- 不在本轮或近期对 `_render_timeline_frame`/`_apply_action`/`__init__` 做任何搬动。
- 不追求"一次性拆完"，每期拆分后必须能独立跑通编辑器主路径（导入→剪辑→预览→导出）冒烟，不允许出现"拆了但装不回去"的中间态残留多个版本并存。
- 不新建第二套时间线状态或绕过 `EditorModule._clips` 单一真相源。

## 六、与既有拆分记录的关系

已完成的抽出（见 [`00-overview.md`](00-overview.md)/[`02-architecture.md`](02-architecture.md)）：`clip_transform` · `editor_export` · `editor_burn` · `editor_subtitle_panel` · `text_frame_map` · `edit_commands` · `filler_silence_detect` · `ai_agent_panel`（6 对话方法）· `editor_export_panel`（8 导出方法）。

本方案第一、二期完成后，应回写 `00-overview.md`"已抽出"列表与 `02-architecture.md` 的行数统计，并更新本文档「六」标注实际完成度。
