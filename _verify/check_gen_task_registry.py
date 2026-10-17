# -*- coding: utf-8 -*-
"""生成任务账本守卫（§6.9-P1 正式化，2026-10-18）

断言：
  ① 幂等键：归一化同键（空白/大小写/全半角）；kind/model/size/seed/duration/
     channel 隔离；**跨进程可复现**（不许依赖内置 hash 随机化）
  ② begin 查重：活跃任务命中去重；force 绕过；终态不查重；
     seed 缺省与固定 seed 不互相命中
  ③ finish：非终态拒改；done 清 error；字段空值不覆盖已有
  ④ 持久化：JSON 往返（新实例读回一致）；坏文件自愈为空库
  ⑤ AssetNode：record_asset 增量更新；resolve_lineage clip→asset→task→节点链
  ⑥ 接线在册：canvas_server.py 的 submit 端点确实走账本查重+收尾登记，
     两个只读端点在册（防静默回退，照 GENLEDGER ⑤ 风格）
  ⑦ 反例自检：非法输入不造假记录、绝不抛异常

用法（项目根执行）：.venv312\\Scripts\\python.exe _verify/check_gen_task_registry.py
退出码 0 = 通过；1 = 有漂移。
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile

# 临时目录钉到项目内 .workbuddy/tmp（沙箱拦系统 Temp，同 check_gen_ledger）
try:
    _SG_TMP = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        if "__file__" in globals() else os.getcwd(),
        ".workbuddy", "tmp",
    )
    os.makedirs(_SG_TMP, exist_ok=True)
    tempfile.tempdir = _SG_TMP
except OSError:
    pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

PY = sys.executable
problems = []


def _fail(msg: str) -> None:
    problems.append(msg)


def _new_store(dirpath: str):
    from app.core.gen_task_registry import GenTaskStore
    return GenTaskStore(store_path=os.path.join(dirpath, "gen_tasks.json"))


# ── ① 幂等键 ──────────────────────────────────────────────────────────

def check_key() -> None:
    from app.core.gen_task_registry import idempotency_key as ik

    base = dict(kind="image", prompt="一个女孩", model="m1",
                size="1024x576", seed=42, duration=None, channel_id="c1")
    k0 = ik(base["kind"], base["prompt"], base["model"], size=base["size"],
            seed=base["seed"], duration=base["duration"], channel_id=base["channel_id"])
    # 归一化同键：空白/大小写/全半角差异不改意图
    k_same = ik("image", "一个  女孩", "M1", size="１０２４Ｘ５７６",
                seed=42, duration=None, channel_id="C1")
    if k0 != k_same:
        _fail("① 归一化未命中同键（空白/大小写/全半角应归一桶）")
    # 维度隔离：每个字段单独变化都必须换键
    mutations = [
        dict(kind="video"),
        dict(prompt="一个男孩"),
        dict(model="m2"),
        dict(size="512x512"),
        dict(seed=43),
        dict(duration=5),
        dict(channel_id="c2"),
    ]
    for m in mutations:
        p = {**base, **m}
        k = ik(p["kind"], p["prompt"], p["model"], size=p["size"],
               seed=p["seed"], duration=p["duration"], channel_id=p["channel_id"])
        if k == k0:
            _fail(f"① 维度未隔离：{m} 与原键相同")
    # seed=None 与 seed 值不互相命中
    k_none = ik("image", "一个女孩", "m1", size="1024x576",
                seed=None, duration=None, channel_id="c1")
    if k_none == k0:
        _fail("① seed 缺省与固定种子不应同键")


def check_key_cross_process() -> None:
    """跨进程稳定：不同 PYTHONHASHSEED 下键一致（禁内置 hash()）。"""
    code = (
        "import sys; sys.path.insert(0, %r)\n"
        "from app.core.gen_task_registry import idempotency_key as ik\n"
        "print(ik('image', '测试 提示', 'm', size='1x1', seed=7, duration=None, channel_id=''))\n"
    % ROOT
    )
    outs = []
    for seed_env in ("0", "12345"):
        env = dict(os.environ, PYTHONHASHSEED=seed_env)
        try:
            r = subprocess.run([PY, "-c", code], capture_output=True, text=True,
                               timeout=60, env=env, cwd=ROOT)
            outs.append(r.stdout.strip().splitlines()[-1] if r.stdout.strip() else f"ERR:{r.stderr[:120]}")
        except Exception as e:
            _fail(f"① 跨进程验证执行失败: {e}")
            return
    if len(outs) == 2 and outs[0] != outs[1]:
        _fail(f"① 键跨进程不稳定: {outs}")


# ── ② begin 查重 ──────────────────────────────────────────────────────

def check_begin_dedup() -> None:
    with tempfile.TemporaryDirectory() as d:
        store = _new_store(d)
        params = {"prompt": "p", "model": "m", "size": "1x1",
                  "seed": 1, "duration": None, "channel_id": ""}
        rec1, dup1 = store.begin("image", params)
        if dup1 or not rec1.get("task_id"):
            _fail("② 首建应新建记录且 deduped=False")
            return
        rec2, dup2 = store.begin("image", params)
        if not dup2 or rec2.get("task_id") != rec1.get("task_id"):
            _fail("② 活跃任务同键应命中去重并返回既有记录")
        # 终态不查重（重拍同参数是合法诉求）
        store.finish(rec1["task_id"], "done", result_paths=["x.png"])
        rec3, dup3 = store.begin("image", params)
        if dup3 or rec3.get("task_id") == rec1.get("task_id"):
            _fail("② 终态记录不应参与查重（重拍同参数是合法诉求）")
        # force 绕过：rec3 仍活跃，同键本会命中，force 应新建
        rec4, dup4 = store.begin("image", params, force=True)
        if dup4 or rec4.get("task_id") == rec3.get("task_id"):
            _fail("② force=True 应绕过查重新建")
        # kind 隔离
        rec5, dup5 = store.begin("video", params)
        if dup5:
            _fail("② kind 不同不应去重")


# ── ③ finish ──────────────────────────────────────────────────────────

def check_finish() -> None:
    with tempfile.TemporaryDirectory() as d:
        store = _new_store(d)
        rec, _ = store.begin("image", {"prompt": "p", "model": "m"})
        tid = rec["task_id"]
        if store.finish(tid, "running") is not None:
            _fail("③ 非终态 status 应被拒改（返回 None）")
        if store.finish("不存在的id", "done") is not None:
            _fail("③ 未知 task_id 应返回 None")
        store.finish(tid, "failed", error="上游超时")
        r = store.get_task(tid)
        if not r or r.get("status") != "failed" or r.get("error") != "上游超时":
            _fail("③ failed 收尾字段未落账")
            return
        # 后写覆盖：done 清 error；空值不覆盖已有 result_paths
        store.finish(tid, "done", result_paths=["a.png"])
        r2 = store.get_task(tid)
        if r2.get("error"):
            _fail("③ done 应清空 error")
        store.finish(tid, "done")
        r3 = store.get_task(tid)
        if r3.get("result_paths") != ["a.png"]:
            _fail("③ finish 空参数不应覆盖已有 result_paths")


# ── ④ 持久化往返 + 坏文件自愈 ─────────────────────────────────────────

def check_persist() -> None:
    from app.core.gen_task_registry import GenTaskStore
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "gen_tasks.json")
        s1 = GenTaskStore(store_path=path)
        rec, _ = s1.begin("image", {"prompt": "往返", "model": "m", "seed": 9})
        s1.finish(rec["task_id"], "done", result_paths=["x.png"])
        s1.record_asset("a1", path="out/x.png", kind="image",
                        generation_task_id=rec["task_id"], canvas_node_id="n1")
        if not os.path.exists(path):
            _fail("④ 账本未落盘")
            return
        s2 = GenTaskStore(store_path=path)
        r2 = s2.get_task(rec["task_id"])
        a2 = s2.get_asset("a1")
        if not r2 or r2.get("prompt") != "往返" or r2.get("status") != "done":
            _fail("④ 新实例读回任务不一致")
        if not a2 or a2.get("generation_task_id") != rec["task_id"]:
            _fail("④ 新实例读回资产不一致")
        # 坏 JSON 自愈
        with open(path, "w", encoding="utf-8") as f:
            f.write("{broken json!!!")
        s3 = GenTaskStore(store_path=path)
        if s3.get_task(rec["task_id"]) is not None:
            _fail("④ 坏文件应自愈为空库（而不是崩溃或读脏数据）")
        try:
            rec3, _ = s3.begin("image", {"prompt": "自愈后仍可写", "model": "m"})
            if not rec3.get("task_id"):
                _fail("④ 自愈后 begin 应正常新建")
        except Exception as e:
            _fail(f"④ 自愈后写入抛异常: {e}")


# ── ⑤ AssetNode + resolve_lineage ─────────────────────────────────────

def check_asset_lineage() -> None:
    with tempfile.TemporaryDirectory() as d:
        store = _new_store(d)
        rec, _ = store.begin("video", {"prompt": "链", "model": "m", "seed": 3})
        tid = rec["task_id"]
        store.set_job_id(tid, "job123")
        store.finish(tid, "done", result_paths=["v.mp4"], canvas_node_id="node-9")
        a = store.record_asset("ast-1", path="out/v.mp4", kind="video",
                               generation_task_id=tid, canvas_node_id="node-9")
        if not a or a.get("asset_id") != "ast-1":
            _fail("⑤ record_asset 未返回记录")
            return
        # 增量更新：空值不覆盖
        a2 = store.record_asset("ast-1", path="out/v.mp4", quality_score=0.8,
                                timeline_clip_ids=["c1"])
        if a2.get("generation_task_id") != tid or a2.get("quality_score") != 0.8:
            _fail("⑤ 增量更新丢失既有字段")
        a3 = store.record_asset("ast-1", path="out/v.mp4",
                                timeline_clip_ids=["c2"])
        if a3.get("timeline_clip_ids") != ["c1", "c2"]:
            _fail("⑤ timeline_clip_ids 应追加去重")
        # 链查询：clip 带 asset_id
        lin = store.resolve_lineage({"id": "c1", "asset_id": "ast-1"})
        if not lin["asset"] or not lin["task"] or lin["task"].get("task_id") != tid:
            _fail("⑤ resolve_lineage 按 asset_id 未走通 clip→asset→task")
        if lin.get("canvas_node_id") != "node-9":
            _fail("⑤ resolve_lineage 未解析出 canvas_node_id")
        # 链查询：clip 只有 path（兜底反查）
        lin2 = store.resolve_lineage({"id": "c9", "path": "out\\v.mp4"})
        if not lin2["asset"]:
            _fail("⑤ 按 path 反查资产失败（应容忍路径分隔符差异）")
        # 链查询：clip 只有 canvas_node_id（任务兜底）
        lin3 = store.resolve_lineage({"id": "c8", "canvas_node_id": "node-9"})
        if not lin3["task"] or lin3["task"].get("task_id") != tid:
            _fail("⑤ 按 canvas_node_id 反查任务失败")
        # 诚实：无关联 clip ⇒ 全空
        lin4 = store.resolve_lineage({"id": "lonely", "path": "no/such/file.mp4"})
        if lin4["asset"] or lin4["task"]:
            _fail("⑤ 无关联 clip 不应造出链记录")


# ── ⑥ 接线在册 ────────────────────────────────────────────────────────

def check_wiring() -> None:
    server = os.path.join(ROOT, "app", "core", "canvas_server.py")
    try:
        with open(server, "r", encoding="utf-8") as f:
            src = f.read()
    except OSError as e:
        _fail(f"⑥ 无法读取 canvas_server.py: {e}")
        return
    for needle, label in [
        ("gen_task_registry", "顶部 import gen_task_registry"),
        ("_gen_task_reg.get_store()", "submit 端点取账本单例"),
        ("_store.begin(kind", "submit 端点幂等查重"),
        ("_store.finish(", "任务收尾登记"),
        ('_route_get("/host/gen-task")', "只读端点 /host/gen-task"),
        ('_route_get("/host/asset-node")', "只读端点 /host/asset-node"),
    ]:
        if needle not in src:
            _fail(f"⑥ canvas_server.py 缺接线：{label}")


# ── ⑦ 反例自检 ────────────────────────────────────────────────────────

def check_negative() -> None:
    from app.core.gen_task_registry import extract_result_paths, idempotency_key
    if extract_result_paths(None) != []:
        _fail("⑦ extract_result_paths 对非 dict 应返回空列表")
    if extract_result_paths({"ok": True, "image_data_url": "data:..."}) != []:
        _fail("⑦ data URL 不应被当成落盘路径（诚实记账）")
    if extract_result_paths({"path": "a.png", "paths": ["b.png", "a.png"]}) != ["a.png", "b.png"]:
        _fail("⑦ result_paths 应去重保序")
    with tempfile.TemporaryDirectory() as d:
        store = _new_store(d)
        if store.record_asset("", path="x") is not None:
            _fail("⑦ 空 asset_id 应拒绝（不造无主记录）")
        if store.record_asset("a", path="") is not None:
            _fail("⑦ 空 path 应拒绝")
        # begin 收到垃圾参数不抛
        try:
            rec, _ = store.begin("", None)  # type: ignore[arg-type]
            if not rec.get("task_id"):
                _fail("⑦ begin 垃圾参数也应返回可用记录")
        except Exception as e:
            _fail(f"⑦ begin 对垃圾参数抛异常: {e}")
    # 键对 None prompt 不抛
    try:
        idempotency_key("image", None, None)  # type: ignore[arg-type]
    except Exception as e:
        _fail(f"⑦ idempotency_key 对 None 抛异常: {e}")


def main() -> int:
    check_key()
    check_key_cross_process()
    check_begin_dedup()
    check_finish()
    check_persist()
    check_asset_lineage()
    check_wiring()
    check_negative()
    if problems:
        print("✗ 生成任务账本守卫发现漂移：")
        for p in problems:
            print("  -", p)
        return 1
    print("✓ 生成任务账本守卫全部通过（键/查重/收尾/持久化/资产链/接线/反例）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
