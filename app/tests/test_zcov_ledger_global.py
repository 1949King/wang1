"""app/tests/test_zcov_ledger_global.py — L0 全局价格层专项测试（2026-10-09）。

覆盖 `app/core/ai/global_price.py`：三层价格体系的 L0 全局层
（月度预算影子价格控制器 + 任务间配额拍卖）。

为什么补（背景）：
    该模块此前**完全没有专门测试**，只有间接覆盖；2026-10-09 加入测试隔离
    （GLOBAL_PRICE_STORE_PATH）后间接覆盖消失。它是「月度账单上限」的守门员，
    也是多任务竞价的核心不变量承载者（Σ 分配 ≤ 全局剩余预算），坏一次就是
    预算失控，故必须直接锁住。

纪律（与 task 要求一致）：
  · 一律显式构造 `GlobalPriceController(store_path=tmp_path/...)`，
    **不使用 `get_global_price()` 单例**，测试绝不写正式账本；
  · 时间相关项（月进度 / 当前月）用 monkeypatch 固定，避免「月初跑绿、月末跑红」；
  · 每个断言都指向**可观察行为**（λ 是否变、配额怎么分、账是否落盘），
    不写 `assert True` 凑数。

风格参考 app/tests/test_zcov_core_a.py。
"""
import threading
import time

import pytest

from app.core.ai import global_price as gp
from app.core.ai.global_price import (
    GlobalPriceController,
    _KAPPA_GEARS,
    _LG_INIT,
    _LG_MAX,
    _LG_MIN,
    _RATE_LIMIT_G,
    _month,
    _month_progress,
    _resolve_store_path,
)


# ────────────────────────────── 工具 ──────────────────────────────

def _ctrl(tmp_path, name="gp.json", **kw):
    """显式构造控制器，账本一律落在 tmp_path（绝不碰正式账本）。"""
    return GlobalPriceController(store_path=str(tmp_path / name), **kw)


def _tick(c):
    """驱动一次 PI 迭代。

    生产周期 T=60s，且 interval 下限被夹到 1.0s；测试里把「上次更新时刻」
    拨回 0 以确定性地跨过周期门，避免依赖 sleep（既慢又不稳）。
    """
    c._last_update = 0.0
    return c.get_lambda()


# ────────────────────────────── 模块级助手 ──────────────────────────────

class TestModuleHelpers:
    def test_month_format_is_year_dash_month(self):
        m = _month()
        assert len(m) == 7 and m[4] == "-"
        assert m[:4].isdigit() and m[5:].isdigit()

    def test_month_progress_is_in_unit_interval(self):
        """进度必须落在 [0, 1)：等于 1 会让剩余时间比归零、误差算崩。"""
        p = _month_progress()
        assert 0.0 <= p < 1.0

    def test_kappa_gears_are_the_three_spec_tiers(self):
        assert _KAPPA_GEARS == (0.5, 1.0, 2.0)

    def test_resolve_store_path_env_override(self, monkeypatch):
        monkeypatch.setenv("GLOBAL_PRICE_STORE_PATH", "/tmp/isolated_gp.json")
        assert _resolve_store_path() == "/tmp/isolated_gp.json"

    def test_resolve_store_path_blank_env_falls_back_to_default(self, monkeypatch):
        """空白环境变量视为未设置 —— 否则会解析出空路径去写。"""
        monkeypatch.setenv("GLOBAL_PRICE_STORE_PATH", "   ")
        assert _resolve_store_path() == gp._DEFAULT_STORE

    def test_resolve_store_path_without_env(self, monkeypatch):
        monkeypatch.delenv("GLOBAL_PRICE_STORE_PATH", raising=False)
        assert _resolve_store_path() == gp._DEFAULT_STORE


# ────────────────────────────── 构造与参数归一 ──────────────────────────────

