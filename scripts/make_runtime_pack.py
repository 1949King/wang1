# -*- coding: utf-8 -*-
"""把 AI 运行时依赖从 .venv312 裁出来后复制成 build/runtime_pack。

为什么要「纯文件目录」而不是让 PyInstaller 收集
================================================
``app/ai_video_editor_local.spec:60-71`` 记载了硬事实：打包期 PyInstaller 会
``__import__`` 模块图并收集原生 DLL，torch 的原生库在 ``import_library`` 隔离子
进程里触发 ``0xC0000005`` 访问违例，打包进程直接崩。所以 torch 永远不能进
PyInstaller 的 Analysis；它必须以普通目录形态跟着 exe 走，运行时靠
``app/core/runtime_pack.py`` 注入 ``sys.path`` 加载。

为什么按「依赖闭包」而不是手写清单
==================================
手写清单必然漏。实测过的漏法：
  · ``librosa`` → ``soxr`` / ``pooch`` / ``lazy_loader`` / ``msgpack``
  · ``easyocr`` → ``scikit-image`` / ``python-bidi`` / ``pyclipper`` / ``ninja``
  · ``mediapipe`` → ``absl-py`` / ``flatbuffers`` / ``attrs``
漏了的表现是 import 时 ModuleNotFoundError，而产品代码几乎处处
``try/except`` ⇒ **静默降级**，装完看着正常、用到才发现没功能。所以这里用
``importlib.metadata`` 递归展开 ``Requires-Dist``，闭包即真相。

已被主包 _internal 收全的跳过
=============================
重复打包不但浪费体积，两份同名库同时躺在 sys.path 上还会让「到底加载了哪一份」
不可预测。判定方式：该 distribution 的任一 top-level 名已存在于
``dist/拾光剪影/_internal`` ⇒ 已由 PyInstaller 收全，跳过。

裁剪原则（只删编译期/链接期产物，不删任何运行时能力）
====================================================
  *.lib / *.exp / *.pdb / *.a / *.obj  —— 链接期静态库与调试符号
  torch/include                        —— C++ 扩展头文件，只在编译扩展时需要
  __pycache__                          —— 字节码缓存

🔴 ``torch/testing/_internal`` **绝不能删**（9.0 MB，试过，会炸）：
   ``torch/utils/checkpoint.py:17`` 在模块顶层
   ``from torch.testing._internal.logging_tensor import capture_logs, LoggingTensorMode``，
   于是 torch.distributed._composable → torch.utils.checkpoint →
   torch.testing._internal 成为硬链。删掉后报错会伪装成
   「transformers: Could not import module 'AutoModel'」（向上传了四层），
   完全看不出跟 testing 有关。

🔴 CUDA 那组 DLL（cufft/cufftw/cusparse/cupti）**也不能删**（2026-11-05 实测）：
   只移出这 4 个，``import torch`` 立刻报
   ``Error loading "torch\\lib\\cusolver64_11.dll" or one of its dependencies``
   —— cusolver 没动，是它硬依赖 cusparse。CUDA DLL 是**加载期紧耦合集合**，
   抽掉任一个都连带炸掉整个 torch（26/26 → 12/26）。即使全库 ``torch.fft`` /
   ``torch.sparse`` 零引用也没用，动态链接不看调用量。

用法:
    .venv312\\Scripts\\python.exe .workbuddy\\tmp\\make_runtime_pack.py
    .venv312\\Scripts\\python.exe .workbuddy\\tmp\\make_runtime_pack.py --list-only
"""
from __future__ import annotations

import importlib.metadata as md
import os
import shutil
import sys
import time

# 路径全部由脚本位置推导，换机器/换盘不用改代码
ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir))
SP = os.environ.get("SG_SITE_PACKAGES") or os.path.join(ROOT, ".venv312", "Lib", "site-packages")
DST = os.path.join(ROOT, "build", "runtime_pack")
INTERNAL = os.path.join(ROOT, "dist", "拾光剪影", "_internal")

