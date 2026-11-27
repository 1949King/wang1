# -*- coding: utf-8 -*-
"""AI 运行时自检（``拾光剪影.exe --selftest``）。

为什么需要这个文件
==================
发布版长期存在一个「看起来正常、实际是残废」的盲区：重型 AI 依赖全部走
``try/except`` 懒加载（这是对的，坏一个不该拖死整个编辑器），代价是**缺依赖时
什么都不报**。于是 torch 被 spec 排除这件事，装了半年也没人发现 —— 打开软件能剪
片子，点「生图」才降级，而用户以为是自己没配模型。

本模块让产物自己交代能力：逐项尝试真实 import + 一次最小可计算操作，输出结果。
它是「打包后是否包含所有模块功能」这条硬约束的**验收工具**，不是装饰。

用法::

    拾光剪影.exe --selftest                   # 人读的表格
    拾光剪影.exe --selftest --json            # 机器读
    拾光剪影.exe --selftest --selftest-out p  # 指定报告落盘路径

设计纪律
========
1. 🔴 **所有重型 import 必须走 ``_imp()`` 动态导入，不准写成 ``import torch``。**
   PyInstaller 的模块图会跟进**函数体内**的静态 import。写成静态形式，整个
   AI 栈就会被拖进 Analysis；打包期 ``import_library`` 隔离子进程为了枚举原生
   DLL 会真的去 import 这些包 —— torch 一加载就 ``0xC0000005``，打包进程当场崩
   （实测退出码 3221225477，而且报出来的包名可能是 ``gguf`` / ``peft`` 这类
   看似无关的包，因为崩的是同一条依赖链，非常难认）。
   用字符串动态导入，PyInstaller 看不见，两边都干净。把这条改成静态 import
   会让打包直接失败 —— 不是风格问题。
2. 不加载任何模型权重 —— 只验证「库在、能算」，秒级完成。
3. 单项失败不中断，全部收集后一次性报告。
4. 数值结果要真的算出来（如 ``matmul`` / ``eigh``），只查 ``__version__``
   的话，DLL 缺一个也照样「通过」。
5. 分两档：硬失败（FAIL，拦出包）与降级（WARN，只记录）。哪些进 WARN 有明确
   门槛，见 ``OPTIONAL_CHECKS`` —— 不是「跑不过就调成 WARN」。
"""
from __future__ import annotations

import importlib
import sys
import time
import traceback


def _imp(mod: str):
    """动态导入（原因见模块 docstring 第 1 条，别改成静态 import）。"""
    return importlib.import_module(mod)


def _t_torch():
    torch = _imp("torch")
    has_cuda = torch.cuda.is_available()
    dev = torch.cuda.get_device_name(0) if has_cuda else ""

    # 🔴 这里原来写的是 `cpu=(x @ x.T).sum()` / `gpu=(a @ a).sum()`，直接把
    #    随机矩阵乘的**求和**当成了算力数字。那两个数既不衡量速度、也不检查
    #    正确性，还会出现负数（随机乘积求和的正常结果）—— 我上一次就把它当
    #    "gpu=708.7" 的性能证据读错过。改成同输入双端比对：一个数只该等于
    #    另一个数，对不上就是真的算错了，没有解释空间。
    torch.manual_seed(0)
    x = torch.randn(512, 512)
    t0 = time.perf_counter()
    want = (x @ x.T).float()
    cpu_ms = (time.perf_counter() - t0) * 1000

    gpu_part = ""
    if has_cuda:
        try:
            xg = x.to("cuda")
            torch.cuda.synchronize()
            t1 = time.perf_counter()
            got = (xg @ xg.T).float().cpu()
            torch.cuda.synchronize()
            gpu_ms = (time.perf_counter() - t1) * 1000
            # 512×512 的 float32 累加，1e-3 是宽松但足以抓错位的容差
            diff = (got - want).abs().max().item()
            if diff > 1e-3:
                raise RuntimeError(f"GPU 结果与 CPU 不一致（max|Δ|={diff:.3g}）")
            gpu_part = f"gpu={gpu_ms:.0f}ms 对齐Δ={diff:.1e}"
        except RuntimeError as e:
            if "不一致" in str(e):
                raise
            gpu_part = f"gpu 不可用（{type(e).__name__}: {str(e)[:60]}）"

    return (f"v{torch.__version__} cuda={has_cuda} {dev} "
            f"cpu={cpu_ms:.0f}ms {gpu_part}").strip()


