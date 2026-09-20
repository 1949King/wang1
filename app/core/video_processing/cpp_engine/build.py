import os
import subprocess
import sys
import shutil
import logging

# ⚠️ logger 必须在使用之前定义：本脚本从第 1 行日志起就要用它。
# （历史 Bug：logger 曾被错放在文件中部 "Step 4" 处，导致整个脚本一执行即 NameError）
logger = logging.getLogger("AI短剧编辑器.core.video_processing.cpp_engine.build")

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
BUILD_DIR = os.path.join(SCRIPT_DIR, 'build')
FFMPEG_ROOT = r"C:\ffmpeg_win_dev"

logger.info('=' * 60)
logger.info('  C++ Video Engine Build')
logger.info('=' * 60)

# Step 1: Clean build dir
logger.info('\n[1/4] Preparing build directory...')
if os.path.exists(BUILD_DIR):
    shutil.rmtree(BUILD_DIR)
os.makedirs(BUILD_DIR, exist_ok=True)
logger.info(f'  Build dir: {BUILD_DIR}')

# Step 2: CMake configure
logger.info('\n[2/4] Running CMake configure...')
cmake_cmd = [
    sys.executable, '-m', 'cmake',
    SCRIPT_DIR,
    '-G', 'Visual Studio 17 2022',
    '-A', 'x64',
    '-DCMAKE_BUILD_TYPE=Release',
    f'-DFFMPEG_ROOT={FFMPEG_ROOT}',
    f'-DCMAKE_PREFIX_PATH={SCRIPT_DIR}',
]

os.chdir(BUILD_DIR)
logger.info(f"  Command: {' '.join(cmake_cmd)}")
result = subprocess.run(cmake_cmd, capture_output=True, text=True)
logger.info('=== STDOUT ===')
logger.info(result.stdout[-3000:] if len(result.stdout) > 3000 else result.stdout)
logger.info('=== STDERR ===')
logger.info(result.stderr[-3000:] if len(result.stderr) > 3000 else result.stderr)
logger.info(f'  Return code: {result.returncode}')

if result.returncode != 0:
    logger.info('\n  CMake configure FAILED!')
    sys.exit(1)
logger.info('  CMake configure OK')

# Step 3: Build
logger.info('\n[3/4] Building...')
build_cmd = [
    sys.executable, '-m', 'cmake',
    '--build', '.',
    '--config', 'Release',
    '--parallel',
]

result = subprocess.run(build_cmd, capture_output=True, text=True)
logger.info('=== STDOUT ===')
logger.info(result.stdout[-3000:] if len(result.stdout) > 3000 else result.stdout)
logger.info('=== STDERR ===')
logger.info(result.stderr[-3000:] if len(result.stderr) > 3000 else result.stderr)
logger.info(f'  Return code: {result.returncode}')

if result.returncode != 0:
    logger.info('\n  Build FAILED!')
    sys.exit(1)

# Step 4: Find and copy output
logger.info('\n[4/4] Looking for output...')
import glob

pyd_files = glob.glob(os.path.join(BUILD_DIR, 'Release', '*.pyd'))
logger.info(f'  Found {len(pyd_files)} .pyd files in Release/')
for p in pyd_files:
    logger.info(f'    {p}')

dll_files = glob.glob(os.path.join(BUILD_DIR, '**', '*.dll'), recursive=True)
logger.info(f'  Found {len(dll_files)} .dll files')

# Also check for .lib and .exp
lib_files = glob.glob(os.path.join(BUILD_DIR, '**', '*.lib'), recursive=True)
logger.info(f'  Found {len(lib_files)} .lib files')

# Check if it built a DLL instead of PYD
for root, dirs, files in os.walk(BUILD_DIR):
    for f in files:
        if f.startswith('video_engine') and (f.endswith('.dll') or f.endswith('.pyd')):
            src = os.path.join(root, f)
            dest = os.path.join(SCRIPT_DIR, f)
            shutil.copy(src, dest)
            logger.info(f'  Copied: {f} -> {dest}')

logger.info('\n' + '=' * 60)
logger.info('  Build Complete!')
logger.info('=' * 60)
