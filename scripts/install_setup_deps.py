#!/usr/bin/env python3
"""Install SSH dependencies locally, without modifying system Python."""
import importlib.util
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / ".build/setup-deps"


def main():
    sys.path.insert(0, str(TARGET))
    try:
        if not (TARGET / "paramiko/__init__.py").is_file():
            raise ImportError()
        import paramiko
        if paramiko.__version__ == "4.0.0":
            return 0
    except ImportError:
        pass
    # Native dependency wheels must match the launcher's actual interpreter.
    python = sys.executable
    if importlib.util.find_spec("pip") is None:
        bootstrap = ROOT / ".build/setup-install-venv"
        subprocess.run([sys.executable, "-m", "venv", str(bootstrap)], check=True)
        python = str(bootstrap / ("Scripts/python.exe" if os.name == "nt" else "bin/python"))
    subprocess.run([python, "-m", "pip", "install", "--upgrade", "--target", str(TARGET),
        "-r", str(ROOT / "requirements-setup.txt")], check=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
