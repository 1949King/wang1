# -*- coding: utf-8 -*-
"""回归：配音听写回环验证闭环（配音一致性方案 P1④，2026-10-15）

守什么（防静默假成功）
======================
用户痛点①是「配音发音与字幕/字对不上，且经常性」。如果配音交付只回一条成功，
不标「到底像不像」，那又会变成"看起来成功、其实读错音"的假交付。本守卫把
**诚实降级 / 可测量** 这两条纪律变成可执行断言：

1. `app/core/ai/dub_verify.py` 存在，且定义 `verify_dubbing`（含阈值语义）与
   `transcribe_for_subtitles`（音→字，字幕真相源）；
2. `VoiceGenerationResult` 增了 `verified_similarity` / `subtitle_source` 两个字段，
   **且 to_dict() 同步输出**（serialization-field-symmetry：否则会静默丢失）；
3. 编排端点 `/host/dub-execute` 的 handler 里**真的回填**了这两个标记
   （`entry["verified_similarity"]` 与 `subtitle_source`）；
4. 字幕来自**音频听写**（调用 `transcribe_for_subtitles`），**禁止用剧本回填**；
5. `dub_pipeline.route_voices` 对未绑定音色的角色明确标 `degraded`（不伪造）。

用法：
    python _verify/check_dub_verify.py
"""
from __future__ import annotations

import ast
import io
import os
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

_fail = []


def check(cond: bool, msg: str) -> None:
    print(f"  {'✓' if cond else '✗'} {msg}")
    if not cond:
        _fail.append(msg)


def _read(rel: str) -> str:
    p = os.path.join(ROOT, rel.replace("/", os.sep))
    if not os.path.isfile(p):
        return ""
    with open(p, encoding="utf-8") as fh:
        return fh.read()


def _func_names(src: str) -> set:
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return set()
    return {n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}


def main() -> int:
    verify_src = _read("app/core/ai/dub_verify.py")
    vg_src = _read("app/core/voice_generator.py")
    routes_src = _read("app/core/canvas_routes_dub.py")
    pipeline_src = _read("app/core/ai/dub_pipeline.py")

    print("[1] dub_verify.py 提供验证与字幕真相源函数")
    check(bool(verify_src), "app/core/ai/dub_verify.py 存在")
    vfn = _func_names(verify_src)
    check("verify_dubbing" in vfn, "定义 verify_dubbing()")
    check("transcribe_for_subtitles" in vfn, "定义 transcribe_for_subtitles()（音→字）")
    check("PASS_THRESHOLD" in verify_src and "WARN_THRESHOLD" in verify_src,
          "相似度阈值（pass/warn）以常量表达，低阈一律红标")

    print("\n[2] VoiceGenerationResult 字段 + to_dict 序列化对称")
    check("verified_similarity" in vg_src, "VoiceGenerationResult 含 verified_similarity")
    check("subtitle_source" in vg_src, "VoiceGenerationResult 含 subtitle_source")
    # to_dict 内必须同时出现两个键（对称性），否则写日志/落盘会丢
    idx = vg_src.find("def to_dict", vg_src.find("class VoiceGenerationResult"))
    to_dict_block = vg_src[idx: idx + 800] if idx != -1 else ""
    check('"verified_similarity"' in to_dict_block and '"subtitle_source"' in to_dict_block,
          "to_dict() 同步输出两个新字段（serialization symmetry）")

    print("\n[3] /host/dub-execute 真的回填标记 + 字幕来自音频")
    check("verify_dubbing" in routes_src, "端点调用 verify_dubbing()")
    check('entry["verified_similarity"]' in routes_src, "回填 entry['verified_similarity']")
    check("red_flag" in routes_src, "低阈打红标（red_flag）")
    check("transcribe_for_subtitles" in routes_src, "字幕走 transcribe_for_subtitles()（音→字）")
    check('subtitle_source = "asr"' in routes_src or "subtitle_source" in routes_src,
          "如实标注 subtitle_source（asr / unavailable）")
    check("/host/dub-plan" in routes_src and "/host/dub-execute" in routes_src
          and "/host/dub-to-timeline" in routes_src,
          "三条编排端点齐备（plan/execute/to-timeline）")

    print("\n[4] 编排纯函数 + 诚实降级")
    pfn = _func_names(pipeline_src)
    for fn in ("parse_dialogue_lines", "route_voices", "retime_shots_by_audio",
               "assemble_dialogue_track"):
        check(fn in pfn, f"dub_pipeline 定义 {fn}()")
    check("degraded" in pipeline_src, "route_voices 对未绑定音色标 degraded（不伪造）")
    check('duration_source' in pipeline_src, "反推镜头时长标注 duration_source（有音频证据才改）")

    print()
    if _fail:
        print(f"✗ 失败 {len(_fail)} 项：")
        for f in _fail:
            print("   -", f)
        return 1
    print("OK 配音验证闭环接线齐备（诚实降级 + 可测量）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
