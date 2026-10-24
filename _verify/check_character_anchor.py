#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""验证 pipeline.character_anchor（角色一致性锚定）—— 自包含，不依赖 pytest / Qt。

跑法: python _verify/check_character_anchor.py

覆盖本能力**独有风险面**：
  1. features 提取（空值不收录 / list 归一 / 去空白）
  2. 特征指纹稳定性（同内容同指纹；改一字则变）
  3. 锚定卡组装（prompt 优先复用 / 负面词 / 参考图标记）
  4. 漂移检测（改一字段 → 精确定位到该项；未改 → 无误报）
  5. 镜头对齐校验（漏拼强特征 → 定位到镜头与缺失项）
  6. 脏数据容错（None / 非 dict / 空 / 超长截断）
  7. 四处接线静态断言（catalog / handler / action 白名单 / 帮助文案）

说明：按**文件路径**加载纯函数模块，不 import app 包（不触发硬件探测）；
dispatcher 级一致性由 `_verify/run_all_checks.py` 的 AGENTMAP 用例覆盖。
"""

from __future__ import annotations

import importlib.util
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FAILS = []
TOTAL = 0


def check(desc: str, cond: bool) -> None:
    global TOTAL
    TOTAL += 1
    print(f"[{'PASS' if cond else 'FAIL'}] {desc}")
    if not cond:
        FAILS.append(desc)


def _load(name: str, *parts: str):
    """加载 app/core/ai 下的模块（伪包方式，使相对导入可用且不 import app 包）。"""
    import types
    ai_dir = os.path.join(ROOT, "app", "core", "ai")
    pkg = "_sg_ai_pkg"
    if pkg not in sys.modules:
        p = types.ModuleType(pkg)
        p.__path__ = [ai_dir]
        sys.modules[pkg] = p
    fname = parts[-1]
    modname = fname[:-3] if fname.endswith(".py") else fname
    full = f"{pkg}.{modname}"
    spec = importlib.util.spec_from_file_location(full, os.path.join(ai_dir, fname))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[full] = mod
    spec.loader.exec_module(mod)
    return mod


def _read(*parts: str) -> str:
    with open(os.path.join(ROOT, *parts), encoding="utf-8-sig") as f:
        return f.read()


def main() -> int:
    ca = _load("_character_anchor", "app", "core", "ai", "character_anchor.py")

    CHAR = {
        "id": "c1", "name": "林晚", "gender": "女", "age_range": "青年",
        "appearance": "长发红衣", "memory_anchors": "左眼泪痣",
        "personality": "清冷", "core_desire": "找回记忆",   # inner 组不该进 traits
        "face_params": '{"v":1,"eyeStyle":"cat"}',          # 捏脸写回 ⇒ 必须参与锚定
    }

    # ── 1. 特征提取 ──
    t = ca.extract_traits(CHAR)
    check("traits 只收录锚定字段", set(t) == {"name", "gender", "age_range",
                                            "appearance", "memory_anchors",
                                            "personality", "face_params"})
    check("inner 组不收录", "core_desire" not in t)
    check("空值不收录", "temperament" not in t)
    check("_norm list 归一", ca._norm(["a", "b"]) == "a,b")
    check("_norm 去空白", ca._norm("  x y ") == "xy")
    check("_norm None → 空", ca._norm(None) == "")
    check("非 dict → {}", ca.extract_traits(None) == {} and ca.extract_traits("x") == {})

    # ── 2. 特征指纹 ──
    f1 = ca.fingerprint(t)
    f2 = ca.fingerprint(ca.extract_traits(CHAR))
    check("指纹稳定且长 12", f1 == f2 and len(f1) == 12)
    t2 = dict(t)
    t2["appearance"] = "短发蓝衣"
    check("改内容指纹变", ca.fingerprint(t2) != f1)
    check("空 traits 指纹为空", ca.fingerprint({}) == "")

    # ── 3. 锚定卡组装 ──
    a = ca.build_anchor(CHAR)
    check("anchor.ok", a["ok"] is True)
    check("anchor 指纹正确", a["fingerprint"] == f1)
    check("anchor prompt 含角色名+外貌", "林晚" in a["prompt"] and "长发红衣" in a["prompt"])
    check("anchor 负面词非空", len(a["negative"]) > 0)
    check("无参考图 has_reference=False", a["has_reference"] is False)
    check("有参考图 has_reference=True", ca.build_anchor(CHAR, reference_image="/x/f.png")["has_reference"] is True)
    check("传入 prompt 优先复用", ca.build_anchor(CHAR, prompt="自定义P")["prompt"] == "自定义P")
    check("None character → ok False", ca.build_anchor(None)["ok"] is False)

    # ── 4. 漂移检测 ──
    d0 = ca.diff_anchor(a, CHAR)
    check("未改动 → 无漂移", d0["ok"] is True and d0["drifted"] == [])
    CHAR2 = dict(CHAR, appearance="短发蓝衣")
    d1 = ca.diff_anchor(a, CHAR2)
    check("改外貌 → 定位 appearance", d1["drifted"] == ["appearance"])
    check("漂移 detail 有前后值",
          d1["detail"]["appearance"]["before"] == "长发红衣"
          and d1["detail"]["appearance"]["after"] == "短发蓝衣")
    check("漂移指纹前后不同", d1["fingerprint_before"] != d1["fingerprint_after"])
    check("空锚定卡 → ok False", ca.diff_anchor(None, CHAR)["ok"] is False)
    check("新增字段也算漂移", "temperament" in ca.diff_anchor(a, dict(CHAR, temperament="温润"))["drifted"])

    # ── 5. 镜头对齐校验（防漏拼）──
    shots = ["林晚站在雨中，长发红衣，左眼泪痣清晰", "林晚的近景，左眼泪痣"]
    al = ca.check_shot_alignment(a, shots)
    check("镜头0 完整 → ok", al["shots"][0]["ok"] is True)
    check("镜头1 漏 appearance → retry", al["retry_indices"] == [1])
    check("漏拼项定位正确", al["shots"][1]["missing"] == ["appearance"])
    al2 = ca.check_shot_alignment(a, ["林晚，长发红衣，左眼泪痣"])
    check("全对齐 → ok 无重试", al2["ok"] is True and al2["retry_indices"] == [])
    check("空锚定卡不崩", ca.check_shot_alignment(None, ["x"])["ok"] is False)
    check("无 shot_prompts 不崩", ca.check_shot_alignment(a, None)["checked"] == 0)
    no_strong = ca.build_anchor({"name": "只知名"})
    check("无强特征 → 跳过校验 ok", ca.check_shot_alignment(no_strong, ["任意"])["ok"] is True)

    # ── 6. plan_anchor 统一入口 ──
    p = ca.plan_anchor(CHAR, shot_prompts=shots)
    check("plan_anchor ok", p["ok"] is True)
    check("plan 含 drift + alignment", p["drift"] is not None and p["alignment"] is not None)
    check("plan message 非空", bool(p["message"]))

    # ── 7. 超长截断 ──
    long_prompt = ca.render_anchor_prompt(ca.build_anchor({"name": "A", "appearance": "x" * 500}))
    check("超长字段被截断", len(long_prompt) < 400)

    # ── 8. 四处接线（静态断言）──
    cat_src = _read("app", "core", "agent_capability_catalog.py")
    check("接线1 catalog 含 pipeline.character_anchor", '"pipeline.character_anchor"' in cat_src)
    h_src = _read("app", "core", "capability_handlers.py")
    check("接线2 handlers 含 def character_anchor", "def character_anchor" in h_src)
    check("接线2 handlers 含 register", 'dispatcher.register("pipeline.character_anchor"' in h_src)
    a_src = _read("app", "core", "agent_action_registry.py")
    check("接线3 action 白名单含 character_anchor", '"character_anchor"' in a_src)
    check("接线3 映射到 pipeline.character_anchor", '"pipeline.character_anchor"' in a_src)
    check("接线4 帮助文案含参数说明", "character_anchor 参数" in a_src)

    # ── 汇总 ──
    print()
    if FAILS:
        print(f"FAILED {len(FAILS)} / {TOTAL}")
        for f in FAILS:
            print(f"  - {f}")
        return 1
    print(f"ALL PASS ({TOTAL} checks)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
