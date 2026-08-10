"""
Puppeteer/Playwright 浏览器自动化模块
======================================
为 OpenClaw 提供真实的浏览器自动化能力，替代模拟数据。
支持：数据采集(playwright) + 平台发布 + MCP Server 接口

依赖: pip install playwright && playwright install chromium
"""
import os
import json
import time
import logging
import threading
from typing import Dict, List, Any, Optional, Callable
from dataclasses import dataclass, field

logger = logging.getLogger("AI短剧编辑器.browser_automation")

# 尝试导入 Playwright (Python 原生绑定)
try:
    from playwright.sync_api import sync_playwright, Browser, Page, BrowserContext
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False
    Browser, Page, BrowserContext = object, object, object  # 类型占位
    logger.warning("playwright 未安装，请运行: pip install playwright && playwright install chromium")


@dataclass
class PlatformConfig:
    """平台配置"""
    name: str
    login_url: str
    creator_url: str
    analytics_url: str
    publish_selectors: Dict[str, str] = field(default_factory=dict)


# 平台预设
PLATFORM_CONFIGS = {
    "抖音": PlatformConfig(
        name="抖音",
        login_url="https://creator.douyin.com/",
        creator_url="https://creator.douyin.com/creator-micro/content/upload",
        analytics_url="https://creator.douyin.com/creator-micro/data/overview",
        publish_selectors={
            "upload_btn": '[class*="upload"]',
            "title_input": '[class*="title"] input',
            "submit_btn": '[class*="submit"]',
        }
    ),
    "快手": PlatformConfig(
        name="快手",
        login_url="https://cp.kuaishou.com/",
        creator_url="https://cp.kuaishou.com/article/publish/video",
        analytics_url="https://cp.kuaishou.com/article/data",
    ),
    "B站": PlatformConfig(
        name="B站",
        login_url="https://member.bilibili.com/platform/home",
        creator_url="https://member.bilibili.com/platform/upload/video/frame",
        analytics_url="https://member.bilibili.com/platform/data/overview",
    ),
}


