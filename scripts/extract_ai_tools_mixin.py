"""第五批 Mixin 抽取: AI 工具按钮回调方法（纯按钮回调，无 _clips 写操作）。"""
import ast
from pathlib import Path

EDITOR = Path(r'd:\拾光剪影\app\modules\lego\editor_module.py')
NEW_MIXIN = Path(r'd:\拾光剪影\app\modules\lego\editor_ai_tools_mixin.py')

# 纯 AI 工具按钮回调（逐一确认无直接 self._clips 写操作、无冻结区符号）
CANDIDATES = {
    "_ensure_viral_engine", "_ensure_ai_clip_algorithm",
    "_generate_ai_subtitles", "_emit_ai_progress", "_emit_ai_fail",
    "connect_to_data_analyzer", "get_recommendations", "record_edit_action",
    "enhance_with_ai", "smart_cut_with_ai",
    "_bind_character_row_events", "_write_character_pref",
    "_create_ai_tools_tab", "_record_ai_tool_history",
    "_refresh_ollama_diagnose_ui", "_show_ollama_diagnose_detail",
    "_apply_manju_portrait_preset", "_apply_landscape_preset",
    "_build_agent_score_card", "_render_score_results",
    "_on_copy_script_clicked", "_on_export_script_clicked",
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
                # 处理函数上面可能存在的装饰器（本批无装饰器，但保留逻辑）
                while start > 1 and lines[start - 2].strip().startswith('@'):
                    start -= 1
                end = getattr(m, 'end_lineno', m.lineno)
                methods_to_extract.append((start, end, m.name, ''.join(lines[start - 1:end])))
        break

methods_to_extract.sort(key=lambda x: x[0])
total_lines = sum(e - s + 1 for s, e, n, _ in methods_to_extract)
print(f"找到 {len(methods_to_extract)} 个方法, 总 {total_lines} 行")
for s, e, n, _ in methods_to_extract:
    print(f"  {n:<36} {s:>6}-{e:<6}")

mixin_doc = f'''# -*- coding: utf-8 -*-
"""editor_ai_tools_mixin.py
============================
EditorAiToolsMixin: 从 editor_module.py 抽出的「纯 AI 工具按钮回调」方法。

承载: AI 生成/增强入口、AI 进度信号、数据闭环、角色偏好、Ollama 诊断、
漫剧/横屏导出预设、五维打分展示、剪辑脚本导入导出。
均为独立按钮回调或轻量辅助，不直接写 `_clips` 核心状态机，不触碰
playback-av / canvas-transform / clip-transform 冻结区。

迁移的方法（共 {len(methods_to_extract)} 个, 约 {total_lines} 行）。
"""
from __future__ import annotations

import logging
import os
from datetime import datetime
from typing import Any, Dict, List, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame,
    QListWidget, QListWidgetItem, QCheckBox, QFileDialog, QMessageBox,
    QApplication,
)

# 爆款优化引擎（懒加载，失败降级，与 editor_module 顶部逻辑保持一致）
try:
    from .viral_optimization_engine import ViralOptimizationEngine, Platform, VideoFeatures
    VIRAL_ENGINE_AVAILABLE = True
except ImportError as e:
    ViralOptimizationEngine = None  # type: ignore
    Platform = VideoFeatures = None  # type: ignore
    VIRAL_ENGINE_AVAILABLE = False

logger = logging.getLogger("AI短剧编辑器.editor")


def _clear_msgbox(title: str, message: str, parent=None):
    """延迟导入 modules.show_clear_messagebox 后调用，避免循环导入。"""
    from .modules import show_clear_messagebox
    return show_clear_messagebox(title, message, parent)


class EditorAiToolsMixin:
    """AI 工具按钮回调 Mixin: 承载 AI 生成/增强/数据闭环/角色/诊断/打分/脚本。"""

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
    new_lines_editor.insert(start_idx, '    # [Mixin] 已迁移至 editor_ai_tools_mixin.py\n')

editor_new_src = ''.join(new_lines_editor)

# ---- 更新继承列表 ----
old_class = 'class EditorModule(BaseModule, AiAgentPanelMixin, EditorExportPanelMixin, EditorAgentPanelMixin, EditorEffectsMixin, EditorUiBuilderMixin, EditorAiProcessMixin):'
new_class = 'class EditorModule(BaseModule, AiAgentPanelMixin, EditorExportPanelMixin, EditorAgentPanelMixin, EditorEffectsMixin, EditorUiBuilderMixin, EditorAiProcessMixin, EditorAiToolsMixin):'
if old_class in editor_new_src:
    editor_new_src = editor_new_src.replace(old_class, new_class, 1)
    print("已更新继承列表")
else:
    print("!! 继承列表字符串未匹配，需手动处理")

# ---- 插入 import（精确匹配现有行，避免阶段1.1误匹配docstring的坑）----
import_line = 'from .editor_ai_tools_mixin import EditorAiToolsMixin\n'
anchor = 'from .editor_ai_process_mixin import EditorAiProcessMixin\n'
if import_line in editor_new_src:
    print("import 已存在")
elif anchor in editor_new_src:
    editor_new_src = editor_new_src.replace(anchor, anchor + import_line, 1)
    print("已插入 import")
else:
    print("!! 未找到 import 锚点，需手动处理")

EDITOR.write_text(editor_new_src, encoding='utf-8')
print(f"editor_module.py: {len(editor_new_src.splitlines())} 行 (减少 {len(lines) - len(editor_new_src.splitlines())})")