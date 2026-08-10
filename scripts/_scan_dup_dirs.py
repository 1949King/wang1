"""扫描项目代码中的同名重复目录（排除虚拟环境和第三方库）"""
import os

ROOT = r'd:\拾光剪影'
SKIP_ROOT_DIRS = {
    '.venv', '.venv312', 'venv', 'bmf_env', 'packaging_env',
    'libopenshot', 'openshot-qt', 'thirdparty',
    '.git', '.workbuddy', '.claude', '.trae', '.cursor',
    'node_modules', '__pycache__', '新建文件夹',
    'app/packaging_env',
}

dirmap = {}
for dp, dirs, fs in os.walk(ROOT):
    parts = os.path.relpath(dp, ROOT).split(os.sep)
    if any(parts[0] == s or parts[0].startswith(s) for s in SKIP_ROOT_DIRS):
        continue
    if any(p in SKIP_ROOT_DIRS for p in parts):
        continue
    # 跳过 site-packages
    if 'site-packages' in parts:
        continue
    for d in list(dirs):
        if d in SKIP_ROOT_DIRS or d == 'site-packages':
            continue
        full = os.path.join(dp, d)
        # 只统计 Python 包目录
        try:
            entries = os.listdir(full)
        except OSError:
            continue
        if not any(f.endswith('.py') for f in entries):
            continue
        dirmap.setdefault(d, []).append(full)

print('=== 项目代码同名重复目录（出现>=2次） ===')
found = False
for d, paths in sorted(dirmap.items()):
    if len(paths) >= 2:
        found = True
        print(f'\n[{d}] {len(paths)}处:')
        for p in paths:
            rel = os.path.relpath(p, ROOT)
            # 统计该目录下py文件数
            pycount = sum(1 for _ in os.scandir(p) if _.name.endswith('.py'))
            print(f'  {rel}  ({pycount}个.py文件)')

if not found:
    print('（无重复目录）')