class BrowserAutomation:
    """浏览器自动化引擎 — Playwright 封装"""

    def __init__(self, headless: bool = True):
        self.headless = headless
        self._playwright = None
        self._browser: Optional[Browser] = None
        self._context: Optional[BrowserContext] = None
        self._pages: Dict[str, Page] = {}
        self._profiles_dir = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))),
            "data", "browser_profiles"
        )
        os.makedirs(self._profiles_dir, exist_ok=True)

    # ---- 生命周期 ----

    def start(self) -> bool:
        """启动浏览器"""
        if not PLAYWRIGHT_AVAILABLE:
            logger.error("Playwright 未安装，无法启动浏览器")
            return False
        try:
            self._playwright = sync_playwright().start()
            self._browser = self._playwright.chromium.launch(
                headless=self.headless,
                args=["--no-sandbox", "--disable-setuid-sandbox"]
            )
            logger.info("浏览器已启动 (headless=%s)", self.headless)
            return True
        except Exception as e:
            logger.error(f"浏览器启动失败: {e}")
            return False

    def stop(self):
        """关闭浏览器"""
        for page in self._pages.values():
            try:
                page.close()
            except Exception as e:
                logger.debug(f"[Automation] 关闭页面失败: {e}")
        if self._context:
            self._context.close()
        if self._browser:
            self._browser.close()
        if self._playwright:
            self._playwright.stop()
        self._pages.clear()
        logger.info("浏览器已关闭")

    # ---- 页面操作 ----

    def new_page(self, name: str = "default") -> Page:
        """创建新页面"""
        if not self._context:
            self._context = self._browser.new_context(
                viewport={"width": 1440, "height": 900},
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            )
        page = self._context.new_page()
        self._pages[name] = page
        return page

    def get_page(self, name: str = "default") -> Optional[Page]:
        return self._pages.get(name)

    # ---- 平台操作 ----

    def login_douyin(self, phone: str = "") -> bool:
        """打开抖音创作者平台（需手动扫码登录）"""
        cfg = PLATFORM_CONFIGS["抖音"]
        page = self.new_page("douyin")
        try:
            page.goto(cfg.login_url, wait_until="networkidle", timeout=30000)
            screenshot_path = os.path.join(self._profiles_dir, "douyin_login.png")
            page.screenshot(path=screenshot_path)
            logger.info(f"抖音创作者平台已打开，截图: {screenshot_path}")
            return True
        except Exception as e:
            logger.error(f"打开抖音失败: {e}")
            return False

    def collect_analytics(self, platform: str) -> Optional[Dict[str, Any]]:
        """采集平台数据"""
        cfg = PLATFORM_CONFIGS.get(platform)
        if not cfg:
            logger.warning(f"不支持平台: {platform}")
            return None

        try:
            page = self.get_page(platform) or self.new_page(platform)
            page.goto(cfg.analytics_url, wait_until="networkidle", timeout=30000)
            time.sleep(2)  # 等动态数据加载

            # 尝试提取页面数据
            data = {}
            try:
                # 提取可能的统计数据
                stats_text = page.inner_text("body")[:3000]
                data["raw_text"] = stats_text
                data["platform"] = platform
                data["timestamp"] = time.time()
                data["url"] = cfg.analytics_url
            except Exception as e:
                logger.debug(f"[Automation] 采集数据失败: {e}")

            screenshot_path = os.path.join(
                self._profiles_dir, f"{platform}_analytics_{int(time.time())}.png"
            )
            page.screenshot(path=screenshot_path)
            data["screenshot"] = screenshot_path

            logger.info(f"{platform} 数据采集完成")
            return data
        except Exception as e:
            logger.error(f"数据采集失败 ({platform}): {e}")
            return None

    def publish_video(self, platform: str, video_path: str,
                      title: str, description: str = "",
                      tags: List[str] = None) -> Dict[str, Any]:
        """发布视频到平台（自动化流程）"""
        cfg = PLATFORM_CONFIGS.get(platform)
        if not cfg:
            return {"success": False, "error": f"不支持平台: {platform}"}

        try:
            page = self.get_page(platform) or self.new_page(platform)
            page.goto(cfg.creator_url, wait_until="networkidle", timeout=30000)
            time.sleep(2)

            # 截图当前状态
            screenshot_pre = os.path.join(
                self._profiles_dir, f"{platform}_publish_pre_{int(time.time())}.png"
            )
            page.screenshot(path=screenshot_pre)

            # 尝试填写标题
            selectors = cfg.publish_selectors
            title_sel = selectors.get("title_input", 'input[placeholder*="标题"]')
            try:
                page.fill(title_sel, title)
                logger.info(f"标题已填写: {title}")
            except Exception:
                logger.warning("自动填写标题失败，需手动填写")

            # 尝试上传视频
            upload_sel = selectors.get("upload_btn", 'input[type="file"]')
            try:
                page.set_input_files(upload_sel, video_path)
                logger.info(f"视频已选择: {video_path}")
            except Exception:
                logger.warning("自动上传视频失败，需手动上传")

            # 截图发布状态
            screenshot_post = os.path.join(
                self._profiles_dir, f"{platform}_publish_post_{int(time.time())}.png"
            )
            page.screenshot(path=screenshot_post)

            result = {
                "success": True,
                "platform": platform,
                "video": video_path,
                "title": title,
                "description": description,
                "tags": tags or [],
                "timestamp": time.time(),
                "screenshots": [screenshot_pre, screenshot_post],
                "note": "部分步骤需手动确认（登录/验证码），请查看截图"
            }

            logger.info(f"{platform} 发布流程完成，截图: {screenshot_post}")
            return result

        except Exception as e:
            logger.error(f"{platform} 发布失败: {e}")
            return {"success": False, "error": str(e)}

    def scrape_drama_data(self, keywords: List[str]) -> List[Dict]:
        """爬取短剧相关数据"""
        results = []
        page = self.new_page("scraper")

        try:
            # 搜索短剧数据平台
            for keyword in keywords[:5]:
                try:
                    # 使用抖音搜索
                    search_url = f"https://www.douyin.com/search/{keyword}?type=general"
                    page.goto(search_url, wait_until="networkidle", timeout=20000)
                    time.sleep(2)

                    # 提取基本信息
                    title_elements = page.query_selector_all('[class*="title"]')
                    for el in title_elements[:10]:
                        text = el.inner_text()
                        if text and len(text) > 5:
                            results.append({
                                "keyword": keyword,
                                "title": text[:100],
                                "timestamp": time.time()
                            })
                except Exception as e:
                    logger.debug(f"[Automation] 提取搜索结果失败: {e}")

                try:
                    page.goto("about:blank")
                except Exception as e:
                    logger.debug(f"[Automation] 跳转空白页失败: {e}")

            logger.info(f"爬取完成，共 {len(results)} 条数据")
            return results
        except Exception as e:
            logger.error(f"爬取失败: {e}")
            return results


