# -*- coding: utf-8 -*-
"""画布意图级增强层守卫（2026-09-30 新增）。

钉死五条纪律——它们都是「漏了不报错、只是悄悄变坏」的类型：
  ① 两个端点已注册（`/host/canvas-enhance` · `/host/enhance-intents`）；
  ② **意图目录只暴露意图，不暴露模型名**（这是与 ComfyUI 的分歧点 ——
     一旦 `available_intents()` 泄漏 `engine`/`model` 键，用户又被推回"选模型"的老路）；
  ③ **每一步必须回报实际引擎**（静态断言 `_step_*` 都含 engine 或显式 applied=False）；
  ④ **`degraded` 必须与 `reason` 同源**（都从同一个 `want_*` 判据推导，
     否则出现「reason 说降级了、degraded 却是 False」的自相矛盾）；
  ⑤ **绝不抛异常**（坏输入返回 ok=False，而不是向上抛）。

零项目依赖：按文件路径加载 `canvas_enhance.py`，不 import app 包。
"""
import ast
import importlib.util
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENHANCE_REL = os.path.join("app", "core", "canvas_enhance.py")
POST_REL = os.path.join("app", "core", "canvas_routes_post.py")
GET_REL = os.path.join("app", "core", "canvas_routes_get.py")

_fails = []


def check(name, ok, detail=""):
    tag = "OK  " if ok else "FAIL"
    print(f"  [{tag}] {name}" + (f" — {detail}" if detail and not ok else ""))
    if not ok:
        _fails.append(name)


def _read(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8") as f:
        return f.read()


def _load_enhance():
    path = os.path.join(ROOT, ENHANCE_REL)
    spec = importlib.util.spec_from_file_location("_enh_guard", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main() -> int:
    print("== 画布意图级增强层守卫 ==")

    enh_src = _read(ENHANCE_REL)
    post_src = _read(POST_REL)
    get_src = _read(GET_REL)

    # ① 端点已注册
    check("端点已声明 POST /host/canvas-enhance",
          '@_route_post("/host/canvas-enhance")' in post_src)
    check("端点已声明 GET /host/enhance-intents",
          '@_route_get("/host/enhance-intents")' in get_src)

    mod = _load_enhance()

    # ② 目录只暴露意图、不暴露模型名
    intents = mod.available_intents()
    check("意图目录非空", len(intents) >= 3, f"实际 {len(intents)} 项")
    leaked = [i for i in intents
              if any(k in i for k in ("engine", "model", "engine_s", "onnx"))]
    check("★ 目录不泄漏模型名（键层面）", not leaked, str(leaked))

    # ★ 文案层面也要查：曾经 label/hint 里写了「high 档用 RealESRGAN」——
    #   那正是把用户推回 ComfyUI 的「选模型」老路。测试先抓到，这里钉死。
    _BANNED_TOKENS = ("realesrgan", "espcn", "gfpgan", "modnet", "u2net",
                      "lama", "onnx", "bicubic", "模型名", "采样器", "steps",
                      "cfg", "denoise")
    text_leaks = []
    for i in intents:
        blob = f"{i.get('label','')} {i.get('hint','')}".lower()
        for tok in _BANNED_TOKENS:
            if tok in blob:
                text_leaks.append(f"{i['id']}:{tok}")
    check("★ 文案不泄漏实现细节（模型名/采样器/步数）", not text_leaks, str(text_leaks))

    check("每个意图都有 label 与 hint",
          all(i.get("label") and i.get("hint") for i in intents))
    check("质量档位为 fast/standard/high",
          set(mod.QUALITY_TIERS) == {"fast", "standard", "high"},
          str(list(mod.QUALITY_TIERS)))

    # ③ 每步都必须回报实际引擎（静态：AST 检查 _step_* 的返回字典）
    tree = ast.parse(enh_src)
    step_names = [n.name for n in ast.walk(tree)
                  if isinstance(n, ast.FunctionDef) and n.name.startswith("_step_")]
    check("存在 5 个意图处理器", len(step_names) == 5, str(step_names))
    bad = []
    for n in ast.walk(tree):
        if isinstance(n, ast.FunctionDef) and n.name.startswith("_step_"):
            has_engine = any(
                isinstance(d, ast.Dict) and any(
                    isinstance(k, ast.Constant) and k.value == "engine"
                    for k in d.keys)
                for d in ast.walk(n))
            has_applied_false = "applied" in ast.dump(n)
            if not (has_engine and has_applied_false):
                bad.append(n.name)
    check("★ 每个处理器都回报 engine 且带 applied 字段", not bad, str(bad))

    # ④ degraded 与 reason 同源（sharpen 是唯一有降级语义的步骤）
    check("★ _step_sharpen 的 degraded 由 want_realesrgan 判据推导（与 reason 同源）",
          "want_realesrgan" in enh_src
          and "degraded = (model == \"bicubic\") or (want_realesrgan and model != \"realesrgan\")" in enh_src)

    # ⑤ 不存在第二份引擎调用（曾经的 _apply_to_array 反模式）
    check("★ 无重复的第二份引擎调用（_apply_to_array 已消除）",
          "_apply_to_array" not in enh_src)
    check("列表式流水线：本步产物交给下一步",
          "img = out" in enh_src)

    # ⑥ 动态：坏输入不抛异常
    # ⚠️ 守卫**刻意不依赖 cv2** —— `run_all_checks` 用调用方的解释器跑守卫，
    #    不同环境（.venv312 vs 托管 venv）cv2 有无不一，依赖它会让守卫时绿时红。
    #    这里只测「不需要解码」的路径；需要解码的语义（未知意图→skipped）
    #    由 pytest（固定在项目 .venv312 跑）覆盖，另加静态断言兜底。
    ok_bad = True
    detail = ""
    try:
        r1 = mod.apply_intents("not-a-data-url", ["face"])   # 非 data URL：正则即拒，不 import cv2
        r2 = mod.apply_intents("", [])                       # 空意图：解码前就返回
        r3 = mod.apply_intents("data:image/png;base64,AAAA", ["__nope__"])  # 解码失败路径
        ok_bad = all(isinstance(r, dict) and r.get("ok") is False for r in (r1, r2, r3))
        detail = f"r1={r1.get('ok')} r2={r2.get('ok')} r3={r3.get('ok')}"
    except Exception as e:
        ok_bad = False
        detail = f"{type(e).__name__}: {e}"
    check("★ 坏输入不抛异常（返回 ok=False）", ok_bad, detail)

    # ⑥b 未知意图必须走 skipped（静态断言：分支与文案都在）
    check("未知意图分支存在（把未知 id 收进 skipped，而非报错）",
          'skipped.append({"intent": name, "label": name,' in enh_src
          and "未知意图" in enh_src)

    # ⑦ 不静默下载：只有 high 档开 RealESRGAN
    check("★ 只有 high 档 use_realesrgan=True（其余档不下载大模型）",
          mod.QUALITY_TIERS["high"]["use_realesrgan"] is True
          and mod.QUALITY_TIERS["fast"]["use_realesrgan"] is False
          and mod.QUALITY_TIERS["standard"]["use_realesrgan"] is False)

    print()
    if _fails:
        print(f"FAILED {len(_fails)}: {_fails}")
        return 1
    print("OK 画布意图级增强层一致（意图而非节点）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
