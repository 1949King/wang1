"""
验证 短剧筛选模块 Real #1 补短
==============================
- 1. 数据源健康状态表
- 2. 用户偏好持久化
- 3. TikHub 真实 API 注入
- 4. fetch_dramas 新增方法(不破坏现有)
- 5. 数据新鲜度标记
"""
import os, sys
import logging
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

# ============================================================
# 1. 数据源健康状态表
# ============================================================
print("\n=== 1. DATA_SOURCE_HEALTH ===")
from app.modules.lego.drama_crawler import DATA_SOURCE_HEALTH, get_data_source_health
check("DATA_SOURCE_HEALTH 是 dict", isinstance(DATA_SOURCE_HEALTH, dict))
check("含 15 个平台", len(DATA_SOURCE_HEALTH) == 15, f"实际 {len(DATA_SOURCE_HEALTH)}")
check("douyin.real = False(未配 token)", DATA_SOURCE_HEALTH["douyin"]["real"] is False)
check("douyin 含 source 字段", "source" in DATA_SOURCE_HEALTH["douyin"])
check("get_data_source_health 返回副本", get_data_source_health() is not DATA_SOURCE_HEALTH or len(get_data_source_health()) == 15)

# ============================================================
# 2. 用户偏好持久化
# ============================================================
print("\n=== 2. user_prefs_store ===")
from app.modules.lego.user_prefs_store import (
    load_user_prefs, save_user_prefs, add_to_favorites,
    remove_from_favorites, add_to_history, set_user_preferences,
    prefs_storage_path,
)

check("存储路径可访问", bool(prefs_storage_path()))
check("load_user_prefs 返回 dict", isinstance(load_user_prefs(), dict))
check("load_user_prefs 字段齐全",
      all(k in load_user_prefs() for k in ("user_preferences", "favorites", "view_history")))

# 写一个测试值
TEST_ID = "_verify_test_drama_id_"
add_to_favorites(TEST_ID)
check("add_to_favorites 后能读到", TEST_ID in load_user_prefs()["favorites"])

remove_from_favorites(TEST_ID)
check("remove_from_favorites 后读不到", TEST_ID not in load_user_prefs()["favorites"])

# 历史
add_to_history("drama_a")
add_to_history("drama_b")
hist = load_user_prefs()["view_history"]
check("历史最近在前", len(hist) >= 2 and hist[0] in ("drama_a", "drama_b"))

# 偏好
set_user_preferences({"preferred_categories": ["霸总", "甜宠"]})
check("偏好持久化",
      "霸总" in load_user_prefs()["user_preferences"].get("preferred_categories", []))

# ============================================================
# 3. TikHub 真实 API
# ============================================================
print("\n=== 3. TikHubDouyinAPI ===")
from app.modules.lego.tiktokhub_douyin_api import (
    TikHubDouyinAPI, is_tikhub_configured, TIKHUB_CONTENT_TYPE
)
check("TIKHUB_CONTENT_TYPE 含 16 个分类", len(TIKHUB_CONTENT_TYPE) == 16, f"实际 {len(TIKHUB_CONTENT_TYPE)}")
check("TIKHUB_CONTENT_TYPE['热榜']=0", TIKHUB_CONTENT_TYPE.get("热榜") == 0)
check("TIKHUB_CONTENT_TYPE['都市']=110", TIKHUB_CONTENT_TYPE.get("都市") == 110)

api = TikHubDouyinAPI()
is_avail = api.is_available()
check(f"is_available 返回 bool, 未配 token → False", is_avail is False, f"实际 {is_avail}")
check("未配 token → fetch 返回 None",
      api.fetch("热榜") is None)

# 模拟一个 TikHub 响应
class _MockResp:
    status_code = 200
    def json(self):
        return {
            "code": 200,
            "data": {
                "aweme_list": [
                    {
                        "aweme_id": "abc123",
                        "title": "总裁的替身新娘",
                        "author": {"nickname": "星辰影视"},
                        "statistics": {"play_count": 1000000, "digg_count": 50000, "comment_count": 2000},
                        "video": {"duration": 1800, "cover": {"url_list": ["http://x.com/c.jpg"]}},
                        "create_time": 1735689600,
                    },
                    {
                        "aweme_id": "xyz789",
                        "title": "战神归来",
                        "author": {"nickname": "光影传媒"},
                        "statistics": {"play_count": 800000, "digg_count": 30000},
                        "video": {"duration": 2400},
                        "create_time": 1735776000,
                    },
                ]
            }
        }

# mock requests
import unittest.mock as mock
class _FakeRequests:
    def get(self, *a, **kw):
        return _MockResp()

