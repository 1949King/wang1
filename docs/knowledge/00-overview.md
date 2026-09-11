# 00 — 产品概览与北极星

> 知识库复核:**2026-08-19**(产品收口：剪辑 + AI 画布 + Agent + 数字人)

## 是什么

**拾光剪影**是 PyQt6 桌面端**短剧精剪 + AI 导演台**。活路径只有：**剪辑模块**与 **AI 画布**（含智能体与画布数字人）。运营/筛选等已卸为接口壳，不再作为迭代主题。

## 北极星（当前）

竖切可重复：**导演台（含数字人）→ 分镜图 → 入轨精剪**。智能体只做确认后的遥控器，不默认一键成片。

四条专注轨：

1. **剪辑体验** — 时间线手感、预览/播放、建议勾选后写 `_clips`
2. **画布体验** — `vendor/shiguang-canvas` 节点、落盘、生图/生视频诚实失败
3. **AI 剪辑与智能体** — FunClip/AutoClip/无损 trim/节拍切开；Agent 白名单 + 勾选写入；**剪辑↔画布 round-trip**
4. **画布数字人** — 形象 + 台词 + TTS；口型驱动成片有模型再接，无模型不假成功

旧「7 阶段发布闭环」阶段 4–7 仅留接口，见下。

用户原始意图不是单点剪辑器,而是端到端闭环:

1. AI 精剪辑 → `editor_module`(已建;含 Agent 面板 / capability 管线)
2. 人工修改 → 编辑器 UI(已建)
3. AI 文案/话题/标题 → `copywriting`(已建,ADVANCED 默认关)
4. 发布到视频平台 → `account` **插件壳**(`account_ops_plugin`；功能已卸；`account.*` 诚实失败)
5. 获取播放/点赞/评论 → 接口保留，采集能力已卸
6. AI 优化建议 → `viral_optimization_engine` 文件仍在；账号运营 UI 不再调用
7. 下一步选题 → 短剧筛选插件壳(`drama_finder_plugin`；无爬虫/榜单；`drama_send_to_editor` 可选手成本地成片)

**关键判断**:阶段 1–3 仍是活路径.  
**阶段 4–7 仅留接口**(2026-08-19 卸空)：商店条目、EventBus `action=account_ops` / `action=drama_finder`、能力名仍注册.  
C3 跳转与 C1 发布回执随账号运营 UI 卸空而不再提供. M6 回流签名保留.

## 优先级(用户明确)

剪辑是地基;AI 是辅助.顺序锁定:

**先剪辑体验,再画布体验,再 AI 剪辑/智能体,再数字人口型成片.**

地基四层(自下而上):

| 层 | 目标 | 状态 |
|----|------|------|
| ①敢动 | 清死代码 / 吞异常改日志 | 已完成(2026-07-22) |
| ②不卡 | 预览/播放流畅(墙钟+顺序解码+音画同步) | **完成一轮**;A2 scrub 降载 ✅;滤镜长片仍可能卡 |
| ③完整 | 接线 core:波形/关键帧/LUT/速度/多轨 | **大半完成**;速度斜坡仍弱;叠轨 KF 连续化 ✅ |
| ④可维护 | 拆分 `editor_module` 上帝类 | **进行中**(A1✅);宿主实测 **13,321 行**(2026-08-11 AST 复核,此前"10.8k"已过时);量化分析+分期方案见 [`10-editor-module-split-plan.md`](10-editor-module-split-plan.md) |
| 顶层 | AI 闭环接线 | 阶段 4–7 **仅接口壳**（2026-08-19） |

已抽出(剪辑相关):`clip_transform` · `editor_export` · `editor_burn` · `editor_subtitle_panel` · `text_frame_map` · `edit_commands` · `filler_silence_detect`.

## 体验评分快照(2026-08-11 重评 · A4 第一刀后)

**日常短剧精剪约 8.0 / 10**(7 月快照 7.5 → 手感/WYSIWYG/代理降载后上调).可当主力剪;离「丝滑像剪映」仍差可维护与边界稳定.目标约 **8.5+**.

| 维度 | 分 |
|------|----|
| 导入/时间线基础 | 8.7 |
| 播放/预览流畅 | 8.0 |
| 所见即所得 | 8.0 |
| 多轨/BGM/PiP | 8.0 |
| 深工具 | 7.7 |
| 导出可靠度 | 8.0 |
| 可维护/稳定性感 | 6.0 |
| 对标剪映体感 | 6.5 |

**本轮优化(A4)**:代理优先胶片条;导入减负;点选不跳播放头;进度条接线;**scrub 与播放同合成路径(转场/叠轨)**.  
**再涨分优先**:①继续拆 `editor_module`（须点头）②少而真转场 ③长对白样片手测（冒烟已入库 `test_long_dialogue_smoke.py`）。


**季度主题(2026-08 起收口)**:剪辑体验 + 画布体验 + Agent/AI 剪辑 + 画布数字人。发布/选题闭环不再排期。

冻结区见 [`08-frozen-zones.md`](08-frozen-zones.md).

## 技术栈摘要

- UI: PyQt6
- 视频: FFmpeg / OpenCV / PyAV / MLT(双内核)
- AI: Ollama + 多云 Provider(DeepSeek 等);编辑器内 Agent / Skill / MCP(拓展中心)
- 架构: `app/core` 业务 · `app/modules/lego` UI · EventBus 通信

## 入口

- 启动: `python -m app.main_qt6` 或根目录 bat
- 配置: `app/config.json`
- 默认 Provider 示例:`app/data/active_provider.json`(常见 `ollama`)