# 必须随包走的根包（import 名）。其余靠依赖闭包补齐。
ROOT_PACKAGES = [
    # torch 栈
    "torch", "torchvision", "torchaudio", "diffusers", "transformers",
    "accelerate", "peft", "diffsynth_engine", "einops",
    "huggingface_hub",
    # 🔴 下面这几个**不能只靠依赖闭包**：transformers 5.x 把 tokenizers、
    #    safetensors、jinja2 划进了 extras，``Requires-Dist`` 的 marker 求值
    #    （extra=""）会判 False，闭包直接跳过。实测后果：
    #    「No module named 'safetensors'」⇒ diffsynth / 微调栈全废。
    #    所以显式登记为根包，别删。
    "safetensors", "tokenizers", "markupsafe",
    # 🔴 httpx2：huggingface_hub 1.23.0 的**代码**里是 `import httpx2`，
    #    而它的 **METADATA** 写的是 `httpx<1,>=0.23.0` —— 元数据和代码不一致。
    #    这类漏法依赖闭包原理上推不出来（按 Requires-Dist 只会去找 httpx）。
    #    表现：transformers/diffusers/diffsynth 全部 ModuleNotFoundError: httpx2。
    #    它是 httpx 的一条完整链：httpx2 → httpcore2 / truststore / idna / anyio。
    #    再遇到同类的，就往这一行加 —— 这也是为什么必须有「运行时真跑」的自检：
    #    光看依赖声明永远补不全。
    "httpx2",
    # opentimelineio：时间线交换（FCPXML/EDL/OTIO）用。它自带原生扩展
    # `_opentimelineio.pyd`，进不了 PyInstaller 的 Analysis（隔离导入子进程里
    # 在 PyQt6 时代与 Qt 冲突，0xC0000005；PySide6 继续隔离），由内核目录供给。
    "opentimelineio",
    # spec excludes 里的重型库
    "easyocr", "mediapipe", "librosa", "numba", "llvmlite",
    "sklearn", "sympy", "networkx", "onnxruntime",
]

SKIP_EXT = {".lib", ".exp", ".pdb", ".a", ".obj", ".iobj", ".ipdb"}
# 包内的编译期目录名（相对包根的第二段）。torch/include 是 C++ 扩展头文件，
# 运行时零需求（29 MB）。注意 dist.files 里的路径带包名前缀（torch/include/...），
# 所以要比对「第二段」而不是「第一段」—— 第一版就写错在这里，导致没裁掉。
SKIP_PKG_SUBDIR = {"include"}

# 🔴 内核**不能**带的 dist（2026-11-05 实测，别删这条注释）。
#
# PyQt6 时代实测 ``sentencepiece`` 和 Qt 在同一进程里是**原生加载顺序互斥**的；
# 迁移 PySide6 后继续保守隔离，不推定旧原生冲突已自动消失：
#   · 先 ``import PyQt6.QtWidgets`` 再 ``import sentencepiece`` ⇒ exit 139 / 0xC0000005，
#     无 Python 栈、无 faulthandler，直接进程消失
#   · 反过来（先 sentencepiece 后 PyQt6）正常
# 崩点定位在 ``sentencepiece`` 的 C 扩展 ``create_module``。产品是 Qt 应用，
# Qt 必定先加载，所以这个顺序在我们这儿无解。
#
# 它对本项目是**可选**依赖，代价很小：
#   · ``gguf/vocab.py:12`` —— ``try: from sentencepiece import ... except ImportError: 置 None``
#   · ``transformers`` —— ``is_sentencepiece_available()`` 门控，缺了只是
#     少数旧式 spm 分词器模型不可用
# 对比之下「带上就整个进程崩」不可接受，所以内核里不带它。
#
# 同一个坑也解释了一件看似无关的事：PyInstaller 打包期会崩在
# ``crashed while importing package 'gguf'`` —— 因为入口进程已 import PyQt6，
# 而 ``gguf/vocab.py`` 的顶层 try 会真的去 import sentencepiece。这条链极难认，
# 所以 ``app/ai_video_editor_local.spec`` 的 excludes 里也排了 ``gguf`` 和
# ``sentencepiece``。
SKIP_TOPLEVEL_DISTS: set[str] = {"sentencepiece"}