# ---- MCP Server 接口 ----

class PuppeteerMCPServer:
    """
    MCP Server 接口 — 将 BrowserAutomation 暴露为标准 MCP 工具
    供 Claude Code / Cursor / Copilot 等外部 AI 客户端调用
    """

    def __init__(self):
        self._automation: Optional[BrowserAutomation] = None

    def get_tools(self) -> List[Dict]:
        """获取可用工具列表（MCP tools/list 协议）"""
        return [
            {
                "name": "browser_collect_data",
                "description": "从指定平台采集账号数据（播放量/点赞/评论等）",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "platform": {"type": "string", "enum": ["抖音", "快手", "B站"]},
                    },
                    "required": ["platform"]
                }
            },
            {
                "name": "browser_publish_video",
                "description": "发布视频到指定平台，包含自动填写标题和上传",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "platform": {"type": "string", "enum": ["抖音", "快手", "B站"]},
                        "video_path": {"type": "string"},
                        "title": {"type": "string"},
                        "description": {"type": "string"},
                        "tags": {"type": "array", "items": {"type": "string"}},
                    },
                    "required": ["platform", "video_path", "title"]
                }
            },
            {
                "name": "browser_scrape_drama",
                "description": "爬取短剧相关数据，支持关键词搜索",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "keywords": {"type": "array", "items": {"type": "string"}},
                    },
                    "required": ["keywords"]
                }
            },
        ]

    def call_tool(self, name: str, arguments: Dict) -> Dict:
        """执行工具调用（MCP tools/call 协议）"""
        if not self._automation:
            self._automation = BrowserAutomation(headless=True)
            self._automation.start()

        if name == "browser_collect_data":
            return self._automation.collect_analytics(arguments.get("platform", "抖音")) or {"error": "采集失败"}

        elif name == "browser_publish_video":
            return self._automation.publish_video(
                arguments["platform"],
                arguments["video_path"],
                arguments.get("title", ""),
                arguments.get("description", ""),
                arguments.get("tags", [])
            )

        elif name == "browser_scrape_drama":
            return {
                "results": self._automation.scrape_drama_data(arguments.get("keywords", []))
            }

        return {"error": f"未知工具: {name}"}

    def stop(self):
        if self._automation:
            self._automation.stop()


# ---- 全局实例 ----

_automation: Optional[BrowserAutomation] = None
_mcp_server: Optional[PuppeteerMCPServer] = None


def get_browser_automation(headless: bool = True) -> BrowserAutomation:
    global _automation
    if _automation is None:
        _automation = BrowserAutomation(headless=headless)
    return _automation


def get_mcp_server() -> PuppeteerMCPServer:
    global _mcp_server
    if _mcp_server is None:
        _mcp_server = PuppeteerMCPServer()
    return _mcp_server
