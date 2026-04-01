import asyncio
import json
import time
import hashlib
import hmac
from typing import Dict, List, Optional, Any, Callable, Tuple
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from enum import Enum
from collections import defaultdict, deque
import aiohttp
from fastapi import Request, Response, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
import jwt
import redis
from prometheus_client import Counter, Histogram, Gauge
import logging
from functools import wraps
import ipaddress

from app.core.service_decomposition import ServiceRegistry, ServiceDiscovery, ServiceLoadBalancer, ServiceType


class GatewayConfig:
    """API网关配置"""
    
    def __init__(self):
        self.jwt_secret = "your-secret-key-change-in-production"
        self.jwt_algorithm = "HS256"
        self.jwt_expiration_hours = 24
        
        self.rate_limit_enabled = True
        self.rate_limit_requests_per_minute = 60
        self.rate_limit_requests_per_hour = 1000
        
        self.circuit_breaker_enabled = True
        self.circuit_breaker_failure_threshold = 5
        self.circuit_breaker_recovery_timeout = 60
        
        self.request_timeout = 30
        self.max_request_size = 10 * 1024 * 1024  # 10MB
        
        self.auth_enabled = True
        self.cors_enabled = True
        self.cors_origins = ["*"]
        
        self.logging_enabled = True
        self.log_level = "INFO"
        
        self.metrics_enabled = True
        self.monitoring_enabled = True


class RouteRule:
    """路由规则"""
    
    def __init__(self, path: str, service_type: ServiceType, 
                 methods: List[str] = None, auth_required: bool = True,
                 rate_limit: Optional[int] = None):
        self.path = path
        self.service_type = service_type
        self.methods = methods or ["GET", "POST", "PUT", "DELETE"]
        self.auth_required = auth_required
        self.rate_limit = rate_limit


class CircuitBreakerState(Enum):
    """熔断器状态"""
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


@dataclass
class CircuitBreakerStats:
    """熔断器统计"""
    failure_count: int = 0
    success_count: int = 0
    last_failure_time: Optional[float] = None
    state: CircuitBreakerState = CircuitBreakerState.CLOSED


class CircuitBreaker:
    """熔断器"""
    
    def __init__(self, config: GatewayConfig):
        self.config = config
        self.breakers: Dict[str, CircuitBreakerStats] = defaultdict(
            lambda: CircuitBreakerStats()
        )
        self.logger = logging.getLogger(__name__)
    
    def is_allowed(self, service_id: str) -> bool:
        """检查是否允许请求"""
        stats = self.breakers[service_id]
        
        if stats.state == CircuitBreakerState.OPEN:
            if time.time() - stats.last_failure_time > self.config.circuit_breaker_recovery_timeout:
                stats.state = CircuitBreakerState.HALF_OPEN
                self.logger.info(f"Circuit breaker for {service_id} transitioned to HALF_OPEN")
                return True
            return False
        
        return True
    
    def record_success(self, service_id: str):
        """记录成功"""
        stats = self.breakers[service_id]
        stats.success_count += 1
        
        if stats.state == CircuitBreakerState.HALF_OPEN:
            stats.state = CircuitBreakerState.CLOSED
            stats.failure_count = 0
            self.logger.info(f"Circuit breaker for {service_id} transitioned to CLOSED")
    
    def record_failure(self, service_id: str):
        """记录失败"""
        stats = self.breakers[service_id]
        stats.failure_count += 1
        stats.last_failure_time = time.time()
        
        if stats.failure_count >= self.config.circuit_breaker_failure_threshold:
            stats.state = CircuitBreakerState.OPEN
            self.logger.warning(f"Circuit breaker for {service_id} opened after {stats.failure_count} failures")
    
    def get_stats(self, service_id: str) -> Dict[str, Any]:
        """获取统计信息"""
        stats = self.breakers[service_id]
        return {
            "state": stats.state.value,
            "failure_count": stats.failure_count,
            "success_count": stats.success_count,
            "last_failure_time": stats.last_failure_time
        }


