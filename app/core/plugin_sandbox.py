"""
插件沙箱系统
==============
实现插件安全隔离和权限控制
"""

import os
import sys
import logging
import threading
import time
import subprocess
from typing import Dict, Any, List, Optional, Callable, Set
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
import json
import tempfile
import shutil

from app.core.logging_enhanced import monitor_performance
from app.core.exceptions import PluginError, SecurityError, ErrorCode

logger = logging.getLogger(__name__)


class PluginPermission(Enum):
    """插件权限"""
    READ = "read"
    WRITE = "write"
    EXECUTE = "execute"
    NETWORK = "network"
    FILE_ACCESS = "file_access"
    SYSTEM_ACCESS = "system_access"
    CAMERA_ACCESS = "camera_access"
    MICROPHONE_ACCESS = "microphone_access"


class PluginStatus(Enum):
    """插件状态"""
    LOADED = "loaded"
    UNLOADED = "unloaded"
    ERROR = "error"
    BLOCKED = "blocked"
    SANDBOXED = "sandboxed"


@dataclass
class PluginSandboxConfig:
    """插件沙箱配置"""
    plugin_id: str
    name: str
    version: str
    permissions: Set[PluginPermission]
    allowed_paths: List[str]
    blocked_paths: List[str]
    allowed_domains: List[str]
    blocked_domains: List[str]
    max_memory_mb: int = 512
    max_cpu_percent: int = 50
    max_execution_time: int = 300
    enable_network: bool = False
    enable_file_access: bool = False
    enable_system_access: bool = False
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            'plugin_id': self.plugin_id,
            'name': self.name,
            'version': self.version,
            'permissions': [p.value for p in self.permissions],
            'allowed_paths': self.allowed_paths,
            'blocked_paths': self.blocked_paths,
            'allowed_domains': self.allowed_domains,
            'blocked_domains': self.blocked_domains,
            'max_memory_mb': self.max_memory_mb,
            'max_cpu_percent': self.max_cpu_percent,
            'max_execution_time': self.max_execution_time,
            'enable_network': self.enable_network,
            'enable_file_access': self.enable_file_access,
            'enable_system_access': self.enable_system_access
        }


@dataclass
class PluginExecutionResult:
    """插件执行结果"""
    plugin_id: str
    success: bool
    execution_time: float
    memory_used_mb: float
    cpu_used_percent: float
    output: str
    error_message: Optional[str] = None
    violations: List[str] = field(default_factory=list)
    sandbox_violations: List[str] = field(default_factory=list)


