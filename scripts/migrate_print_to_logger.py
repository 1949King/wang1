"""
print() -> logger 迁移脚本（一次性工具）
=========================================
按项目硬约束（0.md/1.md：禁止裸 print，统一 logger）执行批量替换。

设计原则：
1. AST 静态分析，不破坏字符串字面量中的 "print" 文本
2. 自动在文件顶部补齐 logger 实例（按现有命名约定 AI短剧编辑器.xxx）
3. 跳过：tests/、__pycache__/、_archive/、__main__ 块、字符串内的 print
4. 默认级别：含异常信息 -> logger.error；普通 -> logger.info；警告语义 -> logger.warning
5. 保留：崩溃钩子 stdout 紧急输出、CLI 入口输出

使用：
    python scripts/migrate_print_to_logger.py --dry-run   # 仅预览
    python scripts/migrate_print_to_logger.py              # 执行
    python scripts/migrate_print_to_logger.py --dir app/core
    python scripts/migrate_print_to_logger.py --dir app/modules/lego
    python scripts/migrate_print_to_logger.py --dir app/plugins
    python scripts/migrate_print_to_logger.py --dir app/integrations

完成后归档至 scripts/_archive/。
"""

import ast
import io
import os
import re
import sys
import tokenize
from pathlib import Path
from typing import List, Optional, Tuple

# 项目根目录
PROJECT_ROOT = Path(__file__).resolve().parent.parent
APP_DIR = PROJECT_ROOT / "app"

# 跳过目录
SKIP_DIRS = {
    "__pycache__",
    "tests",
    "test",
    "_archive",
    "legacy",
    ".git",
    "build",
    "dist",
}

# 文件级跳过（3D 导演台相关、CLI 入口、崩溃钩子等）
SKIP_FILES = {
    # 崩溃钩子保留 stdout 输出
    "main_qt6.py",
    "simple_test.py",
    "run_c5_tests.py",
    "verify_c8_qt6.py",
    "cleanup_project.py",
    # 3D 导演台相关（本轮绕过）
    "canvas_bridge.py",
    "canvas_runtime.py",
    "canvas_agent_runtime.py",
    "editor_canvas_link.py",
    "project_agent_host.py",
    "character_management_module.py",
}


def is_in_main_block(node: ast.AST, source_lines: List[str]) -> bool:
    """判断节点是否位于 if __name__ == '__main__': 块内"""
    parent = getattr(node, "_parent", None)
    while parent is not None:
        if isinstance(parent, ast.If):
            test = parent.test
            if (isinstance(test, ast.Compare)
                and isinstance(test.left, ast.Name)
                and test.left.id == "__name__"):
                for cmp in test.comparators:
                    if isinstance(cmp, ast.Constant) and cmp.value == "__main__":
                        return True
        parent = getattr(parent, "_parent", None)
    return False


def infer_level(args: List[ast.expr]) -> str:
    """根据 print 参数推断 logger 级别"""
    args_text = " ".join(_safe_unparse(a) for a in args).lower()
    if any(kw in args_text for kw in ("error", "exception", "traceback", "失败", "错误", "异常")):
        return "error"
    if any(kw in args_text for kw in ("warn", "警告", "注意", "deprecat")):
        return "warning"
    if any(kw in args_text for kw in ("debug", "调试", "dbg")):
        return "debug"
    return "info"


def _safe_unparse(node: ast.expr) -> str:
    try:
        return ast.unparse(node)
    except Exception:
        return ""


def has_logger_instance(tree: ast.Module) -> Optional[Tuple[str, int]]:
    """检查文件中是否已存在 logger 实例定义，返回 (变量名, 行号) 用于复用"""
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if (isinstance(target, ast.Name)
                    and target.id == "logger"
                    and isinstance(node.value, (ast.Call, ast.Attribute))):
                    return ("logger", node.lineno)
    return None


def infer_logger_name(file_path: Path) -> str:
    """根据文件路径推断 logger 名（按项目约定 AI短剧编辑器.xxx）"""
    try:
        rel = file_path.relative_to(APP_DIR)
        parts = list(rel.parts)
        if parts and parts[-1] == "__init__.py":
            parts = parts[:-1]
        else:
            parts[-1] = parts[-1][:-3]  # 去掉 .py
        # 过滤空段
        parts = [p for p in parts if p and p != "__init__"]
        return "AI短剧编辑器." + ".".join(parts) if parts else "AI短剧编辑器"
    except Exception:
        return "AI短剧编辑器"


def add_parent_links(tree: ast.Module) -> None:
    """为 AST 节点添加 _parent 引用，便于向上查找"""
    for parent in ast.walk(tree):
        for child in ast.iter_child_nodes(parent):
            child._parent = parent


