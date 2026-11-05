# -*- coding: utf-8 -*-
"""一键出包：PyInstaller → 装入 AI 内核 → 自检 → （可选）NSIS 安装包。

为什么需要这个脚本
==================
发布版此前有两处「靠人手记」的步骤，一漏就出事：

  1. **AI 内核**（``dist/拾光剪影/runtime/``）不是 PyInstaller 产物，必须构建后
     再拷进去。而 PyInstaller 每次 ``--noconfirm`` 都会**清空** ``dist/拾光剪影``，
     所以这一步必须放在打包之后 —— 手动做必然某次会忘，忘了的产物就是
     「能剪片子、不会生图」的残废版。
     原因见 ``app/core/runtime_pack.py``：torch 进不了 PyInstaller（0xC0000005）。

  2. **自检**（``拾光剪影.exe --selftest``）必须在出安装包之前跑。它是
     「打包后是否包含所有模块功能」这条约束的唯一机器验证；靠人点界面验证
     AI 功能，成本高到不会有人真做。

用法::

    .venv312\\Scripts\\python.exe scripts\\build_release.py
    .venv312\\Scripts\\python.exe scripts\\build_release.py --skip-pyinstaller
    .venv312\\Scripts\\python.exe scripts\\build_release.py --installer
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
SPEC = os.path.join(ROOT, "app", "ai_video_editor_local.spec")
DIST = os.path.join(ROOT, "dist", "拾光剪影")
EXE = os.path.join(DIST, "拾光剪影.exe")
RUNTIME_SRC = os.path.join(ROOT, "build", "runtime_pack")
RUNTIME_DST = os.path.join(DIST, "runtime")
NSI = os.path.join(ROOT, "scripts", "installer.nsi")
SITE_PACKAGES = os.path.join(ROOT, ".venv312", "Lib", "site-packages")

# 打包期把 torch 目录临时改名，躲开 PyInstaller 的收集崩溃。
#
# 为什么必须这么做（实测，不是猜）：
#   PyInstaller 的 find_binary_dependencies() 会在隔离子进程里把「已收集的包」
#   逐个 import 一遍来枚举原生 DLL。那个子进程里 PyQt6 先被 import；随后
#   scipy 的 scipy._lib.array_api_compat.torch 会反向 import torch ——
#   而 **PyQt6 + torch 同进程必触发原生段错误**（实测 exit 139 /
#   0xC0000005，Python 层无栈，本项目 app/core/interchange/_otio_worker.py
#   拆子进程也是同一类问题）。
#   报错会伪装成 SubprocessDiedError: crashed while importing package 'gguf'，
#   因为崩的是同一条依赖链，报的包名跟真凶无关 —— 极难认。
#
# 为什么屏蔽是安全的：产物本来就不含 torch（spec 的 excludes 有它），
#   torch 由 dist/拾光剪影/runtime/ 在运行时供给（app/core/runtime_pack.py）。
#   打包期它根本不参与任何事，只在子进程里被"顺手"import 了一下。
DISABLED_SUFFIX = "._packaging_disabled"


def log(msg: str) -> None:
    print(f"[build] {msg}", flush=True)


def shield_torch() -> tuple[str, str] | None:
    """把 torch 目录临时改名，使打包子进程 import 不到它。返回 (原路径, 现路径)。"""
    src = os.path.join(SITE_PACKAGES, "torch")
    dst = src + DISABLED_SUFFIX
    if not os.path.isdir(src):
        if os.path.isdir(dst):
            raise SystemExit(
                f"发现上次打包残留的屏蔽：{dst}\n"
                f"先把它改回 torch 再重试（否则虚拟环境是坏的）"
            )
        return None
    if os.path.isdir(dst):
        raise SystemExit(f"{dst} 已存在，拒绝操作")
    os.rename(src, dst)  # 同卷改名，瞬时
    return src, dst


def unshield_torch(pair) -> None:
    if not pair:
        return
    src, dst = pair
    if os.path.isdir(dst):
        os.rename(dst, src)


def run_pyinstaller() -> None:
    log("① PyInstaller 打包（torch 栈仍在 excludes，由 runtime/ 供给）…")
    pyi = os.path.join(ROOT, ".venv312", "Scripts", "pyinstaller.exe")
    if not os.path.exists(pyi):
        pyi = "pyinstaller"
    pair = shield_torch()
    if pair:
        log("   已临时屏蔽 site-packages/torch（躲开 PyInstaller 收集期段错误）")
    try:
        rc = subprocess.call([pyi, SPEC, "--noconfirm"], cwd=ROOT)
    finally:
        unshield_torch(pair)
        if pair:
            log("   已恢复 site-packages/torch")
    if rc != 0:
        raise SystemExit(f"PyInstaller 失败，退出码 {rc}")


def du(path: str) -> int:
    total = 0
    for dp, _dn, fn in os.walk(path):
        for f in fn:
            try:
                total += os.path.getsize(os.path.join(dp, f))
            except OSError:
                pass
    return total


INTERNAL = os.path.join(DIST, "_internal")

# 需要在 _internal 里「差集同步」的包 —— PyInstaller 的按需收集在这里是硬伤。
#
# 为什么必须补：PyInstaller 只收「从入口静态可达」的子模块。这几个包**两边都用**
# （应用核心 + AI 内核），于是拿到的是「恰好够应用自己跑」的残件：
#   · numpy —— 只有 core/fft/linalg/random，连 .dist-info 都没有
#     ⇒ importlib.metadata.version("numpy") 抛 PackageNotFoundError，diffusers 崩
#   · scipy —— 有 fft/integrate/linalg/ndimage/… 但**没有 signal**
#     ⇒ librosa 与 scipy.signal 全废
#   · PIL   —— 没有 ImageEnhance ⇒ torchvision / easyocr import 失败
#
# 为什么不能放进 runtime/：这三个包的 __init__ 已被收进 PYZ。PYZ 里的包优先于
# sys.path 搜索，且它的 __path__ 指向 _internal/<pkg>；往 runtime/ 放同名包会被
# **完全遮住**、一点用都没有（实测过，别重复试）。
#
# 补法是差集同步：site-packages 里有、_internal 里没有的才拷。既补齐，
# 又不会把 PyInstaller 特意裁掉的东西再塞回去。
SYNC_PKGS = ["numpy", "scipy", "PIL", "cryptography", "yaml"]

# 标准库里是「包」的那部分，也必须补进 _internal。
#
# 区别在于形态：
#   · 平铺的 .py 模块（timeit / struct / modulefinder …）→ 放 runtime/ 就生效，
#     因为 PYZ 里没有同名条目，sys.path 搜索能命中。
#   · **包**（html / email / urllib …）→ 不行。PYZ 里已有它的 __init__，
#     __path__ 指向 _MEIPASS/<pkg>，子模块只在那个目录里找。
#     所以 html.parser 会「父包能 import、子模块不存在」。
# 这条是实测撞出来的：torchvision / easyocr 报 No module named 'html.parser'。
SYNC_STDLIB = ["html"]

# 不在 PyInstaller Analysis 里、但必须随包走的 app 子包。
#
# 为什么不进 Analysis：`app/core/video_processing` 是原生引擎层（cython_*.pyd、
# cpp_engine 未编译），进 Analysis 会在收集期 0xC0000005（spec 里为此长期排除它，
# 代价是这块功能整片缺失 —— 覆盖检查实测 6 个模块不在包里）。
# 为什么不放 runtime/：它是 `app` 的子包，父包 `app.core` 在 PYZ 里、
# `__path__` 指向 `_internal/app/core`；放 runtime/ 会被完全遮住（同 PIL/numpy）。
# 所以按目录形态直接拷进 `_internal/app/core/video_processing`，
# PathFinder 顺着父包的 __path__ 就能找到，完全绕开 Analysis。
#
# `app/plugins` 是另一类原因，同样必须拷目录：PluginManager 是**按文件名扫目录**
# 加载的（app/core/plugin_manager.py:74 的 os.listdir(plugin_dir)），
# 目录不存在时它 `continue` 掉了 —— 不报错、不警告。模块在 PYZ 里也没用，
# 因为 `_load_plugin_from_file` 走的是 spec_from_file_location，要的是磁盘上的 .py。
# 实测后果：编辑器里转场/特效插件数 = 0（editor_module.py:721 就 new 了它）。
#
# `app/skills` 是第三种：它是**数据目录**（226 个文件 / 11 个 SKILL.md / 6.4 MB），
# 只有 4 个 .py 在 PYZ 里，其余全是 loader 要 os.walk 的 md/json/svg。
# 根路径在 app/skills/__init__.py:17 用 `Path(__file__).parent` 算，
# 冻结态指向 `_internal/app/skills/__init__.pyc` 的父目录 ⇒ 目录得真在磁盘上。
# 缺了的表现和插件一模一样：三个调用点（extension_facade:112 /
# project_agent_host:654 / extensions_module:1699）都返回 0 且不报错，
# 界面就是「外部 Skill 一栏空着」。
SYNC_APP_SUBPKGS = ["app/core/video_processing", "app/plugins", "app/skills"]


def _tops_of(dist) -> list[str]:
    """dist 的顶层 import 名（已归一化）。"""
    try:
        txt = dist.read_text("top_level.txt")
    except Exception:
        txt = None
    if txt:
        got = []
        for t in txt.split():
            # 🔴 top_level.txt 里并非全是「顶层模块名」：
            #    mediapipe 写的是 `mediapipe\python\_framework_bindings` 这种
            #    带反斜杠的子模块路径。原样拿去比对必然对不上。
            head = t.replace("\\", "/").split("/", 1)[0].strip()
            if head and head not in (".", "..") and head not in got:
                got.append(head)
        if got:
            return got
    out = []
    for f in dist.files or []:
        posix = str(f).replace("\\", "/")
        if "/" not in posix:
            continue
        head = posix.split("/", 1)[0]
        # 🔴 必须滤掉 ".."：numpy 的 RECORD 里带 `../numpy.libs/...` 这种
        #    包外共享库路径，取第一段就是 ".."。它永远不可能出现在产物里，
        #    于是「全部 top-level 都在产物里」这条判据恒假 ⇒ numpy 的
        #    dist-info 永远补不上，而日志只会显示「补 0 个」，完全不报错。
        if head in ("..", ".", ""):
            continue
        if head.endswith((".dist-info", ".data", ".libs", ".dlls")):
            continue
        if head not in out:
            out.append(head)
    return out


def _shipped_names() -> set[str]:
    """产物里实际存在的顶层导入名（_internal + runtime）。"""
    names: set[str] = set()
    for base in (INTERNAL, RUNTIME_DST):
        if not os.path.isdir(base):
            continue
        for n in os.listdir(base):
            low = n.lower()
            if low.endswith((".dist-info", ".libs", ".dlls")):
                continue
            if low.endswith(".pyd"):
                names.add(low.split(".", 1)[0])       # struct.cp312-win_amd64.pyd
            elif low.endswith((".py", ".pyc", ".pyo")):
                names.add(low.rsplit(".", 1)[0])
            else:
                names.add(low)
    return names


def _sync_pkg(pkg: str) -> tuple[int, int]:
    """把 site-packages/<pkg> 里 _internal 缺的文件补进去。"""
    return _sync_tree(os.path.join(SITE_PACKAGES, pkg), os.path.join(INTERNAL, pkg), pkg)


def _sync_stdlib(pkg: str) -> tuple[int, int]:
    """把标准库里的包补进 _internal（原因见 SYNC_STDLIB）。"""
    import sysconfig

    src = os.path.join(sysconfig.get_paths()["stdlib"], pkg)
    return _sync_tree(src, os.path.join(INTERNAL, pkg), pkg)


def _sync_app_subpkg(rel: str) -> tuple[int, int]:
    """把项目里的 app 子包按目录形态拷进 _internal（原因见 SYNC_APP_SUBPKGS）。

    三处专门跳过，都有实测依据：
      · ``build/`` —— cpp_engine 的 CMake/MVSC 中间产物（.obj + Release 副本
        250 MB），运行时零需求；
      · ``.git/`` —— `app/skills/external/` 下三个 skill 是用 git clone 拉进来的
        （seedance2-skill / video-use / videocut-skills，合计 2.3 MB），
        里面是**别人仓库的历史**：发布包不需要，还会把来源与提交记录一起带出去。
        而且 git 的 pack 文件默认只读（-r--r--r--），PyInstaller 下次重建
        `_rmtree(dist)` 时会 PermissionError: [WinError 5] 直接打断打包 ——
        这是实测撞出来的，不是预防性写法；
      · ``_internal`` 里**已存在同名**的 .dll —— 这个子包根下的 FFmpeg DLL
        （avcodec-62 / avfilter-11 等）合计 320 MB，而 `_internal/` 根和
        `_internal/thirdparty/ffmpeg/bin/` 已经有同名的了，再拷一份纯属浪费。
    """
    src = os.path.join(ROOT, *rel.split("/"))
    dst = os.path.join(INTERNAL, *rel.split("/"))
    have = set()
    if os.path.isdir(INTERNAL):
        have = {n.lower() for n in os.listdir(INTERNAL)}
    return _sync_tree(
        src, dst, rel,
        skip_dirs={"build", "__pycache__", ".git", ".github", ".idea", ".vscode"},
        skip_ext={".obj", ".lib", ".exp", ".pdb", ".ilk", ".idb", ".pyc", ".pyo"},
        skip_dll_if_in=have,
    )


def _sync_tree(src_root: str, dst_root: str, label: str,
               skip_dirs: set[str] | None = None,
               skip_ext: set[str] | None = None,
               skip_dll_if_in: set[str] | None = None) -> tuple[int, int]:
    """差集同步：src 里有、dst 里没有（或大小不同）的文件才拷。"""
    if not os.path.isdir(src_root):
        log(f"   ! {label}: 源目录不存在，跳过")
        return 0, 0
    skip_dirs = skip_dirs or {"__pycache__"}
    skip_ext = skip_ext or {".pyc", ".pyo"}
    added = size = 0
    for dp, dn, fn in os.walk(src_root):
        dn[:] = [d for d in dn if d not in skip_dirs]
        rel = os.path.relpath(dp, src_root)
        out_dir = dst_root if rel == "." else os.path.join(dst_root, rel)
        for f in fn:
            ext = os.path.splitext(f)[1].lower()
            if ext in skip_ext:
                continue
            if (skip_dll_if_in and ext == ".dll" and f.lower() in skip_dll_if_in):
                continue
            s = os.path.join(dp, f)
            d = os.path.join(out_dir, f)
            sz = os.path.getsize(s)
            if os.path.exists(d) and os.path.getsize(d) == sz:
                continue
            os.makedirs(out_dir, exist_ok=True)
            shutil.copy2(s, d)
            added += 1
            size += sz
    return added, size


def complete_internal() -> None:
    """补全 _internal 里被按需收集弄残的包，并补齐 dist-info。"""
    log("②b 补全 _internal 里被按需收集弄残的包 …")
    total_f = total_b = 0
    for pkg in SYNC_PKGS:
        n, b = _sync_pkg(pkg)
        total_f += n
        total_b += b
        log(f"   {pkg:<14} 补 {n:>6} 个文件 / {b/1048576:7.1f} MB")
    for pkg in SYNC_STDLIB:
        n, b = _sync_stdlib(pkg)
        total_f += n
        total_b += b
        log(f"   stdlib:{pkg:<7} 补 {n:>6} 个文件 / {b/1048576:7.1f} MB")
    for rel in SYNC_APP_SUBPKGS:
        n, b = _sync_app_subpkg(rel)
        total_f += n
        total_b += b
        log(f"   {rel:<22} 补 {n:>6} 个文件 / {b/1048576:7.1f} MB")

    # dist-info：没有它 importlib.metadata.version() 就抛 PackageNotFoundError。
    # 只给「确实随包发出去」的 dist 补（全部 top-level 都在产物里），免得
    # importlib.metadata 谎报一个实际不存在的包，把库引到错误分支上。
    import importlib.metadata as md

    shipped = _shipped_names()
    n_meta = 0
    for dist in md.distributions():
        tops = _tops_of(dist)
        # 🔴 numpy 这种没有 top_level.txt、dist.files 又取不到的，tops 会是空表。
        #    早先版本写成「tops 为空就跳过」，结果 numpy 的 dist-info 永远补不上，
        #    transformers / diffusers 一直抛 PackageNotFoundError，而补全日志里
        #    只显示「dist-info 补 110 个」，看不出少了谁。所以空表要退到用
        #    dist 名本身去判，不能直接放弃。
        if tops:
            # 用「任一」而非「全部」：PyYAML 的 top_level 是 ['_yaml', 'yaml']，
            # 但 PyInstaller 把 _yaml.pyd 放进了 yaml/ 子目录，顶层没有 _yaml。
            # 按「全部」判会把 PyYAML 整个漏掉，而 transformers 要查
            # metadata.version("pyyaml")，缺了就是一连串 PackageNotFoundError。
            # 方向上的取舍：宁可多给元数据（多给只会让版本查询有个答案，
            # 包真不在的话 import 仍然会失败），也不能少给。
            ok = any(t.lower() in shipped for t in tops)
        else:
            key = (dist.metadata["Name"] or "").replace("-", "_").lower()
            ok = bool(key) and key in shipped
        if not ok:
            continue
        p = getattr(dist, "_path", None)
        if p is None:
            continue
        name = os.path.basename(str(p))
        if not name.lower().endswith(".dist-info"):
            continue
        dst = os.path.join(INTERNAL, name)
        if os.path.isdir(dst):
            continue
        try:
            shutil.copytree(str(p), dst)
            n_meta += 1
        except OSError as e:
            log(f"   ! dist-info {name}: {e}")
    log(f"   dist-info 补 {n_meta} 个；合计补 {total_f} 个文件 / "
        f"{total_b/1048576:.1f} MB")


def copy_runtime() -> None:
    log("② 装入 AI 内核 runtime/ …")
    if not os.path.isdir(RUNTIME_SRC):
        raise SystemExit(
            f"缺少 {RUNTIME_SRC}\n"
            "先执行：.venv312\\Scripts\\python.exe scripts\\make_runtime_pack.py"
        )
    if not os.path.isdir(DIST):
        raise SystemExit(f"缺少 {DIST}（PyInstaller 没产物？）")

    copied = skipped = 0
    for dp, _dn, fn in os.walk(RUNTIME_SRC):
        rel = os.path.relpath(dp, RUNTIME_SRC)
        out_dir = RUNTIME_DST if rel == "." else os.path.join(RUNTIME_DST, rel)
        os.makedirs(out_dir, exist_ok=True)
        for f in fn:
            src = os.path.join(dp, f)
            dst = os.path.join(out_dir, f)
            size = os.path.getsize(src)
            if os.path.exists(dst) and os.path.getsize(dst) == size:
                skipped += 1
                continue
            shutil.copy2(src, dst)
            copied += 1
    log(f"   复制 {copied} 个文件（{du(RUNTIME_DST)/1073741824:.2f} GB），"
        f"已存在跳过 {skipped} 个")


def selftest() -> dict:
    log("③ 运行产物自检（--selftest）…")
    if not os.path.exists(EXE):
        raise SystemExit(f"缺少 {EXE}")
    out = os.path.join(tempfile.gettempdir(), "shiguang_selftest.json")
    if os.path.exists(out):
        os.remove(out)
    kwargs = {}
    if os.name == "nt":
        kwargs["creationflags"] = 0x08000000  # CREATE_NO_WINDOW
    rc = subprocess.call([EXE, "--selftest", "--selftest-out", out], cwd=DIST, **kwargs)
    if not os.path.exists(out):
        raise SystemExit(f"自检没有产出报告（exe 退出码 {rc}），报告路径 {out}")
    with open(out, encoding="utf-8") as f:
        report = json.load(f)

    for c in report["checks"]:
        if c["ok"]:
            continue
        tag = "WARN" if c.get("optional") else "FAIL"
        log(f"   [{tag}] {c['name']}: {c['detail']}")
    rt = report["runtime_pack"]
    log(f"   AI 内核 {rt['size_mb']:.0f} MB / {rt['packages']} 个包，"
        f"自检 {report['passed']}/{report['total']}"
        + (f"（{report['warned']} 项降级）" if report.get("warned") else ""))
    return report


def build_installer() -> str:
    log("④ NSIS 打安装包 …")
    makensis = shutil.which("makensis")
    if not makensis:
        for cand in (r"C:\Program Files (x86)\NSIS\makensis.exe",
                     r"C:\Program Files\NSIS\makensis.exe"):
            if os.path.exists(cand):
                makensis = cand
                break
    if not makensis:
        raise SystemExit("找不到 makensis.exe，请安装 NSIS 或手动执行 scripts\\installer.nsi")
    rc = subprocess.call([makensis, NSI], cwd=ROOT)
    if rc != 0:
        raise SystemExit(f"makensis 失败，退出码 {rc}")
    out_dir = os.path.join(ROOT, "dist")
    setups = [f for f in os.listdir(out_dir) if f.startswith("拾光剪影-Setup-")]
    if not setups:
        raise SystemExit("makensis 成功但没找到 Setup 产物")
    setups.sort(key=lambda f: os.path.getmtime(os.path.join(out_dir, f)), reverse=True)
    return os.path.join(out_dir, setups[0])


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-pyinstaller", action="store_true", help="复用现有 dist，不重打")
    ap.add_argument("--installer", action="store_true", help="继续生成 NSIS 安装包")
    ap.add_argument("--skip-selftest", action="store_true", help="跳过自检（不建议）")
    args = ap.parse_args()

    if not args.skip_pyinstaller:
        run_pyinstaller()
    copy_runtime()
    complete_internal()

    report = None
    if not args.skip_selftest:
        report = selftest()

    log("⑤ 体积")
    log(f"   程序目录 dist/拾光剪影       {du(DIST)/1073741824:.2f} GB")
    if os.path.isdir(RUNTIME_DST):
        log(f"   其中 AI 内核 runtime/        {du(RUNTIME_DST)/1073741824:.2f} GB")
    log(f"   其中主程序 _internal/        {du(os.path.join(DIST,'_internal'))/1073741824:.2f} GB")

    if args.installer:
        setup = build_installer()
        log(f"   安装包 {os.path.basename(setup)}  {os.path.getsize(setup)/1073741824:.2f} GB")

    if report is not None and not report["ok"]:
        log(f"!! 自检有硬失败（{', '.join(report.get('hard_failed') or [])}）—— 不要拿去发布")
        return 1
    if report is not None and report.get("warned"):
        log(f"注意：{report['warned']} 项降级（已入包但冻结环境跑不起来，"
            f"产品侧有降级路径）；详见自检报告")
    log("完成")
    return 0


if __name__ == "__main__":
    sys.exit(main())
