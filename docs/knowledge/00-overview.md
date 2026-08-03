# 00 — 产品概览与北极星

> 知识库复核：**2026-08-04**（对照工作区代码，非仅已提交 commit）

## 是什么

**拾光剪影**（AI 短剧编辑器）是基于 **PyQt6** 的桌面端短剧剪辑与发布工具，支持本地 AI（Ollama）与云端 API，模块化 LEGO UI。

## 北极星：7 阶段闭环

用户原始意图不是单点剪辑器，而是端到端闭环：

1. AI 精剪辑 → `editor_module`（已建；含 Agent 面板 / capability 管线）
2. 人工修改 → 编辑器 UI（已建）
3. AI 文案/话题/标题 → `copywriting`（已建，ADVANCED 默认关）
4. 发布到视频平台 → `account`（已建，EXPERIMENTAL 默认关；**C1 真回执**）
5. 获取播放/点赞/评论 → `account_analyzer`（已建，偏本地运营数据目录）
6. AI 优化建议 → `viral_optimization_engine`（**C2 已接账号运营 UI**；样例/本地数据，非平台真 API）
7. 下一步选题 → 短剧筛选插件（`drama_finder_plugin`+crawler）/ viral 基因分析

**关键判断**：阶段代码多已存在。  
**C1–C3 基础已接**（发布回执 / 爆款建议卡 / EventBus 跳转）。  
仍缺：**选题素材自动导入时间线**、**一键粗剪写回 `_clips`**。  
已知回归：**C3 短剧支路仍发 `target=plugins`，注册表已迁为 `extensions`，桌面跳转短剧可能失败**（剪辑 hint 支路正常）。

## 优先级（用户明确）

剪辑是地基；AI 是辅助。顺序锁定：

**先剪辑（稳 → 快 → 全 → 可维护），后 AI 闭环。**

地基四层（自下而上）：

| 层 | 目标 | 状态 |
|----|------|------|
| ①敢动 | 清死代码 / 吞异常改日志 | 已完成（2026-07-22） |
| ②不卡 | 预览/播放流畅（墙钟+顺序解码+音画同步） | **完成一轮**；A2 scrub 降载 ✅；滤镜长片仍可能卡 |
| ③完整 | 接线 core：波形/关键帧/LUT/速度/多轨 | **大半完成**；速度斜坡仍弱；叠轨 KF 连续化 ✅ |
| ④可维护 | 拆分 `editor_module` 上帝类 | **进行中**（A1✅）；宿主仍约 **10.8k 行** |
| 顶层 | AI 闭环接线 | **部分完成**（C1–C3）；自动导入/粗剪后置 |

已抽出（剪辑相关）：`clip_transform` · `editor_export` · `editor_burn` · `editor_subtitle_panel` · `text_frame_map` · `edit_commands` · `filler_silence_detect`。

## 体验评分快照（2026-07-25；结构未重评）

**日常短剧精剪约 7.5 / 10**。可当主力剪；离「丝滑像剪映」差可维护与边界稳定。目标约 **8.5+**（A3/A4）。

| 维度 | 分 |
|------|----|
| 导入/时间线基础 | 8.5 |
| 播放/预览流畅 | 7.5 |
| 所见即所得 | 7.5 |
| 多轨/BGM/PiP | 8 |
| 深工具 | 7.5 |
| 导出可靠度 | 8 |
| 可维护/稳定性感 | 5.5 |
| 对标剪映体感 | 6 |

**再涨分优先**：①继续拆 `editor_module`（AI/属性页）②修 C3 `plugins→extensions` ③A3 速度斜坡 / A4 手感。

冻结区见 [`08-frozen-zones.md`](08-frozen-zones.md)。

## 技术栈摘要

- UI: PyQt6
- 视频: FFmpeg / OpenCV / PyAV / MLT（双内核）
- AI: Ollama + 多云 Provider（DeepSeek 等）；编辑器内 Agent / Skill / MCP（拓展中心）
- 架构: `app/core` 业务 · `app/modules/lego` UI · EventBus 通信

## 入口

- 启动: `python -m app.main_qt6` 或根目录 bat
- 配置: `app/config.json`
- 默认 Provider 示例：`app/data/active_provider.json`（常见 `ollama`）
