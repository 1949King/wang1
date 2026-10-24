# Agent 面板优化方案（P0 + P1 全套）

## Context

当前 Agent 面板（[editor_module.py:8265-9280](file:///D:/拾光剪影/app/modules/lego/editor_module.py)）存在 8 个痛点，核心问题是：
1. **参数硬编码**：平台/时长/provider 写死在 `_on_run_full_pipeline`，用户无法配置
2. **执行黑盒**：仅追加文本消息，无进度条/无阶段指示/无结果展示
3. **结果不透明**：五维打分、剪辑脚本、预览问题都不展示给用户
4. **失败引导弱**：精剪失败仅文字提示，无一键手动精剪入口

本次优化目标：把 Agent 面板从「单输入框 + 纯文本流」升级为「**配置卡 → 进度卡 → 结果卡**」三段式结构，让全链路执行对用户完全透明可控。

## 硬约束

- **只修改 1 个文件**：`app/modules/lego/editor_module.py`
- **core 层零改动**：`agent_pipeline_orchestrator / capability_handlers / video_generation_client / preview_validation_loop / five_dimension_scorer / editing_script_generator` 全部不动
- **不动冻结区**：本方案完全不触碰冻结区符号
- **保持方法签名不变**：只新增辅助方法，不改既有方法签名
- **所有新增控件存为实例属性**：`self._agent_xxx`，避免 GC
- **所有弹窗绑定父窗口**：`QFileDialog/QMessageBox` 第一参数固定 `self`

## 关键事实（方案成立前提）

1. `pipeline.run_full` handler 已从 `req.params` 读取 `platform/target_duration/clip_duration/provider/auto_preview_pass`（[capability_handlers.py:412-426](file:///D:/拾光剪影/app/core/capability_handlers.py)），**UI 只需把用户选择塞入 params 即可**
2. `pipeline_done` 事件载荷已含 `route/scored_count/editing_script/final_video_path/session_id`（[agent_pipeline_orchestrator.py:49-59](file:///D:/拾光剪影/app/core/agent_pipeline_orchestrator.py)），**UI 只需渲染**
3. `agent_pipeline_orchestrator.get_session(session_id).scored_results` 可只读查询打分明细
4. `video_generation_client.list_providers()` 可只读查询 provider 可用性
5. `preview_validation_loop.get_clips_by_status(PreviewStatus.FAILED)` 可只读查询失败片段
6. 所有需要的 Qt 控件已 import（QProgressBar/QFrame/QListWidget/QComboBox/QSpinBox 等）

## 实施步骤

### 步骤1：新增配置卡（痛点1+8，P0）

**位置**：在 `_create_edit_agent_panel` 内，`pipeline_row`（约 8391 行）之前插入

**新增方法**：`_build_agent_config_card(self, parent_layout: QVBoxLayout) -> None`

**控件**：
- `_agent_platform_combo`: QComboBox（抖音/快手/B站/小红书，data: douyin/kuaishou/bilibili/xiaohongshu）
- `_agent_duration_combo`: QComboBox（15秒/30秒/60秒，data: 15.0/30.0/60.0）
- `_agent_clip_duration_spin`: QDoubleSpinBox（0.5-10.0，step 0.5，默认 5.0）
- `_agent_provider_combo`: QComboBox（auto/seedance/cogvideo/local）
- `_agent_provider_status_lbl`: QLabel（实时显示 provider 可用性）

**新增方法**：
- `_get_pipeline_params(self) -> Dict[str, Any]`：收集配置卡参数
- `_refresh_provider_status(self) -> None`：刷新 provider 状态标签

**改造方法**：`_on_run_full_pipeline`（9148 行）
- 正常启动分支（9244-9253）：把硬编码 `params={...}` 替换为 `**self._get_pipeline_params()`
- 继续执行分支（9178-9188）：同样替换，但 `auto_preview_pass=True` 保持硬写

### 步骤2：新增进度卡（痛点2，P0）

**位置**：配置卡之后插入

**新增方法**：`_build_agent_progress_card(self, parent_layout: QVBoxLayout) -> None`

**控件**：
- `_agent_stage_bar`: QProgressBar（0-100，textVisible=False，渐变 chunk）
- `_agent_stage_label`: QLabel（"3/6 · 五维打分中"）
- `_agent_stage_detail`: QLabel（原始 message，截断 80 字）

**新增常量**：
```python
_PIPELINE_STAGES = [
    ("routing",    "🔀", "智能业务分流"),
    ("generation", "🎬", "AI 视频生成"),      # 业务线1
    ("import_parsing", "📥", "素材解析"),     # 业务线2（与 generation 二选一）
    ("preview",    "🔍", "预览校验"),
    ("scoring",    "📊", "五维打分"),
    ("scripting",  "📝", "剪辑脚本"),
    ("editing",    "✂️", "精剪成片"),
    ("done",       "✅", "完成"),
]
```

**新增方法**：
- `_update_pipeline_stage(self, stage: str, message: str) -> None`：映射 stage 到进度百分比
- `_finalize_pipeline_stage(self, success: bool, error: str = "") -> None`：完成时置 100% 或红色

**改造方法**：
- `_handle_pipeline_progress`（8899）：先调 `_update_pipeline_stage`，再保留原 emoji 消息追加
- `_handle_pipeline_done`（8918）：末尾调 `_finalize_pipeline_stage`
- `_reset_pipeline_button`（8935）：末尾可选手动重置进度条

### 步骤3：provider 回退提示（痛点8，P0）

**扩展方法**：`_on_pipeline_event`（8862）增加分支
```python
elif subtype == "video_generation_done":
    self._handle_video_generation_done(data)
```

**新增方法**：`_handle_video_generation_done(self, data: Dict) -> None`
- 判断 `paths` 是否全是 `gen_*.mp4`（local 占位文件名前缀）
- 若是，在 `_agent_provider_status_lbl` 追加警示，chat 追加系统消息

### 步骤4：新增打分结果卡（痛点3，P1）

**位置**：进度卡之后插入，默认隐藏

**新增方法**：`_build_agent_score_card(self, parent_layout: QVBoxLayout) -> None`

**控件**：
- `_agent_score_list`: QListWidget（每行一个镜头的等级+总分+五维细分）

**新增方法**：`_render_score_results(self, scored_results: List[Dict]) -> None`
- 等级徽章配色：S=#ffd700, A=#7ee787, B=#d29922, C=#fb8500, D=#ff7b72
- D 级追加"⚠ 已剔除"标记

**改造方法**：`_handle_pipeline_done`（8918）
- 从 `result.get("session_id")` 拿 session_id
- 调 `agent_pipeline_orchestrator.get_session(session_id).scored_results`
- 调 `_render_score_results` 渲染

### 步骤5：新增剪辑脚本卡（痛点4+6，P1）

**位置**：打分卡之后插入，默认隐藏

**新增方法**：`_build_agent_script_card(self, parent_layout: QVBoxLayout) -> None`

**控件**：
- `_agent_script_view`: QTextEdit（只读，HTML 渲染）
- `_agent_copy_script_btn`: QPushButton（复制 JSON）
- `_agent_export_script_btn`: QPushButton（导出 JSON 文件）
- `_agent_manual_edit_btn`: QPushButton（▶ 一键手动精剪）

**新增方法**：
- `_render_editing_script(self, script: Optional[Dict]) -> None`：渲染脚本到 HTML
- `_on_copy_script_clicked(self) -> None`：复制到剪贴板
- `_on_export_script_clicked(self) -> None`：QFileDialog 导出（父窗口 self）
- `_on_manual_edit_clicked(self) -> None`：调既有 `pipeline.execute_editing` 能力

**改造方法**：`_handle_pipeline_done`（8918）
- 从 `result.get("editing_script")` 拿脚本
- 调 `_render_editing_script` 渲染

### 步骤6：新增预览问题卡（痛点5，P1）

**位置**：脚本卡之后插入，默认隐藏

**新增方法**：`_build_agent_preview_card(self, parent_layout: QVBoxLayout) -> None`

**控件**：
- `_agent_preview_list`: QListWidget（显示失败片段 clip_id）

**新增方法**：`_render_preview_issues(self, failed_clips: List[Dict]) -> None`
- 保守版：仅显示 clip_id 列表（不展示 issue 描述，因为 `preview_validation_loop._registry` 是私有的）
- 用户可在时间线上手动定位

**改造方法**：`_handle_waiting_preview`（8878）
- 保留原按钮文案切换逻辑
- 末尾新增：调 `preview_validation_loop.get_clips_by_status(PreviewStatus.FAILED)` + `_render_preview_issues`

### 步骤7：精剪失败引导文案优化（痛点6，P1）

**改造方法**：
- `_handle_pipeline_done`（8918）的"脚本已生成，可手动精剪"分支：改为引导用户点击脚本卡的【▶ 一键手动精剪】按钮
- `_on_full_pipeline_done`（9262）同样改造文案

## UI 控件样式规范

| 用途 | 背景色 | 边框色 | 文字色 | 圆角 |
|------|--------|--------|--------|------|
| 卡片容器 | #111722 | #263244 | — | 10px |
| 输入控件 | #161b22 | #30363d | #e6edf3 | 6px |
| 主操作按钮 | #1f2a3d | #2f5139 | #7ee787 | 8px |
| 进度条 chunk | 渐变 #1f6feb → #7ee787 | — | — | 4px |

**等级徽章配色**：S=#ffd700, A=#7ee787, B=#d29922, C=#fb8500, D=#ff7b72

## 风险与缓解

| 风险 | 缓解 |
|------|------|
| 新增卡片撑高面板挤压 chat 区 | 卡片默认隐藏，仅启动时显示进度卡；其他卡仅在事件触发时显示 |
| `get_session()` 返回 None | `_render_score_results` 加 `if not session: return` 守卫 |
| 事件触发早于控件创建 | 所有 `_handle_*` 方法第一行加 `getattr(self, "_agent_xxx", None)` 守卫 |
| 改 params 后 handler 读取失败 | handler 已用 `req.params.get(key, default)` 兜底，安全 |
| 进度条阶段映射不准 | generation/import_parsing 共享同一槽位（业务线1/2互斥） |

## 验证方案

### 静态验证
```
python -m py_compile app/modules/lego/editor_module.py
python scripts/frozen_zone_guard.py
```

### 启动 + 端到端验证
```
python -m app.main_qt6
```

人工核对清单：
1. 配置卡显示平台/时长/单段时长/provider/状态标签
2. provider 状态标签显示 seedance/cogvideo 可用性
3. 输入创意 → 点击全链路执行 → 进度卡按 6 阶段推进
4. 预览暂停时，预览问题卡显示失败片段列表
5. 完成时，打分卡显示每个镜头 S/A/B/C/D 等级 + 五维细分
6. 脚本卡显示 clip_order/transitions/beat_points/bgm/dropped_clips
7. 脚本卡点击【▶ 一键手动精剪】→ 触发既有 `pipeline.execute_editing` 能力
8. 云端 provider 不可用时，状态标签变红，chat 追加"使用了本地占位色块"提示
9. 不输入参数点击执行 → handler 默认值兜底，行为与改造前一致

### 行为回归
- 重复点击启动按钮 → `send_btn.setEnabled(False)` 防重复未被破坏
- 中途异常 → 进度卡显示红色 ❌，不卡死
- 切换平台/时长/provider 后执行 → core 拿到正确参数

## 交付检查清单

1. ✅ 只修改 `app/modules/lego/editor_module.py` 一个文件
2. ✅ core 层零改动
3. ✅ 所有新增控件存为 `self._agent_xxx` 实例属性
4. ✅ 所有弹窗第一参数为 `self`
5. ✅ 防御性 `getattr(self, "_agent_xxx", None)` 守卫全覆盖
6. ✅ 冻结区校验通过
7. ✅ py_compile 通过
8. ✅ 启动 + 全链路一键执行端到端验证通过
