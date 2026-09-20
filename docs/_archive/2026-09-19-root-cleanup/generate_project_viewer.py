"""
生成项目树查看器 (project_viewer.html)
=====================================
零脑方案: 跑一次脚本, 生成 1 个 HTML 文件, 双击打开就能浏览完整项目
"""
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(r"d:\本地磁盘(当前分区)(C)\Users\Administrator\Desktop\AI短剧编辑器2")
OUTPUT_HTML = Path(r"C:\Users\Administrator\Desktop\项目查看.html")

# 排除这些目录/文件, 不显示在树中
EXCLUDE = {
    "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache",
    ".git", "node_modules", "build", "dist",
    "venv", ".venv", ".venv312", "bmf_env", "packaging_env", "app/venv", "app/.venv",
    "libopenshot", "license", "thirdparty",
    "models", "app/models", "bgms", "stickers",
    "output", "app/output", "cache", ".cache", "app/cache",
    "app/bgms", "app/stickers",
    "app/temp", "app/短剧AI剪辑输出", "app/素材库", "app/运营数据", "app/logs", "app/openclow_data",
    "temp", "snapshots", "plugin_test_results", "plugin_certificates",
    "ff", ".vscode", ".codebuddy", ".qoder", ".claude", ".trae", ".writerHelper",
    "openshot-qt", "shotcut", "temp_ai_editor", "新建文件夹",
    "短剧AI剪辑输出", "素材库", "运营数据", "logs", "error_reports", "workflow_logs",
}

EXCLUDE_FILES = {".DS_Store", "Thumbs.db", "*.pyc", "*.pyo", "*.bak"}


def should_skip(name: str) -> bool:
    return name in EXCLUDE


def collect_tree(root: Path, prefix: str = "", max_depth: int = 6) -> list:
    """递归收集目录树, 返回 (depth, is_dir, name, size) 元组"""
    entries = []

    def walk(path: Path, depth: int):
        if depth > max_depth:
            return
        try:
            items = sorted(path.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
        except PermissionError:
            return
        for item in items:
            if should_skip(item.name):
                continue
            if item.is_dir():
                entries.append((depth, True, item.name + "/", 0))
                walk(item, depth + 1)
            else:
                try:
                    size = item.stat().st_size
                except OSError:
                    size = 0
                entries.append((depth, False, item.name, size))

    walk(root, 0)
    return entries


def fmt_size(n: int) -> str:
    if n < 1024:
        return f"{n}B"
    elif n < 1024 * 1024:
        return f"{n/1024:.1f}KB"
    else:
        return f"{n/1024/1024:.1f}MB"


def main():
    print(f"扫描项目: {PROJECT_ROOT}")
    entries = collect_tree(PROJECT_ROOT)
    total = len(entries)
    print(f"生成 HTML: {OUTPUT_HTML}")
    print(f"总条目: {total}")

    # 生成 HTML
    rows = []
    for depth, is_dir, name, size in entries:
        indent = "  " * depth
        icon = "📁" if is_dir else "📄"
        size_str = "" if is_dir else f" ({fmt_size(size)})"
        rows.append(
            f'<div class="row" style="padding-left: {depth*20}px">'
            f'<span class="icon">{icon}</span>'
            f'<span class="name">{indent}{name}</span>'
            f'<span class="size">{size_str}</span>'
            f'</div>'
        )

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<title>AI 短剧编辑器 - 项目文件查看</title>
<style>
  body {{
    font-family: 'Consolas', 'Microsoft YaHei', monospace;
    background: #1e1e1e;
    color: #d4d4d4;
    margin: 0;
    padding: 20px;
    font-size: 13px;
  }}
  h1 {{
    color: #4ec9b0;
    border-bottom: 2px solid #4ec9b0;
    padding-bottom: 10px;
  }}
  .info {{
    color: #858585;
    margin-bottom: 20px;
  }}
  .toolbar {{
    position: sticky;
    top: 0;
    background: #1e1e1e;
    padding: 10px 0;
    border-bottom: 1px solid #333;
    margin-bottom: 10px;
    z-index: 10;
  }}
  .toolbar input {{
    width: 300px;
    padding: 6px 10px;
    background: #252526;
    border: 1px solid #3e3e42;
    color: #d4d4d4;
    border-radius: 3px;
    font-size: 13px;
  }}
  .row {{
    padding: 2px 0;
    white-space: nowrap;
    transition: background 0.1s;
  }}
  .row:hover {{ background: #2a2d2e; }}
  .icon {{ margin-right: 6px; }}
  .name {{ color: #d4d4d4; }}
  .size {{ color: #858585; margin-left: 10px; font-size: 11px; }}
  .stats {{
    margin-top: 20px;
    padding: 10px;
    background: #252526;
    border-radius: 5px;
    color: #4ec9b0;
  }}
</style>
</head>
<body>
<h1>📂 AI 短剧编辑器 - 项目文件树</h1>
<div class="info">
  项目根: {PROJECT_ROOT}<br>
  生成时间: {Path(__file__).name} (实时扫描)<br>
  双击桌面 <code>AI短剧编辑器2_工作区</code> 文件夹进入资源管理器浏览
</div>
<div class="toolbar">
  <input type="text" id="filter" placeholder="🔍 过滤文件名..." onkeyup="filterTree()">
</div>
<div id="tree">
{''.join(rows)}
</div>
<div class="stats">
  📊 总条目: {total}<br>
  💡 提示: 在桌面双击 <code>AI短剧编辑器2_工作区</code> 联接文件夹, 用资源管理器浏览完整项目
</div>
<script>
function filterTree() {{
  const q = document.getElementById('filter').value.toLowerCase();
  document.querySelectorAll('.row').forEach(row => {{
    const name = row.querySelector('.name').textContent.toLowerCase();
    row.style.display = name.includes(q) || q === '' ? '' : 'none';
  }});
}}
</script>
</body>
</html>
"""
    OUTPUT_HTML.write_text(html, encoding='utf-8')
    print(f"✅ 生成完成: {OUTPUT_HTML}")
    print(f"   大小: {OUTPUT_HTML.stat().st_size / 1024:.1f} KB")
    print(f"   条目: {total}")


if __name__ == "__main__":
    main()
