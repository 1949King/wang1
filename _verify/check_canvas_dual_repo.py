# -*- coding: utf-8 -*-
"""回归：画布单一真源防漂卡点（P0-1 Phase 3，2026-10-18 重写）。

背景：
  旧版守卫比对「主库 shiguang-canvas ↔ 副库 AI-Canvas-tauri/src/libtv 副本」的
  MD5 漂移。P0-1 抽包后画布真源唯一存在于 vendor/packages/libtv（@shiguang/libtv），
  两宿主以 workspace 依赖引用、副本已删除 ⇒ 比对对象不复存在，守卫升级为
  「防止副本以任何形式复活」+「接线在册」+「全量构建门禁」。

检查三组：
  [1] 禁宿主 libtv 源码副本：
      - 宿主 src/libtv/ 目录不得存在；
      - 宿主 src 下任何 .ts/.tsx 与包内 src 文件**字节一致**（散落的复制粘贴）⇒ FAIL
        （vite-env.d.ts 属宿主壳标配，白名单放行）。
  [2] 接线在册：
      - 两宿主 package.json 必须依赖 "@shiguang/libtv": "workspace:*"；
      - 宿主源码不得再出现 './libtv/ 或 '../libtv/ 相对导入；
      - pnpm-workspace.yaml members 必须含 packages/libtv + shiguang-canvas + AI-Canvas-tauri。
  [3] 全量构建门禁（默认跑，--no-build 跳过）：
      - web 宿主 pnpm --filter shiguang-canvas run build；
      - tauri 宿主 pnpm --filter AI-Canvas-tauri exec vite build
        （绕开其 build 脚本里的 tsc -b 存量 4 错=§2c.5 基线，非本项职责）；
      - node/pnpm/node_modules 缺失时显式跳过并说明（与 precommit ⑦ 的 CI 跳过同纪律）。

用法：
    python _verify/check_canvas_dual_repo.py            # 静态 + 构建
    python _verify/check_canvas_dual_repo.py --no-build  # 仅静态（precommit 用，快）
"""
from __future__ import annotations

import argparse
import hashlib
import io
import os
import re
import shutil
import subprocess
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

PKG_SRC_REL = os.path.join("vendor", "packages", "libtv", "src")
HOSTS = {
    "shiguang-canvas": os.path.join("vendor", "shiguang-canvas"),
    "AI-Canvas-tauri": os.path.join("vendor", "AI-Canvas-tauri"),
}
# 宿主壳标配文件：与包内容撞车不算「副本复活」
FINGERPRINT_ALLOW = {"vite-env.d.ts"}
# 相对导入 libtv 副本路径（真源只允许经 @shiguang/libtv 包名引用）
REL_LIBTV_IMPORT_RE = re.compile(r"""from\s+["']\.\.?/[^"']*libtv/""")


def _walk_ts(root: str) -> dict:
    """relpath(以 / 分隔) -> 绝对路径，只收 .ts/.tsx，跳过 node_modules/dist。"""
    out = {}
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in ("node_modules", "dist")]
        for f in filenames:
            if f.endswith((".ts", ".tsx")):
                p = os.path.join(dirpath, f)
                out[os.path.relpath(p, root).replace("\\", "/")] = p
    return out


def _md5(path: str) -> str:
    with open(path, "rb") as fh:
        return hashlib.md5(fh.read()).hexdigest()


def _check_no_copies(failures: list) -> None:
    pkg_src = os.path.join(ROOT, PKG_SRC_REL)
    if not os.path.isdir(pkg_src):
        failures.append(f"画布真源包目录不存在：{PKG_SRC_REL}")
        print(f"  ✗ {PKG_SRC_REL} 不存在")
        return
    pkg_hashes = {}
    for rel, p in _walk_ts(pkg_src).items():
        pkg_hashes.setdefault(_md5(p), rel)
    print(f"  · 包真源 {len(pkg_hashes)} 个内容指纹")

    for host, host_rel in HOSTS.items():
        # 目录级：src/libtv 不得复活
        sub_libtv = os.path.join(ROOT, host_rel, "src", "libtv")
        if os.path.isdir(sub_libtv):
            failures.append(f"{host}: src/libtv/ 副本目录复活（P0-1 已抽包，禁止宿主持有副本）")
            print(f"  ✗ {host}: src/libtv/ 目录存在")
            continue
        # 内容级：散落的逐字节复制
        src_dir = os.path.join(ROOT, host_rel, "src")
        if not os.path.isdir(src_dir):
            continue
        for rel, p in sorted(_walk_ts(src_dir).items()):
            if os.path.basename(p) in FINGERPRINT_ALLOW:
                continue
            hit = pkg_hashes.get(_md5(p))
            if hit:
                failures.append(f"{host}: {rel} 与包内 {hit} 字节一致（源码副本复活）")
                print(f"  ✗ {host}: {rel} == 包内 {hit}")
    if not failures:
        print("  ✓ 两宿主无 libtv 源码副本（目录级 + 内容级）")


