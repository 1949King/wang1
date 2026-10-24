# -*- coding: utf-8 -*-
"""守卫：小白闭环自动粗剪合链（§6.9-P2 · 方案 1，2026-10-17）。

验证三件事：
  ① 行为契约：plan 只算不改 + needs_confirmation 恒真；apply 未确认拒绝、
     写回后可撤销（compound 一条）、重复写回拒绝、陈旧提案拒绝；
     export 未写回拒绝、写回后委托精剪入口按序出片。
  ② B1/B2 复用：排轨（磁吸紧排）、水词/静音检测、波纹删除（右→左）
     与模拟预测时长一致（同一套纯函数，演练=实删）。
  ③ 静态接线在册：能力目录 4 行、dispatcher 注册行、薄壳 handler、
     队列 runner、本守卫已登记 run_all_checks（防静默断线）。

导入走 ``app.core`` 包（rough_cut_chain 依赖 edit_commands/filler_silence_detect
的 app.core 绝对导入）；不触碰 UI 层，FakeEditor 鸭子类型即可。
"""
from __future__ import annotations

import io
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from app.core.rough_cut_chain import (  # noqa: E402
    RoughCutChain,
    build_clips_from_materials,
    rough_cut_chain,
    rough_cut_job_runner,
)
from app.core.filler_silence_detect import CleanupConfig  # noqa: E402
from app.core.timeline_store import TimelineStore  # noqa: E402

PASS = []
FAIL = []


def check(name: str, ok: bool, detail: str = "") -> None:
    (PASS if ok else FAIL).append(name)
    print("  %s %-58s %s" % ("✅" if ok else "❌", name, detail))


class FakeEditor:
    """鸭子类型剪辑器：只提供 _clips 真相源 / store 写入口 / _record_action / 精剪出片入口。"""

    def __init__(self, clips):
        self._clips = clips
        # 刀4：写回改走 store.replace_all —— 与真实宿主同律（adopt 同一 list，原地突变保同一性）
        self._timeline_store = TimelineStore(clips)
        self.actions = []
        self.export_calls = []

    def _record_action(self, action):
        self.actions.append(action)

    def agent_execute_pipeline_editing(self, script, session_id=""):
        self.export_calls.append((script, session_id))
        return "out_rough_cut.mp4"


def _clip(cid, start, dur, track=0, **extra):
    c = {"id": cid, "path": f"{cid}.mp4", "duration": dur, "start_time": start,
         "track": track, "in_point": 0.0, "out_point": dur, "type": "video"}
    c.update(extra)
    return c


ASR_A = [
    {"text": "今天天气不错", "start": 1.0, "end": 3.0},
    {"text": "呃", "start": 4.0, "end": 4.5},
    {"text": "我们出发", "start": 6.0, "end": 7.0},
]

# ---------------------------------------------------------------------------
# ① 行为契约：确认后执行纪律 + 写回可撤销 + 幂等
# ---------------------------------------------------------------------------
print("=" * 74)
print("① 行为：plan 只算不改 / apply 确认纪律 / export 委托")
print("=" * 74)

chain = RoughCutChain()
clips = [_clip("a", 0.0, 10.0), _clip("b", 12.0, 8.0)]
editor = FakeEditor([_clip("a", 0.0, 10.0), _clip("b", 12.0, 8.0)])

res = chain.plan(clips, mode="timeline", asr_by_clip={"a": ASR_A})
check("plan 成功返回提案", bool(res.get("ok")), str(res.get("error", "")))
proposal = res["proposal"]
kinds = {iv["kind"] for iv in proposal["intervals"]}
check("B2 检出 filler + silence 两类区间",
      "filler" in kinds and "silence" in kinds, str(sorted(kinds)))
check("needs_confirmation 恒为 True（纪律不可绕过）",
      proposal["needs_confirmation"] is True)
check("plan 不改数据（editor._clips 原样）",
      [c["start_time"] for c in editor._clips] == [0.0, 12.0])
check("预测时长 < 原始时长（18s → %.2fs）" % proposal["predicted_duration"],
      proposal["predicted_duration"] < proposal["original_duration"])

r = chain.apply(editor, proposal["plan_id"], confirmed=False)
check("未确认 apply 拒绝执行", not r["ok"] and "确认" in r["error"], r.get("error", ""))
check("拒绝后 export 也失败（未写回）",
      not chain.export(editor, proposal["plan_id"])["ok"])

r = chain.apply(editor, proposal["plan_id"], confirmed=True)
check("确认后 apply 写回成功", r["ok"], r.get("message", ""))
final_dur = sum(float(c.get("duration", 0) or 0) for c in editor._clips)
check("实删时长 == 模拟预测（演练=实删）",
      abs(final_dur - proposal["predicted_duration"]) < 0.05,
      f"{final_dur:.3f} vs {proposal['predicted_duration']:.3f}")