# 🔴 PyInstaller 漏掉的标准库模块，必须由内核目录补上。
#
# 机理：PyInstaller 只收「从入口静态可达」的模块。torch 在 spec 的 excludes 里
# 完全不参与 Analysis，所以 ``import torch`` 期间需要的标准库模块它一个都不会收。
# 而 ``runtime/`` 会被顶到 ``sys.path[0]``（app/core/runtime_pack.py），
# 于是这些 .py 文件放在这里就能被正常找到 —— 不需要 repack，也不需要
# 往 spec 里塞 hiddenimports。
#
# 这份清单是**实测出来的**，不是猜的：冻结点跑 --selftest，一次报一个缺失模块，
# 补进去再跑，直到 torch / torchvision / numba / sympy 全部 import 通过。
# ``struct`` 也在里面 —— 它是 ``Lib/struct.py`` 这个纯 Python 包装（真实现是
# 内置的 _struct），所以「struct 怎么可能缺」这种直觉在这里不成立。
STDLIB_PATCHES = [
    "timeit",        # torch 顶层的 benchmark 工具链
    "modulefinder",  # torchvision / numba
    "pstats", "profile", "cProfile",  # torch 的 profiler
    "pickletools",   # numpy / joblib 反序列化路径
    "filecmp",       # diffusers 缓存比对
    "_markupbase",   # html.parser 依赖（transformers tokenizer 清洗）
    "struct",        # pickle / numpy 的基础依赖
]


def human(n: float) -> str:
    return f"{n / 1048576:9.1f} MB"


def bundled_names() -> set[str]:
    if not os.path.isdir(INTERNAL):
        return set()
    return {n.lower() for n in os.listdir(INTERNAL)}


def dist_index():
    """dist 名 → (Distribution, [top-level 名])。

    ⚠️ 环境里可能存在**同名的多份 .dist-info**（本项目实测：huggingface_hub
    1.23.0 + 2.0.0、click 8.1.8 + 8.4.2，后者是残留）。不能按「版本更高」挑
    —— 残留那份往往版本更高。要以 ``importlib.metadata.version()`` 的解析结果
    为准，即 transformers 等库运行时真正看到的那个版本；否则会出现
    「包装对了，运行时却判定版本不符」的怪错：
        huggingface-hub>=1.5.0,<2.0 is required ... but found 2.0.0
    """
    groups: dict[str, list] = {}
    for d in md.distributions():
        name = (d.metadata["Name"] or "").strip()
        if not name:
            continue
        groups.setdefault(_canon(name), []).append(d)

    idx = {}
    dups = []
    for key, ds in groups.items():
        if len(ds) == 1:
            chosen = ds[0]
        else:
            try:
                eff = md.version(ds[0].metadata["Name"])
            except Exception:
                eff = None
            chosen = next((d for d in ds if d.version == eff), ds[0])
            dups.append((key, eff, [d.version for d in ds]))
        idx[key] = (chosen, _tops_of(chosen))
    for key, eff, vers in dups:
        print(f"  ⚠ 重名 dist {key}: 生效 {eff}，候选 {vers}（取生效版本）")
    return idx


def _tops_of(d) -> list[str]:
    try:
        txt = d.read_text("top_level.txt")
    except Exception:
        txt = None
    if txt:
        tops = [t.strip() for t in txt.split() if t.strip()]
        if tops:
            return tops
    return _tops_from_files(d)


def _tops_from_files(d) -> list[str]:
    out = []
    for f in d.files or []:
        posix = str(f).replace("\\", "/")
        if "/" not in posix:
            continue
        head = posix.split("/", 1)[0]
        # ".." 来自 RECORD 里的包外共享库路径（`../numpy.libs/...`），不是包名
        if head in ("..", ".", ""):
            continue
        if head.endswith((".dist-info", ".data", ".libs")) or head in ("__pycache__",):
            continue
        if head.endswith((".py", ".pyd", ".so", ".dll")):
            head = head.rsplit(".", 1)[0]
        if head not in out:
            out.append(head)
    return out


def _canon(name: str) -> str:
    return name.lower().replace("-", "_").replace(".", "_")


def closure(roots: list[str], idx) -> tuple[list[str], list[tuple[str, str]]]:
    """返回 (选中的 dist 名列表, [(被跳过, 原因)])。"""
    have = bundled_names()
    selected: list[str] = []
    skipped: list[tuple[str, str]] = []
    seen: set[str] = set()
    queue: list[tuple[str, str]] = [(r, "root") for r in roots]

    while queue:
        name, why = queue.pop(0)
        cname = _canon(name)
        if cname in seen:
            continue
        seen.add(cname)

        hit = idx.get(cname)
        if hit is None:
            # 有些 dist 用连字符/下划线不同写法，兜底再找一次
            for k, v in idx.items():
                if k.replace("_", "") == cname.replace("_", ""):
                    hit = v
                    break
        if hit is None:
            skipped.append((name, f"未安装（来自 {why}）"))
            continue

        dist, tops = hit
        # 主包已收全 ⇒ 跳过（连同它的依赖也不用再展开）
        if tops and any(t.lower() in have for t in tops):
            skipped.append((name, "已在主包 _internal"))
            continue
        if cname in SKIP_TOPLEVEL_DISTS:
            skipped.append((name, "显式排除"))
            continue

        selected.append(cname)
        for req in _requires(dist):
            queue.append((req, name))
    return selected, skipped


