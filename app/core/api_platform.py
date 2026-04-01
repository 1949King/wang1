import asyncio
import json
import time
import uuid
import hashlib
import hmac
from typing import Dict, List, Optional, Set, Any, Tuple, Callable
from dataclasses import dataclass, field, asdict
from enum import Enum
from datetime import datetime, timedelta
from collections import defaultdict, deque
import logging
import redis
import jwt
import requests
import urllib.parse
from pathlib import Path
from functools import wraps
import aiohttp

from app.core.service_decomposition import ServiceType


class APIStatus(Enum):
    """API状态"""
    ACTIVE = "active"
    INACTIVE = "inactive"
    BETA = "beta"
    DEPRECATED = "deprecated"
    RETIRED = "retired"


class APIAccessLevel(Enum):
    """API访问级别"""
    PUBLIC = "public"
    BASIC = "basic"
    PREMIUM = "premium"
    ENTERPRISE = "enterprise"
    ADMIN = "admin"


class APIKeyType(Enum):
    """API密钥类型"""
    CLIENT = "client"
    SERVER = "server"
    SERVICE = "service"
    TEST = "test"


class RateLimitPeriod(Enum):
    """限流周期"""
    MINUTE = "minute"
    HOUR = "hour"
    DAY = "day"
    MONTH = "month"


class WebhookEvent(Enum):
    """Webhook事件"""
    API_REQUEST = "api_request"
    API_ERROR = "api_error"
    RATE_LIMIT = "rate_limit"
    SUBSCRIPTION_CHANGE = "subscription_change"
    USAGE_ALERT = "usage_alert"


@dataclass
class APIKey:
    """API密钥"""
    key_id: str
    api_key: str
    user_id: str
    key_type: APIKeyType
    access_level: APIAccessLevel
    status: APIStatus
    created_at: float
    updated_at: float
    expires_at: Optional[float] = None
    description: Optional[str] = None
    scopes: List[str] = field(default_factory=list)
    rate_limits: Dict[str, int] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class APIRateLimit:
    """API限流"""
    period: RateLimitPeriod
    limit: int
    remaining: int
    reset_at: float


@dataclass
class APIUsage:
    """API使用统计"""
    user_id: str
    endpoint: str
    method: str
    status_code: int
    response_time: float
    timestamp: float
    api_key: str
    client_ip: str
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Webhook:
    """Webhook"""
    webhook_id: str
    user_id: str
    url: str
    events: List[WebhookEvent]
    secret: str
    created_at: float
    updated_at: float
    status: APIStatus
    last_delivery: Optional[float] = None
    last_error: Optional[str] = None


@dataclass
class APISpec:
    """API规范"""
    endpoint: str
    method: str
    description: str
    parameters: List[Dict[str, Any]]
    responses: Dict[int, Dict[str, Any]]
    access_level: APIAccessLevel
    rate_limit: Dict[str, int]
    tags: List[str] = field(default_factory=list)
    deprecated: bool = False
    version: str = "1.0"


@dataclass
class APIDocumentation:
    """API文档"""
    api_id: str
    title: str
    description: str
    spec: APISpec
    examples: List[Dict[str, Any]] = field(default_factory=list)
    changelog: List[Dict[str, Any]] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)


