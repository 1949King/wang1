"""
app/tests/test_draw_loop_defects.py - 抽卡闭环深度求索修复回归

覆盖 2026-09-27 深度求索报告中的两处缺陷：
- DEFECT A：测试不得写入生产账本（由 conftest 自动隔离，此处置于用例内再证一次）
- DEFECT B：Agent 能力 canvas.generate_image 必须透传 seed（此前被吃掉，不可复现）
"""

import json
import os

from app.core.capability_dispatcher import CapabilityRequest
from app.core.capability_handlers import CanvasCapabilityHandlers


# ─────────────────────── DEFECT A：账本隔离 ───────────────────────

def test_draw_book_default_path_honors_env(monkeypatch, tmp_path):
    """环境变量 DRAW_BOOK_STORE_PATH 应覆盖默认路径（测试隔离的支点）。"""
    from app.core.ai import draw_book
    target = tmp_path / "isolated_db.json"
    monkeypatch.setenv("DRAW_BOOK_STORE_PATH", str(target))
    store = draw_book.DrawBookStore()
    store.record_draw("隔离测试", "m", 0.9, seed=1, kind="image")
    assert target.exists(), "账本应写到环境变量指定的隔离路径"
    data = json.loads(target.read_text(encoding="utf-8"))
    assert len(data) == 1


def test_quality_prior_default_path_honors_env(monkeypatch, tmp_path):
    """环境变量 QUALITY_PRIOR_PATH 应覆盖默认路径。"""
    from app.core.ai import quality_prior
    target = tmp_path / "isolated_qp.json"
    monkeypatch.setenv("QUALITY_PRIOR_PATH", str(target))
    store = quality_prior.QualityPriorStore()
    store.record("c_test", 1.0, kind="default")
    assert target.exists()


def test_conftest_isolates_production_ledgers():
    """自动隔离 fixture 生效时，生产账本不应出现在本进程的默认路径上。

    这里只断言「环境变量已由 conftest 设成 tmp 路径」，即代表性证据。
    """
    db = os.environ.get("DRAW_BOOK_STORE_PATH", "")
    qp = os.environ.get("QUALITY_PRIOR_PATH", "")
    assert db and "draw_book.json" in db, "conftest 应已重定向 draw_book 路径"
    assert qp and "quality_prior.json" in qp, "conftest 应已重定向 quality_prior 路径"
    # 且不应指向仓库正式 data/ 目录
    assert os.path.sep + "data" + os.path.sep not in db, "不得指向正式 data/ 目录"


# ─────────────────────── DEFECT B：Agent 生图透传 seed ───────────────────────

def _make_handler():
    return CanvasCapabilityHandlers()


def test_generate_image_passes_seed(monkeypatch):
    """显式 seed 应原样透传给底层生图函数。"""
    captured = {}

    def fake_gen(**kwargs):
        captured.update(kwargs)
        return {"ok": True, "seed": kwargs.get("seed"), "seed_sent": True}

    # handler 内是惰性 from-import，需打到模块属性上
    import app.core.canvas_aigc as aigc
    monkeypatch.setattr(aigc, "generate_image_openai_compatible", fake_gen)

    h = _make_handler()
    req = CapabilityRequest("canvas.generate_image",
                            params={"prompt": "一只猫", "seed": 12345})
    res = h.generate_image(req)
    assert res.success is True
    assert captured.get("seed") == 12345, "seed 必须透传到底层"


def test_generate_image_seed_none_when_absent(monkeypatch):
    """未给 seed 时应传 None（由底层自动生成随机种子），而非 0 或字符串。"""
    captured = {}

    def fake_gen(**kwargs):
        captured.update(kwargs)
        return {"ok": True}

    import app.core.canvas_aigc as aigc
    monkeypatch.setattr(aigc, "generate_image_openai_compatible", fake_gen)

    h = _make_handler()
    req = CapabilityRequest("canvas.generate_image", params={"prompt": "一只狗"})
    h.generate_image(req)
    assert captured.get("seed") is None


def test_generate_image_seed_invalid_is_none(monkeypatch):
    """非法 seed（非整数）应归一为 None，不得抛异常中断生图。"""
    captured = {}

    def fake_gen(**kwargs):
        captured.update(kwargs)
        return {"ok": True}

    import app.core.canvas_aigc as aigc
    monkeypatch.setattr(aigc, "generate_image_openai_compatible", fake_gen)

    h = _make_handler()
    req = CapabilityRequest("canvas.generate_image",
                            params={"prompt": "一只鸟", "seed": "不是数字"})
    res = h.generate_image(req)
    assert res.success is True
    assert captured.get("seed") is None
