"""
插件认证和测试体系
为插件系统提供安全性和质量保证

B3 收敛标记 (2026-05-31): 签名认证层, 独立职责
"""

import os
import json
import hashlib
import subprocess
import time
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass
from enum import Enum
from pathlib import Path


import logging
logger = logging.getLogger("AI短剧编辑器.core.plugin_authentication")

class PluginSecurityLevel(Enum):
    """插件安全级别"""
    LOW = "low"      # 低风险（仅基础功能）
    MEDIUM = "medium"  # 中等风险（访问文件系统）
    HIGH = "high"     # 高风险（网络访问、系统调用）


class PluginTestStatus(Enum):
    """插件测试状态"""
    NOT_TESTED = "not_tested"
    TESTING = "testing"
    PASSED = "passed"
    FAILED = "failed"
    WARNING = "warning"


@dataclass
class PluginCertificate:
    """插件证书"""
    plugin_id: str
    name: str
    version: str
    author: str
    author_email: Optional[str] = None
    security_level: PluginSecurityLevel = PluginSecurityLevel.LOW
    signature: Optional[str] = None
    issued_date: str = ""
    expiry_date: str = ""
    tested: bool = False
    test_results: Dict[str, Any] = None
    
    def __post_init__(self):
        if self.test_results is None:
            self.test_results = {}
        if not self.issued_date:
            self.issued_date = time.strftime("%Y-%m-%d %H:%M:%S")


@dataclass
class PluginTestResult:
    """插件测试结果"""
    plugin_id: str
    status: PluginTestStatus
    tests: List[Dict[str, Any]]
    duration: float
    timestamp: str
    errors: List[str] = None
    warnings: List[str] = None
    
    def __post_init__(self):
        if self.errors is None:
            self.errors = []
        if self.warnings is None:
            self.warnings = []


