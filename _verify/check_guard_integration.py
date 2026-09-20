#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""验证 V4.33.5 的三个管线缺口修复（① TTS 挂配音链路 / ② 质检默认不烧 LLM / ③ 自动装配）。

跑法: python _verify/check_guard_integration.py

覆盖：
  ① voice_generator：长台词 guard=True 分段合成（逐段调 TTS + 拼接）/ 短句走原路径 / 默认关 /
    _write_wav / 两处调用点传 guard=True（静态断言）
  ② guard_pipeline.augment_inspection 默认 use_llm=False（不调 LLM），显式开才调
  ③ guard_pipeline.build_guards_from_context：角色（显式 > 角色库）/ 道具 / 表情档位推断 / use_llm 写入
    + capability_handlers 的 guards="auto" 分支（静态断言）
"""

from __future__ import annotations

import importlib.util
import json
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

FAILS = []
TOTAL = 0


def check(desc: str, cond: bool) -> None:
    global TOTAL
    TOTAL += 1
    print(f"[{'PASS' if cond else 'FAIL'}] {desc}")
    if not cond:
        FAILS.append(desc)


def _load(name: str, *parts: str):
    import types
    ai_dir = os.path.join(ROOT, "app", "core", "ai")
    pkg = "_sg_ai_pkg"
    if pkg not in sys.modules:
        p = types.ModuleType(pkg)
        p.__path__ = [ai_dir]
        sys.modules[pkg] = p
    fname = parts[-1]
    modname = fname[:-3] if fname.endswith(".py") else fname
    spec = importlib.util.spec_from_file_location(f"{pkg}.{modname}", os.path.join(ai_dir, fname))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[f"{pkg}.{modname}"] = mod
    spec.loader.exec_module(mod)
    return mod


def _read(*parts: str) -> str:
    with open(os.path.join(ROOT, *parts), encoding="utf-8-sig") as f:
        return f.read()


def main() -> int:
    # ═══════════ ① TTS 守护挂配音链路 ═══════════
    import numpy as np
    from app.core.voice_generator import AIVoiceGenerator, VoiceGenerationResult

    vg = AIVoiceGenerator()
    calls = []

    def fake_generate_voice(request):
        calls.append(str(request.text))
        n = 2205  # 0.1s @ 22050
        t = np.linspace(0, 0.1, n, endpoint=False)
        audio = np.sin(2 * np.pi * 220 * t).astype(np.float32)
        return VoiceGenerationResult(
            request_id="x", audio_data=audio, audio_path=None,
            duration=0.1, sample_rate=22050, success=True)

    vg.generate_voice = fake_generate_voice

    long_text = "这是第一句台词。" * 8          # 约 64 字 → 应切段
    calls.clear()
    r = vg.generate_audio(long_text, guard=True)
    check("① 长文本 guard=True 分段合成成功",
          r["success"] is True and r.get("guarded") is True and r.get("segments", 1) > 1)
    check("① 逐段调用了 TTS（调用次数 = 段数）", len(calls) == r.get("segments"))
    check("① 产出 wav 文件", os.path.isfile(r.get("audio_path", "")))

    calls.clear()
    r2 = vg.generate_audio("短句。", guard=True)
    check("① 短句不分段（guarded=False）", r2["success"] is True and r2.get("guarded") is False)
    check("① 短句只调一次 TTS", len(calls) == 1)

    calls.clear()
    r3 = vg.generate_audio(long_text)            # 默认不传 guard
    check("① 默认不守护（guarded 非 True）", r3["success"] is True and r3.get("guarded") is not True)

    # _write_wav
    tmp_wav = os.path.join(tempfile.gettempdir(), "sg_test_voice.wav")
    err = vg._write_wav(tmp_wav, np.zeros(1000, dtype=np.float32), 22050)
    check("① _write_wav 成功返回 None", err is None and os.path.isfile(tmp_wav))
    if os.path.isfile(tmp_wav):
        os.remove(tmp_wav)

    # 静态断言：两个调用点已传 guard
    ca = _read("app", "core", "canvas_aigc.py")
    ai = _read("app", "core", "ai_engine.py")
    check("① canvas_aigc 本地后端传 guard", "guard=bool(params.get(\"guard\", True))" in ca)
    check("① ai_engine TTSAdapter 传 guard", "guard=bool(kwargs.get(\"guard\", True))" in ai)

    # ═══════════ ② 质检默认不烧 LLM ═══════════
    gp = _load("_guard_pipeline", "app", "core", "ai", "guard_pipeline.py")

    llm_calls = {"n": 0}

    def spy_llm(prompt):
        llm_calls["n"] += 1
        return '{"issues": [], "suggestion": ""}'

    out_default = gp.augment_inspection("p", guards={}, llm=spy_llm)
    check("② 默认 use_llm=False → 不调 LLM", out_default["layers"]["llm"] is False and llm_calls["n"] == 0)

    out_on = gp.augment_inspection("p", guards={}, llm=spy_llm, use_llm=True)
    check("② 显式 use_llm=True → 调 LLM", out_on["layers"]["llm"] is True and llm_calls["n"] == 1)

    # _guard_inspect 默认开关（静态）
    pipe = _read("app", "core", "ai_video_generation_pipeline.py")
    check("② 管线 _guard_inspect 默认关 LLM", "use_llm=bool(guards.get(\"use_llm\", False))" in pipe)

    # ═══════════ ③ 自动装配 ═══════════
    # 角色库临时文件
    tmp_lib = os.path.join(tempfile.gettempdir(), "sg_library.json")
    with open(tmp_lib, "w", encoding="utf-8") as f:
        json.dump([
            {"name": "林晚", "appearance": "长发红衣", "memory_anchors": "左眼泪痣"},
            {"name": "苏瑶", "appearance": "短发蓝衣"},
        ], f, ensure_ascii=False)

    g_lib = gp.build_guards_from_context(character_name="林晚", library_path=tmp_lib,
                                         prop_type="spear", grip="two_hand",
                                         emotions=["愤怒", "平静"])
    check("③ 角色从库装配", g_lib.get("character", {}).get("name") == "林晚")
    check("③ 来源标记 library", g_lib["_sources"].get("character") == "library")
    check("③ 道具装配", g_lib.get("prop", {}).get("prop_type") == "spear")
    check("③ 强情绪 → intense 档位", g_lib.get("expression", {}).get("profile") == "intense")
    check("③ use_llm 写入 guards", g_lib.get("use_llm") is False)

    g_exp = gp.build_guards_from_context(character={"name": "显式", "appearance": "x"})
    check("③ 显式角色优先", g_exp["_sources"]["character"] == "explicit"
          and g_exp["character"]["name"] == "显式")

    g_miss = gp.build_guards_from_context(character_name="不存在", library_path=tmp_lib)
    check("③ 库未命中 → library_miss 且不崩", g_miss["_sources"].get("character") == "library_miss"
          and "character" not in g_miss)

    g_plain = gp.build_guards_from_context(emotions=["平静"])
    check("③ 无强情绪 → natural", g_plain["expression"]["profile"] == "natural")

    g_none = gp.build_guards_from_context()
    check("③ 全空不崩（仅 use_llm + _sources）", "character" not in g_none and g_none.get("use_llm") is False)

    check("③ describe_guards 非空", bool(gp.describe_guards(g_lib)))

    if os.path.isfile(tmp_lib):
        os.remove(tmp_lib)

    # 静态断言：handler 的 guards="auto" 分支
    h = _read("app", "core", "capability_handlers.py")
    check("③ handler 支持 guards=auto", 'if g == "auto" or (isinstance(g, dict) and g.get("auto"))' in h
          and "build_guards_from_context" in h)

    # ── 汇总 ──
    print()
    if FAILS:
        print(f"FAILED {len(FAILS)} / {TOTAL}")
        for x in FAILS:
            print(f"  - {x}")
        return 1
    print(f"ALL PASS ({TOTAL} checks)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