def _requires(dist) -> list[str]:
    """解析 Requires-Dist，按当前环境求值 marker，跳过 extras。"""
    out = []
    for raw in dist.requires or []:
        try:
            from packaging.requirements import Requirement
            r = Requirement(raw)
        except Exception:
            continue
        if r.marker is not None:
            try:
                env = {"extra": ""}
                if not r.marker.evaluate(env):
                    continue
            except Exception:
                pass
        out.append(r.name)
    return out


def skip_rel(parts: list[str], tops: list[str]) -> bool:
    """判断 dist.files 里的一个相对路径要不要跳过。

    ``parts`` 已按 "/" 切开，形如 ``["torch", "include", "ATen", "ATen.h"]``。
    """
    if len(parts) < 2:
        return False
    if parts[0] in tops and parts[1] in SKIP_PKG_SUBDIR:
        return True
    return False


def copy_dist(dist, tops: list[str], stats: dict) -> int:
    """按 dist.files 精确复制，顺带裁链接期产物。返回复制字节数。"""
    root = str(dist.locate_file(""))
    done = 0
    for f in dist.files or []:
        posix = str(f).replace("\\", "/")
        if ".." in posix.split("/"):
            continue
        parts = posix.split("/")
        if "__pycache__" in parts:
            continue
        rel = os.path.join(*parts)
        if skip_rel(parts, tops):
            stats["skip"] += 1
            continue
        if os.path.splitext(parts[-1])[1].lower() in SKIP_EXT:
            stats["skip"] += 1
            continue
        src = os.path.join(root, rel)
        if not os.path.exists(src):
            continue
        stats["src"] += os.path.getsize(src)
        stats.setdefault("tops", set()).add(parts[0])
        out = os.path.join(DST, rel)
        os.makedirs(os.path.dirname(out), exist_ok=True)
        if os.path.exists(out) and os.path.getsize(out) == os.path.getsize(src):
            done += 0
            stats["copy"] += os.path.getsize(src)
            continue
        try:
            shutil.copy2(src, out)
            done += os.path.getsize(src)
            stats["copy"] += os.path.getsize(src)
        except OSError as e:
            print(f"  ! {rel}: {e}")
    return done


def copy_companion_libs(tops: list[str], stats: dict) -> None:
    """包外共享库目录 <pkg>.libs / <pkg>.dlls（openblas / LLVM 等）。"""
    for t in tops:
        for suf in (".libs", ".dlls"):
            src = os.path.join(SP, t + suf)
            if not os.path.isdir(src):
                continue
            for f in os.listdir(src):
                sp = os.path.join(src, f)
                if not os.path.isfile(sp):
                    continue
                stats["src"] += os.path.getsize(sp)
                dd = os.path.join(DST, t + suf)
                os.makedirs(dd, exist_ok=True)
                stats.setdefault("tops", set()).add(t + suf)
                out = os.path.join(dd, f)
                if os.path.exists(out) and os.path.getsize(out) == os.path.getsize(sp):
                    stats["copy"] += os.path.getsize(sp)
                    continue
                try:
                    shutil.copy2(sp, out)
                    stats["copy"] += os.path.getsize(sp)
                except OSError as e:
                    print(f"  ! {sp}: {e}")


