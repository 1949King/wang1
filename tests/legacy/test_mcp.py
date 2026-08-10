"""
自动化测试脚本 - 基于 Filesystem MCP
==================================
测试项目文件结构、配置文件、代码完整性等
"""

import requests
import json
import os
from typing import Dict, List, Any

class MCPTester:
    """MCP自动化测试器"""
    
    def __init__(self, base_url: str = "http://127.0.0.1:8080"):
        self.base_url = base_url
        self.test_results = []
        self.passed_tests = 0
        self.failed_tests = 0
    
    def test_filesystem_read(self, path: str) -> Dict[str, Any]:
        """测试文件读取"""
        try:
            response = requests.get(
                f"{self.base_url}/api/filesystem/read",
                params={"path": path},
                timeout=10
            )
            result = response.json()
            
            content = result.get("content", "")
            
            test_result = {
                "test_name": f"读取文件: {path}",
                "path": path,
                "success": result.get("success", False),
                "status_code": response.status_code,
                "content_length": len(content),
                "content": content
            }
            
            return test_result
        except Exception as e:
            return {
                "test_name": f"读取文件: {path}",
                "path": path,
                "success": False,
                "error": str(e)
            }
    
    def test_project_structure(self) -> List[Dict[str, Any]]:
        """测试项目结构"""
        print("📁 测试项目结构...")
        
        critical_files = [
            "app/main_qt6.py",
            "app/modules/lego/modules.py",
            "app/modules/lego/account_widgets.py",
            "config.py",
            "models.py",
            "requirements.txt"
        ]
        
        results = []
        for file_path in critical_files:
            result = self.test_filesystem_read(file_path)
            results.append(result)
            
            if result.get("success"):
                print(f"  ✅ {file_path} - 成功")
                self.passed_tests += 1
            else:
                print(f"  ❌ {file_path} - 失败: {result.get('error', '未知错误')}")
                self.failed_tests += 1
        
        return results
    
    def test_config_files(self) -> List[Dict[str, Any]]:
        """测试配置文件"""
        print("\n⚙️ 测试配置文件...")
        
        config_files = [
            "config.py",
            ".trae/settings.json",
            "mcp_server.py"
        ]
        
        results = []
        for file_path in config_files:
            result = self.test_filesystem_read(file_path)
            results.append(result)
            
            if result.get("success"):
                print(f"  ✅ {file_path} - 成功")
                self.passed_tests += 1
            else:
                print(f"  ❌ {file_path} - 失败: {result.get('error', '文件不存在')}")
                self.failed_tests += 1
        
        return results
    
    def test_code_integrity(self) -> List[Dict[str, Any]]:
        """测试代码完整性"""
        print("\n🔍 测试代码完整性...")
        
        code_files = [
            "app/modules/lego/modules.py",
            "app/modules/lego/account_widgets.py",
            "app/modules/lego/video_editor/timeline_ui.py",
            "app/modules/lego/video_editor/professional_editor.py"
        ]
        
        results = []
        for file_path in code_files:
            result = self.test_filesystem_read(file_path)
            
            if result.get("success"):
                content = result.get("content", "")
                
                # 检查关键语法
                syntax_checks = {
                    "导入语句": "import" in content or "from " in content,
                    "类定义": "class " in content,
                    "函数定义": "def " in content
                }
                
                integrity_result = {
                    "test_name": f"代码完整性: {file_path}",
                    "path": file_path,
                    "success": all(syntax_checks.values()),
                    "syntax_checks": syntax_checks,
                    "content_length": result.get("content_length", 0)
                }
                
                results.append(integrity_result)
                self.test_results.append(integrity_result)
                
                if integrity_result["success"]:
                    print(f"  ✅ {file_path} - 完整")
                    self.passed_tests += 1
                else:
                    print(f"  ⚠️ {file_path} - 可能有问题: {syntax_checks}")
                    self.failed_tests += 1
            else:
                print(f"  ❌ {file_path} - 无法读取")
                self.failed_tests += 1
        
        return results
    
    def test_timeline_functionality(self) -> List[Dict[str, Any]]:
        """测试时间轴功能"""
        print("\n🎬 测试时间轴功能...")
        
        result = self.test_filesystem_read("app/modules/lego/modules.py")
        
        if result.get("success"):
            content = result.get("content", "")
            
            # 检查时间轴相关功能
            timeline_checks = {
                "TimelineWidget类": "class TimelineWidget" in content,
                "ClipWidget类": "class ClipWidget" in content,
                "播放控制": "def play" in content and "def pause" in content,
                "片段管理": "def add_clip" in content,
                "时间刻度": "_update_time_ruler" in content
            }
            
            functionality_result = {
                "test_name": "时间轴功能完整性",
                "success": all(timeline_checks.values()),
                "checks": timeline_checks
            }
            
            self.test_results.append(functionality_result)
            
            if functionality_result["success"]:
                print("  ✅ 时间轴功能完整")
                self.passed_tests += 1
            else:
                print(f"  ⚠️ 时间轴功能可能缺失: {timeline_checks}")
                self.failed_tests += 1
        
        return [result]
    
    def run_all_tests(self) -> Dict[str, Any]:
        """运行所有测试"""
        print("=" * 60)
        print("🚀 开始自动化测试")
        print("=" * 60)
        
        # 运行各项测试
        self.test_project_structure()
        self.test_config_files()
        self.test_code_integrity()
        self.test_timeline_functionality()
        
        # 生成测试报告
        total_tests = self.passed_tests + self.failed_tests
        success_rate = (self.passed_tests / total_tests * 100) if total_tests > 0 else 0
        
        report = {
            "summary": {
                "total_tests": total_tests,
                "passed": self.passed_tests,
                "failed": self.failed_tests,
                "success_rate": f"{success_rate:.1f}%"
            },
            "results": self.test_results,
            "timestamp": self._get_timestamp()
        }
        
        print("\n" + "=" * 60)
        print("📊 测试报告")
        print("=" * 60)
        print(f"总测试数: {total_tests}")
        print(f"通过: {self.passed_tests}")
        print(f"失败: {self.failed_tests}")
        print(f"成功率: {success_rate:.1f}%")
        print("=" * 60)
        
        return report
    
    def _get_timestamp(self) -> str:
        """获取当前时间戳"""
        from datetime import datetime
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    def save_report(self, report: Dict[str, Any], filename: str = "test_report.json"):
        """保存测试报告"""
        with open(filename, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, ensure_ascii=False)
        print(f"📄 测试报告已保存到: {filename}")


def main():
    """主函数"""
    tester = MCPTester()
    
    try:
        report = tester.run_all_tests()
        tester.save_report(report)
        
        # 根据测试结果返回退出码
        exit_code = 0 if report["summary"]["failed"] == 0 else 1
        exit(exit_code)
        
    except KeyboardInterrupt:
        print("\n⚠️ 测试被用户中断")
        exit(1)
    except Exception as e:
        print(f"\n❌ 测试过程中发生错误: {e}")
        exit(2)


if __name__ == "__main__":
    main()