def _t_torch_math():
    torch = _imp("torch")
    w = torch.linalg.eigvalsh(torch.eye(4) * 3.0)
    f = torch.fft.rfft(torch.randn(16))
    # 稀疏：indices 形状是 (sparse_dim, nnz)，不是 (nnz,)
    idx = torch.tensor([[0, 1], [1, 0]])
    s = torch.sparse_coo_tensor(idx, torch.tensor([1.0, 2.0]), (2, 2)).to_dense().sum().item()
    return f"eigh={w[0].item():.0f} rfft={f.shape[-1]} sparse={s:.0f}"


def _t_torchvision():
    return f"v{_imp('torchvision').__version__}"


def _t_torchaudio():
    return f"v{_imp('torchaudio').__version__}"


def _t_transformers():
    tr = _imp("transformers")
    _ = tr.AutoConfig  # 触发懒模块解析，确认映射表完好
    return f"v{tr.__version__}"


def _t_diffusers():
    return f"v{_imp('diffusers').__version__}"


def _t_diffsynth():
    mod = _imp("app.core.neural.diffsynth_compat")
    if not mod.ensure_moviepy2_compat():
        raise RuntimeError("moviepy 不可用（diffsynth_engine 无法导入）")
    de = _imp("diffsynth_engine")
    pipes = _imp("diffsynth_engine.pipelines")
    n = len([x for x in dir(pipes) if x.endswith("Pipeline")])
    return f"pipelines={n} ({de.__name__})"


def _t_tuning():
    a = _imp("accelerate")
    p = _imp("peft")
    s = _imp("safetensors")
    t = _imp("tokenizers")
    return f"accelerate={a.__version__} peft={p.__version__} st={s.__version__} tok={t.__version__}"


def _t_onnxruntime():
    ort = _imp("onnxruntime")
    return f"v{ort.__version__} providers={','.join(ort.get_available_providers())}"


def _t_numpy_scipy():
    np = _imp("numpy")
    sp = _imp("scipy")
    sig = _imp("scipy.signal")
    b, _a = sig.butter(4, 0.2)
    return f"numpy={np.__version__} scipy={sp.__version__} butter={len(b)}"


def _t_cv2():
    cv2 = _imp("cv2")
    np = _imp("numpy")
    g = cv2.cvtColor(np.zeros((16, 16, 3), np.uint8), cv2.COLOR_BGR2GRAY)
    return f"v{cv2.__version__} shape={g.shape}"


def _t_pil():
    pil = _imp("PIL")
    img = _imp("PIL.Image")
    return f"v{pil.__version__} mode={img.new('RGB', (4, 4)).mode}"


def _t_librosa():
    librosa = _imp("librosa")
    np = _imp("numpy")
    m = librosa.feature.mfcc(y=np.zeros(8000, dtype=np.float32), sr=16000, n_mfcc=4)
    return f"v{librosa.__version__} mfcc={m.shape}"


def _t_numba():
    nb = _imp("numba")
    lv = _imp("llvmlite")
    return f"numba={nb.__version__} llvmlite={lv.__version__}"


def _t_easyocr():
    return f"v{getattr(_imp('easyocr'), '__version__', '?')}"


def _t_mediapipe():
    return f"v{_imp('mediapipe').__version__}"


def _t_otio():
    """时间线交换层（FCPXML / EDL / OTIO 导入导出）。

    🔴 这里**绝不能** `import opentimelineio`：它的 C 扩展在已经加载过 Qt 绑定
    （历史实测为 PyQt6）的进程里一加载就段错误（exit 139，无 Python 栈），会把整份自检报告一起带走
    —— 第一版就这么写的，实测直接把 exe 打成静默崩溃、报告文件都没生成。
    正确做法是走产品自己的端到端路径：otio_adapter 用 find_spec 探测 +
    在**无 Qt 的独立子进程**里干活，`available_export_formats()` 正好覆盖这两步。
    """
    ad = _imp("app.core.interchange.otio_adapter")
    fmts = ad.available_export_formats()
    if not fmts:
        raise RuntimeError(
            "OTIO 适配器列表为空（子进程没跑通，或 opentimelineio 缺失）"
        )
    return f"{len(fmts)} 个适配器：{', '.join(fmts[:4])}"


