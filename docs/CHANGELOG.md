# 拾光剪影 — 变更日志

## V4.9.2 (2026-07-13) — 贴纸预览与滤镜播放优化

### 🐞 修复

- **贴纸渲染后视频不更新** (`editor_module.py`): 贴纸渲染成功后仅调用 `_add_to_clips` 将结果加入素材列表，但未加载到 `QMediaPlayer`，用户看不到任何变化。现在渲染完成后自动将结果视频加载到播放器并切回 `QMediaPlayer` 预览，用户立即看到贴纸效果。
- **切换滤镜后播放卡顿** (`editor_module.py`): 滤镜激活时 `_refresh_preview_with_effects` 将预览切到 `PreviewManager`（OpenCV CPU 逐帧解码 + numpy 效果），1080p/720p 视频无法实时渲染导致严重卡顿。改为**分策略预览**：暂停/拖拽时用 `PreviewManager` 精确渲染滤镜效果，播放时切回 `QMediaPlayer` 硬件加速流畅播放。`_play_pause`、`_rewind`、`_fast_forward`、进度条拖拽释放均已联动此策略。

## V4.9.1 (2026-07-12) — 剪辑导出可用性修复（续）

### 🐞 修复（致命后端崩溃）

- **subprocess 参数拼写错误（致命）** (`video_processor.py`): 模块内 12 处 `subprocess.run(...)` 误用 `creation_flags=`（带下划线），而 `subprocess.Popen` 仅接受 `creationflags=`（无下划线）。该错误导致 **裁剪(`trim_video`)/滤镜(`apply_video_filter`)/合并(`merge_videos`)/转场(`merge_with_transitions`) 等所有 ffmpeg 调用** 在真正执行时立即抛出 `Popen.__init__() got an unexpected keyword argument 'creation_flags'`，整个剪辑后端完全瘫痪——用户在 UI 上点任何剪辑操作都会静默失败。已用 `replace_all` 统一为正确拼写 `creationflags=`，全项目 `app/` 目录已确认无残留错误拼写。

### ✅ 验证
- 用真实 ffmpeg 跑通「裁剪 → 滤镜烘焙(电影感/黑白) → 画面调节(eq) → 转场(xfade 淡入淡出) → 导出设置(640x360/24fps/2M/H.264/AAC)」完整管线。
- 产物 `final.mp4` 实测 `640 x 360 fps: 24`，`apply_export_settings` 返回 `True`，`RESULT: PASS ✅`。
- `editor_module.py` / `video_processor.py` / `editor_scheduler.py` 三模块 `py_compile` 全部通过。

---

## V4.9.0 (2026-07-12) — 剪辑导出可用性修复

### 🐞 修复（核心可用性）

- **导出致命崩溃修复** (`editor_module._build_edited_video`): `clip["effects"]` 曾被初始化为列表 `[]`，而导出时代码对其调用 `.get()` 触发 `AttributeError`；该异常在无 `except` 的 `try` 中上抛，被 `_export_video` 捕获后静默回退到原始单段素材——**所有剪切/复制/滤镜/转场编辑全部丢失**。现统一 `effects` 为字典并做安全访问，编辑成果可真实进入成品。
- **滤镜按钮全部接通** (`editor_module._make_effect_tab`): 原 12 个滤镜按钮创建后从未绑定点击事件，且「应用滤镜」按钮写死传入非法字符串 `"selected"`（不在滤镜表里），导致滤镜永不烘焙。现每个按钮映射到合法滤镜键并应用；新增 `梦幻/锐利/柔和/都市/黄昏` 五个滤镜（`video_processor._FILTER_CATEGORY_VF`）。
- **导出设置真实生效** (`video_processor.apply_export_settings` + `editor_scheduler.export_video`): 此前 UI 上选的 分辨率/帧率/码率/编码/音频 全部被忽略（轻量内核 `process([])` 仅原样复制）。新增最终转码环节，按设置套用 `scale/fps/编码/码率`。
- **画面调节写入并烘焙** (`editor_module._apply_video_adjustments`): 亮度/对比度/饱和度/色调此前只 `print` 不落盘。现写入当前片段 `effects.color_params`，导出时经 `map_filter_to_vf` 烘焙为 `eq` 滤镜（`map_filter_to_vf` 新增 hue 支持）。
- **传统 AI 剪辑 NameError** (`editor_module._ensure_ai_clip_algorithm`): `AIClipAlgorithm` 被使用却从未导入。改为懒加载（`from .modules import AIClipAlgorithm`）并 `try/except` 兜底，失败时优雅降级而非崩溃。