class TestConstructor:
    def test_default_budget(self, tmp_path):
        assert _ctrl(tmp_path)._budget == 500.0

    @pytest.mark.parametrize("given", [0.0, -10.0])
    def test_budget_has_floor_of_one(self, tmp_path, given):
        """预算下界 1.0：除以 0 会让误差函数直接炸。"""
        c = _ctrl(tmp_path, name=f"b{given}.json", monthly_budget=given)
        assert c._budget == 1.0

    @pytest.mark.parametrize(
        "kappa,expected",
        [(0.6, 0.5), (1.4, 1.0), (3.0, 2.0), (0.0, 0.5), (-5.0, 0.5)],
    )
    def test_kappa_snaps_to_nearest_gear(self, tmp_path, kappa, expected):
        """§33 灵敏度归一化：任意 κ 都要落到三档之一，防止参数爆炸。"""
        c = _ctrl(tmp_path, name=f"k{kappa}.json", kappa=kappa)
        assert c._kappa == expected

    def test_update_interval_has_floor(self, tmp_path):
        c = _ctrl(tmp_path, update_interval=0.0)
        assert c._interval == 1.0

    def test_initial_state(self, tmp_path):
        c = _ctrl(tmp_path)
        assert c._spent == 0.0 and c._lam == _LG_INIT
        assert c._pi_ready is False and c._obs_valid is True
        assert c._loaded is False


# ────────────────────────────── 记账 ──────────────────────────────

class TestRecordSpend:
    def test_amounts_accumulate(self, tmp_path):
        c = _ctrl(tmp_path)
        c.record_spend(3.5)
        c.record_spend(1.5)
        assert c.status()["spent"] == pytest.approx(5.0)

    @pytest.mark.parametrize("bad", [0, 0.0, -1.0, "abc", None, [1]])
    def test_invalid_or_nonpositive_amounts_are_ignored(self, tmp_path, bad):
        """非法/非正金额一律静默丢弃 —— 调用方不该因为它崩主流程。"""
        c = _ctrl(tmp_path)
        c.record_spend(bad)
        assert c.status()["spent"] == 0.0

    def test_remaining_never_negative_when_overspent(self, tmp_path):
        c = _ctrl(tmp_path, monthly_budget=100)
        c.record_spend(150)
        s = c.status()
        assert s["remaining"] == 0.0
        assert s["spent"] == pytest.approx(150.0)


# ────────────────────────────── 误差与状态 ──────────────────────────────

class TestErrorAndStatus:
    def test_status_shape(self, tmp_path):
        c = _ctrl(tmp_path, monthly_budget=200)
        c.record_spend(50)
        s = c.status()
        assert s["budget"] == 200.0
        assert s["spent"] == 50.0
        assert s["remaining"] == pytest.approx(150.0)
        assert s["lambda_g_bounds"] == [_LG_MIN, _LG_MAX]
        assert s["rate_limit"] == _RATE_LIMIT_G
        assert s["kappa"] == 1.0
        assert 0.0 <= s["month_progress"] < 1.0

    def test_error_is_left_ratio_minus_time_ratio(self, tmp_path, monkeypatch):
        monkeypatch.setattr(gp, "_month_progress", lambda: 0.2)
        c = _ctrl(tmp_path, monthly_budget=100)
        # 未花钱：剩余预算比 1.0 − 剩余时间比 0.8 = +0.2
        assert c._error_locked() == pytest.approx(1.0 - 0.8)
        c.record_spend(90)  # 剩余预算比 0.1 < 剩余时间比 0.8
        assert c._error_locked() == pytest.approx(0.1 - 0.8)

    def test_error_floor_of_time_ratio(self, tmp_path, monkeypatch):
        """剩余时间比有 0.02 下限 —— 月末最后一刻也不会把误差推到极端。"""
        monkeypatch.setattr(gp, "_month_progress", lambda: 0.999)
        c = _ctrl(tmp_path, monthly_budget=100)
        assert c._error_locked() == pytest.approx(1.0 - 0.02)

    def test_over_pacing_flag_tracks_error_sign(self, tmp_path, monkeypatch):
        monkeypatch.setattr(gp, "_month_progress", lambda: 0.5)
        c = _ctrl(tmp_path, monthly_budget=100)
        assert c.status()["over_pacing"] is False   # 未花钱，剩余比 1.0 > 0.5
        c.record_spend(80)                          # 剩余比 0.2 < 0.5
        s = c.status()
        assert s["over_pacing"] is True and s["error"] < 0


