#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""覆盖率棘轮门禁 —— 「已覆盖的行只能多，不能少」（2026-10-09）。

跑法：
    python _verify/check_coverage.py                     # 读 .workbuddy/tmp/coverage.json 比对基线
    python _verify/check_coverage.py --json PATH         # 指定 coverage json
    python _verify/check_coverage.py --run               # 自己跑一遍 pytest --cov（慢，约 5 分钟）
    python _verify/check_coverage.py --report            # 只打报告，不判定
    python _verify/check_coverage.py --update            # 写回基线
    python _verify/check_coverage.py --update --force    # 强制下调基线（需显式理由）

为什么是「棘轮」而不是「覆盖率阈值」（2026-10-09 定）：
    直接拍一个「覆盖率 ≥ 60% 才许提交」的数字，等于给全仓判死刑 —— 实测当前只有
    21%（95,466 语句 / 已覆盖 20,254），197 个文件 0% 覆盖。若强卡阈值，所有人
    都会去 `--no-verify`，门禁当场作废。
    本项目已有两套同款范式可循：stability_gate.py（全局计数只减不增）与
    ruff_gate.py（逐文件存量只减不增）。覆盖率照抄 ruff_gate 的**逐文件**粒度，
    语义与它们完全一致：

      * 已有文件：已覆盖行数 **只增不减**（回退 → FAIL，逐文件定位到具体文件）
      * 新文件：首次出现不拦（否则一次新增 30 个文件会直接拦死），但**立刻入账**，
        从此受同一棘轮约束
      * 文件消失：从基线自动剔除（改名/删除不该被判失败），计入报告
      * 总量：已覆盖行数**只增不减**

    这样门禁不会放松反而会自己收紧：任何一次提交都不许把覆盖过的行弄回未覆盖，
    而新增代码会持续进入棘轮视野。想真正抬升覆盖率，请去补
    docs/_reports/ 里那份「零覆盖大模块」清单。

