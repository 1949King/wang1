"""
短剧筛选模块 - 调试脚本
========================
覆盖 4 类场景:
  A. 基础功能 (关键词/平台/分类/排序/分页)
  B. 数据源切换 (Playwright / TikHub / 模拟)
  C. 边界与异常 (空数据/超长关键词/特殊字符/并发)
  D. UI 集成 (data_freshness / health / help)
"""
import os, sys, logging, time, random
logging.disable(logging.DEBUG)  # 保留 INFO, 关掉 DEBUG 噪声
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("debug")

# 强制 stdout 无缓冲
sys.stdout.reconfigure(line_buffering=True)
sys.stderr.reconfigure(line_buffering=True)

_project = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
sys.path.insert(0, _project)

# 真实退出码: 0=通过, 1=失败
results = {"pass": 0, "fail": 0, "errors": []}

# 收集所有 case
_all_cases = []

def case(name):
    def decorator(fn):
        _all_cases.append((name, fn))
        return fn
    return decorator

# ============================================================
# A. 基础功能
# ============================================================
print("\n[A] 基础功能测试")
print("-" * 70)

@case("A1. DramaCrawler 单例")
def t_a1():
    from app.modules.lego.drama_crawler import DramaCrawler
    DramaCrawler._instance = None
    c1 = DramaCrawler()
    c2 = DramaCrawler()
    assert c1 is c2, "DramaCrawler 不是单例"

@case("A2. DramaCrawler 已注入 douyin/bilibili")
def t_a2():
    from app.modules.lego.drama_crawler import DramaCrawler
    c = DramaCrawler()
    assert "douyin" in c._apis, "douyin 未注入"
    assert "bilibili" in c._apis, "bilibili 未注入"

@case("A3. fetch_dramas 默认参数 (page=1, page_size=20)")
def t_a3():
    from app.modules.lego.drama_crawler import DramaCrawler
    c = DramaCrawler()
    data = c.fetch_dramas(page=1, page_size=20)
    assert isinstance(data, list), f"应返回 list, 实际 {type(data)}"
    assert len(data) > 0, "数据为空"
    print(f"     → 返回 {len(data)} 条")

@case("A4. fetch_dramas 分页 page=2")
def t_a4():
    from app.modules.lego.drama_crawler import DramaCrawler
    c = DramaCrawler()
    p1 = c.fetch_dramas(page=1, page_size=20)
    c.clear_cache()
    p2 = c.fetch_dramas(page=2, page_size=20)
    assert isinstance(p2, list), f"page=2 应返回 list, 实际 {type(p2)}"
    print(f"     → page1: {len(p1)} 条, page2: {len(p2)} 条")

@case("A5. 关键词过滤 - 短剧")
def t_a5():
    from app.modules.lego.drama_crawler import DramaCrawler
    c = DramaCrawler()
    c.clear_cache()
    data = c.fetch_dramas(keyword="总裁", page_size=50)
    assert len(data) > 0, "关键词过滤无结果"
    # 标题应包含"总裁"或同义词
    matched = [d for d in data if "总裁" in d.title or "霸总" in d.title or "CEO" in d.title]
    print(f"     → 关键词命中: {len(matched)}/{len(data)}")

@case("A6. 平台过滤 - 抖音")
def t_a6():
    from app.modules.lego.drama_crawler import DramaCrawler
    c = DramaCrawler()
    c.clear_cache()
    data = c.fetch_dramas(platform="douyin", page_size=30)
    platforms = {d.platform for d in data}
    print(f"     → 数据平台: {platforms}")

@case("A7. 排序 - heat 降序")
def t_a7():
    from app.modules.lego.drama_crawler import DramaCrawler
    c = DramaCrawler()
    c.clear_cache()
    data = c.fetch_dramas(sort_by="heat", page_size=30)
    heats = [d.heat for d in data]
    assert heats == sorted(heats, reverse=True), f"heat 未按降序: {heats[:5]}..."
    print(f"     → heat 范围: {min(heats)} ~ {max(heats)}")

@case("A8. 排序 - views 降序")
def t_a8():
    from app.modules.lego.drama_crawler import DramaCrawler
    c = DramaCrawler()
    c.clear_cache()
    data = c.fetch_dramas(sort_by="views", page_size=30)
    views = [d.views for d in data]
    assert views == sorted(views, reverse=True), f"views 未按降序"
    print(f"     → views 范围: {min(views)} ~ {max(views)}")