def copy_stdlib_patches(stats: dict) -> list[str]:
    """把 STDLIB_PATCHES 里的标准库模块从当前解释器拷进内核目录。"""
    import sysconfig

    stdlib = sysconfig.get_paths()["stdlib"]
    done: list[str] = []
    missing: list[str] = []
    for name in STDLIB_PATCHES:
        rel = os.path.join(*name.split("."))
        src_py = os.path.join(stdlib, rel + ".py")
        src_dir = os.path.join(stdlib, rel)
        if os.path.isfile(src_py):
            stats["src"] += os.path.getsize(src_py)
            out = os.path.join(DST, rel + ".py")
            os.makedirs(os.path.dirname(out), exist_ok=True)
            shutil.copy2(src_py, out)
            stats["copy"] += os.path.getsize(src_py)
            # 登记的是**文件名**不是模块名：prune_stale 拿它跟 os.listdir 的结果
            # 逐个比对，写成 "cProfile" 会和磁盘上的 "cProfile.py" 对不上，
            # 于是刚补进去的文件立刻被自己移走（实测踩过）。
            stats.setdefault("tops", set()).add(os.path.basename(rel + ".py"))
            done.append(name)
        elif os.path.isdir(src_dir):
            for dp, _dn, fn in os.walk(src_dir):
                if "__pycache__" in dp:
                    continue
                sub = os.path.relpath(dp, stdlib)
                for f in fn:
                    if f.endswith((".pyc", ".pyo")):
                        continue
                    sp = os.path.join(dp, f)
                    stats["src"] += os.path.getsize(sp)
                    out = os.path.join(DST, sub, f)
                    os.makedirs(os.path.dirname(out), exist_ok=True)
                    shutil.copy2(sp, out)
                    stats["copy"] += os.path.getsize(sp)
            stats.setdefault("tops", set()).add(os.path.basename(rel))
            done.append(name)
        else:
            missing.append(name)
    if missing:
        print(f"  ! 标准库补丁找不到源：{missing}")
    return done


def prune_stale(expected: set[str]) -> int:
    """把内核目录里「不属于本次闭包」的顶层条目移走。

    为什么必须做：脚本只做复制、从不删除，于是**闭包缩小时旧文件会永远留着**。
    实测踩过：sentencepiece 被显式排除后，它仍躺在 runtime/ 里，会让冻结版每次
    启动都 0xC0000005 —— 而且排查时看到的文件和构建逻辑完全对不上。

    移到 ``.workbuddy/tmp/pack_stale/<时间戳>/`` 而不是删除：可回溯，
    也避开沙箱的批量删除拦截。
    """
    if not os.path.isdir(DST):
        return 0
    stale = [n for n in os.listdir(DST) if n not in expected]
    if not stale:
        return 0
    dest = os.path.join(ROOT, ".workbuddy", "tmp", "pack_stale", time.strftime("%m%d_%H%M%S"))
    os.makedirs(dest, exist_ok=True)
    for n in stale:
        shutil.move(os.path.join(DST, n), os.path.join(dest, n))
    print(f"\n移出 {len(stale)} 个不属于当前闭包的残留：{', '.join(stale[:8])}"
          f"{' …' if len(stale) > 8 else ''}")
    print(f"  已移到 {dest}")
    return len(stale)


def main() -> int:
    if os.name != "nt":
        print("仅支持 Windows")
        return 2
    list_only = "--list-only" in sys.argv

    idx = dist_index()
    sel, skipped = closure(ROOT_PACKAGES, idx)

    print(f"闭包选中 {len(sel)} 个 dist：")
    rows = []
    for cname in sel:
        dist, tops = idx[cname]
        size = 0
        for f in dist.files or []:
            p = str(dist.locate_file(f))
            try:
                size += os.path.getsize(p)
            except OSError:
                pass
        rows.append((size, dist.metadata["Name"], tops))
    rows.sort(reverse=True)
    for size, name, tops in rows:
        print(f"  {human(size)}  {name:<28} {','.join(tops[:3])}")

    print(f"\n跳过 {len(skipped)} 项：")
    by_reason: dict[str, int] = {}
    for _n, why in skipped:
        by_reason[why] = by_reason.get(why, 0) + 1
    for why, cnt in sorted(by_reason.items(), key=lambda x: -x[1]):
        print(f"  {cnt:4d}  {why}")
    for n, why in skipped:
        if "未安装" in why or "显式" in why:
            print(f"     ! {n}: {why}")

    if list_only:
        return 0

    os.makedirs(DST, exist_ok=True)
    t0 = time.time()
    stats = {"src": 0, "copy": 0, "skip": 0, "tops": set()}
    for cname in sel:
        dist, tops = idx[cname]
        copy_dist(dist, tops, stats)
        copy_companion_libs(tops, stats)
    patched = copy_stdlib_patches(stats)
    if patched:
        print(f"\n补入标准库 {len(patched)} 个：{', '.join(patched)}")

    prune_stale(stats["tops"])

    el = time.time() - t0
    print("\n" + "-" * 50)
    print(f"闭包源合计 {human(stats['src'])}")
    print(f"实际落地   {human(stats['copy'])}")
    print(f"裁掉文件   {stats['skip']} 个（链接期/调试/头文件）")
    print(f"耗时       {el:.1f} s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
