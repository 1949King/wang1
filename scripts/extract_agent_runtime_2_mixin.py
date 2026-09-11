"""第七批 Mixin 抽取: 阶段 1.3 —— 追加「Agent 面板运行时 UI + 任务控制」方法。

把仍残留在 editor_module.py 中的 24 个纯 UI/编排/任务控制方法（无 `_clips` 写、
无 Hebbian 学习闭环、无指令执行核心）追加抽取到既有的 EditorAgentRuntimeMixin，
并把 `_PIPELINE_STAGES` 阶段映射常量一并迁移（仅被 `_stage_progress`/`_stage_label` 使用）。
"""
import ast
from pathlib import Path

EDITOR = Path(r'd:\拾光剪影\app\modules\lego\editor_module.py')
MIXIN = Path(r'd:\拾光剪影\app\modules\lego\editor_agent_runtime_mixin.py')

# 阶段 1.3 候选：纯 UI/编排/任务控制（逐一确认无 _clips 写、无冻结区符号）
CANDIDATES = {
    # 模型/provider 订阅与读取
    "_subscribe_provider_activated", "_on_provider_activated_event",
    "_list_local_ollama_models",
    # 阶段映射（依赖 _PIPELINE_STAGES）
    "_stage_progress", "_stage_label",
    # 配置卡参数读取 + provider 状态刷新
    "_get_pipeline_params", "_refresh_provider_status",
    # 进度卡 / 预览问题卡刷新
    "_update_pipeline_stage", "_finalize_pipeline_stage", "_render_preview_issues",
    # 手动精剪按钮回调
    "_on_manual_edit_clicked",
    # 流式 chunk 缓存
    "_on_edit_agent_chunk",
    # Plan 模式 UI：展示/确认/取消
    "_show_agent_plan", "_confirm_agent_plan", "_cancel_agent_plan",
    # 反馈/终止/完成回调（纯 UI 状态）
    "_on_agent_feedback", "_on_edit_agent_stopped", "_on_edit_agent_finished",
    # 全链路事件处理（UI 刷新）
    "_on_pipeline_event", "_handle_video_generation_done",
    "_handle_waiting_preview", "_handle_pipeline_progress",
    "_reset_pipeline_button", "_on_full_pipeline_done",
}

src = EDITOR.read_text(encoding='utf-8')
lines = src.splitlines(keepends=True)
tree = ast.parse(src)

methods_to_extract = []   # (start, end, name, source)
class_attr_blocks = []     # (start, end, name, source)  —— 仅 _PIPELINE_STAGES
for node in ast.walk(tree):
    if not (isinstance(node, ast.ClassDef) and node.name == 'EditorModule'):
        continue
    for m in node.body:
        if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef)) and m.name in CANDIDATES:
            start = m.lineno
            if m.decorator_list:
                start = min(d.lineno for d in m.decorator_list)
            while start > 1 and lines[start - 2].strip().startswith('@'):
                start -= 1
            end = getattr(m, 'end_lineno', m.lineno)
            methods_to_extract.append((start, end, m.name, ''.join(lines[start - 1:end])))
        elif isinstance(m, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == '_PIPELINE_STAGES' for t in m.targets
        ):
            start = m.lineno
            # 带上紧邻前置注释（`# Agent 全链路 6+ 主阶段映射...`）
            if start > 1 and lines[start - 2].strip().startswith('#'):
                start -= 1
            end = getattr(m, 'end_lineno', m.lineno)
            class_attr_blocks.append((start, end, '_PIPELINE_STAGES', ''.join(lines[start - 1:end])))
    break

methods_to_extract.sort(key=lambda x: x[0])
class_attr_blocks.sort(key=lambda x: x[0])

total_lines = sum(e - s + 1 for s, e, n, _ in methods_to_extract + class_attr_blocks)
print(f"找到 {len(methods_to_extract)} 个方法 + {len(class_attr_blocks)} 个类属性, 合计 {total_lines} 行")
for s, e, n, _ in class_attr_blocks:
    print(f"  [attr] {n:<38} {s:>6}-{e:<6}")
for s, e, n, _ in methods_to_extract:
    print(f"  {n:<40} {s:>6}-{e:<6}")

# ── 1. 从 editor_module.py 删除并从后往前替换为标记注释 ──
all_blocks = class_attr_blocks + methods_to_extract
all_blocks.sort(key=lambda x: x[0])

new_editor_lines = list(lines)
for s, e, n, _ in reversed(all_blocks):
    start_idx = s - 1
    end_idx = e
    del new_editor_lines[start_idx:end_idx]
    tag = '已迁移至 editor_agent_runtime_mixin.py'
    if n == '_PIPELINE_STAGES':
        new_editor_lines.insert(start_idx, f'    # [Mixin] _PIPELINE_STAGES {tag}\n')
    else:
        new_editor_lines.insert(start_idx, f'    # [Mixin] {n} {tag}\n')

editor_new_src = ''.join(new_editor_lines)
EDITOR.write_text(editor_new_src, encoding='utf-8')
print(f"editor_module.py: {len(editor_new_src.splitlines())} 行 (减少 {len(lines) - len(editor_new_src.splitlines())})")

# ── 2. 追加到既有 Mixin ──
mixin_src = MIXIN.read_text(encoding='utf-8')

# 2a. 补充 import：os、QListWidgetItem（_render_preview_issues 需要）
if '\nimport os\n' not in mixin_src and '\nimport os' not in mixin_src:
    mixin_src = mixin_src.replace(
        'import logging\n',
        'import logging\nimport os\n',
        1,
    )
    print("已补充 import os")
if 'QListWidgetItem' not in mixin_src:
    mixin_src = mixin_src.replace(
        '    QProgressBar, QMessageBox,\n',
        '    QProgressBar, QMessageBox, QListWidgetItem,\n',
        1,
    )
    print("已补充 QListWidgetItem")

# 2b. 更新 docstring 方法计数（18 → 18 + 本次）
old_count_line = '迁移的方法（共 18 个, 约 306 行）。'
if old_count_line in mixin_src:
    new_total = 18 + len(methods_to_extract)
    new_count_line = f'迁移的方法（共 {new_total} 个, 约 {306 + total_lines} 行，含阶段映射常量 _PIPELINE_STAGES）。'
    mixin_src = mixin_src.replace(old_count_line, new_count_line, 1)
    print("已更新 docstring 方法计数")

# 2c. 追加类属性 + 方法体（保持 4 空格缩进）
append_blocks = []
append_blocks.append('\n    # ───────────────── 阶段 1.3 追加：面板运行时任务控制 ─────────────────\n')
for s, e, n, block_src in all_blocks:
    if n == '_PIPELINE_STAGES':
        append_blocks.append(block_src)
        append_blocks.append('\n')
    else:
        append_blocks.append(f'    # 抽取自 editor_module.py L{s}-{e}\n')
        append_blocks.append(block_src)
        append_blocks.append('\n')

# 确保文件以一个空行结尾后追加
if not mixin_src.endswith('\n'):
    mixin_src += '\n'
mixin_src += ''.join(append_blocks)

MIXIN.write_text(mixin_src, encoding='utf-8')
print(f"editor_agent_runtime_mixin.py: {len(mixin_src.splitlines())} 行")