class RateLimiter:
    """限流器"""
    
    def __init__(self, config: GatewayConfig, redis_client: Optional[redis.Redis] = None):
        self.config = config
        self.redis_client = redis_client
        self.local_limits: Dict[str, deque] = defaultdict(deque)
        self.logger = logging.getLogger(__name__)
    
    def is_allowed(self, client_id: str, endpoint: str = "*") -> Tuple[bool, Dict[str, Any]]:
        """检查是否允许请求"""
        if not self.config.rate_limit_enabled:
            return True, {"limit_type": "unlimited"}
        
        key = f"{client_id}:{endpoint}"
        
        if self.redis_client:
            return self._check_redis_limit(key)
        else:
            return self._check_local_limit(key)
    
    def _check_redis_limit(self, key: str) -> Tuple[bool, Dict[str, Any]]:
        """使用Redis检查限流"""
        now = time.time()
        minute_key = f"rate:minute:{key}"
        hour_key = f"rate:hour:{key}"
        
        pipe = self.redis_client.pipeline()
        
        minute_count = pipe.incr(minute_key)
        pipe.expire(minute_key, 60)
        hour_count = pipe.incr(hour_key)
        pipe.expire(hour_key, 3600)
        
        results = pipe.execute()
        
        minute_count = results[0]
        hour_count = results[2]
        
        if minute_count > self.config.rate_limit_requests_per_minute:
            return False, {
                "limit_type": "minute",
                "current": minute_count,
                "limit": self.config.rate_limit_requests_per_minute,
                "retry_after": 60
            }
        
        if hour_count > self.config.rate_limit_requests_per_hour:
            return False, {
                "limit_type": "hour",
                "current": hour_count,
                "limit": self.config.rate_limit_requests_per_hour,
                "retry_after": 3600
            }
        
        return True, {
            "limit_type": "success",
            "minute_count": minute_count,
            "hour_count": hour_count
        }
    
    def _check_local_limit(self, key: str) -> Tuple[bool, Dict[str, Any]]:
        """使用本地内存检查限流"""
        now = time.time()
        requests = self.local_limits[key]
        
        minute_ago = now - 60
        hour_ago = now - 3600
        
        while requests and requests[0] < minute_ago:
            requests.popleft()
        
        minute_count = len([t for t in requests if t > minute_ago])
        hour_count = len([t for t in requests if t > hour_ago])
        
        if minute_count >= self.config.rate_limit_requests_per_minute:
            return False, {
                "limit_type": "minute",
                "current": minute_count,
                "limit": self.config.rate_limit_requests_per_minute,
                "retry_after": 60
            }
        
        if hour_count >= self.config.rate_limit_requests_per_hour:
            return False, {
                "limit_type": "hour",
                "current": hour_count,
                "limit": self.config.rate_limit_requests_per_hour,
                "retry_after": 3600
            }
        
        requests.append(now)
        return True, {
            "limit_type": "success",
            "minute_count": minute_count + 1,
            "hour_count": hour_count + 1
        }


class AuthManager:
    """认证管理器"""
    
    def __init__(self, config: GatewayConfig):
        self.config = config
        self.security = HTTPBearer()
        self.logger = logging.getLogger(__name__)
    
    def create_token(self, user_id: str, payload: Dict[str, Any] = None) -> str:
        """创建JWT令牌"""
        now = datetime.utcnow()
        exp = now + timedelta(hours=self.config.jwt_expiration_hours)
        
        token_payload = {
            "user_id": user_id,
            "iat": now.timestamp(),
            "exp": exp.timestamp(),
            **(payload or {})
        }
        
        token = jwt.encode(token_payload, self.config.jwt_secret, algorithm=self.config.jwt_algorithm)
        return token
    
    def verify_token(self, token: str) -> Optional[Dict[str, Any]]:
        """验证JWT令牌"""
        try:
            payload = jwt.decode(token, self.config.jwt_secret, algorithms=[self.config.jwt_algorithm])
            return payload
        except jwt.ExpiredSignatureError:
            self.logger.warning("Token expired")
            return None
        except jwt.InvalidTokenError as e:
            self.logger.warning(f"Invalid token: {e}")
            return None
    
    async def authenticate(self, request: Request) -> Optional[Dict[str, Any]]:
        """认证请求"""
        if not self.config.auth_enabled:
            return {"user_id": "anonymous", "role": "guest"}
        
        try:
            credentials: HTTPAuthorizationCredentials = await self.security(request)
            token = credentials.credentials
            payload = self.verify_token(token)
            
            if payload:
                return payload
            else:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid or expired token"
                )
        except Exception as e:
            self.logger.error(f"Authentication error: {e}")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authentication failed"
            )
    
    def check_permission(self, user: Dict[str, Any], required_role: str) -> bool:
        """检查权限"""
        user_role = user.get("role", "guest")
        role_hierarchy = {
            "admin": 3,
            "editor": 2,
            "viewer": 1,
            "guest": 0
        }
        
        return role_hierarchy.get(user_role, 0) >= role_hierarchy.get(required_role, 0)


