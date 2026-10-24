# -*- coding: utf-8 -*-
"""抽卡账本守卫（生成抽卡闭环 P3，方案 §四 P3 验收行）

断言（方案裁定三条 + 两条工程纪律）：
  ① **账本可加载**：写→新实例读回，mean/best_seed 一致；坏 JSON 自愈为空库
  ② **指纹稳定**：归一化同键（空白/大小写/全半角）；kind/model/size 隔离；
     跨进程可复现（不许依赖 Python 内置 hash 随机化）
  ③ **推荐不返回过期桶**：last_used 超期的桶不参与推荐；全过期 → None
  ④ 红线：proxy 分只进 draw_book / quality_prior 的 proxy 桶，
     **route_mean 不消费 proxy**（人工真值桶零污染）
  ⑤ 接线在册：canvas_aigc 生成收尾确实调用了 feed_draw_ledger（防有人回退掉）

用法（项目根执行）：.venv312\\Scripts\\python.exe _verify/check_gen_ledger.py
退出码 0 = 通过；1 = 有漂移。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time

# 临时目录钉到项目内 .workbuddy/tmp（2026-09-28）：沙箱拦截系统 Temp 写入 ⇒
# tempfile.gettempdir() 回退到 cwd（项目根），直接单跑本脚本会把临时目录漏进仓库根。
# 规范入口 run_all_checks 已用 TMPDIR 传递；此处覆盖「直接单跑」路径。
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


# ── ① 账本可加载（持久化往返 + 坏文件自愈）────────────────────────────────


def check_roundtrip() -> None:
    from app.core.ai.draw_book import DrawBookStore, fingerprint

    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "draw_book.json")
        s1 = DrawBookStore(store_path=path)
        s1.record_draw("守卫用例", "m1", 0.8, seed=12345, size="1024x576")
        if not os.path.exists(path):
            _fail("① 账本未落盘（record_draw 后文件不存在）")
            return
        try:
            raw = json.load(open(path, encoding="utf-8"))
        except Exception as e:
            _fail(f"① 落盘 JSON 不可解析: {e}")
            return
        key = fingerprint("守卫用例", "m1", size="1024x576")
        if key not in raw:
            _fail("① 落盘 JSON 里找不到该指纹桶（键算法与写入不一致？）")
            return

        s2 = DrawBookStore(store_path=path)
        rec = s2.recommend("守卫用例", "m1", size="1024x576")
        if not rec:
            _fail("① 新实例读回后 recommend 返回 None（持久化往返断了）")
            return
        if rec["best_seed"] != 12345:
            _fail(f"① best_seed 往返失真：期望 12345，实得 {rec['best_seed']}")
        if abs(float(rec["mean"]) - 0.8) > 1e-9:
            _fail(f"① mean 往返失真：期望 0.8，实得 {rec['mean']}")


def check_corrupt_file_self_heals() -> None:
    from app.core.ai.draw_book import DrawBookStore

    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "draw_book.json")
        with open(path, "w", encoding="utf-8") as f:
            f.write("{ 这不是 JSON")
        s = DrawBookStore(store_path=path)
        if s.recommend("p", "m") is not None:
            _fail("① 坏账本文件应视为空库（recommend 必须返回 None）")
        s.record_draw("自愈", "m1", 0.5)
        if s.recommend("自愈", "m1") is None:
            _fail("① 坏账本文件未自愈（写一次后应可正常读）")


# ── ② 指纹稳定 ─────────────────────────────────────────────────────────────


def check_fingerprint_stable() -> None:
    from app.core.ai.draw_book import fingerprint

    cases = [
        ("一个 女孩，站在 雨中", "FLUX.1", "1024x576"),      # 半角空格 + 全角逗号
        ("一个女孩，站在雨中", "flux.1", "1024X576"),          # 大小写
        ("一个\u3000女孩，站在雨中", "FLUX.1", "1024x576"),    # 全角空格 U+3000
        ("一个女孩,站在雨中", "FLUX.1", "1024x576"),           # 半角逗号（NFKC 统一）
    ]
    keys = {fingerprint(p, m, size=s) for p, m, s in cases}
    if len(keys) != 1:
        _fail(f"② 归一化失败：四个等价提示词得到 {len(keys)} 个不同指纹（应同键）")

    base = fingerprint("女孩", "m1", size="1024x576", kind="image")
    if base == fingerprint("女孩", "m1", size="1024x576", kind="video"):
        _fail("② kind 未入指纹（图/视频会串桶）")
    if base == fingerprint("女孩", "m1", size="768x768", kind="image"):
        _fail("② size 未入指纹（不同尺寸会串桶）")
    if base == fingerprint("女孩", "m2", size="1024x576", kind="image"):
        _fail("② model 未入指纹（不同模型会串桶）")
    if len(base) != 16:
        _fail(f"② 指纹长度应为 16，实得 {len(base)}")

    # 跨进程稳定性：另起解释器算同一输入的指纹（防误用内置 hash() 的随机化）
    code = (
        "import sys; sys.path.insert(0, r'%s');"
        "from app.core.ai.draw_book import fingerprint;"
        "print(fingerprint('女孩', 'm1', size='1024x576'))" % ROOT
    )
    try:
        out = subprocess.run([PY, "-c", code], capture_output=True, text=True,
                             timeout=90, cwd=ROOT)
        other = (out.stdout or "").strip().splitlines()[-1] if out.stdout else ""
        if other != base:
            _fail(f"② 指纹跨进程不稳定：本进程 {base} vs 子进程 {other}"
                  "（是否误用了内置 hash()？）")
    except Exception as e:
        _fail(f"② 跨进程指纹校验无法完成: {e}")


# ── ③ 推荐不返回过期桶 ─────────────────────────────────────────────────────


def check_stale_bucket_not_recommended() -> None:
    from app.core.ai.draw_book import DrawBookStore, fingerprint

    with tempfile.TemporaryDirectory() as d:
        s = DrawBookStore(store_path=os.path.join(d, "db.json"))
        s.record_draw("过期用例", "m1", 0.95, seed=7, size="1024x576")
        key = fingerprint("过期用例", "m1", size="1024x576")
        # 把 last_used 拨回 90 天前（超过默认 60 天新鲜度）
        s._buckets[key]["last_used"] = time.time() - 90 * 86400
        if s.recommend("过期用例", "m1", size="1024x576") is not None:
            _fail("③ 过期桶（90 天前）仍被推荐了——会把人推向不成立的参数组合")
        # 关掉新鲜度检查可回看历史（调试通道仍在）
        if s.recommend("过期用例", "m1", size="1024x576",
                       max_age_days=0) is None:
            _fail("③ max_age_days=0（关闭检查）时应能查到历史桶")
        # 新鲜桶照常推荐
        s.record_draw("新鲜用例", "m1", 0.6, seed=9, size="1024x576")
        if s.recommend("新鲜用例", "m1", size="1024x576") is None:
            _fail("③ 新鲜桶被误判为过期")


# ── ④ 红线：proxy 桶隔离 ───────────────────────────────────────────────────


def check_proxy_bucket_isolated() -> None:
    from app.core.ai.quality_prior import QualityPriorStore

    with tempfile.TemporaryDirectory() as d:
        st = QualityPriorStore(store_path=os.path.join(d, "qp.json"))
        st.record_outcome("guard_ch", True, quality=0.99, kind="proxy")
        if st.route_mean("guard_ch") != 0.5:
            _fail("④ route_mean 消费了 proxy 桶（AI 代理分冒充真值 = 破红线）")
        if [k for k in st.summary() if k.endswith("::quality")]:
            _fail("④ quality 真值桶被非人工通道写入")
        st.record_outcome("guard_ch", True, quality=0.9, kind="quality")
        if abs(st.route_mean("guard_ch") - 0.9) > 1e-9:
            _fail("④ 人工真值（quality 桶）未能接管路由")


# ── ⑤ 接线在册（防回退）────────────────────────────────────────────────────


def check_wiring_present() -> None:
    aigc = open(os.path.join(ROOT, "app", "core", "canvas_aigc.py"),
                encoding="utf-8").read()
    if "feed_draw_ledger" not in aigc:
        _fail("⑤ canvas_aigc 生成收尾未调用 feed_draw_ledger（P1/P2 接线被回退？）")
    critic = open(os.path.join(ROOT, "app", "core", "ai", "gen_critic.py"),
                  encoding="utf-8").read()
    if "is_proxy" not in critic:
        _fail("⑤ gen_critic 丢失 is_proxy 标注（破红线）")
    # P4：坏区检测必须用格级「死区」判据（用整图 std 判据会把低对比的真实区域
    # 误判成坏区 ⇒ 每次体检都"查出"一堆坏区、白花钱）
    if "_dead_tile_score" not in critic:
        _fail("⑤ gen_critic 丢失格级死区判据 _dead_tile_score（P4 检测会退化成误判）")
    routes = open(os.path.join(ROOT, "app", "core", "canvas_routes_post.py"),
                  encoding="utf-8").read()
    if "/host/repair-image" not in routes:
        _fail("⑤ /host/repair-image 端点缺失（P4 局部重绘无调用入口 = 死代码）")
    ledger = open(os.path.join(ROOT, "app", "core", "ai", "draw_ledger.py"),
                  encoding="utf-8").read()
    if "repair_plan" not in ledger:
        _fail("⑤ 生成结果未回传 repair_plan（坏区体检报告）")


def check_best_of_n_orchestration() -> None:
    """⑥ 刀 A2（2026-10-05）：抽卡选优编排的**不重复记账**纪律 + 上限锁。

    每张候选在生成收尾已由 feed_draw_ledger 入账；编排层若再入一次，
    同一张图会被计成两笔样本 ⇒ 污染 EMA 与 best_seed 竞争（隐蔽且难查）。
    因此这里做**源码级**锁定（去掉注释与 docstring 后不得出现入账调用）。
    """
    import re as _re

    path = os.path.join(ROOT, "app", "core", "ai", "draw_orchestrator.py")
    if not os.path.isfile(path):
        _fail("⑥ 抽卡选优编排 draw_orchestrator.py 缺失（刀 A2 未接线）")
        return
    src = open(path, encoding="utf-8").read()
    body = _re.sub(r"^\s*#.*$", "", src, flags=_re.M)
    body = _re.sub(r'"""[\s\S]*?"""', "", body)
    if "feed_draw_ledger(" in body:
        _fail("⑥ 编排层调用了 feed_draw_ledger ⇒ 重复记账（生成收尾已入账）")
    if "record_draw(" in body:
        _fail("⑥ 编排层调用了 record_draw ⇒ 重复记账（污染 EMA）")
    if "MAX_N = 6" not in src:
        _fail("⑥ 单次张数上限 MAX_N 被改（每张都是真实云端额度，不得放开）")
    if "is_proxy" not in src:
        _fail("⑥ 编排层丢失 is_proxy 标注（破「代理分不冒充真值」红线）")
    cat = open(os.path.join(ROOT, "app", "core", "agent_capability_catalog.py"),
               encoding="utf-8").read()
    for cid in ("canvas.best_of_draw", "canvas.repair_image"):
        if f'"{cid}"' not in cat:
            _fail(f"⑥ 能力目录缺 {cid}（Agent 侧调不到）")
    handlers = open(os.path.join(ROOT, "app", "core", "capability_handlers.py"),
                    encoding="utf-8").read()
    for name in ("def best_of_draw", "def repair_image"):
        if name not in handlers:
            _fail(f"⑥ handler 缺 {name}（能力声明了但没人接）")


def main() -> int:
    print("=" * 62)
    print("抽卡账本守卫（Scheme §四 P3）")
    print("=" * 62)
    for fn in (check_roundtrip, check_corrupt_file_self_heals,
               check_fingerprint_stable, check_stale_bucket_not_recommended,
               check_proxy_bucket_isolated, check_wiring_present,
               check_best_of_n_orchestration):
        try:
            fn()
        except Exception as e:  # 守卫脚本自身异常也算失败，不静默
            _fail(f"{fn.__name__} 抛异常: {type(e).__name__}: {e}")

    if problems:
        print("✗ 失败项：")
        for p in problems:
            print(f"  - {p}")
        return 1
    print("OK 抽卡账本：往返/指纹/新鲜度/桶位隔离/接线/选优编排 全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
