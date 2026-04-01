import asyncio
import json
import time
import socket
import struct
import ipaddress
from typing import Dict, List, Optional, Set, Any, Callable
from dataclasses import dataclass, field, asdict
from enum import Enum
from datetime import datetime, timedelta
from collections import defaultdict
import aiohttp
import redis
import logging
from concurrent.futures import ThreadPoolExecutor
import hashlib
import ssl

from app.core.service_decomposition import ServiceRegistry, ServiceType, ServiceInstance


class HealthCheckStatus(Enum):
    """健康检查状态"""
    HEALTHY = "healthy"
    UNHEALTHY = "unhealthy"
    DEGRADED = "degraded"
    UNKNOWN = "unknown"


class ServiceDiscoveryMethod(Enum):
    """服务发现方法"""
    CONSOLE = "console"
    DNS = "dns"
    HTTP = "http"
    TCP = "tcp"
    UDP = "udp"
    REDIS = "redis"


@dataclass
class HealthCheckConfig:
    """健康检查配置"""
    enabled: bool = True
    interval_seconds: int = 30
    timeout_seconds: int = 5
    unhealthy_threshold: int = 3
    healthy_threshold: int = 2
    check_methods: List[str] = field(default_factory=lambda: ["tcp", "http"])
    http_path: str = "/health"
    http_expected_status: int = 200
    tcp_port: Optional[int] = None
    custom_check: Optional[Callable] = None


@dataclass
class ServiceMetadata:
    """服务元数据"""
    version: str = "1.0.0"
    environment: str = "production"
    region: str = "default"
    datacenter: str = "default"
    tags: List[str] = field(default_factory=list)
    capabilities: List[str] = field(default_factory=list)
    dependencies: List[str] = field(default_factory=list)
    custom_data: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ServiceHealth:
    """服务健康状态"""
    service_id: str
    status: HealthCheckStatus
    last_check_time: float
    consecutive_failures: int = 0
    consecutive_successes: int = 0
    response_time_ms: float = 0
    error_message: Optional[str] = None
    metadata: Optional[ServiceMetadata] = None


class HealthChecker:
    """健康检查器"""
    
    def __init__(self, config: HealthCheckConfig):
        self.config = config
        self.logger = logging.getLogger(__name__)
        self.executor = ThreadPoolExecutor(max_workers=10)
        self.session: Optional[aiohttp.ClientSession] = None
    
    async def initialize(self):
        """初始化检查器"""
        timeout = aiohttp.ClientTimeout(total=self.config.timeout_seconds)
        self.session = aiohttp.ClientSession(timeout=timeout)
    
    async def shutdown(self):
        """关闭检查器"""
        if self.session:
            await self.session.close()
        self.executor.shutdown(wait=True)
    
    async def check_health(self, service: ServiceInstance) -> ServiceHealth:
        """检查服务健康状态"""
        if not self.config.enabled:
            return ServiceHealth(
                service_id=service.instance_id,
                status=HealthCheckStatus.UNKNOWN,
                last_check_time=time.time()
            )
        
        start_time = time.time()
        status = HealthCheckStatus.HEALTHY
        error_message = None
        
        for method in self.config.check_methods:
            try:
                if method == "tcp":
                    await self._check_tcp(service)
                elif method == "http":
                    await self._check_http(service)
                elif method == "custom" and self.config.custom_check:
                    await self.config.custom_check(service)
            except Exception as e:
                status = HealthCheckStatus.UNHEALTHY
                error_message = str(e)
                break
        
        response_time = (time.time() - start_time) * 1000
        
        return ServiceHealth(
            service_id=service.instance_id,
            status=status,
            last_check_time=time.time(),
            response_time_ms=response_time,
            error_message=error_message
        )
    
    async def _check_tcp(self, service: ServiceInstance):
        """TCP连接检查"""
        host = service.host
        port = self.config.tcp_port or service.port
        
        loop = asyncio.get_event_loop()
        
        def _tcp_check():
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(self.config.timeout_seconds)
            try:
                result = sock.connect_ex((host, port))
                if result != 0:
                    raise ConnectionError(f"TCP connection failed to {host}:{port}")
            finally:
                sock.close()
        
        await loop.run_in_executor(self.executor, _tcp_check)
    
    async def _check_http(self, service: ServiceInstance):
        """HTTP健康检查"""
        url = f"http://{service.host}:{service.port}{self.config.http_path}"
        
        async with self.session.get(url) as response:
            if response.status != self.config.http_expected_status:
                raise Exception(f"HTTP check failed: expected {self.config.http_expected_status}, got {response.status}")