class RequestValidator:
    """请求验证器"""
    
    def __init__(self, config: GatewayConfig):
        self.config = config
        self.logger = logging.getLogger(__name__)
    
    async def validate_request(self, request: Request) -> Tuple[bool, Optional[str]]:
        """验证请求"""
        content_length = request.headers.get("content-length", 0)
        
        if int(content_length) > self.config.max_request_size:
            return False, f"Request size exceeds maximum allowed size of {self.config.max_request_size} bytes"
        
        content_type = request.headers.get("content-type", "")
        
        if request.method in ["POST", "PUT", "PATCH"] and not content_type:
            return False, "Content-Type header is required for this request"
        
        user_agent = request.headers.get("user-agent", "")
        if not user_agent:
            self.logger.warning("Request without User-Agent header")
        
        return True, None
    
    def validate_path(self, path: str) -> bool:
        """验证路径安全性"""
        if ".." in path or path.startswith("/"):
            return False
        
        if path.startswith("//"):
            return False
        
        return True
    
    def sanitize_headers(self, headers: Dict[str, str]) -> Dict[str, str]:
        """清理请求头"""
        sensitive_headers = ["authorization", "cookie", "x-api-key"]
        return {k: v for k, v in headers.items() if k.lower() not in sensitive_headers}


class GatewayMetrics:
    """网关指标"""
    
    def __init__(self):
        self.request_counter = Counter(
            "gateway_requests_total",
            "Total requests through gateway",
            ["method", "endpoint", "status"]
        )
        
        self.request_duration = Histogram(
            "gateway_request_duration_seconds",
            "Request duration through gateway",
            ["method", "endpoint"]
        )
        
        self.active_requests = Gauge(
            "gateway_active_requests",
            "Active requests being processed"
        )
        
        self.rate_limit_hits = Counter(
            "gateway_rate_limit_hits_total",
            "Total rate limit violations",
            ["client_id", "endpoint"]
        )
        
        self.circuit_breaker_trips = Counter(
            "gateway_circuit_breaker_trips_total",
            "Total circuit breaker trips",
            ["service_id"]
        )
        
        self.auth_failures = Counter(
            "gateway_auth_failures_total",
            "Total authentication failures",
            ["reason"]
        )


class GatewayLogger:
    """网关日志记录器"""
    
    def __init__(self, config: GatewayConfig):
        self.config = config
        self.logger = logging.getLogger("gateway")
        
        if config.logging_enabled:
            self.logger.setLevel(getattr(logging, config.log_level))
            
            handler = logging.StreamHandler()
            formatter = logging.Formatter(
                '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
            )
            handler.setFormatter(formatter)
            self.logger.addHandler(handler)
    
    def log_request(self, request: Request, response: Response, duration: float):
        """记录请求"""
        if not self.config.logging_enabled:
            return
        
        log_data = {
            "method": request.method,
            "path": request.url.path,
            "status_code": response.status_code,
            "duration_ms": round(duration * 1000, 2),
            "client_ip": request.client.host if request.client else "unknown",
            "user_agent": request.headers.get("user-agent", "unknown"),
            "timestamp": datetime.utcnow().isoformat()
        }
        
        self.logger.info(f"Request: {json.dumps(log_data)}")
    
    def log_error(self, error: Exception, request: Request):
        """记录错误"""
        if not self.config.logging_enabled:
            return
        
        log_data = {
            "error_type": type(error).__name__,
            "error_message": str(error),
            "path": request.url.path,
            "method": request.method,
            "client_ip": request.client.host if request.client else "unknown",
            "timestamp": datetime.utcnow().isoformat()
        }
        
        self.logger.error(f"Error: {json.dumps(log_data)}")


