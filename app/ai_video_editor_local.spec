# -*- mode: python ; coding: utf-8 -*-
"""AI短剧编辑器 PyInstaller 打包配置（onedir 目录模式）。

补齐缺失的运行时资源，保证打包后 3D 导演台 / AI 画布 / FFmpeg 导出可用：
  - vendor/shiguang-canvas/dist     前端构建产物（React 画布）
  - vendor/shiguang-canvas/public   人偶模型 + 提示词库
  - thirdparty/ffmpeg               FFmpeg 二进制
  - app/data                        运行时数据（模型池/平台模板/记忆缓存）
  - app/config.json                 运行时配置
  - license/                        授权模块（入口 main_qt6.py 直接导入）
  - app/modules/lego/{effects,transitions}  特效/转场数据

用法（在项目根目录执行）：
    .venv312\\Scripts\\pyinstaller.exe app/ai_video_editor_local.spec --noconfirm
"""
import os
import sys
from PyInstaller.utils.hooks import collect_data_files

# SPECPATH 即 spec 所在目录（app/）；项目根为上一级
_SPEC_DIR = os.path.abspath(SPECPATH)
_ROOT = os.path.abspath(os.path.join(_SPEC_DIR, os.pardir))

# ========== OpenCV FFmpeg 插件：运行时动态加载，PyInstaller 收集不到，必须显式加入 ==========
# 没有它，cv2.VideoCapture 打不开任何视频 → 预览全黑但声音正常
import cv2
_cv2_dir = os.path.dirname(cv2.__file__)
_cv2_ffmpeg_dll = None
_cv2_ffmpeg_dll_name = None
for _f in os.listdir(_cv2_dir):
    if _f.startswith('opencv_videoio_ffmpeg') and _f.endswith('.dll'):
        _cv2_ffmpeg_dll = os.path.join(_cv2_dir, _f)
        _cv2_ffmpeg_dll_name = _f
        break
binaries = []
if _cv2_ffmpeg_dll and os.path.exists(_cv2_ffmpeg_dll):
    binaries.append((_cv2_ffmpeg_dll, '.'))  # 放到 exe 同级，cv2 运行时会在 PATH 中查找

datas = [
    # 画布前端构建产物（3D 导演台 + AI 画布）
    (os.path.join(_ROOT, 'vendor', 'shiguang-canvas', 'dist'), 'vendor/shiguang-canvas/dist'),
    # 画布公开资源（BodyKun/BodyChan 人偶模型 + 提示词库）
    (os.path.join(_ROOT, 'vendor', 'shiguang-canvas', 'public'), 'vendor/shiguang-canvas/public'),
    # FFmpeg 二进制（ffmpeg/ffprobe/ffplay）
    (os.path.join(_ROOT, 'thirdparty', 'ffmpeg'), 'thirdparty/ffmpeg'),
    # 运行时数据（模型池/平台模板/记忆/提示词缓存）
    (os.path.join(_ROOT, 'app', 'data'), 'app/data'),
    # 运行时配置文件
    (os.path.join(_ROOT, 'app', 'config.json'), '.'),
    # 特效 / 转场数据（运行时加载的 JSON）
    (os.path.join(_ROOT, 'app', 'modules', 'lego', 'effects'), 'app/modules/lego/effects'),
    (os.path.join(_ROOT, 'app', 'modules', 'lego', 'transitions'), 'app/modules/lego/transitions'),
    # 授权模块（入口 main_qt6.py 直接 from license.license_manager import ...）
    (os.path.join(_ROOT, 'license'), 'license'),
    # 模式 B 姿态解析 worker（纯脚本不被 import，子进程按路径执行；
    # 发布版内嵌解释器不可用时诚实降级，脚本收录仅为完整性）
    (os.path.join(_ROOT, 'app', 'core', 'ai', 'pose_worker.py'), 'app/core/ai'),
]

# 收集隐式依赖（仅保留「核心包」必需、且体积可控的包）。
#
# ===== AI 内核不进 PyInstaller（重要，别改回去）=====
# torch / transformers / diffusers 等**永远留在 excludes**，但它们**不是被砍掉的功能**：
# 它们以普通目录形态随包分发在 `<exe 同级>/runtime/`，启动时由
# `app/core/runtime_pack.py::ensure_runtime_path()` 注入 sys.path 加载。
#
# 为什么不能进 PyInstaller：
#   1) 打包期 PyInstaller 会 __import__ 模块图收集原生 DLL，torch 的原生库在
#      import_library 隔离子进程里触发原生访问违例(0xC0000005)，打包进程直接崩
#      （实测：`SubprocessDiedError: Isolated subprocess crashed while importing
#      package 'peft'` —— 注意报的包名是 peft 不是 torch，因为链条是被依赖拖进去的）；
#   2) 运行时目录可裁可换（删 *.lib / include 等链接期产物，见
#      scripts/make_runtime_pack.py），而 PyInstaller 产物不可裁。
#
# 🔴 纪律：`app/core/ai_runtime_selftest.py` 里的 `import torch` 写在函数体内也
#    逃不掉 —— PyInstaller 的模块图会跟进函数级 import。所以凡是 runtime/ 供给的
#    顶层包，**必须**同时出现在下面的 excludes 里，否则打包必崩。
#
# 反面参考：曾把 pytorch 从 excludes 拿掉、想「直接打进包里」，结果就是上面那条崩。
_hidden = [
    'faster_whisper', 'imageio',
]


