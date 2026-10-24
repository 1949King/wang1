"""app/tests/test_zcov_ledger_budget.py — L1 日预算 PI 影子价格控制器补测（2026-10-09）。

被测：app/core/ai/budget_pacer.py（《异构动态协作引擎规格书》第六篇 C 模块最小落地）

为什么要单独补（背景）：
  该模块此前只有**间接覆盖**（被 execution_decider / engine_api /
  video_generation_client 的测试顺带调用）。2026-10-09 root conftest 增加
  `isolate_ledger_state` fixture（把账本状态指向 tmp_path 并清空进程级单例）
  之后，间接覆盖消失，真实测试缺口暴露。它又是「三层价格体系」的 L1 任务层，
  坏一次就是全链路路由偏好跑偏，必须显式锁住。

纪律（对齐 test_zcov_core_a.py）：
  · **一律显式构造** `BudgetPacer(budget=..., store_path=tmp_path/...)`，
    绝不碰 `get_pacer()` 进程级单例 —— 单例跨测试污染正是本次事故的根源。
  · 每个用例断言**可观察行为**（返回值 / 持久化往返 / 状态字段），
    对内部状态（`_lam` / `_e_prev`）的断言仅用于锁死文档化的控制律契约。
  · 不写 `assert True` 之类凑数用例。
"""
from __future__ import annotations

import json
import re
import time

import pytest

from app.core.ai import budget_pacer as bp
from app.core.ai.budget_pacer import (
    BudgetPacer,
    _DEFAULT_BUDGET,
    _LAMBDA_INIT,
    _LAMBDA_MAX,
    _LAMBDA_MIN,
    _KI,
    _KP,
)

pytestmark = pytest.mark.unit


def _pacer(tmp_path, budget=50.0, kp=_KP, ki=_KI, interval=30.0):
    """显式构造（不使用单例）；状态文件落在 tmp_path。"""
    return BudgetPacer(
        budget=budget,
        store_path=str(tmp_path / "budget_pacer.json"),
        kp=kp, ki=ki, update_interval=interval,
    )


# ═══════════════════════════════════════════════════════════════
#  构造与默认状态
# ═══════════════════════════════════════════════════════════════


class TestConstruction:
    def test_defaults_before_any_io(self, tmp_path):
        p = _pacer(tmp_path)
        assert p._budget == 50.0
        assert p._lam == _LAMBDA_INIT == 0.2
        assert p._spent == 0.0
        assert p._pi_ready is False        # 未加载 ⇒ 首拍只建基线
        assert p._obs_valid is True

    def test_budget_is_floored_at_one_yuan(self, tmp_path):
        """负预算 / 0 预算必须被夹到 1.0 —— 否则 spend_ratio 会除零。"""
        assert _pacer(tmp_path, budget=0.0)._budget == 1.0
        assert _pacer(tmp_path, budget=-100.0)._budget == 1.0
        assert _pacer(tmp_path, budget=0.4)._budget == 1.0

    def test_update_interval_is_floored_at_one_second(self, tmp_path):
        """update_interval<=0 会让「周期锁死」退化成每读必算，夹到 1.0。"""
        assert _pacer(tmp_path, interval=0.0)._interval == 1.0
        assert _pacer(tmp_path, interval=-5.0)._interval == 1.0

    def test_explicit_store_path_wins_over_env(self, tmp_path, monkeypatch):
        monkeypatch.setenv("BUDGET_PACER_STORE_PATH", str(tmp_path / "from_env.json"))
        p = _pacer(tmp_path)
        assert p._path == str(tmp_path / "budget_pacer.json")


# ═══════════════════════════════════════════════════════════════
#  模块级辅助函数
# ═══════════════════════════════════════════════════════════════


class TestModuleHelpers:
    def test_resolve_store_path_prefers_env(self, monkeypatch):
        monkeypatch.setenv("BUDGET_PACER_STORE_PATH", "  /tmp/custom.json  ")
        assert bp._resolve_store_path() == "/tmp/custom.json"   # 带 strip

    def test_resolve_store_path_blank_env_falls_back_to_default(self, monkeypatch):
        """空串 / 纯空白 的环境变量不能把账本路径变成空 —— 必须回退默认。"""
        monkeypatch.setenv("BUDGET_PACER_STORE_PATH", "   ")
        got = bp._resolve_store_path()
        assert got == bp._DEFAULT_STORE and got.endswith("budget_pacer.json")

    def test_today_is_iso_date(self):
        assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", bp._today())

    def test_day_progress_within_unit_interval(self):
        v = bp._day_progress()
        assert 0.0 <= v < 1.0


