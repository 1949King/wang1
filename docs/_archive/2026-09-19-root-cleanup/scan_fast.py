import os
import ast
import json
from pathlib import Path

PROJECT_ROOT = Path(r"c:\Users\Administrator\Desktop\拾光剪影")
CORE_DIR = PROJECT_ROOT / "app" / "core"
LEGO_DIR = PROJECT_ROOT / "app" / "modules" / "lego"


def get_all_py_files(directory):
    return sorted(directory.rglob("*.py"))


def analyze_file(filepath):
    size = filepath.stat().st_size
    with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
        content = f.read()
    lines = content.splitlines()
    line_count = len(lines)
    
    non_empty = [l for l in lines if l.strip() and not l.strip().startswith("#")]
    
    if len(non_empty) == 0:
        return size, line_count, "empty", "空文件或只有注释", content
    
    if filepath.name == "__init__.py" and len(non_empty) <= 10:
        simple = True
        for l in non_empty:
            s = l.strip()
            if not (s.startswith(("from ", "import ", "__all__", '"""', "'''", '"', "'"))):
                simple = False
                break
        if simple:
            return size, line_count, "empty", "__init__.py 仅含导入/简单声明", content
    
    has_todo = "TODO" in content.upper() or "FIXME" in content.upper()
    
    try:
        tree = ast.parse(content)
    except SyntaxError:
        return size, line_count, "unknown", "语法错误无法解析", content
    
    class_count = 0
    func_count = 0
    real_func = 0
    has_top_logic = False
    has_real_logic = False
    
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            class_count += 1
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            func_count += 1
        elif isinstance(node, ast.Pass):
            pass
        elif isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant):
            pass
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            pass
        else:
            has_top_logic = True
    
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if not (
                len(node.body) == 1 and (
                    isinstance(node.body[0], ast.Pass) or
                    (isinstance(node.body[0], ast.Expr) and isinstance(node.body[0].value, ast.Constant))
                )
            ):
                # Check if function has real statements beyond pass/docstring
                has_body_stmt = False
                for item in node.body:
                    if isinstance(item, ast.Pass):
                        continue
                    if isinstance(item, ast.Expr) and isinstance(item.value, ast.Constant):
                        continue
                    # Check for raise NotImplementedError
                    if isinstance(item, ast.Raise):
                        if isinstance(item.exc, ast.Call):
                            func_id = getattr(item.exc.func, "id", "")
                            if "NotImplemente" in str(func_id):
                                continue
                    has_body_stmt = True
                    break
                
                if has_body_stmt:
                    real_func += 1
                    has_real_logic = True
    
    if real_func > 0 or has_top_logic:
        status = "implemented"
        reason = f"类:{class_count}, 函数:{func_count}(实际实现:{real_func})"
        if has_top_logic:
            reason += ", 有顶层执行代码"
    elif func_count > 0:
        status = "skeleton"
        reason = f"有 {class_count} 类 {func_count} 函数，但函数体为空/pass/docstring"
    elif class_count > 0:
        status = "skeleton"
        reason = f"仅类定义({class_count}个)，无方法实现"
    else:
        status = "implemented" if has_top_logic else "skeleton"
        reason = "有可执行代码但无类/函数结构"
    
    if has_todo:
        reason += " [含TODO/FIXME]"
    
    return size, line_count, status, reason, content


def main():
    print("Scanning...")
    
    # 收集所有 py 文件内容用于引用计数
    all_py_files = list(PROJECT_ROOT.rglob("*.py"))
    all_contents = {}
    for f in all_py_files:
        try:
            with open(f, "r", encoding="utf-8", errors="ignore") as fh:
                all_contents[str(f)] = fh.read()
        except:
            all_contents[str(f)] = ""
    
    def count_refs(target_filepath, content):
        rel = str(target_filepath.relative_to(PROJECT_ROOT)).replace("\\", "/")
        module_dot = rel.replace("/", ".").replace(".py", "")
        stem = target_filepath.stem
        
        # 多种可能的 import 形式
        checks = [
            f"from {module_dot}",
            f"import {module_dot}",
        ]
        
        # 对 core 下的文件添加简化路径匹配
        if "app/core" in rel:
            rel_core = rel.replace("app/core/", "")
            m2 = "core." + rel_core.replace("/", ".").replace(".py", "")
            checks.extend([f"from {m2}", f"import {m2}"])
            # 添加最简化形式: from core.stem
            m3 = f"core.{stem}"
            checks.extend([f"from {m3}", f"import {m3}"])
        
        # lego 下的文件
        if "app/modules/lego" in rel:
            rel_lego = rel.replace("app/modules/lego/", "")
            m2 = "modules.lego." + rel_lego.replace("/", ".").replace(".py", "")
            checks.extend([f"from {m2}", f"import {m2}"])
        
        count = 0
        for other_path, other_content in all_contents.items():
            if other_path == str(target_filepath):
                continue
            for c in checks:
                if c in other_content:
                    count += 1
                    break
        
        return count
    
    def scan_dir(directory, label):
        py_files = get_all_py_files(directory)
        results = []
        for f in py_files:
            size, lines, status, reason, content = analyze_file(f)
            refs = count_refs(f, content)
            rel = str(f.relative_to(PROJECT_ROOT)).replace("\\", "/")
            results.append({
                "file": rel,
                "size_kb": round(size/1024, 1),
                "lines": lines,
                "status": status,
                "reason": reason,
                "referenced_by": refs
            })
        return results
    
    core = scan_dir(CORE_DIR, "CORE")
    lego = scan_dir(LEGO_DIR, "LEGO")
    
    # 排序
    order = {"skeleton": 0, "empty": 1, "implemented": 2, "unknown": 3}
    core.sort(key=lambda x: (order.get(x["status"], 99), x["file"]))
    lego.sort(key=lambda x: (order.get(x["status"], 99), x["file"]))
    
    # 输出 JSON
    output = {"CORE_FILES": core, "LEGO_FILES": lego}
    with open(PROJECT_ROOT / "scan_results.json", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    
    # 打印摘要
    def print_summary(results, name):
        print(f"\n{'='*70}")
        print(f"  {name}")
        print(f"{'='*70}")
        for status in ["SKELETON", "EMPTY", "IMPLEMENTED"]:
            items = [r for r in results if r["status"].lower() == status.lower()]
            if items:
                print(f"\n  [{status}] {len(items)} 个文件")
                print(f"  {'-'*68}")
                for r in items:
                    print(f"  {r['file']}")
                    print(f"    {r['size_kb']}KB | {r['lines']}行 | 被引:{r['referenced_by']}次 | {r['reason']}")
        
        total = len(results)
        print(f"\n  [统计] 总计:{total} | 骨架:{sum(1 for r in results if r['status']=='skeleton')} | "
              f"空:{sum(1 for r in results if r['status']=='empty')} | "
              f"实现:{sum(1 for r in results if r['status']=='implemented')}")
    
    print_summary(core, "CORE_FILES (app/core/)")
    print_summary(lego, "LEGO_FILES (app/modules/lego/)")
    print(f"\n\n结果已保存到 scan_results.json")


if __name__ == "__main__":
    main()
