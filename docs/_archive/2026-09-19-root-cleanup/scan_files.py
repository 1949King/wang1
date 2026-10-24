import os
import ast
import json
from pathlib import Path

CORE_DIR = Path(r"c:\Users\Administrator\Desktop\拾光剪影\app\core")
LEGO_DIR = Path(r"c:\Users\Administrator\Desktop\拾光剪影\app\modules\lego")
PROJECT_ROOT = Path(r"c:\Users\Administrator\Desktop\拾光剪影")


def collect_py_files(directory: Path):
    """递归收集目录下所有 .py 文件"""
    return sorted(directory.rglob("*.py"))


def count_lines_and_size(filepath: Path):
    """统计文件大小和行数"""
    size = filepath.stat().st_size
    with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
        lines = f.readlines()
    return size, len(lines)


def analyze_file_content(filepath: Path):
    """分析文件内容，判断是否为骨架代码"""
    try:
        with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()
            lines = content.splitlines()
    except Exception:
        return "unknown", "读取失败"
    
    # 判断空文件或几乎空的文件
    non_empty_lines = [l for l in lines if l.strip() and not l.strip().startswith("#")]
    if len(non_empty_lines) == 0:
        return "empty", "空文件或只有注释"
    
    # __init__.py 文件特殊处理
    if filepath.name == "__init__.py" and len(non_empty_lines) <= 10:
        # 检查是否只是简单的 __all__ 或 import
        has_only_simple = True
        for line in non_empty_lines:
            stripped = line.strip()
            if stripped.startswith(("from ", "import ")):
                continue
            if stripped.startswith("__all__"):
                continue
            if stripped.startswith(('"""', "'''", '"', "'")):
                continue
            has_only_simple = False
            break
        if has_only_simple:
            return "empty", "__init__.py 仅含导入/简单声明"
    
    # 解析 AST
    try:
        tree = ast.parse(content)
    except SyntaxError:
        # 语法错误的文件，尝试启发式判断
        return analyze_by_heuristics(lines, content)
    
    has_real_logic = False
    has_skeleton_only = True
    has_todo = "TODO" in content.upper() or "FIXME" in content.upper()
    reason_parts = []
    
    # 遍历 AST 节点
    class_count = 0
    func_count = 0
    real_func_count = 0
    
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            class_count += 1
            # 检查类体是否有实际内容
            class_body_has_content = False
            for item in node.body:
                if isinstance(item, ast.Pass):
                    continue
                if isinstance(item, ast.Expr) and isinstance(item.value, ast.Constant):
                    # docstring
                    continue
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                # 有类变量或其他语句
                class_body_has_content = True
                break
            
            if class_body_has_content:
                has_skeleton_only = False
        
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            func_count += 1
            # 检查函数体是否有实际逻辑
            has_body = False
            for item in node.body:
                if isinstance(item, ast.Pass):
                    continue
                if isinstance(item, ast.Expr) and isinstance(item.value, ast.Constant):
                    # docstring
                    continue
                # 有实际语句
                has_body = True
                break
            
            if has_body:
                real_func_count += 1
                # 进一步检查是否有真正的逻辑（不仅仅是 raise NotImplementedError 或 pass）
                for item in node.body:
                    if isinstance(item, ast.Raise):
                        # raise ... 可能是 NotImplementedError
                        if isinstance(item.exc, ast.Call):
                            if hasattr(item.exc.func, "id") and "NotImplemented" in str(item.exc.func.id):
                                continue
                    if isinstance(item, (ast.Assign, ast.AugAssign, ast.If, ast.For, ast.While,
                                         ast.Call, ast.Return, ast.Try, ast.With, ast.Import,
                                         ast.ImportFrom, ast.Expr, ast.Delete)):
                        # 这些都算实际逻辑
                        has_real_logic = True
                        break
    
    # 检查顶层语句（非 class/function 内的语句）
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            continue
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if isinstance(node, ast.Pass):
            continue
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant):
            continue
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            continue
        # 有顶层执行代码
        has_real_logic = True
        has_skeleton_only = False
    
    # 统计模块导入引用数量（简单匹配，用于 cross-reference 计数）
    module_path_parts = filepath.parts
    # 获取相对路径作为模块名
    rel_parts = []
    in_app = False
    for p in filepath.parts:
        if p == "app":
            in_app = True
        if in_app:
            rel_parts.append(p)
    module_dot_name = ".".join(rel_parts).replace(".py", "")
    
    # 判断状态
    if has_real_logic and real_func_count > 0:
        status = "implemented"
        reason = f"有 {class_count} 个类, {func_count} 个函数(其中 {real_func_count} 个有实际逻辑)"
        if has_todo:
            reason += "，含 TODO/FIXME"
    elif func_count > 0 and real_func_count == 0:
        status = "skeleton"
        reason = f"有 {class_count} 个类, {func_count} 个函数，但函数体为空或仅 docstring/pass"
        if has_todo:
            reason += "，含 TODO/FIXME"
    elif class_count > 0 and not has_real_logic:
        status = "skeleton"
        reason = f"仅类定义({class_count}个)，无实际方法实现"
    elif has_skeleton_only and not has_real_logic:
        status = "skeleton"
        reason = "仅结构定义，无实际业务逻辑"
    else:
        status = "implemented"
        reason = f"有执行逻辑语句"
    
    return status, reason


