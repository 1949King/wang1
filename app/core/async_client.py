"""
异步HTTP客户端模块 v1.0
======================
aiohttp封装 + 连接池 + 重试机制 + 超时控制
"""

import asyncio
import aiohttp
import time
import json
import logging
import threading
from typing import Any, Dict, Optional, List, Callable, Union
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
import ssl
import certifi
from functools import wraps

logger = logging.getLogger(__name__)


@dataclass
class RequestConfig:
    """请求配置"""
    timeout: float = 30.0
    connect_timeout: float = 10.0
    max_retries: int = 3
    retry_delay: float = 1.0
    retry_backoff: float = 2.0
    max_connections: int = 100
    max_connections_per_host: int = 10
    enable_cache: bool = True
    cache_ttl: int = 300


@dataclass
class Response:
    """响应数据"""
    status: int
    headers: Dict[str, str]
    data: Any
    url: str
    elapsed: float
    success: bool
    error: Optional[str] = None
    
    def json(self) -> Any:
        if isinstance(self.data, (dict, list)):
            return self.data
        try:
            return json.loads(self.data) if isinstance(self.data, str) else None
        except Exception:
            pass
            return None
    
    def text(self) -> str:
        return str(self.data) if self.data else ""


class AsyncHTTPClient:
    """异步HTTP客户端"""
    
    _instance: Optional['AsyncHTTPClient'] = None
    _lock = threading.Lock()
    
    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        
        self._session: Optional[aiohttp.ClientSession] = None
        self._config = RequestConfig()
        self._cache: Dict[str, tuple] = {}
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._stats = {
            "requests": 0,
            "success": 0,
            "failed": 0,
            "cached": 0,
            "total_time": 0.0,
        }
    
    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            ssl_context = ssl.create_default_context(cafile=certifi.where())
            connector = aiohttp.TCPConnector(
                limit=self._config.max_connections,
                limit_per_host=self._config.max_connections_per_host,
                ssl=ssl_context,
            )
            
            timeout = aiohttp.ClientTimeout(
                total=self._config.timeout,
                connect=self._config.connect_timeout,
            )
            
            self._session = aiohttp.ClientSession(
                connector=connector,
                timeout=timeout,
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                    "Accept": "application/json, text/plain, */*",
                    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
                }
            )
        
        return self._session
    
    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None
    
    def _get_cache_key(self, method: str, url: str, **kwargs) -> str:
        params = kwargs.get("params", {})
        data = kwargs.get("data") or kwargs.get("json")
        cache_data = f"{method}:{url}:{json.dumps(params, sort_keys=True)}:{json.dumps(data, sort_keys=True) if data else ''}"
        import hashlib
        return hashlib.md5(cache_data.encode()).hexdigest()
    
    def _get_from_cache(self, key: str) -> Optional[Response]:
        if not self._config.enable_cache:
            return None
        
        if key in self._cache:
            cached_data, cached_time = self._cache[key]
            if time.time() - cached_time < self._config.cache_ttl:
                self._stats["cached"] += 1
                return cached_data
            else:
                del self._cache[key]
        
        return None
    
    def _set_cache(self, key: str, response: Response):
        if self._config.enable_cache and response.success:
            self._cache[key] = (response, time.time())
    
    async def request(
        self,
        method: str,
        url: str,
        params: Dict = None,
        data: Any = None,
        json_data: Any = None,
        headers: Dict = None,
        cookies: Dict = None,
        **kwargs
    ) -> Response:
        cache_key = self._get_cache_key(method, url, params=params, data=data, json=json_data)
        
        cached = self._get_from_cache(cache_key)
        if cached:
            return cached
        
        session = await self._get_session()
        start_time = time.time()
        
        retries = 0
        last_error = None
        
        while retries <= self._config.max_retries:
            try:
                self._stats["requests"] += 1
                
                request_headers = dict(session.headers)
                if headers:
                    request_headers.update(headers)
                
                async with session.request(
                    method,
                    url,
                    params=params,
                    data=data,
                    json=json_data,
                    headers=request_headers,
                    cookies=cookies,
                    **kwargs
                ) as resp:
                    elapsed = time.time() - start_time
                    
                    content_type = resp.headers.get("Content-Type", "")
                    if "application/json" in content_type:
                        result_data = await resp.json()
                    elif "text/" in content_type:
                        result_data = await resp.text()
                    else:
                        result_data = await resp.read()
                    
                    response = Response(
                        status=resp.status,
                        headers=dict(resp.headers),
                        data=result_data,
                        url=str(resp.url),
                        elapsed=elapsed,
                        success=200 <= resp.status < 300,
                    )
                    
                    self._stats["success"] += 1
                    self._stats["total_time"] += elapsed
                    
                    self._set_cache(cache_key, response)
                    
                    return response
                    
            except asyncio.TimeoutError as e:
                last_error = f"请求超时: {e}"
                logger.warning(f"请求超时 {url}, 重试 {retries}/{self._config.max_retries}")
            except aiohttp.ClientError as e:
                last_error = f"客户端错误: {e}"
                logger.warning(f"请求失败 {url}: {e}, 重试 {retries}/{self._config.max_retries}")
            except Exception as e:
                last_error = f"未知错误: {e}"
                logger.error(f"请求异常 {url}: {e}")
                break
            
            retries += 1
            if retries <= self._config.max_retries:
                delay = self._config.retry_delay * (self._config.retry_backoff ** (retries - 1))
                await asyncio.sleep(delay)
        
        self._stats["failed"] += 1
        elapsed = time.time() - start_time
        self._stats["total_time"] += elapsed
        
        return Response(
            status=0,
            headers={},
            data=None,
            url=url,
            elapsed=elapsed,
            success=False,
            error=last_error or "请求失败",
        )
    
    async def get(self, url: str, params: Dict = None, **kwargs) -> Response:
        return await self.request("GET", url, params=params, **kwargs)
    
    async def post(self, url: str, data: Any = None, json_data: Any = None, **kwargs) -> Response:
        return await self.request("POST", url, data=data, json_data=json_data, **kwargs)
    
    async def put(self, url: str, data: Any = None, json_data: Any = None, **kwargs) -> Response:
        return await self.request("PUT", url, data=data, json_data=json_data, **kwargs)
    
    async def delete(self, url: str, **kwargs) -> Response:
        return await self.request("DELETE", url, **kwargs)
    
    async def download(self, url: str, save_path: str, chunk_size: int = 8192,
                      progress_callback: Callable[[int, int], None] = None) -> bool:
        try:
            session = await self._get_session()
            
            async with session.get(url) as resp:
                if resp.status != 200:
                    return False
                
                total_size = int(resp.headers.get("Content-Length", 0))
                downloaded = 0
                
                path = Path(save_path)
                path.parent.mkdir(parents=True, exist_ok=True)
                
                with open(path, 'wb') as f:
                    async for chunk in resp.content.iter_chunked(chunk_size):
                        f.write(chunk)
                        downloaded += len(chunk)
                        if progress_callback:
                            progress_callback(downloaded, total_size)
                
                return True
                
        except Exception as e:
            logger.error(f"下载失败 {url}: {e}")
            return False
    
    async def batch_requests(
        self,
        requests: List[Dict],
        concurrency: int = 10,
        progress_callback: Callable[[int, int], None] = None
    ) -> List[Response]:
        semaphore = asyncio.Semaphore(concurrency)
        results = [None] * len(requests)
        completed = 0
        
        async def make_request(index: int, req: Dict):
            nonlocal completed
            async with semaphore:
                result = await self.request(**req)
                results[index] = result
                completed += 1
                if progress_callback:
                    progress_callback(completed, len(requests))
        
        tasks = [
            make_request(i, req)
            for i, req in enumerate(requests)
        ]
        
        await asyncio.gather(*tasks)
        
        return results
    
    def stats(self) -> Dict[str, Any]:
        avg_time = self._stats["total_time"] / self._stats["requests"] if self._stats["requests"] > 0 else 0
        return {
            **self._stats,
            "avg_time": round(avg_time, 3),
            "cache_size": len(self._cache),
        }
    
    def clear_cache(self):
        self._cache.clear()


def run_async(coro):
    """在同步环境中运行异步函数"""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                future = pool.submit(asyncio.run, coro)
                return future.result()
        else:
            return loop.run_until_complete(coro)
    except RuntimeError:
        return asyncio.run(coro)


def async_to_sync(func):
    """将异步函数转换为同步函数"""
    @wraps(func)
    def wrapper(*args, **kwargs):
        return run_async(func(*args, **kwargs))
    return wrapper


http_client = AsyncHTTPClient()
