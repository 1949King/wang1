# 12 — OTIO 概念 ↔ 拾光剪影 clip 字段

> **不换真相源**：运行时仍是 `EditorModule._clips` + `.timeline` JSON。  
> 本文只做语义对照，方便日后可选 `export_otio`（路线图 D4），以及 Agent/文档用语对齐。  
> 参考：[OpenTimelineIO](https://github.com/AcademySoftwareFoundation/OpenTimelineIO) · [`11-opentake-gap.md`](11-opentake-gap.md)

## 工程文件

| OTIO | 拾光剪影 |
|------|----------|
| `.otio` / Timeline | `.timeline`（`version` 当前 **1.2**） |
| schema version | `project_data["version"]` |
| global metadata | `sequence`（画幅/帧率）、`master_volume`、`export_time` |
| markers（完整） | 仅章节 markers 局部 EDL；**非** OTIO Marker 全集 |
| Stack / Nested sequence | **无**（扁平 clip 列表） |

## Clip 级字段对照

| OTIO 概念 | 本仓库 clip 字段 | 说明 |
|-----------|------------------|------|
| Clip.name | `name`（可缺省，常从 `path` 推） | Agent 上下文会补 `name` |
| ExternalReference.target_url | `path` | 本地绝对/相对路径 |
| source_range.start_time | `in_point`（秒） | 媒体入点 |
| source_range.duration | `duration` 或 `out_point - in_point` | 以 `duration` 为准更稳 |
| source_range end | `out_point` | 可能缺失，应用时回算 |
| timeline range start | `start_time` | 时间线上起点（秒） |
| Track kind / index | `track` | **禁止写死 `track==1`**，用 `find_track_index_by_type` |
| Transition | `transition` | 片段出点侧转场 dict |
| Effect / Filter | `effects` | 含滤镜等 |
| Speed | `speed`、`speed_ramp` | 预览/导出已部分接线 |
| Opacity / Transform | `opacity`、`scale`、`x`/`y`、`rotation` 等 | 画布变换 / 关键帧 |
| Keyframes | `keyframes` | UI 有；**Agent 未开放** `set_keyframes` |
| Volume | `volume` | 与 master_volume 分层 |
| Linked A/V | 导入时「联动音频片」约定 | 非 OTIO media_reference 组 |
| Metadata | 任意额外键 / 字幕绑定 | 自由扩展，导出时原样写入 clips 数组 |

## 时间线级（非单 clip）

| OTIO | 拾光剪影 |
|------|----------|
| Track list | 由各 clip 的 `track` 聚合；Agent 上下文提供 `tracks` / `track_count` |
| Gap | 无独立 Gap 对象；Agent 上下文计算 `gaps[]`（同轨空隙） |
| Freeze / Gap filler | 预览空隙黑场（实现侧） |
| Subtitles | 工程顶层 `subtitles` + `subtitle_styles`（非 OTIO 标准字幕轨） |
| Stickers | `stickers` |

## 刻意差距（短期不补）

1. 不引入 `opentimelineio` Python 依赖写回主路径  
2. 不做 Nested Composition / Multi-timeline  
3. 不做完整 Marker / LinearTimeWarp 对象模型  
4. Agent **不**直接读写 OTIO；只读写 `_clips` 与对话 action  

## 若将来做导出适配（备忘）

最小映射建议：`Clip` ← path + in/out + start_time + duration + track；`Transition` ← transition；其余进 `metadata`。验收：往返一轮后主轨时长与 clip 数一致即可，不追求 100% schema 保真。
