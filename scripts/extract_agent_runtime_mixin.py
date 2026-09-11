"""第六批 Mixin 抽取: Agent 面板运行时 UI 与任务控制方法（纯 UI/编排，无 _clips 写操作）。"""
import ast
from pathlib import Path

EDITOR = Path(r'd:\拾光剪影\app\modules\lego\editor_module.py')
NEW_MIXIN = Path(r'd:\拾光剪影\app\modules\lego\editor_agent_runtime_mixin.py')

# Agent 面板运行时 UI + 任务控制（逐一确认无直接 self._clips 写操作、无冻结区符号）
CANDIDATES = {
    # 面板 UI 控制
    "_toggle_edit_agent_panel", "_close_agent_tab", "_position_edit_agent_panel",
    # 上下文持久化
    "_load_agent_project_context_fields", "_save_agent_project_context",
    "_persist_agent_project_context_silent", "_append_agent_message",
    "_refresh_agent_brain_status",
    # UI 卡片构建
    "_build_agent_progress_card", "_build_agent_preview_card",
    # 任务控制按钮回调
    "_fill_edit_agent_prompt", "_pause_edit_agent_task", "_resume_edit_agent_task",
    "_replan_edit_agent_task", "_stop_edit_agent_message",
    "_get_selected_edit_agent_model", "_is_agent_plan_mode", "_get_agent_session_mode",
}

src = EDITOR.read_text(encoding='utf-8')
lines = src.splitlines(keepends=True)
tree = ast.parse(src)

methods_to_extract = []
for node in ast.walk(tree):
    if isinstance(node, ast.ClassDef) and node.name == 'EditorModule':
        for m in node.body:
            if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef)) and m.name in CANDIDATES:
                start = m.lineno
                if m.decorator_list:
                    start = min(d.lineno for d in m.decorator_list)
                while start > 1 and lines[start - 2].strip().startswith('@'):
                    start -= 1
                end = getattr(m, 'end_lineno', m.lineno)
                methods_to_extract.append((start, end, m.name, ''.join(lines[start - 1:end])))
        break

methods_to_extract.sort(key=lambda x: x[0])
total_lines = sum(e - s + 1 for s, e, n, _ in methods_to_extract)
print(f"找到 {len(methods_to_extract)} 个方法, 总 {total_lines} 行")
for s, e, n, _ in methods_to_extract:
    print(f"  {n:<40} {s:>6}-{e:<6}")

mixin_doc = f'''# -*- coding: utf-8 -*-
"""editor_agent_runtime_mixin.py
============================
EditorAgentRuntimeMixin: 从 editor_module.py 抽出的「Agent 面板运行时 UI + 任务控制」方法。

承载: Agent 标签页切换/定位、多集上下文持久化、进度卡/预览卡构建、
大脑状态刷新、消息追加、任务暂停/恢复/重规划/停止、模型/模式读取。
均为纯 UI/编排/持久化回调，不直接写 `_clips` 核心状态机，不触碰
playback-av / canvas-transform / clip-transform 冻结区。

与 EditorAgentPanelMixin 的区别：后者承载 Agent 面板构建与 pipeline 编排，
本 Mixin 承载面板发布后的运行时交互与任务启停控制。

迁移的方法（共 {len(methods_to_extract)} 个, 约 {total_lines} 行）。
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from PyQt6.QtCore import QPoint, QTimer, Qt
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame, QListWidget,
    QProgressBar, QMessageBox,
)

logger = logging.getLogger("AI短剧编辑器.editor")


class EditorAgentRuntimeMixin:
    """Agent 面板运行时 UI 与任务控制 Mixin。"""

'''

new_lines = [mixin_doc]
for s, e, n, method_src in methods_to_extract:
    new_lines.append(f'    # 抽取自 editor_module.py L{s}-{e}\n')
    new_lines.append(method_src)
    new_lines.append('\n')

NEW_MIXIN.write_text(''.join(new_lines), encoding='utf-8')
print(f"\n新文件: {NEW_MIXIN} ({len(''.join(new_lines).splitlines())} 行)")

# 删除原方法（从后往前，避免行号偏移）
new_lines_editor = list(lines)
for s, e, n, _ in reversed(methods_to_extract):
    start_idx = s - 1  # 0-based
    end_idx = e        # 0-based exclusive
    del new_lines_editor[start_idx:end_idx]
    new_lines_editor.insert(start_idx, '    # [Mixin] 已迁移至 editor_agent_runtime_mixin.py\n')

editor_new_src = ''.join(new_lines_editor)

# ---- 更新继承列表（精确字符串匹配）----
old_class = 'class EditorModule(BaseModule, AiAgentPanelMixin, EditorExportPanelMixin, EditorAgentPanelMixin, EditorEffectsMixin, EditorUiBuilderMixin, EditorAiProcessMixin, EditorAiToolsMixin):'
new_class = 'class EditorModule(BaseModule, AiAgentPanelMixin, EditorExportPanelMixin, EditorAgentPanelMixin, EditorEffectsMixin, EditorUiBuilderMixin, EditorAiProcessMixin, EditorAiToolsMixin, EditorAgentRuntimeMixin):'
if old_class in editor_new_src:
    editor_new_src = editor_new_src.replace(old_class, new_class, 1)
    print("已更新继承列表")
else:
    print("!! 继承列表字符串未匹配，需手动处理")

# ---- 插入 import（精确锚点）----
import_line = 'from .editor_agent_runtime_mixin import EditorAgentRuntimeMixin\n'
anchor = 'from .editor_ai_tools_mixin import EditorAiToolsMixin\n'
if import_line in editor_new_src:
    print("import 已存在")
elif anchor in editor_new_src:
    editor_new_src = editor_new_src.replace(anchor, anchor + import_line, 1)
    print("已插入 import")
else:
    print("!! 未找到 import 锚点，需手动处理")

EDITOR.write_text(editor_new_src, encoding='utf-8')
print(f"editor_module.py: {len(editor_new_src.splitlines())} 行 (减少 {len(lines) - len(editor_new_src.splitlines())})")