class APIKeyManager:
    """API密钥管理器"""
    
    def __init__(self, redis_client: Optional[redis.Redis] = None):
        self.redis_client = redis_client
        self.api_keys: Dict[str, APIKey] = {}
        self.logger = logging.getLogger(__name__)
    
    def generate_api_key(self, user_id: str, key_type: APIKeyType, 
                        access_level: APIAccessLevel, description: Optional[str] = None, 
                        scopes: List[str] = None, rate_limits: Dict[str, int] = None) -> APIKey:
        """生成API密钥"""
        key_id = str(uuid.uuid4())
        api_key = f"sk_{uuid.uuid4().hex}"
        
        api_key_obj = APIKey(
            key_id=key_id,
            api_key=api_key,
            user_id=user_id,
            key_type=key_type,
            access_level=access_level,
            status=APIStatus.ACTIVE,
            created_at=time.time(),
            updated_at=time.time(),
            description=description,
            scopes=scopes or [],
            rate_limits=rate_limits or {}
        )
        
        self.api_keys[api_key] = api_key_obj
        
        if self.redis_client:
            self._cache_api_key(api_key_obj)
        
        self.logger.info(f"Generated API key for user: {user_id}")
        return api_key_obj
    
    def get_api_key(self, api_key: str) -> Optional[APIKey]:
        """获取API密钥"""
        if api_key in self.api_keys:
            return self.api_keys[api_key]
        
        if self.redis_client:
            return self._get_cached_api_key(api_key)
        
        return None
    
    def validate_api_key(self, api_key: str) -> Tuple[bool, Optional[APIKey]]:
        """验证API密钥"""
        key = self.get_api_key(api_key)
        if not key:
            return False, None
        
        if key.status != APIStatus.ACTIVE:
            return False, key
        
        if key.expires_at and key.expires_at < time.time():
            return False, key
        
        return True, key
    
    def revoke_api_key(self, api_key: str) -> bool:
        """撤销API密钥"""
        key = self.get_api_key(api_key)
        if not key:
            return False
        
        key.status = APIStatus.INACTIVE
        key.updated_at = time.time()
        
        if self.redis_client:
            self._update_cached_api_key(key)
        
        self.logger.info(f"Revoked API key: {api_key}")
        return True
    
    def update_api_key(self, api_key: str, **kwargs) -> Optional[APIKey]:
        """更新API密钥"""
        key = self.get_api_key(api_key)
        if not key:
            return None
        
        for k, v in kwargs.items():
            if hasattr(key, k):
                setattr(key, k, v)
        
        key.updated_at = time.time()
        
        if self.redis_client:
            self._update_cached_api_key(key)
        
        return key
    
    def get_user_api_keys(self, user_id: str) -> List[APIKey]:
        """获取用户的API密钥"""
        return [key for key in self.api_keys.values() if key.user_id == user_id]
    
    def _cache_api_key(self, api_key: APIKey):
        """缓存API密钥到Redis"""
        key = f"api_key:{api_key.api_key}"
        data = json.dumps(asdict(api_key))
        self.redis_client.setex(key, 86400, data)
    
    def _get_cached_api_key(self, api_key: str) -> Optional[APIKey]:
        """从Redis获取缓存的API密钥"""
        key = f"api_key:{api_key}"
        data = self.redis_client.get(key)
        if data:
            key_data = json.loads(data)
            key_data['key_type'] = APIKeyType(key_data['key_type'])
            key_data['access_level'] = APIAccessLevel(key_data['access_level'])
            key_data['status'] = APIStatus(key_data['status'])
            return APIKey(**key_data)
        return None
    
    def _update_cached_api_key(self, api_key: APIKey):
        """更新Redis中的API密钥缓存"""
        key = f"api_key:{api_key.api_key}"
        data = json.dumps(asdict(api_key))
        self.redis_client.setex(key, 86400, data)