# ────────────────────────────── λ 动力学 ──────────────────────────────

class TestLambdaDynamics:
    def test_first_update_only_builds_baseline(self, tmp_path, monkeypatch):
        """§35 恢复/启动首拍只采基线不动作（杜绝阶跃抖动）。"""
        monkeypatch.setattr(gp, "_month_progress", lambda: 0.5)
        c = _ctrl(tmp_path, monthly_budget=100, update_interval=1.0)
        c.record_spend(100)          # e = -0.5，强烈超支
        _tick(c)                     # 首拍：仅建基线
        assert c.status()["lambda_g"] == 0.0
        assert c._pi_ready is True

    def test_overspend_raises_lambda_within_rate_limit(self, tmp_path, monkeypatch):
        monkeypatch.setattr(gp, "_month_progress", lambda: 0.5)
        c = _ctrl(tmp_path, monthly_budget=100, update_interval=1.0)
        c.record_spend(100)          # e = -0.5
        _tick(c)                     # baseline
        prev = c.status()["lambda_g"]
        _tick(c)                     # 真步进
        lam = c.status()["lambda_g"]
        assert lam > prev
        assert lam - prev <= _RATE_LIMIT_G + 1e-9

    def test_lambda_bounded_and_rate_limited_over_many_steps(
        self, tmp_path, monkeypatch
    ):
        """连续超支下：每步 ≤0.1 且 λ 单调升、始终封顶在 _LG_MAX 内。"""
        monkeypatch.setattr(gp, "_month_progress", lambda: 0.5)
        c = _ctrl(tmp_path, monthly_budget=100, update_interval=1.0)
        c.record_spend(100)
        prev = 0.0
        for _ in range(20):
            _tick(c)
            lam = c.status()["lambda_g"]
            assert lam >= prev - 1e-9
            assert lam - prev <= _RATE_LIMIT_G + 1e-9
            assert _LG_MIN - 1e-9 <= lam <= _LG_MAX + 1e-9
            prev = lam
        assert prev == pytest.approx(_LG_MAX, abs=1e-3)

    def test_interval_gate_skips_update_within_period(self, tmp_path, monkeypatch):
        """周期锁死（T=60s）：未跨周期时不得推进状态/重算 λ。"""
        monkeypatch.setattr(gp, "_month_progress", lambda: 0.5)
        c = _ctrl(tmp_path, monthly_budget=100, update_interval=60.0)
        c.record_spend(100)
        marker = time.time()
        c._last_update = marker
        c.get_lambda()
        assert c._last_update == marker      # 未跨周期 → 未推进

    def test_underspend_lowers_lambda(self, tmp_path, monkeypatch):
        monkeypatch.setattr(gp, "_month_progress", lambda: 0.5)
        c = _ctrl(tmp_path, monthly_budget=100, update_interval=1.0)
        c._lam = 0.4
        c._pi_ready = False          # 人为抬高，观察回落
        _tick(c)                     # baseline
        _tick(c)                     # e = +0.5 → λ 降
        assert c.status()["lambda_g"] < 0.4

    def test_kappa_scales_gain_below_rate_limit(self, tmp_path, monkeypatch):
        """κ 三档整体缩放增益：余额充足（步长未触限速）时应能观察到差异。

        e = 0.4 − 0.5 = −0.1 ⇒ Δλ = 0.3·κ·0.1 = 0.03κ（均 < 0.1 限幅）。
        """
        monkeypatch.setattr(gp, "_month_progress", lambda: 0.5)
        lam = {}
        for kappa in (0.5, 2.0):
            c = _ctrl(tmp_path, name=f"k{kappa}.json", monthly_budget=100,
                      kappa=kappa, update_interval=1.0)
            c.record_spend(60)
            _tick(c)
            _tick(c)
            lam[kappa] = c.status()["lambda_g"]
        assert lam[0.5] == pytest.approx(0.015, abs=1e-4)
        assert lam[2.0] == pytest.approx(0.06, abs=1e-4)
        assert lam[2.0] > lam[0.5]


