"""app/tests/test_draw_orchestrator.py — 抽卡选优编排（刀 A2）回归（2026-10-05）。

锁定刀 A2 的五件事：
  ① **选最优**——按代理分降序取第一，无分的候选不被优先选中；
  ② **不重复记账**——n 张在各自生成收尾已入账，编排**绝不再调**
     `feed_draw_ledger` / `draw_book.record_draw`（重复入账会污染 EMA 与新鲜度）；
  ③ **种子可复现**——给 base_seed ⇒ 第 i 张用 base_seed+i；
  ④ **诚实失败**——全失败 ok=False 且逐张原因保留；部分失败如实报张数；
  ⑤ **代理分不冒充真值**——恒带 `is_proxy=True` + 白话 advice。

注：本测试不真调网络（monkeypatch 生成函数），不写账本。
"""
import inspect
import pathlib
import re

from app.core.ai import draw_orchestrator as DO

ROOT = pathlib.Path(__file__).resolve().parents[2]


# ─────────────────────── ① clamp_n ───────────────────────

def test_clamp_n_default_and_bounds():
    assert DO.clamp_n(4)[0] == 4
    assert DO.clamp_n(1)[0] == 1
    assert DO.clamp_n(DO.MAX_N)[0] == DO.MAX_N


def test_clamp_n_out_of_range_is_honest():
    """越界不静默截断 —— 必须给 note 说明（诚实原则）。"""
    n, note = DO.clamp_n(0)
    assert n == 1 and "非法" in note
    n2, note2 = DO.clamp_n(99)
    assert n2 == DO.MAX_N and "上限" in note2
    n3, note3 = DO.clamp_n("abc")
    assert n3 == DO.DEFAULT_N and note3 == ""  # 非法输入按默认，不算越界


def test_max_n_locked():
    """单次张数上限锁死（每张都是真实云端额度，不得放开）。"""
    assert DO.MAX_N == 6


# ─────────────────────── ② 选优逻辑 ───────────────────────

def _fake_gen(scores, *, fail_idx=()):
    """造一个假生成函数：按 index 顺序返回受控分数。"""
    calls = {"kw": [], "i": 0}

    def _gen(**kw):
        i = calls["i"]
        calls["i"] += 1
        calls["kw"].append(kw)
        if i in fail_idx:
            return {"ok": False, "message": f"第{i}张炸了"}
        return {"ok": True, "image_data_url": f"data:image/png;base64,img{i}",
                "proxy_score": scores[i], "seed": kw.get("seed"),
                "seed_sent": kw.get("seed") is not None, "size": kw.get("size") or "768x1344",
                "proxy_detail": {"i": i}}

    return _gen, calls


def test_best_of_picks_highest_score(monkeypatch):
    gen, calls = _fake_gen([0.41, 0.88, 0.62, 0.55])
    monkeypatch.setattr("app.core.canvas_aigc.generate_image_openai_compatible", gen)
    r = DO.best_of_n(prompt="a girl", n=4)
    assert r["ok"] is True
    assert r["generated"] == 4 and r["failed"] == 0
    assert r["best"]["index"] == 1 and abs(r["best"]["score"] - 0.88) < 1e-9
    assert len(r["candidates"]) == 4
    assert r["api_calls"] == 4  # 成本透明


def test_unscored_candidate_not_preferred(monkeypatch):
    """无代理分的候选必须垫后——不得因顺序靠前而压过有分的。

    （模块对缺分候选会**本地补算一次**（不入账）；此用例让补算也拿不到分，
    以覆盖「确实无分」的垫后分支。）
    """
    monkeypatch.setattr("app.core.ai.gen_critic.score_image",
                        lambda *a, **k: {"score": None, "detail": {}, "is_proxy": True})

    def _gen(**kw):
        i = _gen.i = getattr(_gen, "i", 0)
        _gen.i = i + 1
        res = {"ok": True, "image_data_url": f"data:img{i}", "seed": 1, "seed_sent": True}
        if i != 0:
            res["proxy_score"] = 0.9
        return res

    monkeypatch.setattr("app.core.canvas_aigc.generate_image_openai_compatible", _gen)
    r = DO.best_of_n(prompt="x", n=2)
    assert r["ok"] and r["best"]["index"] == 1
    assert any("无代理分" in x for x in r["reasons"])


# ─────────────────────── ③ 种子策略 ───────────────────────

def test_base_seed_increments_for_reproducibility(monkeypatch):
    gen, calls = _fake_gen([0.5, 0.5, 0.5])
    monkeypatch.setattr("app.core.canvas_aigc.generate_image_openai_compatible", gen)
    DO.best_of_n(prompt="x", n=3, base_seed=100)
    assert [c["seed"] for c in calls["kw"]] == [100, 101, 102]


def test_no_base_seed_leaves_none(monkeypatch):
    gen, calls = _fake_gen([0.5])
    monkeypatch.setattr("app.core.canvas_aigc.generate_image_openai_compatible", gen)
    DO.best_of_n(prompt="x", n=1)
    assert calls["kw"][0]["seed"] is None  # 交给生成层随机


