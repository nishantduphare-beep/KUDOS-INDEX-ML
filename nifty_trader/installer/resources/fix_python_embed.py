"""
installer/resources/fix_python_embed.py
─────────────────────────────────────────────────────────────────
Runs once during installation inside the embedded Python.
Fixes the ._pth file so site-packages works, then
installs all bundled wheels silently.

Called by Install.vbs as the second step.
"""

import sys
import os
import subprocess
from pathlib import Path

def main():
    base_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(r"C:\NiftyTrader")
    py_dir   = base_dir / "python"
    pkg_dir  = base_dir / "packages"

    # ── Fix ._pth file ────────────────────────────────────────────
    # Embedded Python ships with a .pth that disables site-packages.
    # We need to uncomment "import site" to enable pip and packages.
    for pth_name in ["python310._pth", "python312._pth", "python3._pth"]:
        pth_path = py_dir / pth_name
        if pth_path.exists():
            content = pth_path.read_text(encoding="utf-8")
            # Uncomment import site
            content = content.replace("#import site", "import site")
            # Add Lib paths if not present
            additions = "\nimport site\nLib\nLib\\site-packages\n"
            if "import site" not in content:
                content += additions
            pth_path.write_text(content, encoding="utf-8")
            break

    # ── Install pip if missing ────────────────────────────────────
    pip_path = py_dir / "Scripts" / "pip.exe"
    if not pip_path.exists():
        get_pip = base_dir / "resources" / "get-pip.py"
        if get_pip.exists():
            subprocess.run(
                [str(py_dir / "python.exe"), str(get_pip),
                 "--no-warn-script-location", "--quiet"],
                cwd=str(base_dir),
                capture_output=True
            )

    # ── Install packages from bundled wheels ──────────────────────
    if pkg_dir.exists():
        pip = str(py_dir / "Scripts" / "pip.exe")
        if not Path(pip).exists():
            pip = None

        packages = [
            "PySide6", "pandas", "numpy", "SQLAlchemy", "requests"
        ]

        for pkg in packages:
            if pip:
                cmd = [
                    pip, "install",
                    "--no-index",
                    f"--find-links={pkg_dir}",
                    pkg, "--quiet",
                    "--no-warn-script-location"
                ]
            else:
                cmd = [
                    str(py_dir / "python.exe"), "-m", "pip",
                    "install",
                    "--no-index",
                    f"--find-links={pkg_dir}",
                    pkg, "--quiet",
                    "--no-warn-script-location"
                ]
            subprocess.run(cmd, capture_output=True, cwd=str(base_dir))

    print("Setup complete.")

if __name__ == "__main__":
    main()