### ✅ 验证
- 已用真实 ffmpeg 跑通「裁剪 + 滤镜烘焙 + 转场 xfade + 调节 + 导出设置」完整管线，产出合法视频文件。

---

## V4.8.1 (2026-07-12) — AI特效制作插件

### 🆕 新增
- **AI特效制作插件** (`app/plugins/ai_effects_plugin/`): 完整的智能视频/图像特效处理系统（4316行代码），符合PLUGIN_STANDARD规范，实现IEffectPlugin接口全部必需方法
  - **风格迁移模块** (`effects/style_transfer.py`, 379行): 8种预设艺术风格——梵高星空🌀、莫奈睡莲💐、毕加索抽象🔷、赛博朋克🌃、动漫风✨、油画🎨、水彩画💧、素描✏️；可调节风格强度(0-100%)与颜色保留选项；基于双边滤波+边缘增强算法
  - **背景替换模块** (`effects/background_replace.py`, 300行): GrabCut语义分割自动识别前景；5种背景类型(纯色/模糊/自定义图片/渐变/透明)；边缘羽化平滑过渡；集成QColorDialog颜色选择器
  - **超分辨率模块** (`effects/super_resolution.py`, 385行): 支持2x/3x/4倍放大；3种质量模式(快速⚡/均衡⚖️/高质量🎯)；内置3级降噪算法(高斯/双边/NL-Means)；多尺度细节重建+USM锐化；含VideoSR子类支持帧间时序融合
  - **智能美颜模块** (`effects/beauty_filter.py`, 458行): 自动人脸检测(Haar级联)；4维美颜参数(磨皮/美白/瘦脸/大眼)；自然效果模式开关；**4个快捷预设**(自然清新/柔光女神/精致妆容/韩式偶像)；局部网格变形技术
  - **物体移除模块** (`effects/object_removal.py`, 639行): 3种移除模式(自动检测🤖/手动框选▢/笔刷涂抹🖌️)；4种填充算法(AI Inpainting/Content-Aware Fill/Blur Fill/Clone Stamp)；11类可检测物体(文字水印/Logo/印章日期戳/人物汽车建筑等)；FFT频域文字检测技术
  - **PyQt6控制面板** (`ui/ai_effects_widget.py`, 1003行): 5标签页UI架构；20+参数控件(滑块/下拉框/颜色选择器/复选框/SpinBox)；EffectProcessorThread后台线程处理避免UI阻塞；实时预览区；进度条显示

### 🔌 插件规范
- 实现IEffectPlugin完整接口: `plugin_info`属性、`initialize`/`shutdown`生命周期、`get_ui_config`配置、`apply_effect`核心方法、`get_effect_params`参数定义
- PLUGIN_INFO元信息: name/version/author/category/icon/entry_point/tags/compatibility完整定义
- manifest.json配置清单符合PluginStore发布格式
- 支持PluginLoader自动发现与热加载
- 单例模式确保资源唯一性 + 懒加载模型机制
- 完整README.md使用文档(17KB, 含8个API示例)

### 📦 依赖
- 必需: numpy>=1.21, opencv-python>=4.5, Pillow>=8.0, PyQt6>=6.2
- 推荐(高级功能): torch>=1.10, dlib>=19.22, mediapipe>=0.8

---

## V4.8.0 (2026-07-11) — 滤镜转场落盘与云 API 懒加载