def _t_render_engine():
    """渲染引擎层（PyAV 引擎）。

    `app/core/video_processing/` 同样不在 Analysis 里（见 spec 的 excludes 注释），
    它是导出视频的引擎，缺了就是「能剪不能出片」。用 is_pyav_available() 判定，
    因为这个函数的语义就是「引擎是否可用」，不靠版本号糊弄。
    """
    m = _imp("app.core.video_processing.pyav_engine")
    ok = m.is_pyav_available()
    if not ok:
        raise RuntimeError("pyav_engine.is_pyav_available() 返回 False")
    eng = m.get_pyav_engine()
    return f"{type(eng).__name__} 就绪"


def _t_plugins():
    """转场 / 特效插件是否真的被 PluginManager 加载到了。

    🔴 这是「模块在包里 ≠ 功能在」的典型样本：插件模块在 PYZ 里一个不少，
    但 PluginManager 是**按文件名扫目录**加载的（plugin_manager.py 的
    os.listdir(plugin_dir)），目录不存在时它直接 `continue`，不报错不警告。
    所以必须真建一次管理器、真数一遍插件，光查 import 是查不出来的。
    """
    pm_mod = _imp("app.core.plugin_manager")
    pm = pm_mod.PluginManager()
    got = pm.load_plugins() or []
    if not got:
        errs = ""
        try:
            errs = pm.format_load_errors(3) or ""
        except Exception as e:
            # 拿不到明细也要把「为什么拿不到」报出来，别让这层再吞一次异常
            errs = f"（错误明细读取失败：{type(e).__name__}: {e}）"
        raise RuntimeError(
            f"0 个插件被加载（目录 {getattr(pm, 'plugin_dirs', '?')}）"
            + (f"；{errs}" if errs else "")
        )
    return f"{len(got)} 个插件（目录 {len(getattr(pm, 'plugin_dirs', []))} 个）"


def _t_skills():
    """外部 Skill（``app/skills/external``）能不能真的被扫出来并注册。

    和插件是同一类坑，但定位方式不同：这里 `SKILLS_ROOT = Path(__file__).parent`
    （app/skills/__init__.py:17），冻结态 `__file__` 指向
    `_internal/app/skills/__init__.pyc` ⇒ 目录必须在磁盘上真实存在。
    模块在 PYZ 里一个不少也没用：loader 靠 os.walk 找 `SKILL.md`。

    产品侧三个入口都会调它（extension_facade:112 / project_agent_host:654 /
    extensions_module:1699），目录缺失时返回 0 且**不报错** —— 表现就是
    「拓展中心里外部 Skill 一栏空着」。
    """
    import os

    mod = _imp("app.skills.external_loader")
    n = mod.ensure_external_skills_registered()
    if not n:
        root = _imp("app.skills").EXTERNAL_SKILLS_ROOT
        raise RuntimeError(
            f"0 个外部 skill 注册（根 {root}，存在={os.path.isdir(str(root))}）"
        )
    return f"{n} 个外部 skill"


def _t_asr():
    ct = _imp("ctranslate2")
    fw = _imp("faster_whisper")
    return f"ct2={ct.__version__} fw={fw.__version__}"


def _t_av():
    a = _imp("av")
    _imp("imageio_ffmpeg")
    return f"av={a.__version__} +imageio_ffmpeg"


def _t_sklearn():
    return f"v{_imp('sklearn').__version__}"


def _t_sympy_networkx():
    sy = _imp("sympy")
    nx = _imp("networkx")
    return f"sympy={sy.__version__} nx={nx.__version__}"


def _t_gguf():
    # gguf 没有 __version__，但带量化尺寸表；用表项数证明模块逻辑真的加载了
    g = _imp("gguf")
    return f"quant_sizes={len(getattr(g, 'GGML_QUANT_SIZES', {}) or {})}"


def _t_app_engine():
    """产品自己的引擎判定链是否走得通（不加载权重）。"""
    ed = _imp("app.core.ai.execution_decider")
    if not hasattr(ed, "decide"):
        consts = [n for n in dir(ed) if n.isupper()]
        return f"已加载，导出常量 {len(consts)} 个"
    d = ed.decide()
    get = getattr(d, "get", lambda k: None)
    return f"engine={get('engine')} reason={str(get('reason'))[:60]}"


