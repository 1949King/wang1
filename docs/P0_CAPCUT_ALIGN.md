# 拾光剪影 vs 剪映：差距与分期验收

**主线**：逼近剪映日常剪辑（时间线 + 预览 ≈ 成片）。不做商城/云草稿/模板社区。  
**约束**：`EditorModule._clips` 为真相源；活路径 `editor_module` + `timeline_widget` + `preview_manager`；最小入侵。

## 已对齐

| 能力 | 状态 |
|------|------|
| 导入 / 分割 / 复制粘贴 / 删除 | 可用 |
| 边缘 trim、时间线跨片播放 | 可用 |
| 调色 / 命名滤镜预览≈导出 | 基本可用 |
| `.timeline` + 120s autosave | 可用 |
| 字幕软预览、边缘 fade 近似 | 可用 |

## 分期与验收

### 第 0 期 — 诚实基线
- 本文档 + help/editor 与实现一致
- 空隙黑场/静音；播完复位 ▶

### 第 1 期 — 手感
- 波纹删除、按 `start_time` 定位、片缘吸附、trim/移动可撤销

### 第 2 期 — 所见即所得
- 字幕进工程 + 导出烧录、转场双帧近似、音量打通预览、autosave 恢复询问

### 第 3 期 — 多轨
- 跨轨落点、双层合成预览、BGM 轨、内核保留 `start_time`/`track`

### 第 4 期 — 深工具
- 片段 `speed`、opacity/volume/scale 关键帧、EffectManager 写入预览参数

## 明确不做

重写时间线架构 / GPU 流式 / 完整转场库 / ASS 动画 / HSL·LUT / Desktop 栈迁入。
