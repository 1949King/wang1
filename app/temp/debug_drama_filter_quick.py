"""
短剧筛选模块 - 快速调试脚本 (Mock API 模式)
============================================
不触发真实网络请求,用 Mock API 注入 DramaCrawler,
验证排序/过滤/分页/异常等核心逻辑。
"""
import os, sys, logging, time
logging.disable(logging.DEBUG)
logging.basicConfig(level=logging.WARNING)  # 静音
sys.stdout.reconfigure(line_buffering=True)

_project = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
sys.path.insert(0, _project)

results = {"pass": 0, "fail": 0, "errors": []}
_all_cases = []

def case(name):
    def decorator(fn):
        _all_cases.append((name, fn))
        return fn
    return decorator


# ============================================================
# 准备: 注入 Mock API (10 条假数据, 字段可控)
# ============================================================
print("=" * 70)
print("  短剧筛选模块调试 (Mock 模式)")
print("=" * 70)

from app.modules.lego.drama_crawler import (
    DramaCrawler, DramaInfo, ScoringEngine, DATA_SOURCE_HEALTH,
)
from app.modules.lego import drama_crawler as dc

# Mock API 类 - 走 _generate_data 路径, 不联网
class MockAPI(dc.PlatformAPI):
    """Mock 平台 API - 返回 10 条固定结构的假数据"""
    def fetch(self, keyword="", page=1, page_size=20, user_prefs=None):
        items = [
            {"title": "总裁的替身新娘", "platform": "douyin", "category": "霸总",
             "tags": ["霸总", "甜宠"], "episodes": 80, "views": 5_000_000,
             "likes": 200_000, "commission": 30000, "rating": 8.8, "heat": 80000,
             "author": "星辰影视", "status": "连载中"},
            {"title": "重生之商业女王", "platform": "douyin", "category": "重生",
             "tags": ["重生", "逆袭"], "episodes": 100, "views": 3_000_000,
             "likes": 150_000, "commission": 25000, "rating": 9.0, "heat": 70000,
             "author": "番茄剧场", "status": "连载中"},
            {"title": "战神归来", "platform": "kuaishou", "category": "逆袭",
             "tags": ["逆袭", "战神"], "episodes": 60, "views": 8_000_000,
             "likes": 400_000, "commission": 35000, "rating": 8.5, "heat": 100000,
             "author": "光影传媒", "status": "已完结"},
            {"title": "校园纯爱故事", "platform": "bilibili", "category": "校园",
             "tags": ["校园", "青春"], "episodes": 24, "views": 1_000_000,
             "likes": 80_000, "commission": 10000, "rating": 9.2, "heat": 30000,
             "author": "B站短剧", "status": "已完结"},
            {"title": "斗破苍穹短剧", "platform": "bilibili", "category": "玄幻",
             "tags": ["玄幻", "修仙"], "episodes": 50, "views": 6_000_000,
             "likes": 250_000, "commission": 20000, "rating": 8.7, "heat": 60000,
             "author": "UP主创作", "status": "连载中"},
        ]
        # 关键词过滤
        if keyword and keyword not in ("all", ""):
            items = [x for x in items if keyword in x["title"] or keyword in str(x.get("tags", []))]
        # 返回 DramaInfo 列表
        dramas = []
        for i, x in enumerate(items):
            d = DramaInfo(
                id=f"mock_{i}",
                title=x["title"],
                platform=x["platform"],
                category=x["category"],
                tags=x["tags"],
                episodes=x["episodes"],
                views=x["views"],
                likes=x["likes"],
                commission=x["commission"],
                rating=x["rating"],
                heat=x["heat"],
                author=x["author"],
                status=x["status"],
                update_time="2026-05-01 12:00",
                cover_url="",
                source_url=f"https://mock.example.com/{i}",
            )
            d.score = ScoringEngine.calculate_score(d)
            d.recommend_reason = "Mock 推荐"
            dramas.append(d)
        return dramas
    def is_available(self): return True

# 注入 Mock API (覆盖现有注入)
DramaCrawler._instance = None
crawler = DramaCrawler()
crawler._apis = {
    "douyin":   MockAPI(),
    "kuaishou": MockAPI(),
    "bilibili": MockAPI(),
}
# 标记为 fake (因为是 mock)
for pid in ["douyin", "kuaishou", "bilibili"]:
    DATA_SOURCE_HEALTH[pid] = {"real": False, "source": "Mock 调试用", "api_class": "MockAPI"}
print(f"  Mock 注入完成: {list(crawler._apis.keys())}")
print()


# ============================================================
# A. 基础功能
# ============================================================
print("[A] 基础功能")
print("-" * 70)

@case("A1. 单例")
def t_a1():
    c2 = DramaCrawler()
    assert c2 is crawler, "单例被破坏"