# 「已入包但冻结环境里跑不起来」的项 —— 记 WARN，不算硬失败。
#
# 为什么需要这一档：自检是发布门禁（build_release.py 拿 report["ok"] 决定
# 能不能出包）。如果某一项在冻结环境里**结构性地**无法通过，把它算成硬失败
# 只会让门禁永远红 —— 一个永远红的门禁等于没有门禁，谁都会开始忽略它。
#
# 进这一档的门槛（两项都必须满足，缺一不进）：
#   1. 文件**已经**在包里（不是漏打包）；
#   2. 产品代码对该能力**已有明确的降级路径**，失败时不会崩、不会假报可用。
#
# 当前两项的实况（2026-11-05 逐条实测，不是推测）：
#   · mediapipe —— 文件 100% 一致（非缓存文件缺口 0），但
#     `_framework_bindings.pyd` 在冻结进程里 LoadLibrary 即 1114
#     (DLL 初始化例程失败)。排除了 CRT 版本、CONCRT140 缺失、同目录冲突。
#     产品侧 app/core/ai/pose_extract_service.py 明写「发布版内嵌环境暂不支持
#     姿态解析」，属于既有降级。
#   · 时间线交换 OTIO —— opentimelineio 的原生扩展在冻结解释器里 import 即段错误
#     （连无 Qt 的全新进程也一样；同一批文件用普通解释器 import 正常）。
#     产品侧 otio_adapter.__init__ 明写「主进程绝不能 import opentimelineio」，
#     读写走独立子进程；子进程挂了只让 available_export_formats() 返回空表，
#     GUI 不受影响。
OPTIONAL_CHECKS = {"mediapipe", "时间线交换 OTIO"}

CHECKS = [
    ("torch",              _t_torch),
    ("torch 数学核",        _t_torch_math),
    ("torchvision",        _t_torchvision),
    ("torchaudio",         _t_torchaudio),
    ("transformers",       _t_transformers),
    ("diffusers",          _t_diffusers),
    ("diffsynth_engine",   _t_diffsynth),
    ("微调栈",              _t_tuning),
    ("onnxruntime",        _t_onnxruntime),
    ("numpy/scipy",        _t_numpy_scipy),
    ("opencv",             _t_cv2),
    ("pillow",             _t_pil),
    ("librosa",            _t_librosa),
    ("numba",              _t_numba),
    ("easyocr",            _t_easyocr),
    ("mediapipe",          _t_mediapipe),
    ("语音转写",            _t_asr),
    ("PyAV / ffmpeg",      _t_av),
    ("sklearn",            _t_sklearn),
    ("sympy/networkx",     _t_sympy_networkx),
    ("gguf",               _t_gguf),
    ("时间线交换 OTIO",      _t_otio),
    ("渲染引擎层",           _t_render_engine),
    ("转场/特效插件",         _t_plugins),
    ("外部技能库",            _t_skills),
    ("产品引擎判定",         _t_app_engine),
]


def _assemble(checks: list, runtime: dict, only: str | None = None) -> dict:
    """把已完成项组装成报告。

    ``ok`` 只由**硬失败**决定（见 OPTIONAL_CHECKS）：降级项记 warned，不拦出包。
    """
    ok = sum(1 for c in checks if c["ok"])
    warned = sum(1 for c in checks if not c["ok"] and c.get("optional"))
    hard = [c["name"] for c in checks if not c["ok"] and not c.get("optional")]
    report = {
        "frozen": bool(getattr(sys, "frozen", False)),
        "python": sys.version.split()[0],
        "runtime_pack": runtime,
        "checks": checks,
        "passed": ok,
        "total": len(checks),
        "warned": warned,
        "hard_failed": hard,
        "ok": not hard,
    }
    if only:
        # 单跑不是全量验收，别让调用方把它当成「全绿」
        report["only"] = only
    return report


