# 05 — 已知问题与近期修复

## 已修复（2026-07-25 AI 加载/提示）

| 项 | 说明 |
|----|------|
| AI 特效插件加载 | `PluginManager` 兼容 `plugin_info`；记录 `_load_errors`；特效子模块懒加载；插件中心状态条 +「打开面板」失败明文 |
| LLMClipper | `last_error`；空字幕/空 JSON/无模型不再静默切前 15 秒；编辑器 AI 页提示词 + LLM 按钮 + 主线程弹窗 |
| Ollama 诊断 | `format_diagnose_report` / `diagnose_user_message`；模型卡状态带 error；编辑器 AI 页「重新诊断/详情」 |

## 已修复（2026-07-25 AI 诚实降预期）

| 项 | 说明 |
|----|------|
| 文案静默模板 | 选云端模型失败时弹窗确认，不再假装 AI 成功；「本地模板（非 AI）」 |
| TTS 适配器 | `VoiceGenerator` 别名 + `generate_audio` |
| 插帧命名 | UI/日志改为「线性补帧」 |
| Whisper 提示 | `unavailable_reason()` + setup_deps 路径 |
| 模块说明 | copywriting / ai_clip_flow / models 描述标明依赖与半通 |

## 已修复（2026-07-25 续）

### 预览比例被拉成 16:9

| 根因 | 修复 |
|------|------|
| `preview_quality=medium/low` 硬编码目标 960×540 / 640×360 | `_get_target_size()` 按长边降采样，保持片源宽高比 |
| 空隙黑场写死 `QImage(1280,720)` | 改用当前片源宽高 |
| QLabel 可能拉伸 | `setScaledContents(False)` |

涉及：`preview_manager.py` · `editor_module.py`  
验收：`test_preview_aspect.py`

### 恢复工程后音频轨无波形

| 根因 | 修复 |
|------|------|
| 旧 `autosave/latest.timeline` 只存视频片、无联动音频 | `import_project` → `_ensure_linked_audio_clips()` 自动补 audio 轨 |
| 相对路径导致 `exists` 失败 | ClipWidget `_resolve_clip_media_path()` |

涉及：`editor_module.py` · `timeline_widget.py`  
验收：`test_linked_audio_restore.py`

## 已修复（2026-07-25）

### 音频轨无波形

| 根因 | 修复 |
|------|------|
| 绘制写死 `track==1` | `_is_audio_clip()` 按轨 type / type / 扩展名 |
| 生成失败 → 全 0 peaks ≈ 看不见 | `WaveformGenerator` 失败返回 `None`；UI 虚线中线 |
| BGM `_add_to_clips` 未上时间线 | 真正 `add_clip` 到 audio 轨 |
| paintEvent 反复起线程 + 随机假波形 | 防重入；去掉随机占位 |

涉及：`timeline_widget.py` · `waveform_generator.py` · `editor_module.py`  
验收脚本：`test_waveform_fix.py`

### 播放卡顿 / 音画不同步

| 根因 | 修复 |
|------|------|
| playhead `+=0.033` 软件时钟 | `QElapsedTimer` 墙钟 + 忙则丢帧 |
| 每帧 `CAP_PROP_POS_FRAMES` seek | 顺序 grab/read，落后≤24 帧 grab 追赶 |
| 音画双时钟，350ms 才纠偏 | 阈值 80ms；跳过联动音频双开 |
| Smooth 缩放 + 高分辨率预览 | 播放中 medium + FastTransformation |

涉及：`editor_module.py` · `preview_manager.py`

### 导入/时间线（较早）

- `_ensure_preview_manager()` 后再 `open_video`
- ClipWidget `elidedText` 替代错误的 `setEllipsize`
- 详见 `debug-video-import-timeline.md`

## 已完善（2026-07-25 手感/接线）

| 项 | 说明 |
|----|------|
| 修复 `move_clip` | 此前误粘在 `add_keyframe_at_playhead` 后成为死代码 |
| 吸附默认开 | 按钮与 `_snap_enabled` 同步；trim 片头/片尾也可吸附 |
| 波纹删除 | 删视频连带删联动音频；一次撤销恢复整组 |
| 变速 | 「应用变速」写片段 speed（可撤销）；复杂预设走导出 |
| LUT | 调色页应用/即时预览写入 `effects.color_params.lut` |
| 关键帧入口 | 时间线工具条「◆ 关键帧」 |

## 已完善（2026-07-25 第 2 期所见即所得 · 第一刀）