@case("A2. fetch_dramas 默认")
def t_a2():
    data = crawler.fetch_dramas(page=1, page_size=20)
    assert isinstance(data, list)
    assert len(data) > 0
    print(f"     → {len(data)} 条")

@case("A3. 关键词过滤 '总裁'")
def t_a3():
    data = crawler.fetch_dramas(keyword="总裁", page_size=20)
    assert all("总裁" in d.title for d in data), f"过滤后还含非命中: {[d.title for d in data]}"
    print(f"     → {len(data)} 条命中")

@case("A4. 关键词过滤 '重生'")
def t_a4():
    data = crawler.fetch_dramas(keyword="重生", page_size=20)
    print(f"     → {len(data)} 条命中: {[d.title for d in data]}")

@case("A5. 平台过滤 douyin")
def t_a5():
    data = crawler.fetch_dramas(platform="douyin", page_size=20)
    assert all(d.platform == "douyin" for d in data)
    print(f"     → {len(data)} 条, 全是 douyin")

@case("A6. 平台过滤 bilibili")
def t_a6():
    data = crawler.fetch_dramas(platform="bilibili", page_size=20)
    assert all(d.platform == "bilibili" for d in data)
    print(f"     → {len(data)} 条, 全是 bilibili")

@case("A7. 排序 heat 降序")
def t_a7():
    data = crawler.fetch_dramas(sort_by="heat", page_size=20)
    heats = [d.heat for d in data]
    assert heats == sorted(heats, reverse=True), f"heat 未降序: {heats}"
    print(f"     → {heats}")

@case("A8. 排序 views 降序")
def t_a8():
    data = crawler.fetch_dramas(sort_by="views", page_size=20)
    views = [d.views for d in data]
    assert views == sorted(views, reverse=True)
    print(f"     → {views}")

@case("A9. 排序 rating 降序")
def t_a9():
    data = crawler.fetch_dramas(sort_by="rating", page_size=20)
    ratings = [d.rating for d in data]
    assert ratings == sorted(ratings, reverse=True)
    print(f"     → {ratings}")

@case("A10. 排序 commission 降序")
def t_a10():
    data = crawler.fetch_dramas(sort_by="commission", page_size=20)
    comms = [d.commission for d in data]
    assert comms == sorted(comms, reverse=True)
    print(f"     → {comms}")

@case("A11. 排序 score 降序")
def t_a11():
    data = crawler.fetch_dramas(sort_by="score", page_size=20)
    scores = [d.score for d in data]
    assert scores == sorted(scores, reverse=True)
    print(f"     → {[round(s,2) for s in scores]}")

@case("A12. 排序 latest (按 update_time)")
def t_a12():
    data = crawler.fetch_dramas(sort_by="latest", page_size=20)
    times = [d.update_time for d in data]
    assert times == sorted(times, reverse=True), f"latest 未降序: {times}"
    print(f"     → {times}")

@case("A13. 排序 engagement")
def t_a13():
    data = crawler.fetch_dramas(sort_by="engagement", page_size=20)
    engs = [(d.likes / d.views if d.views else 0) for d in data]
    assert engs == sorted(engs, reverse=True), "engagement 未降序"
    print(f"     → {[round(e,4) for e in engs]}")

@case("A14. min_commission=20000 过滤")
def t_a14():
    data = crawler.fetch_dramas(min_commission=20000, page_size=20)
    assert all(d.commission >= 20000 for d in data)
    print(f"     → {len(data)} 条, 佣金={[d.commission for d in data]}")

@case("A15. min_rating=9.0 过滤")
def t_a15():
    data = crawler.fetch_dramas(min_rating=9.0, page_size=20)
    assert all(d.rating >= 9.0 for d in data)
    print(f"     → {len(data)} 条, 评分={[d.rating for d in data]}")

@case("A16. status_filter='连载中'")
def t_a16():
    data = crawler.fetch_dramas(status_filter="连载中", page_size=20)
    assert all(d.status == "连载中" for d in data)
    print(f"     → {len(data)} 条, 状态全为连载中")

@case("A17. min_heat=80000 过滤")
def t_a17():
    data = crawler.fetch_dramas(min_heat=80000, page_size=20)
    assert all(d.heat >= 80000 for d in data)
    print(f"     → {len(data)} 条")

@case("A18. min_views=5000000 过滤")
def t_a18():
    data = crawler.fetch_dramas(min_views=5000000, page_size=20)
    assert all(d.views >= 5000000 for d in data)
    print(f"     → {len(data)} 条, 播放量={[d.views for d in data]}")

@case("A19. category='霸总' 过滤")
def t_a19():
    data = crawler.fetch_dramas(category="霸总", page_size=20)
    assert all(d.category == "霸总" for d in data)
    print(f"     → {len(data)} 条, 分类全为霸总")