# ═══════════════════════════════════════════════════════════════
#  记账 record_spend
# ═══════════════════════════════════════════════════════════════


class TestRecordSpend:
    def test_positive_amount_accumulates(self, tmp_path):
        p = _pacer(tmp_path)
        p.record_spend(3.5)
        p.record_spend(6.5)
        assert p.status()["spent"] == 10.0

    @pytest.mark.parametrize("bad", [0.0, -1.0, -999.0])
    def test_zero_and_negative_are_ignored(self, tmp_path, bad):
        """花费恒 >=0：非正数不能入账（负数入账会凭空造预算）。"""
        p = _pacer(tmp_path)
        p.record_spend(bad)
        assert p.status()["spent"] == 0.0

    @pytest.mark.parametrize("bad", ["not-a-number", None, [], {}])
    def test_non_numeric_is_swallowed_not_raised(self, tmp_path, bad):
        """贪心容错契约：控制器绝不能因脏输入把生成主链路带崩。"""
        p = _pacer(tmp_path)
        p.record_spend(bad)              # 不抛
        assert p.status()["spent"] == 0.0

    def test_numeric_string_is_coerced(self, tmp_path):
        """记录既有行为：`float("12.5")` 成功 ⇒ 数字串会被真的记进去。"""
        p = _pacer(tmp_path)
        p.record_spend("12.5")
        assert p.status()["spent"] == 12.5


# ═══════════════════════════════════════════════════════════════
#  持久化往返
# ═══════════════════════════════════════════════════════════════


class TestPersistence:
    def test_save_creates_file_with_expected_keys(self, tmp_path):
        p = _pacer(tmp_path)
        p.record_spend(8.0)
        path = tmp_path / "budget_pacer.json"
        assert path.exists()
        d = json.loads(path.read_text(encoding="utf-8"))
        assert set(d) >= {"date", "budget", "spent", "lambda", "e_prev"}
        assert d["spent"] == 8.0

    def test_roundtrip_spent_and_lambda_survive_reconstruction(self, tmp_path):
        """核心回归锁：保存后**新建实例**必须读回同一 spent / λ。"""
        p1 = _pacer(tmp_path)
        p1.record_spend(12.5)
        p1._lam = 0.7071
        p1._save_locked()

        p2 = _pacer(tmp_path)            # 全新对象，只有磁盘状态可继承
        st = p2.status()
        assert st["spent"] == 12.5
        assert st["lambda"] == 0.7071
        assert p2._pi_ready is True      # 有持久化状态 = 控制器已在跑，跳过建基线

    def test_missing_file_starts_from_defaults_without_error(self, tmp_path):
        p = _pacer(tmp_path)             # 文件不存在
        st = p.status()
        assert st["spent"] == 0.0 and st["lambda"] == _LAMBDA_INIT

    def test_corrupted_json_falls_back_to_defaults(self, tmp_path):
        """半截 JSON（断电/磁盘满）不能让状态加载抛异常。"""
        path = tmp_path / "budget_pacer.json"
        path.write_text("{ this is not json", encoding="utf-8")
        p = _pacer(tmp_path)
        st = p.status()
        assert st["spent"] == 0.0 and st["lambda"] == _LAMBDA_INIT

    def test_non_dict_payload_is_ignored(self, tmp_path):
        """顶层是 list/标量时的容错：isinstance(d, dict) 守卫。"""
        path = tmp_path / "budget_pacer.json"
        path.write_text("[1, 2, 3]", encoding="utf-8")
        p = _pacer(tmp_path)
        assert p.status()["spent"] == 0.0

    def test_save_failure_does_not_raise_and_keeps_memory_state(self, tmp_path, monkeypatch):
        """持久化失败必须被吞掉（优化项挂了不能用静态 λ 兜底前的崩）。"""
        p = _pacer(tmp_path)

        def _boom(*a, **k):
            raise OSError("disk full")

        monkeypatch.setattr(bp.tempfile, "mkstemp", _boom)
        p.record_spend(5.0)              # 不抛
        assert p.status()["spent"] == 5.0   # 内存态照常推进
        assert not (tmp_path / "budget_pacer.json").exists()

    def test_budget_persisted_but_not_reloaded(self, tmp_path):
        """记录一个**不对称**：`_save_locked` 写了 budget，`_ensure_loaded` 却不读。

        现状 = `set_budget` 的改动**不进重启**（新实例用构造参数里的预算）。
        本用例把现状锁成显式契约，避免它被静默改变；若这是缺陷，
        请在 budget_pacer.py 的 `_ensure_loaded` 补 `self._budget = float(d["budget"])`。
        """
        p1 = _pacer(tmp_path, budget=50.0)
        p1.set_budget(100.0)
        assert p1._budget == 100.0
        d = json.loads((tmp_path / "budget_pacer.json").read_text(encoding="utf-8"))
        assert d["budget"] == 100.0      # 确实写盘了

        p2 = _pacer(tmp_path, budget=50.0)   # 构造预算 50
        assert p2.status()["budget"] == 50.0  # 磁盘上的 100 被忽略


