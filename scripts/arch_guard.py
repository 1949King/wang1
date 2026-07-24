"""
架构守护脚本
============
定义黑白名单目录规则，扫描AI修改是否触及FFmpeg底层/渲染核心禁区，
在CI或pre-commit时拦截，防止跨层破坏。

核心能力：
1. 定义分层架构的黑白名单规则
2. 扫描文件修改，检测违规操作
3. 生成安全报告，标记高危变更
4. 支持pre-commit钩子集成
"""
import os
import sys
import re
import json
import argparse
from typing import Dict, List, Optional, Any, Tuple

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

ARCHITECTURE_RULES = {
    "layers": {
        "ui": {
            "name": "UI层",
            "description": "界面渲染、用户交互、控件绑定",
            "directories": [
                "app/ui/",
                "app/modules/lego/ui/",
                "app/modules/lego/video_editor/",
                "app/modules/lego/widgets/",
            ],
            "file_patterns": ["*.py", "*.ui", "*.qml"],
            "allowed_actions": ["read", "modify", "create"],
            "risk_level": "LOW",
        },
        "core": {
            "name": "核心层",
            "description": "业务逻辑、状态管理、接口定义",
            "directories": [
                "app/core/",
                "app/modules/lego/core.py",
            ],
            "file_patterns": ["*.py"],
            "allowed_actions": ["read", "modify", "create"],
            "risk_level": "MEDIUM",
        },
        "engine": {
            "name": "引擎层",
            "description": "FFmpeg调用、硬件加速、媒体编解码",
            "directories": [
                "app/core/video_processing/",
                "thirdparty/ffmpeg/",
                "thirdparty/mlt/",
                "app/core/gpu_acceleration.py",
                "app/core/render_manager.py",
            ],
            "file_patterns": ["*.py", "*.dll", "*.so", "*.dylib", "*.exe"],
            "allowed_actions": ["read"],
            "risk_level": "HIGH",
            "warning_message": "修改引擎层可能破坏媒体管线，需经过架构审查",
        },
        "debug": {
            "name": "调试层",
            "description": "调试工具、日志分析、性能监控",
            "directories": [
                "app/core/debug/",
                "scripts/",
            ],
            "file_patterns": ["*.py"],
            "allowed_actions": ["read", "modify", "create"],
            "risk_level": "LOW",
        },
    },
    "blacklist": {
        "description": "绝对禁止修改的文件/目录",
        "entries": [
            "thirdparty/ffmpeg/bin/",
            "thirdparty/mlt/Shotcut/",
            "app/core/video_processing/mlt_engine_cpp.py",
            "app/core/video_processing/cpp_engine.py",
            "app/core/video_processing/pyav_engine.py",
            "app/core/gpu_acceleration.py",
        ],
    },
    "whitelist": {
        "description": "允许自由修改的文件/目录",
        "entries": [
            "app/ui/",
            "app/core/debug/",
            "scripts/",
            "tests/",
            "app/modules/lego/video_editor/",
        ],
    },
    "dependency_rules": {
        "description": "模块依赖关系约束",
        "rules": [
            {
                "from": "ui",
                "to": ["core"],
                "allowed": True,
                "description": "UI层可以调用核心层接口",
            },
            {
                "from": "core",
                "to": ["engine"],
                "allowed": True,
                "description": "核心层可以调用引擎层",
            },
            {
                "from": "ui",
                "to": ["engine"],
                "allowed": False,
                "description": "UI层禁止直接调用引擎层",
            },
            {
                "from": "engine",
                "to": ["ui"],
                "allowed": False,
                "description": "引擎层禁止反向依赖UI层",
            },
        ],
    },
}