| 项 | 说明 |
|----|------|
| 字幕进工程 | `subtitle_styles` 存取对齐 `SubtitleManager`；导入刷新列表；字幕编辑标 dirty |
| 字幕-only autosave | 无片段但有字幕也会写入 `autosave/latest.timeline` |
| 音量打通预览 | 音频页「片段/总控」滑条；轨音量 × 片段 × 总控；导出烘焙含轨音量 |
| 转场 UI | 类型/时长/曲线控件真正存引用并写入片段 `transition` |
| 字幕烧录样式 | ASS 导出（字体/色/描边/底/位置）；预览按 x,y 中心锚点；失败回退 SRT |
| 多轨导出 | 主轨按 start_time 黑场空隙；上层视频画中画叠轨；独立音频 adelay+amix；跳过联动内嵌音 |
| 关键帧深工具 | 属性选 opacity/volume/scale；删关键帧；缓动走 `keyframe_animation`；可撤销；EffectManager getter 修复 |
| 滤镜预览体验 | 滑杆 60ms 节流；同帧只改 GL uniform；拖 scrub 降分辨率；播放跳过锐化/模糊/暗角；LUT 半分辨率快路径 |
| 多轨导出 UX | 叠轨/混音进度 toast；失败明文提示；PiP 读专业页 X/Y/大小 |

## 已完善（2026-07-25 右侧工具栏接线）

| 项 | 说明 |
|----|------|
| 调色页 | 基础/HSL 滑杆存 `_color_sliders`；拖动即时预览；应用/重置写入片段 `effects.color_params`（可撤销） |
| 属性页 | 不透明度 / 缩放 / 位移 / 旋转 live 写片段；选中时同步滑杆 |
| 导出页 | 平台/分辨率/帧率/码率等真实 `QComboBox` 引用；硬件加速可见；项目信息刷新；`_export_video` 安全读取控件 |

## 已修复（2026-07-25 导出链路）

| 根因 | 修复 |
|------|------|
| `ProfessionalVideoEngine` 打印 `✓` 在 GBK 控制台抛错 → 「FFmpeg CLI 不可用」 | 安全打印 / ASCII 标记 |
| 专业渲染 `-hwaccel_output_format cuda` + CPU `scale` → Function not implemented | 仅 `-hwaccel cuda`，帧回系统内存再滤镜 |
| UI「硬件加速」未进最终转码 | `apply_export_settings` 优先 NVENC/QSV/AMF，失败软编 |
| `H.265` 未映射 / 缺编码器直接失败 | 映射 `libx265`；失败回退 `libx264` |
| `ffprobe`/`-encoders` 用系统默认编码导致 probe 空 | `encoding=utf-8, errors=ignore` |
| 导出源片取 `_clips[0]` 可能是音频 | 优先取视频轨路径 |

涉及：`professional_video_engine.py` · `video_processor.py` · `render_manager.py` · `editor_module.py`

## 已修复（2026-07-25 贴纸）

| 根因 | 修复 |
|------|------|
| 仅离线 FFmpeg 烘焙，预览无叠加 | 点击即上画布；`_overlay_stickers_on_qimage` 进预览/GL |
| 后台线程 `QMessageBox` 易卡死 | 去掉线程弹窗；滑杆 live 写回选中贴纸 |
| 导出不含贴纸 | `_burn_stickers_if_any` 在字幕烧录后执行 |
| 工程不存贴纸 | `export_project` / `import_project` 读写 `stickers` |

## 已修复（2026-07-25 字幕识别）

| 根因 | 修复 |
|------|------|
| `from core.subtitle_generator` 导入失败 → 假字幕「字幕片段 N」 | 改走 `app.core.ai.whisper_asr`；禁用占位假文案 |
| Whisper 未安装 | 需 `pip install faster-whisper`；未安装时明确提示 |
| TypoCorrector 乱换「的/得/在/再」 | 默认纠错表清空；`correct_typos=False` |
| 未按片段 in/out 截取音频 | 提取当前片音轨并按 `start_time` 对齐时间轴 |
| HuggingFace 超时下不了模型 | `whisper_asr` 默认 `HF_ENDPOINT=https://hf-mirror.com` |

## 环境补齐（2026-07-25）

一键脚本：`scripts/setup_deps.ps1`  
已装：CUDA `torch 2.6.0+cu124`（RTX 4060）、`faster-whisper`、`transformers`、`easyocr`、`librosa`；Whisper **tiny/base** 已缓存。  
注意：勿用默认 PyPI 装 CPU 版 torch 覆盖 CUDA wheel。