check("排轨生效：b 已贴齐前片尾（缝隙闭合）",
      editor._clips[-1]["start_time"] < 12.0, str(editor._clips[-1]["start_time"]))
check("一条 compound 撤销条目（label=rough_cut_apply）",
      len(editor.actions) == 1 and editor.actions[0].get("type") == "compound"
      and editor.actions[0].get("label") == "rough_cut_apply")
check("写回后重复 apply 拒绝（幂等）",
      not chain.apply(editor, proposal["plan_id"], confirmed=True)["ok"])
ex = chain.export(editor, proposal["plan_id"])
check("export 委托精剪入口并按序传 clip_order",
      ex["ok"] and ex["final_video_path"] == "out_rough_cut.mp4"
      and editor.export_calls
      and editor.export_calls[0][0]["clip_order"]
      == [c["id"] for c in sorted(editor._clips, key=lambda c: c["start_time"])])

# ---------------------------------------------------------------------------
# ② 陈旧守卫：时间线变化后拒绝写回（坐标失效）
# ---------------------------------------------------------------------------
print("=" * 74)
print("② 陈旧守卫：增删片段 / 缺片段 / 不存在提案")
print("=" * 74)

chain2 = RoughCutChain()
clips2 = [_clip("x", 0.0, 6.0), _clip("y", 6.0, 4.0)]
ed2 = FakeEditor([_clip("x", 0.0, 6.0), _clip("y", 6.0, 4.0)])
p2 = chain2.plan(clips2, mode="timeline",
                 asr_by_clip={"y": [{"text": "嗯", "start": 0.5, "end": 1.0}]},
                 cleanup_config=CleanupConfig(detect_silence=False))["proposal"]
ed2._clips.append(_clip("z", 10.0, 3.0))
r = chain2.apply(ed2, p2["plan_id"], confirmed=True)
check("timeline 模式：片段集合变化 ⇒ 拒绝（时间线已变化）",
      not r["ok"] and "变化" in r["error"], r.get("error", ""))
check("不存在的 plan_id 拒绝", not chain2.apply(ed2, "deadbeef0000", confirmed=True)["ok"])
check("空 clips plan 诚实失败", not chain2.plan([], mode="timeline")["ok"])
check("未知 mode 诚实失败", not chain2.plan(clips2, mode="magic")["ok"])

# ---------------------------------------------------------------------------
# ③ materials 模式：入库别名解析（编辑器重生成 id 不断链）
# ---------------------------------------------------------------------------
print("=" * 74)
print("③ materials：顺序紧排 + source_clip_id 别名回退")
print("=" * 74)

materials = [{"clip_id": "m1", "path": "x.mp4", "duration": 6},
             {"clip_id": "m2", "path": "y.mp4", "duration": 4}]
built = build_clips_from_materials(materials)
check("materials 按序从 0 紧排",
      [c["start_time"] for c in built] == [0.0, 6.0], str([c["start_time"] for c in built]))

chain3 = RoughCutChain()
p3 = chain3.plan(built, mode="materials",
                 asr_by_clip={"m2": [{"text": "呃", "start": 0.5, "end": 1.0}]},
                 cleanup_config=CleanupConfig(detect_silence=False))["proposal"]
# 模拟入库后编辑器重生成 id（source_clip_id 别名保留）
ed3 = FakeEditor([
    _clip("clip_1001", 0.0, 6.0, source_clip_id="m1"),
    _clip("clip_1002", 6.0, 4.0, source_clip_id="m2"),
])
r = chain3.apply(ed3, p3["plan_id"], confirmed=True)
check("materials 写回成功（别名解析新 id）", r["ok"], r.get("message", r.get("error", "")))
check("水词已删：m2 时长 4→3.5",
      abs(sum(float(c["duration"]) for c in ed3._clips) - 9.5) < 0.05,
      str([c["duration"] for c in ed3._clips]))
ex3 = chain3.export(ed3, p3["plan_id"])
# 水词在 m2 中间 → B1 切出第三段（split id），顺序按 start_time 排
check("materials export 用写回后的新 id 顺序（含 split 产物）",
      ex3["ok"] and ed3.export_calls[-1][0]["clip_order"]
      == [c["id"] for c in sorted(ed3._clips, key=lambda c: c["start_time"])]
      and len(ed3._clips) == 3,
      str(ed3.export_calls[-1][0]["clip_order"]))
# 未入库直接 apply → 诚实失败
chain4 = RoughCutChain()
p4 = chain4.plan(build_clips_from_materials(materials), mode="materials")["proposal"]
r = chain4.apply(FakeEditor([]), p4["plan_id"], confirmed=True)
check("materials 未入库 apply 拒绝（提示先入库）",
      not r["ok"] and "入库" in r["error"], r.get("error", ""))