def _app_modules():
    """枚举 app/ 下**全部**模块，塞进 hiddenimports。

    为什么必须自动枚举：产品的模块体系是「按目录/按名字动态加载」的
    （导航切换、插件目录扫描、引擎注册表都是运行时才算模块名），
    PyInstaller 的静态分析一个都看不见。手写 hiddenimports 实测漏了 107 个：
    `app.core.editor_scheduler`、`app.modules.lego.timeline_widget`、
    27 个特效/转场插件全都不在包里 —— 打包产物看着能启动，一点就到
    ModuleNotFoundError。手写清单这种形式的错是必然的，不是不小心。
    """
    skip = {'__pycache__', 'tests', 'temp', '_retired', 'packaging_env'}
    # 与 excludes 保持一致：这一层已被显式排除，再塞进 hiddenimports 只会
    # 让 Analysis 报一堆 "excluded module" 警告，且它确实进不了包。
    skip_prefix = ('app.core.video_processing',)
    out = []
    for dp, dn, fn in os.walk(os.path.join(_ROOT, 'app')):
        dn[:] = [d for d in dn if d not in skip]
        for f in fn:
            if not f.endswith('.py'):
                continue
            rel = os.path.relpath(os.path.join(dp, f), _ROOT)
            mod = rel[:-3].replace(os.sep, '.')
            if mod.endswith('.__init__'):
                mod = mod[: -len('.__init__')]
            if mod.startswith(skip_prefix):
                continue
            out.append(mod)
    return sorted(set(out))


_app = _app_modules()
print(f"[spec] 枚举 app 模块 {len(_app)} 个 → hiddenimports")

# 合并显式 hiddenimports
hiddenimports = [
    # PyQt6
    'PyQt6.QtCore', 'PyQt6.QtWidgets', 'PyQt6.QtGui',
    'PyQt6.QtMultimedia', 'PyQt6.QtMultimediaWidgets',
    'PyQt6.QtWebEngineWidgets', 'PyQt6.QtWebEngineCore',
    'PyQt6.QtWebChannel', 'PyQt6.QtNetwork', 'PyQt6.QtPrintSupport',
    # 本地包
    'app.modules.lego', 'app.core', 'app.modules', 'license',
    # 第三方显式声明
    'moviepy', 'PIL', 'numpy', 'cv2', 'psutil',
    'aiohttp', 'requests', 'imageio', 'imageio_ffmpeg',
] + _hidden + _app

# 收集数据文件（仅保留核心包所需的模型/资源）
datas += collect_data_files('faster_whisper')

a = Analysis(
    # 入口用根目录 main_qt6.py（绝对导入，PyInstaller 下无相对导入问题）
    [os.path.join(_ROOT, 'main_qt6.py')],
    pathex=[_ROOT, _SPEC_DIR],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # yt_dlp 仅被 transformers.video_utils 懒加载（从 YouTube 下载视频才用），
    # 且其 hook 处理 curl_cffi 时会在 isolated 子进程卡死，故排除之。
    # AI 内核整段排除 —— 由 runtime/ 供给，理由见上方长注释。
    # 注意：这里排的是「顶层包名」，PyInstaller 按前缀匹配，'torch' 不会覆盖 'torchao'。
    excludes=['tkinter', 'yt_dlp', 'curl_cffi',
              # —— torch 栈 ——
              'torch', 'torchvision', 'torchaudio', 'torchao',
              'transformers', 'diffusers', 'accelerate', 'peft',
              'diffsynth_engine', 'sentencepiece', 'huggingface_hub',
              # —— 视觉 / 音频 / OCR（重型原生）——
              'mediapipe', 'easyocr', 'librosa', 'numba', 'llvmlite',
              'onnxruntime', 'skimage', 'scikit-image',
              # —— 数值 / 科学计算 ——
              'sklearn', 'sympy', 'jax', 'jaxlib',
              # —— 被上面拖进来的大件 ——
              'modelscope', 'trimesh', 'matplotlib',
              # —— gguf：它由 runtime/ 供给，而且**必须排掉** ——
              # gguf/vocab.py:12 → import sentencepiece，而 sentencepiece 与
              # PyQt6 有导入顺序依赖的原生冲突（先 Qt 后 sentencepiece 必
              # 0xC0000005；反过来正常）。PyInstaller 的隔离导入子进程里 PyQt6
              # 先被加载，于是 import_library('gguf') 必崩 —— 报错显示
              # `crashed while importing package 'gguf'`，但真凶是 sentencepiece。
              # 把 gguf 排除后子进程不再碰它，构建恢复正常。
              'gguf',
              'tensorboard',
              # —— opentimelineio：与 torch/gguf 同一类崩溃 ——
              # 加进 hiddenimports（app.core.interchange 依赖它）后，PyInstaller
              # 的 import_library 隔离子进程在 PyQt6 已加载的情况下 import 它，
              # 直接 0xC0000005：
              #   SubprocessDiedError: ... importing package 'opentimelineio',
              #   exit code 3221225477
              # 它自带原生扩展 _opentimelineio.pyd，属于「加载期与 Qt 冲突」那一族。
              # 处理方式：不进 Analysis，改由 runtime/ 供给（同 torch）。
              'opentimelineio',
              # —— 原生引擎层（含未编译 cpp_engine，collect 期会 0xC0000005）——
              'app.core.video_processing'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='拾光剪影',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[
        # OpenCV 原生 DLL：UPX 压缩后会导致运行时加载失败 / VideoCapture 打不开
        'cv2.pyd',
        # Qt WebEngine 核心：UPX 压缩会导致沙箱进程崩溃
        'Qt6WebEngineCore.dll',
        'QtWebEngineProcess.exe',
    ] + ([_cv2_ffmpeg_dll_name] if _cv2_ffmpeg_dll_name else []),
    name='拾光剪影',
)