## 已完善（2026-07-28 A2 滤镜/scrub 预览降载）

| 项 | 说明 |
|----|------|
| 播放二次解码 | `playhead_moved` 在播放中 early-return，避免 `_render_timeline_frame` 后再走一遍 scrub 预览 |
| scrub 合并 | 50ms 定时器合并 playhead 事件，松手 220ms 后恢复高质量 + 一次性音频 seek |
| scrub fast | `_lighten_effects_for_playback` 在 `_preview_scrubbing` 时也设 `_preview_fast` |
| CPU 滤镜 | `PreviewManager._apply_effects_sync`：fast 跳过命名滤镜与 hue/gamma/exposure |
| 质量恢复 bug | `_begin_preview_scrub` 修正读 `preview_quality`（非 `_preview_quality`） |
| 可观测 | scrub 结束日志 `scrub 预览合并 N 次请求（降载）` |

涉及：`editor_module.py` · `preview_manager.py`  
验收：`_verify/test_scrub_filter_smoke.py`

## 已完善（2026-07-28 轨 C1 发布真回执）

| 项 | 说明 |
|----|------|
| 快速发布死按钮 | `account_ops_module._create_publish_card` 中 `pub_btn` 接线 `_quick_publish` |
| 矩阵/快速假成功 | `_execute_publish` 统一回执：`failed` / `local_queue` / `local_export` / `upload_attempted`；禁止弹「已提交到平台」 |
| publish_log | 写入 `status` + `receipt_kind` + `message`（及 `export_path`）；不再默认 `published` |
| PlatformIntegrator | 有 Playwright 上传器时标 `upload_attempted` 并提示后台核对；否则标本地导出路径 |

涉及：`account_ops_module.py`  
验收：账号运营 → 快速发布/矩阵发布，无视频或标题应失败可见；无 API 时文案含「本地队列/需手动上传」。

## 已完善（2026-07-28 轨 C2 爆款优化进 UI）

| 项 | 说明 |
|----|------|
| 入口 | 账号运营各平台面板 →「🔥 爆款优化建议」（在 AI 运营建议下方） |
| 引擎接线 | `get_account_analyzer().analyze_data()` → `_build_video_features_from_analysis` → `ViralOptimizationEngine.predict_performance` + `generate_optimization_suggestions` |
| 无数据 | 状态条提示 `app/运营数据` 为空；「样例分析」明确标注非真实数据 |
| 引擎失败 | 显示「爆款优化引擎加载失败」，不弹假成功 |
| C1 保留 | 快速/矩阵发布真回执未回退 |

涉及：`account_ops_module.py`  
手测：启用账号运营 → 任平台 →「从运营数据生成」（无数据应警告）→「样例分析」应出预测与建议。

## 已完善（2026-07-28 轨 C3 闭环跳转）

| 项 | 说明 |
|----|------|
| 入口 | 账号运营各平台 →「🔥 爆款优化建议」生成后 →「🎭 去短剧筛选选题」/「✂️ 去剪辑（下一轮粗剪）」 |
| 跳转机制 | `EventType.MODULE_ACTIVATED` + `target`/`action`/`workflow_hint`；`MainWindow._flush_pending_module_action` 交付子页 |
| 粗剪提示 | `target=editor` + `workflow_hint` → 剪辑状态栏 + 非模态信息框展示优化项摘要 ✅ |
| 短剧筛选 | 原设计 `target=plugins` + `action=drama_finder` |
| C2 保留 | 爆款引擎/analyzer 接线未回退 |

涉及：`account_ops_module.py` · `main_window.py` · `editor_module.py`（`_on_workflow_hint_received`）

### 开放缺陷（2026-08-04 复核）— C3 短剧支路断裂

| 根因 | 说明 |
|------|------|
| 注册表迁移 | `plugins` 已迁为 **`extensions`**；`is_enabled("plugins")` 恒为假 |
| 跳转未改 | `account_ops_module` 仍发 `target=plugins`；`main_window` 仍按 `module_id == "plugins"` 处理 |
| 宿主漂移 | 短剧常驻标签在未注册的 `plugins_module`；拓展中心为弹窗 `_open_drama_finder` |

**修复方向**：统一 `target=extensions` + 拓展中心打开短剧；或恢复兼容别名。修前勿宣称 C3 全通。

## 仍开放 / 待做

