"""
build_installer.py
══════════════════════════════════════════════════════════════════
Run ONCE on any machine that has Python + internet access.

Steps:
  1. Downloads Python 3.10.11 Windows Embeddable
  2. Gets get-pip.py
  3. Copies already-downloaded packages/ folder
  4. Copies app source
  5. Copies pre-written Install.vbs / NiftyTrader.vbs
  6. Zips everything → NiftyTrader_v2_Setup.zip

Usage:
    cd nifty_trader/installer
    python download_packages.py     # run first (needs internet)
    python build_installer.py       # run second (offline ok)

Output:
    dist/NiftyTrader_v2_Setup.zip
"""

import os
import sys
import shutil
import zipfile
import urllib.request
import urllib.error
import subprocess
from pathlib import Path

# ── Paths ─────────────────────────────────────────────────────────
ROOT     = Path(__file__).parent          # installer/
DIST     = ROOT / "dist"
STAGING  = DIST / "NiftyTrader_Setup"
APP_SRC  = ROOT.parent                    # nifty_trader/

PYTHON_VERSION = "3.10.11"
PYTHON_EMBED_URL = (
    "https://www.python.org/ftp/python/3.10.11/"
    "python-3.10.11-embed-amd64.zip"
)
PIP_URL = "https://bootstrap.pypa.io/get-pip.py"

# ── Helpers ───────────────────────────────────────────────────────

def banner(msg):
    print(f"\n{'─'*60}\n  {msg}\n{'─'*60}")

def download(url, dest, desc=""):
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        print(f"  [cached] {dest.name}")
        return
    print(f"  Downloading {desc or dest.name} ...")
    try:
        urllib.request.urlretrieve(url, dest, reporthook=_progress)
        print()
    except urllib.error.URLError as e:
        print(f"\n  ERROR: {e}")
        sys.exit(1)

def _progress(count, block, total):
    done = min(count * block, total)
    pct  = int(done / max(total, 1) * 40)
    bar  = "#" * pct + "." * (40 - pct)
    mb   = done / 1_048_576
    print(f"\r  [{bar}] {mb:.1f} MB", end="", flush=True)

def copy_app(src, dest):
    src  = Path(src)
    dest = Path(dest)
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    skip_dirs = {"__pycache__", ".git", "dist", "installer",
                 "logs", "models", "auth"}
    skip_exts = {".pyc", ".db"}
    for item in src.iterdir():
        nm = item.name
        if nm in skip_dirs or nm.startswith(".") or nm.startswith("{"):
            continue
        if item.is_file() and item.suffix in skip_exts:
            continue
        if item.is_dir():
            shutil.copytree(
                item, dest / nm,
                ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.db")
            )
        else:
            shutil.copy2(item, dest / nm)

# ── Main build ────────────────────────────────────────────────────

def build():
    banner(f"NiftyTrader Installer Builder  —  Python {PYTHON_VERSION}")

    # Fresh staging dir
    if STAGING.exists():
        shutil.rmtree(STAGING)
    for sub in ["python_embed", "packages", "resources", "app"]:
        (STAGING / sub).mkdir(parents=True)

    # ── 1. Python embeddable ──────────────────────────────────────
    banner("1/5  Python 3.10.11 embeddable runtime")
    py_zip = DIST / f"python-{PYTHON_VERSION}-embed-amd64.zip"
    download(PYTHON_EMBED_URL, py_zip, f"Python {PYTHON_VERSION} Embeddable (~30 MB)")
    if py_zip.exists():
        print("  Extracting ...")
        with zipfile.ZipFile(py_zip) as z:
            z.extractall(STAGING / "python_embed")
        print("  Done.")
    else:
        print("  WARNING: Python zip not found, skipping.")

    # ── 2. get-pip.py ─────────────────────────────────────────────
    banner("2/5  pip bootstrap")
    pip_dest = STAGING / "resources" / "get-pip.py"
    download(PIP_URL, pip_dest, "get-pip.py")

    # ── 3. Copy packages (already downloaded by download_packages.py)
    banner("3/5  Copying bundled packages")
    src_pkgs = ROOT / "packages"
    if not src_pkgs.exists():
        print("  ERROR: packages/ folder not found.")
        print("  Run:  python download_packages.py  first.")
        sys.exit(1)
    dst_pkgs = STAGING / "packages"
    wheels = list(src_pkgs.glob("*.whl")) + list(src_pkgs.glob("*.tar.gz"))
    for w in wheels:
        shutil.copy2(w, dst_pkgs / w.name)
    print(f"  Copied {len(wheels)} package files.")

    # ── 4. Copy app source ────────────────────────────────────────
    banner("4/5  Copying NiftyTrader app source")
    copy_app(APP_SRC, STAGING / "app")
    py_files = list((STAGING / "app").rglob("*.py"))
    print(f"  Copied {len(py_files)} Python files.")

    # ── 5. Copy installer scripts (already written separately) ────
    banner("5/5  Copying installer scripts")
    scripts = [
        (ROOT / "Install.vbs",       STAGING / "Install.vbs"),
        (ROOT / "NiftyTrader.vbs",   STAGING / "NiftyTrader.vbs"),
    ]
    for src, dst in scripts:
        if src.exists():
            shutil.copy2(src, dst)
            print(f"  Copied {src.name}")
        else:
            print(f"  WARNING: {src.name} not found — skipping")

    # Write README.txt
    readme = (
        "NiftyTrader Intelligence v2.0\n"
        "=" * 40 + "\n\n"
        "INSTALLATION\n"
        "-" * 40 + "\n"
        "1. Make sure you have extracted this folder\n"
        "2. Double-click  Install.vbs\n"
        "3. Click OK when asked\n"
        "4. Wait 2-3 minutes\n"
        "5. App launches automatically\n\n"
        "No Python needed. No internet needed. No admin rights needed.\n\n"
        "AFTER INSTALL\n"
        "-" * 40 + "\n"
        "Desktop shortcut: NiftyTrader\n"
        "Start Menu: Start > NiftyTrader\n\n"
        "UNINSTALL\n"
        "-" * 40 + "\n"
        "Start Menu > NiftyTrader > Uninstall\n"
    )
    (STAGING / "README.txt").write_text(readme, encoding="utf-8")
    print("  Written README.txt")

    # ── Zip everything ────────────────────────────────────────────
    banner("Creating final ZIP")
    out_zip = DIST / "NiftyTrader_v2_Setup.zip"
    print(f"  Zipping to {out_zip.name} ...")
    with zipfile.ZipFile(out_zip, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for f in STAGING.rglob("*"):
            if f.is_file():
                zf.write(f, f.relative_to(DIST))
    size_mb = out_zip.stat().st_size / 1_048_576
    print(f"  Done.  Size: {size_mb:.1f} MB")

    banner("Build complete")
    print(f"\n  OUTPUT: {out_zip.resolve()}\n")
    print("  Send that ZIP to anyone.")
    print("  They extract it, double-click Install.vbs, done.\n")


if __name__ == "__main__":
    build()
