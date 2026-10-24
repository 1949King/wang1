"""
测试框架基础模块 v1.0
====================
单元测试基类 + 测试工具 + Mock支持
"""

import unittest
import asyncio
import time
import json
import os
import sys
import logging
from typing import Any, Dict, List, Optional, Callable, Type
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from functools import wraps
import traceback
import inspect

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@dataclass
class TestResult:
    """测试结果"""
    name: str
    passed: bool
    duration: float
    error: Optional[str] = None
    traceback: Optional[str] = None
    assertions: int = 0


@dataclass
class TestSuiteResult:
    """测试套件结果"""
    name: str
    tests: List[TestResult] = field(default_factory=list)
    start_time: datetime = None
    end_time: datetime = None
    
    @property
    def passed(self) -> int:
        return sum(1 for t in self.tests if t.passed)
    
    @property
    def failed(self) -> int:
        return sum(1 for t in self.tests if not t.passed)
    
    @property
    def total_duration(self) -> float:
        return sum(t.duration for t in self.tests)
    
    @property
    def success_rate(self) -> float:
        return self.passed / len(self.tests) if self.tests else 0


class TestBase(unittest.TestCase):
    """测试基类"""
    
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._test_results: List[TestResult] = []
        cls._start_time = time.time()
        logger.info(f"\n{'='*60}")
        logger.info(f"开始测试: {cls.__name__}")
        logger.info(f"{'='*60}")
    
    @classmethod
    def tearDownClass(cls):
        duration = time.time() - cls._start_time
        passed = sum(1 for t in cls._test_results if t.passed)
        failed = len(cls._test_results) - passed
        
        logger.info(f"\n{'='*60}")
        logger.info(f"测试完成: {cls.__name__}")
        logger.info(f"  通过: {passed}, 失败: {failed}, 耗时: {duration:.2f}s")
        logger.info(f"{'='*60}")
        
        super().tearDownClass()
    
    def setUp(self):
        self._test_start = time.time()
        self._assertion_count = 0
        super().setUp()
    
    def tearDown(self):
        duration = time.time() - self._test_start
        result = TestResult(
            name=self._testMethodName,
            passed=True,
            duration=duration,
            assertions=self._assertion_count
        )
        self._test_results.append(result)
        super().tearDown()
    
    def _record_failure(self, error: str, tb: str = None):
        duration = time.time() - self._test_start
        result = TestResult(
            name=self._testMethodName,
            passed=False,
            duration=duration,
            error=error,
            traceback=tb or traceback.format_exc(),
            assertions=self._assertion_count
        )
        self._test_results.append(result)
    
    def assertJsonEqual(self, first: Any, second: Any, msg: str = None):
        self._assertion_count += 1
        first_json = json.dumps(first, sort_keys=True)
        second_json = json.dumps(second, sort_keys=True)
        if first_json != second_json:
            self.fail(f"JSON不相等:\n期望: {first_json}\n实际: {second_json}")
    
    def assertAlmostEqual(self, first: float, second: float, places: int = 7, msg: str = None):
        self._assertion_count += 1
        super().assertAlmostEqual(first, second, places, msg)
    
    def assertGreater(self, first: Any, second: Any, msg: str = None):
        self._assertion_count += 1
        super().assertGreater(first, second, msg)
    
    def assertLess(self, first: Any, second: Any, msg: str = None):
        self._assertion_count += 1
        super().assertLess(first, second, msg)
    
    def assertIn(self, member: Any, container: Any, msg: str = None):
        self._assertion_count += 1
        super().assertIn(member, container, msg)
    
    def assertNotIn(self, member: Any, container: Any, msg: str = None):
        self._assertion_count += 1
        super().assertNotIn(member, container, msg)
    
    def assertIsInstance(self, obj: Any, cls: Type, msg: str = None):
        self._assertion_count += 1
        super().assertIsInstance(obj, cls, msg)
    
    def assertRaises(self, expected_exception: Type, *args, **kwargs):
        self._assertion_count += 1
        return super().assertRaises(expected_exception, *args, **kwargs)
    
    def assertDictContainsSubset(self, subset: Dict, dictionary: Dict, msg: str = None):
        self._assertion_count += 1
        for key, value in subset.items():
            self.assertIn(key, dictionary, msg)
            self.assertEqual(value, dictionary[key], msg)


