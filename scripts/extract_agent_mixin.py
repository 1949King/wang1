"""
editor_module.py Mixin 抽取脚本
================================
将 17 个 Agent 面板/编排方法从 editor_module.py 抽出到 editor_agent_panel_mixin.py

安全策略:
1. 基于 AST 精确行号抽取,不修改方法体
2. 保留装饰器
3. 新文件复制原文件顶部 import 块,确保依赖完整
4. 从原文件删除方法时,从后往前删除避免行号偏移
5. 删除后保留方法间空行,保持类结构完整
6. 更新 EditorModule 继承列表

执行后必须验证:
- python -m compileall app/modules/lego/editor_agent_panel_mixin.py
- python -m compileall app/modules/lego/editor_module.py
- python scripts/frozen_zone_guard.py
- python -c "import app.main_qt6"
"""
import ast
import re
from pathlib import Path

EDITOR = Path(r'd:\拾光剪影\app\modules\lego\editor_module.py')
NEW_MIXIN = Path(r'd:\拾光剪影\app\modules\lego\editor_agent_panel_mixin.py')

# 候选方法名(全部不触及冻结符号)
CANDIDATES = {
    "_create_edit_agent_panel",
    "_refresh_edit_agent_models",
    "_build_agent_config_card",
    "_build_agent_script_card",
    "_render_editing_script",
    "_send_edit_agent_message",
    "_build_edit_agent_messages",
    "_get_agent_extensions_context",
    "_get_agent_timeline_context",
    "agent_suggest_canvas_roundtrip",
    "agent_suggest_cleanup",
    "_handle_pipeline_done",
    "_agent_call_extension",
    "_on_run_full_pipeline",
    "_execute_pipeline_editing",
    "_apply_single_clip_ffmpeg",
    "_apply_multi_clip_ffmpeg",
}

src = EDITOR.read_text(encoding='utf-8')
lines = src.splitlines(keepends=True)
tree = ast.parse(src)

# 1. 找出 EditorModule 类中候选方法的位置(含装饰器)
methods_to_extract = []  # [(start_line, end_line, name, source_text)]
for node in ast.walk(tree):
    if isinstance(node, ast.ClassDef) and node.name == 'EditorModule':
        for m in node.body:
            if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef)) and m.name in CANDIDATES:
                start = m.lineno
                # 包含装饰器
                if m.decorator_list:
                    start = min(d.lineno for d in m.decorator_list)
                # 向上扩展装饰器前导注释(如果有 @ 符号开头的行)
                while start > 1 and lines[start - 2].strip().startswith('@'):
                    start -= 1
                end = getattr(m, 'end_lineno', m.lineno)
                method_src = ''.join(lines[start - 1:end])
                methods_to_extract.append((start, end, m.name, method_src))
        break

# 按起始行排序
methods_to_extract.sort(key=lambda x: x[0])

print(f"找到 {len(methods_to_extract)} 个方法:")
total_lines = 0
for s, e, n, _ in methods_to_extract:
    print(f"  {n:<40} {s:>6}-{e:<6} ({e - s + 1} 行)")
    total_lines += e - s + 1
print(f"总行数: {total_lines}")

# 2. 找出 editor_module.py 顶部 import 块(到 EditorModule 类定义前)
# 通常是: 文档字符串 -> import -> 全局常量 -> class EditorModule
# 我们需要找出第一个 class 定义前的所有内容
import_block = []
in_imports = True
class_editor_line = None
for i, line in enumerate(lines):
    stripped = line.strip()
    # 跳过空行和注释
    if not stripped or stripped.startswith('#'):
        if in_imports:
            import_block.append(line)
        continue
    # 检测 class 定义
    if stripped.startswith('class ') or stripped.startswith('def '):
        if 'class EditorModule' in stripped:
            class_editor_line = i + 1  # 1-indexed
            break
        in_imports = False
    # 检测 import 语句
    if stripped.startswith('import ') or stripped.startswith('from '):
        if in_imports:
            import_block.append(line)
        continue
    # 检测 try-except import 块
    if stripped.startswith('try:') or stripped.startswith('except'):
        if in_imports:
            import_block.append(line)
        continue
    # 赋值语句(常量定义)
    if re.match(r'^[A-Z_][A-Z_0-9]*\s*=', stripped) or re.match(r'^_[a-z][a-z_0-9]*\s*=', stripped):
        if in_imports:
            import_block.append(line)
        continue
    # 其他
    if in_imports:
        in_imports = False