class ArchitectureGuard:
    """架构守护器"""
    
    def __init__(self, project_root: str = PROJECT_ROOT):
        self.project_root = project_root
        self.rules = ARCHITECTURE_RULES
        self.violations = []
        self.warnings = []
    
    def scan_file(self, file_path: str, action: str = "modify") -> Dict[str, Any]:
        """扫描单个文件"""
        rel_path = os.path.relpath(file_path, self.project_root)
        
        result = {
            "file": rel_path,
            "action": action,
            "layer": None,
            "risk_level": "UNKNOWN",
            "allowed": True,
            "message": "",
            "violation": False,
        }
        
        for layer_name, layer_config in self.rules["layers"].items():
            for directory in layer_config["directories"]:
                if rel_path.startswith(directory):
                    result["layer"] = layer_name
                    result["risk_level"] = layer_config["risk_level"]
                    
                    if action not in layer_config["allowed_actions"]:
                        result["allowed"] = False
                        result["violation"] = True
                        result["message"] = f"操作'{action}'不允许在{layer_config['name']}({layer_name})中执行"
                    elif layer_config["risk_level"] == "HIGH":
                        result["message"] = layer_config.get("warning_message", "")
                    
                    break
        
        for blacklist_entry in self.rules["blacklist"]["entries"]:
            if rel_path.startswith(blacklist_entry):
                result["allowed"] = False
                result["violation"] = True
                result["risk_level"] = "CRITICAL"
                result["message"] = f"文件在黑名单中: {blacklist_entry}"
                break
        
        return result
    
    def scan_directory(self, directory: str, action: str = "modify") -> List[Dict[str, Any]]:
        """扫描目录"""
        results = []
        for root, dirs, files in os.walk(os.path.join(self.project_root, directory)):
            for file in files:
                file_path = os.path.join(root, file)
                result = self.scan_file(file_path, action)
                results.append(result)
                if result["violation"]:
                    self.violations.append(result)
                elif result["risk_level"] == "HIGH" and result["message"]:
                    self.warnings.append(result)
        return results
    
    def scan_changes(self, changed_files: List[str]) -> Dict[str, Any]:
        """扫描变更文件列表"""
        results = []
        
        for file_path in changed_files:
            if os.path.isfile(file_path):
                result = self.scan_file(file_path, "modify")
                results.append(result)
                if result["violation"]:
                    self.violations.append(result)
                elif result["risk_level"] == "HIGH" and result["message"]:
                    self.warnings.append(result)
        
        return {
            "total_files": len(results),
            "violations": len(self.violations),
            "warnings": len(self.warnings),
            "details": results,
        }
    
    def check_imports(self, file_path: str) -> List[Dict[str, Any]]:
        """检查文件导入是否符合依赖规则"""
        issues = []
        
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()
        
        imports = self._extract_imports(content)
        rel_path = os.path.relpath(file_path, self.project_root)
        source_layer = self._get_layer_for_path(rel_path)
        
        if source_layer is None:
            return issues
        
        for import_path in imports:
            target_layer = self._get_layer_for_path(import_path)
            
            if target_layer and source_layer and target_layer != source_layer:
                allowed = self._check_dependency_rule(source_layer, target_layer)
                if not allowed:
                    issues.append({
                        "file": rel_path,
                        "import": import_path,
                        "source_layer": source_layer,
                        "target_layer": target_layer,
                        "violation": True,
                        "message": f"不允许从{source_layer}层导入{target_layer}层的模块",
                    })
        
        return issues
    
    def _extract_imports(self, content: str) -> List[str]:
        """提取导入路径"""
        imports = []
        
        for line in content.split("\n"):
            match = re.match(r'^(?:from|import)\s+(\S+)', line)
            if match:
                imports.append(match.group(1))
        
        return imports
    
    def _get_layer_for_path(self, rel_path: str) -> Optional[str]:
        """获取路径所属层"""
        for layer_name, layer_config in self.rules["layers"].items():
            for directory in layer_config["directories"]:
                if rel_path.startswith(directory):
                    return layer_name
        return None
    
    def _check_dependency_rule(self, from_layer: str, to_layer: str) -> bool:
        """检查依赖规则"""
        for rule in self.rules["dependency_rules"]["rules"]:
            if rule["from"] == from_layer and rule["to"] == to_layer:
                return rule["allowed"]
            if rule["from"] == from_layer and to_layer in rule["to"]:
                return rule["allowed"]
        return True
    
    def generate_report(self) -> Dict[str, Any]:
        """生成架构安全报告"""
        return {
            "project_root": self.project_root,
            "timestamp": os.path.getmtime(__file__),
            "violations": self.violations,
            "warnings": self.warnings,
            "total_violations": len(self.violations),
            "total_warnings": len(self.warnings),
            "rules_summary": {
                "layers": len(self.rules["layers"]),
                "blacklist_entries": len(self.rules["blacklist"]["entries"]),
                "whitelist_entries": len(self.rules["whitelist"]["entries"]),
                "dependency_rules": len(self.rules["dependency_rules"]["rules"]),
            },
        }
    
    def print_report(self):
        """打印报告"""
        report = self.generate_report()
        
        print("\n" + "="*70)
        print("  🏗️  架构安全扫描报告")
        print("="*70)
        
        print(f"\n总违规: {report['total_violations']}")
        print(f"总警告: {report['total_warnings']}")
        
        if report["violations"]:
            print("\n--- 违规列表 ---")
            for v in report["violations"]:
                print(f"  ❌ [{v['risk_level']}] {v['file']}: {v['message']}")
        
        if report["warnings"]:
            print("\n--- 警告列表 ---")
            for w in report["warnings"]:
                print(f"  ⚠️ [{w['risk_level']}] {w['file']}: {w['message']}")
        
        print("\n" + "="*70)
        
        return report["total_violations"] == 0


def main():
    """主函数"""
    parser = argparse.ArgumentParser(description="架构守护脚本")
    parser.add_argument("--scan", type=str, help="扫描指定目录")
    parser.add_argument("--file", type=str, help="扫描指定文件")
    parser.add_argument("--check-imports", action="store_true", help="检查导入依赖")
    parser.add_argument("--report", action="store_true", help="生成报告")
    parser.add_argument("--json", action="store_true", help="输出JSON格式")
    
    args = parser.parse_args()
    
    guard = ArchitectureGuard()
    
    if args.scan:
        results = guard.scan_directory(args.scan)
        if args.json:
            print(json.dumps(results, indent=2, ensure_ascii=False))
        else:
            success = guard.print_report()
            sys.exit(0 if success else 1)
    
    elif args.file:
        result = guard.scan_file(args.file)
        if args.json:
            print(json.dumps(result, indent=2, ensure_ascii=False))
        else:
            status = "✅ 允许" if result["allowed"] else "❌ 禁止"
            print(f"{status} [{result['risk_level']}] {result['file']}")
            if result["message"]:
                print(f"   {result['message']}")
        
        if args.check_imports:
            issues = guard.check_imports(args.file)
            if issues:
                print("\n--- 导入违规 ---")
                for issue in issues:
                    print(f"  ❌ {issue['message']}")
                    print(f"     文件: {issue['file']}")
                    print(f"     导入: {issue['import']}")
            else:
                print("\n✅ 导入检查通过")
    
    elif args.report:
        report = guard.generate_report()
        if args.json:
            print(json.dumps(report, indent=2, ensure_ascii=False))
        else:
            guard.print_report()
    
    else:
        parser.print_help()


if __name__ == "__main__":
    main()