# ────────────────────────────── 观测门控（§35） ──────────────────────────────

class TestObservationGate:
    def test_invalid_observation_freezes_lambda(self, tmp_path, monkeypatch):
        monkeypatch.setattr(gp, "_month_progress", lambda: 0.5)
        c = _ctrl(tmp_path, monthly_budget=100, update_interval=1.0)
        c.record_spend(100)
        c.set_observation(False, "断网")
        for _ in range(5):
            _tick(c)
        assert c.status()["lambda_g"] == 0.0
        assert c.status()["observation_valid"] is False

    def test_recovery_resets_pi_ready_for_baseline(self, tmp_path):
        """恢复后首个周期只建基线：把 _pi_ready 置 False（防阶跃）。"""
        c = _ctrl(tmp_path)
        c.set_observation(False)
        c.set_observation(True)
        assert c._pi_ready is False
        assert c.status()["observation_valid"] is True

    def test_repeated_same_state_is_harmless(self, tmp_path):
        c = _ctrl(tmp_path)
        c.set_observation(True)      # 本就是 True，不应误复位
        c.set_observation(True)
        assert c._obs_valid is True


# ────────────────────────────── 配额拍卖（§39） ──────────────────────────────

class TestAuction:
    def test_pressure_proportional_split(self, tmp_path):
        c = _ctrl(tmp_path, monthly_budget=100)
        r = c.auction({"A": 3.0, "B": 1.0})
        assert r["quotas"]["A"] == pytest.approx(75.0)
        assert r["quotas"]["B"] == pytest.approx(25.0)
        assert r["invariant_ok"] is True
        assert sum(r["quotas"].values()) <= r["remaining"] + 1e-9

    def test_high_pressure_gets_more(self, tmp_path):
        c = _ctrl(tmp_path, monthly_budget=100)
        r = c.auction({"hot": 9.0, "cold": 1.0})
        assert r["quotas"]["hot"] > r["quotas"]["cold"]

    def test_key_floor_then_pressure_residual(self, tmp_path):
        """关键任务先拿 50 保底，余 50 再按压力 1:1 均分 → A=75 / B=25。"""
        c = _ctrl(tmp_path, monthly_budget=100)
        r = c.auction({"A": 1.0, "B": 1.0}, key_tasks={"A": 0.5})
        assert r["quotas"]["A"] == pytest.approx(75.0)
        assert r["quotas"]["B"] == pytest.approx(25.0)

    def test_key_floors_drain_pool_first_come_first_served(self, tmp_path):
        """两个 key 任务各要 100% 保底：先到先得，A 吃满 100，B 无池可分。"""
        c = _ctrl(tmp_path, monthly_budget=100)
        r = c.auction({}, key_tasks={"A": 1.0, "B": 1.0})
        assert r["quotas"]["A"] == pytest.approx(100.0)
        assert r["quotas"]["B"] == pytest.approx(0.0)
        assert r["invariant_ok"] is True

    def test_key_task_not_in_pressures_still_gets_floor(self, tmp_path):
        c = _ctrl(tmp_path, monthly_budget=100)
        r = c.auction({"B": 1.0}, key_tasks={"A": 0.3})
        assert r["quotas"]["A"] == pytest.approx(30.0)

    def test_no_remaining_gives_zero_quota(self, tmp_path):
        c = _ctrl(tmp_path, monthly_budget=100)
        c.record_spend(100)
        r = c.auction({"A": 1.0})
        assert r["remaining"] == 0.0
        assert r["quotas"]["A"] == 0.0
        assert r["invariant_ok"] is True

    def test_empty_pressures_yields_empty_quotas(self, tmp_path):
        c = _ctrl(tmp_path, monthly_budget=100)
        r = c.auction({})
        assert r["quotas"] == {}
        assert r["invariant_ok"] is True

    def test_zero_total_pressure_allocates_nothing(self, tmp_path):
        c = _ctrl(tmp_path, monthly_budget=100)
        r = c.auction({"A": 0.0, "B": 0.0})
        assert r["quotas"] == {"A": 0.0, "B": 0.0}
        assert r["invariant_ok"] is True

    def test_negative_pressure_treated_as_zero(self, tmp_path):
        c = _ctrl(tmp_path, monthly_budget=100)
        r = c.auction({"A": -5.0, "B": 1.0})
        assert r["quotas"]["A"] == pytest.approx(0.0)
        assert r["quotas"]["B"] == pytest.approx(100.0)

    def test_debt_is_deducted_from_pressure_share(self, tmp_path):
        """§39：超支任务下期配额先抵欠账。各分 50，A 还 30 → 得 20。"""
        c = _ctrl(tmp_path, monthly_budget=100)
        c.report_task_spend("A", amount=80, quota=50)   # 欠 30
        r = c.auction({"A": 1.0, "B": 1.0})
        assert r["quotas"]["A"] == pytest.approx(20.0)
        assert r["quotas"]["B"] == pytest.approx(50.0)
        assert r["debts"]["A"] == pytest.approx(0.0)

    def test_debt_is_deducted_from_key_floor(self, tmp_path):
        """保底配额 ≥ 欠账时，欠账从保底里扣清。"""
        c = _ctrl(tmp_path, monthly_budget=100)
        c.report_task_spend("A", amount=90, quota=60)   # 欠 30
        r = c.auction({"B": 1.0}, key_tasks={"A": 1.0})
        assert r["quotas"]["A"] == pytest.approx(70.0)  # 100 保底 − 30 欠账
        assert r["debts"]["A"] == pytest.approx(0.0)

    def test_invariant_sum_never_exceeds_remaining(self, tmp_path):
        """永久不变量：Σ 分配 ≤ 全局剩余预算（混合场景压一遍）。"""
        c = _ctrl(tmp_path, monthly_budget=100)
        c.record_spend(30)                              # 剩余 70
        r = c.auction({"A": 5.0, "B": 3.0, "C": 1.0},
                      key_tasks={"A": 0.4, "C": 0.2})
        assert r["invariant_ok"] is True
        assert sum(r["quotas"].values()) <= r["remaining"] + 1e-9