# ═══════════════════════════════════════════════════════════════
#  跨日结转 _rollover_locked（λ 指数回退）
# ═══════════════════════════════════════════════════════════════


class TestRollover:
    def test_rollover_resets_spend_and_relaxes_lambda(self, tmp_path, monkeypatch):
        """跨日：花费归档归零，λ 指数回退（不清零，杜绝阶跃抖动）。"""
        p = _pacer(tmp_path)
        p._spent = 30.0
        p._e_prev = 0.42
        p._lam = 0.6
        monkeypatch.setattr(bp, "_today", lambda: "2099-01-01")

        p._rollover_locked()

        assert p._spent == 0.0
        assert p._e_prev == 0.0
        # λ ← init + (λ − init) × 0.5 = 0.2 + (0.6−0.2)×0.5 = 0.4
        assert p._lam == pytest.approx(0.4)

    def test_same_day_rollover_is_noop(self, tmp_path):
        p = _pacer(tmp_path)
        p._spent = 7.0
        p._lam = 0.9
        p._rollover_locked()             # _date 仍 == _today()
        assert p._spent == 7.0 and p._lam == 0.9

    def test_rollover_on_load_from_stale_file(self, tmp_path, monkeypatch):
        """磁盘里是旧日期的状态 ⇒ 加载时立即结转，λ 回退、花费清零。"""
        path = tmp_path / "budget_pacer.json"
        path.write_text(json.dumps({
            "date": "2000-01-01", "budget": 50.0,
            "spent": 99.0, "lambda": 0.9, "e_prev": 0.5,
        }), encoding="utf-8")
        monkeypatch.setattr(bp, "_today", lambda: "2099-01-01")

        p = _pacer(tmp_path)
        st = p.status()
        assert st["spent"] == 0.0
        assert st["lambda"] == pytest.approx(0.2 + (0.9 - 0.2) * 0.5)   # 0.55
        assert p._e_prev == 0.0
        assert st["date"] == "2099-01-01"


# ═══════════════════════════════════════════════════════════════
#  误差信号与 PI 迭代
# ═══════════════════════════════════════════════════════════════


class TestErrorSignal:
    def test_overspend_gives_negative_error(self, tmp_path, monkeypatch):
        """e = 剩余预算比 − 剩余时间比；花了 40/50 且日初 ⇒ e = 0.2 − 1.0 < 0。"""
        p = _pacer(tmp_path)
        p._spent = 40.0
        monkeypatch.setattr(bp, "_day_progress", lambda: 0.0)
        assert p._error_locked() == pytest.approx(0.2 - 1.0)

    def test_surplus_gives_positive_error(self, tmp_path, monkeypatch):
        """没花钱且临近日末 ⇒ 预算富余 ⇒ e > 0。"""
        p = _pacer(tmp_path)
        monkeypatch.setattr(bp, "_day_progress", lambda: 0.9)
        assert p._error_locked() == pytest.approx(1.0 - 0.1)

    def test_time_left_ratio_is_floored_at_002(self, tmp_path, monkeypatch):
        """日末防除零失真：剩余时间比下限 0.02，不让它跌到 0。"""
        p = _pacer(tmp_path)
        monkeypatch.setattr(bp, "_day_progress", lambda: 0.999)
        # 剩余时间 = 1 − 0.999 = 0.001 → 被夹到 0.02；预算剩 1.0
        assert p._error_locked() == pytest.approx(1.0 - 0.02)


