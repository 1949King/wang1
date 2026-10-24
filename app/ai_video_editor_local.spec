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
# 重 AI 运行时（torch/torchvision/torchaudio/transformers/numba/onnxruntime/
# easyocr/librosa）在项目内均为函数内懒加载（无顶层 import），打包时排除之：
#   1) 打包阶段 PyInstaller 会 __import__ 模块图收集 DLL，这些原生库在 ~8GB 空闲
#      内存下触发原生访问违例(0xC0000005)，导致打包进程崩溃；
#   2) 排除后对应 AI 特性（生视频/生图/语音识别/超分等）在发布版中优雅降级，
#      由调用处既有 try/except 兜底，不影响核心剪辑/导出/3D 导演台。
# 这些 AI 运行时后续可作独立安装包分发（见 docs/商用化改造路线图.md P2）。
# scipy 已从 hiddenimports 移除：scipy._external.array_api_compat 会
# 在 import 阶段反向导入 torch/dask/cupy，触发 torch.cuda 原生 DLL 加载，
# 在 PyInstaller 的 import_library 隔离子进程中导致访问违例(0xC0000005)。
# scipy 在项目内均为函数内懒加载（无顶层 import），移除后相关特性优雅降级。
_hidden = [
    'faster_whisper', 'imageio',
]

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
] + _hidden

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
    # 重 AI 运行时改为 excluded：避免打包期导入崩溃，且这些特性全部懒加载可优雅降级。
    # app.core.video_processing 为 C++/MLT/PyAV 原生引擎层（含未编译的
    # cpp_engine C++ 源码与 FFmpeg 原生 DLL），import_library 扫描其原生
    # DLL 时触发访问违例(0xC0000005)。所有调用方均已用 try/except 懒加载，
    # 打包后自动回退 FFmpeg CLI 渲染路径。
    excludes=['tkinter', 'yt_dlp', 'curl_cffi',
              'torch', 'torchvision', 'torchaudio',
              'transformers', 'numba', 'onnxruntime',
              'easyocr', 'librosa', 'tensorboard',
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
