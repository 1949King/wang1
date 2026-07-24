import os
import subprocess
import sys
import shutil

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
BUILD_DIR = os.path.join(SCRIPT_DIR, 'build')
FFMPEG_ROOT = r"C:\ffmpeg_win_dev"

print("=" * 60)
print("  C++ Video Engine Build")
print("=" * 60)

# Step 1: Clean build dir
print("\n[1/4] Preparing build directory...")
if os.path.exists(BUILD_DIR):
    shutil.rmtree(BUILD_DIR)
os.makedirs(BUILD_DIR, exist_ok=True)
print(f"  Build dir: {BUILD_DIR}")

# Step 2: CMake configure
print("\n[2/4] Running CMake configure...")
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
print(f"  Command: {' '.join(cmake_cmd)}")
result = subprocess.run(cmake_cmd, capture_output=True, text=True)
print("=== STDOUT ===")
print(result.stdout[-3000:] if len(result.stdout) > 3000 else result.stdout)
print("=== STDERR ===")
print(result.stderr[-3000:] if len(result.stderr) > 3000 else result.stderr)
print(f"  Return code: {result.returncode}")

if result.returncode != 0:
    print("\n  CMake configure FAILED!")
    sys.exit(1)
print("  CMake configure OK")

# Step 3: Build
print("\n[3/4] Building...")
build_cmd = [
    sys.executable, '-m', 'cmake',
    '--build', '.',
    '--config', 'Release',
    '--parallel',
]

result = subprocess.run(build_cmd, capture_output=True, text=True)
print("=== STDOUT ===")
print(result.stdout[-3000:] if len(result.stdout) > 3000 else result.stdout)
print("=== STDERR ===")
print(result.stderr[-3000:] if len(result.stderr) > 3000 else result.stderr)
print(f"  Return code: {result.returncode}")

if result.returncode != 0:
    print("\n  Build FAILED!")
    sys.exit(1)

# Step 4: Find and copy output
print("\n[4/4] Looking for output...")
import glob
pyd_files = glob.glob(os.path.join(BUILD_DIR, 'Release', '*.pyd'))
print(f"  Found {len(pyd_files)} .pyd files in Release/")
for p in pyd_files:
    print(f"    {p}")

dll_files = glob.glob(os.path.join(BUILD_DIR, '**', '*.dll'), recursive=True)
print(f"  Found {len(dll_files)} .dll files")

# Also check for .lib and .exp
lib_files = glob.glob(os.path.join(BUILD_DIR, '**', '*.lib'), recursive=True)
print(f"  Found {len(lib_files)} .lib files")

# Check if it built a DLL instead of PYD
for root, dirs, files in os.walk(BUILD_DIR):
    for f in files:
        if f.startswith('video_engine') and (f.endswith('.dll') or f.endswith('.pyd')):
            src = os.path.join(root, f)
            dest = os.path.join(SCRIPT_DIR, f)
            shutil.copy(src, dest)
            print(f"  Copied: {f} -> {dest}")

print("\n" + "=" * 60)
print("  Build Complete!")
print("=" * 60)