class PluginSandbox:
    """插件沙箱"""
    
    def __init__(self, sandbox_dir: Optional[str] = None):
        self.sandbox_dir = sandbox_dir or os.path.join(tempfile.gettempdir(), 'plugin_sandbox')
        self._plugin_configs: Dict[str, PluginSandboxConfig] = {}
        self._active_plugins: Dict[str, Dict[str, Any]] = {}
        self._plugin_processes: Dict[str, subprocess.Popen] = {}
        self._resource_monitors: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.RLock()
        
        self._violation_log: List[Dict[str, Any]] = []
        self._stats = {
            'total_executions': 0,
            'successful_executions': 0,
            'failed_executions': 0,
            'blocked_executions': 0,
            'total_violations': 0,
            'plugins_blocked': 0
        }
        
        # 创建沙箱目录结构
        self._create_sandbox_structure()
    
    def _create_sandbox_structure(self):
        """创建沙箱目录结构"""
        directories = [
            'plugins',
            'temp',
            'data',
            'cache',
            'logs'
        ]
        
        for directory in directories:
            dir_path = os.path.join(self.sandbox_dir, directory)
            os.makedirs(dir_path, exist_ok=True)
        
        logger.info(f"沙箱目录结构已创建: {self.sandbox_dir}")
    
    def load_plugin_config(self, config_path: str) -> PluginSandboxConfig:
        """加载插件配置
        
        Args:
            config_path: 配置文件路径
        
        Returns:
            插件配置对象
        """
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                config_data = json.load(f)
            
            config = PluginSandboxConfig(
                plugin_id=config_data['plugin_id'],
                name=config_data['name'],
                version=config_data['version'],
                permissions=set(PluginPermission(p) for p in config_data.get('permissions', [])),
                allowed_paths=config_data.get('allowed_paths', []),
                blocked_paths=config_data.get('blocked_paths', []),
                allowed_domains=config_data.get('allowed_domains', []),
                blocked_domains=config_data.get('blocked_domains', []),
                max_memory_mb=config_data.get('max_memory_mb', 512),
                max_cpu_percent=config_data.get('max_cpu_percent', 50),
                max_execution_time=config_data.get('max_execution_time', 300),
                enable_network=config_data.get('enable_network', False),
                enable_file_access=config_data.get('enable_file_access', False),
                enable_system_access=config_data.get('enable_system_access', False)
            )
            
            with self._lock:
                self._plugin_configs[config.plugin_id] = config
            
            logger.info(f"插件配置已加载: {config.plugin_id}")
            return config
            
        except Exception as e:
            logger.error(f"插件配置加载失败: {config_path} - {e}")
            raise PluginError(
                ErrorCode.PLUGIN_LOAD_ERROR,
                f"插件配置加载失败: {str(e)}",
                details={'config_path': config_path}
            )
    
    def register_plugin(self, config: PluginSandboxConfig) -> bool:
        """注册插件
        
        Args:
            config: 插件配置
        
        Returns:
            是否注册成功
        """
        with self._lock:
            if config.plugin_id in self._plugin_configs:
                logger.warning(f"插件已注册: {config.plugin_id}")
                return False
            
            self._plugin_configs[config.plugin_id] = config
            
            # 创建插件目录
            plugin_dir = os.path.join(self.sandbox_dir, 'plugins', config.plugin_id)
            os.makedirs(plugin_dir, exist_ok=True)
            
            # 创建插件配置文件
            config_file = os.path.join(plugin_dir, 'config.json')
            with open(config_file, 'w', encoding='utf-8') as f:
                json.dump(config.to_dict(), f, ensure_ascii=False, indent=2)
        
        logger.info(f"插件已注册: {config.plugin_id}")
        return True
    
    def unregister_plugin(self, plugin_id: str) -> bool:
        """注销插件
        
        Args:
            plugin_id: 插件ID
        
        Returns:
            是否注销成功
        """
        with self._lock:
            if plugin_id not in self._plugin_configs:
                logger.warning(f"插件未注册: {plugin_id}")
                return False
            
            # 停止插件进程
            if plugin_id in self._plugin_processes:
                self._stop_plugin_process(plugin_id)
            
            # 删除插件目录
            plugin_dir = os.path.join(self.sandbox_dir, 'plugins', plugin_id)
            if os.path.exists(plugin_dir):
                shutil.rmtree(plugin_dir)
            
            del self._plugin_configs[plugin_id]
            
            if plugin_id in self._active_plugins:
                del self._active_plugins[plugin_id]
            
            if plugin_id in self._resource_monitors:
                del self._resource_monitors[plugin_id]
        
        logger.info(f"插件已注销: {plugin_id}")
        return True
    
    def execute_plugin(self, plugin_id: str, 
                   command: List[str],
                   args: Optional[List[str]] = None,
                   input_data: Optional[str] = None) -> PluginExecutionResult:
        """执行插件
        
        Args:
            plugin_id: 插件ID
            command: 执行命令
            args: 命令参数
            input_data: 输入数据
        
        Returns:
            执行结果
        """
        config = self._get_plugin_config(plugin_id)
        if not config:
            raise PluginError(
                ErrorCode.PLUGIN_NOT_FOUND,
                f"插件未找到: {plugin_id}",
                details={'plugin_id': plugin_id}
            )
        
        start_time = time.time()
        violations = []
        sandbox_violations = []
        
        # 检查权限
        permission_violations = self._check_permissions(config, command)
        violations.extend(permission_violations)
        
        # 检查路径访问
        path_violations = self._check_path_access(config, args or [])
        violations.extend(path_violations)
        
        # 检查网络访问
        network_violations = self._check_network_access(config, command)
        violations.extend(network_violations)
        
        if violations:
            self._log_violation(plugin_id, violations)
            self._stats['blocked_executions'] += 1
            self._stats['plugins_blocked'] += 1
            
            return PluginExecutionResult(
                plugin_id=plugin_id,
                success=False,
                execution_time=time.time() - start_time,
                memory_used_mb=0,
                cpu_used_percent=0,
                output="",
                error_message="插件执行被阻止: 违反安全策略",
                violations=violations,
                sandbox_violations=sandbox_violations
            )
        
        # 执行插件
        try:
            result = self._execute_in_sandbox(config, command, args, input_data)
            
            execution_time = time.time() - start_time
            
            # 检查资源使用
            resource_violations = self._check_resource_usage(config, result)
            sandbox_violations.extend(resource_violations)
            
            if sandbox_violations:
                self._log_violation(plugin_id, sandbox_violations)
                self._stats['failed_executions'] += 1
                self._stats['total_violations'] += len(sandbox_violations)
                
                return PluginExecutionResult(
                    plugin_id=plugin_id,
                    success=False,
                    execution_time=execution_time,
                    memory_used_mb=result.get('memory_used_mb', 0),
                    cpu_used_percent=result.get('cpu_used_percent', 0),
                    output=result.get('output', ''),
                    error_message="资源使用超限",
                    violations=[],
                    sandbox_violations=sandbox_violations
                )
            
            self._stats['successful_executions'] += 1
            self._stats['total_executions'] += 1
            
            return PluginExecutionResult(
                plugin_id=plugin_id,
                success=True,
                execution_time=execution_time,
                memory_used_mb=result.get('memory_used_mb', 0),
                cpu_used_percent=result.get('cpu_used_percent', 0),
                output=result.get('output', ''),
                violations=violations,
                sandbox_violations=sandbox_violations
            )
            
        except Exception as e:
            self._stats['failed_executions'] += 1
            self._stats['total_executions'] += 1
            
            logger.error(f"插件执行失败: {plugin_id} - {e}")
            
            return PluginExecutionResult(
                plugin_id=plugin_id,
                success=False,
                execution_time=time.time() - start_time,
                memory_used_mb=0,
                cpu_used_percent=0,
                output="",
                error_message=str(e),
                violations=[],
                sandbox_violations=[]
            )
    
    def _check_permissions(self, config: PluginSandboxConfig, 
                        command: List[str]) -> List[str]:
        """检查权限"""
        violations = []
        
        # 检查网络权限
        if PluginPermission.NETWORK not in config.permissions:
            for cmd in command:
                if any(keyword in cmd.lower() for keyword in ['http', 'https', 'ftp', 'socket']):
                    violations.append(f"未授权的网络访问: {cmd}")
        
        # 检查文件访问权限
        if PluginPermission.FILE_ACCESS not in config.permissions:
            for cmd in command:
                if any(keyword in cmd.lower() for keyword in ['file', 'path', 'read', 'write']):
                    violations.append(f"未授权的文件访问: {cmd}")
        
        # 检查系统访问权限
        if PluginPermission.SYSTEM_ACCESS not in config.permissions:
            for cmd in command:
                if any(keyword in cmd.lower() for keyword in ['system', 'registry', 'process']):
                    violations.append(f"未授权的系统访问: {cmd}")
        
        return violations
    
    def _check_path_access(self, config: PluginSandboxConfig, 
                         args: List[str]) -> List[str]:
        """检查路径访问"""
        violations = []
        
        for arg in args:
            # 检查是否为路径
            if os.path.exists(arg):
                abs_path = os.path.abspath(arg)
                
                # 检查是否在允许的路径中
                allowed = any(
                    abs_path.startswith(os.path.join(self.sandbox_dir, allowed_path))
                    for allowed_path in config.allowed_paths
                )
                
                # 检查是否在阻止的路径中
                blocked = any(
                    abs_path.startswith(blocked_path)
                    for blocked_path in config.blocked_paths
                )
                
                if not allowed and not blocked:
                    violations.append(f"未授权的路径访问: {abs_path}")
                elif blocked:
                    violations.append(f"尝试访问阻止的路径: {abs_path}")
        
        return violations
    
    def _check_network_access(self, config: PluginSandboxConfig, 
                           command: List[str]) -> List[str]:
        """检查网络访问"""
        violations = []
        
        if not config.enable_network:
            for cmd in command:
                if any(keyword in cmd.lower() for keyword in ['http://', 'https://', 'ftp://']):
                    violations.append(f"未授权的网络访问: {cmd}")
        
        return violations
    
    def _execute_in_sandbox(self, config: PluginSandboxConfig, 
                          command: List[str],
                          args: Optional[List[str]] = None,
                          input_data: Optional[str] = None) -> Dict[str, Any]:
        """在沙箱中执行插件"""
        plugin_dir = os.path.join(self.sandbox_dir, 'plugins', config.plugin_id)
        
        # 设置环境变量
        env = os.environ.copy()
        env['PLUGIN_SANDBOX'] = '1'
        env['PLUGIN_ID'] = config.plugin_id
        env['PLUGIN_DIR'] = plugin_dir
        
        # 执行命令
        process = subprocess.Popen(
            command + (args or []),
            cwd=plugin_dir,
            env=env,
            stdin=subprocess.PIPE if input_data else None,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        
        # 保存进程引用
        with self._lock:
            self._plugin_processes[config.plugin_id] = process
            self._active_plugins[config.plugin_id] = {
                'status': PluginStatus.LOADED,
                'started_at': time.time(),
                'config': config
            }
        
        # 等待执行完成
        stdout, stderr = process.communicate(input=input_data, timeout=config.max_execution_time)
        
        return {
            'returncode': process.returncode,
            'stdout': stdout,
            'stderr': stderr,
            'output': stdout
        }
    
    def _check_resource_usage(self, config: PluginSandboxConfig, 
                           result: Dict[str, Any]) -> List[str]:
        """检查资源使用"""
        violations = []
        
        # 检查内存使用
        memory_used = result.get('memory_used_mb', 0)
        if memory_used > config.max_memory_mb:
            violations.append(f"内存使用超限: {memory_used}MB > {config.max_memory_mb}MB")
        
        # 检查CPU使用
        cpu_used = result.get('cpu_used_percent', 0)
        if cpu_used > config.max_cpu_percent:
            violations.append(f"CPU使用超限: {cpu_used}% > {config.max_cpu_percent}%")
        
        return violations
    
    def _stop_plugin_process(self, plugin_id: str):
        """停止插件进程"""
        if plugin_id in self._plugin_processes:
            process = self._plugin_processes[plugin_id]
            
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
            
            del self._plugin_processes[plugin_id]
            
            with self._lock:
                if plugin_id in self._active_plugins:
                    self._active_plugins[plugin_id]['status'] = PluginStatus.UNLOADED
    
    def _log_violation(self, plugin_id: str, violations: List[str]):
        """记录违规"""
        violation_record = {
            'plugin_id': plugin_id,
            'timestamp': time.time(),
            'violations': violations,
            'count': len(violations)
        }
        
        self._violation_log.append(violation_record)
        logger.warning(f"插件违规: {plugin_id} - {violations}")
    
    def get_plugin_status(self, plugin_id: str) -> Optional[Dict[str, Any]]:
        """获取插件状态"""
        with self._lock:
            return self._active_plugins.get(plugin_id)
    
    def get_all_plugins(self) -> Dict[str, Dict[str, Any]]:
        """获取所有插件状态"""
        with self._lock:
            return self._active_plugins.copy()
    
    def get_violation_log(self, limit: int = 100) -> List[Dict[str, Any]]:
        """获取违规日志"""
        with self._lock:
            return self._violation_log[-limit:]
    
    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        with self._lock:
            return self._stats.copy()
    
    def cleanup_sandbox(self):
        """清理沙箱"""
        with self._lock:
            # 停止所有插件进程
            for plugin_id in list(self._plugin_processes.keys()):
                self._stop_plugin_process(plugin_id)
            
            # 清理临时文件
            temp_dir = os.path.join(self.sandbox_dir, 'temp')
            if os.path.exists(temp_dir):
                shutil.rmtree(temp_dir)
            
            # 清理日志文件
            logs_dir = os.path.join(self.sandbox_dir, 'logs')
            if os.path.exists(logs_dir):
                old_logs = [
                    f for f in os.listdir(logs_dir)
                    if time.time() - os.path.getmtime(os.path.join(logs_dir, f)) > 7 * 24 * 3600
                ]
                for old_log in old_logs:
                    os.remove(os.path.join(logs_dir, old_log))
        
        logger.info("沙箱清理完成")
    
    def export_plugin_configs(self, output_dir: str):
        """导出插件配置"""
        os.makedirs(output_dir, exist_ok=True)
        
        with self._lock:
            for plugin_id, config in self._plugin_configs.items():
                config_file = os.path.join(output_dir, f"{plugin_id}_config.json")
                with open(config_file, 'w', encoding='utf-8') as f:
                    json.dump(config.to_dict(), f, ensure_ascii=False, indent=2)
        
        logger.info(f"插件配置已导出: {output_dir}")


# 全局实例
_global_plugin_sandbox: Optional[PluginSandbox] = None


def get_plugin_sandbox(sandbox_dir: Optional[str] = None) -> PluginSandbox:
    """获取全局插件沙箱"""
    global _global_plugin_sandbox
    
    if _global_plugin_sandbox is None:
        _global_plugin_sandbox = PluginSandbox(sandbox_dir)
    
    return _global_plugin_sandbox