class TestPiIteration:
    def test_first_update_only_builds_baseline(self, tmp_path, monkeypatch):
        """首拍只建 e 基线、不动作 —— 防启动时的比例踢（规格 §35）。"""
        p = _pacer(tmp_path)
        p._spent = 40.0                       # 有明确误差在此
        monkeypatch.setattr(bp, "_day_progress", lambda: 0.0)

        p._update_locked(force=True)

        assert p._pi_ready is True
        assert p._lam == _LAMBDA_INIT         # λ 未动
        assert p._e_prev == pytest.approx(-0.8)

    def test_overspend_raises_lambda(self, tmp_path, monkeypatch):
        """超支 ⇒ e<0 ⇒ λ 上调（公式逐项手算核对）。"""
        p = _pacer(tmp_path, kp=0.5, ki=0.1)
        monkeypatch.setattr(bp, "_day_progress", lambda: 0.0)
        p._spent = 40.0
        p._pi_ready = True
        p._e_prev = 0.0
        p._lam = 0.2

        p._update_locked(force=True)

        # e = -0.8；delta = 0.5·(0 − (−0.8)) + 0.1·(0.8) = 0.48 ⇒ λ = 0.68
        assert p._error_locked() == pytest.approx(-0.8)
        assert p._lam == pytest.approx(0.68)

    def test_surplus_lowers_lambda(self, tmp_path, monkeypatch):
        """预算富余 ⇒ e>0 ⇒ λ 下调（偏质量渠道）。"""
        p = _pacer(tmp_path, kp=0.5, ki=0.1)
        monkeypatch.setattr(bp, "_day_progress", lambda: 0.9)
        p._spent = 0.0
        p._pi_ready = True
        p._e_prev = 0.0
        p._lam = 0.95

        p._update_locked(force=True)

        # e = 0.9；delta = 0.5·(0 − 0.9) + 0.1·(−0.9) = −0.54 ⇒ λ = 0.41
        assert p._lam == pytest.approx(0.41)

    def test_interval_gate_blocks_rapid_iteration(self, tmp_path, monkeypatch):
        """周期锁死：距上次更新不足 T_update 时读 λ 不迭代。"""
        p = _pacer(tmp_path, interval=30.0)
        monkeypatch.setattr(bp, "_day_progress", lambda: 0.0)
        p._spent = 40.0

        p.get_lambda()                        # 首拍：迭代（建基线）并写 _last_update
        t_after = p._last_update
        assert t_after > 0.0

        p.get_lambda()                        # 紧接一次：被间隔门控挡下
        assert p._last_update == t_after
        assert p._lam == _LAMBDA_INIT

    def test_first_get_lambda_does_not_move_despite_error(self, tmp_path, monkeypatch):
        """即便此刻误差很大，首次读取也只建基线、λ 保持初值。"""
        p = _pacer(tmp_path)
        monkeypatch.setattr(bp, "_day_progress", lambda: 0.0)
        p._spent = 45.0
        assert p.get_lambda() == _LAMBDA_INIT


# ═══════════════════════════════════════════════════════════════
#  λ 上下界夹取 + 抗卷绕
# ═══════════════════════════════════════════════════════════════


class TestLambdaClamping:
    def test_lambda_is_clamped_at_max(self, tmp_path, monkeypatch):
        """极强超支不应让 λ 越过上界。"""
        p = _pacer(tmp_path, kp=0.0, ki=100.0)
        monkeypatch.setattr(bp, "_day_progress", lambda: 0.0)
        p._spent = 50.0                        # e = −1.0
        p._pi_ready = True
        p._e_prev = 0.0
        p._lam = 0.2

        p._update_locked(force=True)

        assert p._lam == _LAMBDA_MAX
        # 撞上界 ⇒ 积分冻结：e_prev 不推进（抗卷绕，规格 §34）
        assert p._e_prev == 0.0

    def test_lambda_is_clamped_at_min(self, tmp_path, monkeypatch):
        """极强富余不应让 λ 跌破下界。"""
        p = _pacer(tmp_path, kp=0.0, ki=100.0)
        monkeypatch.setattr(bp, "_day_progress", lambda: 0.99)
        p._spent = 0.0                         # e ≈ +0.98
        p._pi_ready = True
        p._e_prev = 0.0
        p._lam = 0.2

        p._update_locked(force=True)

        assert p._lam == _LAMBDA_MIN
        assert p._e_prev == 0.0                # 撞下界同样冻结积分

    def test_repeated_overspend_never_winds_up_beyond_max(self, tmp_path, monkeypatch):
        """持续超支多拍之后，λ 始终被夹在上界内，不会「积压后反向爆冲」。"""
        p = _pacer(tmp_path, kp=0.5, ki=0.1)
        monkeypatch.setattr(bp, "_day_progress", lambda: 0.0)
        p._spent = 50.0
        p._pi_ready = True
        p._e_prev = 0.0
        for _ in range(50):
            p._update_locked(force=True)
        assert _LAMBDA_MIN <= p._lam <= _LAMBDA_MAX
        assert p._lam == _LAMBDA_MAX

    def test_non_clamped_update_advances_baseline(self, tmp_path, monkeypatch):
        """未撞界的正常一拍会刷新 e_prev（与撞界冻结形成对照）。"""
        p = _pacer(tmp_path, kp=0.5, ki=0.1)
        monkeypatch.setattr(bp, "_day_progress", lambda: 0.0)
        p._spent = 40.0                        # e = −0.8，增量 0.48 ⇒ 不撞界
        p._pi_ready = True
        p._e_prev = 0.0
        p._lam = 0.2

        p._update_locked(force=True)

        assert p._e_prev == pytest.approx(-0.8)


