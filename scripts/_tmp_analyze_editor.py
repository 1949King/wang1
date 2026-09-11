"""临时脚本：分析 editor_module.py 方法分布"""
import ast
from pathlib import Path

src = Path(r'd:\拾光剪影\app\modules\lego\editor_module.py').read_text(encoding='utf-8')
tree = ast.parse(src)

methods = []
for node in ast.walk(tree):
    if isinstance(node, ast.ClassDef) and node.name == 'EditorModule':
        for m in node.body:
            if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef)):
                end = getattr(m, 'end_lineno', m.lineno)
                methods.append((m.name, m.lineno, end, end - m.lineno + 1))

methods.sort(key=lambda x: -x[3])
print(f"共 {len(methods)} 个方法, 总行数: {sum(m[3] for m in methods)}")
print(f"{'方法名':<60} {'起':>8} {'行数':>6}")
for n, s, e, c in methods:
    print(f"{n[:60]:<60} {s:>8} {c:>6}")
