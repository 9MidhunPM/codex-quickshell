#!/usr/bin/env python3
"""Capture the real QML dashboard with explicit demo data, without a live account.

Requires Quickshell and an installed sans-serif font. Uses an isolated offscreen
Qt renderer, temporary HOME/runtime, disabled telemetry and disabled IPC. Images
are captured at 2x resolution directly from the opaque application surface.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
VIEWS = (("home", "overview", 560, 360), ("usage", "usage", 860, 620),
         ("agents", "agents", 860, 740))


def fixture() -> dict:
    now = int(time.time())
    return {
        "type": "snapshot", "version": 1,
        "connection": {"state": "connected", "message": "Demo data"},
        "usage": {"state": "fresh", "observedAt": now, "plan": "Demo",
                  "buckets": [{"id": "codex", "name": "Codex", "windows": [
                      {"label": "5-hour", "remainingPercent": 82, "resetsAt": now + 8000,
                       "durationMinutes": 300},
                      {"label": "Weekly", "remainingPercent": 64, "resetsAt": now + 240000,
                       "durationMinutes": 10080}],
                      "credits": {"balance": "20.00", "hasCredits": True, "unlimited": False}}]},
        "agents": {"state": "fresh", "observedAt": now, "activeCount": 1, "items": [
            {"id": "demo-main", "parentId": None, "title": "Build the desktop module",
             "nickname": "Main agent", "workspace": "sample-project", "model": "Example model A",
             "state": "working", "openTargetId": None, "openLabel": None, "depth": 0},
            {"id": "demo-review", "parentId": "demo-main", "title": "Review the integration",
             "nickname": "Review agent", "workspace": "sample-project", "model": "Example model B",
             "state": "waiting_approval", "openTargetId": None, "openLabel": None, "depth": 1},
            {"id": "demo-docs", "parentId": "demo-main", "title": "Update the documentation",
             "nickname": "Docs agent", "workspace": "sample-project", "model": None,
             "state": "idle", "openTargetId": None, "openLabel": None, "depth": 1}]}}


def qml(view: str, width: int, height: int, output: Path, snapshot: dict) -> str:
    # JSON quoting keeps local paths as QML string data; the import never scans
    # or copies a user's shell configuration or credential directories.
    return f'''import QtQuick
import Quickshell
import {json.dumps((ROOT / "qml").as_uri())} as Codex

ShellRoot {{
    Codex.CodexService {{
        id: service
        transportEnabled: false
        ipcEnabled: false
        reducedMotion: true
    }}
    FloatingWindow {{
        id: window
        title: "Codex screenshot demo"
        implicitWidth: {width}
        implicitHeight: {height}
        Rectangle {{
            id: surface
            width: {width}
            height: {height}
            color: service.background
            Codex.CodexDashboard {{
                id: dashboard
                anchors.fill: parent
                controller: service
                hostWindowVisible: true
            }}
        }}
    }}
    Component.onCompleted: {{
        service.applyMessage({json.dumps(snapshot)});
        dashboard.selectView({json.dumps(view)});
    }}
    Timer {{
        interval: 600
        running: true
        onTriggered: {{
            if (!service.usageFresh || service.agents.items.length !== 3) {{
                console.error("Demo snapshot was not applied");
                Qt.exit(1);
                return;
            }}
            surface.grabToImage(function(result) {{
            if (!result.saveToFile({json.dumps(str(output))})) {{
                console.error("Screenshot save failed");
                Qt.exit(1);
            }} else Qt.quit();
            }}, Qt.size({width * 2}, {height * 2}));
        }}
    }}
}}
'''


def validate_png(path: Path, width: int, height: int) -> None:
    data = path.read_bytes()
    if (data[:8] != b"\x89PNG\r\n\x1a\n" or data[12:16] != b"IHDR"
            or struct.unpack(">II", data[16:24]) != (width, height)):
        raise RuntimeError(f"Unexpected screenshot dimensions: {path.name}")
    # No embedded text, EXIF, or arbitrary application metadata is published.
    offset = 8
    while offset + 12 <= len(data):
        length = struct.unpack(">I", data[offset:offset + 4])[0]
        kind = data[offset + 4:offset + 8]
        if kind in {b"tEXt", b"zTXt", b"iTXt", b"eXIf"}:
            raise RuntimeError(f"Unexpected screenshot metadata: {path.name}")
        offset += length + 12


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "docs/assets")
    args = parser.parse_args()
    executable = shutil.which("qs") or shutil.which("quickshell")
    if not executable:
        parser.error("Quickshell is required")
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="codex-screenshots-") as directory:
        temporary = Path(directory)
        for name in ("runtime", "home", "config", "data", "cache"):
            (temporary / name).mkdir(mode=0o700)
        # In particular, do not inherit API keys, CODEX_HOME, a session bus,
        # display socket, or arbitrary QML import/plugin environment overrides.
        env = {key: os.environ[key] for key in ("PATH", "LANG", "LC_ALL") if key in os.environ}
        env.update(HOME=str(temporary / "home"), XDG_RUNTIME_DIR=str(temporary / "runtime"),
                   XDG_CONFIG_HOME=str(temporary / "config"), XDG_DATA_HOME=str(temporary / "data"),
                   XDG_CACHE_HOME=str(temporary / "cache"), QT_QPA_PLATFORM="offscreen",
                   QT_QUICK_BACKEND="software", QSG_RHI_BACKEND="software")
        snapshot = fixture()
        for name, view, width, height in VIEWS:
            destination = temporary / (name + ".png")
            shell = temporary / "shell.qml"
            shell.write_text(qml(view, width, height, destination, snapshot))
            result = subprocess.run([executable, "-p", str(shell)], env=env, capture_output=True,
                                    text=True, timeout=20)
            if result.returncode or not destination.is_file():
                raise RuntimeError(f"Quickshell screenshot failed for {name}: " + result.stderr[-2000:])
            validate_png(destination, width * 2, height * 2)
            shutil.copyfile(destination, output / (name + ".png"))
            print(f"Captured {name}.png ({width * 2} x {height * 2})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
