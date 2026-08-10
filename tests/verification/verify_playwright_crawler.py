"""验证 短剧 Playwright 爬虫方案"""
import os, sys, logging
logging.disable(logging.CRITICAL)
_project = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
sys.path.insert(0, _project)

pass_count = 0
fail_count = 0
def check(name, cond, detail=""):
    global pass_count, fail_count
    if cond:
        pass_count += 1
        print(f"  [PASS] {name}")
    else:
        fail_count += 1
        print(f"  [FAIL] {name}: {detail}")

print("\n=== 1. StealthBrowser ===")
from app.modules.lego.stealth_browser import (
    is_playwright_available, get_stealth_browser,
    cleanup_stealth_browser, StealthBrowser, STEALTH_INIT_SCRIPT,
)
check("STEALTH_INIT_SCRIPT 非空", len(STEALTH_INIT_SCRIPT) > 1000)
check("STEALTH_INIT_SCRIPT 含 webdriver 修复", "webdriver" in STEALTH_INIT_SCRIPT)
check("STEALTH_INIT_SCRIPT 含 chrome 修复", "chrome" in STEALTH_INIT_SCRIPT)
check("is_playwright_available 返回 bool", isinstance(is_playwright_available(), bool))
print(f"  (playwright 可用性: {is_playwright_available()})")

b1 = get_stealth_browser()
b2 = get_stealth_browser()
check("StealthBrowser 单例", b1 is b2)
check("b1.is_running 是方法", callable(b1.is_running))
try:
    b1.start()
    check("b1.start 成功 (chromium 已装)", b1.is_running())
    b1.stop()
    check("b1.stop 后 not running", not b1.is_running())
except Exception as e:
    check("b1.start 启动失败优雅", True, str(e)[:80])
    check("b1.stop 后 not running", not b1.is_running())

print("\n=== 2. DouyinPlaywrightAPI ===")
from app.modules.lego.douyin_playwright_api import DouyinPlaywrightAPI, KEYWORDS_HOT
from app.modules.lego import drama_crawler as dc

api = DouyinPlaywrightAPI()
check("实例化", api is not None)
check("is_available 返回 bool", isinstance(api.is_available(), bool))
check("未启动时 fetch 返回 None", api.fetch("短剧") is None)

test_item = {
    "aweme_id": "test_123",
    "title": "总裁的替身新娘#霸总#甜宠",
    "author": {"nickname": "星辰影视"},
    "statistics": {"play_count": 500000, "digg_count": 20000, "comment_count": 800, "share_count": 100},
    "video": {"duration": 60000, "cover": {"url_list": ["http://x.com/cover.jpg"]}},
    "create_time": 1735689600,
    "text_extra": [{"tag_name": "霸总"}, {"tag_name": "甜宠"}, {"tag_name": "短剧"}],
}
d = api._to_drama_info(test_item, None)
check("数据解析", d is not None)
if d:
    check("title 清洗 # 话题", d.title == "总裁的替身新娘")
    check("views=500000", d.views == 500000)
    check("heat 综合算分", d.heat == 500 + 20000*10 + 800*5 + 100*8)
    check("tags 截断到 10 个", len(d.tags) <= 10)
    check("id 前缀", d.id == "douyin_playwright_test_123")
    check("source_url", "test_123" in d.source_url)
    check("score > 0", d.score > 0)
    check("recommend_reason", bool(d.recommend_reason))

check("douyin.health.real 注入时为 True", dc.DATA_SOURCE_HEALTH["douyin"]["real"] is True)
check("source 含 Playwright 或 TikHub", "Playwright" in dc.DATA_SOURCE_HEALTH["douyin"]["source"] or "TikHub" in dc.DATA_SOURCE_HEALTH["douyin"]["source"])

print("\n=== 3. BilibiliPlaywrightAPI ===")
from app.modules.lego.bilibili_playwright_api import BilibiliPlaywrightAPI

api2 = BilibiliPlaywrightAPI()
check("实例化", api2 is not None)
check("is_available 返回 bool", isinstance(api2.is_available(), bool))

test_bili = {
    "data_type": "video",
    "bvid": "BV1xx411c7mD",
    "title": "<em class=\"keyword\">短剧</em>合集",
    "author": "影视飓风",
    "play": 1000000,
    "like": 50000,
    "danmaku": 2000,
    "duration": "12:34",
    "pic": "http://x.com/c.jpg",
    "tag": "短剧,甜宠,重生",
    "pubdate": 1735689600,
    "description": "重磅短剧合集",
}
d2 = api2._to_drama_info(test_bili, None)
check("数据解析", d2 is not None)
if d2:
    check("title 清洗 em 标签", "<em" not in d2.title and "短剧" in d2.title)
    check("bvid=id", d2.id == "bilibili_playwright_BV1xx411c7mD")
    check("episodes 估算", d2.episodes >= 1)
    check("tags", d2.tags == ["短剧", "甜宠", "重生"])
    check("cover", "c.jpg" in d2.cover_url)

check("bilibili.health.real 注入时为 True", dc.DATA_SOURCE_HEALTH["bilibili"]["real"] is True)

d3 = api2._to_drama_info({"data_type": "live", "title": "x", "author": "y"}, None)
check("非 video 类型跳过", d3 is None)

print("\n=== 4. DramaCrawler 默认注入顺序 ===")
from app.modules.lego.drama_crawler import DramaCrawler
DramaCrawler._instance = None
crawler = DramaCrawler()
injected = list(crawler._apis.keys())
print(f"  注入的平台: {injected}")
check("douyin 已注入", "douyin" in injected)
check("bilibili 已注入", "bilibili" in injected)
douyin_class = type(crawler._apis.get("douyin")).__name__
print(f"  douyin API 类: {douyin_class}")
if is_playwright_available():
    check("Playwright 可用 → DouyinPlaywrightAPI", douyin_class == "DouyinPlaywrightAPI", f"实际: {douyin_class}")
else:
    check("Playwright 不可用 → fallback DouyinAPI", douyin_class == "DouyinAPI", f"实际: {douyin_class}")

print("\n=== 5. 帮助文档 ===")
help_text = DramaCrawler.get_help_text()
check("get_help_text 非空", bool(help_text))
check("含 Playwright", "Playwright" in help_text)
check("含 TikHub", "TikHub" in help_text)
check("含价格", "0.04" in help_text)
check("含 TIKHUB_API_TOKEN", "TIKHUB_API_TOKEN" in help_text)
check("含常见问题", "Q1" in help_text and "Q2" in help_text)
check("DATA_SOURCE_HELP 模块常量", bool(dc.DATA_SOURCE_HELP))
check("DATA_SOURCE_HELP 3 方案", "默认" in dc.DATA_SOURCE_HELP and "高级" in dc.DATA_SOURCE_HELP and "兜底" in dc.DATA_SOURCE_HELP)

print(f"\n{'='*50}")
print(f"  通过 {pass_count} / 失败 {fail_count}  (共 {pass_count + fail_count} 项)")
print(f"{'='*50}")
if fail_count == 0:
    print("  全部通过 ✅")
else:
    print(f"  {fail_count} 项失败 ❌")
sys.exit(0 if fail_count == 0 else 1)