### 🆕 新增
- **滤镜/转场烘焙进导出视频**: `video_processor` 新增 `map_filter_to_vf` / `apply_video_filter` / `merge_with_transitions`，将预览态的滤镜(黑白/复古/清新/暖色调/冷色调/电影感)与转场(淡入淡出/滑动/缩放/模糊/翻转/溶解/擦除)通过 ffmpeg `-vf` 与 `xfade`/`acrossfade` 真正写入成品；`editor_module._build_edited_video` 重构为「先逐段烘焙滤镜 → 再按需 xfade 合并」，实现预览即所得
- **Sprint 2 云 API 懒加载注册表**: `cloud_providers/registry.py` 的 `ProviderRegistry` 支持 `register` / `bulk_register` / 懒加载 `resolve`（首次调用才动态 `importlib` 导入并缓存）+ 动态注册；`cloud_api.py` 改用 `default_registry`，消除对 15 个 provider 类的急切导入依赖
- **ai_clip_flow 步骤契约单测**: `tests/test_ai_clip_flow_steps.py` 以 sys.modules 桩件在无 GUI 环境下加载模块，校验「84 行编排器 + 5 个 step 方法」的派发顺序与统一签名(settings/vp/work_dir/base_name/current_output/progress/results)，并验证 current_output 在步骤间正确透传

### 🧪 测试
- conftest `reset_core_singletons` 在缺少 PyQt6 的无头/CI 环境下静默跳过单例重置，避免阻断不依赖 GUI 的单元测试

## V4.6.0 (2026-06-19) — Sprint 1 清债与架构修复

### 🐛 Bug 修复
- **删除 3 个冗余旧类**: `modules.py` 中 `ThreadPool`/`HardwareDetector`/`PerformanceMonitor` 旧版定义覆盖了 `utils/` 的正确导入（隐蔽 Bug）
- **修复 editor 懒加载路径**: `module_registry.py` 中 `import_module` 从 `.modules` 改为 `.editor_module`，避免触发整个 modules.py 全量加载

### 🔧 架构重构
- **BaseModule 独立化**: 从 `modules.py` 提取 `BaseModule` 到 `base_module.py`，解除 9 个子模块的循环依赖风险
- **render 包瘦身**: `render/__init__.py` 从 277 行实现代码 → 9 行 re-export，实现类移至 `render/render_core.py`
- **SettingsModule/HelpModule 统一继承 BaseModule**: 获得 EventBus/DataBus 自动注入 + 统一 `set_theme()` 接口
- 9 个子模块的 `from .modules import BaseModule` 全部改为 `from .base_module import BaseModule`

### 📦 modules.py 精简
- `modules.py` 从 ~1925行 压缩到 ~1810行（删除冗余类 + BaseModule 提取）

---

## V4.5.0 (2026-06-19) — Sprint 0 深度拆分

### 🔧 重构
- **TimelineWidget 家族4类** 拆分为独立文件 `timeline_widget.py`（~1225行）: TimeRuler、TrackControlPanel、TimelineWidget、ClipWidget
- **HelpModule** 拆分为独立文件 `help_module.py`（~822行）
- `modules.py` 从 ~1925行 进一步压缩（TimelineWidget 家族已拆分）
- `settings_module.py` 从 ~3261行 压缩到 ~2439行（-25%）
- `module_registry.py` 同步更新 help 模块导入路径

### 🎨 UI
- **合并设置选项卡**: "主题"+"字体" → 统一 "外观" 选项卡
- **新增关于页面**: 精美 QSS 渐变设计，显示版本号 V4.5.0 + 技术栈标签

### 🐛 修复
- 窗口标题版本号同步: v3.0 → v4.4.0
- `materials_module.py`/`tasks_module.py` 中 `QMimeData`/`QUrl` 导入更正（PyQt6.QtGui → QtCore）

---

## V4.4.0 (2026-06-19) — Sprint 0 模块拆分