def transform_file(file_path: Path, dry_run: bool = False) -> Tuple[int, int, List[str]]:
    """
    转换单个文件
    返回：(替换数, 涉及 logger 新增数, 修改日志)
    """
    try:
        source = file_path.read_text(encoding="utf-8")
    except Exception as e:
        return (0, 0, [f"[skip] 读取失败 {file_path}: {e}"])

    try:
        tree = ast.parse(source, filename=str(file_path))
    except SyntaxError as e:
        return (0, 0, [f"[skip] 语法错误 {file_path}: {e}"])

    add_parent_links(tree)

    # 收集需要替换的 print 节点
    replacements = []  # [(lineno, col_offset, end_lineno, end_col_offset, new_text)]
    existing_logger = has_logger_instance(tree)

    # 找出所有顶层 import 块的结束位置，用于插入 logger
    imports_end_line = 0
    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            imports_end_line = max(imports_end_line, getattr(node, "end_lineno", node.lineno))

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        # 识别 print(...)
        func = node.func
        if not (isinstance(func, ast.Name) and func.id == "print"):
            continue

        # 跳过 __main__ 块
        if is_in_main_block(node, source.splitlines()):
            continue

        # 跳过字符串字面量中的 print（AST 已过滤，不会匹配字符串字面量）

        level = infer_level(node.args)
        args_unparsed = ", ".join(_safe_unparse(a) for a in node.args)

        # 构造替换文本
        if args_unparsed:
            new_text = f"logger.{level}({args_unparsed})"
        else:
            new_text = f"logger.{level}()"

        replacements.append({
            "lineno": node.lineno,
            "col_offset": node.col_offset,
            "end_lineno": getattr(node, "end_lineno", node.lineno),
            "end_col_offset": getattr(node, "end_col_offset", node.col_offset),
            "new_text": new_text,
        })

    if not replacements:
        return (0, 0, [])

    # 按 (lineno desc, col desc) 排序，从后往前替换避免坐标偏移
    replacements.sort(key=lambda r: (-r["lineno"], -r["col_offset"]))

    lines = source.splitlines(keepends=True)
    logger_added = 0
    log_lines = []

    # 执行替换
    for r in replacements:
        start_idx = r["lineno"] - 1
        end_idx = r["end_lineno"] - 1

        # 获取缩进
        original_line = lines[start_idx]
        indent_match = re.match(r"^(\s*)", original_line)
        indent = indent_match.group(1) if indent_match else ""

        # 多行 print 合并为单行（AST 已 unparse 为单行）
        new_line = indent + r["new_text"] + "\n"

        # 替换从 start_idx 到 end_idx 的所有行
        lines[start_idx:end_idx + 1] = [new_line]
        log_lines.append(
            f"  L{r['lineno']}: print(...) -> {r['new_text'].strip()[:80]}"
        )

    # 如果没有 logger 实例，添加一个
    if not existing_logger and replacements:
        logger_name = infer_logger_name(file_path)
        # 检查是否已 import logging
        has_logging_import = False
        for node in tree.body:
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == "logging":
                        has_logging_import = True
                        break
            elif isinstance(node, ast.ImportFrom) and node.module == "logging":
                has_logging_import = True
            if has_logging_import:
                break

        # 在 imports_end_line 之后插入
        insert_line = imports_end_line
        # 跳过空行
        while insert_line < len(lines) and lines[insert_line].strip() == "":
            insert_line += 1

        insert_block = []
        if not has_logging_import:
            insert_block.append("import logging\n")
        insert_block.append(f'logger = logging.getLogger("{logger_name}")\n')
        insert_block.append("\n")

        lines = lines[:insert_line] + insert_block + lines[insert_line:]
        logger_added = 1
        log_lines.append(f"  [+] 添加 logger 实例: {logger_name}")

    new_source = "".join(lines)

    # 验证语法正确
    try:
        ast.parse(new_source, filename=str(file_path))
    except SyntaxError as e:
        return (0, 0, [f"[ERROR] 替换后语法错误 {file_path}: {e}，已跳过"])

    if not dry_run:
        file_path.write_text(new_source, encoding="utf-8")

    return (len(replacements), logger_added, log_lines)


def collect_files(target_dir: Path) -> List[Path]:
    """收集目标目录下所有 .py 文件"""
    files = []
    for root, dirs, fnames in os.walk(target_dir):
        # 跳过目录
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for fname in fnames:
            if not fname.endswith(".py"):
                continue
            if fname in SKIP_FILES:
                continue
            files.append(Path(root) / fname)
    return files


def main():
    import argparse
    parser = argparse.ArgumentParser(description="print -> logger 批量迁移")
    parser.add_argument("--dir", default="app", help="目标目录（相对项目根）")
    parser.add_argument("--dry-run", action="store_true", help="仅预览，不写文件")
    parser.add_argument("--file", help="仅处理单个文件（绝对路径）")
    args = parser.parse_args()

    if args.file:
        files = [Path(args.file)]
    else:
        target = PROJECT_ROOT / args.dir if not Path(args.dir).is_absolute() else Path(args.dir)
        if not target.exists():
            print(f"[ERROR] 目标目录不存在: {target}")
            sys.exit(1)
        files = collect_files(target)

    total_replaced = 0
    total_logger_added = 0
    files_changed = 0

    for f in files:
        rel = f.relative_to(PROJECT_ROOT)
        replaced, logger_added, logs = transform_file(f, dry_run=args.dry_run)
        if replaced > 0:
            files_changed += 1
            total_replaced += replaced
            total_logger_added += logger_added
            mode = "[DRY]" if args.dry_run else "[OK]"
            print(f"{mode} {rel}: 替换 {replaced} 处, 新增 logger {logger_added}")
            for log in logs:
                print(log)

    print()
    print("=" * 60)
    print(f"文件改动: {files_changed}")
    print(f"print 替换总数: {total_replaced}")
    print(f"logger 实例新增: {total_logger_added}")
    if args.dry_run:
        print("(dry-run 模式，未写盘)")


if __name__ == "__main__":
    main()
