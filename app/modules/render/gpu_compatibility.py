"""
GPU兼容性测试矩阵
用于检测和测试不同GPU硬件和驱动的兼容性
"""

import os
import subprocess
import platform
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass
from enum import Enum
import time

from app.modules.utils.logger import logger


class GPUVendor(Enum):
    """GPU厂商"""
    NVIDIA = "nvidia"
    AMD = "amd"
    INTEL = "intel"
    APPLE = "apple"
    UNKNOWN = "unknown"


class GPUCompatibilityStatus(Enum):
    """GPU兼容性状态"""
    FULLY_COMPATIBLE = "fully_compatible"
    PARTIALLY_COMPATIBLE = "partially_compatible"
    INCOMPATIBLE = "incompatible"
    UNTESTED = "untested"


class GPURenderTestLevel(Enum):
    """GPU渲染测试级别"""
    BASIC = "basic"      # 基本功能测试
    STANDARD = "standard"  # 标准功能测试
    ADVANCED = "advanced"  # 高级功能测试


@dataclass
class GPUInfo:
    """GPU信息"""
    vendor: GPUVendor
    model: str
    driver_version: str
    memory_mb: int
    compute_capability: Optional[str] = None
    opencl_version: Optional[str] = None
    vulkan_version: Optional[str] = None


@dataclass
class GPUCompatibilityResult:
    """GPU兼容性测试结果"""
    gpu_info: GPUInfo
    status: GPUCompatibilityStatus
    supported_resolutions: List[str]
    supported_backends: List[str]
    performance_score: float
    issues: List[str]
    recommendations: List[str]


@dataclass
class CompatibilityTestConfig:
    """兼容性测试配置"""
    test_level: GPURenderTestLevel = GPURenderTestLevel.STANDARD
    test_resolutions: List[Tuple[int, int]] = None
    test_backends: List[str] = None
    timeout_seconds: int = 30
    enable_performance_test: bool = True


