# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec file for battest.

This spec file includes optimizations to reduce antivirus false positives:
- Version information resource for legitimacy
- Disabled UPX compression (--noupx) which triggers heuristic detection
- Console application metadata
- Company and product information

Generate ``file_version_info.txt`` before building:
    python scripts/generate_file_version_info.py
"""

block_cipher = None

a = Analysis(
    ["src/battest/__main__.py"],
    pathex=["src"],
    binaries=[],
    datas=[
        ("src/battest/data", "battest/data"),
        ("src/battest/py.typed", "battest"),
        ("pyproject.toml", "."),
    ],
    hiddenimports=[
        "battest",
        "charset_normalizer",
        "pydantic",
        "yaml",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "tkinter",
        "_tkinter",
        "turtle",
        "idlelib",
        "unittest",
        "test",
        "tests",
        "doctest",
        "pydoc",
        "curses",
        "_curses",
        "lib2to3",
        "ensurepip",
        "venv",
        "matplotlib",
        "numpy",
        "PIL",
        "cv2",
        "scipy",
        "pandas",
        "sqlite3",
        "_sqlite3",
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
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="battest",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    version="file_version_info.txt",
)