print(f"\nimport 块行数: {len(import_block)}")
print(f"EditorModule 类定义行: {class_editor_line}")

# 3. 构建新 Mixin 文件内容
mixin_doc = '''"""
editor_agent_panel_mixin.py
============================
EditorAgentPanelMixin: 从 editor_module.py 抽出的 Agent 面板 UI 与编排方法。

设计目标（遵循 .trae/rules/2.md §三 架构分层）:
- **最小侵入**: 方法体完全照搬, self 访问不变, 符合 §二.3 不破坏原有功能
- **零回归风险**: 方法签名/实现不变, 只是文件位置改变
- **单一职责**: 本 Mixin 承载 Agent 面板创建、模型刷新、消息构建、流水线编排
- **不独立实例化**: Mixin 模式, 必须混入宿主类使用

迁移的方法（共 ''' + str(len(methods_to_extract)) + ''' 个, 约 ''' + str(total_lines) + ''' 行）:
'''
for i, (s, e, n, _) in enumerate(methods_to_extract, 1):
    mixin_doc += f"{i}. {n} (原 L{s}-{e}, {e-s+1} 行)\n"
mixin_doc += '''
使用方式:
    class EditorModule(BaseModule, AiAgentPanelMixin, EditorExportPanelMixin, EditorAgentPanelMixin):
        ...

迁移后 EditorModule 实例通过 self 访问这些方法, MRO 解析到本 Mixin。
所有 self.xxx 属性访问由 EditorModule.__init__ 提供, 不会断裂。
"""

'''

# 组装新文件: 文档字符串 + import 块 + 类定义 + 方法
new_lines = []
new_lines.append(mixin_doc)
# 复制 import 块(过滤掉文档字符串和与 Mixin 无关的内容)
# 实际上, 直接复制整个文件头到 class 定义前的内容是最安全的
# 但需要过滤掉原来的文件级文档字符串(三引号开头)
in_docstring = False
docstring_count = 0
for line in import_block:
    stripped = line.strip()
    # 跳过文件级文档字符串
    if stripped.startswith('"""') and not in_docstring and docstring_count == 0:
        in_docstring = True
        docstring_count += 1
        if stripped.count('"""') >= 2:
            in_docstring = False
        continue
    if in_docstring:
        if '"""' in stripped:
            in_docstring = False
        continue
    new_lines.append(line)

# 确保有 logger
new_lines.append('\n')
new_lines.append('logger = logging.getLogger("AI短剧编辑器.editor")\n')
new_lines.append('\n\n')

# 类定义
new_lines.append('class EditorAgentPanelMixin:\n')
new_lines.append('    """编辑 Agent 面板与流水线编排 Mixin。\n\n')
new_lines.append('    本 Mixin 从 editor_module.py 抽出, 承载 Agent 面板创建、模型刷新、\n')
new_lines.append('    消息构建、上下文获取、流水线编排、FFmpeg 应用等方法。被 EditorModule\n')
new_lines.append('    继承后, 通过 self 访问 EditorModule 的所有属性和其他方法。\n')
new_lines.append('    """\n\n')

# 方法体(缩进4空格)
for s, e, n, method_src in methods_to_extract:
    new_lines.append('    # ' + '=' * 70 + '\n')
    new_lines.append(f'    # 抽取自 editor_module.py L{s}-{e}\n')
    new_lines.append('    # ' + '=' * 70 + '\n')
    # 方法体已经是 4 空格缩进(class 内方法), 直接附加
    new_lines.append(method_src)
    new_lines.append('\n')

new_content = ''.join(new_lines)

# 4. 写入新文件
NEW_MIXIN.write_text(new_content, encoding='utf-8')
print(f"\n新文件已写入: {NEW_MIXIN}")
print(f"新文件行数: {len(new_content.splitlines())}")

