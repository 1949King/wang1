"""第四批 Mixin 抽取: AI 处理方法"""
import ast, re
from pathlib import Path

EDITOR = Path(r'd:\拾光剪影\app\modules\lego\editor_module.py')
NEW_MIXIN = Path(r'd:\拾光剪影\app\modules\lego\editor_ai_process_mixin.py')

CANDIDATES = {
    "_run_ai_concat_after_picks", "_funclip_process", "_videofusion_process",
    "_autoclip_process", "_lora_edit_process", "_lossless_trim_selected",
    "_try_render_plugin_transition",
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

mixin_doc = f'''"""
editor_ai_process_mixin.py
============================
EditorAiProcessMixin: 从 editor_module.py 抽出的 AI 处理方法。

承载: AI 拼接/FunClip/VideoFusion/AutoClip/LoRA 编辑/无损裁剪/插件转场渲染。
迁移的方法（共 {len(methods_to_extract)} 个, 约 {total_lines} 行）。
"""

from typing import Dict, Any, Optional, List
import os, json, logging, subprocess, threading, time

from PyQt6.QtCore import Qt, QTimer, QUrl, QEvent
from PyQt6.QtGui import QFont, QAction, QColor, QPainter, QPen, QBrush
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


class EditorAiProcessMixin:
    """AI 处理 Mixin: 承载 AI 拼接/FunClip/VideoFusion/AutoClip/LoRA/无损裁剪/插件转场。"""

'''

new_lines = [mixin_doc]
for s, e, n, method_src in methods_to_extract:
    new_lines.append(f'    # 抽取自 editor_module.py L{s}-{e}\n')
    new_lines.append(method_src)
    new_lines.append('\n')

NEW_MIXIN.write_text(''.join(new_lines), encoding='utf-8')
print(f"\n新文件: {NEW_MIXIN} ({len(''.join(new_lines).splitlines())} 行)")

# 删除方法
delete_ranges = []
for s, e, n, _ in reversed(methods_to_extract):
    end_extend = e
    while end_extend < len(lines) and lines[end_extend].strip() == '':
        end_extend += 1
    delete_ranges.append((s - 1, end_extend))

new_lines_editor = list(lines)
for start_idx, end_idx in delete_ranges:
    del new_lines_editor[start_idx:end_idx]
    new_lines_editor.insert(start_idx, '    # [Mixin] 已迁移至 editor_ai_process_mixin.py\n')

editor_new_src = ''.join(new_lines_editor)
pattern = r'class EditorModule\([^)]*\):'
match = re.search(pattern, editor_new_src)
if match:
    old_line = match.group(0)
    new_line = old_line[:-2] + ', EditorAiProcessMixin):'
    editor_new_src = editor_new_src.replace(old_line, new_line, 1)
    print("已更新继承列表")

import_line = 'from .editor_ai_process_mixin import EditorAiProcessMixin'
if import_line not in editor_new_src:
    matches = list(re.finditer(r'(from \.editor_\w+ import [^\n]+\n)', editor_new_src))
    if matches:
        insert_pos = matches[-1].end()
        editor_new_src = editor_new_src[:insert_pos] + import_line + '\n' + editor_new_src[insert_pos:]
        print(f"已加入 import")

EDITOR.write_text(editor_new_src, encoding='utf-8')
print(f"editor_module.py: {len(editor_new_src.splitlines())} 行 (减少 {len(lines) - len(editor_new_src.splitlines())})")