# ═══════════════════════════════════════════════════════════════
#  观测门控 set_observation（规格 §35）
# ═══════════════════════════════════════════════════════════════


class TestObservationGate:
    def test_invalid_observation_freezes_lambda(self, tmp_path, monkeypatch):
        """观测无效（断网/暂停）⇒ λ 冻结，update 不推进控制器。"""
        p = _pacer(tmp_path, kp=0.5, ki=0.1)
        monkeypatch.setattr(bp, "_day_progress", lambda: 0.0)
        p._spent = 40.0
        p._pi_ready = True
        p._e_prev = 0.0
        p._lam = 0.2

        p.set_observation(False, reason="断网")
        p._update_locked(force=True)

        assert p._obs_valid is False
        assert p._lam == 0.2                   # 冻结：λ 未变
        assert p._e_prev == 0.0                # 基线也未推进

    def test_recovery_first_tick_only_rebuilds_baseline(self, tmp_path, monkeypatch):
        """恢复后首拍只重采 e_prev、不动作 —— 冻结期误差跳变不进控制器。"""
        p = _pacer(tmp_path, kp=0.5, ki=0.1)
        monkeypatch.setattr(bp, "_day_progress", lambda: 0.0)
        p._spent = 40.0
        p._pi_ready = True
        p._e_prev = 0.0
        p._lam = 0.2

        p.set_observation(False)
        p.set_observation(True)                # 恢复 ⇒ _pi_ready 被置 False
        assert p._pi_ready is False

        p._update_locked(force=True)           # 首拍：只建基线
        assert p._lam == 0.2
        assert p._e_prev == pytest.approx(-0.8)

        p._update_locked(force=True)           # 第二拍：λ 开始动作
        # e 与基线相同 ⇒ 比例项为 0，仅积分项生效：λ = 0.2 + 0.1×0.8 = 0.28
        # （这正是「恢复首拍先建基线」的价值：比例踢被吃掉，只留平滑的积分修正）
        assert p._lam == pytest.approx(0.28)

    def test_redundant_valid_signal_does_not_reset_baseline(self, tmp_path):
        """连续两次 valid 不应把 _pi_ready 拉回 False（否则永远不动作）。"""
        p = _pacer(tmp_path)
        p._pi_ready = True
        p.set_observation(True)                # was=True & valid=True ⇒ 不重置
        assert p._pi_ready is True

    def test_redundant_invalid_signal_is_idempotent(self, tmp_path):
        p = _pacer(tmp_path)
        p.set_observation(False)
        p.set_observation(False)               # was=False ⇒ 只保留状态
        assert p._obs_valid is False


# ═══════════════════════════════════════════════════════════════
#  status() 字段
# ═══════════════════════════════════════════════════════════════