# 5. 从 editor_module.py 中删除这些方法(从后往前删除)
# 创建删除区间列表(包含方法间的空行)
# 策略: 对每个方法, 删除 [start-1, end] 行, 但保留方法后的空行(如果有)
# 实际上, 直接删除 [start, end+1] (包含方法后空行), 然后在删除点插入一个空行保持间距
delete_ranges = []  # [(start_0indexed, end_0indexed_exclusive)]
for s, e, n, _ in reversed(methods_to_extract):
    # 0-indexed: start-1 到 e (包含)
    # 扩展到包含方法后的空行
    end_extend = e
    while end_extend < len(lines) and lines[end_extend].strip() == '':
        end_extend += 1
    delete_ranges.append((s - 1, end_extend))

# 从后往前删除
new_lines_editor = list(lines)
for start_idx, end_idx in delete_ranges:
    # 保留一个空行作为方法间分隔
    del new_lines_editor[start_idx:end_idx]
    # 插入一个占位注释 + 空行
    new_lines_editor.insert(start_idx, f'    # [Mixin] {n} 已迁移至 editor_agent_panel_mixin.py\n')

# 6. 更新 EditorModule 继承列表
# 找到 class EditorModule 定义行, 加入 EditorAgentPanelMixin
editor_new_src = ''.join(new_lines_editor)
# 替换继承列表
old_inherit = 'class EditorModule(BaseModule, AiAgentPanelMixin, EditorExportPanelMixin):'
new_inherit = 'class EditorModule(BaseModule, AiAgentPanelMixin, EditorExportPanelMixin, EditorAgentPanelMixin):'
if old_inherit in editor_new_src:
    editor_new_src = editor_new_src.replace(old_inherit, new_inherit, 1)
    print("已更新 EditorModule 继承列表")
else:
    # 尝试其他变体
    pattern = r'class EditorModule\([^)]*\):'
    match = re.search(pattern, editor_new_src)
    if match:
        old_line = match.group(0)
        # 在最后一个 ) 前加入 EditorAgentPanelMixin
        new_line = old_line[:-2] + ', EditorAgentPanelMixin):'
        editor_new_src = editor_new_src.replace(old_line, new_line, 1)
        print(f"已更新继承列表(变体): {old_line} -> {new_line}")
    else:
        print("警告: 未找到 EditorModule 类定义, 请手动更新继承列表")

# 7. 写回 editor_module.py
EDITOR.write_text(editor_new_src, encoding='utf-8')
print(f"\neditor_module.py 已更新")
print(f"原行数: {len(lines)}")
print(f"新行数: {len(editor_new_src.splitlines())}")
print(f"减少: {len(lines) - len(editor_new_src.splitlines())} 行")

# 8. 在 editor_module.py 顶部 import 区加入新 Mixin 的 import
# 找到 from .editor_subtitle_panel import 或类似行, 在其后加入
import_line = 'from .editor_agent_panel_mixin import EditorAgentPanelMixin'
if import_line not in editor_new_src:
    # 找一个合适的插入点(其他 editor_*_panel import 之后)
    pattern = r'(from \.editor_\w+_panel import [^\n]+\n)'
    matches = list(re.finditer(pattern, editor_new_src))
    if matches:
        last_match = matches[-1]
        insert_pos = last_match.end()
        editor_new_src = editor_new_src[:insert_pos] + import_line + '\n' + editor_new_src[insert_pos:]
        EDITOR.write_text(editor_new_src, encoding='utf-8')
        print(f"已在 editor_module.py 中加入 import: {import_line}")
    else:
        print("警告: 未找到 editor_*_panel import, 请手动加入")
else:
    print("import 已存在, 跳过")

print("\n抽取完成, 请验证:")
print("1. python -m compileall app/modules/lego/editor_agent_panel_mixin.py")
print("2. python -m compileall app/modules/lego/editor_module.py")
print("3. python scripts/frozen_zone_guard.py")
print("4. python -c \"import app.main_qt6; print('OK')\"")
