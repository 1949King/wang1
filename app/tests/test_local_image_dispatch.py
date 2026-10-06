"""app/tests/test_local_image_dispatch.py — 刀 A1 本地图像引擎「通电」回归（2026-10-04）。

锁定刀 A1 的五个交付：
  ① `/host/local-image-generate` 三态路由已注册进路由表（@_route_post）；
  ② `execution_decider.resolve_local_image_engine` 是主备裁定的**真执行**入口 ——
     显式指定 / 开关解析 / 首选不可用再降一级，理由全部留痕（R9）；
  ③ 能力目录 `canvas.local_generate_image` 一行 + handler 注册（唯一入口纪律）；
  ④ SDXL `original_config_url` 第二来源登记（换机 provisioning 可复现）；
  ⑤ bench 脚本入库 `_verify/bench/`（M1~M5 验收门可复测，不再漂在 tmp）。

注：本测试不真 import torch/diffusers/diffsynth_engine，不下载权重，不起 HTTP。
"""
import inspect
import pathlib

from app.core.ai import execution_decider as ED
from app.core.neural import diffusers_image as D

ROOT = pathlib.Path(__file__).resolve().parents[2]


# ─────────────────────── ① 路由注册 ───────────────────────

def test_local_image_route_registered():
    src = (ROOT / "app" / "core" / "canvas_routes_post.py").read_text(encoding="utf-8")
    assert '@_route_post("/host/local-image-generate")' in src
    # 三态齐备
    assert '"models"' in src and '"pull"' in src
    # 与云端路径刻意不同名（local- 前缀语义分界，同 local-video 约定）
    assert "local-image-generate" in src


def test_route_dispatches_via_decider():
    """路由必须经 resolve_local_image_engine 分派（决策不空转），且 R9 降级字段透出。"""
    src = (ROOT / "app" / "core" / "canvas_routes_post.py").read_text(encoding="utf-8")
    assert "resolve_local_image_engine" in src
    assert "engine_is_fallback" in src


# ─────────────────────── ② 真分派 ───────────────────────

def test_resolve_local_image_engine_explicit_builtin():
    sel = ED.resolve_local_image_engine(prefer="builtin")
    assert sel["ok"], sel.get("reasons")
    assert sel["engine"] == "builtin"
    assert sel["is_fallback"] is True
    assert sel["backend"] is not None
    assert any("显式指定" in r for r in sel["reasons"])


def test_resolve_local_image_engine_explicit_diffsynth():
    sel = ED.resolve_local_image_engine(prefer="diffsynth")
    # 本机 diffsynth_engine 已装（V4.40.25）⇒ 应可选中；即便未来环境变化，
    # 也必须**再降一级**到 builtin 而不是裸失败（双栈均不可用才 ok=False）。
    assert sel["ok"], sel.get("reasons")
    assert sel["engine"] in ("diffsynth", "builtin")
    if sel["engine"] == "builtin":
        assert any("降级" in r for r in sel["reasons"])


def test_resolve_local_image_engine_unknown_prefer_ignored():
    """未知 engine 字符串必须忽略并按开关解析，绝不抛异常。"""
    sel = ED.resolve_local_image_engine(prefer="nonsense-engine")
    assert sel["ok"] or sel["message"]
    assert any("未知 engine" in r for r in sel["reasons"])


def test_resolve_local_image_engine_default_switch():
    sel = ED.resolve_local_image_engine()
    assert sel["ok"], sel.get("reasons")
    assert sel["engine"] in ("diffsynth", "builtin")
    assert sel["reasons"], "选路理由必须非空（可解释）"


def test_resolve_local_image_engine_exported():
    assert "resolve_local_image_engine" in ED.__all__


# ─────────────────────── ③ 能力目录 + handler ───────────────────────

def test_catalog_has_local_generate_image():
    from app.core.agent_capability_catalog import CAPABILITY_ROWS
    ids = [r[0] for r in CAPABILITY_ROWS]
    assert "canvas.local_generate_image" in ids
    row = next(r for r in CAPABILITY_ROWS if r[0] == "canvas.local_generate_image")
    assert row[1] == "canvas" and row[2] == "media_write"
    assert row[3] is False, "本地引擎零调用费，paid 必须为 False"


def test_handler_registered_and_implemented():
    from app.core.capability_handlers import CanvasCapabilityHandlers
    h = CanvasCapabilityHandlers()
    assert hasattr(h, "local_generate_image")
    sig = inspect.signature(h.local_generate_image)
    assert len(sig.parameters) == 1  # req


def test_handler_honest_fail_without_torch(monkeypatch):
    """引擎双栈不可用时诚实失败（ok=False + reasons），绝不返回占位图。"""
    monkeypatch.setattr(ED, "resolve_local_image_engine",
                        lambda prefer="": {"ok": False, "engine": "", "is_fallback": True,
                                           "reasons": ["模拟双栈不可用"], "backend": None,
                                           "message": "本地图像引擎双栈均不可用（详见 reasons）"})
    from app.core.capability_handlers import CanvasCapabilityHandlers
    from app.core.capability_dispatcher import CapabilityRequest
    req = CapabilityRequest(request_id="t1", capability_id="canvas.local_generate_image",
                            params={"prompt": "x"})
    res = CanvasCapabilityHandlers().local_generate_image(req)
    assert res.success is False
    assert "不可用" in (res.error or "")


# ─────────────────────── ④ SDXL 第二来源 ───────────────────────

def test_sdxl_registers_original_config_url():
    spec = D.DIFFUSERS_IMAGE_MODELS["sdxl-t2i"]
    url = spec.get("original_config_url", "")
    assert url.startswith("https://"), "SDXL yaml 第二来源未登记（换机不可复现）"
    assert url.endswith("sd_xl_base.yaml")


def test_sd15_does_not_need_second_source():
    """sd15 的 v1-inference.yaml 在 ModelScope 仓库内 ⇒ 不需要也不该配第二来源。"""
    spec = D.DIFFUSERS_IMAGE_MODELS["sd15-t2i"]
    assert not spec.get("original_config_url")


def test_pull_consumes_second_source():
    src = inspect.getsource(D.DiffusersImageEngine.pull)
    assert "original_config_url" in src
    assert "urlopen" in src


# ─────────────────────── ⑤ bench 入库 ───────────────────────

def test_bench_scripts_in_repo():
    bench = ROOT / "_verify" / "bench"
    assert (bench / "bench_sdxl_modes.py").is_file()
    assert (bench / "compare_dual_stack_sd15.py").is_file()
    # 入库后可复测性：两脚本仍按项目根解析 sys.path（dirname/../..）
    for name in ("bench_sdxl_modes.py", "compare_dual_stack_sd15.py"):
        text = (bench / name).read_text(encoding="utf-8")
        assert "已入库" in text
