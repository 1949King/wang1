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
- **进度（2026-07-25）**：字幕 styles 存取、dirty/autosave、音量 UI→预览/导出、转场控件接线、ASS 样式烧录（位置/字体/色/描边/底）与预览对齐；ASS 入出场动画不做

### 第 3 期 — 多轨
- 跨轨落点、双层合成预览、BGM 轨、内核保留 `start_time`/`track`
- **进度（2026-07-25）**：上层轨归一化叠轨预览≈导出；预览画布拖拽改位置；旋转/锚点进合成

### 第 4 期 — 深工具
- 片段 `speed`、opacity/volume/scale/x/y/rotation 关键帧、EffectManager 写入预览参数
- **进度（2026-07-25）**：关键帧 UI + 预览插值；导出优先连续表达式 bake（失败回退分段）；画布 Alt/角落拖旋转 + 边角缩放；`clip_transform.py`；GPU LUT 2D 图集

## 明确不做

重写时间线架构 / GPU 流式 / 完整转场库 / ASS 动画 / Desktop 栈迁入。  
不做剪映素材商店包 / OFX / AE 预设兼容。

**自研路径（已接）**：`.cube`/`.3dl` 导入 UI + `lut_loader`；转场走 `ITransitionPlugin` / `app/plugins/transition_*.py`（非商店格式）。
