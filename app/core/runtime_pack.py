# -*- coding: utf-8 -*-
"""把随包分发的 ``runtime/`` 目录接进 ``sys.path``（本产品 AI 内核的加载入口）。

为什么存在这个文件
==================
``app/ai_video_editor_local.spec:60-71`` 记载了一条硬事实：**torch 进不了
PyInstaller 的 Analysis**。打包期 PyInstaller 会 ``__import__`` 模块图并收集原生
DLL，torch 的原生库在 ``import_library`` 隔离子进程里触发 ``0xC0000005`` 访问违例，
打包进程直接崩掉。所以此前发布版的 ``excludes`` 里塞着 torch/torchvision/
transformers/diffusers/onnxruntime/easyocr/librosa —— **装完是个剪辑器，不是
AI 生成工具**，生图/生视频/语音识别全部静默降级。

解法不是「把 torch 塞进 PyInstaller」，而是换一条装载路径：

    exe 同级 ``runtime/``  <-- 纯文件目录，绕开 PyInstaller 的模块图与 DLL 收集
        torch/  torchvision/  transformers/  diffusers/  ...
    启动时本模块把 ``runtime/`` 插到 ``sys.path`` 最前面 → ``import torch`` 命中它

好处不止「能跑」：
  1. 不触发 0xC0000005 —— PyInstaller 全程不碰这些包；
  2. 体积可裁 —— 目录是普通文件，可以删 ``*.lib``/``include`` 等链接期产物
     （见 ``.workbuddy/tmp/make_runtime_pack.py``）；
  3. 可拆可换 —— 用户能单独下载/升级 AI 内核，不必重装 1.9 GB 编辑器本体。

源码运行时不生效（``runtime/`` 不存在就直接返回），开发环境仍用 ``.venv312``。
"""
from __future__ import annotations

import os
import sys

#: runtime 目录名（与 exe 同级）
RUNTIME_DIRNAME = "runtime"

_applied = False
_runtime_dir = ""


def app_root() -> str:
    """返回应用根目录。

    - 冻结态（PyInstaller onedir）：``exe`` 所在目录
    - 源码态：本文件在 ``<root>/app/core/`` 下，上溯三级
    """
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    here = os.path.abspath(__file__)
    return os.path.dirname(os.path.dirname(os.path.dirname(here)))


def runtime_dir() -> str:
    """返回 ``runtime/`` 的绝对路径（不保证存在）。"""
    return os.path.join(app_root(), RUNTIME_DIRNAME)


def ensure_runtime_path() -> str:
    """把 ``runtime/`` 插到 ``sys.path`` 首位。幂等。

    Returns:
        命中的 runtime 目录路径；目录不存在（源码运行）时返回空字符串。
    """
    global _applied, _runtime_dir
    if _applied:
        return _runtime_dir

    d = runtime_dir()
    if not os.path.isdir(d):
        _applied = True
        _runtime_dir = ""
        return ""

    # 插到最前面：runtime 里的包必须优先于任何同名的兜底副本
    while d in sys.path:
        sys.path.remove(d)
    sys.path.insert(0, d)

    # Windows 上第三方原生扩展（ctranslate2 / av / onnxruntime）靠 DLL 搜索目录
    # 找同级 DLL；PyInstaller 的 _internal 由 bootloader 处理，这里补 runtime 侧。
    if os.name == "nt" and hasattr(os, "add_dll_directory"):
        for sub in _native_dirs(d):
            try:
                os.add_dll_directory(sub)
            except OSError:
                pass  # stability-gate: allow-swallow（目录不存在/已在搜索路径，add_dll_directory 的正常拒绝）

    _applied = True
    _runtime_dir = d
    return d


def _native_dirs(root: str, limit: int = 40):
    """列出 runtime 下含 ``.pyd``/``.dll`` 的目录（浅层，够用且快）。"""
    out = []
    try:
        tops = sorted(os.listdir(root))
    except OSError:
        return out
    for name in tops:
        sub = os.path.join(root, name)
        if not os.path.isdir(sub):
            continue
        try:
            names = os.listdir(sub)
        except OSError:
            continue
        if any(n.lower().endswith((".pyd", ".dll")) for n in names):
            out.append(sub)
            if len(out) >= limit:
                break
    return out


def available() -> bool:
    """``runtime/`` 是否存在（= 这个安装有没有 AI 内核）。"""
    return bool(runtime_dir()) and os.path.isdir(runtime_dir())


def describe() -> dict:
    """供「设置 / 关于」页展示的内核状态。只读文件系统，不 import 任何重包。"""
    d = runtime_dir()
    info = {"present": False, "path": d, "packages": 0, "size_mb": 0.0}
    if not os.path.isdir(d):
        return info
    info["present"] = True
    total = 0
    pkgs = 0
    for name in os.listdir(d):
        p = os.path.join(d, name)
        if not os.path.isdir(p):
            continue
        pkgs += 1
        for dp, _dn, fn in os.walk(p):
            for f in fn:
                try:
                    total += os.path.getsize(os.path.join(dp, f))
                except OSError:
                    pass  # stability-gate: allow-swallow（统计体积时单个文件读不到就跳过，不影响可用性判定）
    info["packages"] = pkgs
    info["size_mb"] = round(total / 1048576.0, 1)
    return info
