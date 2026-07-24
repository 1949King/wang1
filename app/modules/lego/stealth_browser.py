"""
通用反爬浏览器封装 (StealthBrowser)
=====================================
基于 Playwright 同步 API 封装, 任何平台爬虫都可以复用这个类。

特性:
  1. 启动参数隐藏 webdriver
  2. 注入 stealth.js (绕过 navigator.webdriver / plugins / chrome.runtime)
  3. 高斯分布随机延迟 (模拟真人操作节奏)
  4. 统一错误处理 (任何 platform 失败, 上层只需 try/except)
  5. 懒加载 (start 时才装, 失败不报错 - 优雅降级)

参考:
  - https://github.com/Greatdori/Douyin_TikTok_Scraper (反爬参数)
  - https://github.com/cv-cat/python-xiaohongshu-scraper (stealth.js)
  - MediaCrawler 架构
"""
import os
import time
import random
import logging
import threading
from typing import Optional, List, Dict, Any, Callable

logger = logging.getLogger(__name__)

# 探测 playwright 是否可用 (不强制, 缺包时优雅降级)
try:
    from playwright.sync_api import sync_playwright, Browser, BrowserContext, Page
    _PLAYWRIGHT_AVAILABLE = True
except ImportError:
    _PLAYWRIGHT_AVAILABLE = False


# ============================================================
# 全局单例 + 懒加载 (不强制启动浏览器, 降低项目启动成本)
# ============================================================

_browser_instance: Optional["StealthBrowser"] = None
_browser_lock = threading.Lock()

# ============================================================
# is_playwright_available() 结果缓存 (避免重复启动 driver 进程)
# ============================================================
_playwright_avail_cache: Optional[bool] = None
_playwright_avail_lock = threading.Lock()


def is_playwright_available() -> bool:
    """
    Playwright 及其 Chromium 是否可用 (带缓存)。

    修复: 之前每次调用都启动/关闭一次 playwright driver,
    在 DramaCrawler 注入阶段 (短时间内多次调用) 会偶发返回 False,
    导致 Playwright API 被误判为不可用而走 fallback。
    """
    global _playwright_avail_cache
    if not _PLAYWRIGHT_AVAILABLE:
        return False
    # 命中缓存直接返回
    if _playwright_avail_cache is not None:
        return _playwright_avail_cache
    with _playwright_avail_lock:
        if _playwright_avail_cache is not None:
            return _playwright_avail_cache
        try:
            from playwright.sync_api import sync_playwright
            with sync_playwright() as p:
                path = p.chromium.executable_path
                if path and os.path.isfile(path):
                    _playwright_avail_cache = True
                    return True
            _playwright_avail_cache = False
            return False
        except Exception:
            _playwright_avail_cache = False
            return False


def reset_playwright_avail_cache() -> None:
    """清空 is_playwright_available 缓存 (供测试 / 重载用)"""
    global _playwright_avail_cache
    with _playwright_avail_lock:
        _playwright_avail_cache = None


def get_stealth_browser() -> "StealthBrowser":
    """获取全局 StealthBrowser 单例 (线程安全)"""
    global _browser_instance
    with _browser_lock:
        if _browser_instance is None:
            _browser_instance = StealthBrowser()
        return _browser_instance


# ============================================================
# 注入的 stealth.js 脚本 (绕过浏览器指纹检测)
# ============================================================

