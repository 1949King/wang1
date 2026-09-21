#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""验证 provider_caps（P0-3 能力声明 + 自动路由）—— 自包含，不依赖 pytest / Qt。

跑法: python _verify/check_provider_caps.py

对照任务清单验收标准：
  1. 请求「首尾帧」→ 声明 first_last_frame=False 的 provider（cogvideo）不出现在候选
  2. 请求 duration=12 而 max_duration=10 → 被过滤
  3. 新增 provider 只加声明（register_caps），路由代码零改动
  4. local 永远兜底、不受筛选拦截
  5. normalize_spec 合并（显式 spec 优先 / width+height → 分辨率档位 / 竖屏同档）
"""
from __future__ import annotations

import importlib.util
import os
import sys
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
    pc = _load("provider_caps.py")

    # ── 1. 首尾帧筛选（验收①）──
    order = pc.resolve_order("auto", spec={"first_last_frame": True})
    check("首尾帧请求 → cogvideo 不在候选", "cogvideo" not in order)
    check("首尾帧请求 → seedance 在候选", "seedance" in order)
    check("local 永远兜底", order[-1] == "local")
    check("无 spec → 默认顺序全保留",
          pc.resolve_order("auto") == ["dashscope", "seedance", "cogvideo", "local"])

    # ── 2. 时长筛选（验收②）──
    order = pc.resolve_order("auto", spec={"duration": 12.0})
    check("duration=12 → seedance/cogvideo 都被过滤", order == ["local"])
    check("duration=10 → 不被过滤（边界 =）",
          "seedance" in pc.resolve_order("auto", spec={"duration": 10.0}))

    # ── 3. 显式 provider 不支持 → 只剩 local ──
    check("指定 cogvideo 请求首尾帧 → 只剩 local",
          pc.resolve_order("cogvideo", spec={"first_last_frame": True}) == ["local"])
    check("指定 seedance 请求首尾帧 → 正常",
          pc.resolve_order("seedance", spec={"first_last_frame": True})
          == ["seedance", "local"])

    # ── 4. 分辨率筛选 ──
    order = pc.resolve_order("auto", spec={"resolution": "480p"})
    check("480p 请求 → cogvideo 被过滤（不支持480p）", "cogvideo" not in order)
    check("1080p 竖屏（1080x1920）→ 同档不被过滤",
          "cogvideo" in pc.resolve_order(
              "auto", spec={"width": 1080, "height": 1920}))

    # ── 5. register_caps：新增 provider 只加声明（验收③）──
    pc.register_caps("newvid", {
        "name": "测试新渠道", "text_to_video": True, "image_to_video": True,
        "first_last_frame": True, "lip_sync": True,
        "max_duration": 20.0, "resolutions": ["*"], "quality_tier": 2,
    })
    order = pc.resolve_order("auto", spec={"lip_sync": True, "duration": 15.0})
    check("新增 provider 进 auto 顺序", "newvid" in order)
    check("tier=2 的新渠道排最前（tier 降序）", order[0] == "newvid")
    check("lip_sync=True → 旧渠道被过滤", "seedance" not in order and "cogvideo" not in order)
    # 清理，避免影响后续断言
    pc.DEFAULT_REAL_ORDER.remove("newvid")
    del pc.PROVIDER_CAPS["newvid"]

    # ── 6. supports / filter_by_caps 明细 ──
    ok, reason = pc.supports("cogvideo", {"first_last_frame": True})
    check("supports 返回人话理由", ok is False and "首尾帧" in reason)
    ok, reason = pc.supports("seedance", {"duration": 11})
    check("超时长理由", ok is False and "时长" in reason)
    ok, _ = pc.supports("seedance", {"duration": 8})
    check("正常需求 ok", ok is True)
    filt = pc.filter_by_caps(["seedance", "cogvideo", "local"],
                             {"first_last_frame": True})
    check("filter_by_caps 不动 local", filt["kept"] == ["seedance"]
          and filt["dropped"] == [("cogvideo", filt["dropped"][0][1])])

    # ── 7. normalize_spec ──
    s = pc.normalize_spec({"first_last_frame": True, "width": 1920, "height": 1080})
    check("spec 内 width/height → resolution", s.get("resolution") == "1080p")
    s = pc.normalize_spec({"resolution": "auto"})
    check("resolution=auto 不参与筛选", "resolution" not in s)
    s = pc.normalize_spec({"duration": 5}, duration=12)
    check("显式 spec 的 duration 优先", s.get("duration") == 5.0)
    s = pc.normalize_spec(None, duration=12)
    check("裸 duration 参数生效", s.get("duration") == 12.0)
    check("空 spec → 无筛选条件", pc.normalize_spec(None) == {})
    check("resolution_label 竖屏同档", pc.resolution_label(1080, 1920) == "1080p")
    check("resolution_label 未知档 → 空", pc.resolution_label(999, 999) == "")

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
