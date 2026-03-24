# NiftyTrader — One-Click Installer Build Guide

## Overview

Two methods to create the installer. Both produce a package that:
- Works on any Windows 10/11 64-bit PC
- Needs zero internet on the target machine
- Needs zero command prompt during install or launch
- Creates a desktop shortcut and Start Menu entry

---

## METHOD 1 — Embedded Python (Recommended)

This bundles Python 3.10 + all packages inside the zip.
User extracts → double-clicks `Install.vbs` → done.

### Step-by-step (do this ONCE on your own PC)

**Prerequisites:** Python 3.9+ and pip on your build machine. Internet access.

```
cd nifty_trader/installer

# Step 1: Download all package wheels (180 MB, run once)
python download_packages.py

# Step 2: Build the full installer package
python build_installer.py
```

**Output:** `dist/NiftyTrader_v2_Setup.zip` (~220 MB)

### What the target user does

1. Receive `NiftyTrader_v2_Setup.zip`
2. Extract to any folder (Downloads, Desktop, etc.)
3. Double-click **`Install.vbs`**
4. Click OK
5. Wait ~2-3 minutes (packages installing silently)
6. App launches automatically ✓

**Desktop shortcut created → `NiftyTrader`**
**Start Menu → NiftyTrader → NiftyTrader**

---

## METHOD 2 — PyInstaller Single EXE (Smaller, Faster)

Creates a single `.exe` that contains everything. No zip extraction needed.

### Steps

```
cd nifty_trader

# Install build tools
pip install pyinstaller

# Build
pyinstaller NiftyTrader.spec
```

**Output:** `dist/NiftyTrader/` folder (~150 MB)

Wrap with Inno Setup for a proper installer `.exe`:
```
# Install Inno Setup: https://jrsoftware.org/isdl.php
# Then compile:
iscc installer/installer.iss
```

**Output:** `dist/NiftyTrader_v2_Installer.exe` (~120 MB compressed)

---

## Installer Package Contents

```
NiftyTrader_Setup/
├── Install.vbs          ← USER DOUBLE-CLICKS THIS
├── README.txt           ← Instructions
├── python_embed/        ← Python 3.10 (no installation needed)
│   ├── python.exe
│   ├── python310.zip
│   └── DLLs/
├── packages/            ← All .whl files (PySide6, pandas, etc.)
│   ├── PySide6-6.7.2-*.whl
│   ├── pandas-2.2.2-*.whl
│   ├── numpy-1.26.4-*.whl
│   └── ...
├── resources/
│   └── get-pip.py
└── app/                 ← NiftyTrader source
    ├── main.py
    ├── config.py
    ├── data/
    ├── engines/
    ├── ui/
    └── ...
```

---

## Installed Location

```
%LOCALAPPDATA%\NiftyTrader\
├── NiftyTrader.vbs      ← Desktop shortcut points here
├── Uninstall.vbs        ← Start Menu uninstaller
├── python\              ← Python 3.10 runtime
├── app\                 ← NiftyTrader source
├── logs\                ← Application logs
├── auth\                ← Fyers token + credentials
└── models\              ← ML model files
```

---

## Uninstall

Start Menu → NiftyTrader → Uninstall NiftyTrader

Or double-click: `%LOCALAPPDATA%\NiftyTrader\Uninstall.vbs`

---

## Troubleshooting

**Install.vbs says "python_embed folder not found"**
→ You didn't extract the zip first. Extract the whole folder, then double-click Install.vbs.

**App doesn't start after install**
→ Open `%LOCALAPPDATA%\NiftyTrader\logs\` — check the latest .log file for errors.

**"python.exe not found" error**
→ Run Install.vbs again. The Python extraction may have been incomplete.

**PySide6 import error**
→ The packages/ folder is missing wheels. Re-run `download_packages.py` and rebuild.

---

## System Requirements (Target PC)

| Item | Requirement |
|------|-------------|
| OS | Windows 10 / 11  (64-bit) |
| RAM | 4 GB minimum, 8 GB recommended |
| Disk | 500 MB free |
| Internet | NOT required after installation |
| Python | NOT required (bundled) |
| Admin rights | NOT required (installs to %LOCALAPPDATA%\NiftyTrader, not Program Files) |