- GPU 滤镜：命名滤镜可实时；LUT 可走 **GPU 2D 图集**（失败自动回退 CPU）
- 导出 nvenc 正常，预览加速 ≠ 成片加速（预期）
- 速度斜坡曲线仍走「导出成片」；固定倍率已写入片段 `speed` ✅
- 叠轨带 transform 关键帧：优先 **连续 overlay 表达式**；失败回退分段静态
- `editor_module.py` 仍大（约 **10.8k**）；已抽 [`clip_transform`](app/modules/lego/clip_transform.py) · [`editor_export`](app/modules/lego/editor_export.py) · [`editor_burn`](app/modules/lego/editor_burn.py) · [`editor_subtitle_panel`](app/modules/lego/editor_subtitle_panel.py) + B0–B2 core
- 7 阶段闭环：**C1/C2 ✅**；**C3 半通**（见上）；自动导入选题 / 一键粗剪仍缺
- `extensions` 实验级却默认开（与「首屏只 CORE」不完全一致）
- 冻结区见 [`08-frozen-zones.md`](08-frozen-zones.md)

## 已完善（2026-07-25 所见即所得·导出烘焙）

| 项 | 说明 |
|----|------|
| 缩放/不透明度 | `bake_clip_transform` 写入主轨成片（半透明叠黑底） |
| 不透明度关键帧 | geq 动画 alpha |
| 音量关键帧 | `volume=expr:eval=frame` |
| scale 关键帧 | 分段静态 bake + concat（阶跃近似，非连续 zoompan） |
| 叠轨 | 可读属性页 scale/position；PiP 滑条仍优先 |
| exposure | 映射进 `eq` brightness |

## 已完善（2026-07-25 剪辑体验短冲刺）

| 项 | 说明 |
|----|------|
| 归一化变换 | `normalize_clip_transform` / `apply_normalized_transform`；属性页与 PiP 滑条读写同一套 `pip_*` + `transform` |
| 预览叠层 | `_render_timeline_frame` 按 x/y/scale 偏移粘贴（多轨跳过单层 GL） |
| 导出叠轨 | `overlay_timeline_videos` 与预览同坐标；scale 上限 2.0；去掉 1920×1080 硬编码映射 |
| scale 关键帧导出 | 去掉中点近似，走分段烘焙 |
| UX | 导出分阶段文案；autosave 恢复带修改时间；AI 字幕失败摘要更明确 |

## 已完善（2026-07-25 变换深工具）

| 项 | 说明 |
|----|------|
| 旋转/锚点 | 属性页接线；预览 `composite_overlay_bgr`；导出 bake `rotate=` + 叠轨 rotate |
| position/rotation 关键帧 | 添加关键帧 UI + `_interpolate_clip_keyframes`；预览吃 `_tf_x/y/rot` |
| 画布拖拽 | `_preview_label` eventFilter 拖动改归一化 x/y |
| GPU LUT | `GLFilterWidget.supports_lut` + 2D 图集纹理；失败回退 CPU |
| 拆分 | 新增 [`clip_transform.py`](app/modules/lego/clip_transform.py)；`video_processor` 再导出 |

## 仍开放 / 待做

- `editor_module` 继续拆 UI/AI 面板（可维护性；导出/字幕已抽）
- 7 阶段闭环：修 C3 `plugins→extensions`；自动导入选题 / 一键粗剪仍缺

## 已完善（2026-07-25 叠轨 KF 连续化）

| 项 | 说明 |
|----|------|
| 导出 | `overlay_timeline_videos` 吃 `_x/_y/_sc/_rot_kfs`，scale+overlay `eval=frame` |
| 预拆段 | 默认不再拆段；失败才 `_force_segment_overlay` |
| 冒烟 | `_verify/test_overlay_kf_smoke.py` |

## 非剪辑模块审计（2026-07-25）

来源：全库盘点。  
原则：**先诚实降预期 / 修阶段 4，再谈闭环**；不优先堆未接线引擎。

