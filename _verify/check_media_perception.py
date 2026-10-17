# -*- coding: utf-8 -*-
"""Media Engine 统一感知门面守卫（§6.9 感知收拢，2026-10-18）

断言：
  ① 能力清单：wired/not_wired 诚实二值；scenes/asr/quality 在册 wired，
     face/ocr/silence/vision 如实 not_wired；list_capabilities 返回副本
  ② perceive 结构完整：文件不存在 ⇒ 全部 wired 能力如实失败且**绝不抛异常**；
     未知能力 / not_wired 能力请求都得到诚实拒绝而非静默跳过
  ③ quality 真实分发：显式分被尊重、估算维度如实标注（对齐 §8 诚实红线）
  ④ record_perception 落账：SG_GEN_TASK_STORE 隔离账本，感知只写进
     既有资产的 perception 字段（增量合并）；无资产不落账、不造假
  ⑤ 上游接口在册：gen_task_registry.record_asset 的 perception 参数
     仍存在（门面落点被静默删除时本守卫报警）

用法（项目根执行）：.venv312\\Scripts\\python.exe _verify/check_media_perception.py
退出码 0 = 通过；1 = 有漂移。
"""
from __future__ import annotations

import os
import sys
import tempfile

# 临时目录钉到项目内 .workbuddy/tmp（沙箱拦系统 Temp，同 check_gen_task_registry）
try:
    _SG_TMP = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        ".workbuddy", "tmp",
    )
    os.makedirs(_SG_TMP, exist_ok=True)
    tempfile.tempdir = _SG_TMP
except OSError:
    pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

problems = []


def _fail(msg: str) -> None:
    problems.append(msg)


# ── ① 能力清单 ────────────────────────────────────────────────────────

def check_capabilities() -> None:
    from app.core.media_perception import list_capabilities

    caps = list_capabilities()
    by_kind = {c["kind"]: c for c in caps}
    wired_expect = {"scenes", "asr", "quality"}
    not_wired_expect = {"face", "ocr", "silence", "vision"}
    for k in wired_expect:
        c = by_kind.get(k)
        if not c or c["status"] != "wired":
            _fail(f"① wired 能力缺失或状态漂移：{k}")
    for k in not_wired_expect:
        c = by_kind.get(k)
        if not c or c["status"] != "not_wired":
            _fail(f"① 未接入能力被冒充 wired：{k}（诚实红线）")
    for c in caps:
        if c["status"] not in ("wired", "not_wired"):
            _fail(f"① 非法状态值：{c['kind']}={c['status']}")
        if c["status"] == "not_wired" and not c.get("note"):
            _fail(f"① not_wired 能力未说明真实原因：{c['kind']}")
    # 返回副本：改返回值不得污染内部表
    caps[0]["status"] = "hacked"
    if list_capabilities()[0]["status"] == "hacked":
        _fail("① list_capabilities 未隔离内部表（返回了引用）")


# ── ② perceive 结构完整 + 绝不抛异常 ─────────────────────────────────

def check_perceive_structure() -> None:
    from app.core.media_perception import perceive

    r = perceive("z:/__no_such_media__.mp4")
    if r.get("file_exists") is not False:
        _fail("② 不存在文件应报 file_exists=False")
    for kind in ("scenes", "asr", "quality"):
        e = r["results"].get(kind)
        if not isinstance(e, dict) or e.get("ok") is not False:
            _fail(f"② wired 能力对不存在文件应如实失败：{kind}")
        if "文件不存在" not in (e.get("error") or ""):
            _fail(f"② 失败原因不诚实：{kind} -> {e.get('error')!r}")
    # 未知能力：诚实拒绝（不是 KeyError，也不是静默跳过）
    r2 = perceive("z:/__no_such__.mp4", ["hologram"])
    e2 = r2["results"].get("hologram")
    if not e2 or e2.get("ok") is not False or "未知能力" not in e2["error"]:
        _fail("② 未知能力未得到诚实拒绝")
    # not_wired 能力：请求即如实告知未接入
    r3 = perceive("z:/__no_such__.mp4", ["face"])
    e3 = r3["results"].get("face")
    if not e3 or e3.get("ok") is not False or "未接入" not in e3["error"]:
        _fail("③ not_wired 能力未如实告知未接入")


