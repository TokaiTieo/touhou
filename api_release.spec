# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['backend\\api.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('version.json', '.'),
        ('index.html', '.'),
        ('js', 'js'),
        ('css', 'css'),
        ('static', 'static'),
        ('avatars', 'avatars'),
        ('release\\build_worlds_clean', 'worlds'),
        ('prompts', 'prompts'),
    ],
    hiddenimports=[
        'webview',
        'aiosqlite',
        'langgraph.func',
        'langgraph.types',
        'langgraph.checkpoint.sqlite',
        'langgraph.checkpoint.sqlite.aio',
        'sqlite_vec',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'Flask', 'PIL', 'fitz', 'matplotlib', 'numpy', 'pandas',
        'pypdf', 'scipy', 'sklearn', 'tkinter'
    ],
    noarchive=False,
    optimize=1,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='touhou',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
