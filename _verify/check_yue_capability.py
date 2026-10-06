#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""YuE 能力接线 + 诚实失败守卫（2026-09-28）

为什么单独写一个（`run_all_checks` 的 AGENTMAP 不够）
-----------------------------------------------------
AGENTMAP 只覆盖「能力目录 ↔ dispatcher」这一对。而新增能力实际有 **4 处**接线，
其中**第 3/4 处（action 白名单、帮助文案）任何守卫都不覆盖** —— 漏了不报错，
只表现为「Agent 根本不会调用它」。本项目历史上真踩过这个坑。

本脚本做三件事：
  1. **静态断言 4 处接线齐全**（不 import app，避免沙箱 wmic 链）
  2. **动态验证诚实失败**（执行端未配置时 plan/render/transcribe 必须
     返回 unavailable + 安装指引，**绝不**返回假 audio_url / 假 abc）
  3. 探测结果的字段契约（probe 恒带 available/mode/hint）

自包含可执行：`python _verify/check_yue_capability.py`
"""
from __future__ import annotations

import importlib.util
import io
import os
import sys
import tempfile
import types

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FAILS = []

# 临时目录钉到项目内（沙箱 %TEMP% 不可写时 tempfile 会回退到仓库根）
try:
    _T = os.path.join(ROOT, ".workbuddy", "tmp")
    os.makedirs(_T, exist_ok=True)
    tempfile.tempdir = _T
except OSError:
    pass


def check(desc: str, cond: bool) -> None:
    print(f"[{'PASS' if cond else 'FAIL'}] {desc}")
    if not cond:
        FAILS.append(desc)


def _read(*parts: str) -> str:
    p = os.path.join(ROOT, *parts)
    try:
        with open(p, "r", encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError:
        return ""


def _load_yue_music():
    """伪包加载 app/core/ai/yue_music.py —— 跑真代码但不 import app 包。

    yue_music 内部有 `from app.core.canvas_aigc import _canvas_inbox_dir` 等延迟导入，
    只在真正落盘时触发，本脚本不触达，故安全。
    """
    ai_dir = os.path.join(ROOT, "app", "core", "ai")
    pkg = "_sg_ai_pkg"
    if pkg not in sys.modules:
        p = types.ModuleType(pkg)
        p.__path__ = [ai_dir]
        sys.modules[pkg] = p
    full = f"{pkg}.yue_music"
    spec = importlib.util.spec_from_file_location(full, os.path.join(ai_dir, "yue_music.py"))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[full] = mod
    spec.loader.exec_module(mod)
    return mod


# ═══════════════ 1. 四处接线静态断言（守卫不覆盖 3/4） ═══════════════

CATALOG = _read("app", "core", "agent_capability_catalog.py")
HANDLERS = _read("app", "core", "capability_handlers.py")
ACTIONS = _read("app", "core", "agent_action_registry.py")

PAIRS = [
    ("canvas.yue_plan", "yue_plan"),
    ("canvas.yue_render", "yue_render"),
    ("canvas.yue_transcribe", "yue_transcribe"),
]

for cap, act in PAIRS:
    check(f"接线1 目录表含 {cap}", f'"{cap}"' in CATALOG)
    check(f"接线2 dispatcher 注册 {cap}", f'dispatcher.register("{cap}"' in HANDLERS)
    check(f"接线3 action 表映射 {act} → {cap}", f'("{act}", "safe", "{cap}"' in ACTIONS)
    check(f"接线4 帮助文案含 {act} 参数说明", f"{act} 参数:" in ACTIONS)

# 帮助文案必须包含「未配置时如实转告」的纪律，避免 LLM 假装成功
check("接线4 含『不要假装生成成功』纪律", "不要假装生成成功" in ACTIONS)

# 端点必须登记（前端桥依赖）
ROUTES = _read("app", "core", "canvas_routes_post.py")
for ep in ("/host/yue/probe", "/host/yue/plan", "/host/yue/generate", "/host/yue/transcribe"):
    check(f"端点已登记 {ep}", f'"{ep}"' in ROUTES)

# cs. 名必须可从 canvas_server 解析（否则端点 AttributeError 静默失效）
SERVER = _read("app", "core", "canvas_server.py")
for name in ("yue_probe_engine", "yue_plan_song", "yue_render_song", "yue_transcribe_reference"):
    check(f"canvas_server 导入 {name}", name in SERVER)


# ═══════════════ 2. 诚实失败（核心纪律） ═══════════════

ym = _load_yue_music()

# 隔离：确保没有远程端点/本地引擎
for k in (ym._ENV_ENDPOINT, ym._ENV_HOME, ym._ENV_SHEETSAGE2_PY):
    os.environ.pop(k, None)
ym._project_root = lambda: os.path.join(tempfile.gettempdir(), "_no_yue_here")

probe = ym.probe_engine()
check("probe 字段契约（available/mode/hint）",
      {"available", "mode", "hint"} <= set(probe.keys()))
check("probe 未配置时 available=False", probe["available"] is False)
check("probe 未配置时给出安装指引", bool(probe.get("hint")) and "SHIGUANG_YUE_ENDPOINT" in probe["hint"])
check("probe 报告 transcribe 不可用", probe.get("transcribe") is False)
check("probe 给出转录环境指引", bool(probe.get("transcribe_hint")))

r_plan = ym.plan_song(lyrics="歌词", style="city pop")
check("plan 未配置 → 诚实失败", r_plan["ok"] is False and r_plan.get("unavailable") is True)
check("plan 未配置 → 不返回假谱", not r_plan.get("abc"))
check("plan 未配置 → 带指引", bool(r_plan.get("hint")))

r_rend = ym.render_song(lyrics="歌词", style="pop")
check("render 未配置 → 诚实失败", r_rend["ok"] is False and r_rend.get("unavailable") is True)
check("render 未配置 → 不返回假音频", not r_rend.get("audio_url"))
check("render 未配置 → 带指引", bool(r_rend.get("hint")))

r_tr = ym.transcribe_reference(audio="/tmp/whatever.wav")
check("transcribe 未配置 → 诚实失败", r_tr["ok"] is False)

# 空输入早退（不应混淆成「引擎未配置」）
r_empty = ym.plan_song(lyrics="  ", style="")
check("空输入早退且不报 unavailable", r_empty["ok"] is False and "unavailable" not in r_empty)


# ═══════════════ 3. 请求组装 / cot 语义 ═══════════════

check("cot 三档对齐官方语义", ym.COT_MODES == ("full", "melody", "off"))
check("cot 默认 full", ym.COT_DEFAULT == "full")

req = ym._build_request(lyrics=" L ", style=" S ", cot="bogus", seed=7)
check("非法 cot 归一到 full", req["cot"] == "full")
check("lyrics/style 去空白", req["lyrics"] == "L" and req["style"] == "S")
check("空谱不进请求", "abc" not in req)
req2 = ym._build_request(lyrics="x", style="y", abc="X:1", cot="melody")
check("编辑谱进请求（编辑模式）", req2["abc"] == "X:1" and req2["cot"] == "melody")


# ═══════════════ 汇总 ═══════════════

print("\n" + "=" * 52)
if FAILS:
    print(f"✗ 失败 {len(FAILS)} 项：")
    for f in FAILS:
        print(f"  - {f}")
    sys.exit(1)
print("OK YuE 能力接线（4 处齐全）+ 诚实失败纪律 全部通过")
sys.exit(0)