# ─────────────────────── ④ 诚实失败 ───────────────────────

def test_all_failed_is_honest(monkeypatch):
    gen, _ = _fake_gen([0, 0], fail_idx=(0, 1))
    monkeypatch.setattr("app.core.canvas_aigc.generate_image_openai_compatible", gen)
    r = DO.best_of_n(prompt="x", n=2)
    assert r["ok"] is False and r["best"] is None
    assert r["generated"] == 0 and r["failed"] == 2
    assert len(r["candidates"]) == 2  # 失败候选也保留（可排障）
    assert "全部生成失败" in r["message"]


def test_partial_failure_reports_count(monkeypatch):
    gen, _ = _fake_gen([0.7, 0.2], fail_idx=(1,))
    monkeypatch.setattr("app.core.canvas_aigc.generate_image_openai_compatible", gen)
    r = DO.best_of_n(prompt="x", n=2)
    assert r["ok"] is True and r["generated"] == 1 and r["failed"] == 1
    assert any("失败" in x for x in r["reasons"])


def test_empty_prompt_fails_fast(monkeypatch):
    called = {"n": 0}

    def _gen(**kw):
        called["n"] += 1
        return {"ok": True}

    monkeypatch.setattr("app.core.canvas_aigc.generate_image_openai_compatible", _gen)
    r = DO.best_of_n(prompt="   ", n=3)
    assert r["ok"] is False and called["n"] == 0  # 不该白花额度


# ─────────────────────── ⑤ 代理分红线 + 不重复记账 ───────────────────────

def test_is_proxy_redline(monkeypatch):
    gen, _ = _fake_gen([0.6])
    monkeypatch.setattr("app.core.canvas_aigc.generate_image_openai_compatible", gen)
    r = DO.best_of_n(prompt="x", n=1)
    assert r["is_proxy"] is True
    assert "代理分" in r["advice"] and "非审美真值" in r["advice"]


def test_never_re_records_to_ledger(monkeypatch):
    """★ 核心纪律：编排层绝不重复入账（生成收尾已入账）。"""
    ledger_calls = {"feed": 0, "record": 0}
    monkeypatch.setattr("app.core.ai.draw_ledger.feed_draw_ledger",
                        lambda *a, **k: ledger_calls.__setitem__("feed", ledger_calls["feed"] + 1))
    monkeypatch.setattr("app.core.ai.draw_book.DrawBookStore.record_draw",
                        lambda *a, **k: ledger_calls.__setitem__("record", ledger_calls["record"] + 1))
    gen, _ = _fake_gen([0.5, 0.6, 0.7])
    monkeypatch.setattr("app.core.canvas_aigc.generate_image_openai_compatible", gen)
    DO.best_of_n(prompt="x", n=3)
    assert ledger_calls == {"feed": 0, "record": 0}


def test_source_has_no_ledger_write():
    """源码级锁：编排模块不得出现 feed_draw_ledger / record_draw 的调用。"""
    src = (ROOT / "app" / "core" / "ai" / "draw_orchestrator.py").read_text(encoding="utf-8")
    body = re.sub(r"^\s*#.*$", "", src, flags=re.M)          # 去注释行
    body = re.sub(r'"""[\s\S]*?"""', "", body)               # 去 docstring
    assert "feed_draw_ledger(" not in body
    assert "record_draw(" not in body


def test_never_raises_on_broken_generator(monkeypatch):
    def _boom(**kw):
        raise RuntimeError("模拟生成层异常")

    monkeypatch.setattr("app.core.canvas_aigc.generate_image_openai_compatible", _boom)
    r = DO.best_of_n(prompt="x", n=2)
    assert r["ok"] is False and r["failed"] == 2  # 异常不外抛


# ─────────────────────── 能力接线 ───────────────────────

def test_catalog_rows_present():
    from app.core.agent_capability_catalog import CAPABILITY_ROWS
    ids = [r[0] for r in CAPABILITY_ROWS]
    assert "canvas.best_of_draw" in ids and "canvas.repair_image" in ids
    for cid in ("canvas.best_of_draw", "canvas.repair_image"):
        row = next(r for r in CAPABILITY_ROWS if r[0] == cid)
        assert row[1] == "canvas" and row[2] == "media_write"
        assert row[3] is True, f"{cid} 会花云端额度 ⇒ paid 必须为 True"


def test_handlers_implemented():
    from app.core.capability_handlers import CanvasCapabilityHandlers
    h = CanvasCapabilityHandlers()
    for name in ("best_of_draw", "repair_image"):
        assert hasattr(h, name)
        assert len(inspect.signature(getattr(h, name)).parameters) == 1


def test_repair_requires_image():
    from app.core.capability_dispatcher import CapabilityRequest
    from app.core.capability_handlers import CanvasCapabilityHandlers
    req = CapabilityRequest(request_id="t", capability_id="canvas.repair_image", params={})
    res = CanvasCapabilityHandlers().repair_image(req)
    assert res.success is False and "image" in (res.error or "")
