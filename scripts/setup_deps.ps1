# 拾光剪影 — 补齐核心依赖与 Whisper 模型
# 用法: 在项目根目录执行  powershell -ExecutionPolicy Bypass -File scripts\setup_deps.ps1

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $Root

$Py = Join-Path $Root ".venv312\Scripts\python.exe"
if (-not (Test-Path $Py)) {
    Write-Error "未找到 .venv312，请先创建虚拟环境"
}

$env:HF_ENDPOINT = "https://hf-mirror.com"
Write-Host "==> Python: $Py"
Write-Host "==> HF_ENDPOINT=$env:HF_ENDPOINT"

Write-Host "`n==> 安装 CUDA PyTorch (cu124) ..."
& $Py -m pip install --upgrade pip
& $Py -m pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu124

Write-Host "`n==> 安装字幕/OCR/音频依赖 ..."
& $Py -m pip install `
    "faster-whisper>=1.0.0" `
    "transformers>=4.30.0" `
    "easyocr>=1.7.0" `
    "librosa>=0.10.0" `
    "numba>=0.58.0" `
    "onnxruntime>=1.14.0" `
    "imageio-ffmpeg>=0.4.0" `
    "opencv-python-headless>=4.8.0" `
    "Pillow>=10.0.0" `
    "numpy>=1.24.0" `
    "moviepy>=1.0.3" `
    "PySide6==6.10.2" `
    "PySide6-Essentials==6.10.2" `
    "PySide6-Addons==6.10.2" `
    "shiboken6==6.10.2"

Write-Host "`n==> 预下载 Whisper tiny/base 模型 ..."
& $Py -c @"
import os, sys
sys.path.insert(0, '.')
os.environ.setdefault('HF_ENDPOINT', 'https://hf-mirror.com')
from app.core.ai import whisper_asr
whisper_asr._WHISPER_TYPE = None
whisper_asr._MODEL_CACHE.clear()
for size in ('tiny', 'base'):
    print('loading', size, flush=True)
    m = whisper_asr._load_model(size)
    print(size, 'OK' if m else 'FAIL', flush=True)
"@

Write-Host "`n==> 验收 ..."
& $Py -c @"
import sys
req = ['PySide6','cv2','torch','transformers','faster_whisper','easyocr','PIL','numpy','librosa','moviepy']
miss=[]
for m in req:
    try: __import__(m)
    except Exception as e: miss.append(f'{m}:{e}')
import torch
print('cuda', torch.cuda.is_available())
from app.core.ai.whisper_asr import is_available, get_backend
print('asr', is_available(), get_backend())
print('MISS', miss if miss else 'none')
sys.exit(1 if miss else 0)
"@

Write-Host "`n完成。首次 AI 字幕建议有网络（HF 镜像已配置）。"