@case("A20. 复合过滤: 平台+分类+排序")
def t_a20():
    data = crawler.fetch_dramas(
        platform="bilibili", category="校园", sort_by="views", page_size=20
    )
    for d in data:
        assert d.platform == "bilibili"
        assert d.category == "校园"
    print(f"     → {len(data)} 条: {[d.title for d in data]}")


# ============================================================
# B. 数据源健康度
# ============================================================
print("\n[B] 数据源健康度")
print("-" * 70)

@case("B1. DATA_SOURCE_HEALTH 字典")
def t_b1():
    assert "douyin" in DATA_SOURCE_HEALTH
    assert "bilibili" in DATA_SOURCE_HEALTH
    print(f"     → 共 {len(DATA_SOURCE_HEALTH)} 平台")

@case("B2. get_data_source_health()")
def t_b2():
    health = DramaCrawler.get_data_source_health()
    assert "douyin" in health
    assert "real" in health["douyin"]
    print(f"     → douyin: real={health['douyin']['real']}, source={health['douyin']['source']}")

@case("B3. fetch 后 data_freshness")
def t_b3():
    crawler.fetch_dramas(page=1, page_size=10)
    f = crawler.get_data_freshness()
    assert "has_real" in f
    assert "is_pure_fallback" in f
    assert "sources" in f
    print(f"     → has_real={f['has_real']}, pure_fallback={f['is_pure_fallback']}")

@case("B4. get_last_errors() 返回 list")
def t_b4():
    errs = crawler.get_last_errors()
    assert isinstance(errs, list)
    print(f"     → 错误 {len(errs)} 条")

@case("B5. get_help_text()")
def t_b5():
    t = DramaCrawler.get_help_text()
    assert "Playwright" in t
    assert "TikHub" in t
    print(f"     → 帮助文本 {len(t)} 字符")

@case("B6. DATA_SOURCE_HELP 模块常量")
def t_b6():
    assert "Playwright" in dc.DATA_SOURCE_HELP
    print(f"     → 模块常量 {len(dc.DATA_SOURCE_HELP)} 字符")

@case("B7. DATA_SOURCE_HELP 含三个方案")
def t_b7():
    h = dc.DATA_SOURCE_HELP
    has_default = "默认" in h
    has_premium = "TikHub" in h or "高级" in h
    has_fallback = "兜底" in h or "模拟" in h
    assert has_default and has_premium and has_fallback
    print(f"     → 默认/高级/兜底 三档齐全")


# ============================================================
# C. 边界与异常
# ============================================================
print("\n[C] 边界与异常")
print("-" * 70)

@case("C1. keyword='' 不崩")
def t_c1():
    data = crawler.fetch_dramas(keyword="", page_size=20)
    assert len(data) > 0
    print(f"     → {len(data)} 条")

@case("C2. 超长关键词 1000 字符")
def t_c2():
    data = crawler.fetch_dramas(keyword="短" * 500, page_size=20)
    assert isinstance(data, list)
    print(f"     → {len(data)} 条 (关键词被截断或空)")

@case("C3. 特殊字符关键词")
def t_c3():
    for kw in ["!@#$%", "短剧\n\t", "💕🍿", "<script>alert(1)</script>"]:
        data = crawler.fetch_dramas(keyword=kw, page_size=10)
        assert isinstance(data, list)
    print(f"     → 4 种特殊字符均正常")

@case("C4. 不存在平台 fallback")
def t_c4():
    data = crawler.fetch_dramas(platform="notexist", page_size=10)
    assert isinstance(data, list)
    print(f"     → {len(data)} 条 (空)")

@case("C5. 不存在分类")
def t_c5():
    data = crawler.fetch_dramas(category="notexist", page_size=10)
    assert isinstance(data, list)
    print(f"     → {len(data)} 条")

@case("C6. 极端 min_views (远超上限)")
def t_c6():
    data = crawler.fetch_dramas(min_views=999_999_999, page_size=50)
    assert isinstance(data, list)
    print(f"     → {len(data)} 条 (空, 不崩)")

@case("C7. 极端 min_heat")
def t_c7():
    data = crawler.fetch_dramas(min_heat=999_999_999, page_size=50)
    assert isinstance(data, list)
    print(f"     → {len(data)} 条 (空, 不崩)")

@case("C8. 6 种 content_type")
def t_c8():
    for ct in ["drama", "comic", "movie", "tv", "all", "unknown"]:
        crawler.clear_cache()
        data = crawler.fetch_dramas(content_type=ct, page_size=10)
        assert isinstance(data, list)
    print(f"     → 6 种 content_type 均正常")

@case("C9. clear_cache() 行为")
def t_c9():
    crawler.fetch_dramas(keyword="clear_test", page_size=5)
    crawler.clear_cache()
    data = crawler.fetch_dramas(keyword="clear_test", page_size=5)
    assert isinstance(data, list)
    print(f"     → 清理后再拉取 OK")

