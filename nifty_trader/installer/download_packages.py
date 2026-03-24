"""
installer/download_packages.py
─────────────────────────────────────────────────────────────────
Downloads all required Python packages as wheel files.
Run this ONCE on a machine with internet access.
The resulting packages/ folder is bundled into the installer.

Usage:
    python download_packages.py

Output:
    installer/packages/   (all .whl files, ~180 MB)

Note: Downloads Windows 64-bit wheels for Python 3.10
so they work on any Windows PC without internet.
"""

import subprocess
import sys
from pathlib import Path

PKG_DIR = Path(__file__).parent / "packages"
PKG_DIR.mkdir(exist_ok=True)

# Full list — order matters for dependency resolution
PACKAGES = [
    # PySide6 — the largest package (~150 MB), must be first
    "PySide6==6.7.2",

    # Data stack
    "numpy==1.26.4",
    "pandas==2.2.2",
    "python-dateutil==2.9.0",
    "pytz==2024.1",
    "tzdata==2024.1",
    "six==1.16.0",

    # Database
    "SQLAlchemy==2.0.30",

    # Networking
    "requests==2.32.3",
    "certifi==2024.6.2",
    "charset-normalizer==3.3.2",
    "idna==3.7",
    "urllib3==2.2.1",
]

def download_all():
    print("=" * 60)
    print("  NiftyTrader — Package Downloader")
    print("=" * 60)
    print(f"\n  Output directory: {PKG_DIR}\n")

    for pkg in PACKAGES:
        name = pkg.split("==")[0]
        print(f"  Downloading {pkg}…")

        cmd = [
            sys.executable, "-m", "pip", "download",
            pkg,
            "--dest", str(PKG_DIR),
            "--python-version", "3.10",
            "--platform", "win_amd64",
            "--only-binary", ":all:",
            "--quiet",
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)

        if result.returncode != 0:
            # Retry without platform constraint (for pure-python packages)
            cmd2 = [
                sys.executable, "-m", "pip", "download",
                pkg,
                "--dest", str(PKG_DIR),
                "--quiet",
            ]
            result2 = subprocess.run(cmd2, capture_output=True, text=True)
            if result2.returncode != 0:
                print(f"    WARNING: Could not download {pkg}")
                print(f"    {result2.stderr[:200]}")
            else:
                print(f"    OK (universal)")
        else:
            print(f"    OK")

    # Summary
    wheels = list(PKG_DIR.glob("*.whl")) + list(PKG_DIR.glob("*.tar.gz"))
    total_mb = sum(f.stat().st_size for f in wheels) / 1_048_576

    print(f"\n{'─' * 60}")
    print(f"  Total packages : {len(wheels)}")
    print(f"  Total size     : {total_mb:.1f} MB")
    print(f"\n  Packages downloaded:")
    for w in sorted(wheels, key=lambda x: x.stat().st_size, reverse=True):
        print(f"    {w.stat().st_size/1_048_576:6.1f} MB  {w.name}")
    print(f"\n  Ready for bundling into installer.")


if __name__ == "__main__":
    download_all()
