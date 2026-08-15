#!/usr/bin/env bash
# OpenShot QtPlayer 一键构建脚本（MSYS2 UCRT64 / Windows）
# 用法：在 MSYS2 UCRT64 终端里 bash build_qtplayer.sh
# 前提：pacman 依赖已装好（见 README 安装指南）

set -euo pipefail

echo "=========================================="
echo "  OpenShot QtPlayer Build Script"
echo "  Prefix: /ucrt64"
echo "=========================================="

export PATH=/ucrt64/bin:/usr/bin:$PATH

# ---- 1. libopenshot-audio ----
AUDIO_SRC="/d/shiguang_build/libopenshot-audio"
if [ ! -d "$AUDIO_SRC" ]; then
  echo "[1/3] Cloning libopenshot-audio..."
  mkdir -p /d/shiguang_build
  cd /d/shiguang_build
  git clone --depth 1 https://github.com/OpenShot/libopenshot-audio.git
  # 关掉 ASIO（Windows 上无 SDK）
  sed -i 's/#define   JUCE_ASIO 1/#define   JUCE_ASIO 0/' /d/shiguang_build/libopenshot-audio/JuceLibraryCode/AppConfig.h
else
  echo "[1/3] libopenshot-audio already cloned, skipping"
fi

echo "  Building libopenshot-audio..."
cd "$AUDIO_SRC"
rm -rf build && mkdir build && cd build
cmake -G "MinGW Makefiles" -DCMAKE_INSTALL_PREFIX=/ucrt64 ../ 2>&1 | tail -3
mingw32-make -j$(nproc) 2>&1 | tail -5
mingw32-make install 2>&1 | tail -3
echo "  ✅ libopenshot-audio installed"

# ---- 2. libopenshot + Python binding ----
OPENSHOT_SRC="/d/拾光剪影/libopenshot"
OPENSHOT_BUILD="/d/shiguang_build/libopenshot-build"

echo "[2/3] Building libopenshot + Python binding..."
rm -rf "$OPENSHOT_BUILD" && mkdir -p "$OPENSHOT_BUILD" && cd "$OPENSHOT_BUILD"

cmake -G "MinGW Makefiles" \
  -DCMAKE_INSTALL_PREFIX=/ucrt64 \
  -DENABLE_TESTS=OFF \
  -DENABLE_EXAMPLES=OFF \
  -DENABLE_GUI=OFF \
  -DQTDIR=/ucrt64 \
  -DCMAKE_PREFIX_PATH="/ucrt64;/ucrt64/lib/cmake/Qt6" \
  -DPython3_EXECUTABLE=/ucrt64/bin/python.exe \
  -DPYTHON_EXECUTABLE=/ucrt64/bin/python.exe \
  -DENABLE_OPENMP=OFF \
  -DWANT_IMAGE_MAGICK=OFF \
  "$OPENSHOT_SRC" 2>&1 | tail -20

echo "  --- make ---"
mingw32-make -j$(nproc) 2>&1 | tail -10
mingw32-make install 2>&1 | tail -5
echo "  ✅ libopenshot + binding installed"

# ---- 3. 验证 ----
echo "[3/3] Verifying binding..."
/ucrt64/bin/python.exe -c "
import openshot
print('  openshot version:', openshot.OPENSHOT_VERSION_FULL)
p = openshot.QtPlayer()
print('  QtPlayer created:', p)
tl = openshot.Timeline(1280, 720, openshot.Fraction(30, 1))
print('  Timeline created:', tl)
print('  ✅ ALL OK')
"

echo ""
echo "=========================================="
echo "  Build complete!"
echo "  Next: copy _openshot.pyd + openshot.py"
echo "    to D:/拾光剪影/.venv312/Lib/site-packages/"
echo "  and add C:/msys64/ucrt64/bin to PATH"
echo "=========================================="