def analyze_by_heuristics(lines, content):
    """无法解析 AST 时的启发式分析"""
    non_empty = [l.strip() for l in lines if l.strip() and not l.strip().startswith("#")]
    
    has_class = any(l.startswith("class ") for l in non_empty)
    has_def = any(l.startswith("def ") for l in non_empty)
    has_pass = any(l == "pass" for l in non_empty)
    has_real_stmt = False
    
    real_keywords = ["return ", "if ", "for ", "while ", "print(", "subprocess", "os.", "sys.",
                      "open(", "json.", "= ", "+=", "-=", "*=", "/=", "import ", "from "]
    for l in non_empty:
        for kw in real_keywords:
            if kw in l and not l.startswith(("class ", "def ")):
                has_real_stmt = True
                break
        if has_real_stmt:
            break
    
    has_todo = "TODO" in content.upper()
    
    if has_class and has_def and has_pass and not has_real_stmt:
        return "skeleton", f"启发式: 有类/函数定义但无实际语句 (pass 为主)" + ("，含 TODO" if has_todo else "")
    elif has_real_stmt:
        return "implemented", f"启发式: 有实际执行语句"
    elif has_class or has_def:
        return "skeleton", f"启发式: 仅有类/函数定义骨架" + ("，含 TODO" if has_todo else "")
    else:
        return "empty", "启发式: 无可识别代码结构"


def count_import_references(target_filepath: Path, all_files):
    """统计 target_filepath 被其他多少个 Python 文件引用"""
    rel_parts = []
    in_app = False
    for p in target_filepath.parts:
        if p == "app":
            in_app = True
        if in_app:
            rel_parts.append(p)
    module_name = ".".join(rel_parts).replace(".py", "")
    
    # 也用于 from ... import 的路径
    module_path = str(target_filepath.relative_to(PROJECT_ROOT)).replace(os.sep, "/").replace(".py", "")
    module_path_dots = module_path.replace("/", ".")
    
    # 文件名本身（用于简单 import filename 形式）
    stem = target_filepath.stem
    
    count = 0
    ref_files = []
    
    for other_file in all_files:
        if other_file == target_filepath:
            continue
        try:
            with open(other_file, "r", encoding="utf-8", errors="ignore") as f:
                other_content = f.read()
        except:
            continue
        
        found = False
        # 检查多种 import 形式
        check_strs = [
            f"from {module_name}",
            f"import {module_name}",
            f"from {module_path_dots}",
            f"import {module_path_dots}",
        ]
        
        # 如果 stem 比较独特（不是太泛的名字），也检查
        unique_stems = {"config_manager", "log_manager", "plugin_manager", "project_manager",
                         "asset_manager", "cache_manager", "render_manager", "history_manager",
                         "subtitle_manager", "title_manager", "effect_manager", "track_manager",
                         "transition_manager", "video_processor", "audio_manager", "ai_tools",
                         "preview_manager", "shortcut_manager", "security", "i18n", "apm_monitoring",
                         "alert_system", "auto_backup", "thread_safety", "memory_optimization",
                         "gpu_acceleration", "multithread_rendering", "permission_management",
                         "platform_adapter", "realtime_collaboration", "service_decomposition",
                         "smart_cache", "speed_ramping", "startup_optimization", "validation",
                         "version_control", "voice_generator", "waveform_generator", "lut_loader",
                         "mask_system", "metadata_extractor", "music_recommendation",
                         "chapter_markers", "frame_navigator", "keyframe_animation",
                         "timeline_manager", "timeline_dsl", "virtual_timeline",
                         "file_operator", "base_repository", "asset_repository",
                         "project_repository", "editor_interface", "editor_scheduler",
                         "editing_capabilities", "conflict_resolution", "developer_community",
                         "exception", "api_gateway", "api_platform", "async_client",
                         "ai_editing_assistant", "ai_enhanced", "code_refactoring",
                         "cache_system", "cache_enhanced", "cache_strategy_optimization",
                         "cache_manager_refactor", "log_aggregation", "logging_enhanced",
                         "performance_benchmark", "service_discovery_enhanced",
                         "plugin_authentication", "plugin_hotloader", "plugin_loader",
                         "plugin_sandbox", "plugin_marketplace", "preset_manager",
                         "proxy_media", "secure_store", "subtitle_generator",
                         "test_base", "transitions", "type_annotation_enhancement",
                         "update_manager", "video_effects", "video_processor_stable",
                         "audio_processor", "audio_scopes", "asset_library",
                         "local_asset_manager", "multitrack_editor", "asset_manager",
                         "llm_clipper", "viral_detector", "prompt_templates",
                         "drama_mlt", "mlt_engine", "mlt_engine_cpp", "pyav_engine",
                         "test_cpp_engine", "performance_optimizer", "build",
                         "install_ffmpeg_dev", "video_engine",
                         "pybind11_wrapper", "setup_cpp_engine", "main_window",
                         "login_window", "auth", "core", "data_collector",
                         "douyin_playwright_api", "bilibili_playwright_api", "drama_crawler",
                         "drama_crawler_example", "drama_understanding_engine", "email_service",
                         "email_verify", "enhanced_thread_pool", "flow_orchestrator",
                         "license_manager", "model_management", "modules", "ollama_client",
                         "online_materials", "openclow_engine", "plugin_manager_legacy",
                         "plugin_store", "professional_video_engine", "settings_module",
                         "skill_engine", "smart_editing_engine", "stealth_browser",
                         "tiktokhub_douyin_api", "timeline_ui", "top0_integration",
                         "user_prefs_store", "video_editing_skill", "video_processor",
                         "viral_optimization_engine", "batch_task_manager", "block_loader",
                         "builtin_blocks", "cloud_api", "account_analyzer", "account_skills",
                         "account_widgets", "agent_workflow", "base_block",
                         "hardware_monitor", "thread_pool", "export_render", "gpu_render",
                         "preview_render", "soft_render", "ai_integration", "frame_editor",
                         "multi_track_editor", "professional_editor", "undo_manager",
                         "main_qt6"}
        
        for cs in check_strs:
            if cs in other_content:
                found = True
                break
        
        if not found and stem in unique_stems:
            # 检查更模糊的模式
            patterns = [
                f"from .{stem}",
                f"from ..{stem}",
                f"import {stem}",
                f"from {stem}",
            ]
            for p in patterns:
                if p in other_content:
                    found = True
                    break
        
        if found:
            count += 1
            ref_files.append(str(other_file))
    
    return count