class PluginAuthenticator:
    """插件认证器"""
    
    def __init__(self):
        self.certificates_dir = "plugin_certificates"
        os.makedirs(self.certificates_dir, exist_ok=True)
        self.certificates = self._load_certificates()
    
    def _load_certificates(self) -> Dict[str, PluginCertificate]:
        """加载证书"""
        certificates = {}
        
        for file in os.listdir(self.certificates_dir):
            if file.endswith(".json"):
                try:
                    with open(os.path.join(self.certificates_dir, file), 'r', encoding='utf-8') as f:
                        data = json.load(f)
                        cert = PluginCertificate(
                            plugin_id=data.get("plugin_id"),
                            name=data.get("name"),
                            version=data.get("version"),
                            author=data.get("author"),
                            author_email=data.get("author_email"),
                            security_level=PluginSecurityLevel(data.get("security_level", "low")),
                            signature=data.get("signature"),
                            issued_date=data.get("issued_date"),
                            expiry_date=data.get("expiry_date"),
                            tested=data.get("tested", False),
                            test_results=data.get("test_results", {})
                        )
                        certificates[cert.plugin_id] = cert
                except Exception as e:
                    logger.error(f'加载证书失败 {file}: {e}')
        
        return certificates
    
    def generate_certificate(self, plugin_info: Dict[str, Any]) -> PluginCertificate:
        """生成插件证书"""
        plugin_id = plugin_info.get("id")
        security_level = self._assess_security_level(plugin_info)
        
        cert = PluginCertificate(
            plugin_id=plugin_id,
            name=plugin_info.get("name"),
            version=plugin_info.get("version"),
            author=plugin_info.get("author", "Unknown"),
            author_email=plugin_info.get("author_email"),
            security_level=security_level
        )
        
        # 生成签名
        cert.signature = self._generate_signature(cert)
        
        # 保存证书
        self._save_certificate(cert)
        self.certificates[plugin_id] = cert
        
        return cert
    
    def _assess_security_level(self, plugin_info: Dict[str, Any]) -> PluginSecurityLevel:
        """评估插件安全级别"""
        # 基于插件类型和功能评估安全级别
        plugin_type = plugin_info.get("plugin_type", "")
        
        # 检查插件代码中的潜在风险
        file_path = plugin_info.get("file_path")
        if not file_path:
            return PluginSecurityLevel.LOW
        
        # 检查导入的模块
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
                
                # 高风险模块
                high_risk_imports = [
                    "os", "subprocess", "sys", "shutil", "tempfile",
                    "socket", "urllib", "requests", "http"
                ]
                
                # 中等风险模块
                medium_risk_imports = [
                    "json", "yaml", "pickle", "marshal",
                    "io", "fileinput"
                ]
                
                has_high_risk = any(imp in content for imp in high_risk_imports)
                has_medium_risk = any(imp in content for imp in medium_risk_imports)
                
                if has_high_risk:
                    return PluginSecurityLevel.HIGH
                elif has_medium_risk:
                    return PluginSecurityLevel.MEDIUM
                else:
                    return PluginSecurityLevel.LOW
        except Exception:
            return PluginSecurityLevel.LOW
    
    def _generate_signature(self, cert: PluginCertificate) -> str:
        """生成证书签名"""
        data = f"{cert.plugin_id}:{cert.name}:{cert.version}:{cert.author}:{cert.issued_date}"
        return hashlib.sha256(data.encode()).hexdigest()
    
    def _save_certificate(self, cert: PluginCertificate):
        """保存证书"""
        data = {
            "plugin_id": cert.plugin_id,
            "name": cert.name,
            "version": cert.version,
            "author": cert.author,
            "author_email": cert.author_email,
            "security_level": cert.security_level.value,
            "signature": cert.signature,
            "issued_date": cert.issued_date,
            "expiry_date": cert.expiry_date,
            "tested": cert.tested,
            "test_results": cert.test_results
        }
        
        file_path = os.path.join(self.certificates_dir, f"{cert.plugin_id}.json")
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    
    def verify_certificate(self, plugin_id: str) -> bool:
        """验证插件证书"""
        if plugin_id not in self.certificates:
            return False
        
        cert = self.certificates[plugin_id]
        expected_signature = self._generate_signature(cert)
        
        return cert.signature == expected_signature
    
    def get_certificate(self, plugin_id: str) -> Optional[PluginCertificate]:
        """获取插件证书"""
        return self.certificates.get(plugin_id)
    
    def revoke_certificate(self, plugin_id: str) -> bool:
        """吊销插件证书"""
        if plugin_id in self.certificates:
            del self.certificates[plugin_id]
            file_path = os.path.join(self.certificates_dir, f"{plugin_id}.json")
            if os.path.exists(file_path):
                os.remove(file_path)
            return True
        return False


