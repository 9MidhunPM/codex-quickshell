#!/usr/bin/env python3
"""Find Qt 6 tools without accidentally selecting a Qt 5 installation."""
from pathlib import Path
import os
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def tool(name):
    candidates = [Path(os.environ["QT_BIN_DIR"]) / name] if os.environ.get("QT_BIN_DIR") else []
    candidates += [Path(prefix) / name for prefix in ("/usr/lib/qt6/bin", "/usr/lib64/qt6/bin", "/usr/lib/qt6/libexec", "/usr/lib/qt6")]
    found = shutil.which(name + "6") or shutil.which(name)
    if found:
        candidates.append(Path(found))
    for candidate in candidates:
        if not candidate.is_file():
            continue
        option = "-help" if name == "qmltestrunner" else "--version"
        result = subprocess.run([str(candidate), option], capture_output=True, text=True,
                                env={**os.environ, "QT_QPA_PLATFORM": "offscreen"})
        output = result.stdout + result.stderr
        if "6." in output or (name == "qmltestrunner" and "qt6" in str(candidate) and result.returncode == 0):
            return str(candidate)
    raise SystemExit(f"Qt 6 {name} unavailable; set QT_BIN_DIR to your Qt 6 tools directory")


def run(argv, **kwargs):
    subprocess.run(argv, cwd=ROOT, check=True, **kwargs)


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "all"
    if mode not in {"all", "lint", "test"}:
        raise SystemExit("Usage: check_qml.py [all|lint|test]")
    if mode in {"all", "lint"}:
        files = sorted(str(p.relative_to(ROOT)) for folder in ("qml", "examples") for p in (ROOT / folder).rglob("*.qml"))
        command = [tool("qmllint")]
        if os.environ.get("QML_IMPORT_PATH"):
            for path in os.environ["QML_IMPORT_PATH"].split(os.pathsep):
                command += ["-I", path]
        run([*command, *files])
    if mode in {"all", "test"}:
        run([tool("qmltestrunner"), "-input", "qml/tests"], env={**os.environ, "QT_QPA_PLATFORM": "offscreen"})


if __name__ == "__main__":
    main()