def run(verbose: bool = False, only: str | None = None, on_progress=None) -> dict:
    """逐项自检，返回可序列化报告。

    ``only`` 只跑名字包含它的项（``--selftest --only mediapipe``）。

    这个开关不是为了省时间，是为了**判真伪**：某些原生库在「同进程里已经加载了
    别的东西」时会失败，但在产品真实的**独立子进程**里是好的（姿态解析就是这样：
    ``app/core/ai/pose_worker.py`` 是独立进程）。全项自检把几十个库塞进一个进程，
    会得到比产品更差的结论。单跑一项 = 一个干净进程 = 与产品子进程同条件。

    ``on_progress(report)`` 每完成一项回调一次。存在的理由很实际：某些原生库
    import 会**直接把进程干掉**（不是抛异常，是段错误），那种情况下异常处理一行
    都进不去。有了逐项回调，报告至少写到崩溃前的那一项，能直接看出谁是元凶 ——
    否则只能拿到一个空文件和 exit 139。
    """
    try:
        rp = _imp("app.core.runtime_pack")
        runtime = rp.describe()
    except Exception:
        runtime = {"present": False, "path": "", "packages": 0, "size_mb": 0.0}

    picked = CHECKS
    if only:
        key = only.strip().lower()
        picked = [(n, f) for n, f in CHECKS if key in n.lower()]

    checks = []
    for name, fn in picked:
        entry = {"name": name, "ok": False, "detail": "",
                 "optional": name in OPTIONAL_CHECKS}
        try:
            entry["detail"] = str(fn())
            entry["ok"] = True
        except Exception as e:
            entry["detail"] = f"{type(e).__name__}: {e}"
            if verbose:
                traceback.print_exc()
        checks.append(entry)
        if on_progress is not None:
            try:
                on_progress(_assemble(checks, runtime, only or None))
            except Exception:
                pass  # stability-gate: allow-swallow（进度写盘失败不该影响自检本身；末尾还会统一写一次报告）

    return _assemble(checks, runtime, only or None)


def format_text(report: dict) -> str:
    rt = report["runtime_pack"]
    lines = [
        "=" * 72,
        f"拾光剪影 AI 运行时自检    冻结={report['frozen']}  Python {report['python']}",
    ]
    if rt.get("present"):
        lines.append(f"AI 内核   {rt['size_mb']:.0f} MB / {rt['packages']} 个包")
        lines.append(f"          {rt['path']}")
    else:
        lines.append("AI 内核   **未安装**（runtime/ 不存在）—— AI 生成类功能将全部降级")
    lines.append("=" * 72)
    for c in report["checks"]:
        if c["ok"]:
            tag = "PASS"
        elif c.get("optional"):
            tag = "WARN"
        else:
            tag = "FAIL"
        lines.append(f"[{tag}] {c['name']:<16} {c['detail']}")
    lines.append("-" * 72)
    tail = f"{report['passed']}/{report['total']} 通过"
    if report.get("warned"):
        tail += f"，{report['warned']} 项降级（见上 WARN，已入包但冻结环境跑不起来）"
    if report.get("only"):
        tail += f"（只见「{report['only']}」，非全量验收）"
    lines.append(tail)
    return "\n".join(lines)


def _attach_console() -> None:
    """发布版是 console=False（无控制台），从 cmd 调用时把输出接回父控制台。"""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        ctypes.windll.kernel32.AttachConsole(-1)  # ATTACH_PARENT_PROCESS
    except Exception:
        pass  # stability-gate: allow-swallow（双击运行没有父控制台，属正常分支；JSON 文件是主输出通道）


def emit(as_json: bool = False, out_path: str = "", only: str = "") -> int:
    """执行自检 → 写 JSON 文件（发布版唯一可靠的输出通道）→ 尝试打屏。

    Args:
        only: 只跑名字包含它的项（见 ``run()`` 的说明）。

    Returns:
        进程退出码：0 全通过，1 有失败项。
    """
    import json
    import os
    import tempfile

    path = out_path or os.path.join(tempfile.gettempdir(), "shiguang_selftest.json")

    def _flush(partial: dict) -> None:
        """每完成一项就落一次盘 —— 进程被原生库打死时，报告仍有内容。"""
        tmp = path + ".part"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(partial, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)

    # run() 内部任何一项抛的异常都会被接住；真正的风险是某项原生库 import
    # 直接把进程打死（段错误，异常处理一行都进不去）—— 那种情况下
    # _flush 已经把这个报告写到了崩溃前那一项，path 里不会是空的。
    report = run(only=only or None, on_progress=_flush)
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
    except OSError as e:
        print(f"（自检报告写盘失败：{e}）")  # stability-gate: allow-print（CLI 报告器，人读输出必须走 stdout）

    if as_json:
        print(json.dumps(report, ensure_ascii=False, indent=2))  # stability-gate: allow-print（--selftest --json 的唯一出口）
    else:
        _attach_console()
        print(format_text(report))  # stability-gate: allow-print（人读表格，logger 会写进日志文件用户看不见）
        print(f"\n报告已写入：{path}")  # stability-gate: allow-print（告诉用户报告落在哪，属 CLI 输出）
    return 0 if report["ok"] else 1
