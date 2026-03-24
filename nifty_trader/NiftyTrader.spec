# NiftyTrader.spec
# ─────────────────────────────────────────────────────────────────
# PyInstaller spec for building a standalone Windows executable.
# This is ALTERNATIVE to the embedded-Python approach.
#
# Usage (run from nifty_trader/ directory):
#   pip install pyinstaller
#   pyinstaller NiftyTrader.spec
#
# Output:
#   dist/NiftyTrader/NiftyTrader.exe   (one-folder distribution)
#   dist/NiftyTrader_onefile.exe       (single file — slower startup)
#
# The dist/NiftyTrader/ folder can be zipped and distributed.
# No Python installation required on target machine.
# ─────────────────────────────────────────────────────────────────

import sys
from pathlib import Path

block_cipher = None
APP_DIR = Path(SPECPATH)

a = Analysis(
    [str(APP_DIR / 'main.py')],
    pathex=[str(APP_DIR)],
    binaries=[],
    datas=[
        # Include any non-Python data files here
        # (config, icons, etc.)
    ],
    hiddenimports=[
        # PySide6 modules that PyInstaller misses
        'PySide6.QtCore',
        'PySide6.QtGui',
        'PySide6.QtWidgets',
        'PySide6.QtNetwork',
        # SQLAlchemy dialects
        'sqlalchemy.dialects.sqlite',
        # pandas/numpy internals
        'pandas._libs.tslibs.timestamps',
        'numpy.core._multiarray_umath',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Exclude unused heavy modules to reduce size
        'matplotlib', 'scipy', 'sklearn', 'PIL',
        'IPython', 'jupyter', 'notebook',
        'tkinter', 'wx',
        'PySide6.Qt3DCore', 'PySide6.Qt3DRender',
        'PySide6.QtBluetooth', 'PySide6.QtPositioning',
        'PySide6.QtMultimedia', 'PySide6.QtWebEngine',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

# ── One-folder EXE (recommended — faster startup) ─────────────────
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='NiftyTrader',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,           # No console window — critical!
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(APP_DIR / 'installer' / 'resources' / 'icon.ico')
    if (APP_DIR / 'installer' / 'resources' / 'icon.ico').exists()
    else None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='NiftyTrader',
)