STEALTH_INIT_SCRIPT = """
// 1. 隐藏 webdriver 标志
Object.defineProperty(navigator, 'webdriver', {
    get: () => undefined,
    configurable: true
});

// 2. 伪造 plugins 长度 (headless 默认 0)
Object.defineProperty(navigator, 'plugins', {
    get: () => [1, 2, 3, 4, 5],
    configurable: true
});

// 3. 伪造 languages
Object.defineProperty(navigator, 'languages', {
    get: () => ['zh-CN', 'zh', 'en'],
    configurable: true
});

// 4. 注入 chrome.runtime (抖音/小红书反爬关键检测点)
window.chrome = {
    runtime: {
        onMessage: { addListener: function() {}, removeListener: function() {} },
        sendMessage: function() {},
        connect: function() { return { onMessage: { addListener: function() {} } }; }
    },
    loadTimes: function() { return { requestTime: Date.now() / 1000 }; },
    csi: function() { return { startE: Date.now(), onloadT: Date.now() }; },
    app: { isInstalled: false }
};

// 5. 修复 Permissions API
const originalQuery = window.navigator.permissions.query;
window.navigator.permissions.query = (parameters) => (
    parameters.name === 'notifications' ?
    Promise.resolve({ state: Notification.permission }) :
    originalQuery(parameters)
);

// 6. 隐藏 HeadlessChrome 特征
const userAgentLower = navigator.userAgent.toLowerCase();
if (userAgentLower.includes('headless')) {
    Object.defineProperty(navigator, 'userAgent', {
        get: () => navigator.userAgent.replace(/HeadlessChrome/g, 'Chrome')
    });
}
"""


class StealthBrowser:
    """
    通用反爬浏览器。

    用法:
        browser = get_stealth_browser()
        page = browser.new_page()
        page.goto("https://www.douyin.com/...")
        html = page.content()
        # 解析 + 关闭
    """

    def __init__(self, headless: bool = True, proxy: Optional[str] = None):
        self.headless = headless
        self.proxy = proxy  # 例: "http://127.0.0.1:7890"
        self._playwright_ctx = None
        self._browser: Optional[Browser] = None
        self._lock = threading.Lock()
        self._started = False

    def start(self):
        """启动浏览器 (懒加载) - 失败抛 RuntimeError, 调用方应回退"""
        if self._started:
            return
        with self._lock:
            if self._started:
                return
            if not _PLAYWRIGHT_AVAILABLE:
                raise RuntimeError("playwright 未安装: pip install playwright && playwright install chromium")

            self._playwright_ctx = sync_playwright().start()
            launch_kwargs = {
                "headless": self.headless,
                "args": [
                    "--disable-blink-features=AutomationControlled",
                    "--disable-dev-shm-usage",
                    "--no-sandbox",
                    "--disable-gpu",
                    "--no-first-run",
                    "--no-default-browser-check",
                ],
            }
            if self.proxy:
                launch_kwargs["proxy"] = {"server": self.proxy}

            self._browser = self._playwright_ctx.chromium.launch(**launch_kwargs)
            self._started = True
            logger.info("[StealthBrowser] 启动成功 (headless=%s)", self.headless)

    def new_page(self, locale: str = "zh-CN", timezone: str = "Asia/Shanghai") -> "Page":
        """创建 1 个新 page (已注入 stealth 脚本)"""
        if not self._started:
            self.start()
        context = self._browser.new_context(
            locale=locale,
            timezone_id=timezone,
            viewport={"width": 1920, "height": 1080},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
        )
        page = context.new_page()
        # 注入 stealth 脚本 - 在每个页面加载前执行
        page.add_init_script(STEALTH_INIT_SCRIPT)
        return page

    def human_delay(self, mean: float = 3.0, std: float = 1.0):
        """高斯分布随机延迟 (模拟真人)"""
        delay = max(0.5, random.gauss(mean, std))
        time.sleep(delay)

    def stop(self):
        """关闭浏览器 (释放资源)"""
        with self._lock:
            if self._browser:
                try:
                    self._browser.close()
                except Exception as e:
                    logger.debug(f"关闭 browser 异常: {e}")
                self._browser = None
            if self._playwright_ctx:
                try:
                    self._playwright_ctx.stop()
                except Exception as e:
                    logger.debug(f"停止 playwright 异常: {e}")
                self._playwright_ctx = None
            self._started = False

    def is_running(self) -> bool:
        return self._started and self._browser is not None


def cleanup_stealth_browser():
    """项目退出时清理 (供 main.py 注册)"""
    global _browser_instance
    with _browser_lock:
        if _browser_instance is not None:
            _browser_instance.stop()
            _browser_instance = None