| 问题 | 严重度 | 说明 |
|------|--------|------|
| 账号「矩阵发布」假成功 | — | **已修（2026-07-28 C1）**：不再写 `status=published` 假回执；须选视频+标题；弹窗区分 `local_queue` / `local_export` / `upload_attempted` / `failed` |
| 账号「快速发布」死按钮 | — | **已修（2026-07-28 C1）**：`pub_btn.clicked.connect` → `_quick_publish`；补视频浏览与诚实说明 |
| 在线素材假目录 | 高 | `online_materials._generate_materials` 随机造卡；下载 MOCK |
| 短剧筛选入口 | — | **已收口（同日）**：删注册表 drama 模块；仅插件；爬虫打包进 `drama_finder_plugin/crawler/` |
| 短剧筛选无打开入口 | — | **已修（同日）**：详情页「打开界面」→ `plugin.run()` 弹 `DramaFinderWidget` |
| 打开插件 `'Plugin' has no _widget` | — | **已修**：PluginManager 只实例化不 `initialize`；`getattr(_initialized, True)` 误跳过；短剧插件补 `__init__`/`_initialized`，打开前 `_ensure_plugin_initialized` |
| 短剧筛选无可视化预览 | — | **已修**：`drama_ui.py` 封面卡片墙+右侧详情预览；插件中心常驻「🎭 短剧筛选」标签 |
| 插件商店虚构上架 | — | **已修**：`OFFICIAL_ITEMS`/`items.json` 仅保留 `app/plugins` 真实 17 项；剔除智能剪辑/字幕生成/批量导出Pro 等假条目；残缺转场补 description |
| AI特效面板 AttributeError | — | **已修**：`btn_glamour.setToolTip` 笔误 |
| 模块切换卡顿/抢跳 | — | **已修**：禁用后台 `_on_module_selected` 预加载（曾误激活剪辑等重模块） |
| 播放声音卡顿 | 中 | **缓解**：主音/BGM 纠偏阈值 80ms→280ms，减少每帧硬 seek |
| 关程序后仍出声 | — | **已修（同日）**：`EditorModule.cleanup` + `MainWindow._stop_all_media_on_exit` 关窗前 stop/静音/清 source（Windows WMF 幽灵音） |
| 首页快捷跳未启用模块 | 中 | `MODULE_ACTIVATED` 时导航无按钮 → 静默无反应（短剧快捷已改为插件中心） |
| 文案无模型静默模板 | — | **已修（同日）**：云端失败弹窗征得同意再模板；模型项改名「本地模板（非 AI）」；批量/AB 带回退 reason |
| extensions 实验却默认开 | 低 | 原 plugins 已迁 id=`extensions`；仍 default_enabled=True，与「首屏只 CORE」不完全一致 |
| viral / account_analyzer | 中 | **C2 已接线**：账号运营「爆款优化建议」；仍不吃平台真播放 API |
| C3 短剧跳转 | 高 | **2026-08 开放**：仍 `target=plugins`，registry 无此 id（见上文「C3 短剧支路断裂」） |
| TTS 类名不一致 | — | **已修**：`VoiceGenerator` 别名 + `generate_audio`；AIEngine TTS 适配器可初始化 |
| 「AI 插帧」名不副实 | — | **已修**：文案改为线性补帧；默认仍关闭 |

相对可信：settings · help · performance（监控）· copywriting（配好 Provider；失败不再静默假 AI）· materials **本地**导入 · 短剧筛选（插件中心启用后）。

## 短剧筛选爬虫可用性（2026-07-25）

引擎位置：`app/plugins/drama_finder_plugin/crawler/`  
适配层仍在：`modules/lego/*_playwright_api.py` · `stealth_browser.py` · `tiktokhub_douyin_api.py`

| 层 | 完整度 | 本机可用性 |
|----|--------|------------|
| 数据结构 / 评分 / 推荐 / 偏好持久化 | 高 | ✅ |
| 平台壳 15 个 | 列表齐全 | 多数 `api_class=None`（未接入） |
| Douyin/Kuaishou/Bilibili **内置 API 类** | 有代码 | ❌ 实为 `_generate_data` 随机假数据 |
| Playwright 抖音/B站 | 代码在 lego | ❌ 当前 venv **未装 playwright** → 不注入 |
| TikHub | 代码在 | ❌ 未配 `TIKHUB_API_TOKEN` |
| DramaWebScraper HTTP 源 | 有骨架 | ❌ `api.example.com` 且 `enabled=False` |
| `app/data/drama_data.json` 静态缓存 | 有文件 | ✅ 迁插件后路径曾指错 `plugins/data`，**已修回 app/data** |
| 内置标题池兜底 | 有 | ✅ UI 永不空，但非真实榜单 |

**结论**：代码链路完整；**默认优先静态缓存**（`app/data/drama_data.json`），不再被内置随机假 API 抢先。真榜单仍需 Playwright/TikHub。  
完善（2026-07-25）：跳过 fake API → Web/静态 → 随机兜底；UI 标注来源；验收 `test_drama_crawler_static.py`。

## 已完善（2026-07-25 连续变换 bake）

