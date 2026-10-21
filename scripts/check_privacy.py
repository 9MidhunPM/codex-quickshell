#!/usr/bin/env python3
"""Offline publication guard. Reports locations, never matching secret values.

Use a private --deny-file for additional personal strings. No scanner can prove
the absence of every secret; combine this guard with an independent scanner.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
import re
import subprocess


@dataclass(frozen=True, order=True)
class Issue:
    path: str
    line: int
    rule: str


RULES = {
    "provider-token": re.compile(r"\b(?:sk-(?:proj-|svcacct-)?[A-Za-z0-9_-]{32,}|gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,}|AKIA[A-Z0-9]{16})\b"),
    "private-key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----"),
    "personal-home": re.compile(r"/home/(?!user(?:/|\b)|example(?:/|\b)|demo(?:/|\b)|test(?:/|\b)|runner(?:/|\b))[A-Za-z0-9_.-]+/"),
}
EMAIL = re.compile(r"\b[A-Za-z0-9._%+-]+@([A-Za-z0-9.-]+\.[A-Za-z]{2,})\b")
SAFE_EMAIL_DOMAINS = {"example.com", "example.org", "example.net", "users.noreply.github.com"}
FORBIDDEN_PARTS = {".codex", ".aws", ".impeccable", ".private", "artifacts", "concepts", "__pycache__"}


def safe_link(path: str, target: bytes) -> bool:
    # Only repository-contained example aliases; absolute/private links fail.
    return (path in {f"examples/{name}/CodexStatusModule" for name in
                     ("standalone", "integration", "embedded", "hyprland")}
            and target == b"../../qml")


def path_issue(path: str) -> bool:
    parts = Path(path).parts
    name = Path(path).name.lower()
    return (bool(set(parts) & FORBIDDEN_PARTS) or name in {"auth.json", "prompts.json", ".env"}
            or name.startswith(".env.") or name.startswith("rollout-")
            or name.endswith((".db", ".sqlite", ".sqlite3", ".log", ".pem", ".key", ".pyc")))


def inspect(path: str, data: bytes, denied: tuple[str, ...] = ()) -> set[Issue]:
    issues = {Issue(path, 0, "private-artifact")} if path_issue(path) else set()
    if b"\x00" in data:
        if denied and any(value.encode() in data for value in denied):
            issues.add(Issue(path, 0, "private-deny-list"))
        return issues
    for number, line in enumerate(data.decode("utf-8", errors="replace").splitlines(), 1):
        for rule, pattern in RULES.items():
            if pattern.search(line):
                issues.add(Issue(path, number, rule))
        for match in EMAIL.finditer(line):
            domain = match.group(1).lower()
            if domain not in SAFE_EMAIL_DOMAINS and not domain.endswith(".example"):
                issues.add(Issue(path, number, "personal-email"))
        if any(value in line for value in denied):
            issues.add(Issue(path, number, "private-deny-list"))
    return issues


def git(root: Path, *args: str) -> bytes:
    return subprocess.run(["git", "-C", str(root), *args], check=True,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE).stdout


def check(root: Path, history: bool, denied: tuple[str, ...] = ()) -> set[Issue]:
    issues: set[Issue] = set()
    for raw in git(root, "ls-files", "-z").split(b"\x00"):
        if not raw:
            continue
        name = raw.decode("utf-8", errors="surrogateescape")
        file = root / name
        if file.is_symlink():
            target = str(file.readlink()).encode()
            if not safe_link(name, target):
                issues.add(Issue(name, 0, "tracked-symlink"))
        elif file.is_file():
            issues.update(inspect(name, file.read_bytes(), denied))
    if history:
        # Enumerate each commit tree: paths and deleted blobs are both inspected.
        seen: set[tuple[str, str]] = set()
        commits = git(root, "rev-list", "--all").decode().splitlines()
        for commit in commits:
            metadata = git(root, "show", "-s", "--format=%an%n%ae%n%cn%n%ce%n%B", commit)
            issues.update(inspect("commit:" + commit[:12], metadata, denied))
            for row in git(root, "ls-tree", "-rz", commit).split(b"\x00"):
                if not row:
                    continue
                header, rawname = row.split(b"\t", 1)
                mode, kind, oid = header.decode().split()
                name = rawname.decode("utf-8", errors="surrogateescape")
                if kind != "blob" or (oid, name) in seen:
                    continue
                seen.add((oid, name))
                label = name + " [" + oid[:12] + "]"
                data = git(root, "cat-file", "blob", oid)
                if mode == "120000" and not safe_link(name, data):
                    issues.add(Issue(label, 0, "tracked-symlink"))
                issues.update(inspect(label, data, denied))
    return issues


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--history", action="store_true", help="Also inspect all reachable commit trees and metadata")
    parser.add_argument("--deny-file", type=Path, help="Private UTF-8 file of additional literal strings, one per line; never commit it")
    args = parser.parse_args(argv)
    denied = tuple(line for line in args.deny_file.read_text().splitlines() if line) if args.deny_file else ()
    issues = check(args.root.resolve(), args.history, denied)
    for issue in sorted(issues):
        print(f"{issue.path}:{issue.line}: {issue.rule}")
    print(f"Publication guard: {len(issues)} issue(s). Matching values are redacted.")
    return 1 if issues else 0


if __name__ == "__main__":
    raise SystemExit(main())