class RateLimitManager:
    """限流管理器"""
    
    def __init__(self, redis_client: Optional[redis.Redis] = None):
        self.redis_client = redis_client
        self.local_limits: Dict[str, Dict[str, int]] = defaultdict(dict)
        self.logger = logging.getLogger(__name__)
    
    def check_rate_limit(self, api_key: str, endpoint: str, 
                        method: str, limits: Dict[str, int]) -> Tuple[bool, APIRateLimit]:
        """检查限流"""
        if self.redis_client:
            return self._check_redis_rate_limit(api_key, endpoint, method, limits)
        else:
            return self._check_local_rate_limit(api_key, endpoint, method, limits)
    
    def _check_redis_rate_limit(self, api_key: str, endpoint: str, 
                               method: str, limits: Dict[str, int]) -> Tuple[bool, APIRateLimit]:
        """使用Redis检查限流"""
        key = f"rate_limit:{api_key}:{endpoint}:{method}"
        now = time.time()
        
        for period, limit in limits.items():
            if period == "minute":
                window = 60
            elif period == "hour":
                window = 3600
            elif period == "day":
                window = 86400
            else:
                continue
            
            count = self.redis_client.incr(key)
            if count == 1:
                self.redis_client.expire(key, window)
            
            remaining = max(0, limit - count)
            reset_at = now + (window - (now % window))
            
            if count > limit:
                return False, APIRateLimit(
                    period=RateLimitPeriod(period),
                    limit=limit,
                    remaining=remaining,
                    reset_at=reset_at
                )
        
        return True, APIRateLimit(
            period=RateLimitPeriod("minute"),
            limit=limits.get("minute", 60),
            remaining=limits.get("minute", 60) - 1,
            reset_at=now + (60 - (now % 60))
        )
    
    def _check_local_rate_limit(self, api_key: str, endpoint: str, 
                               method: str, limits: Dict[str, int]) -> Tuple[bool, APIRateLimit]:
        """使用本地内存检查限流"""
        key = f"{api_key}:{endpoint}:{method}"
        now = time.time()
        
        for period, limit in limits.items():
            if period == "minute":
                window = 60
            elif period == "hour":
                window = 3600
            elif period == "day":
                window = 86400
            else:
                continue
            
            period_key = f"{key}:{period}"
            
            if period_key not in self.local_limits:
                self.local_limits[period_key] = {}
            
            current_time = int(now / window) * window
            
            if current_time not in self.local_limits[period_key]:
                self.local_limits[period_key][current_time] = 0
            
            self.local_limits[period_key][current_time] += 1
            
            count = self.local_limits[period_key][current_time]
            remaining = max(0, limit - count)
            reset_at = current_time + window
            
            if count > limit:
                return False, APIRateLimit(
                    period=RateLimitPeriod(period),
                    limit=limit,
                    remaining=remaining,
                    reset_at=reset_at
                )
        
        return True, APIRateLimit(
            period=RateLimitPeriod("minute"),
            limit=limits.get("minute", 60),
            remaining=limits.get("minute", 60) - 1,
            reset_at=now + (60 - (now % 60))
        )
    
    def get_rate_limit_status(self, api_key: str, endpoint: str, 
                            method: str, limits: Dict[str, int]) -> Dict[str, Any]:
        """获取限流状态"""
        status = {}
        now = time.time()
        
        for period, limit in limits.items():
            if period == "minute":
                window = 60
            elif period == "hour":
                window = 3600
            elif period == "day":
                window = 86400
            else:
                continue
            
            if self.redis_client:
                key = f"rate_limit:{api_key}:{endpoint}:{method}"
                count = int(self.redis_client.get(key) or 0)
            else:
                key = f"{api_key}:{endpoint}:{method}:{period}"
                current_time = int(now / window) * window
                count = self.local_limits.get(key, {}).get(current_time, 0)
            
            remaining = max(0, limit - count)
            reset_at = now + (window - (now % window))
            
            status[period] = {
                "limit": limit,
                "remaining": remaining,
                "reset_at": reset_at
            }
        
        return status