class RequestRouter:
    """请求路由器"""
    
    def __init__(self, config: GatewayConfig, 
                 service_registry: ServiceRegistry,
                 service_discovery: ServiceDiscovery,
                 load_balancer: ServiceLoadBalancer):
        self.config = config
        self.service_registry = service_registry
        self.service_discovery = service_discovery
        self.load_balancer = load_balancer
        self.routes: List[RouteRule] = []
        self.logger = logging.getLogger(__name__)
        
        self._initialize_default_routes()
    
    def _initialize_default_routes(self):
        """初始化默认路由"""
        default_routes = [
            RouteRule("/api/video/*", ServiceType.VIDEO_PROCESSING),
            RouteRule("/api/render/*", ServiceType.RENDER_ENGINE),
            RouteRule("/api/storage/*", ServiceType.STORAGE_SERVICE),
            RouteRule("/api/cache/*", ServiceType.CACHE_SERVICE),
            RouteRule("/api/auth/*", ServiceType.AUTH_SERVICE),
            RouteRule("/api/project/*", ServiceType.PROJECT_SERVICE),
            RouteRule("/api/plugin/*", ServiceType.PLUGIN_MANAGER),
            RouteRule("/api/export/*", ServiceType.EXPORT_SERVICE),
            RouteRule("/api/ai/*", ServiceType.AI_SERVICE),
            RouteRule("/api/monitor/*", ServiceType.MONITORING_SERVICE),
            RouteRule("/api/notification/*", ServiceType.NOTIFICATION_SERVICE),
            RouteRule("/api/backup/*", ServiceType.BACKUP_SERVICE),
            RouteRule("/api/config/*", ServiceType.CONFIG_SERVICE),
        ]
        
        self.routes.extend(default_routes)
    
    def add_route(self, route: RouteRule):
        """添加路由"""
        self.routes.append(route)
        self.logger.info(f"Added route: {route.path} -> {route.service_type.value}")
    
    def find_route(self, path: str, method: str) -> Optional[RouteRule]:
        """查找匹配的路由"""
        for route in self.routes:
            if self._match_path(route.path, path) and method in route.methods:
                return route
        return None
    
    def _match_path(self, pattern: str, path: str) -> bool:
        """匹配路径"""
        if pattern.endswith("/*"):
            prefix = pattern[:-2]
            return path.startswith(prefix)
        return pattern == path
    
    async def route_request(self, request: Request, route: RouteRule) -> Optional[str]:
        """路由请求到服务实例"""
        services = self.service_registry.get_services(route.service_type)
        
        if not services:
            self.logger.warning(f"No available services for {route.service_type.value}")
            return None
        
        selected_service = self.load_balancer.select_service(services)
        return selected_service


