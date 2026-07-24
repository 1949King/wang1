# -*- mode: python ; coding: utf-8 -*-
# 修复 P0-D: 入口从废弃的 ai_video_editor_local.py 改为 main_qt6.py
# 生成命令: pyinstaller main_qt6.spec --noconfirm

a = Analysis(
    ['main_qt6.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('modules/lego/plugins', 'modules/lego/plugins'),
        ('modules/lego/effects', 'modules/lego/effects'),
        ('modules/lego/transitions', 'modules/lego/transitions'),
        ('config', 'config'),
        ('data/platform_templates', 'data/platform_templates'),
    ],
    hiddenimports=[
        'PyQt6.QtCore', 'PyQt6.QtWidgets', 'PyQt6.QtGui',
        'PyQt6.QtMultimedia', 'PyQt6.QtMultimediaWidgets',
        'app.modules.lego', 'app.core', 'app.modules',
        'moviepy', 'PIL', 'numpy',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['tkinter'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='AI短剧编辑器',
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
    upx_exclude=[],
    name='AI短剧编辑器',
)