class ServiceMonitor:
    """服务监控器"""
    
    def __init__(self, service_registry: ServiceRegistry, 
                 health_checker: HealthChecker,
                 redis_client: Optional[redis.Redis] = None):
        self.service_registry = service_registry
        self.health_checker = health_checker
        self.redis_client = redis_client
        self.health_states: Dict[str, ServiceHealth] = {}
        self.monitoring_tasks: Dict[str, asyncio.Task] = {}
        self.logger = logging.getLogger(__name__)
    
    async def start_monitoring(self, service_id: str):
        """开始监控服务"""
        if service_id in self.monitoring_tasks:
            return
        
        task = asyncio.create_task(self._monitor_service(service_id))
        self.monitoring_tasks[service_id] = task
        self.logger.info(f"Started monitoring service: {service_id}")
    
    async def stop_monitoring(self, service_id: str):
        """停止监控服务"""
        if service_id in self.monitoring_tasks:
            task = self.monitoring_tasks[service_id]
            task.cancel()
            del self.monitoring_tasks[service_id]
            self.logger.info(f"Stopped monitoring service: {service_id}")
    
    async def _monitor_service(self, service_id: str):
        """监控单个服务"""
        while True:
            try:
                service = self.service_registry.get_service(service_id)
                if not service:
                    self.logger.warning(f"Service not found: {service_id}")
                    await asyncio.sleep(self.health_checker.config.interval_seconds)
                    continue
                
                health = await self.health_checker.check_health(service)
                self._update_health_state(health)
                
                self._persist_health_state(health)
                
                if health.status == HealthCheckStatus.UNHEALTHY:
                    self.logger.warning(f"Service unhealthy: {service_id} - {health.error_message}")
                
                await asyncio.sleep(self.health_checker.config.interval_seconds)
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                self.logger.error(f"Error monitoring service {service_id}: {e}")
                await asyncio.sleep(self.health_checker.config.interval_seconds)
    
    def _update_health_state(self, health: ServiceHealth):
        """更新健康状态"""
        previous_health = self.health_states.get(health.service_id)
        
        if previous_health:
            if health.status == HealthCheckStatus.HEALTHY:
                health.consecutive_successes = previous_health.consecutive_successes + 1
                health.consecutive_failures = 0
            else:
                health.consecutive_failures = previous_health.consecutive_failures + 1
                health.consecutive_successes = 0
        
        self.health_states[health.service_id] = health
    
    def _persist_health_state(self, health: ServiceHealth):
        """持久化健康状态"""
        if self.redis_client:
            key = f"service_health:{health.service_id}"
            value = json.dumps({
                "status": health.status.value,
                "last_check_time": health.last_check_time,
                "consecutive_failures": health.consecutive_failures,
                "consecutive_successes": health.consecutive_successes,
                "response_time_ms": health.response_time_ms,
                "error_message": health.error_message
            })
            self.redis_client.setex(key, 3600, value)
    
    def get_health_state(self, service_id: str) -> Optional[ServiceHealth]:
        """获取服务健康状态"""
        return self.health_states.get(service_id)
    
    def get_all_health_states(self) -> Dict[str, ServiceHealth]:
        """获取所有服务健康状态"""
        return self.health_states.copy()
    
    def get_healthy_services(self) -> List[str]:
        """获取健康服务列表"""
        return [
            service_id for service_id, health in self.health_states.items()
            if health.status == HealthCheckStatus.HEALTHY
        ]
    
    def get_unhealthy_services(self) -> List[str]:
        """获取不健康服务列表"""
        return [
            service_id for service_id, health in self.health_states.items()
            if health.status == HealthCheckStatus.UNHEALTHY
        ]