class APIGateway:
    """API网关主类"""
    
    def __init__(self, config: GatewayConfig,
                 service_registry: ServiceRegistry,
                 service_discovery: ServiceDiscovery,
                 load_balancer: ServiceLoadBalancer,
                 redis_client: Optional[redis.Redis] = None):
        self.config = config
        self.service_registry = service_registry
        self.service_discovery = service_discovery
        self.load_balancer = load_balancer
        
        self.circuit_breaker = CircuitBreaker(config)
        self.rate_limiter = RateLimiter(config, redis_client)
        self.auth_manager = AuthManager(config)
        self.request_validator = RequestValidator(config)
        self.gateway_logger = GatewayLogger(config)
        self.request_router = RequestRouter(config, service_registry, service_discovery, load_balancer)
        self.metrics = GatewayMetrics()
        
        self.session: Optional[aiohttp.ClientSession] = None
        self.logger = logging.getLogger(__name__)
    
    async def initialize(self):
        """初始化网关"""
        self.session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=self.config.request_timeout))
        self.logger.info("API Gateway initialized")
    
    async def shutdown(self):
        """关闭网关"""
        if self.session:
            await self.session.close()
        self.logger.info("API Gateway shutdown")
    
    async def handle_request(self, request: Request) -> Response:
        """处理请求"""
        start_time = time.time()
        client_id = self._get_client_id(request)
        
        self.metrics.active_requests.inc()
        
        try:
            route = self.request_router.find_route(request.url.path, request.method)
            
            if not route:
                raise HTTPException(status_code=404, detail="Route not found")
            
            valid, error_msg = await self.request_validator.validate_request(request)
            if not valid:
                raise HTTPException(status_code=400, detail=error_msg)
            
            if route.auth_required:
                user = await self.auth_manager.authenticate(request)
            else:
                user = {"user_id": "anonymous", "role": "guest"}
            
            allowed, limit_info = self.rate_limiter.is_allowed(client_id, request.url.path)
            if not allowed:
                self.metrics.rate_limit_hits.labels(client_id=client_id, endpoint=request.url.path).inc()
                raise HTTPException(
                    status_code=429,
                    detail=f"Rate limit exceeded: {limit_info}",
                    headers={"Retry-After": str(limit_info.get("retry_after", 60))}
                )
            
            service_url = await self.request_router.route_request(request, route)
            
            if not service_url:
                raise HTTPException(status_code=503, detail="Service unavailable")
            
            service_id = service_url.split(":")[-1]
            
            if not self.circuit_breaker.is_allowed(service_id):
                self.metrics.circuit_breaker_trips.labels(service_id=service_id).inc()
                raise HTTPException(status_code=503, detail="Circuit breaker is open")
            
            response = await self._proxy_request(request, service_url, user)
            
            if response.status_code < 500:
                self.circuit_breaker.record_success(service_id)
            else:
                self.circuit_breaker.record_failure(service_id)
            
            duration = time.time() - start_time
            self._record_metrics(request, response, duration)
            
            return response
            
        except HTTPException:
            raise
        except Exception as e:
            self.gateway_logger.log_error(e, request)
            duration = time.time() - start_time
            raise HTTPException(status_code=500, detail="Internal server error")
        finally:
            self.metrics.active_requests.dec()
    
    async def _proxy_request(self, request: Request, service_url: str, user: Dict[str, Any]) -> Response:
        """代理请求到后端服务"""
        url = f"{service_url}{request.url.path}"
        headers = dict(request.headers)
        headers["X-User-ID"] = user.get("user_id", "anonymous")
        headers["X-User-Role"] = user.get("role", "guest")
        
        body = await request.body() if request.method in ["POST", "PUT", "PATCH"] else None
        
        async with self.session.request(
            method=request.method,
            url=url,
            headers=headers,
            data=body,
            params=request.query_params
        ) as response:
            content = await response.read()
            
            return Response(
                content=content,
                status_code=response.status,
                headers=dict(response.headers),
                media_type=response.headers.get("content-type", "application/json")
            )
    
    def _get_client_id(self, request: Request) -> str:
        """获取客户端ID"""
        forwarded_for = request.headers.get("X-Forwarded-For", "")
        if forwarded_for:
            return forwarded_for.split(",")[0].strip()
        
        return request.client.host if request.client else "unknown"
    
    def _record_metrics(self, request: Request, response: Response, duration: float):
        """记录指标"""
        self.metrics.request_counter.labels(
            method=request.method,
            endpoint=request.url.path,
            status=response.status_code
        ).inc()
        
        self.metrics.request_duration.labels(
            method=request.method,
            endpoint=request.url.path
        ).observe(duration)
    
    def add_route(self, route: RouteRule):
        """添加路由规则"""
        self.request_router.add_route(route)
    
    def get_stats(self) -> Dict[str, Any]:
        """获取网关统计信息"""
        return {
            "circuit_breakers": {
                service_id: self.circuit_breaker.get_stats(service_id)
                for service_id in self.circuit_breaker.breakers.keys()
            },
            "active_routes": len(self.request_router.routes),
            "registered_services": len(self.service_registry.get_all_services())
        }


_global_gateway: Optional[APIGateway] = None


def get_gateway(config: Optional[GatewayConfig] = None,
                service_registry: Optional[ServiceRegistry] = None,
                service_discovery: Optional[ServiceDiscovery] = None,
                load_balancer: Optional[ServiceLoadBalancer] = None,
                redis_client: Optional[redis.Redis] = None) -> APIGateway:
    """获取全局网关实例"""
    global _global_gateway
    
    if _global_gateway is None:
        if config is None:
            config = GatewayConfig()
        if service_registry is None:
            service_registry = get_service_registry()
        if service_discovery is None:
            service_discovery = get_service_discovery()
        if load_balancer is None:
            load_balancer = get_load_balancer()
        
        _global_gateway = APIGateway(
            config=config,
            service_registry=service_registry,
            service_discovery=service_discovery,
            load_balancer=load_balancer,
            redis_client=redis_client
        )
    
    return _global_gateway


def get_service_registry() -> ServiceRegistry:
    """获取服务注册中心"""
    from app.core.service_decomposition import get_service_registry as _get_registry
    return _get_registry()


def get_service_discovery() -> ServiceDiscovery:
    """获取服务发现"""
    from app.core.service_decomposition import get_service_discovery as _get_discovery
    return _get_discovery()


def get_load_balancer() -> ServiceLoadBalancer:
    """获取负载均衡器"""
    from app.core.service_decomposition import get_load_balancer as _get_balancer
    return _get_balancer()


async def create_gateway(config: Optional[GatewayConfig] = None,
                        redis_client: Optional[redis.Redis] = None) -> APIGateway:
    """创建并初始化网关"""
    gateway = get_gateway(config=config, redis_client=redis_client)
    await gateway.initialize()
    return gateway