class PluginTester:
    """插件测试器"""
    
    def __init__(self):
        self.test_results_dir = "plugin_test_results"
        os.makedirs(self.test_results_dir, exist_ok=True)
        self.test_results = self._load_test_results()
    
    def _load_test_results(self) -> Dict[str, PluginTestResult]:
        """加载测试结果"""
        results = {}
        
        for file in os.listdir(self.test_results_dir):
            if file.endswith(".json"):
                try:
                    with open(os.path.join(self.test_results_dir, file), 'r', encoding='utf-8') as f:
                        data = json.load(f)
                        result = PluginTestResult(
                            plugin_id=data.get("plugin_id"),
                            status=PluginTestStatus(data.get("status")),
                            tests=data.get("tests", []),
                            duration=data.get("duration", 0.0),
                            timestamp=data.get("timestamp"),
                            errors=data.get("errors", []),
                            warnings=data.get("warnings", [])
                        )
                        results[result.plugin_id] = result
                except Exception as e:
                    logger.error(f'加载测试结果失败 {file}: {e}')
        
        return results
    
    def test_plugin(self, plugin_id: str, plugin_instance: Any) -> PluginTestResult:
        """测试插件"""
        start_time = time.time()
        tests = []
        errors = []
        warnings = []
        
        # 测试插件基本功能
        tests.append(self._test_basic_functionality(plugin_instance, errors, warnings))
        
        # 测试插件性能
        tests.append(self._test_performance(plugin_instance, errors, warnings))
        
        # 测试插件稳定性
        tests.append(self._test_stability(plugin_instance, errors, warnings))
        
        # 测试插件安全性
        tests.append(self._test_security(plugin_instance, errors, warnings))
        
        duration = time.time() - start_time
        
        # 确定测试状态
        if errors:
            status = PluginTestStatus.FAILED
        elif warnings:
            status = PluginTestStatus.WARNING
        else:
            status = PluginTestStatus.PASSED
        
        result = PluginTestResult(
            plugin_id=plugin_id,
            status=status,
            tests=tests,
            duration=duration,
            timestamp=time.strftime("%Y-%m-%d %H:%M:%S"),
            errors=errors,
            warnings=warnings
        )
        
        # 保存测试结果
        self._save_test_result(result)
        self.test_results[plugin_id] = result
        
        return result
    
    def _test_basic_functionality(self, plugin: Any, errors: List[str], warnings: List[str]) -> Dict[str, Any]:
        """测试插件基本功能"""
        test_name = "Basic Functionality"
        test_result = {"name": test_name, "passed": True, "details": []}
        
        try:
            # 测试插件初始化
            if hasattr(plugin, "initialize"):
                plugin.initialize()
                test_result["details"].append("✓ 初始化成功")
            else:
                test_result["details"].append("⚠ 缺少initialize方法")
                warnings.append("插件缺少initialize方法")
            
            # 测试插件运行
            if hasattr(plugin, "run"):
                try:
                    result = plugin.run()
                    test_result["details"].append("✓ 运行成功")
                except Exception as e:
                    test_result["details"].append(f"✗ 运行失败: {e}")
                    errors.append(f"插件运行失败: {e}")
                    test_result["passed"] = False
            else:
                test_result["details"].append("⚠ 缺少run方法")
                warnings.append("插件缺少run方法")
            
            # 测试插件关闭
            if hasattr(plugin, "shutdown"):
                plugin.shutdown()
                test_result["details"].append("✓ 关闭成功")
            else:
                test_result["details"].append("⚠ 缺少shutdown方法")
                warnings.append("插件缺少shutdown方法")
        except Exception as e:
            test_result["details"].append(f"✗ 测试失败: {e}")
            errors.append(f"基本功能测试失败: {e}")
            test_result["passed"] = False
        
        return test_result
    
    def _test_performance(self, plugin: Any, errors: List[str], warnings: List[str]) -> Dict[str, Any]:
        """测试插件性能"""
        test_name = "Performance"
        test_result = {"name": test_name, "passed": True, "details": []}
        
        try:
            # 测试执行时间
            start_time = time.time()
            if hasattr(plugin, "run"):
                plugin.run()
                exec_time = time.time() - start_time
                test_result["details"].append(f"✓ 执行时间: {exec_time:.2f}秒")
                
                if exec_time > 5.0:
                    test_result["details"].append("⚠ 执行时间较长")
                    warnings.append("插件执行时间较长")
            else:
                test_result["details"].append("⚠ 无法测试性能")
        except Exception as e:
            test_result["details"].append(f"✗ 测试失败: {e}")
            errors.append(f"性能测试失败: {e}")
            test_result["passed"] = False
        
        return test_result
    
    def _test_stability(self, plugin: Any, errors: List[str], warnings: List[str]) -> Dict[str, Any]:
        """测试插件稳定性"""
        test_name = "Stability"
        test_result = {"name": test_name, "passed": True, "details": []}
        
        try:
            # 测试多次执行
            if hasattr(plugin, "run"):
                for i in range(3):
                    try:
                        plugin.run()
                        test_result["details"].append(f"✓ 第{i+1}次执行成功")
                    except Exception as e:
                        test_result["details"].append(f"✗ 第{i+1}次执行失败: {e}")
                        errors.append(f"插件稳定性测试失败: {e}")
                        test_result["passed"] = False
                        break
            else:
                test_result["details"].append("⚠ 无法测试稳定性")
        except Exception as e:
            test_result["details"].append(f"✗ 测试失败: {e}")
            errors.append(f"稳定性测试失败: {e}")
            test_result["passed"] = False
        
        return test_result
    
    def _test_security(self, plugin: Any, errors: List[str], warnings: List[str]) -> Dict[str, Any]:
        """测试插件安全性"""
        test_name = "Security"
        test_result = {"name": test_name, "passed": True, "details": []}
        
        try:
            # 检查插件文件
            if hasattr(plugin, "_file_path"):
                file_path = plugin._file_path
                
                # 检查文件权限
                if os.path.exists(file_path):
                    import stat
                    file_stat = os.stat(file_path)
                    if file_stat.st_mode & stat.S_IEXEC:
                        test_result["details"].append("⚠ 插件文件具有执行权限")
                        warnings.append("插件文件具有执行权限")
                
                # 检查代码中的安全问题
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                    
                    # 检查危险操作
                    dangerous_patterns = [
                        "eval(", "exec(", "__import__(", "open(", "os.system(",
                        "subprocess.", "shutil.", "sys.exit("
                    ]
                    
                    for pattern in dangerous_patterns:
                        if pattern in content:
                            test_result["details"].append(f"⚠ 发现潜在危险操作: {pattern}")
                            warnings.append(f"插件包含潜在危险操作: {pattern}")
        except Exception as e:
            test_result["details"].append(f"✗ 测试失败: {e}")
            errors.append(f"安全性测试失败: {e}")
            test_result["passed"] = False
        
        return test_result
    
    def _save_test_result(self, result: PluginTestResult):
        """保存测试结果"""
        data = {
            "plugin_id": result.plugin_id,
            "status": result.status.value,
            "tests": result.tests,
            "duration": result.duration,
            "timestamp": result.timestamp,
            "errors": result.errors,
            "warnings": result.warnings
        }
        
        file_path = os.path.join(self.test_results_dir, f"{result.plugin_id}.json")
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    
    def get_test_result(self, plugin_id: str) -> Optional[PluginTestResult]:
        """获取测试结果"""
        return self.test_results.get(plugin_id)
    
    def get_test_summary(self, plugin_id: str) -> Dict[str, Any]:
        """获取测试摘要"""
        result = self.get_test_result(plugin_id)
        if not result:
            return {"status": "not_tested", "message": "插件尚未测试"}
        
        return {
            "status": result.status.value,
            "duration": result.duration,
            "errors": len(result.errors),
            "warnings": len(result.warnings),
            "timestamp": result.timestamp
        }