class AsyncTestBase(TestBase):
    """异步测试基类"""
    
    def setUp(self):
        super().setUp()
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
    
    def tearDown(self):
        self._loop.close()
        super().tearDown()
    
    def async_test(self, coro):
        """运行异步测试"""
        return self._loop.run_until_complete(coro)
    
    def run_async(self, func: Callable, *args, **kwargs):
        """运行异步函数"""
        return self._loop.run_until_complete(func(*args, **kwargs))


def async_test(coro):
    """异步测试装饰器"""
    @wraps(coro)
    def wrapper(self, *args, **kwargs):
        return self.async_test(coro(self, *args, **kwargs))
    return wrapper


class MockResponse:
    """Mock HTTP响应"""
    
    def __init__(self, status: int = 200, data: Any = None, headers: Dict = None):
        self.status = status
        self._data = data or {}
        self.headers = headers or {}
    
    async def json(self):
        return self._data
    
    async def text(self):
        return str(self._data)
    
    async def read(self):
        return self._data if isinstance(self._data, bytes) else str(self._data).encode()


class MockSession:
    """Mock HTTP会话"""
    
    def __init__(self, responses: Dict[str, MockResponse] = None):
        self._responses = responses or {}
        self.requests = []
    
    def set_response(self, url: str, response: MockResponse):
        self._responses[url] = response
    
    async def request(self, method: str, url: str, **kwargs):
        self.requests.append({
            "method": method,
            "url": url,
            "kwargs": kwargs
        })
        
        if url in self._responses:
            return self._responses[url]
        
        return MockResponse(status=404, data={"error": "Not found"})
    
    async def get(self, url: str, **kwargs):
        return await self.request("GET", url, **kwargs)
    
    async def post(self, url: str, **kwargs):
        return await self.request("POST", url, **kwargs)
    
    async def __aenter__(self):
        return self
    
    async def __aexit__(self, *args):
        pass


class TestRunner:
    """测试运行器"""
    
    def __init__(self, test_dir: str = "tests", pattern: str = "test_*.py"):
        self._test_dir = Path(test_dir)
        self._pattern = pattern
        self._results: List[TestSuiteResult] = []
    
    def discover_tests(self) -> unittest.TestSuite:
        loader = unittest.TestLoader()
        
        if self._test_dir.exists():
            suite = loader.discover(
                str(self._test_dir),
                pattern=self._pattern
            )
        else:
            suite = unittest.TestSuite()
        
        return suite
    
    def run(self, verbosity: int = 2) -> bool:
        suite = self.discover_tests()
        runner = unittest.TextTestRunner(verbosity=verbosity)
        result = runner.run(suite)
        
        return result.wasSuccessful()
    
    def run_with_report(self, output_file: str = None) -> Dict:
        suite = self.discover_tests()
        
        start_time = datetime.now()
        
        for test_group in suite:
            if isinstance(test_group, unittest.TestSuite):
                for test in test_group:
                    if hasattr(test, '_testMethodName'):
                        pass
        
        runner = unittest.TextTestRunner(verbosity=2)
        result = runner.run(suite)
        
        end_time = datetime.now()
        
        report = {
            "start_time": start_time.isoformat(),
            "end_time": end_time.isoformat(),
            "duration": (end_time - start_time).total_seconds(),
            "tests_run": result.testsRun,
            "failures": len(result.failures),
            "errors": len(result.errors),
            "skipped": len(result.skipped),
            "success": result.wasSuccessful(),
            "failure_details": [
                {"test": str(f[0]), "error": str(f[1])}
                for f in result.failures
            ],
            "error_details": [
                {"test": str(e[0]), "error": str(e[1])}
                for e in result.errors
            ]
        }
        
        if output_file:
            with open(output_file, 'w', encoding='utf-8') as f:
                json.dump(report, f, ensure_ascii=False, indent=2)
        
        return report