class ServiceTopology:
    """服务拓扑"""
    
    def __init__(self):
        self.service_graph: Dict[str, Set[str]] = defaultdict(set)
        self.reverse_graph: Dict[str, Set[str]] = defaultdict(set)
        self.logger = logging.getLogger(__name__)
    
    def add_dependency(self, service_id: str, depends_on: str):
        """添加服务依赖关系"""
        self.service_graph[service_id].add(depends_on)
        self.reverse_graph[depends_on].add(service_id)
        self.logger.debug(f"Added dependency: {service_id} -> {depends_on}")
    
    def remove_dependency(self, service_id: str, depends_on: str):
        """移除服务依赖关系"""
        self.service_graph[service_id].discard(depends_on)
        self.reverse_graph[depends_on].discard(service_id)
        self.logger.debug(f"Removed dependency: {service_id} -> {depends_on}")
    
    def get_dependencies(self, service_id: str) -> Set[str]:
        """获取服务依赖"""
        return self.service_graph.get(service_id, set())
    
    def get_dependents(self, service_id: str) -> Set[str]:
        """获取依赖该服务的其他服务"""
        return self.reverse_graph.get(service_id, set())
    
    def get_topology_order(self) -> List[str]:
        """获取拓扑排序"""
        visited = set()
        temp_visited = set()
        result = []
        
        def dfs(service_id: str):
            if service_id in temp_visited:
                raise ValueError(f"Circular dependency detected involving {service_id}")
            if service_id in visited:
                return
            
            temp_visited.add(service_id)
            
            for dep in self.get_dependencies(service_id):
                dfs(dep)
            
            temp_visited.remove(service_id)
            visited.add(service_id)
            result.append(service_id)
        
        for service_id in self.service_graph:
            if service_id not in visited:
                dfs(service_id)
        
        return result
    
    def detect_circular_dependencies(self) -> List[List[str]]:
        """检测循环依赖"""
        visited = set()
        temp_visited = set()
        cycles = []
        
        def dfs(service_id: str, path: List[str]):
            if service_id in temp_visited:
                cycle_start = path.index(service_id)
                cycles.append(path[cycle_start:] + [service_id])
                return
            
            if service_id in visited:
                return
            
            temp_visited.add(service_id)
            path.append(service_id)
            
            for dep in self.get_dependencies(service_id):
                dfs(dep, path)
            
            path.pop()
            temp_visited.remove(service_id)
            visited.add(service_id)
        
        for service_id in self.service_graph:
            if service_id not in visited:
                dfs(service_id, [])
        
        return cycles
    
    def visualize_topology(self) -> str:
        """可视化服务拓扑"""
        lines = ["Service Topology:"]
        
        for service_id in sorted(self.service_graph.keys()):
            deps = self.get_dependencies(service_id)
            if deps:
                lines.append(f"  {service_id} -> {', '.join(sorted(deps))}")
            else:
                lines.append(f"  {service_id} (no dependencies)")
        
        return "\n".join(lines)