class APIUsageManager:
    """API使用统计管理器"""
    
    def __init__(self, redis_client: Optional[redis.Redis] = None):
        self.redis_client = redis_client
        self.usage_records: List[APIUsage] = []
        self.logger = logging.getLogger(__name__)
    
    def record_usage(self, user_id: str, endpoint: str, method: str, 
                    status_code: int, response_time: float, 
                    api_key: str, client_ip: str, 
                    metadata: Optional[Dict[str, Any]] = None):
        """记录API使用"""
        usage = APIUsage(
            user_id=user_id,
            endpoint=endpoint,
            method=method,
            status_code=status_code,
            response_time=response_time,
            timestamp=time.time(),
            api_key=api_key,
            client_ip=client_ip,
            metadata=metadata or {}
        )
        
        self.usage_records.append(usage)
        
        if self.redis_client:
            self._cache_usage(usage)
        
        if len(self.usage_records) > 1000:
            self.usage_records = self.usage_records[-1000:]
    
    def get_user_usage(self, user_id: str, start_time: Optional[float] = None, 
                      end_time: Optional[float] = None) -> List[APIUsage]:
        """获取用户API使用记录"""
        if not start_time:
            start_time = time.time() - 86400
        if not end_time:
            end_time = time.time()
        
        return [
            usage for usage in self.usage_records
            if usage.user_id == user_id and start_time <= usage.timestamp <= end_time
        ]
    
    def get_endpoint_usage(self, endpoint: str, start_time: Optional[float] = None, 
                          end_time: Optional[float] = None) -> List[APIUsage]:
        """获取端点API使用记录"""
        if not start_time:
            start_time = time.time() - 86400
        if not end_time:
            end_time = time.time()
        
        return [
            usage for usage in self.usage_records
            if usage.endpoint == endpoint and start_time <= usage.timestamp <= end_time
        ]
    
    def get_usage_stats(self, start_time: Optional[float] = None, 
                       end_time: Optional[float] = None) -> Dict[str, Any]:
        """获取API使用统计"""
        if not start_time:
            start_time = time.time() - 86400
        if not end_time:
            end_time = time.time()
        
        stats = {
            "total_requests": 0,
            "by_status": defaultdict(int),
            "by_endpoint": defaultdict(int),
            "by_method": defaultdict(int),
            "average_response_time": 0,
            "total_response_time": 0
        }
        
        filtered_usage = [
            usage for usage in self.usage_records
            if start_time <= usage.timestamp <= end_time
        ]
        
        for usage in filtered_usage:
            stats["total_requests"] += 1
            stats["by_status"][usage.status_code] += 1
            stats["by_endpoint"][usage.endpoint] += 1
            stats["by_method"][usage.method] += 1
            stats["total_response_time"] += usage.response_time
        
        if filtered_usage:
            stats["average_response_time"] = stats["total_response_time"] / len(filtered_usage)
        
        stats["by_status"] = dict(stats["by_status"])
        stats["by_endpoint"] = dict(stats["by_endpoint"])
        stats["by_method"] = dict(stats["by_method"])
        
        return stats
    
    def _cache_usage(self, usage: APIUsage):
        """缓存使用记录到Redis"""
        key = f"usage:{usage.user_id}:{int(usage.timestamp / 3600)}"
        data = json.dumps(asdict(usage))
        self.redis_client.lpush(key, data)
        self.redis_client.expire(key, 86400 * 7)