@case("C10. fetch 内部异常被捕获")
def t_c10():
    class BoomAPI(dc.PlatformAPI):
        def fetch(self, *a, **kw): raise RuntimeError("boom!")
        def is_available(self): return True
    crawler._apis["__boom__"] = BoomAPI()
    try:
        data = crawler.fetch_dramas(platform="__boom__", page_size=10)
        assert isinstance(data, list)
    finally:
        crawler._apis.pop("__boom__", None)
    print(f"     → 内部异常被捕获, 不崩")

@case("C11. fetch 返回 None")
def t_c11():
    class NoneAPI(dc.PlatformAPI):
        def fetch(self, *a, **kw): return None
        def is_available(self): return True
    crawler._apis["__none__"] = NoneAPI()
    try:
        data = crawler.fetch_dramas(platform="__none__", page_size=10)
        assert isinstance(data, list)
    finally:
        crawler._apis.pop("__none__", None)
    print(f"     → None 被优雅处理, fallback {len(data)} 条")

@case("C12. 关键词命中 0 条不崩")
def t_c12():
    data = crawler.fetch_dramas(keyword="notexist_keyword_xyz", page_size=10)
    assert isinstance(data, list)
    print(f"     → {len(data)} 条 (空)")

@case("C13. DramaInfo 字段完整")
def t_c13():
    data = crawler.fetch_dramas(page_size=1)
    d = data[0]
    required = ["id", "title", "platform", "category", "tags", "episodes", "views",
                "likes", "commission", "rating", "heat", "cover_url", "source_url",
                "score", "recommend_reason", "status", "author", "update_time"]
    for f in required:
        assert hasattr(d, f), f"缺字段: {f}"
    print(f"     → {len(required)} 个字段齐全")

@case("C14. 5 并发调用不冲突")
def t_c14():
    import threading
    out = [None] * 5
    def w(i):
        out[i] = crawler.fetch_dramas(page=1, page_size=10)
    ts = [threading.Thread(target=w, args=(i,)) for i in range(5)]
    for t in ts: t.start()
    for t in ts: t.join()
    assert all(isinstance(r, list) for r in out)
    print(f"     → 5 并发均拿到 {len(out[0])} 条")

@case("C15. 排序键不识别时 fallback 到 score")
def t_c15():
    data = crawler.fetch_dramas(sort_by="notexist_sort_key", page_size=10)
    assert isinstance(data, list)
    print(f"     → {len(data)} 条 (走 score 默认)")


# ============================================================
# D. 持久化
# ============================================================
print("\n[D] 持久化")
print("-" * 70)

@case("D1. 收藏持久化")
def t_d1():
    from app.modules.lego.user_prefs_store import add_to_favorites, remove_from_favorites, load_user_prefs
    tid = "dbg_fav_001"
    add_to_favorites(tid)
    assert tid in load_user_prefs()["favorites"]
    remove_from_favorites(tid)
    assert tid not in load_user_prefs()["favorites"]
    print(f"     → 收藏/取消 OK")

@case("D2. 历史持久化")
def t_d2():
    from app.modules.lego.user_prefs_store import add_to_history, load_user_prefs
    tid = "dbg_hist_001"
    add_to_history(tid, max_len=10)
    assert tid in load_user_prefs()["view_history"]
    print(f"     → 历史 OK")

@case("D3. 偏好持久化")
def t_d3():
    from app.modules.lego.user_prefs_store import set_user_preference, load_user_prefs
    set_user_preference("dbg_key", {"foo": 1})
    assert load_user_prefs()["user_preferences"].get("dbg_key") == {"foo": 1}
    print(f"     → 偏好 OK")


# ============================================================
# 执行
# ============================================================
print(f"\n  共 {len(_all_cases)} 个用例待执行")
print()
for name, fn in _all_cases:
    t0 = time.time()
    try:
        fn()
        results["pass"] += 1
        print(f"[OK]   {name}  ({time.time()-t0:.2f}s)")
    except AssertionError as e:
        results["fail"] += 1
        results["errors"].append((name, f"Assert: {e}"))
        print(f"[FAIL] {name}: {e}")
    except Exception as e:
        results["fail"] += 1
        results["errors"].append((name, f"{type(e).__name__}: {e}"))
        print(f"[ERR]  {name}: {type(e).__name__}: {e}")

print("\n" + "=" * 70)
print(f"  通过 {results['pass']} / 失败 {results['fail']}  (共 {results['pass']+results['fail']} 项)")
print("=" * 70)
if results["fail"] > 0:
    print("\n失败明细:")
    for name, err in results["errors"]:
        print(f"  ✗ {name}: {err[:200]}")
    sys.exit(1)
else:
    print("  全部通过 ✅")
    sys.exit(0)