@case("A9. 排序 - rating 降序")
def t_a9():
    from app.modules.lego.drama_crawler import DramaCrawler
    c = DramaCrawler()
    c.clear_cache()
    data = c.fetch_dramas(sort_by="rating", page_size=30)
    ratings = [d.rating for d in data if d.rating > 0]
    assert ratings == sorted(ratings, reverse=True), "rating 未按降序"
    print(f"     → rating 范围: {min(ratings):.1f} ~ {max(ratings):.1f}")

@case("A10. 综合过滤 - min_commission + min_rating + status")
def t_a10():
    from app.modules.lego.drama_crawler import DramaCrawler
    c = DramaCrawler()
    c.clear_cache()
    data = c.fetch_dramas(
        min_commission=20000,
        min_rating=8.0,
        status_filter="连载中",
        page_size=50,
    )
    for d in data:
        assert d.commission >= 20000, f"佣金过滤失败: {d.title} = {d.commission}"
        assert d.rating >= 8.0, f"评分过滤失败: {d.title} = {d.rating}"
        assert d.status == "连载中", f"状态过滤失败: {d.title} = {d.status}"
    print(f"     → 复合过滤后: {len(data)} 条")

# ============================================================
# B. 数据源切换
# ============================================================
print("\n[B] 数据源切换测试")
print("-" * 70)

@case("B1. DATA_SOURCE_HEALTH 字典存在")
def t_b1():
    from app.modules.lego.drama_crawler import DATA_SOURCE_HEALTH
    assert isinstance(DATA_SOURCE_HEALTH, dict)
    assert "douyin" in DATA_SOURCE_HEALTH
    assert "bilibili" in DATA_SOURCE_HEALTH
    print(f"     → 平台数: {len(DATA_SOURCE_HEALTH)}")

@case("B2. get_data_source_health() 返回健康度")
def t_b2():
    from app.modules.lego.drama_crawler import DramaCrawler
    health = DramaCrawler.get_data_source_health()
    assert "douyin" in health
    assert "real" in health["douyin"]
    print(f"     → douyin: real={health['douyin']['real']}, source={health['douyin']['source'][:30]}")

@case("B3. DATA_SOURCE_HEALTH 反映真实 API 可用性")
def t_b3():
    from app.modules.lego.drama_crawler import DramaCrawler
    from app.modules.lego.stealth_browser import is_playwright_available
    c = DramaCrawler()
    if is_playwright_available():
        # 如果 Playwright 可用, douyin 应该是 real=True
        douyin_api = c._apis.get("douyin")
        api_class = type(douyin_api).__name__
        assert api_class == "DouyinPlaywrightAPI", f"Playwright 可用时 douyin 应是 Playwright API, 实际 {api_class}"
        print(f"     → douyin API: {api_class} (Playwright 可用 ✓)")
    else:
        print(f"     → Playwright 不可用, 跳过")

@case("B4. fetch 后 data_freshness 正确")
def t_b4():
    from app.modules.lego.drama_crawler import DramaCrawler
    c = DramaCrawler()
    c.clear_cache()
    c.fetch_dramas(page=1, page_size=20)
    freshness = c.get_data_freshness()
    assert "has_real" in freshness
    assert "is_pure_fallback" in freshness
    assert "sources" in freshness
    print(f"     → has_real={freshness['has_real']}, pure_fallback={freshness['is_pure_fallback']}, sources={len(freshness['sources'])}")

@case("B5. get_last_errors() 返回 list")
def t_b5():
    from app.modules.lego.drama_crawler import DramaCrawler
    c = DramaCrawler()
    c.clear_cache()
    c.fetch_dramas(page=1, page_size=20)
    errs = c.get_last_errors()
    assert isinstance(errs, list)
    print(f"     → 错误数: {len(errs)}")

@case("B6. TikHub 注入不覆盖 Playwright")
def t_b6():
    from app.modules.lego.drama_crawler import DramaCrawler
    from app.modules.lego.stealth_browser import is_playwright_available
    c = DramaCrawler()
    douyin_api = c._apis.get("douyin")
    api_class = type(douyin_api).__name__
    if is_playwright_available():
        # Playwright 可用时不应被 TikHub 覆盖
        assert api_class == "DouyinPlaywrightAPI", f"被 TikHub 覆盖了: {api_class}"
    print(f"     → douyin API 类: {api_class}")

# ============================================================
# C. 边界与异常
# ============================================================
print("\n[C] 边界与异常测试")
print("-" * 70)