# ---------------------------------------------------------------------------
# ④ 静态接线在册（防静默断线）
# ---------------------------------------------------------------------------
print("=" * 74)
print("④ 接线：目录行 / dispatcher 注册 / 薄壳 / 队列 runner / 守卫登记")
print("=" * 74)

from app.core.agent_capability_catalog import CAPABILITY_ROWS  # noqa: E402

cap_ids = {row[0] for row in CAPABILITY_ROWS}
for cid in ("editor.rough_cut_plan", "editor.rough_cut_apply",
            "editor.rough_cut_export", "pipeline.rough_cut_chain"):
    check(f"能力目录在册：{cid}", cid in cap_ids)


def _src(path: str) -> str:
    with open(os.path.join(ROOT, path), encoding="utf-8") as f:
        return f.read()


handlers_src = _src(os.path.join("app", "core", "capability_handlers.py"))
skills_src = _src(os.path.join("app", "core", "capability_handlers_editor_skills.py"))
check("dispatcher 注册：editor.rough_cut_* 三行在循环表",
      all(f'("editor.rough_cut_{n}", "rough_cut_{n}"' in handlers_src
          for n in ("plan", "apply", "export")))
check("dispatcher 注册：pipeline.rough_cut_chain",
      'dispatcher.register("pipeline.rough_cut_chain"' in handlers_src)
check("薄壳 handler 四方法在册（editor_skills）",
      all(f"def rough_cut_{n}(self" in skills_src
          for n in ("plan", "apply", "export", "chain_submit")))
check("队列 runner 可导入且可调用", callable(rough_cut_job_runner))
check("合链单例与类同源（rough_cut_chain 实例）",
      isinstance(rough_cut_chain, RoughCutChain))
check("本守卫已登记 run_all_checks",
      "check_rough_cut_chain.py" in _src(os.path.join("_verify", "run_all_checks.py")))

# ── 画布审核卡 UI 消费接线（2026-10-17 §6.9-P2）──────────────────
chain_src = _src(os.path.join("app", "core", "rough_cut_chain.py"))
check("SSE 双通道在册：_broadcast 推 push_to_canvas(rough_cut.review)",
      'push_to_canvas("rough_cut.review"' in chain_src)
check("plan_ready 广播带 intervals（审核卡可逐条核对）",
      '"intervals": intervals,' in chain_src)

rc_routes_src = _src(os.path.join("app", "core", "canvas_routes_roughcut.py"))
check("端点在册：/host/rough-cut/apply|export 路由注册",
      '@_route_post("/host/rough-cut/apply")' in rc_routes_src
      and '@_route_post("/host/rough-cut/export")' in rc_routes_src)
check("confirmed=True 钉死在后端端点（前端不可绕过闸门）",
      "confirmed=True" in rc_routes_src)
server_src = _src(os.path.join("app", "core", "canvas_server.py"))
check("mixin 接入 _BridgeHandler 继承链",
      "CanvasRoughCutRoutesMixin" in server_src)
routes_guard = _src(os.path.join("_verify", "check_canvas_routes.py"))
check("路由契约守卫登记：SERVER_FILES 含 canvas_routes_roughcut.py",
      "canvas_routes_roughcut.py" in routes_guard)
check("路由契约守卫登记：CLIENTS 含 hostRoughCut.ts",
      "hostRoughCut.ts" in routes_guard)

# P0-1 Phase 2（2026-10-18）：tauri 侧 libtv 副本已删除，两宿主共用真源包，只扫一处。
for repo in (os.path.join("vendor", "packages", "libtv", "src"),):
    hr_src = _src(os.path.join(repo, "hostRoughCut.ts"))
    check(f"前端在册（{repo.split(os.sep)[1]}）：hostRoughCut 订阅判读 + 两端点",
          'rough_cut.review' in hr_src
          and "/host/rough-cut/apply" in hr_src
          and "/host/rough-cut/export" in hr_src)
    # 只查「对象键语法」出现 confirmed（注释里的说明文字不算）：
    # 前端一旦传 confirmed 键，后端闸门即被绕过。
    check(f"前端纪律（{repo.split(os.sep)[1]}）：请求体不传 confirmed 键（闸门在后端）",
          "confirmed:" not in hr_src
          and '"confirmed"' not in hr_src
          and "'confirmed'" not in hr_src)
shell_src = _src(os.path.join("vendor", "packages", "libtv", "src", "CanvasShell.tsx"))
check("CanvasShell 挂载 RoughCutReviewDock（壳层常驻订阅）",
      "import RoughCutReviewDock" in shell_src and "<RoughCutReviewDock />" in shell_src)

# ---------------------------------------------------------------------------
print("=" * 74)
print(f"结果：{len(PASS)} 通过 / {len(FAIL)} 失败")
if FAIL:
    print("失败项：")
    for name in FAIL:
        print(f"  ❌ {name}")
    sys.exit(1)
print("ROUGH_CUT 守卫全绿 ✅")