class Benchmark:
    """性能基准测试"""
    
    def __init__(self, name: str = "Benchmark"):
        self._name = name
        self._results: List[Dict] = []
    
    def measure(self, func: Callable, *args, iterations: int = 100, **kwargs) -> Dict:
        times = []
        
        for _ in range(iterations):
            start = time.perf_counter()
            result = func(*args, **kwargs)
            end = time.perf_counter()
            times.append(end - start)
        
        avg_time = sum(times) / len(times)
        min_time = min(times)
        max_time = max(times)
        
        result = {
            "name": func.__name__,
            "iterations": iterations,
            "avg_time_ms": avg_time * 1000,
            "min_time_ms": min_time * 1000,
            "max_time_ms": max_time * 1000,
            "total_time_ms": sum(times) * 1000,
        }
        
        self._results.append(result)
        
        logger.info(f"\n{self._name} - {func.__name__}:")
        logger.info(f"  迭代次数: {iterations}")
        logger.info(f"  平均耗时: {avg_time*1000:.4f}ms")
        logger.info(f"  最小耗时: {min_time*1000:.4f}ms")
        logger.info(f"  最大耗时: {max_time*1000:.4f}ms")
        
        return result
    
    def compare(self, baseline: Callable, optimized: Callable, 
                *args, iterations: int = 100, **kwargs) -> Dict:
        baseline_result = self.measure(baseline, *args, iterations=iterations, **kwargs)
        optimized_result = self.measure(optimized, *args, iterations=iterations, **kwargs)
        
        speedup = baseline_result["avg_time_ms"] / optimized_result["avg_time_ms"]
        
        comparison = {
            "baseline": baseline_result,
            "optimized": optimized_result,
            "speedup": speedup,
            "improvement_pct": (speedup - 1) * 100,
        }
        
        logger.info(f"\n性能对比:")
        logger.info(f"  基准版本: {baseline_result['avg_time_ms']:.4f}ms")
        logger.info(f"  优化版本: {optimized_result['avg_time_ms']:.4f}ms")
        logger.info(f"  加速比: {speedup:.2f}x")
        logger.info(f"  提升: {(speedup-1)*100:.1f}%")
        
        return comparison
    
    def report(self) -> List[Dict]:
        return self._results.copy()


def test_case(name: str = None):
    """测试用例装饰器"""
    def decorator(func):
        func._test_name = name or func.__name__
        func._is_test_case = True
        
        @wraps(func)
        def wrapper(*args, **kwargs):
            start = time.time()
            try:
                result = func(*args, **kwargs)
                duration = time.time() - start
                logger.info(f"✓ {func._test_name} ({duration:.3f}s)")
                return result
            except Exception as e:
                duration = time.time() - start
                logger.error(f"✗ {func._test_name} ({duration:.3f}s): {e}")
                raise
        
        return wrapper
    return decorator


def skip_if(condition: bool, reason: str = ""):
    """条件跳过装饰器"""
    def decorator(func):
        if condition:
            @wraps(func)
            def wrapper(*args, **kwargs):
                logger.info(f"⊘ 跳过 {func.__name__}: {reason}")
            return wrapper
        return func
    return decorator


def timeout(seconds: int):
    """超时装饰器"""
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            import signal
            
            def handler(signum, frame):
                raise TimeoutError(f"测试超时: {seconds}秒")
            
            old_handler = signal.signal(signal.SIGALRM, handler)
            signal.alarm(seconds)
            
            try:
                result = func(*args, **kwargs)
            finally:
                signal.alarm(0)
                signal.signal(signal.SIGALRM, old_handler)
            
            return result
        
        return wrapper
    return decorator