def scan_directory(directory: Path, label: str):
    py_files = collect_py_files(directory)
    # 收集整个项目的 py 文件用于 cross-reference
    all_py_files = list(PROJECT_ROOT.rglob("*.py"))
    
    results = []
    for f in py_files:
        size, line_count = count_lines_and_size(f)
        status, reason = analyze_file_content(f)
        refs = count_import_references(f, all_py_files)
        results.append({
            "file_path": str(f),
            "size": size,
            "lines": line_count,
            "status": status,
            "reason": reason,
            "imports_this_file": refs
        })
    
    # 排序: skeleton 先，然后 empty, 然后 implemented
    order_map = {"skeleton": 0, "empty": 1, "implemented": 2}
    results.sort(key=lambda x: (order_map.get(x["status"], 99), x["file_path"]))
    
    return results


def print_results(results, label):
    print(f"\n{'='*80}")
    print(f"  {label}")
    print(f"{'='*80}")
    
    status_map = {"skeleton": [], "empty": [], "implemented": []}
    for r in results:
        status_map[r["status"]].append(r)
    
    for status in ["skeleton", "empty", "implemented"]:
        items = status_map[status]
        if not items:
            continue
        print(f"\n  [{status.upper()}] 共 {len(items)} 个文件")
        print(f"  {'-'*76}")
        for r in items:
            rel = r["file_path"].split("拾光剪影")[-1].lstrip("\\")
            size_kb = r["size"] / 1024
            print(f"  {rel}")
            print(f"    大小: {size_kb:.1f} KB | 行数: {r['lines']} | 被引用: {r['imports_this_file']} 次")
            print(f"    原因: {r['reason']}")
            print()
    
    # 汇总统计
    print(f"\n  汇总:")
    total = len(results)
    skel = len(status_map["skeleton"])
    empty = len(status_map["empty"])
    impl = len(status_map["implemented"])
    print(f"    总计: {total} 个 Python 文件")
    print(f"    骨架代码 (skeleton): {skel} ({skel/total*100:.1f}%)")
    print(f"    空文件 (empty): {empty} ({empty/total*100:.1f}%)")
    print(f"    已实现 (implemented): {impl} ({impl/total*100:.1f}%)")


if __name__ == "__main__":
    core_results = scan_directory(CORE_DIR, "CORE 模块 (app/core/)")
    lego_results = scan_directory(LEGO_DIR, "LEGO 模块 (app/modules/lego/)")
    
    print_results(core_results, "CORE_FILES")
    print_results(lego_results, "LEGO_FILES")
    
    # 保存 JSON
    output = {
        "CORE_FILES": core_results,
        "LEGO_FILES": lego_results
    }
    output_path = PROJECT_ROOT / "scan_results.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"\n\nJSON 结果已保存至: {output_path}")
