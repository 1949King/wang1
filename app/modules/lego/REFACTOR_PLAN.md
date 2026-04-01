# AI短剧编辑器代码拆分计划

## 源文件
`ai_short_drama_editor_optimized.py` (16305行)

## 拆分目标

### 1. 核心模块 (modules/lego/)

| 文件名 | 内容 | 预估行数 |
|--------|------|----------|
| `thread_pool.py` | ThreadPool 线程池类 | ~100行 |
| `account_analyzer.py` | AccountAnalyzer 账号分析类 | ~150行 |
| `openclow_engine.py` | OpenClowEngine 自动化引擎类 | ~250行 |
| `editor_main.py` | AIShortDramaEditor 主编辑器类 | ~8000行 |
| `plugin_manager_legacy.py` | PluginManager 插件管理类 | ~300行 |
| `video_processor.py` | 视频处理函数 | ~500行 |
| `ui_components.py` | UI组件和主题 | ~1000行 |
| `editor_utils.py` | 辅助函数和工具 | ~500行 |

### 2. 已有模块 (保持不变)
- `core.py` - EventBus, MasterClock, DataBus
- `base_block.py` - LegoBlock 积木基类
- `skill_engine.py` - Skill 执行引擎
- `account_skills.py` - 账号运营 Skills
- `main_window.py` - Qt6 主窗口
- `modules.py` - 9 大功能模块
- `builtin_blocks.py` - 内置积木
- `block_loader.py` - 积木加载器
- `flow_orchestrator.py` - 流程编排器
- `auth.py` - 认证服务
- `login_window.py` - 登录界面

## 拆分步骤

### 步骤 1: 创建独立类文件
1. 提取 ThreadPool 类 → `thread_pool.py`
2. 提取 AccountAnalyzer 类 → `account_analyzer.py`
3. 提取 OpenClowEngine 类 → `openclow_engine.py`
4. 提取 PluginManager 类 → `plugin_manager_legacy.py`

### 步骤 2: 拆分主编辑器类
1. 提取主题相关方法 → `ui_components.py`
2. 提取视频处理方法 → `video_processor.py`
3. 提取辅助方法 → `editor_utils.py`
4. 保留核心编辑器逻辑 → `editor_main.py`

### 步骤 3: 更新导入
1. 更新 `__init__.py` 导出新模块
2. 确保所有依赖正确导入

## 依赖关系

```
editor_main.py
├── ui_components.py (主题、UI工具)
├── video_processor.py (视频处理)
├── editor_utils.py (辅助函数)
├── thread_pool.py (线程池)
├── account_analyzer.py (账号分析)
├── openclow_engine.py (自动化引擎)
├── plugin_manager_legacy.py (插件管理)
├── core.py (EventBus, DataBus)
├── auth.py (认证服务)
└── 外部依赖 (tkinter, cv2, etc.)
```

## 执行顺序
1. 创建 thread_pool.py
2. 创建 account_analyzer.py
3. 创建 openclow_engine.py
4. 创建 plugin_manager_legacy.py
5. 创建 ui_components.py
6. 创建 video_processor.py
7. 创建 editor_utils.py
8. 创建 editor_main.py
9. 更新 __init__.py