def _check_wiring(failures: list) -> None:
    import json

    for host, host_rel in HOSTS.items():
        pj = os.path.join(ROOT, host_rel, "package.json")
        if not os.path.isfile(pj):
            failures.append(f"{host}: package.json 缺失")
            continue
        deps = json.load(open(pj, encoding="utf-8")).get("dependencies", {})
        if deps.get("@shiguang/libtv") != "workspace:*":
            failures.append(f'{host}: 未依赖 "@shiguang/libtv": "workspace:*"（实到 {deps.get("@shiguang/libtv")}）')
            print(f"  ✗ {host}: 包依赖接线缺失")
        else:
            print(f"  ✓ {host}: @shiguang/libtv workspace:* 在册")

    for host, host_rel in HOSTS.items():
        src_dir = os.path.join(ROOT, host_rel, "src")
        if not os.path.isdir(src_dir):
            continue
        for rel, p in sorted(_walk_ts(src_dir).items()):
            body = open(p, encoding="utf-8", errors="replace").read()
            if REL_LIBTV_IMPORT_RE.search(body):
                failures.append(f"{host}: {rel} 仍用相对路径导入 libtv 副本（应改 @shiguang/libtv/*）")
                print(f"  ✗ {host}: {rel} 相对导入 libtv/")

    ws = os.path.join(ROOT, "vendor", "pnpm-workspace.yaml")
    if not os.path.isfile(ws):
        failures.append("vendor/pnpm-workspace.yaml 不存在")
    else:
        body = open(ws, encoding="utf-8").read()
        for member in ("packages/libtv", "shiguang-canvas", "AI-Canvas-tauri"):
            if member not in body:
                failures.append(f"pnpm-workspace.yaml members 缺 {member}")
            else:
                print(f"  ✓ workspace members 含 {member}")


def _check_builds(failures: list) -> None:
    node = shutil.which("node")
    pnpm = shutil.which("pnpm")
    if not node or not pnpm:
        print("  ⚠️ 未找到 node/pnpm，跳过构建门禁（不阻断；CI 由 frontend job 覆盖）")
        return
    if not os.path.isdir(os.path.join(ROOT, "vendor", "node_modules", ".pnpm")):
        print("  ⚠️ vendor/node_modules 未安装，跳过构建门禁（先 pnpm install）")
        return
    env = os.environ.copy()
    env["COREPACK_ENABLE_DOWNLOAD_PROMPT"] = "0"
    vendor_dir = os.path.join(ROOT, "vendor")
    cmds = [
        # 🔴 2026-10-25 定案：**必须构建到独立 outDir**，不得让门禁碰宿主 dist。
        # 这两条 build 默认 emptyOutDir=true 会清空 vendor/shiguang-canvas/dist；
        # `run_all_checks.py` 默认执行本项 ⇒ 画布正在运行时（:3011 有监听）跑一次门禁，
        # 就在用户眼皮底下把产物抽走 ⇒ 页面所有 hashed chunk 404 ⇒ App 动态 import 抛错
        # ⇒ 整页崩溃 ⇒ 宿主报「画布进程已退出」。这才是「运行期 dist 被搬走」的真凶
        # （此前误判为外部构建进程/人为 mv；dist 消失只是症状，本脚本才是原因）。
        # 构建到 dist.check 还有副作用好处：目录不存在时 emptyDir 无需删除任何文件，
        # 顺带绕开沙箱 safe-delete 对 rmSync 的拦截（该拦截曾让本项长期假失败）。
        ("web 宿主 vite build",
         "pnpm --filter shiguang-canvas exec vite build --outDir dist.check --emptyOutDir"),
        # tauri 的 build 脚本含 tsc -b（存量 4 错=§2c.5 基线），构建门禁只验打包链路
        # 2026-10-19 修：filter 曾写成大写 AI-Canvas-tauri，而包名是小写 ai-canvas-tauri
        # ⇒ pnpm「No projects matched」但退出码 0 ⇒ 本项长期空跑假绿（门禁摆设）。
        # 修后首次真跑即暴露 safe-delete 环境问题（见 CHANGELOG 2026-10-19 条目）。
        ("tauri 宿主 vite build",
         "pnpm --filter ai-canvas-tauri exec vite build --outDir dist.check --emptyOutDir"),
    ]
    for label, cmd in cmds:
        r = subprocess.run(cmd, cwd=vendor_dir, env=env, shell=True,
                           capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=600)
        if r.returncode != 0:
            tail = (r.stdout or "") + (r.stderr or "")
            print(f"  ✗ {label} 失败（尾部）：")
            print("\n".join(tail.strip().splitlines()[-8:]))
            failures.append(f"构建门禁失败：{label}")
        else:
            print(f"  ✓ {label}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-build", action="store_true",
                    help="跳过 [3] 全量构建门禁（precommit 增量模式用）")
    args = ap.parse_args()

    failures: list = []

    print("[1] 禁宿主 libtv 源码副本（目录级 + 内容指纹级）")
    _check_no_copies(failures)

    print("\n[2] 接线在册（workspace 依赖 / 无相对副本导入 / members）")
    _check_wiring(failures)

    print("\n[3] 全量构建门禁（两宿主 vite build）")
    if args.no_build:
        print("  · --no-build 跳过（全量门禁 run_all_checks 默认执行）")
    else:
        _check_builds(failures)

    print()
    if failures:
        print(f"✗ 画布单一真源防漂失败 {len(failures)} 项：")
        for f in failures:
            print("   -", f)
        return 1
    print("OK 画布单一真源防漂卡点全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