class EnhancedServiceDiscovery:
    """增强型服务发现"""
    
    def __init__(self, service_registry: ServiceRegistry,
                 health_checker: HealthChecker,
                 redis_client: Optional[redis.Redis] = None):
        self.service_registry = service_registry
        self.health_checker = health_checker
        self.redis_client = redis_client
        
        self.service_monitor = ServiceMonitor(service_registry, health_checker, redis_client)
        self.service_topology = ServiceTopology()
        
        self.discovery_methods: Dict[ServiceDiscoveryMethod, Callable] = {
            ServiceDiscoveryMethod.CONSOLE: self._discover_console,
            ServiceDiscoveryMethod.DNS: self._discover_dns,
            ServiceDiscoveryMethod.HTTP: self._discover_http,
            ServiceDiscoveryMethod.TCP: self._discover_tcp,
            ServiceDiscoveryMethod.REDIS: self._discover_redis,
        }
        
        self.logger = logging.getLogger(__name__)
    
    async def initialize(self):
        """初始化服务发现"""
        await self.health_checker.initialize()
        self.logger.info("Enhanced Service Discovery initialized")
    
    async def shutdown(self):
        """关闭服务发现"""
        await self.health_checker.shutdown()
        self.logger.info("Enhanced Service Discovery shutdown")
    
    async def discover_services(self, methods: List[ServiceDiscoveryMethod] = None,
                                network_range: str = "192.168.1.0/24") -> Dict[str, List[str]]:
        """发现服务"""
        if methods is None:
            methods = [ServiceDiscoveryMethod.REDIS, ServiceDiscoveryMethod.CONSOLE]
        
        discovered = defaultdict(list)
        
        for method in methods:
            try:
                method_results = await self.discovery_methods[method](network_range)
                for service_type, services in method_results.items():
                    discovered[service_type].extend(services)
            except Exception as e:
                self.logger.error(f"Error discovering services with {method.value}: {e}")
        
        return dict(discovered)
    
    async def _discover_console(self, network_range: str) -> Dict[str, List[str]]:
        """通过控制台发现服务"""
        services = self.service_registry.get_all_services()
        return {service_type.value: [s.instance_id for s in instances] 
                for service_type, instances in services.items()}
    
    async def _discover_dns(self, network_range: str) -> Dict[str, List[str]]:
        """通过DNS发现服务"""
        discovered = defaultdict(list)
        
        try:
            import socket
            hostname = socket.gethostname()
            ip_address = socket.gethostbyname(hostname)
            
            network = ipaddress.ip_network(network_range, strict=False)
            
            for ip in network.hosts():
                try:
                    hostname = socket.gethostbyaddr(str(ip))[0]
                    if "service" in hostname.lower():
                        discovered["dns"].append(str(ip))
                except socket.herror:
                    continue
                    
        except Exception as e:
            self.logger.error(f"DNS discovery error: {e}")
        
        return dict(discovered)
    
    async def _discover_http(self, network_range: str) -> Dict[str, List[str]]:
        """通过HTTP发现服务"""
        discovered = defaultdict(list)
        
        try:
            network = ipaddress.ip_network(network_range, strict=False)
            
            tasks = []
            for ip in network.hosts():
                for port in [8000, 8001, 8002, 9000, 9001]:
                    tasks.append(self._check_http_service(str(ip), port))
            
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            for result in results:
                if isinstance(result, tuple) and result[0]:
                    service_type, service_url = result
                    discovered[service_type].append(service_url)
                    
        except Exception as e:
            self.logger.error(f"HTTP discovery error: {e}")
        
        return dict(discovered)
    
    async def _check_http_service(self, host: str, port: int) -> Optional[tuple]:
        """检查HTTP服务"""
        try:
            url = f"http://{host}:{port}/api/discover"
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=2)) as session:
                async with session.get(url) as response:
                    if response.status == 200:
                        data = await response.json()
                        service_type = data.get("service_type", "unknown")
                        return (service_type, f"{host}:{port}")
        except Exception:
            pass
        return None
    
    async def _discover_tcp(self, network_range: str) -> Dict[str, List[str]]:
        """通过TCP发现服务"""
        discovered = defaultdict(list)
        
        try:
            network = ipaddress.ip_network(network_range, strict=False)
            
            loop = asyncio.get_event_loop()
            
            def _check_tcp_port(host: str, port: int):
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(1)
                try:
                    result = sock.connect_ex((host, port))
                    if result == 0:
                        return f"{host}:{port}"
                except Exception:
                    pass
                finally:
                    sock.close()
                return None
            
            tasks = []
            for ip in network.hosts():
                for port in [8000, 8001, 8002, 9000, 9001]:
                    tasks.append(loop.run_in_executor(None, _check_tcp_port, str(ip), port))
            
            results = await asyncio.gather(*tasks)
            
            for result in results:
                if result:
                    discovered["tcp"].append(result)
                    
        except Exception as e:
            self.logger.error(f"TCP discovery error: {e}")
        
        return dict(discovered)
    
    async def _discover_redis(self, network_range: str) -> Dict[str, List[str]]:
        """通过Redis发现服务"""
        discovered = defaultdict(list)
        
        if not self.redis_client:
            return dict(discovered)
        
        try:
            pattern = "service:*"
            keys = self.redis_client.keys(pattern)
            
            for key in keys:
                try:
                    data = json.loads(self.redis_client.get(key))
                    service_type = data.get("service_type", "unknown")
                    service_id = data.get("instance_id", key)
                    discovered[service_type].append(service_id)
                except Exception as e:
                    self.logger.error(f"Error parsing service data from {key}: {e}")
                    
        except Exception as e:
            self.logger.error(f"Redis discovery error: {e}")
        
        return dict(discovered)
    
    async def register_and_monitor(self, service: ServiceInstance, 
                                   metadata: Optional[ServiceMetadata] = None) -> str:
        """注册并监控服务"""
        service_id = self.service_registry.register_service(
            service.service_type,
            service.host,
            service.port,
            service.config
        )
        
        if metadata:
            self._update_service_metadata(service_id, metadata)
        
        await self.service_monitor.start_monitoring(service_id)
        
        return service_id
    
    def _update_service_metadata(self, service_id: str, metadata: ServiceMetadata):
        """更新服务元数据"""
        if self.redis_client:
            key = f"service_metadata:{service_id}"
            value = json.dumps(asdict(metadata))
            self.redis_client.setex(key, 3600, value)
    
    def get_service_metadata(self, service_id: str) -> Optional[ServiceMetadata]:
        """获取服务元数据"""
        if self.redis_client:
            key = f"service_metadata:{service_id}"
            data = self.redis_client.get(key)
            if data:
                return ServiceMetadata(**json.loads(data))
        return None
    
    async def failover_service(self, service_id: str) -> Optional[str]:
        """服务故障转移"""
        service = self.service_registry.get_service(service_id)
        if not service:
            return None
        
        same_type_services = self.service_registry.get_services(service.service_type)
        healthy_services = [
            s for s in same_type_services 
            if s.instance_id != service_id and 
            self.service_monitor.get_health_state(s.instance_id)?.status == HealthCheckStatus.HEALTHY
        ]
        
        if healthy_services:
            return healthy_services[0].instance_id
        
        return None
    
    def get_service_topology(self) -> ServiceTopology:
        """获取服务拓扑"""
        return self.service_topology
    
    def get_service_health_summary(self) -> Dict[str, Any]:
        """获取服务健康摘要"""
        health_states = self.service_monitor.get_all_health_states()
        
        summary = {
            "total_services": len(health_states),
            "healthy": 0,
            "unhealthy": 0,
            "degraded": 0,
            "unknown": 0,
            "average_response_time_ms": 0,
            "services": {}
        }
        
        total_response_time = 0
        
        for service_id, health in health_states.items():
            summary["services"][service_id] = {
                "status": health.status.value,
                "response_time_ms": health.response_time_ms,
                "consecutive_failures": health.consecutive_failures
            }
            
            if health.status == HealthCheckStatus.HEALTHY:
                summary["healthy"] += 1
            elif health.status == HealthCheckStatus.UNHEALTHY:
                summary["unhealthy"] += 1
            elif health.status == HealthCheckStatus.DEGRADED:
                summary["degraded"] += 1
            else:
                summary["unknown"] += 1
            
            total_response_time += health.response_time_ms
        
        if health_states:
            summary["average_response_time_ms"] = total_response_time / len(health_states)
        
        return summary


_global_enhanced_discovery: Optional[EnhancedServiceDiscovery] = None


def get_enhanced_discovery(service_registry: Optional[ServiceRegistry] = None,
                           health_checker: Optional[HealthChecker] = None,
                           redis_client: Optional[redis.Redis] = None) -> EnhancedServiceDiscovery:
    """获取全局增强型服务发现实例"""
    global _global_enhanced_discovery
    
    if _global_enhanced_discovery is None:
        if service_registry is None:
            from app.core.service_decomposition import get_service_registry
            service_registry = get_service_registry()
        
        if health_checker is None:
            health_checker = HealthChecker(HealthCheckConfig())
        
        _global_enhanced_discovery = EnhancedServiceDiscovery(
            service_registry=service_registry,
            health_checker=health_checker,
            redis_client=redis_client
        )
    
    return _global_enhanced_discovery


async def create_enhanced_discovery(service_registry: Optional[ServiceRegistry] = None,
                                    redis_client: Optional[redis.Redis] = None) -> EnhancedServiceDiscovery:
    """创建并初始化增强型服务发现"""
    discovery = get_enhanced_discovery(service_registry=service_registry, redis_client=redis_client)
    await discovery.initialize()
    return discovery