class WebhookManager:
    """Webhook管理器"""
    
    def __init__(self, redis_client: Optional[redis.Redis] = None):
        self.redis_client = redis_client
        self.webhooks: Dict[str, Webhook] = {}
        self.logger = logging.getLogger(__name__)
    
    def create_webhook(self, user_id: str, url: str, events: List[WebhookEvent], 
                      secret: Optional[str] = None) -> Webhook:
        """创建Webhook"""
        webhook_id = str(uuid.uuid4())
        if not secret:
            secret = uuid.uuid4().hex
        
        webhook = Webhook(
            webhook_id=webhook_id,
            user_id=user_id,
            url=url,
            events=events,
            secret=secret,
            created_at=time.time(),
            updated_at=time.time(),
            status=APIStatus.ACTIVE
        )
        
        self.webhooks[webhook_id] = webhook
        
        if self.redis_client:
            self._cache_webhook(webhook)
        
        return webhook
    
    def get_webhook(self, webhook_id: str) -> Optional[Webhook]:
        """获取Webhook"""
        if webhook_id in self.webhooks:
            return self.webhooks[webhook_id]
        
        if self.redis_client:
            return self._get_cached_webhook(webhook_id)
        
        return None
    
    def get_user_webhooks(self, user_id: str) -> List[Webhook]:
        """获取用户的Webhook"""
        return [webhook for webhook in self.webhooks.values() if webhook.user_id == user_id]
    
    async def deliver_webhook(self, webhook: Webhook, event: WebhookEvent, 
                            payload: Dict[str, Any]) -> bool:
        """发送Webhook"""
        if webhook.status != APIStatus.ACTIVE:
            return False
        
        if event not in webhook.events:
            return False
        
        try:
            headers = {
                "Content-Type": "application/json",
                "X-Webhook-Event": event.value,
                "X-Webhook-Signature": self._generate_webhook_signature(webhook.secret, payload)
            }
            
            async with aiohttp.ClientSession() as session:
                async with session.post(webhook.url, json=payload, headers=headers) as response:
                    if response.status >= 200 and response.status < 300:
                        webhook.last_delivery = time.time()
                        webhook.last_error = None
                        webhook.updated_at = time.time()
                        
                        if self.redis_client:
                            self._update_cached_webhook(webhook)
                        
                        return True
                    else:
                        webhook.last_error = f"HTTP {response.status}"
                        webhook.updated_at = time.time()
                        
                        if self.redis_client:
                            self._update_cached_webhook(webhook)
                        
                        return False
        except Exception as e:
            webhook.last_error = str(e)
            webhook.updated_at = time.time()
            
            if self.redis_client:
                self._update_cached_webhook(webhook)
            
            self.logger.error(f"Error delivering webhook: {e}")
            return False
    
    def _generate_webhook_signature(self, secret: str, payload: Dict[str, Any]) -> str:
        """生成Webhook签名"""
        payload_str = json.dumps(payload, sort_keys=True)
        signature = hmac.new(secret.encode(), payload_str.encode(), hashlib.sha256).hexdigest()
        return f"sha256={signature}"
    
    def _cache_webhook(self, webhook: Webhook):
        """缓存Webhook到Redis"""
        key = f"webhook:{webhook.webhook_id}"
        data = json.dumps({
            **asdict(webhook),
            "events": [e.value for e in webhook.events]
        })
        self.redis_client.setex(key, 86400, data)
    
    def _get_cached_webhook(self, webhook_id: str) -> Optional[Webhook]:
        """从Redis获取缓存的Webhook"""
        key = f"webhook:{webhook_id}"
        data = self.redis_client.get(key)
        if data:
            webhook_data = json.loads(data)
            webhook_data['events'] = [WebhookEvent(e) for e in webhook_data['events']]
            webhook_data['status'] = APIStatus(webhook_data['status'])
            return Webhook(**webhook_data)
        return None
    
    def _update_cached_webhook(self, webhook: Webhook):
        """更新Redis中的Webhook缓存"""
        key = f"webhook:{webhook.webhook_id}"
        data = json.dumps({
            **asdict(webhook),
            "events": [e.value for e in webhook.events]
        })
        self.redis_client.setex(key, 86400, data)