| 项 | 说明 |
|----|------|
| 主轨 KF | `bake_clip_transform` 优先 `_bake_clip_transform_continuous`（scale eval=frame + rotate + overlay eval=frame） |
| 回退 | 表达式失败时仍走分段静态 + concat |
| 位置 | 不用含 `t` 的 pad（不稳定），改 overlay 归一化坐标 |

## 已完善（2026-07-25 画布缩放把手）

| 项 | 说明 |
|----|------|
| 边角缩放 | 命中片段包围盒四角/边框 → 拖拽改 scale |
| Ctrl+滚轮 | 预览区缩放当前选中片段 |
| 变换框 | 暂停时绘制蓝框+四角把手；Alt 仍为旋转 |
| 坐标 | 鼠标映射扣除信箱黑边，与 KeepAspectRatio 预览对齐 |

## 已完善（2026-07-25 position 关键帧 + 旋转把手）

| 项 | 说明 |
|----|------|
| transform 分段 | `_build_transform_segments` 同时吃 scale/x/y/rotation 关键帧（叠轨/回退仍用） |
| 主轨导出 | 连续表达式 bake（见上）；失败回退分段 |
| 叠轨导出 | 有 transform 关键帧时拆成多段静态 overlay（避免透明通道丢失） |
| 画布旋转 | Alt+拖 或 四角附近拖 → 旋转；中心区拖 → 平移 |

## 已完善（2026-07-28 B0 文本↔帧绑定）

| 项 | 说明 |
|----|------|
| 映射层 | `app/core/text_frame_map.py`：Whisper/字幕条目 → timeline & source 的 in/out 秒 + 半开帧区间 |
| 边界策略 | 默认 `SAFE_WORD`：起点 `floor(t*fps)`、终点 `ceil(t*fps)`（`[frame_in, frame_out)`），极短段至少 1 帧 |
| 接线点 | `SubtitleManager.compute_frame_bindings(clip, fps)`；编辑器 AI 字幕写入处注释指向 B1 |
| 验收 | `pytest app/tests/test_text_frame_map.py -m unit` |

## 已完善（2026-07-28 B1 薄指令执行器）

| 项 | 说明 |
|----|------|
| 执行层 | `app/core/edit_commands.py`：`split_clip_at_timeline` / `ripple_delete_timeline_range` / `ripple_delete_from_binding` |
| 撤销 | 返回 `compound` steps，与 `EditorModule._apply_action` 对接；Ctrl+Z 可回滚整段 split+delete |
| UI 入口 | 字幕面板「🗑 删除」：B0 帧绑定 → 主视频轨波纹删除 → 再删字幕条目 |
| 限制 | 仅主视频轨；联动内嵌音频轨不会随 mid-clip 切分同步（整片删除仍走原逻辑） |
| 验收 | `pytest app/tests/test_edit_commands.py -m unit` |

## 已完善（2026-07-28 B2 去水词/长静音）

| 项 | 说明 |
|----|------|
| 检测层 | `app/core/filler_silence_detect.py`：纯填充词（呃/嗯/啊等）+ 句间长静音（默认 ≥0.4s，可配置） |
| 映射 | 经 B0 `bind_entries_to_clip` → timeline `[t_in,t_out)`；批量删除从右向左复用 B1 |
| UI 入口 | 字幕面板「✂ 一键去水词」；需先有 AI/导入字幕；短剧密集对白仅删纯填充词且二次确认 |
| 限制 | 句级 ASR，混合句内填充词默认不删；批量删后字幕列表未自动时间轴同步（可重跑 AI 字幕）；仅主视频轨 |
| 验收 | `pytest app/tests/test_filler_silence_detect.py -m unit` |

## 已完善（2026-07-28 A1 拆 editor_module · 字幕面板）

| 项 | 说明 |
|----|------|
| 新模块 | `app/modules/lego/editor_subtitle_panel.py`：文字侧栏字幕 UI + CRUD + AI 生成 + 去水词 |
| 接线 | `EditorModule._make_text_tab` 委托 `build_subtitle_panel_section`；原 `_refresh_subtitle_list` 等方法保留薄包装 |
| 冻结区 | 未改 playback/exit-media/canvas-transform 等锁定符号；`frozen_zone_guard.py` 通过 |
| 验收 | 模块可 import；`test_edit_commands` / `test_filler_silence_detect` 无回归 |

## 调试备忘

- 临时 debug HTTP（`127.0.0.1:7777`）若仍残留，修完后应移除
- 崩溃日志：`app/_crash_report.log`