### 🔧 重构
- **CopywritingModule** 拆分为独立文件 `copywriting_module.py`（~1050行）
- **TasksModule** 拆分为独立文件 `tasks_module.py`（~750行）
- **MaterialsModule**（含 `_DraggableAssetList`）拆分为独立文件 `materials_module.py`（~570行）
- `modules.py` 从 ~5500行 压缩到 ~3150行（减少 ~43%）
- `module_registry.py` 同步更新3个模块的导入路径
- 修复 `materials_module.py` 缺失的 `_current_page/_page_size/_current_materials` 初始化和 `_change_page()` 方法

---

## V4.3.0 (2026-06-19) — 第二轮专项补全

### 🆕 新增
- **DramaWebScraper** (`drama_web_scraper.py`): 短剧Web抓取器，从公开数据聚合源获取真实热榜
- **drama_data.json**: 92条结构化短剧数据JSON缓存
- **CopywritingModule.batch_generate()**: C-1 批量文案生成，支持多输入并发LLM调用
- **CopywritingModule.ab_generate()**: C-3 A/B多版本文案对比，含5维评分引擎
- **BatchTaskManager 定时调度 (T-6)**: `schedule_task()` + 后台调度线程，支持延迟执行
- **BatchTaskManager 并发控制**: `threading.Semaphore` 限制真正并发数

### 🔧 修复
- **DramaCrawler._init_apis()**: 集成 DramaWebScraper 作为第四层兜底数据源
- **DramaCrawler.fetch_dramas()**: 在API失败后/Plywright失败后增加Web抓取器中间层
- **BatchTask 数据类**: 新增 `depends_on`(T-1), `max_retries/retry_count/retry_delay`(T-3), `scheduled_at`(T-6)
- **BatchTaskManager._process_queue()**: 集成T-1依赖检查——只有依赖完成的任务才执行
- **BatchTaskManager._execute_task_with_retry()**: T-3自动重试机制
- **BatchTaskManager.add_task()**: 支持 depends_on/max_retries/scheduled_at 参数

---

## V4.2.0 (2026-06-19) — 开源专项补全

### 🆕 新增
- 版本号管理体系 (`app/version.py`, `CHANGELOG.md`)
- DouyinUploader / BilibiliUploader: Playwright 自动化平台发布
- GenericUploader: 通用多平台导出器
- video_processor.py 新增7种操作类型: add_bgm, sharpen, denoise, saturation, stabilize, upscale, logo_removal

### 🔧 修复
- **video_processor.py**: `_find_highlights()` 对接 AutoClipIntegration 真实算法；`_classify_content()` 改为10类关键词匹配
- **platforms/__init__.py**: `publish_to_platform()` 从纯模拟→3级策略（Playwright→本地导出→错误）
- **account_skills.py**: `_collect_platform_data()` / `_do_publish()` / `_batch_publish()` 对接真实模块
- **workflow_manager.py**: 4个核心步骤 (下载/剪辑/文案/发布) 全部对接真实模块
- **llm_editor.py**: 6个action 全部真实映射 — add_transition→TransitionManager / add_effect→EffectManager / add_subtitle/add_title→SubtitleManager / change_speed→tm.update_clip / adjust_volume→tm.update_clip

---

## V4.1 (2026-06-19) — 乐高积木式插件架构

### 🆕 新增
- 乐高积木式模块架构: CORE(4) / ADVANCED(5) / EXPERIMENTAL(5)
- 自然语言编辑器 (LLMEditor)
- 全链路工作流管理器 (WorkflowManager)
- 账号运营Skills系统 (AccountOpsModule)
- 平台集成发布系统 (PlatformIntegrator)
- 开源项目专项补全方案 (第十一章)

### 🔧 修复
- AutoClip 5维高光检测算法 (运动40%+音频25%+场景15%+面部20%+综合)

---

## V3.0 (2026-06) — PyQt6 AI短剧编辑器

### 🆕 新增
- PyQt6 桌面端应用架构
- AI短剧剪辑流水线
- 多平台发布框架
- 14个模块插件系统
