# 03 — 剪辑活路径（Editor Pipeline）

> 复核：2026-08-04

## 真相源与活文件

- 真相源：`EditorModule._clips`
- **主路径**：`editor_module` + `timeline_widget` + `preview_manager` + `waveform_generator`
- **抽出副路径**（改功能优先跟这些，再回宿主薄包装）：
  - `clip_transform.py` — 归一化变换 / LUT atlas
  - `editor_export.py` — 主轨拼片、多轨 finalize、叠轨
  - `editor_burn.py` — 字幕 / 贴纸烧录
  - `editor_subtitle_panel.py` — 字幕侧栏
  - `text_frame_map.py` · `edit_commands.py` · `filler_silence_detect.py` — B0–B2

## 导入 → 时间线

```
_import_video / _load_video
  → AssetManager.import_asset（可选）
  → PreviewManager.open_video + QMediaPlayer（音频）
  → _add_clip_to_timeline
       → TimelineManager.add_clip（内核）
       → TimelineWidget.add_clip(video_track)
       → TimelineWidget.add_clip(audio_track)  # 联动音频 type=audio
```

找轨用 `TimelineWidget.find_track_index_by_type("audio"|"video")`，**禁止写死 track==1**。

## 波形

- `ClipWidget._is_audio_clip()`：`type==audio` / 扩展名 / 所在轨 type  
- 异步 `WaveformGenerator.generate`；失败返回 `None`，UI 画虚线中线（不随机假波形）  
- BGM / `_add_to_clips(kind=audio)` 必须真正 `add_clip` 到 audio 轨

## 时间线播放（冻结区 `playback-av`）

```
空格 → _start_timeline_playback
  → QElapsedTimer 墙钟 + anchor_t
  → QTimer 16ms；_timeline_render_busy 则丢帧
  → _render_timeline_frame(t)
       → PreviewManager.get_frame_at（顺序 grab/read，大跳才 seek）
       → 特效/叠层/字幕
       → QMediaPlayer 跟墙钟，漂移 >280ms 才 setPosition（勿压回 ~80ms）
       → _sync_bgm_audio（跳过联动音频片，避免双开）
```

播放中：`preview_quality=medium`，预览缩放 `FastTransformation`；停止后恢复原质量。  
降采样按片源**长边**限制分辨率，**保持宽高比**（禁止硬拉 16:9）。

**Scrub 降载（A2）**：播放中 `playhead_moved` early-return；scrub 50ms 合并 + `_preview_fast`；松手后恢复质量。

## 字幕 / AI 体力活（B0–B2）

```
AI/导入字幕 → SubtitleManager / text_frame_map 帧绑定
  → 字幕面板删除 → edit_commands.ripple_delete（可撤销）
  → 「一键去水词」→ filler_silence_detect → 批量 B1
```

限制：默认主视频轨；去水词后字幕列表未必自动重对齐时间轴；混合句内填充词默认不删。

## 导出

```
UI 导出
  → editor_export（拼片 / 多轨 / overlay）
  → editor_burn（字幕/贴纸）
  → EditorScheduler.export_video
       → PRO: core.render_manager
       → LITE: VideoProcessor.process
```

改导出优先动 `editor_export` / `editor_burn`，保持宿主薄委托。

## 暂停/跳转

快进、后退、拖播放头、改倍速 → `_rebasing_playback_clock`，避免墙钟跳回旧轨迹。
