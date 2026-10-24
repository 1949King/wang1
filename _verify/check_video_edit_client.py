#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""验证指令式视频编辑客户端（video_edit_client，P1-2）—— 自包含，不依赖 pytest / Qt / 网络。

跑法: python _verify/check_video_edit_client.py

验收标准（2026-10-15 竞争点 P1-2）：
  1. provider_caps edit_video 能力位：seedance/kling=True，dashscope/cogvideo/local=False
  2. plan_edit 纯函数拒绝路径：空指令 / 素材两缺 / 文件不存在 / 不出域硬开关
  3. 渠道顺序固定 seedance 先、kling 后；kling 无公网 video_url 诚实跳过（出域要知情）
  4. edit_video 失败保原镜：无 Key → 诚实失败、original_kept=True、clip_path 仍是原片
  5. Base64 直传上限：超限诚实拒绝，不硬传
  6. 成功路径编排：渠道成功 → original_kept=False、channel_used 如实回报
"""
from __future__ import annotations

import importlib.util
import os
import sys
import tempfile
import types

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FAILS = []
TOTAL = 0


def check(desc: str, cond: bool) -> None:
    global TOTAL
    TOTAL += 1
    print(f"[{'PASS' if cond else 'FAIL'}] {desc}")
    if not cond:
        FAILS.append(desc)


def _load(fname: str):
    """加载 app/core/ai 下的模块（伪包方式，使相对导入可用且不 import app 包）。"""
    ai_dir = os.path.join(ROOT, "app", "core", "ai")
    pkg = "_sg_ai_pkg"
    if pkg not in sys.modules:
        p = types.ModuleType(pkg)
        p.__path__ = [ai_dir]
        sys.modules[pkg] = p
    modname = fname[:-3]
    full = f"{pkg}.{modname}"
    spec = importlib.util.spec_from_file_location(full, os.path.join(ai_dir, fname))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[full] = mod
    spec.loader.exec_module(mod)
    return mod


def main() -> int:
    pc = _load("provider_caps.py")   # 先加载：video_edit_client 的相对导入复用同一伪包
    vec = _load("video_edit_client.py")

    # 临时片段文件（存在性校验用，不读内容）
    fd, clip = tempfile.mkstemp(suffix=".mp4", prefix="sg_edit_")
    os.write(fd, b"stub")
    os.close(fd)
    # 备份并清空可能干扰的环境（no_egress 读取；Key 走 monkeypatch 不依赖 env）
    saved_env = {k: os.environ.pop(k, None) for k in
                 ("SHIGUANG_NO_EGRESS", "ARK_API_KEY", "VOLC_ARK_API_KEY",
                  "DOUBAO_API_KEY", "KLING_API_KEY")}
    try:
        # ── 1. provider_caps edit_video 能力位（验收①）──
        ok, _ = pc.supports("seedance", {"edit_video": True})
        check("seedance 声明 edit_video=True", ok is True)
        ok, _ = pc.supports("kling", {"edit_video": True})
        check("kling 声明 edit_video=True", ok is True)
        ok, reason = pc.supports("dashscope", {"edit_video": True})
        check("dashscope 不支持 → 理由含「指令式编辑」", ok is False and "指令式编辑" in reason)
        ok, _ = pc.supports("cogvideo", {"edit_video": True})
        check("cogvideo 不支持 edit_video", ok is False)
        ok, _ = pc.supports("local", {"edit_video": True})
        check("local 不声明 edit_video（无本地占位编辑）", ok is False)

        # ── 2. plan_edit 拒绝路径（验收②）──
        r = vec.plan_edit(clip, "")
        check("空指令 → 拒绝", r["ok"] is False and "指令" in r["message"])
        r = vec.plan_edit("", "把外套改成红色")
        check("素材两缺 → 拒绝", r["ok"] is False and "至少其一" in r["message"])
        r = vec.plan_edit(os.path.join(tempfile.gettempdir(), "sg_no_such_clip.mp4"),
                          "把外套改成红色")
        check("片段不存在 → 拒绝", r["ok"] is False and "不存在" in r["message"])
        os.environ["SHIGUANG_NO_EGRESS"] = "1"
        r = vec.plan_edit(clip, "把外套改成红色", video_url="https://example.com/v.mp4")
        check("不出域硬开关 → 诚实拒绝", r["ok"] is False and "不出域" in r["message"])
        del os.environ["SHIGUANG_NO_EGRESS"]

        # ── 3. 渠道顺序与 kling 出域前提（验收③）──
        r = vec.plan_edit(clip, "把外套改成红色")
        check("无 video_url → 只剩 seedance", r["ok"] and r["channels"] == ["seedance"])
        check("kling 被跳过且理由含「公网 URL」",
              any(p == "kling" and "公网 URL" in reason for p, reason in r["dropped"]))
        r = vec.plan_edit(clip, "把外套改成红色", video_url="https://example.com/v.mp4")
        check("有 video_url → seedance 先 kling 后", r["channels"] == ["seedance", "kling"])
        r = vec.plan_edit(clip, "把外套改成红色", channel="kling")
        check("显式只要 kling 但无 URL → 无可用渠道",
              r["ok"] is False and "没有可用编辑渠道" in r["message"])

        # ── 4. edit_video 失败保原镜（验收④）──
        vec.get_ark_key = lambda: ""    # monkeypatch：模拟两渠道都没 Key
        vec.get_kling_key = lambda: ""
        res = vec.edit_video(clip, "把外套改成红色",
                             video_url="https://example.com/v.mp4")
        check("无 Key → ok=False", res["ok"] is False)
        check("无 Key → 保原镜 original_kept=True", res["original_kept"] is True)
        check("无 Key → clip_path 仍是原片", res["clip_path"] == clip)
        check("无 Key → errors 逐渠道如实记录（含方舟 Key 提示）",
              len(res["errors"]) == 2 and any("方舟" in e for e in res["errors"]))

        # ── 5. Base64 直传上限（验收⑤）──
        vec.get_ark_key = lambda: "fake-key"
        vec._MAX_BASE64_MB = 0          # 模拟超限（stub 文件 >0MB 即触发）
        res = vec.edit_video(clip, "把外套改成红色", model="seedance-edit-x")
        check("超 Base64 上限 → 诚实拒绝且保原镜",
              res["ok"] is False and res["original_kept"] is True
              and any("Base64" in e for e in res["errors"]))
        vec._MAX_BASE64_MB = 50

        # ── 6. 成功路径编排（验收⑥，mock 渠道执行不联网）──
        vec._edit_seedance = lambda *a, **k: {
            "ok": True, "clip_path": clip + ".new.mp4",
            "channel": "seedance", "cost_note": "测试"}
        res = vec.edit_video(clip, "把外套改成红色")
        check("渠道成功 → ok=True 且 original_kept=False",
              res["ok"] is True and res["original_kept"] is False)
        check("渠道成功 → channel_used 如实回报", res["channel_used"] == "seedance")
    finally:
        for k, v in saved_env.items():
            if v is not None:
                os.environ[k] = v
        try:
            os.remove(clip)
        except OSError:
            pass

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