class TestStatus:
    def test_all_fields_present(self, tmp_path):
        st = _pacer(tmp_path).status()
        assert set(st) >= {
            "date", "budget", "spent", "remaining", "spend_ratio",
            "time_ratio", "error", "over_pacing", "lambda",
            "lambda_bounds", "note",
        }
        assert st["lambda_bounds"] == [_LAMBDA_MIN, _LAMBDA_MAX]

    def test_over_pacing_flag_true_when_budget_ahead_of_time(self, tmp_path, monkeypatch):
        p = _pacer(tmp_path)
        p._spent = 40.0
        monkeypatch.setattr(bp, "_day_progress", lambda: 0.0)
        st = p.status()
        assert st["over_pacing"] is True and st["error"] < 0

    def test_over_pacing_flag_false_when_surplus(self, tmp_path, monkeypatch):
        p = _pacer(tmp_path)
        monkeypatch.setattr(bp, "_day_progress", lambda: 0.9)
        st = p.status()
        assert st["over_pacing"] is False and st["error"] > 0

    def test_remaining_never_negative_when_overspent(self, tmp_path):
        p = _pacer(tmp_path, budget=50.0)
        p._spent = 80.0
        p._save_locked()
        st = p.status()
        assert st["remaining"] == 0.0
        assert st["spend_ratio"] == pytest.approx(1.6)

    def test_spend_ratio_reflects_accounted_spend(self, tmp_path):
        p = _pacer(tmp_path, budget=50.0)
        p.record_spend(25.0)
        assert p.status()["spend_ratio"] == pytest.approx(0.5)


# ═══════════════════════════════════════════════════════════════
#  set_budget
# ═══════════════════════════════════════════════════════════════


class TestSetBudget:
    def test_updates_budget_immediately(self, tmp_path):
        p = _pacer(tmp_path, budget=50.0)
        p.set_budget(120.0)
        assert p.status()["budget"] == 120.0

    def test_zero_or_negative_is_floored(self, tmp_path):
        p = _pacer(tmp_path, budget=50.0)
        p.set_budget(0.0)
        assert p.status()["budget"] == 1.0
        p.set_budget(-7.0)
        assert p.status()["budget"] == 1.0

    def test_non_numeric_is_swallowed_and_keeps_old_budget(self, tmp_path):
        p = _pacer(tmp_path, budget=50.0)
        p.set_budget("oops")                   # 不抛
        assert p.status()["budget"] == 50.0

    def test_set_budget_does_not_touch_spent_or_lambda(self, tmp_path):
        p = _pacer(tmp_path, budget=50.0)
        p.record_spend(10.0)
        p._lam = 0.66
        p.set_budget(200.0)
        st = p.status()
        assert st["spent"] == 10.0 and st["lambda"] == pytest.approx(0.66)


# ═══════════════════════════════════════════════════════════════
#  异常兜底路径（控制器绝不拖垮主链路）
# ═══════════════════════════════════════════════════════════════


class TestExceptionFallbacks:
    def _breaker(self, p):
        def _boom():
            raise RuntimeError("simulated load failure")
        p._ensure_loaded = _boom         # 覆写实例方法，触发 except 分支

    def test_get_lambda_returns_init_on_internal_error(self, tmp_path):
        p = _pacer(tmp_path)
        self._breaker(p)
        assert p.get_lambda() == _LAMBDA_INIT

    def test_status_returns_fallback_dict_on_internal_error(self, tmp_path):
        p = _pacer(tmp_path)
        self._breaker(p)
        st = p.status()
        assert st["lambda"] == _LAMBDA_INIT and "note" in st

    def test_set_budget_swallows_internal_error(self, tmp_path):
        p = _pacer(tmp_path, budget=50.0)
        self._breaker(p)
        p.set_budget(300.0)               # 不抛
        assert p._budget == 50.0          # 未生效但不 crash


# ═══════════════════════════════════════════════════════════════
#  测试辅助方法
# ═══════════════════════════════════════════════════════════════


class TestResetForTests:
    def test_reset_restores_initial_state_and_marks_loaded(self, tmp_path):
        p = _pacer(tmp_path)
        p._spent = 33.0
        p._lam = 0.88
        p._e_prev = 0.5
        p._pi_ready = False

        p._reset_for_tests()

        assert p._spent == 0.0
        assert p._lam == _LAMBDA_INIT
        assert p._e_prev == 0.0
        assert p._loaded is True


# ═══════════════════════════════════════════════════════════════
#  并发（线程安全，RLock）
# ═══════════════════════════════════════════════════════════════


class TestConcurrency:
    def test_concurrent_record_spend_does_not_lose_money(self, tmp_path):
        """8 线程 × 50 笔 × 1.0 元 = 400 元。丢一笔就说明锁没起作用。"""
        import threading

        p = _pacer(tmp_path, budget=1000.0)
        threads = [
            threading.Thread(target=lambda: [p.record_spend(1.0) for _ in range(50)])
            for _ in range(8)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert p.status()["spent"] == pytest.approx(400.0)
