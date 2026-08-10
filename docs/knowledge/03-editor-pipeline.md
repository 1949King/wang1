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

用户预览档：`EditorModule._user_preview_quality`（默认 `medium`=1/2）；UI 下拉 + Ctrl+1/2/3。  
播放/scrub 中强制 `low`（1/4），停止/松手后恢复**用户档**（非「播放前偶然值」）。  
降采样按片源**长边**限制分辨率，**保持宽高比**（禁止硬拉 16:9）。

**代理预览**：`proxy_media.ProxyMediaManager`；导入后异步生成；`_ensure_preview_source_open` → `_maybe_proxy_preview_path`；片段 `proxy_path` 仅预览，`path` 导出真相源。缓存目录：`editor.proxy_cache_dir` / `SHIGUANG_PROXY_CACHE`。

**Scrub 降载（A2+M2+A4）**：播放中 `playhead_moved` early-return；scrub 80ms 合并 + busy-drop；跨 clip `open_video(for_scrub=True)`；**scrub 走 `_render_timeline_frame` 合成**（转场/叠轨 WYSIWYG），拖动 stub 主音/BGM；跳过字幕/贴纸叠层；松手后恢复质量 + 音频 seek。未改冻结 `get_frame_at` / main-audio 块。

**工具栏指令**：`editor_ux_commands.dispatch_editor_action` 与快捷键共用。折叠轨 `sleep_media_workers`；拖片 `set_clip_interaction_active`。

## 字幕 / AI 体力活（B0–B2）

```
AI/导入字幕 → SubtitleManager / text_frame_map 帧绑定
  → 字幕面板删除 → edit_commands.ripple_delete（可撤销）
  → 「一键去水词」→ filler_silence_detect → 批量 B1
```

限制：默认主视频轨；去水词弹出勾选列表确认后执行（M5）；完成后可确认「重对齐字幕时间轴」（M3）；混合句内填充词默认不删。

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

**工程画幅 SSOT**：`EditorModule._sequence_format`（`app/core/sequence_format.py`）为比例/分辨率/fit 真相源。预览三路统一落到画幅后再显示：

- CPU：`_fit_qimage_to_sequence` → 字幕/贴纸/手柄 → `_present_preview_frame`（再 contain 进控件）
- GL：`_show_frame_gl` 先 letterbox 再上传纹理（滤镜预览与导出同画幅）
- 多轨：`_place_bgr_on_sequence_canvas` 底图 + 叠层归一化坐标用 sequence 宽高

默认漫剧 `9:16`·`1080×1920`·`contain`；旧工程无 `sequence`/`resolution` 时按首个视频片像素推断。

## 暂停/跳转

快进、后退、拖播放头、改倍速 → `_rebasing_playback_clock`，避免墙钟跳回旧轨迹。