# ────────────────────────────── 任务回报欠账 ──────────────────────────────

class TestReportTaskSpend:
    def test_over_quota_records_debt(self, tmp_path):
        c = _ctrl(tmp_path)
        c.report_task_spend("t", amount=30, quota=10)
        assert c._debts["t"] == pytest.approx(20.0)

    def test_under_quota_records_nothing(self, tmp_path):
        c = _ctrl(tmp_path)
        c.report_task_spend("t", amount=5, quota=10)
        assert c._debts.get("t", 0.0) == 0.0

    def test_exactly_quota_records_nothing(self, tmp_path):
        c = _ctrl(tmp_path)
        c.report_task_spend("t", amount=10, quota=10)
        assert "t" not in c._debts

    def test_debts_accumulate_across_reports(self, tmp_path):
        c = _ctrl(tmp_path)
        c.report_task_spend("t", 20, 10)   # +10
        c.report_task_spend("t", 15, 10)   # +5
        assert c._debts["t"] == pytest.approx(15.0)

    def test_negative_quota_treated_as_zero(self, tmp_path):
        """quota 被夹到 ≥0：否则 amount−负配额会凭空造出负欠账。"""
        c = _ctrl(tmp_path)
        c.report_task_spend("t", amount=10, quota=-5.0)
        assert c._debts["t"] == pytest.approx(10.0)