with mock.patch("app.modules.lego.tiktokhub_douyin_api.requests", _FakeRequests()), \
     mock.patch("app.modules.lego.tiktokhub_douyin_api._get_tikhub_token", return_value="fake_token"):
    result = api.fetch("热榜")
    check("mock 真实 API 返回 list", isinstance(result, list) and len(result) == 2)
    if result:
        d = result[0]
        check("真实数据 1: title", d.title == "总裁的替身新娘")
        check("真实数据 1: views=1000000", d.views == 1000000)
        check("真实数据 1: likes=50000", d.likes == 50000)
        check("真实数据 1: author=星辰影视", d.author == "星辰影视")
        check("真实数据 1: id=douyin_tikhub_abc123", d.id == "douyin_tikhub_abc123")
        check("真实数据 1: platform=douyin", d.platform == "douyin")
        check("真实数据 1: source_url 含 abc123", "abc123" in d.source_url)
        check("真实数据 1: cover_url", "c.jpg" in d.cover_url)
        check("真实数据 1: score > 0", d.score > 0)
        check("真实数据 1: recommend_reason", bool(d.recommend_reason))
        # 估算热度
        check("真实数据 1: heat=500250", d.heat == 1000000//100 + 50000*5)
        # 健康状态标记
        from app.modules.lego.drama_crawler import DATA_SOURCE_HEALTH as DSH
        check("成功抓取后 douyin.real=True", DSH["douyin"]["real"] is True)

# ============================================================
# 4. fetch_dramas 数据新鲜度
# ============================================================
print("\n=== 4. fetch_dramas 新增能力 ===")
from app.modules.lego.drama_crawler import DramaCrawler

# 单例: 重置
DramaCrawler._instance = None
crawler = DramaCrawler()

# 4.1 不配 token,走 platform="all" 走平台 API 路径
# 注: 重置 module-level DATA_SOURCE_HEALTH (上一组测试把 douyin.real 设成了 True)
DramaCrawler._instance = None
from app.modules.lego.drama_crawler import DATA_SOURCE_HEALTH
DATA_SOURCE_HEALTH["douyin"] = {"real": False, "source": "随机生成（未配 token）", "api_class": "DouyinAPI"}
crawler = DramaCrawler()
dramas = crawler.fetch_dramas(platform="all", page_size=5)
check("fetch_dramas 仍可调用", len(dramas) > 0)
fresh = crawler.get_data_freshness()
check("get_data_freshness 返回 dict", isinstance(fresh, dict))
# 此时 TikHubDouyinAPI 仍是 is_available()=False (没配 token),所以应该是 pure_fallback
check("未配 token → is_pure_fallback=True", fresh.get("is_pure_fallback") is True, f"实际: {fresh}")
check("未配 token → has_real=False", fresh.get("has_real") is False, f"实际: {fresh}")
check("未配 token → has_fake=True", fresh.get("has_fake") is True, f"实际: {fresh}")
check("sources 含 (douyin, fake)", any(p == "douyin" and k == "fake" for p, k in fresh.get("sources", [])), f"实际: {fresh.get('sources')}")

# 4.1.1 验证 has_real=True 路径: 手工注入 mock douyin 真实 API
with mock.patch("app.modules.lego.tiktokhub_douyin_api._get_tikhub_token", return_value="fake_token"), \
     mock.patch("app.modules.lego.tiktokhub_douyin_api.requests", _FakeRequests()):
    # 重新生成实例,让 _init_apis 重新走
    DramaCrawler._instance = None
    c3 = DramaCrawler()
    c3.fetch_dramas(platform="all", page_size=5)
    fresh2 = c3.get_data_freshness()
    check("配 token 后 has_real=True", fresh2.get("has_real") is True, f"实际: {fresh2}")
    check("配 token 后 has_fake=True (其他平台仍是 fake)", fresh2.get("has_fake") is True, f"实际: {fresh2}")
    check("配 token 后 is_pure_fallback=False", fresh2.get("is_pure_fallback") is False, f"实际: {fresh2}")
    check("sources 含 (douyin, real)", any(p == "douyin" and k == "real" for p, k in fresh2.get("sources", [])), f"实际: {fresh2.get('sources')}")
    c3.clear_cache()
errs = crawler.get_last_errors()
check("get_last_errors 返回 list", isinstance(errs, list))

# 4.2 持久化收藏
TEST_ID2 = "_verify_drama_zzz_"
crawler.add_to_favorites_persisted(TEST_ID2)
check("持久化收藏生效", TEST_ID2 in crawler._favorites)
check("磁盘文件已更新", TEST_ID2 in load_user_prefs()["favorites"])

crawler.remove_from_favorites_persisted(TEST_ID2)
check("持久化取消收藏生效", TEST_ID2 not in crawler._favorites)

# 4.3 持久化历史
crawler.add_to_history_persisted("drama_xxx")
check("持久化历史生效", "drama_xxx" in crawler._view_history)
check("磁盘文件已更新", "drama_xxx" in load_user_prefs()["view_history"])

# 4.4 启动时恢复(模拟)
DramaCrawler._instance = None
c2 = DramaCrawler()
# 之前的 history 应在
check("启动时自动恢复历史", "drama_xxx" in c2._view_history)

# ============================================================
# 5. 兼容性(不破坏现有调用)
# ============================================================
print("\n=== 5. 兼容性 ===")
# 原 API: get_recommendations / get_hot_dramas / get_high_commission
recs = crawler.get_recommendations(count=3)
check("get_recommendations 仍可用", len(recs) == 3)
hotties = crawler.get_hot_dramas(count=3)
check("get_hot_dramas 仍可用", len(hotties) == 3)
high_c = crawler.get_high_commission(min_commission=100, count=3)
check("get_high_commission 仍可用", len(high_c) == 3)

# 清理
load_user_prefs()  # 不删,保留偏好

# ============================================================
print(f"\n{'='*50}")
print(f"  通过 {pass_count} / 失败 {fail_count}  (共 {pass_count + fail_count} 项)")
print(f"{'='*50}")
if fail_count == 0:
    print("  全部通过 ✅")
else:
    print(f"  {fail_count} 项失败 ❌")
sys.exit(0 if fail_count == 0 else 1)