@case("C1. 空关键词 (keyword='') 不崩溃")
def t_c1():
    from app.modules.lego.drama_crawler import DramaCrawler
    c = DramaCrawler()
    c.clear_cache()
    data = c.fetch_dramas(keyword="", page_size=20)
    assert len(data) > 0
    print(f"     → {len(data)} 条")

@case("C2. 超长关键词 (1000 字符) 不崩溃")
def t_c2():
    from app.modules.lego.drama_crawler import DramaCrawler
    c = DramaCrawler()
    c.clear_cache()
    long_kw = "短剧" * 500
    data = c.fetch_dramas(keyword=long_kw, page_size=20)
    assert isinstance(data, list)
    print(f"     → 超长关键词返回 {len(data)} 条")

@case("C3. 特殊字符关键词 (emoji/特殊符号) 不崩溃")
def t_c3():
    from app.modules.lego.drama_crawler import DramaCrawler
    c = DramaCrawler()
    c.clear_cache()
    for kw in ["短剧!@#$%^&*()", "短剧\n\t", "短剧💕🍿", "<script>alert(1)</script>"]:
        data = c.fetch_dramas(keyword=kw, page_size=10)
        assert isinstance(data, list), f"特殊字符 '{kw[:20]}...' 崩溃"
    print(f"     → 4 种特殊字符关键词均正常")

@case("C4. 不存在的平台 fallback")
def t_c4():
    from app.modules.lego.drama_crawler import DramaCrawler
    c = DramaCrawler()
    c.clear_cache()
    data = c.fetch_dramas(platform="notexist", page_size=20)
    assert isinstance(data, list), "未识别平台应 fallback"
    print(f"     → 不存在平台返回 {len(data)} 条")

@case("C5. 不存在的分类 fallback")
def t_c5():
    from app.modules.lego.drama_crawler import DramaCrawler
    c = DramaCrawler()
    c.clear_cache()
    data = c.fetch_dramas(category="notexist", page_size=20)
    assert isinstance(data, list)
    print(f"     → 不存在分类返回 {len(data)} 条")

@case("C6. min_views/min_heat 极端值")
def t_c6():
    from app.modules.lego.drama_crawler import DramaCrawler
    c = DramaCrawler()
    c.clear_cache()
    data = c.fetch_dramas(min_views=999999999, min_heat=999999999, page_size=50)
    print(f"     → 极高门槛后剩余 {len(data)} 条 (可能为空, 不应崩)")

@case("C7. content_type=drama/comic/movie/tv")
def t_c7():
    from app.modules.lego.drama_crawler import DramaCrawler
    c = DramaCrawler()
    for ct in ["drama", "comic", "movie", "tv", "all", "unknown"]:
        c.clear_cache()
        data = c.fetch_dramas(content_type=ct, page_size=10)
        assert isinstance(data, list)
    print(f"     → 6 种 content_type 均正常")

@case("C8. clear_cache() 行为正确")
def t_c8():
    from app.modules.lego.drama_crawler import DramaCrawler
    c = DramaCrawler()
    c.fetch_dramas(keyword="test_clear", page_size=10)
    c.clear_cache()
    # 重新拉取应该不报错
    data = c.fetch_dramas(keyword="test_clear", page_size=10)
    assert isinstance(data, list)
    print(f"     → 清理后重新拉取 OK")

@case("C9. DramaInfo dataclass 字段完整")
def t_c9():
    from app.modules.lego.drama_crawler import DramaInfo, DramaCrawler
    c = DramaCrawler()
    data = c.fetch_dramas(page=1, page_size=5)
    if data:
        d = data[0]
        required = ["id", "title", "platform", "category", "tags", "episodes", "views",
                    "likes", "commission", "rating", "heat", "cover_url", "source_url",
                    "score", "recommend_reason", "status", "author", "update_time"]
        for f in required:
            assert hasattr(d, f), f"DramaInfo 缺字段: {f}"
        print(f"     → {len(required)} 个字段齐全")

# ============================================================
# D. UI 集成 (仅检查方法存在, 不弹窗)
# ============================================================
print("\n[D] UI 集成测试")
print("-" * 70)

@case("D1. get_help_text() 包含关键说明")
def t_d1():
    from app.modules.lego.drama_crawler import DramaCrawler
    help_text = DramaCrawler.get_help_text()
    assert "Playwright" in help_text
    assert "TikHub" in help_text
    assert "TIKHUB_API_TOKEN" in help_text
    assert "0.04" in help_text
    assert "Q1" in help_text
    print(f"     → 帮助文档长度: {len(help_text)} 字符")