# ────────────────────────────── 持久化 ──────────────────────────────

class TestPersistence:
    def test_roundtrip_preserves_state(self, tmp_path):
        p = tmp_path / "gp.json"
        c1 = GlobalPriceController(monthly_budget=100, store_path=str(p))
        c1.record_spend(40)
        c1._lam = 0.25
        c1._i_term = 0.25
        c1._save_locked()

        c2 = GlobalPriceController(monthly_budget=100, store_path=str(p))
        c2._ensure_loaded()
        assert c2._spent == pytest.approx(40.0)
        assert c2._lam == pytest.approx(0.25)
        assert c2._i_term == pytest.approx(0.25)

    def test_corrupt_json_falls_back_without_raising(self, tmp_path):
        """损坏账本不能让控制器崩 —— 按初始状态启动。"""
        p = tmp_path / "gp.json"
        p.write_text("{ this is not json", encoding="utf-8")
        c = GlobalPriceController(monthly_budget=100, store_path=str(p))
        c._ensure_loaded()                              # 不抛
        s = c.status()
        assert s["spent"] == 0.0 and s["lambda_g"] == 0.0

    def test_non_dict_json_falls_back(self, tmp_path):
        p = tmp_path / "gp.json"
        p.write_text("[1, 2, 3]", encoding="utf-8")
        c = GlobalPriceController(monthly_budget=100, store_path=str(p))
        c._ensure_loaded()
        assert c._spent == 0.0

    def test_ensure_loaded_is_idempotent(self, tmp_path):
        c = _ctrl(tmp_path)
        c._ensure_loaded()
        c._ensure_loaded()
        assert c._loaded is True

    def test_save_creates_parent_directory(self, tmp_path):
        """账本目录不存在时应自动建目录（首次运行场景）。"""
        p = tmp_path / "nested" / "deep" / "gp.json"
        c = GlobalPriceController(monthly_budget=100, store_path=str(p))
        c.record_spend(1.0)
        assert p.exists()


# ────────────────────────────── 跨月结转 ──────────────────────────────

class TestRollover:
    def test_month_change_resets_spend_and_relaxes_lambda(
        self, tmp_path, monkeypatch
    ):
        monkeypatch.setattr(gp, "_month", lambda: "2026-10")
        c = _ctrl(tmp_path, monthly_budget=100)
        c.record_spend(50)
        c._lam = 0.4
        c._i_term = 0.4

        monkeypatch.setattr(gp, "_month", lambda: "2026-11")
        c._rollover_locked()
        assert c._spent == 0.0
        assert c._i_term == 0.0
        assert c._lam == pytest.approx(0.4 * 0.5)   # 指数回退而非清零

    def test_same_month_is_noop(self, tmp_path, monkeypatch):
        monkeypatch.setattr(gp, "_month", lambda: "2026-10")
        c = _ctrl(tmp_path, monthly_budget=100)
        c.record_spend(50)
        c._rollover_locked()
        assert c._spent == pytest.approx(50.0)


# ────────────────────────────── 并发 ──────────────────────────────

class TestConcurrency:
    def test_parallel_record_spend_not_lost(self, tmp_path):
        """RLock 守护：4 线程 × 25 次 = 100，丢一次就说明锁失效。"""
        c = _ctrl(tmp_path, monthly_budget=100000)

        def work():
            for _ in range(25):
                c.record_spend(1.0)

        threads = [threading.Thread(target=work) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert c.status()["spent"] == pytest.approx(100.0)