class PluginQualityAssurance:
    """插件质量保证"""
    
    def __init__(self):
        self.authenticator = PluginAuthenticator()
        self.tester = PluginTester()
    
    def certify_plugin(self, plugin_info: Dict[str, Any], plugin_instance: Any) -> Tuple[bool, Dict[str, Any]]:
        """认证插件"""
        result = {
            "plugin_id": plugin_info.get("id"),
            "certificate": None,
            "test_result": None,
            "issues": []
        }
        
        try:
            # 生成证书
            certificate = self.authenticator.generate_certificate(plugin_info)
            result["certificate"] = certificate.__dict__
            
            # 测试插件
            test_result = self.tester.test_plugin(plugin_info.get("id"), plugin_instance)
            result["test_result"] = test_result.__dict__
            
            # 检查测试结果
            if test_result.status == PluginTestStatus.FAILED:
                result["issues"].extend(test_result.errors)
                return False, result
            elif test_result.status == PluginTestStatus.WARNING:
                result["issues"].extend(test_result.warnings)
                
            # 更新证书测试状态
            certificate.tested = True
            certificate.test_results = test_result.__dict__
            self.authenticator._save_certificate(certificate)
            
            return True, result
        except Exception as e:
            result["issues"].append(f"认证失败: {e}")
            return False, result
    
    def verify_plugin(self, plugin_id: str) -> Dict[str, Any]:
        """验证插件"""
        result = {
            "plugin_id": plugin_id,
            "certificate_valid": False,
            "test_status": "not_tested",
            "issues": []
        }
        
        # 验证证书
        if self.authenticator.verify_certificate(plugin_id):
            result["certificate_valid"] = True
        else:
            result["issues"].append("证书无效或不存在")
        
        # 检查测试结果
        test_result = self.tester.get_test_result(plugin_id)
        if test_result:
            result["test_status"] = test_result.status.value
            if test_result.status == PluginTestStatus.FAILED:
                result["issues"].extend(test_result.errors)
            elif test_result.status == PluginTestStatus.WARNING:
                result["issues"].extend(test_result.warnings)
        
        return result
    
    def get_plugin_quality_score(self, plugin_id: str) -> float:
        """获取插件质量评分"""
        certificate = self.authenticator.get_certificate(plugin_id)
        test_result = self.tester.get_test_result(plugin_id)
        
        if not certificate or not test_result:
            return 0.0
        
        # 基础分数
        score = 100.0
        
        # 根据测试结果扣分
        if test_result.status == PluginTestStatus.FAILED:
            score -= 50.0
        elif test_result.status == PluginTestStatus.WARNING:
            score -= len(test_result.warnings) * 5.0
        
        # 根据安全级别扣分
        if certificate.security_level == PluginSecurityLevel.HIGH:
            score -= 10.0
        elif certificate.security_level == PluginSecurityLevel.MEDIUM:
            score -= 5.0
        
        # 根据执行时间扣分
        if test_result.duration > 5.0:
            score -= (test_result.duration - 5.0) * 2.0
        
        return max(0.0, min(100.0, score))
    
    def list_certified_plugins(self) -> List[Dict[str, Any]]:
        """列出已认证的插件"""
        certified = []
        
        for plugin_id, certificate in self.authenticator.certificates.items():
            test_result = self.tester.get_test_result(plugin_id)
            quality_score = self.get_plugin_quality_score(plugin_id)
            
            certified.append({
                "plugin_id": plugin_id,
                "name": certificate.name,
                "version": certificate.version,
                "author": certificate.author,
                "security_level": certificate.security_level.value,
                "quality_score": quality_score,
                "test_status": test_result.status.value if test_result else "not_tested",
                "issued_date": certificate.issued_date
            })
        
        return certified
    
    def generate_quality_report(self, plugin_id: str) -> Dict[str, Any]:
        """生成质量报告"""
        certificate = self.authenticator.get_certificate(plugin_id)
        test_result = self.tester.get_test_result(plugin_id)
        
        if not certificate:
            return {"error": "插件未认证"}
        
        report = {
            "plugin_id": plugin_id,
            "name": certificate.name,
            "version": certificate.version,
            "author": certificate.author,
            "security_level": certificate.security_level.value,
            "quality_score": self.get_plugin_quality_score(plugin_id),
            "issued_date": certificate.issued_date,
            "test_summary": self.tester.get_test_summary(plugin_id) if test_result else {"status": "not_tested"},
            "recommendations": []
        }
        
        # 生成建议
        if test_result:
            if test_result.errors:
                report["recommendations"].append("修复测试中发现的错误")
            if test_result.warnings:
                report["recommendations"].append("处理测试中发现的警告")
            if test_result.duration > 5.0:
                report["recommendations"].append("优化插件性能")
        
        if certificate.security_level == PluginSecurityLevel.HIGH:
            report["recommendations"].append("减少插件的权限和危险操作")
        
        return report


# 全局实例
plugin_authenticator = PluginAuthenticator()
plugin_tester = PluginTester()
plugin_qa = PluginQualityAssurance()