class GPUCompatibilityTester:
    """GPU兼容性测试器"""
    
    def __init__(self):
        self._test_resolutions = [
            (1280, 720),   # 720P
            (1920, 1080),  # 1080P
            (3840, 2160)   # 4K
        ]
        self._test_backends = ["cuda", "opencl", "vulkan"]
        if platform.system() == "Darwin":
            self._test_backends.append("metal")
    
    def detect_gpu(self) -> Optional[GPUInfo]:
        """检测GPU信息"""
        try:
            if platform.system() == "Windows":
                return self._detect_gpu_windows()
            elif platform.system() == "Darwin":
                return self._detect_gpu_macos()
            elif platform.system() == "Linux":
                return self._detect_gpu_linux()
            else:
                logger.warning(f"不支持的操作系统: {platform.system()}")
                return None
        except Exception as e:
            logger.error(f"GPU检测失败: {e}")
            return None
    
    def _detect_gpu_windows(self) -> Optional[GPUInfo]:
        """在Windows上检测GPU"""
        try:
            # 使用wmic命令检测GPU
            result = subprocess.run(
                ["wmic", "path", "win32_VideoController", "get", "Name,DriverVersion,AdapterRAM"],
                capture_output=True,
                text=True,
                timeout=10
            )
            
            output = result.stdout.strip()
            lines = output.split('\n')[1:]
            
            for line in lines:
                parts = line.strip().split()
                if parts:
                    # 提取GPU信息
                    model = ' '.join(parts[:-2])
                    driver_version = parts[-2]
                    memory_kb = int(parts[-1])
                    memory_mb = memory_kb // 1024
                    
                    # 确定厂商
                    vendor = self._detect_vendor(model)
                    
                    return GPUInfo(
                        vendor=vendor,
                        model=model,
                        driver_version=driver_version,
                        memory_mb=memory_mb
                    )
            
        except Exception as e:
            logger.error(f"Windows GPU检测失败: {e}")
        
        return None
    
    def _detect_gpu_macos(self) -> Optional[GPUInfo]:
        """在macOS上检测GPU"""
        try:
            # 使用system_profiler命令检测GPU
            result = subprocess.run(
                ["system_profiler", "SPDisplaysDataType"],
                capture_output=True,
                text=True,
                timeout=10
            )
            
            output = result.stdout
            
            # 解析输出
            model = ""
            memory_mb = 0
            vendor = GPUVendor.APPLE
            
            for line in output.split('\n'):
                line = line.strip()
                if 'Chipset Model:' in line:
                    model = line.split(':', 1)[1].strip()
                elif 'VRAM (Total):' in line:
                    memory_str = line.split(':', 1)[1].strip()
                    if 'MB' in memory_str:
                        memory_mb = int(memory_str.split(' ')[0])
                    elif 'GB' in memory_str:
                        memory_mb = int(memory_str.split(' ')[0]) * 1024
            
            if model:
                return GPUInfo(
                    vendor=vendor,
                    model=model,
                    driver_version="macOS built-in",
                    memory_mb=memory_mb
                )
            
        except Exception as e:
            logger.error(f"macOS GPU检测失败: {e}")
        
        return None
    
    def _detect_gpu_linux(self) -> Optional[GPUInfo]:
        """在Linux上检测GPU"""
        try:
            # 尝试使用lspci命令
            result = subprocess.run(
                ["lspci", "-v"],
                capture_output=True,
                text=True,
                timeout=10
            )
            
            output = result.stdout
            
            # 解析输出
            model = ""
            vendor = GPUVendor.UNKNOWN
            memory_mb = 0
            
            for line in output.split('\n'):
                line = line.strip()
                if 'VGA compatible controller' in line or '3D controller' in line:
                    # 提取GPU型号
                    parts = line.split(':')
                    if len(parts) > 2:
                        model = parts[2].strip()
                        vendor = self._detect_vendor(model)
                elif 'Memory at' in line and 'prefetchable' in line:
                    # 提取显存大小
                    try:
                        memory_str = line.split('(')[1].split(')')[0]
                        if 'MB' in memory_str:
                            memory_mb = int(memory_str.split(' ')[0])
                        elif 'GB' in memory_str:
                            memory_mb = int(memory_str.split(' ')[0]) * 1024
                    except Exception:
                        pass
                        pass
            
            if model:
                return GPUInfo(
                    vendor=vendor,
                    model=model,
                    driver_version="Linux driver",
                    memory_mb=memory_mb
                )
            
        except Exception as e:
            logger.error(f"Linux GPU检测失败: {e}")
        
        return None
    
    def _detect_vendor(self, model: str) -> GPUVendor:
        """根据型号检测厂商"""
        model_lower = model.lower()
        if 'nvidia' in model_lower:
            return GPUVendor.NVIDIA
        elif 'amd' in model_lower or 'radeon' in model_lower:
            return GPUVendor.AMD
        elif 'intel' in model_lower:
            return GPUVendor.INTEL
        else:
            return GPUVendor.UNKNOWN
    
    def test_compatibility(self, config: Optional[CompatibilityTestConfig] = None) -> Optional[GPUCompatibilityResult]:
        """测试GPU兼容性"""
        if config is None:
            config = CompatibilityTestConfig()
        
        gpu_info = self.detect_gpu()
        if not gpu_info:
            logger.error("无法检测到GPU信息")
            return None
        
        logger.info(f"开始测试GPU兼容性: {gpu_info.model}")
        
        # 测试分辨率支持
        supported_resolutions = []
        for width, height in (config.test_resolutions or self._test_resolutions):
            if self._test_resolution(width, height, config.timeout_seconds):
                supported_resolutions.append(f"{width}x{height}")
        
        # 测试后端支持
        supported_backends = []
        for backend in (config.test_backends or self._test_backends):
            if self._test_backend(backend, config.timeout_seconds):
                supported_backends.append(backend)
        
        # 性能测试
        performance_score = 0.0
        if config.enable_performance_test:
            performance_score = self._test_performance()
        
        # 评估兼容性状态
        status = self._evaluate_compatibility(
            gpu_info, supported_resolutions, supported_backends, performance_score
        )
        
        # 生成问题和建议
        issues = self._identify_issues(gpu_info, supported_resolutions, supported_backends)
        recommendations = self._generate_recommendations(gpu_info, status)
        
        result = GPUCompatibilityResult(
            gpu_info=gpu_info,
            status=status,
            supported_resolutions=supported_resolutions,
            supported_backends=supported_backends,
            performance_score=performance_score,
            issues=issues,
            recommendations=recommendations
        )
        
        logger.info(f"GPU兼容性测试完成: {status.value}")
        return result
    
    def _test_resolution(self, width: int, height: int, timeout: int) -> bool:
        """测试特定分辨率是否支持"""
        try:
            # 使用FFmpeg测试分辨率
            cmd = [
                'ffmpeg',
                '-f', 'lavfi',
                '-i', 'testsrc=duration=1:size=1920x1080:rate=30',
                '-s', f'{width}x{height}',
                '-c:v', 'h264',
                '-t', '1',
                '-f', 'null',
                '-'
            ]
            
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout
            )
            
            return result.returncode == 0
        except Exception as e:
            logger.warning(f"测试分辨率 {width}x{height} 失败: {e}")
            return False
    
    def _test_backend(self, backend: str, timeout: int) -> bool:
        """测试特定后端是否支持"""
        try:
            # 检查FFmpeg是否支持该后端
            cmd = ['ffmpeg', '-hwaccels']
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout
            )
            
            output = result.stdout.lower()
            return backend in output
        except Exception as e:
            logger.warning(f"测试后端 {backend} 失败: {e}")
            return False
    
    def _test_performance(self) -> float:
        """测试GPU性能"""
        try:
            # 简单的性能测试
            start_time = time.time()
            
            cmd = [
                'ffmpeg',
                '-f', 'lavfi',
                '-i', 'testsrc=duration=5:size=1920x1080:rate=30',
                '-c:v', 'h264',
                '-preset', 'medium',
                '-f', 'null',
                '-'
            ]
            
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=10
            )
            
            if result.returncode == 0:
                elapsed_time = time.time() - start_time
                # 计算性能得分（时间越短得分越高）
                score = max(0, 100 - (elapsed_time * 10))
                return score
            else:
                return 0.0
        except Exception as e:
            logger.warning(f"性能测试失败: {e}")
            return 0.0
    
    def _evaluate_compatibility(self, gpu_info: GPUInfo, supported_resolutions: List[str], 
                               supported_backends: List[str], performance_score: float) -> GPUCompatibilityStatus:
        """评估GPU兼容性状态"""
        # 基于测试结果评估兼容性
        if not supported_resolutions:
            return GPUCompatibilityStatus.INCOMPATIBLE
        
        # 检查是否支持1080P
        has_1080p = any('1920x1080' in res for res in supported_resolutions)
        # 检查是否支持至少一个硬件加速后端
        has_hardware_backend = any(backend in ['cuda', 'opencl', 'metal', 'vulkan'] for backend in supported_backends)
        
        if has_1080p and has_hardware_backend and performance_score > 50:
            return GPUCompatibilityStatus.FULLY_COMPATIBLE
        elif supported_resolutions and supported_backends:
            return GPUCompatibilityStatus.PARTIALLY_COMPATIBLE
        else:
            return GPUCompatibilityStatus.INCOMPATIBLE
    
    def _identify_issues(self, gpu_info: GPUInfo, supported_resolutions: List[str], 
                        supported_backends: List[str]) -> List[str]:
        """识别潜在问题"""
        issues = []
        
        # 检查分辨率支持
        if not any('1920x1080' in res for res in supported_resolutions):
            issues.append("不支持1080P分辨率")
        if not any('3840x2160' in res for res in supported_resolutions):
            issues.append("不支持4K分辨率")
        
        # 检查后端支持
        if gpu_info.vendor == GPUVendor.NVIDIA and 'cuda' not in supported_backends:
            issues.append("NVIDIA GPU不支持CUDA加速")
        if 'opencl' not in supported_backends:
            issues.append("不支持OpenCL加速")
        
        # 检查显存
        if gpu_info.memory_mb < 2048:
            issues.append("显存不足，可能影响高分辨率渲染")
        
        return issues
    
    def _generate_recommendations(self, gpu_info: GPUInfo, status: GPUCompatibilityStatus) -> List[str]:
        """生成优化建议"""
        recommendations = []
        
        if status == GPUCompatibilityStatus.PARTIALLY_COMPATIBLE:
            recommendations.append("建议使用720P分辨率以获得更好的性能")
        elif status == GPUCompatibilityStatus.INCOMPATIBLE:
            recommendations.append("建议使用软渲染作为备选方案")
        
        if gpu_info.vendor == GPUVendor.NVIDIA:
            recommendations.append("确保安装了最新的NVIDIA驱动")
        elif gpu_info.vendor == GPUVendor.AMD:
            recommendations.append("确保安装了最新的AMD驱动")
        
        recommendations.append("定期更新GPU驱动以获得最佳性能")
        
        return recommendations
    
    def generate_compatibility_report(self, result: GPUCompatibilityResult) -> str:
        """生成兼容性报告"""
        report = []
        report.append("===== GPU兼容性测试报告 =====")
        report.append(f"GPU型号: {result.gpu_info.model}")
        report.append(f"厂商: {result.gpu_info.vendor.value}")
        report.append(f"驱动版本: {result.gpu_info.driver_version}")
        report.append(f"显存: {result.gpu_info.memory_mb} MB")
        report.append(f"兼容性状态: {result.status.value}")
        report.append(f"性能得分: {result.performance_score:.1f}/100")
        report.append("")
        report.append("支持的分辨率:")
        for res in result.supported_resolutions:
            report.append(f"  - {res}")
        report.append("")
        report.append("支持的后端:")
        for backend in result.supported_backends:
            report.append(f"  - {backend}")
        report.append("")
        if result.issues:
            report.append("发现的问题:")
            for issue in result.issues:
                report.append(f"  - {issue}")
            report.append("")
        if result.recommendations:
            report.append("建议:")
            for recommendation in result.recommendations:
                report.append(f"  - {recommendation}")
        report.append("=============================")
        
        return '\n'.join(report)
    
    def run_full_test_suite(self) -> Dict[str, Any]:
        """运行完整测试套件"""
        results = {}
        
        # 基本测试
        basic_config = CompatibilityTestConfig(
            test_level=GPURenderTestLevel.BASIC,
            enable_performance_test=False
        )
        basic_result = self.test_compatibility(basic_config)
        if basic_result:
            results['basic'] = basic_result
        
        # 标准测试
        standard_config = CompatibilityTestConfig(
            test_level=GPURenderTestLevel.STANDARD
        )
        standard_result = self.test_compatibility(standard_config)
        if standard_result:
            results['standard'] = standard_result
        
        # 高级测试
        advanced_config = CompatibilityTestConfig(
            test_level=GPURenderTestLevel.ADVANCED,
            enable_performance_test=True
        )
        advanced_result = self.test_compatibility(advanced_config)
        if advanced_result:
            results['advanced'] = advanced_result
        
        return results


# 全局GPU兼容性测试器实例
gpu_compatibility_tester = None

def get_gpu_compatibility_tester() -> GPUCompatibilityTester:
    """获取GPU兼容性测试器实例（单例模式）"""
    global gpu_compatibility_tester
    if gpu_compatibility_tester is None:
        gpu_compatibility_tester = GPUCompatibilityTester()
    return gpu_compatibility_tester


def test_gpu_compatibility() -> str:
    """测试GPU兼容性并返回报告"""
    tester = get_gpu_compatibility_tester()
    result = tester.test_compatibility()
    if result:
        return tester.generate_compatibility_report(result)
    else:
        return "无法检测GPU信息，无法生成兼容性报告"
