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


# ─────────────────────── ⑥ P0b（2026-10-10）：本地生图入闭环 ───────────────────────
# 深潜复核发现：本地生图 seed 缺省 0、不归一化、不回显、不调 feed_draw_ledger
# —— 零成本抽卡主力是账本盲区。本组锁定修复后的行为。

def _fake_backend_ok(tmp_path, png_bytes=b"\x89PNG\r\n\x1a\nfake"):
    """构造一个假引擎：生成成功、产物落盘、返回与真引擎同构的 dict。"""

    class _B:
        def generate(self, model_id, *, prompt="", negative_prompt="", image_path="",
                     width=0, height=0, seed=0, steps=0, cfg=0.0, out_path=""):
            p = tmp_path / "img.png"
            p.write_bytes(png_bytes)
            return {"ok": True, "path": str(p), "image_path": str(p),
                    "image_url": "inbox://img.png", "width": width or 512,
                    "height": height or 512, "seconds_elapsed": 0.1,
                    "message": "生成完成"}

    return _B()


def test_local_generate_seed_normalized_and_echoed(monkeypatch, tmp_path):
    """seed 缺省 → 密码学随机且 >0；显式 42 → 透传；两者都回显且 seed_sent=True。"""
    calls = {}

    def _fake_backend():
        b = _fake_backend_ok(tmp_path)
        orig_gen = b.generate

        def gen(model_id, **kw):
            calls.update(kw)
            return orig_gen(model_id, **kw)

        b.generate = gen
        return b

    monkeypatch.setattr(ED, "resolve_local_image_engine",
                        lambda prefer="": {"ok": True, "engine": "builtin",
                                           "is_fallback": True, "reasons": ["测试"],
                                           "backend": _fake_backend()})
    from app.core.capability_handlers import CanvasCapabilityHandlers
    from app.core.capability_dispatcher import CapabilityRequest

    # 缺省 seed
    res = CanvasCapabilityHandlers().local_generate_image(
        CapabilityRequest(request_id="t1", capability_id="canvas.local_generate_image",
                          params={"prompt": "x"}))
    assert res.success
    out = res.output
    assert out["seed"] > 0 and out["seed_sent"] is True
    assert calls["seed"] == out["seed"], "引擎收到的 seed 必须与回显一致（可复现）"

    # 显式 seed=42
    res2 = CanvasCapabilityHandlers().local_generate_image(
        CapabilityRequest(request_id="t2", capability_id="canvas.local_generate_image",
                          params={"prompt": "x", "seed": 42}))
    assert res2.output["seed"] == 42
    assert calls["seed"] == 42


def test_local_generate_feeds_ledger_on_success(monkeypatch, tmp_path):
    """生成成功必须进闭环接线（feed_draw_ledger_local），失败/未生成则不进。"""
    fed = []

    import app.core.ai.draw_ledger as DL

    def _fake_feed_local(result, *, prompt, model_id, engine, seed, elapsed_ms=None):
        fed.append({"prompt": prompt, "model_id": model_id, "engine": engine,
                    "seed": seed, "path": result.get("image_path")})

    monkeypatch.setattr(DL, "feed_draw_ledger_local", _fake_feed_local)
    # capability_handlers 在函数内 import，patch 的是 draw_ledger 模块属性 ⇒ 生效
    monkeypatch.setattr(ED, "resolve_local_image_engine",
                        lambda prefer="": {"ok": True, "engine": "builtin",
                                           "is_fallback": True, "reasons": ["测试"],
                                           "backend": _fake_backend_ok(tmp_path)})
    from app.core.capability_handlers import CanvasCapabilityHandlers
    from app.core.capability_dispatcher import CapabilityRequest

    res = CanvasCapabilityHandlers().local_generate_image(
        CapabilityRequest(request_id="t3", capability_id="canvas.local_generate_image",
                          params={"prompt": "入账测试", "model_id": "sd15-t2i"}))
    assert res.success
    assert len(fed) == 1
    assert fed[0]["model_id"] == "sd15-t2i"
    assert fed[0]["engine"] == "builtin"
    assert fed[0]["prompt"] == "入账测试"


def test_feed_draw_ledger_local_adapts_file_to_data_url(monkeypatch, tmp_path):
    """适配层：文件 → data URL 喂 feed_draw_ledger，事后移除临时字段。"""
    seen = {}

    import app.core.ai.draw_ledger as DL

    def _fake_feed(result, *, prompt, model, size, channel_id, seed,
                   seed_sent, elapsed_ms, retried=False, kind="image"):
        seen["data_url"] = result.get("image_data_url", "")
        seen["model"] = model
        seen["seed_sent"] = seed_sent
        result["proxy_score"] = 0.9   # 模拟接线层就地写回
        result["is_proxy"] = True

    monkeypatch.setattr(DL, "feed_draw_ledger", _fake_feed)
    p = tmp_path / "img.png"
    p.write_bytes(b"\x89PNGfake")
    result = {"ok": True, "image_path": str(p), "width": 512, "height": 512}

    DL.feed_draw_ledger_local(result, prompt="p", model_id="sd15-t2i",
                              engine="diffsynth", seed=7)

    assert seen["data_url"].startswith("data:image/png;base64,")
    assert seen["model"] == "local/diffsynth/sd15-t2i"
    assert seen["seed_sent"] is True
    # 临时 data URL 必须被移除；接线层写回的字段保留
    assert "image_data_url" not in result
    assert result["proxy_score"] == 0.9


def test_feed_draw_ledger_local_never_raises(tmp_path):
    """红线：入账链路任何异常绝不抛出（不影响生成主链路）。"""
    from app.core.ai.draw_ledger import feed_draw_ledger_local

    # 产物不存在 → 静默跳过
    feed_draw_ledger_local({"ok": True, "image_path": str(tmp_path / "nope.png")},
                           prompt="p", model_id="m", seed=1)
    # 产物字段缺失 → 静默跳过
    feed_draw_ledger_local({"ok": True}, prompt="p", model_id="m", seed=1)


def test_route_generate_uses_normalized_seed():
    """源码级锁：路由 generate 分支必须 seed 归一化 + 收尾入账 + 回显。"""
    src = (ROOT / "app" / "core" / "canvas_routes_post.py").read_text(encoding="utf-8")
    seg = src[src.index("local-image-generate"):]
    assert "normalize_seed" in seg, "路由必须用 normalize_seed 归一化 seed"
    assert "feed_draw_ledger_local" in seg, "路由生成成功后必须入闭环"
    assert 'res["seed_sent"] = True' in seg, "本地生成必可复现，必须回显 seed_sent"
