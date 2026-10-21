#!/usr/bin/env python3
"""Install an additive, user-owned Quickshell module. Dry-run is the default.

Existing shell configurations are deliberately never read or rewritten. The
manifest records only newly created files; no personal configuration is backed up.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
import tempfile

REPO = Path(__file__).resolve().parents[1]
UNIT = "codex-quickshell.service"
MODULE = "CodexStatusModule"
MANIFEST = "manifest.json"
SCHEMA = 1
MAX_ASSET = 1024 * 1024
MAX_MANIFEST = 1024 * 1024


class InstallError(Exception):
    """An unsafe or unsupported installation request."""


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def clean_path(value: str | Path) -> Path:
    text = str(value)
    if not text or any(ord(char) < 32 or ord(char) == 127 for char in text):
        raise InstallError("Paths must not contain control characters")
    path = Path(text).expanduser()
    if not path.is_absolute() or ".." in path.parts:
        raise InstallError("Paths must be absolute and must not contain '..'")
    return path


def check_parents(path: Path) -> None:
    """Reject foreign-owned, symlinked, or unsafely writable ancestors."""
    for part in (path, *path.parents):
        try:
            info = part.lstat()
        except FileNotFoundError:
            continue
        if not stat.S_ISDIR(info.st_mode):
            raise InstallError(f"Not a real directory: {part}")
        # A sticky directory's owner can rename children owned by another UID.
        # Only root or this user may retain that authority over installed QML.
        if info.st_uid not in {0, os.getuid()}:
            raise InstallError(f"Directory is owned by another user: {part}")
        # A sticky /tmp is suitable for isolated test installations. Ordinary
        # shared writable directories are not safe publication destinations.
        if info.st_mode & 0o022 and not info.st_mode & stat.S_ISVTX:
            raise InstallError(f"Unsafe writable directory: {part}")


def owned_file(path: Path, *, optional: bool = False) -> bytes | None:
    check_parents(path.parent)
    try:
        info = path.lstat()
    except FileNotFoundError:
        if optional:
            return None
        raise InstallError(f"Missing owned file: {path}")
    if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
            or info.st_mode & 0o022):
        raise InstallError(f"Not a safe owned file: {path}")
    if info.st_size > MAX_MANIFEST:
        raise InstallError(f"Owned file exceeds the size limit: {path}")
    return path.read_bytes()


def atomic_publish(path: Path, data: bytes, *, replace: bool = False) -> None:
    """Publish complete private bytes, never overwrite during first install."""
    check_parents(path.parent)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            os.fchmod(handle.fileno(), 0o600)
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        if replace:
            os.replace(temporary, path)
        else:
            os.link(temporary, path)
    finally:
        if os.path.lexists(temporary):
            os.unlink(temporary)


def systemd_quote(value: str) -> str:
    if any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise InstallError("Control characters are not supported in service arguments")
    value = value.replace("\\", "\\\\").replace('"', '\\"')
    value = value.replace("%", "%%").replace("$", "$$")
    return f'"{value}"'


def systemd_directory(value: str) -> str:
    value = str(clean_path(value))
    # WorkingDirectory is a setting value, not an ExecStart argument. Avoid
    # quotes and C-style escapes becoming literal parts of the directory name.
    # The generic config reader strips trailing whitespace/joins backslash lines.
    if value[-1].isspace() or value.endswith("\\"):
        raise InstallError("Service checkout path cannot end in whitespace or a backslash")
    return value.replace("%", "%%")


def render_unit(codex: str | None, terminal: str | None = None,
                disable_actions: bool = False) -> bytes:
    binary = str(clean_path(codex)) if codex is not None else shutil.which("codex")
    if not binary:
        raise InstallError("Codex CLI is not on PATH; use --codex-bin or --no-service")
    binary = str(clean_path(os.path.abspath(binary)))
    template = (REPO / "systemd" / (UNIT + ".in")).read_text(encoding="utf-8")
    arguments = ""
    if terminal is not None:
        if not terminal.strip():
            raise InstallError("--terminal must not be empty")
        arguments += " --terminal " + systemd_quote(terminal)
    if disable_actions:
        arguments += " --disable-actions"
    replacements = {"@REPO@": systemd_directory(str(REPO)),
                    "@PYTHON@": systemd_quote(str(clean_path(sys.executable))),
                    "@CODEX@": systemd_quote(binary), "@OPTIONS@": arguments}

    def substitute(match: re.Match) -> str:
        if match.group() not in replacements:
            raise InstallError("Service template has an unknown placeholder")
        return replacements[match.group()]

    # Single-pass substitution never interprets placeholder-like path data.
    return re.sub(r"@[A-Z_]+@", substitute, template).encode("utf-8")


def source_assets() -> dict[str, bytes]:
    source = REPO / "qml"
    check_parents(source)
    assets: dict[str, bytes] = {}
    for path in sorted(source.iterdir()):
        if path.name == "preview.qml":
            continue
        if path.name != "qmldir" and path.suffix not in (".qml", ".js"):
            continue
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o022:
            raise InstallError(f"Module source must be a regular, non-writable asset: {path.name}")
        if info.st_size > MAX_ASSET:
            raise InstallError(f"Module asset is too large: {path.name}")
        assets[path.name] = path.read_bytes()
    if not {"CodexStatus.qml", "CodexPill.qml", "qmldir"}.issubset(assets):
        raise InstallError("Required module sources are missing")
    return assets


def standalone_source(module: Path) -> bytes:
    # as_uri percent-encodes URL-sensitive path characters; JSON supplies the
    # QML string escaping. No directory name becomes executable QML syntax.
    location = json.dumps(module.as_uri(), ensure_ascii=True)
    return (
        "// Generated by Codex Quickshell; existing shells are not modified.\n"
        "import QtQuick\nimport Quickshell\n"
        f"import {location} as CodexModule\n\n"
        "Scope {\n"
        "    CodexModule.CodexStatus { id: status }\n"
        "    // Open with: qs ipc -p <this configuration directory> call codex-status open\n"
        "}\n"
    ).encode("utf-8")


def default_roots() -> tuple[Path, Path, Path]:
    config = clean_path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config")))
    state = clean_path(os.environ.get("XDG_STATE_HOME", str(Path.home() / ".local/state")))
    return config / "quickshell", state / "codex-quickshell/install", config / "systemd/user"


def settings(args) -> dict:
    defaults = default_roots()
    config = clean_path(args.config_root or defaults[0])
    state = clean_path(args.state_root or defaults[1])
    units = clean_path(args.unit_root or defaults[2])
    module = clean_path(args.module_dir or config / "modules" / MODULE)
    if not module.is_relative_to(config) or module == config:
        raise InstallError("--module-dir must be a child of --config-root")
    standalone = config / "codex-status"
    if module == standalone or module.is_relative_to(standalone) or standalone.is_relative_to(module):
        raise InstallError("The module directory overlaps the standalone configuration")
    roots = [config, state, units]
    if len(set(roots)) != 3 or any(
            left.is_relative_to(right) or right.is_relative_to(left)
            for index, left in enumerate(roots) for right in roots[index + 1:]):
        raise InstallError("Config, state and unit roots must be separate directories")
    # The unit root is checked when a unit file is actually planned or loaded
    # from the manifest. Module-only installation must not inspect that tree.
    for root in [config, state, module]:
        check_parents(root)
    if args.activate and (args.no_service or tuple(roots) != defaults
                          or any((args.config_root, args.state_root, args.unit_root))):
        raise InstallError("--activate requires the default user roots and a service installation")
    return {"configRoot": str(config), "stateRoot": str(state), "unitRoot": str(units),
            "moduleDir": str(module), "standalone": args.standalone,
            "service": not args.no_service, "activated": args.activate}


def missing_directories(paths: list[Path]) -> list[Path]:
    result: set[Path] = set()
    for path in paths:
        check_parents(path)
        current = path
        while not current.exists():
            result.add(current)
            current = current.parent
    return sorted(result, key=lambda path: (len(path.parts), str(path)))


def encode_manifest(manifest: dict) -> bytes:
    return (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode("utf-8")


def load_manifest(state: Path, current: dict) -> dict | None:
    path = state / MANIFEST
    data = owned_file(path, optional=True)
    if data is None:
        if state.exists() and any(state.iterdir()):
            raise InstallError("State directory contains foreign files and no installation manifest")
        return None
    if path.stat().st_mode & 0o077:
        raise InstallError("Installation manifest must be private (mode 0600)")
    try:
        value = json.loads(data)
        expected_keys = {"version", "status", "settings", "files", "directories"}
        if (not isinstance(value, dict) or set(value) != expected_keys
                or value["version"] != SCHEMA or value["status"] not in ("installed", "installing")):
            raise ValueError
        saved = value["settings"]
        if (not isinstance(saved, dict) or set(saved) != set(current)
                or any(not isinstance(saved[key], bool) for key in ("standalone", "service", "activated"))):
            raise ValueError
        for key in ("configRoot", "stateRoot", "unitRoot"):
            if saved[key] != current[key]:
                raise InstallError("Manifest roots do not match this invocation; repeat the installation root flags")
        config = clean_path(saved["configRoot"])
        module = clean_path(saved["moduleDir"])
        if not module.is_relative_to(config) or module == config:
            raise ValueError
        standalone = config / "codex-status"
        if module == standalone or module.is_relative_to(standalone) or standalone.is_relative_to(module):
            raise ValueError
        check_parents(module)
        unit = clean_path(saved["unitRoot"]) / UNIT
        if not isinstance(value["files"], list) or not value["files"]:
            raise ValueError
        seen: set[str] = set()
        for item in value["files"]:
            if (not isinstance(item, dict) or set(item) != {"path", "sha256", "kind"}
                    or not isinstance(item["sha256"], str)
                    or re.fullmatch(r"[a-f0-9]{64}", item["sha256"]) is None):
                raise ValueError
            file = clean_path(item["path"])
            if str(file) in seen:
                raise ValueError
            seen.add(str(file))
            if item["kind"] == "module":
                if (file.parent != module or file.name != "qmldir" and file.suffix not in (".qml", ".js")):
                    raise ValueError
            elif item["kind"] == "unit":
                if file != unit or not saved["service"]:
                    raise ValueError
            elif item["kind"] == "standalone":
                if file != standalone / "shell.qml" or not saved["standalone"]:
                    raise ValueError
            else:
                raise ValueError
            check_parents(file.parent)
        if sum(item["kind"] == "unit" for item in value["files"]) != int(saved["service"]):
            raise ValueError
        if sum(item["kind"] == "standalone" for item in value["files"]) != int(saved["standalone"]):
            raise ValueError
        if not isinstance(value["directories"], list) or len(set(value["directories"])) != len(value["directories"]):
            raise ValueError
        targets = [module, state, clean_path(saved["unitRoot"])]
        if saved["standalone"]:
            targets.append(standalone)
        for directory in value["directories"]:
            directory = clean_path(directory)
            if directory == Path("/") or not any(target.is_relative_to(directory) for target in targets):
                raise ValueError
            check_parents(directory)
    except (ValueError, KeyError, TypeError) as exc:
        raise InstallError("Invalid installation manifest; no files were changed") from exc
    return value


def planned_files(config: dict, args) -> list[tuple[Path, bytes, str]]:
    module = Path(config["moduleDir"])
    files = [(module / name, data, "module") for name, data in source_assets().items()]
    if config["standalone"]:
        files.append((Path(config["configRoot"]) / "codex-status/shell.qml", standalone_source(module), "standalone"))
    if config["service"]:
        files.append((Path(config["unitRoot"]) / UNIT,
                      render_unit(args.codex_bin, args.terminal, args.disable_actions), "unit"))
    return files


def run_systemctl(*args: str) -> None:
    try:
        result = subprocess.run(["systemctl", "--user", *args], capture_output=True,
                                text=True, timeout=20, check=False)
    except (OSError, subprocess.SubprocessError) as exc:
        raise InstallError("Could not contact the systemd user manager") from exc
    if result.returncode:
        # Do not print environments, journals or arbitrary subprocess output.
        raise InstallError(f"systemctl {' '.join(args)} failed (exit {result.returncode})")


def read_service_definition() -> dict[str, str]:
    """Read bounded manager metadata without accepting an unavailable bus as absent."""
    try:
        result = subprocess.run(
            ["systemctl", "--user", "show", "--no-pager", "--all", "--property=LoadState",
             "--property=FragmentPath", UNIT],
            capture_output=True, text=True, timeout=20, check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise InstallError("Could not verify the user service definition") from exc
    entries = [line.split("=", 1) for line in result.stdout.splitlines() if "=" in line]
    values = dict(entries)
    if (len(result.stdout) > 4096 or result.returncode not in (0, 1, 4)
            or len(entries) != len(values) or set(values) != {"LoadState", "FragmentPath"}
            or values["LoadState"] not in {"loaded", "not-found", "masked", "error", "bad-setting"}):
        raise InstallError("The user service definition cannot be verified")
    return values


def assert_service_name_unused() -> None:
    """Do not shadow an existing global or transient user unit on activation."""
    values = read_service_definition()
    if values["LoadState"] != "not-found" or values["FragmentPath"]:
        raise InstallError("The service name is already defined or cannot be verified; refusing activation")


def owned_service_state(manifest: dict) -> str:
    """Return loaded/unloaded/absent only when no foreign unit can be controlled."""
    item = next((item for item in manifest["files"] if item["kind"] == "unit"), None)
    if item is None:
        raise InstallError("No service ownership entry exists")
    path = Path(item["path"])
    data = owned_file(path, optional=True)
    if data is not None and digest(data) != item["sha256"]:
        raise InstallError("Installed service was modified; refusing service control")
    values = read_service_definition()
    if values["LoadState"] == "not-found" and not values["FragmentPath"]:
        return "absent" if data is None else "unloaded"
    if values["LoadState"] != "loaded" or values["FragmentPath"] != str(path):
        raise InstallError("The manager resolves a foreign or unsupported service; preserving the installation")
    if data is None:
        raise InstallError("The installed unit is missing while still loaded; restore its verified bytes or resolve it manually")
    return "loaded"


def stop_owned_service(manifest: dict) -> str:
    state = owned_service_state(manifest)
    if state == "loaded":
        run_systemctl("disable", "--now", UNIT)
    elif state == "unloaded":
        # No loaded unit exists to stop. Remove only this verified file's links.
        run_systemctl("disable", UNIT)
    return state


def real_service_roots(config: dict) -> bool:
    config_root, state_root, unit_root = default_roots()
    return (config["configRoot"], config["stateRoot"], config["unitRoot"]) == (
        str(config_root), str(state_root), str(unit_root))


def verify_installed(manifest: dict, *, missing_ok: bool = False) -> None:
    for item in manifest["files"]:
        path = Path(item["path"])
        data = owned_file(path, optional=missing_ok)
        if data is not None and digest(data) != item["sha256"]:
            raise InstallError(f"Installed file was modified; preserving all files: {path}")


def remove_empty_directories(directories: list[str]) -> None:
    for name in sorted(directories, key=lambda value: len(Path(value).parts), reverse=True):
        path = Path(name)
        check_parents(path)
        try:
            info = path.lstat()
        except FileNotFoundError:
            continue
        if info.st_uid != os.getuid():
            continue
        try:
            path.rmdir()
        except OSError:
            # Unknown files and concurrent user changes always win.
            pass


def install(config: dict, args, existing: dict | None, *, dry_run: bool) -> None:
    files = planned_files(config, args)
    if existing:
        if existing["status"] != "installed":
            raise InstallError("An interrupted installation exists; run --uninstall to recover safely")
        verify_installed(existing)
        if (existing["settings"] != config or
                {(str(path), digest(data), kind) for path, data, kind in files} !=
                {(item["path"], item["sha256"], item["kind"]) for item in existing["files"]}):
            raise InstallError("Installation options or source files changed; uninstall before reinstalling")
        print("Already installed; no files or services changed.")
        return
    module = Path(config["moduleDir"])
    standalone = Path(config["configRoot"]) / "codex-status"
    for root in [module, *([standalone] if config["standalone"] else [])]:
        if os.path.lexists(root):
            raise InstallError(f"Destination exists without an owned manifest: {root}")
    for path, _, _ in files:
        check_parents(path.parent)
        if os.path.lexists(path):
            raise InstallError(f"Refusing to overwrite an existing file: {path}")
    print("Dry-run: no files or services will change." if dry_run else "Installing additive Codex module.")
    for path, _, kind in files:
        print(f"  Create {kind}: {path}")
    if dry_run:
        if config["activated"]:
            print(f"  Activate user service: {UNIT}")
        return
    if config["activated"]:
        assert_service_name_unused()
    state = Path(config["stateRoot"])
    directories = missing_directories([state, *(path.parent for path, _, _ in files)])
    manifest = {"version": SCHEMA, "status": "installing", "settings": config,
                "files": [{"path": str(path), "sha256": digest(data), "kind": kind}
                          for path, data, kind in files],
                "directories": [str(path) for path in directories]}
    created: list[str] = []
    written: list[tuple[Path, bytes]] = []
    manifest_created = False
    activation_attempted = False
    manager_reloaded = False
    try:
        # Create state ancestors first, then publish a journal before module files.
        for path in directories:
            if state.is_relative_to(path):
                path.mkdir(mode=0o700)
                created.append(str(path))
        if state.stat().st_uid != os.getuid() or state.stat().st_mode & 0o077:
            raise InstallError("State root must be owned by the current user and private (0700)")
        atomic_publish(state / MANIFEST, encode_manifest(manifest))
        manifest_created = True
        for path in directories:
            if str(path) not in created:
                path.mkdir(mode=0o700)
                created.append(str(path))
        for path, data, _ in files:
            atomic_publish(path, data)
            written.append((path, data))
        if config["activated"]:
            # Verify the disk entry before asking the manager to load it.
            verify_installed(manifest)
            run_systemctl("daemon-reload")
            manager_reloaded = True
            if owned_service_state(manifest) != "loaded":
                raise InstallError("The manager did not load the verified installed unit")
            activation_attempted = True
            run_systemctl("enable", "--now", UNIT)
        manifest["status"] = "installed"
        atomic_publish(state / MANIFEST, encode_manifest(manifest), replace=True)
    except (OSError, InstallError):
        cleanup_safe = True
        if activation_attempted:
            try:
                stop_owned_service(manifest)
            except InstallError:
                cleanup_safe = False
        if cleanup_safe:
            for path, data in reversed(written):
                try:
                    if owned_file(path, optional=True) == data:
                        path.unlink()
                    else:
                        cleanup_safe = False
                except (OSError, InstallError):
                    cleanup_safe = False
        if cleanup_safe and manager_reloaded:
            try:
                # Drop the removed unit from the manager's cache so retrying an
                # installation cannot mistake our rolled-back unit for foreign.
                run_systemctl("daemon-reload")
            except InstallError:
                cleanup_safe = False
        if cleanup_safe and manifest_created:
            (state / MANIFEST).unlink()
        remove_empty_directories(created)
        if cleanup_safe:
            print("Installation rolled back; existing configurations were not changed.")
        else:
            print("Installation interrupted. Ownership manifest retained; run --uninstall to recover.")
        raise
    print("Installed. Existing Quickshell files were not read or modified.")
    if config["service"] and not config["activated"]:
        print(f"Service is not activated. Optional: systemctl --user daemon-reload && systemctl --user enable --now {UNIT}")


def uninstall(config: dict, args, manifest: dict | None, *, dry_run: bool) -> None:
    if manifest is None:
        print("Already uninstalled; no owned manifest found.")
        return
    saved = manifest["settings"]
    if args.no_service and saved["service"]:
        raise InstallError("This installation includes a service; omit --no-service to uninstall it fully")
    # Missing files are safe to forget and allow interrupted uninstalls to resume.
    # Every file that still exists must match before any service or file changes.
    verify_installed(manifest, missing_ok=True)
    print("Dry-run: no files or services will change." if dry_run else "Uninstalling owned files only.")
    for item in manifest["files"]:
        print(f"  Remove {item['kind']}: {item['path']}")
    if dry_run:
        return
    # Fixture roots never control the real user manager. Only our exact unit at
    # the default roots may be stopped, after all owned-file hashes have passed.
    service_state = "fixture"
    if saved["service"] and real_service_roots(saved):
        service_state = stop_owned_service(manifest)
    for item in reversed(manifest["files"]):
        path = Path(item["path"])
        data = owned_file(path, optional=True)
        if data is not None:
            if digest(data) != item["sha256"]:
                raise InstallError(f"File changed during uninstall; preserving it and the manifest: {path}")
            path.unlink()
    if service_state in ("loaded", "unloaded"):
        run_systemctl("daemon-reload")
    (Path(saved["stateRoot"]) / MANIFEST).unlink()
    remove_empty_directories(manifest["directories"])
    print("Uninstalled. Modified or unrelated files are preserved.")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group()
    action.add_argument("--install", action="store_true")
    action.add_argument("--uninstall", action="store_true")
    parser.add_argument("--dry-run", action="store_true", help="Preview even when an action is selected")
    parser.add_argument("--config-root", help="Quickshell configurations root (absolute)")
    parser.add_argument("--state-root", help="Private installer state directory (absolute)")
    parser.add_argument("--unit-root", help="User unit directory (absolute)")
    parser.add_argument("--module-dir", help="New module directory beneath config root")
    parser.add_argument("--standalone", action="store_true", help="Create a new codex-status configuration")
    parser.add_argument("--no-service", action="store_true", help="Install only QML; never contact systemd")
    parser.add_argument("--activate", action="store_true", help="Opt in to enabling and starting the new user service")
    parser.add_argument("--codex-bin", help="Absolute Codex executable path for the service")
    parser.add_argument("--terminal", help="Terminal command prefix, e.g. 'foot -e'; passed as data, never to a shell")
    parser.add_argument("--disable-actions", action="store_true", help="Disable external app launches in the bridge")
    args = parser.parse_args(argv)
    try:
        config = settings(args)
        if args.activate and args.uninstall:
            raise InstallError("--activate applies only to installation")
        if args.no_service and (args.terminal or args.codex_bin or args.disable_actions):
            raise InstallError("Service options cannot be combined with --no-service")
        manifest = load_manifest(Path(config["stateRoot"]), config)
        dry_run = args.dry_run or not (args.install or args.uninstall)
        if args.uninstall:
            uninstall(config, args, manifest, dry_run=dry_run)
        else:
            install(config, args, manifest, dry_run=dry_run)
        return 0
    except (InstallError, OSError, UnicodeError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
