# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path

block_cipher = None
project_root = Path('.').resolve()

added_files = [
    (str(project_root / 'meowboard' / 'assets'), 'meowboard/assets'),
]

a = Analysis(
    ['main.py'],
    pathex=[str(project_root)],
    binaries=[],
    datas=added_files,
    hiddenimports=[
        'pygame',
        'numpy',
        'scipy',
        'PySide6',
        'meowboard',
        'meowboard.config',
        'meowboard.core',
        'meowboard.gui',
        'meowboard.utils',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'tkinter',
        'matplotlib',
        'IPython',
        'unittest',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='MEOWBOARD',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,  # Suppress console window (Windowed desktop application)
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(project_root / 'meowboard' / 'assets' / 'icons' / 'meowboard.ico'),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='MEOWBOARD',
)
