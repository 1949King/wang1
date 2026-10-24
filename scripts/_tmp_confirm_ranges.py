"""精确确认 editor_module.py 中候选抽出方法的行号范围"""
import ast
from pathlib import Path

src = Path(r'd:\拾光剪影\app\modules\lego\editor_module.py').read_text(encoding='utf-8')
lines = src.splitlines()
tree = ast.parse(src)

# 候选方法名(全部不触及冻结符号)
candidates = [
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
]

for node in ast.walk(tree):
    if isinstance(node, ast.ClassDef) and node.name == 'EditorModule':
        for m in node.body:
            if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef)) and m.name in candidates:
                # 检查装饰器,起始行需取 min(装饰器行, 方法行)
                start = m.lineno
                if m.decorator_list:
                    start = min(d.lineno for d in m.decorator_list)
                end = getattr(m, 'end_lineno', m.lineno)
                # 检查方法前一行是否是装饰器(注释行也算)
                # 向上扩展到包含装饰器的最小行
                while start > 1 and lines[start - 2].strip().startswith('@'):
                    start -= 1
                print(f"{m.name:<40} {start:>6}-{end:<6} ({end - start + 1} 行)")
                # 检查下一个非空行,确认方法边界
                if end + 1 <= len(lines):
                    next_line = lines[end].strip() if end < len(lines) else ""
                    if next_line and not next_line.startswith('def ') and not next_line.startswith('class ') and not next_line.startswith('@'):
                        print(f"  警告: 方法后第 1 行 = {next_line[:80]}")
        break
