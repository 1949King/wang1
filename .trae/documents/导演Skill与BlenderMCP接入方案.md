# 导演 Skill（全功能型）+ Blender MCP（harveyxiacn 增强版）接入方案

## Context（为什么做这个改动）

用户要在「拓展中心」加入「导演 Skill」和「Blender MCP」，目标是对齐「专业创意剪辑 + AI 智能剪辑 + 3D CG 视频生成」定位。

通读代码后发现两个关键事实，颠覆了表面认知：

1. **Blender MCP 连接逻辑现已可用**：`app/core/mcp_client.py` 是完整 JSON-RPC 2.0 客户端（stdio/SSE 双传输、30 秒超时、Windows select 回退），`BLENDER_MCP_CONFIG` 预设已配。`ExtensionsModule._connect_mcp_preset` ([extensions_module.py:1379](file:///d:/拾光剪影/app/modules/lego/extensions_module.py#L1379)) 真实调用 `McpClientManager.connect()` 后台线程拉取工具列表。MCP tab 已有完整 UI。

2. **两个隐藏 bug 让用户觉得"没有"**：
   - `register_skills()` ([video_editing_skill.py:315](file:///d:/拾光剪影/app/modules/lego/video_editing_skill.py#L315)) 定义了却**从未被任何地方调用** → 3 个现有 Skill 全没注册，Skill 工坊列表为空。
   - `_run_selected_skill` ([extensions_module.py:1354](file:///d:/拾光剪影/app/modules/lego/extensions_module.py#L1354)) 是**假实现**：只拼字符串显示，根本没调 `skill_engine.execute_skill()`，且主线程跑会卡 UI（违反 `.trae/rules/2.md §五.2`）。

3. `thirdparty/blender/` 目录不存在，需新增 Git 下载脚本。

### 用户决策（已确认）
- **导演 Skill = 全功能型**：直接调 LLM 从零生成剧本+分镜+剪辑指令，不依赖现有 SmartClip/AutoSubtitle
- **Blender MCP = harveyxiacn 增强版**（[github.com/harveyxiacn/blender-mcp](https://github.com/harveyxiacn/blender-mcp)）：359 工具 + 6 档 profile + skill 系统，更适合 AI 导演场景

### 冻结区核查（已确认安全）
`docs/knowledge/frozen_zones.json` 显示冻结符号仅涉及：editor_module 播放/变换、video_processor bake、preview_manager、clip_transform、drama_finder_plugin、plugins_module 的 drama_finder 方法、plugin_store。

**本次改动文件全部未冻结**：`ai_engine.py` / `llm_clipper.py` / `ai_editing_assistant.py` / `extensions_module.py` / `skill_engine.py` / `video_editing_skill.py` / `main_qt6.py` 均不在冻结区，可安全修改。

---

## 改动清单（5 项，全部最小侵入）

### 改动 1：修复 Skill 注册（隐藏 bug A）

**文件**：[main_qt6.py](file:///d:/拾光剪影/main_qt6.py) `AIShortDramaEditorApp._show_main_window`（L68-75）

在 `MainWindow` 创建后调用 `register_skills()`：

```python
def _show_main_window(self):
    print("创建MainWindow...")
    self.main_window = MainWindow()
    # 修复：register_skills 之前从未被调用，导致 Skill 工坊列表为空
    try:
        from app.modules.lego.video_editing_skill import register_skills
        register_skills()
    except Exception as e:
        print(f"Skill 注册失败（不影响启动）: {e}")
    self.main_window.destroyed.connect(self._on_main_window_closed)
    self.main_window.show()
    print("MainWindow已显示")
```

### 改动 2：新增全功能型导演 Skill（新文件）

**新文件**：`app/modules/lego/director_skill.py`

照 [video_editing_skill.py](file:///d:/拾光剪影/app/modules/lego/video_editing_skill.py) 的 Skill 基类模式，但**直接调 LLM 从零生成**，不依赖现有 Skill：

```python
class DirectorSkill(Skill):
    """AI 导演技能 - 全功能型：LLM 从零生成剧本/分镜/剪辑指令，可选 Blender 3D 片头"""

    skill_id = "director"
    skill_name = "AI 导演（全功能）"
    skill_description = "输入主题/素材，LLM 生成完整剧本→分镜表→剪辑指令→字幕，可选 Blender MCP 渲染 3D 片头"
    skill_category = "AI 导演"
    skill_icon = "🎬"
    skill_version = "1.0.0"
```

**步骤设计**（全部调 LLM 生成，复用 ai_engine 接口）：

| 步骤 | handler | 复用来源 | 输出 |
|------|---------|----------|------|
| 1. 生成剧本 | `_generate_script` | `AIEngine.chat_with_fallback` ([ai_engine.py:533](file:///d:/拾光剪影/app/core/ai_engine.py#L533)) | 完整剧本（场景/对白/动作） |
| 2. 拆分镜表 | `_generate_storyboard` | `AISession.chat` ([ai_engine.py:747](file:///d:/拾光剪影/app/core/ai_engine.py#L747)) + system_prompt | 镜头表（编号/时长/景别/对白） |
| 3. 生成剪辑指令 | `_generate_edit_instructions` | `LLMClipper.smart_clip` ([llm_clipper.py:228](file:///d:/拾光剪影/app/core/ai/llm_clipper.py#L228)) 复用 prompt 模板 | 时间线剪辑指令 JSON |
| 4. 提取字幕 | `_extract_subtitles` | 从分镜对白提取，调 whisper fallback | SRT 字幕 |
| 5. 可选 3D 片头 | `_render_3d_intro` | `McpClientManager` 调 Blender MCP（连上时） | 片头视频路径 |
| 6. 合成报告 | `_compose_final` | 汇总以上产物 | 导演报告 JSON |

**关键实现要点**：

- **LLM 调用统一走 `chat_with_fallback`**：云服务 → Ollama 本地 → 模板占位，三级降级（[ai_engine.py:533](file:///d:/拾光剪影/app/core/ai_engine.py#L533) 已实现），保证离线也能跑
- **system_prompt 设计**：导演步骤用专业 prompt 模板（剧本结构/分镜规范/剪辑语法），写入 `DirectorSkill._build_prompt(step_name)` 私有方法
- **流式输出**：`chat_with_fallback(stream=True)` 返回 Generator，逐 token 写 `context.set_variable` 供进度回调显示
- **3D 片头降级**：`condition=self._blender_connected` 控制步骤 5 是否执行，Blender MCP 未连时跳过不阻断
- **异常路径**：每步 try/except，LLM 失败返回 `StepResult(success=False, error=...)` 但不抛异常打断整个 Skill

**注册**：在 `video_editing_skill.py` 的 `register_skills()` 末尾追加：

```python
def register_skills():
    skill_registry.register(AutoSubtitleSkill)
    skill_registry.register(SmartClipSkill)
    skill_registry.register(CoverGeneratorSkill)
    # 新增：全功能型 AI 导演 Skill
    from .director_skill import DirectorSkill
    skill_registry.register(DirectorSkill)
```

### 改动 3：修复 _run_selected_skill（隐藏 bug B，主线程保护）

**文件**：[extensions_module.py:1354-1373](file:///d:/拾光剪影/app/modules/lego/extensions_module.py#L1354)

当前假实现只拼字符串。改为真实异步执行 + 信号槽回主线程：

```python
# ExtensionsModule 类顶部新增信号
class ExtensionsModule(BaseModule):
    _skill_progress_signal = pyqtSignal(int, str)   # 新增：子线程→主线程
    _skill_finished_signal = pyqtSignal(bool, str)  # 新增：完成回调

    def _setup_ui(self):
        ...
        # 信号槽连接（_setup_ui 内部）
        self._skill_progress_signal.connect(self._on_skill_progress_main)
        self._skill_finished_signal.connect(self._on_skill_finished_main)

    def _run_selected_skill(self):
        """运行选中的技能（异步执行，主线程安全）"""
        current = self._skill_list.currentItem()
        if not current:
            QMessageBox.warning(self, "警告", "请先选择一个技能")
            return
        skill_data = current.data(Qt.ItemDataRole.UserRole)
        skill_id = skill_data.get("skill_id")
        if not skill_id:
            return
        inputs = {}
        input_text = self._skill_input.text().strip()
        if input_text:
            try:
                inputs = json.loads(input_text)
            except json.JSONDecodeError:
                QMessageBox.warning(self, "参数错误", "输入参数不是合法 JSON")
                return
        self._set_status(f"正在执行技能: {skill_data.get('name', '')}")
        self._skill_output.setPlainText("执行中...")
        from app.modules.lego.skill_engine import skill_engine
        # async_mode=True 已在子线程跑（skill_engine.py:507）
        result = skill_engine.execute_skill(
            skill_id, inputs,
            progress_callback=lambda p, m: self._skill_progress_signal.emit(p, m),
            async_mode=True
        )
        if not result.get("success") and result.get("error"):
            self._skill_output.setPlainText(f"启动失败: {result['error']}")

    def _on_skill_progress_main(self, progress: int, message: str):
        """主线程槽：更新进度"""
        self._skill_output.setPlainText(f"[{progress}%] {message}")
        self._set_status(f"执行中: {progress}%")

    def _on_skill_finished_main(self, success: bool, result_text: str):
        """主线程槽：更新最终结果"""
        self._skill_output.setPlainText(result_text)
        self._set_status("完成" if success else "失败")
```

**注意**：`skill_engine.execute_skill(async_mode=True)` 的 progress_callback 在子线程触发，必须通过 `pyqtSignal` 中转回主线程（`.trae/rules/2.md §五.2`）。完成信号需在 Skill 执行结束时触发——可通过 EventBus 监听 `TASK_COMPLETED`/`TASK_FAILED` 事件（[skill_engine.py:299](file:///d:/拾光剪影/app/modules/lego/skill_engine.py#L299) 已 emit 这些事件），在 ExtensionsModule 订阅并转 `_skill_finished_signal`。

### 改动 4：Blender MCP（harveyxiacn 增强版）Git 下载

**新文件**：`scripts/setup_blender_mcp.ps1`

```powershell
# 从 Git 下载 harveyxiacn/blender-mcp 到 thirdparty/blender/blender-mcp/
$ErrorActionPreference = "Stop"
$root = Split-Path $PSScriptRoot -Parent
$target = Join-Path $root "thirdparty\blender\blender-mcp"

# 检查 git
$git = Get-Command git -ErrorAction SilentlyContinue
if (-not $git) { throw "未检测到 git，请先安装 Git for Windows" }

if (Test-Path $target) {
    Write-Host "blender-mcp 已存在: $target"
    exit 0
}
New-Item -ItemType Directory -Force -Path (Split-Path $target) | Out-Null
Write-Host "正在 git clone harveyxiacn/blender-mcp（359 工具增强版）..."
git clone --depth 1 https://github.com/harveyxiacn/blender-mcp.git $target
if ($LASTEXITCODE -ne 0) { throw "git clone 失败" }
Write-Host "完成: $target"
Write-Host ""
Write-Host "后续启用方式（二选一）："
Write-Host "  1. 本地运行: cd $target; uv sync; uv run blender-mcp"
Write-Host "  2. 直接安装: pip install blender-mcp（注：PyPI 版本为基础版，增强版需从 git 装）"
Write-Host ""
Write-Host "Blender 端：编辑→首选项→插件→安装→选择 $target\dist\blender_mcp_addon.zip"
```

### 改动 5：MCP tab 加「从 Git 下载」按钮

**文件**：[extensions_module.py](file:///d:/拾光剪影/app/modules/lego/extensions_module.py) `_create_mcp_preset_card`（L617）

在 Blender MCP 预设卡片旁新增下载按钮（仅当 `thirdparty/blender/blender-mcp/` 不存在时显示）：

```python
def _create_mcp_preset_card(self, preset: Dict) -> QFrame:
    # ... 原有卡片逻辑保持不变 ...
    # 仅 Blender MCP 追加「从 Git 下载」按钮
    if preset.get("id") == "blender":
        import os
        blender_mcp_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
                os.path.abspath(__file__))))),
            "thirdparty", "blender", "blender-mcp"
        )
        if not os.path.exists(blender_mcp_path):
            download_btn = QPushButton("📥 从 Git 下载")
            download_btn.setStyleSheet(self._btn_secondary_style())
            download_btn.setToolTip("下载 harveyxiacn/blender-mcp 增强版到 thirdparty/blender/")
            download_btn.clicked.connect(self._download_blender_mcp)
            layout.addWidget(download_btn)
    return card

def _download_blender_mcp(self):
    """后台线程跑 setup_blender_mcp.ps1"""
    import subprocess, threading, os
    script = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__))))), "scripts", "setup_blender_mcp.ps1")
    self._set_status("正在从 Git 下载 blender-mcp...")

    def do_download():
        try:
            result = subprocess.run(
                ["powershell", "-ExecutionPolicy", "Bypass", "-File", script],
                capture_output=True, text=True, timeout=120,
                creationflags=subprocess.CREATE_NO_WINDOW
            )
            ok = result.returncode == 0
            msg = result.stdout if ok else (result.stderr or "下载失败")
            # 信号回主线程
            QTimer.singleShot(0, lambda: self._on_blender_download_done(ok, msg))
        except Exception as e:
            QTimer.singleShot(0, lambda: self._on_blender_download_done(False, str(e)))

    threading.Thread(target=do_download, daemon=True).start()

def _on_blender_download_done(self, success: bool, message: str):
    """主线程：下载完成提示"""
    if success:
        QMessageBox.information(self, "下载完成", f"blender-mcp 已下载到 thirdparty/blender/\n\n{message}")
        self._refresh_installed()  # 刷新卡片（下载按钮会消失）
        self._set_status("blender-mcp 下载完成")
    else:
        QMessageBox.warning(self, "下载失败", message)
        self._set_status("blender-mcp 下载失败")
```

---

## 复用的现有能力（不重复造轮子）

| 能力 | 文件:行 | 复用方式 |
|------|---------|----------|
| MCP 客户端 | [app/core/mcp_client.py:81](file:///d:/拾光剪影/app/core/mcp_client.py#L81) `McpClientManager` | DirectorSkill 步骤5 调用，已完整可用 |
| LLM 多级降级 | [app/core/ai_engine.py:533](file:///d:/拾光剪影/app/core/ai_engine.py#L533) `chat_with_fallback` | DirectorSkill 步骤1-3 调用，云→Ollama→模板 |
| LLM 会话 | [app/core/ai_engine.py:747](file:///d:/拾光剪影/app/core/ai_engine.py#L747) `AISession.chat` | 带 system_prompt 的分镜生成 |
| 剪辑 prompt 模板 | [app/core/ai/llm_clipper.py:228](file:///d:/拾光剪影/app/core/ai/llm_clipper.py#L228) `smart_clip` | 步骤3 复用 prompt 模板结构 |
| Skill 基类与异步执行 | [app/modules/lego/skill_engine.py:87](file:///d:/拾光剪影/app/modules/lego/skill_engine.py#L87) `Skill` + L507 `_execute_skill_async` | DirectorSkill 继承，async_mode=True |
| 现有 Skill 样板 | [app/modules/lego/video_editing_skill.py](file:///d:/拾光剪影/app/modules/lego/video_editing_skill.py) | DirectorSkill 代码结构照搬 |
| EventBus 完成事件 | [app/modules/lego/skill_engine.py:299](file:///d:/拾光剪影/app/modules/lego/skill_engine.py#L299) `TASK_COMPLETED` | 改动3 监听转完成信号 |

## 不改动的内容（守住边界）

- 不动 `app/core/mcp_client.py`（已完整可用，只调用）
- 不动 `app/core/ai_engine.py`（只调用 chat_with_fallback / AISession.chat）
- 不动 `app/core/ai/llm_clipper.py`（只复用 prompt 模板结构，不修改其符号）
- 不动 ExtensionsModule 的 4 个 tab 结构、MCP_PRESETS 列表
- 不动 PluginsModule / plugin_store.py（向后兼容）
- 不动 skill_engine.py 核心执行逻辑（async_mode 已支持）
- 不动冻结区任何符号
- 不删除任何原有代码、注释

---

## 验证方案

### 1. 语法验证（每个改动的 Python 文件）
```powershell
$py = "d:\拾光剪影\.venv312\Scripts\python.exe"
& $py -m py_compile main_qt6.py
& $py -m py_compile app\modules\lego\director_skill.py
& $py -m py_compile app\modules\lego\extensions_module.py
& $py -m py_compile app\modules\lego\video_editing_skill.py
```

### 2. 冻结区守护
```powershell
& $py scripts\frozen_zone_guard.py
```
预期：本次改动不引入新冻结符号，guard 应输出「未发现违规」。

### 3. Skill 注册与导演 Skill 验证
```powershell
$env:QT_QPA_PLATFORM = "offscreen"
& $py -c "from app.modules.lego.video_editing_skill import register_skills; from app.modules.lego.skill_engine import skill_engine; register_skills(); skills = skill_engine.list_available_skills(); print(f'Skill数: {len(skills)}'); assert len(skills) >= 4; assert any(s['skill_id'] == 'director' for s in skills); print('导演Skill已注册')"
```

### 4. 端到端人工验证
- 启动应用 → 拓展中心 → Skill 工坊 → 应看到 4 个 Skill（含「AI 导演（全功能）」）
- 点选 DirectorSkill → 输入 `{"topic": "30秒科技产品介绍"}` → 点运行 → 输出区显示进度（[0%] 生成剧本...→[100%] 完成）
- 切到 MCP 服务 tab → Blender MCP 卡片 → 点「📥 从 Git 下载」→ 等待 clone 完成
- 下载完成后卡片只显示「🔌 连接」按钮（下载按钮自动消失）
- 点「🔌 连接」→ 验证已连接列表出现 Blender MCP + 工具数

### 5. 残余风险
- `git` 未安装 → `setup_blender_mcp.ps1` 检测并提示安装 Git for Windows
- `uvx`/`uv` 未安装时 Blender MCP 连不上 → `McpClientManager` 已有 `FileNotFoundError` 处理（[mcp_client.py:284](file:///d:/拾光剪影/app/core/mcp_client.py#L284)），UI 显示「命令不存在」
- harveyxiacn 版默认 `skill` profile 只启动 32 工具，按需加载 → 与 DirectorSkill 理念契合，但首次 `tools/list` 只返回 32 个，需在 UI 提示用户可切 profile
- LLM 云服务不可用 → `chat_with_fallback` 自动降级到 Ollama 或模板占位，DirectorSkill 不阻断
- DirectorSkill 步骤5 调 Blender MCP 时若未连接 → `condition` 回调返回 False 跳过，主流程继续