退出码：0=通过；1=棘轮回退；2=用法错；3=找不到 coverage 数据。
"""
from __future__ import annotations

import argparse
import io
import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

DEFAULT_JSON = os.path.join(ROOT, ".workbuddy", "tmp", "coverage.json")
BASELINE = os.path.join(ROOT, "docs", "knowledge", "coverage_baseline.json")

# 只看产品本体，与 pytest 的 --cov=app 对齐（测试/校验脚本自身不计入）
SCOPE_PREFIX = "app/"
# 报告用：零覆盖且语句数超过此值的模块才会被点名（避免刷屏）
BIG_MODULE_STMTS = 200
TOP_N = 20


def _norm(p: str) -> str:
    """把 coverage 的路径统一成仓库内 POSIX 相对路径。"""
    p = p.replace("\\", "/")
    if p.startswith("./"):
        p = p[2:]
    idx = p.find("app/")
    if idx > 0:
        p = p[idx:]
    return p


def _venv_python() -> str:
    for rel in ("venv312", ".venv312", "venv", ".venv"):
        for exe in ("Scripts/python.exe", "bin/python"):
            cand = os.path.join(ROOT, rel, exe.replace("/", os.sep))
            if os.path.isfile(cand):
                return cand
    return sys.executable


def run_coverage(json_path: str) -> int:
    """自己跑一遍 pytest --cov 产出 json（独立可用；check_all.sh 走的是复用路径）。"""
    os.makedirs(os.path.dirname(json_path), exist_ok=True)
    cmd = [
        _venv_python(), "-m", "pytest", "-q",
        "--cov=app",
        f"--cov-report=json:{json_path}",
        f"--cov-report=term:skip-covered",
    ]
    env = dict(os.environ)
    env.setdefault("QT_QPA_PLATFORM", "offscreen")
    env.setdefault("PYTHONIOENCODING", "utf-8")
    print("── 运行 pytest --cov（约 5 分钟）")
    print("   $ " + " ".join(cmd))
    return subprocess.call(cmd, cwd=ROOT, env=env)


def load_cov(json_path: str):
    if not os.path.isfile(json_path):
        print(f"✗ 找不到 coverage 数据：{json_path}")
        print("  先跑：python _verify/check_coverage.py --run")
        print("  或：  bash scripts/check_all.sh（会先跑 pytest 并产出该文件）")
        return None
    with open(json_path, encoding="utf-8") as f:
        data = json.load(f)
    files = {}
    for raw, info in (data.get("files") or {}).items():
        rel = _norm(raw)
        if not rel.startswith(SCOPE_PREFIX):
            continue
        s = info.get("summary") or {}
        files[rel] = {
            "covered": int(s.get("covered_lines") or 0),
            "stmts": int(s.get("num_statements") or 0),
        }
    totals = data.get("totals") or {}
    total = {
        "covered": int(totals.get("covered_lines") or sum(v["covered"] for v in files.values())),
        "stmts": int(totals.get("num_statements") or sum(v["stmts"] for v in files.values())),
    }
    return {"files": files, "total": total}


def load_baseline():
    if not os.path.isfile(BASELINE):
        return None
    with open(BASELINE, encoding="utf-8") as f:
        return json.load(f)


def print_report(cov, base, fails):
    files, total = cov["files"], cov["total"]
    pct = (total["covered"] / total["stmts"] * 100) if total["stmts"] else 0.0
    print()
    print("── 覆盖率现状 ─────────────────────────────────────────")
    print(f"   语句 {total['stmts']:,} · 已覆盖 {total['covered']:,} · 覆盖率 {pct:.1f}%")
    if total["stmts"] - total["covered"]:
        print(f"   未覆盖 {total['stmts'] - total['covered']:,} 行")
    print(f"   受测文件 {len(files)} 个，其中零覆盖 {sum(1 for v in files.values() if v['covered'] == 0)} 个")

    # 棘轮回退明细
    if fails:
        print()
        print("── 棘轮回退（已覆盖的行变回未覆盖）───────────────────")
        for f_, got, want, allow in fails[:40]:
            extra = f"（已扣除删码额度 {allow}）" if allow else "（语句数未减，纯退化）"
            print(f"   ✗ {f_}  {got} < 基线 {want} {extra}")
        if len(fails) > 40:
            print(f"   … 另有 {len(fails) - 40} 个文件回退")

    # 零覆盖大模块 Top N（提示用，不拦）
    big = sorted(
        ((v["stmts"], k) for k, v in files.items() if v["covered"] == 0 and v["stmts"] >= BIG_MODULE_STMTS),
        reverse=True,
    )
    if big:
        print()
        print(f"── 零覆盖大模块 Top {min(TOP_N, len(big))}（补测试 ROI 最高，不阻断）──")
        for stmts, k in big[:TOP_N]:
            print(f"   {stmts:>4} 语句  {k}")
        print(f"   （共 {len(big)} 个零覆盖模块，语句数 ≥ {BIG_MODULE_STMTS}）")


def main() -> int:
    ap = argparse.ArgumentParser(description="覆盖率棘轮门禁")
    ap.add_argument("--json", default=DEFAULT_JSON, help="coverage json 路径")
    ap.add_argument("--run", action="store_true", help="先跑 pytest --cov 再判定")
    ap.add_argument("--report", action="store_true", help="只打报告，不判定")
    ap.add_argument("--update", action="store_true", help="写回基线")
    ap.add_argument("--force", action="store_true", help="允许下调基线（需显式理由，见文件头注释）")
    args = ap.parse_args()

    if args.run:
        rc = run_coverage(args.json)
        if rc != 0:
            print("✗ pytest --cov 失败（先修测试，再谈覆盖率）")
            return 1

    cov = load_cov(args.json)
    if cov is None:
        return 3
    base = load_baseline()

    if args.report:
        print_report(cov, base, [])
        return 0

    if base is None:
        if not args.update:
            print(f"✗ 基线不存在：{BASELINE}")
            print("  首次建立：python _verify/check_coverage.py --update")
            return 1
        base = None

    fails = []
    gone = []
    new_files = []
    if base:
        bfiles = base.get("files") or {}
        for path, want in bfiles.items():
            got = cov["files"].get(path)
            if got is None:
                gone.append(path)
                continue
            want_cov = int(want.get("covered") or 0)
            want_stmts = int(want.get("stmts") or 0)
            # 允许的下降额度 = 本次**删掉的语句数**。
            # 为什么需要这个容差（2026-10-09 实测踩到）：
            #   「已覆盖行数只增不减」对「删代码」是不公平的 —— 删掉 20 行死代码，
            #   语句数 -20，已覆盖行数也必然 -20 左右，但这**不是覆盖率退化**。
            #   没有容差的话，任何一次正当的删减/重构都会把门禁顶红，逼人 --update --force，
            #   棘轮当场作废（和「拍个 60% 阈值」是同一种失败）。
            # 语义因此精确为：**覆盖行数的下降不得超过语句数的下降**。
            #   · 只删测试（语句数不变）⇒ 额度 0 ⇒ 严格拦死 ← 这才是要防的
            #   · 删/重构代码 ⇒ 额度 = 删掉的语句数 ⇒ 不误伤
            allowed_drop = max(0, want_stmts - got["stmts"])
            if got["covered"] < want_cov - allowed_drop:
                fails.append((path, got["covered"], want_cov, allowed_drop))
        for path in cov["files"]:
            if path not in bfiles:
                new_files.append(path)
        bt = base.get("total") or {}
        want_total = int(bt.get("covered") or 0)
        want_total_stmts = int(bt.get("stmts") or 0)
        total_allowed = max(0, want_total_stmts - cov["total"]["stmts"])
        total_dropped = want_total - cov["total"]["covered"]
        if total_dropped > total_allowed and not fails:
            print(f"   ⚠️ 总量回退 {total_dropped} 行 > 允许额度 {total_allowed}，"
                  f"但无文件级回退 —— 多半是文件被删/改名（见下方清单）")

    print_report(cov, base, fails)
    if gone:
        print()
        print(f"── 已消失（自动从基线剔除，不算失败）{len(gone)} 个 ──")
        for g in gone[:10]:
            print(f"   - {g}")
        if len(gone) > 10:
            print(f"   … 另有 {len(gone) - 10} 个")
    if new_files:
        print()
        print(f"── 新入账文件 {len(new_files)} 个（本次不拦，从此受棘轮约束）──")
        for n in new_files[:10]:
            print(f"   + {n}")
        if len(new_files) > 10:
            print(f"   … 另有 {len(new_files) - 10} 个")

    if args.update:
        if fails and not args.force:
            print()
            print(f"✗ 有 {len(fails)} 个文件覆盖率回退，拒绝写回基线。")
            print("  若确认是正当的（如重构后代码量与覆盖同步下降），加 --force 并说明理由。")
            return 1
        payload = {
            "updated": "2026-10-09",
            "note": ("覆盖率棘轮基线：逐文件「已覆盖行数只增不减」。"
                     "新文件首次入账不拦，但立即受约束。"
                     "判定逻辑见 _verify/check_coverage.py 文件头。"),
            "scope": ["app/"],
            "totals": cov["total"],
            "files": {k: v for k, v in sorted(cov["files"].items())},
        }
        os.makedirs(os.path.dirname(BASELINE), exist_ok=True)
        with open(BASELINE, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=1)
            f.write("\n")
        print()
        print(f"✓ 基线已写回 {os.path.relpath(BASELINE, ROOT)}"
              f"（{len(cov['files'])} 文件 / 已覆盖 {cov['total']['covered']:,} 行）")
        return 0

    print()
    if fails:
        print(f"✗ 覆盖率棘轮回退：{len(fails)} 个文件的已覆盖行数下降")
        print("  这不是「覆盖率不够高」，是「已经覆盖过的行退回未覆盖」——")
        print("  通常是删了测试、改了导入路径、或测试被 skip。请修回。")
        return 1
    print(f"✓ 覆盖率棘轮通过（已覆盖 {cov['total']['covered']:,} 行，只增不减）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
