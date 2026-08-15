# 拾光剪影 — 项目长期记忆（核心事实）

> **结构化知识库（优先）**: [`docs/knowledge/INDEX.md`](../../docs/knowledge/INDEX.md)  
> 本文件保留北极星与偏好摘要；架构/活路径/已知问题以知识库 00–08 为准。  
> 摘要复核：**2026-08-13**

## 一、产品北极星闭环

7 阶段：精剪 → 人工改 → 文案 → 发布 → 数据采集 → 优化建议 → 选题。

| 状态 | 说明 |
|------|------|
| C1 | 发布真回执 ✅ |
| C2 | 爆款建议进账号运营 UI ✅ |
| C3 | 剪辑 workflow_hint ✅；短剧跳转走 `extensions` ✅ |
| 仍缺 | 选题自动导入时间线 / 一键粗剪写 `_clips` |

优先级：**先剪辑（稳→快→全→可维护），后 AI 闭环。**

地基：①清创 ✅ ②不卡（一轮+A2）✅ ③接线大半 ④拆上帝类进行中（宿主 ~10.8k） 顶层部分完成。

## 二、代码健康度（摘要）

- 真相源：`EditorModule._clips`；勿用 `AppState` / 孤儿 `ExportRenderer`
- 已抽：`clip_transform` · `editor_export` · `editor_burn` · `editor_subtitle_panel` · B0–B2 core
- 注册表：`extensions`（默认开）取代 `plugins`；`drama` 仅插件；**`account` 已迁插件**
- 音画纠偏：**~280ms**（冻结区）；勿压回 80ms
- 冻结区 7 个：见 `docs/knowledge/08-frozen-zones.md`

## 三、用户工作习惯与偏好

- 核电管工转 AIGC；简体中文；指令极简；偏好先看结论再展开
- 讲解要「小白模式」：比喻 + 表格
- 迭代：规划→确认「开始」→收汇总说「继续」
- 拒绝随机效果；前后端强绑定
- 情绪化表达不满时不回怼，专业耐心推进

## 四、最近落地（2026-08-12～13 · 跨 IDE 共用）

- 素材库仅本机；素材网站直达在**帮助**
- 账号运营：**插件** `app/plugins/account_ops_plugin/`，入口拓展中心（注册表已无 `account`）
- 画布默认 `shiguang-canvas`；3D 导演台可**单人/群像模板**；素模正面=+Z（五官+黄箭头）
- 姿势：点选人模 → 滑条 / 关节(J)；旧站位按钮不会生成多人，须用群像模板
- 构建产物：`vendor/shiguang-canvas/dist`（`Stage3D-2xKnAlH-.js`，含 `dummy13-v3`）
