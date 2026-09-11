"""
第三批 Mixin 抽取脚本:UI 创建方法
======================================
将 UI 创建方法从 editor_module.py 抽出到 editor_ui_builder_mixin.py
"""
import ast
import re
from pathlib import Path

EDITOR = Path(r'd:\拾光剪影\app\modules\lego\editor_module.py')
NEW_MIXIN = Path(r'd:\拾光剪影\app\modules\lego\editor_ui_builder_mixin.py')

CANDIDATES = {
    "_create_toolbar",
    "_create_preview_panel",
    "_create_tools_panel",
    "_create_left_panel",
    "_make_effect_tab",
    "_make_sticker_tab",
    "_create_timeline_panel",
    "_create_params_tab",
    "_create_character_tab",
    "_refresh_character_panel",
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
                method_src = ''.join(lines[start - 1:end])
                methods_to_extract.append((start, end, m.name, method_src))
        break

methods_to_extract.sort(key=lambda x: x[0])

print(f"找到 {len(methods_to_extract)} 个方法:")
total_lines = 0
for s, e, n, _ in methods_to_extract:
    print(f"  {n:<40} {s:>6}-{e:<6} ({e - s + 1} 行)")
    total_lines += e - s + 1
print(f"总行数: {total_lines}")

mixin_doc = f'''"""
editor_ui_builder_mixin.py
============================
EditorUiBuilderMixin: 从 editor_module.py 抽出的 UI 创建方法。

设计目标（遵循 .trae/rules/2.md §三 架构分层）:
- **最小侵入**: 方法体完全照搬, self 访问不变
- **零回归风险**: 方法签名/实现不变, 只是文件位置改变
- **单一职责**: 本 Mixin 承载 UI 面板创建(工具栏/预览/工具/左侧/特效/贴纸/时间线/参数/角色)
- **不独立实例化**: Mixin 模式, 必须混入宿主类使用

迁移的方法（共 {len(methods_to_extract)} 个, 约 {total_lines} 行）:
'''
for i, (s, e, n, _) in enumerate(methods_to_extract, 1):
    mixin_doc += f"{i}. {n} (原 L{s}-{e}, {e-s+1} 行)\n"
mixin_doc += '''
使用方式:
    class EditorModule(..., EditorUiBuilderMixin):
        ...
"""

from typing import Dict, Any, Optional, List
import os
import json
import logging
import subprocess
import threading

from PyQt6.QtCore import Qt, QTimer, QUrl, QEvent, QSize, QPoint
from PyQt6.QtGui import QFont, QAction, QColor, QPainter, QPen, QBrush, QFontMetrics, QShortcut, QKeySequence, QDrag, QPixmap, QImage
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFrame, QScrollArea, QGridLayout, QProgressBar, QListWidget,
    QListWidgetItem, QTextEdit, QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox,
    QGroupBox, QSplitter, QTableWidget, QTableWidgetItem, QHeaderView,
    QFileDialog, QMessageBox, QInputDialog, QTabWidget, QCheckBox, QSlider,
    QTreeWidget, QTreeWidgetItem, QMenu, QToolButton, QApplication, QSizePolicy,
    QFormLayout, QSpacerItem, QToolTip, QStackedLayout
)

logger = logging.getLogger("AI短剧编辑器.editor")


class EditorUiBuilderMixin:
    """UI 创建 Mixin。

    本 Mixin 从 editor_module.py 抽出, 承载编辑器各 UI 面板的创建方法。
    """

'''

new_lines = [mixin_doc]
for s, e, n, method_src in methods_to_extract:
    new_lines.append('    # ' + '=' * 70 + '\n')
    new_lines.append(f'    # 抽取自 editor_module.py L{s}-{e}\n')
    new_lines.append('    # ' + '=' * 70 + '\n')
    new_lines.append(method_src)
    new_lines.append('\n')

new_content = ''.join(new_lines)
NEW_MIXIN.write_text(new_content, encoding='utf-8')
print(f"\n新文件已写入: {NEW_MIXIN}")
print(f"新文件行数: {len(new_content.splitlines())}")

# 从 editor_module.py 删除方法
delete_ranges = []
for s, e, n, _ in reversed(methods_to_extract):
    end_extend = e
    while end_extend < len(lines) and lines[end_extend].strip() == '':
        end_extend += 1
    delete_ranges.append((s - 1, end_extend))

new_lines_editor = list(lines)
for start_idx, end_idx in delete_ranges:
    del new_lines_editor[start_idx:end_idx]
    new_lines_editor.insert(start_idx, f'    # [Mixin] 已迁移至 editor_ui_builder_mixin.py\n')

editor_new_src = ''.join(new_lines_editor)
old_inherit = 'class EditorModule(BaseModule, AiAgentPanelMixin, EditorExportPanelMixin, EditorAgentPanelMixin, EditorEffectsMixin):'
new_inherit = 'class EditorModule(BaseModule, AiAgentPanelMixin, EditorExportPanelMixin, EditorAgentPanelMixin, EditorEffectsMixin, EditorUiBuilderMixin):'
if old_inherit in editor_new_src:
    editor_new_src = editor_new_src.replace(old_inherit, new_inherit, 1)
    print("已更新继承列表")
else:
    pattern = r'class EditorModule\([^)]*\):'
    match = re.search(pattern, editor_new_src)
    if match:
        old_line = match.group(0)
        new_line = old_line[:-2] + ', EditorUiBuilderMixin):'
        editor_new_src = editor_new_src.replace(old_line, new_line, 1)
        print(f"已更新继承列表(变体)")

import_line = 'from .editor_ui_builder_mixin import EditorUiBuilderMixin'
if import_line not in editor_new_src:
    pattern = r'(from \.editor_\w+ import [^\n]+\n)'
    matches = list(re.finditer(pattern, editor_new_src))
    if matches:
        last_match = matches[-1]
        insert_pos = last_match.end()
        editor_new_src = editor_new_src[:insert_pos] + import_line + '\n' + editor_new_src[insert_pos:]
        print(f"已加入 import: {import_line}")

EDITOR.write_text(editor_new_src, encoding='utf-8')
print(f"\neditor_module.py 已更新")
print(f"新行数: {len(editor_new_src.splitlines())}")
print(f"减少: {len(lines) - len(editor_new_src.splitlines())} 行")