# ── ③ quality 真实分发（显式分被尊重 + 估算如实标注） ─────────────────

def check_quality_dispatch() -> None:
    from app.core.media_perception import perceive

    fd, tmp = tempfile.mkstemp(prefix="sg_mp_", suffix=".mp4")
    os.close(fd)  # 空占位文件；关像素分析后 quality 只吃 clip_meta
    os.environ["SHIGUANG_AESTHETIC_ANALYSIS"] = "0"
    try:
        r = perceive(tmp, ["quality"],
                    clip_meta={"id": "c1", "duration": 3.0,
                               "quality_scores": {"visual_quality": 88}})
        e = r["results"]["quality"]
        if not e["ok"]:
            _fail(f"③ quality 分发失败：{e['error']}")
            return
        data = e["data"]
        dims = set(data.get("dimensions") or {})
        expect = {"visual_quality", "narrative_highlight", "copy_match",
                  "bgm_match", "shot_duration"}
        if dims != expect:
            _fail(f"③ 五维不齐：{sorted(dims)}")
        if data.get("dimensions", {}).get("visual_quality") != 88:
            _fail("③ 显式分未被尊重（应=88）")
        est = data.get("estimated_dims") or []
        if "visual_quality" in est:
            _fail("③ 显式分维度被误标估算")
        if not est:
            _fail("③ 估算维度未如实标注（§8 诚实红线）")
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass


# ── ④ record_perception 落账（隔离账本） ─────────────────────────────

def check_record_perception() -> None:
    root = tempfile.mkdtemp(prefix="sg_mperc_store_")
    os.environ["SG_GEN_TASK_STORE"] = os.path.join(root, "gen_tasks.json")
    try:
        from app.core.gen_task_registry import get_store
        from app.core.media_perception import record_perception

        # 无资产 ⇒ 不落账、不造假
        fake = {"path": "z:/orphan.mp4", "results": {
            "scenes": {"ok": True, "data": [{"start_time": 0.0}], "error": ""}}}
        if record_perception("z:/orphan.mp4", fake) is not False:
            _fail("④ 无资产时竟落了账（造了无主记录）")

        # 有资产 ⇒ perception 增量合并；ok=False 的能力不写入
        path = "z:/media/clip_a.mp4"
        store = get_store()
        store.record_asset("ast_1", path=path, perception={"asr": ["旧转写"]})
        result = {"path": path, "results": {
            "scenes": {"ok": True, "data": [{"start_time": 0.0, "end_time": 2.0}],
                       "error": ""},
            "quality": {"ok": True, "data": {"weighted_score": 77.0}, "error": ""},
            "asr": {"ok": False, "data": None, "error": "模型不可用"},
        }}
        if record_perception(path, result) is not True:
            _fail("④ 落账应成功")
        rec = store.get_asset("ast_1") or {}
        per = rec.get("perception") or {}
        if "scenes" not in per or "quality" not in per:
            _fail(f"④ 感知未写入 AssetNode.perception：{sorted(per)}")
        if per.get("asr") != ["旧转写"]:
            _fail("④ 失败能力覆盖了既有感知（增量合并被破坏）")

        # 坏 result 输入：绝不抛异常、返回 False
        if record_perception(path, "not-a-dict") is not False:
            _fail("④ 非法 result 输入未诚实拒绝")
    finally:
        os.environ.pop("SG_GEN_TASK_STORE", None)


# ── ⑤ 上游接口在册 ───────────────────────────────────────────────────

def check_upstream_contract() -> None:
    reg = os.path.join(ROOT, "app", "core", "gen_task_registry.py")
    with open(reg, "r", encoding="utf-8") as f:
        src = f.read()
    if "perception: Optional[Dict[str, Any]] = None" not in src:
        _fail("⑤ gen_task_registry.record_asset 的 perception 参数被删/改签名"
              "（门面落点断裂）")


def main() -> int:
    check_capabilities()
    check_perceive_structure()
    check_quality_dispatch()
    check_record_perception()
    check_upstream_contract()
    if problems:
        for p in problems:
            print(f"FAIL  {p}")
        return 1
    print("PASS  Media Engine 感知门面：能力诚实二值/结构完整/quality分发/感知落账/上游在册")
    return 0


if __name__ == "__main__":
    sys.exit(main())
