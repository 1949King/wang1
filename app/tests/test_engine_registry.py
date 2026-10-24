# -*- coding: utf-8 -*-
"""引擎注册表：族/角色/健康/用量口径测试（不 import 重依赖）。"""
from __future__ import annotations

from app.core import engine_registry as reg


def test_families_and_unique_ids() -> None:
    assert len(reg.FAMILIES) == 9
    ids = [e.id for e in reg.ENGINES]
    assert len(ids) == len(set(ids))
    assert len(reg.ENGINES) >= 50


def test_roles_valid_and_modules_exist() -> None:
    for e in reg.ENGINES:
        assert e.role in reg.ROLES, e.id
        assert reg._module_exists(e.module), e.id + " → " + e.module


def test_health_rules() -> None:
    yue = next(e for e in reg.ENGINES if e.id == "music.yue")
    assert reg.health(yue)[0] == "disabled"
    svd = next(e for e in reg.ENGINES if e.id == "video.svd")
    h, missing = reg.health(svd)
    assert h in ("ready", "degraded")
    if h == "degraded":
        assert "torch" in missing or "diffusers" in missing


def test_status_shape() -> None:
    s = reg.status()
    assert s["total"] == len(reg.ENGINES)
    assert sum(s["by_role"].values()) == s["total"]
    assert sum(s["by_family"].values()) == s["total"]
    for v in s["engines"]:
        assert v["health"] in ("ready", "degraded", "disabled", "missing")
        assert v["usage"] is None or set(v["usage"]) == {"calls", "ok", "last_ts"}


def test_usage_aggregation_and_idle(monkeypatch) -> None:
    fake = {
        "diffusers|sd15|cuda0": {"n": 3, "ok": 2, "last_ts": 10.0},
        "diffsynth|sd15|cuda0": {"n": 1, "ok": 1, "last_ts": 20.0},
        # 已埋点但 0 调用：只有这种才应进「空着清单」
        "svd|svd-xt|cuda0": {"n": 0, "ok": 0, "last_ts": 0.0},
    }
    monkeypatch.setattr(reg, "_telemetry_records", lambda: fake)
    agg = reg._usage_by_engine(fake)
    assert agg["diffusers"]["calls"] == 3
    assert agg["diffusers"]["ok"] == 2
    assert agg["diffsynth"]["last_ts"] == 20.0
    idle = reg.idle_engines()
    assert idle and all(int(i["usage"]["calls"]) == 0 for i in idle)
    # 未埋点引擎不得被判成「0 调用」
    assert all(i["telemetry"] for i in idle)