class APIDocumentationManager:
    """API文档管理器"""
    
    def __init__(self, docs_dir: str):
        self.docs_dir = Path(docs_dir)
        self.docs_dir.mkdir(parents=True, exist_ok=True)
        self.documentation: Dict[str, APIDocumentation] = {}
        self.logger = logging.getLogger(__name__)
        
        self._load_documentation()
    
    def _load_documentation(self):
        """加载文档"""
        for doc_file in self.docs_dir.rglob("*.json"):
            try:
                with open(doc_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                
                spec = APISpec(**data['spec'])
                doc = APIDocumentation(
                    api_id=data['api_id'],
                    title=data['title'],
                    description=data['description'],
                    spec=spec,
                    examples=data.get('examples', []),
                    changelog=data.get('changelog', []),
                    created_at=data.get('created_at', time.time()),
                    updated_at=data.get('updated_at', time.time())
                )
                
                self.documentation[doc.api_id] = doc
            except Exception as e:
                self.logger.error(f"Error loading documentation {doc_file}: {e}")
    
    def create_documentation(self, api_id: str, title: str, description: str, 
                           spec: APISpec, examples: List[Dict[str, Any]] = None) -> APIDocumentation:
        """创建API文档"""
        doc = APIDocumentation(
            api_id=api_id,
            title=title,
            description=description,
            spec=spec,
            examples=examples or []
        )
        
        self.documentation[api_id] = doc
        self._save_documentation(doc)
        
        return doc
    
    def _save_documentation(self, doc: APIDocumentation):
        """保存文档到文件"""
        doc_file = self.docs_dir / f"{doc.api_id}.json"
        data = {
            "api_id": doc.api_id,
            "title": doc.title,
            "description": doc.description,
            "spec": asdict(doc.spec),
            "examples": doc.examples,
            "changelog": doc.changelog,
            "created_at": doc.created_at,
            "updated_at": doc.updated_at
        }
        
        with open(doc_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    
    def get_documentation(self, api_id: str) -> Optional[APIDocumentation]:
        """获取API文档"""
        return self.documentation.get(api_id)
    
    def get_all_documentation(self) -> List[APIDocumentation]:
        """获取所有API文档"""
        return list(self.documentation.values())
    
    def update_documentation(self, api_id: str, **kwargs) -> Optional[APIDocumentation]:
        """更新API文档"""
        doc = self.get_documentation(api_id)
        if not doc:
            return None
        
        for k, v in kwargs.items():
            if hasattr(doc, k):
                setattr(doc, k, v)
        
        doc.updated_at = time.time()
        self._save_documentation(doc)
        
        return doc


class APIOpenPlatform:
    """API开放平台"""
    
    def __init__(self, docs_dir: str = "./docs", 
                 redis_client: Optional[redis.Redis] = None):
        self.docs_dir = docs_dir
        self.redis_client = redis_client
        
        self.api_key_manager = APIKeyManager(redis_client)
        self.rate_limit_manager = RateLimitManager(redis_client)
        self.usage_manager = APIUsageManager(redis_client)
        self.webhook_manager = WebhookManager(redis_client)
        self.documentation_manager = APIDocumentationManager(docs_dir)
        
        self.api_specs: Dict[str, APISpec] = {}
        self.logger = logging.getLogger(__name__)
        
        self._initialize_api_specs()
    
    def _initialize_api_specs(self):
        """初始化API规范"""
        # 示例API规范
        specs = [
            APISpec(
                endpoint="/api/video/process",
                method="POST",
                description="处理视频",
                parameters=[
                    {
                        "name": "video_url",
                        "in": "body",
                        "required": True,
                        "schema": {"type": "string"}
                    }
                ],
                responses={
                    200: {"description": "成功"},
                    400: {"description": "请求错误"}
                },
                access_level=APIAccessLevel.BASIC,
                rate_limit={"minute": 60, "hour": 1000}
            ),
            APISpec(
                endpoint="/api/render/preview",
                method="GET",
                description="渲染预览",
                parameters=[
                    {
                        "name": "project_id",
                        "in": "query",
                        "required": True,
                        "schema": {"type": "string"}
                    }
                ],
                responses={
                    200: {"description": "成功"},
                    404: {"description": "项目不存在"}
                },
                access_level=APIAccessLevel.PUBLIC,
                rate_limit={"minute": 100, "hour": 10000}
            )
        ]
        
        for spec in specs:
            key = f"{spec.method}:{spec.endpoint}"
            self.api_specs[key] = spec
    
    def register_api(self, spec: APISpec):
        """注册API"""
        key = f"{spec.method}:{spec.endpoint}"
        self.api_specs[key] = spec
        
        self.documentation_manager.create_documentation(
            api_id=key,
            title=spec.endpoint,
            description=spec.description,
            spec=spec
        )
    
    def generate_api_key(self, user_id: str, key_type: APIKeyType, 
                        access_level: APIAccessLevel, description: Optional[str] = None) -> APIKey:
        """生成API密钥"""
        return self.api_key_manager.generate_api_key(
            user_id=user_id,
            key_type=key_type,
            access_level=access_level,
            description=description
        )
    
    def validate_request(self, api_key: str, endpoint: str, 
                        method: str, client_ip: str) -> Tuple[bool, Dict[str, Any]]:
        """验证请求"""
        valid, key = self.api_key_manager.validate_api_key(api_key)
        if not valid:
            return False, {"error": "Invalid API key"}
        
        key = key
        
        spec_key = f"{method}:{endpoint}"
        spec = self.api_specs.get(spec_key)
        if not spec:
            return False, {"error": "API endpoint not found"}
        
        if key.access_level.value < spec.access_level.value:
            return False, {"error": "Insufficient access level"}
        
        allowed, rate_limit = self.rate_limit_manager.check_rate_limit(
            api_key,
            endpoint,
            method,
            spec.rate_limit
        )
        if not allowed:
            return False, {
                "error": "Rate limit exceeded",
                "rate_limit": asdict(rate_limit)
            }
        
        return True, {
            "user_id": key.user_id,
            "access_level": key.access_level.value,
            "rate_limit": asdict(rate_limit)
        }
    
    def record_usage(self, user_id: str, endpoint: str, method: str, 
                    status_code: int, response_time: float, 
                    api_key: str, client_ip: str, 
                    metadata: Optional[Dict[str, Any]] = None):
        """记录API使用"""
        self.usage_manager.record_usage(
            user_id=user_id,
            endpoint=endpoint,
            method=method,
            status_code=status_code,
            response_time=response_time,
            api_key=api_key,
            client_ip=client_ip,
            metadata=metadata
        )
    
    def create_webhook(self, user_id: str, url: str, 
                      events: List[WebhookEvent]) -> Webhook:
        """创建Webhook"""
        return self.webhook_manager.create_webhook(
            user_id=user_id,
            url=url,
            events=events
        )
    
    def get_api_usage(self, user_id: str, days: int = 7) -> Dict[str, Any]:
        """获取API使用统计"""
        start_time = time.time() - (days * 86400)
        end_time = time.time()
        
        usage = self.usage_manager.get_user_usage(user_id, start_time, end_time)
        stats = self.usage_manager.get_usage_stats(start_time, end_time)
        
        return {
            "usage": [asdict(u) for u in usage],
            "stats": stats,
            "period": {
                "start": start_time,
                "end": end_time,
                "days": days
            }
        }
    
    def get_api_documentation(self, api_id: str) -> Optional[APIDocumentation]:
        """获取API文档"""
        return self.documentation_manager.get_documentation(api_id)
    
    def get_all_api_documentation(self) -> List[APIDocumentation]:
        """获取所有API文档"""
        return self.documentation_manager.get_all_documentation()
    
    def get_platform_stats(self) -> Dict[str, Any]:
        """获取平台统计"""
        usage_stats = self.usage_manager.get_usage_stats()
        
        return {
            "api_count": len(self.api_specs),
            "total_requests": usage_stats.get("total_requests", 0),
            "average_response_time": usage_stats.get("average_response_time", 0),
            "active_api_keys": len([k for k in self.api_key_manager.api_keys.values() if k.status == APIStatus.ACTIVE]),
            "webhooks": len(self.webhook_manager.webhooks)
        }


_global_api_platform: Optional[APIOpenPlatform] = None


def get_api_platform(docs_dir: str = "./docs",
                    redis_client: Optional[redis.Redis] = None) -> APIOpenPlatform:
    """获取API开放平台实例"""
    global _global_api_platform
    
    if _global_api_platform is None:
        _global_api_platform = APIOpenPlatform(docs_dir, redis_client)
    
    return _global_api_platform


def create_api_platform(docs_dir: str = "./docs",
                      redis_client: Optional[redis.Redis] = None) -> APIOpenPlatform:
    """创建API开放平台"""
    return APIOpenPlatform(docs_dir, redis_client)