@case("D2. DATA_SOURCE_HELP 模块常量")
def t_d2():
    from app.modules.lego.drama_crawler import DATA_SOURCE_HELP
    assert "Playwright" in DATA_SOURCE_HELP
    assert "TikHub" in DATA_SOURCE_HELP
    print(f"     → 模块常量长度: {len(DATA_SOURCE_HELP)} 字符")

@case("D3. 持久化 - 收藏")
def t_d3():
    from app.modules.lego.user_prefs_store import add_to_favorites, remove_from_favorites, load_user_prefs
    test_id = "debug_test_001"
    add_to_favorites(test_id)
    prefs = load_user_prefs()
    assert test_id in prefs["favorites"], "添加收藏失败"
    remove_from_favorites(test_id)
    prefs = load_user_prefs()
    assert test_id not in prefs["favorites"], "取消收藏失败"
    print(f"     → 收藏 / 取消收藏 OK")

@case("D4. 持久化 - 历史")
def t_d4():
    from app.modules.lego.user_prefs_store import add_to_history, load_user_prefs
    test_id = "debug_test_history_001"
    add_to_history(test_id, max_len=10)
    prefs = load_user_prefs()
    assert test_id in prefs["view_history"], "添加历史失败"
    print(f"     → 历史记录 OK (当前 {len(prefs['view_history'])} 条)")

@case("D5. 持久化 - 偏好")
def t_d5():
    from app.modules.lego.user_prefs_store import set_user_preference, load_user_prefs
    test_key = "debug_pref_key"
    test_val = {"foo": "bar", "n": 42}
    set_user_preference(test_key, test_val)
    prefs = load_user_prefs()
    assert prefs["user_preferences"].get(test_key) == test_val, "偏好保存失败"
    print(f"     → 偏好保存/读取 OK")

# ============================================================
# E. 极端异常 - 不崩
# ============================================================
print("\n[E] 异常路径覆盖")
print("-" * 70)

@case("E1. fetch_dramas 内部异常被捕获")
def t_e1():
    from app.modules.lego.drama_crawler import DramaCrawler
    c = DramaCrawler()
    # 模拟一个 API 抛异常
    class BoomAPI:
        def fetch(self, *a, **kw):
            raise RuntimeError("boom!")
        def is_available(self): return True
    c._apis["__boom__"] = BoomAPI()
    try:
        data = c.fetch_dramas(platform="__boom__", page_size=10)
        # 不应崩
        assert isinstance(data, list)
        print(f"     → 内部异常被捕获, 返回 {len(data)} 条")
    finally:
        c._apis.pop("__boom__", None)

@case("E2. fetch_dramas 返回 None (真实 API 失败)")
def t_e2():
    from app.modules.lego.drama_crawler import DramaCrawler
    c = DramaCrawler()
    class NoneAPI:
        def fetch(self, *a, **kw): return None
        def is_available(self): return True
    c._apis["__none__"] = NoneAPI()
    try:
        data = c.fetch_dramas(platform="__none__", page_size=10)
        assert isinstance(data, list)
        print(f"     → None 返回值被优雅处理, 拿到 {len(data)} 条 fallback")
    finally:
        c._apis.pop("__none__", None)

@case("E3. 并发调用 5 次不冲突")
def t_e3():
    import threading
    from app.modules.lego.drama_crawler import DramaCrawler
    c = DramaCrawler()
    results_list = [None] * 5
    def worker(i):
        c.clear_cache()
        results_list[i] = c.fetch_dramas(page=1, page_size=10)
    threads = [threading.Thread(target=worker, args=(i,)) for i in range(5)]
    for t in threads: t.start()
    for t in threads: t.join()
    assert all(isinstance(r, list) for r in results_list), "并发调用出错"
    print(f"     → 5 并发均正常, 各拿到 {len(results_list[0])} 条")


# ============================================================
# 收集并执行
# ============================================================
print("=" * 70)
print("  短剧筛选模块调试")
print("=" * 70)
print(f"  收集中: {len(_all_cases)} 个用例")
print()

for name, fn in _all_cases:
    t0 = time.time()
    try:
        fn()
        results["pass"] += 1
        print(f"[OK]   {name}  ({time.time()-t0:.2f}s)")
    except AssertionError as e:
        results["fail"] += 1
        results["errors"].append((name, str(e)))
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
