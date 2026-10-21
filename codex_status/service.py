"""One private telemetry bridge per desktop user. No third-party dependencies."""

from __future__ import annotations

import argparse
import asyncio
import errno
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import shlex
import signal
import socket
import stat
import struct
import subprocess
import threading
import time
from uuid import uuid4

from .model import (mark_usage_stale, normalize_agents, normalize_usage,
                    unavailable_agents, unavailable_usage)
from .protocol import CodexConnection, ProtocolError, RpcError, valid_id

MAX_UI_FRAME = 4096
MAX_SNAPSHOT = 512 * 1024
MAX_THREADS = 256
DASHBOARDS = {
    "usage": "https://platform.openai.com/settings/organization/usage",
    "billing": "https://platform.openai.com/settings/organization/billing",
}
TERMINALS = (
    ("x-terminal-emulator", "-e"),
    ("kitty", "-e"),
    ("foot", "-e"),
    ("alacritty", "-e"),
    ("konsole", "-e"),
    ("wezterm", "start", "--"),
    ("gnome-terminal", "--"),
)


def terminal_command(value: str) -> tuple[str, ...]:
    """Parse trusted local configuration once; never invoke a command shell."""
    try:
        argv = tuple(shlex.split(value))
    except ValueError as error:
        raise argparse.ArgumentTypeError("Terminal command has invalid quoting") from error
    if (not argv or len(value) > 4096 or len(argv) > 64
            or any("\0" in part or len(part) > 1024 for part in argv)):
        raise argparse.ArgumentTypeError("Terminal command must be a bounded argument vector")
    return argv


def resolve_terminal(configured: tuple[str, ...] | None) -> list[str] | None:
    """Resolve an explicitly configured terminal or a known terminal prefix."""
    for candidate in (configured,) if configured else TERMINALS:
        executable = shutil.which(candidate[0])
        if executable:
            return [executable, *candidate[1:]]
    return None


class UiClient:
    def __init__(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        self.reader, self.writer = reader, writer
        self.open = False
        self.queue: asyncio.Queue = asyncio.Queue(maxsize=2)
        self.last_action = 0.0

    def enqueue(self, value: dict) -> None:
        # Slow desktops keep only the newest snapshot; no unbounded backlog.
        if self.queue.full():
            self.queue.get_nowait()
        self.queue.put_nowait(value)

    async def send(self) -> None:
        while True:
            value = await self.queue.get()
            data = json.dumps(value, ensure_ascii=True, allow_nan=False,
                              separators=(",", ":")).encode() + b"\n"
            if len(data) > MAX_SNAPSHOT:
                raise ProtocolError("UI snapshot too large")
            self.writer.write(data)
            await asyncio.wait_for(self.writer.drain(), 3)


class Bridge:
    def __init__(self, binary: str, codex_home: Path,
                 terminal: tuple[str, ...] | None = None, actions_enabled: bool = True):
        self.binary, self.codex_home = binary, codex_home
        self.terminal = terminal
        self.actions_enabled = actions_enabled
        self.connection = {"state": "connecting", "message": "Connecting to local Codex"}
        self.usage = unavailable_usage()
        self.agents = unavailable_agents()
        self.clients: set[UiClient] = set()
        self.wake = asyncio.Event()
        self.refresh_usage = True
        self.last_manual_refresh = 0.0
        self.identity: str | None = None
        self.account_generation = 0
        self.last_usage_poll = float("-inf")
        self.force_account_read = True
        self.action_processes: set[asyncio.subprocess.Process] = set()
        self.shutting_down = False

    @property
    def opened(self) -> bool:
        return any(client.open for client in self.clients)

    def snapshot(self) -> dict:
        agents = self.agents
        observed = agents.get("observedAt")
        if observed is not None and time.time() - observed > 15:
            agents = unavailable_agents()
        return {"type": "snapshot", "version": 1,
                "connection": self.connection, "usage": self.usage, "agents": agents}

    def publish(self) -> None:
        snapshot = self.snapshot()
        for client in tuple(self.clients):
            client.enqueue(snapshot)

    def notification(self, method: str) -> None:
        if method == "account/updated":
            self.account_generation += 1
            self.force_account_read = True
            self.usage = unavailable_usage()
            self.identity = None
            self.publish()
        self.refresh_usage = True
        self.wake.set()

    async def read_usage(self, rpc: CodexConnection) -> None:
        generation = self.account_generation
        try:
            response = await rpc.read("account/read", {"refreshToken": False})
            if generation != self.account_generation:
                return
            # Identity is used only in memory to invalidate previous-account data.
            identity = hashlib.sha256(json.dumps({
                "account": response.get("account"),
                "routing": response.get("workspaceRouting"),
            }, sort_keys=True).encode()).hexdigest()
            if identity != self.identity:
                self.usage = unavailable_usage()
                self.identity = identity
                self.publish()
            account = response.get("account")
            if not isinstance(account, dict) or account.get("type") != "chatgpt":
                self.usage = unavailable_usage()
                return
            limits = await rpc.read("account/rateLimits/read", {"excludeResetCreditDetails": True})
            if generation != self.account_generation:
                return
            routing = response.get("workspaceRouting")
            if (isinstance(routing, dict) and routing.get("chatgptAccountId")
                    and limits.get("accountId")
                    and routing["chatgptAccountId"] != limits["accountId"]):
                self.usage = unavailable_usage()
                return
            self.usage = normalize_usage(limits, account.get("planType"), time.time())
        except RpcError:
            self.usage = mark_usage_stale(self.usage)

    async def read_agents(self, rpc: CodexConnection) -> None:
        ids, cursors = [], set()
        cursor = None
        for _ in range(4):
            page = await rpc.read("thread/loaded/list", {"limit": 100, "cursor": cursor})
            values = page.get("data")
            if not isinstance(values, list):
                raise ProtocolError("Unsupported thread listing")
            ids.extend(value for value in values if valid_id(value) and value not in ids)
            cursor = page.get("nextCursor")
            if not cursor:
                break
            if not isinstance(cursor, str) or cursor in cursors or len(ids) >= MAX_THREADS:
                raise ProtocolError("Thread listing exceeds monitoring bounds")
            cursors.add(cursor)
        else:
            raise ProtocolError("Thread listing exceeds monitoring bounds")
        if len(ids) > MAX_THREADS:
            raise ProtocolError("Too many loaded sessions")
        semaphore = asyncio.Semaphore(4)

        async def read_one(thread_id: str) -> dict | None:
            async with semaphore:
                try:
                    result = await rpc.read("thread/read", {"threadId": thread_id, "includeTurns": False})
                    thread = result.get("thread")
                    if isinstance(thread, dict) and thread.get("id") == thread_id:
                        return thread
                except RpcError:
                    pass  # A thread may disappear between listing and reading.
                return None

        threads = await asyncio.wait_for(asyncio.gather(*(read_one(i) for i in ids)), 10)
        self.agents = normalize_agents([thread for thread in threads if thread is not None], time.time())
        if any(thread is None for thread in threads):
            self.agents["state"] = "unavailable"
            self.agents["activeCount"] = None

    async def monitor(self) -> None:
        delay = 1
        while True:
            rpc = CodexConnection(self.binary, self.codex_home, self.notification)
            self.connection = {"state": "connecting", "message": "Connecting to local Codex"}
            self.agents = unavailable_agents()
            self.publish()
            try:
                await rpc.connect()
                self.connection = {"state": "connected", "message": "Connected to local Codex daemon"}
                # Old data cannot survive reconnect before account identity is checked.
                self.usage = unavailable_usage()
                self.identity = None
                usage_due = 0.0
                agents_due = 0.0
                while not rpc.closed.is_set():
                    self.wake.clear()
                    now = time.monotonic()
                    if ((self.refresh_usage or now >= usage_due)
                            and (self.force_account_read or now - self.last_usage_poll >= 10)):
                        self.refresh_usage = False
                        self.force_account_read = False
                        self.last_usage_poll = now
                        await self.read_usage(rpc)
                        usage_due = time.monotonic() + (60 if self.opened else 300)
                    if time.monotonic() >= agents_due:
                        await self.read_agents(rpc)
                        agents_due = time.monotonic() + (2 if self.opened else 5)
                    # A handshake alone does not establish compatible monitoring.
                    delay = 1
                    self.publish()
                    next_usage = (self.last_usage_poll + 10 if self.refresh_usage
                                  else max(usage_due, self.last_usage_poll + 10))
                    if self.force_account_read:
                        next_usage = time.monotonic()
                    timeout = max(0.1, min(agents_due, next_usage) - time.monotonic())
                    try:
                        await asyncio.wait_for(self.wake.wait(), timeout)
                    except asyncio.TimeoutError:
                        pass
                raise ProtocolError("Codex disconnected")
            except RpcError as error:
                self.connection = {"state": "incompatible" if error.code == -32601 else "disconnected",
                                   "message": "Codex monitoring interface unavailable"}
            except (OSError, ProtocolError, asyncio.TimeoutError):
                self.connection = {"state": "disconnected",
                                   "message": "Local Codex daemon unavailable"}
            finally:
                await rpc.close()
                self.agents = unavailable_agents()
                self.usage = mark_usage_stale(self.usage)
                self.publish()
            await asyncio.sleep(delay)
            delay = min(delay * 2, 30)

    async def heartbeat(self) -> None:
        while True:
            await asyncio.sleep(5)
            self.publish()

    async def launch(self, argv: list[str]) -> bool:
        # UI actions are explicit; telemetry never calls this path.
        if not self.actions_enabled or len(self.action_processes) >= 4:
            return False
        launcher = shutil.which("systemd-run")
        if not launcher:
            # Non-systemd desktops can still open items. A daemon reaper avoids
            # blocking the event loop or shutdown while the application runs.
            env = dict(os.environ, CODEX_HOME=str(self.codex_home))
            try:
                process = subprocess.Popen(
                    argv, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL, start_new_session=True, env=env)
                threading.Thread(target=process.wait, daemon=True,
                                 name="codex-quickshell-open-reaper").start()
                return True
            except OSError:
                return False
        # A transient user service owns the new application, so restarting the
        # bridge cannot kill its terminal. It also receives the user manager's
        # current graphical environment, even when the bridge started at login.
        command = [launcher, "--user", "--collect", "--quiet", "--service-type=exec",
                   "--expand-environment=no", "--property=StandardOutput=null",
                   "--property=StandardError=null",
                   f"--unit=codex-quickshell-open-{uuid4().hex}",
                   f"--setenv=CODEX_HOME={self.codex_home}", "--", *argv]
        process = None
        try:
            process = await asyncio.create_subprocess_exec(
                *command, stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
                start_new_session=True)
            self.action_processes.add(process)
            return await asyncio.wait_for(process.wait(), 5) == 0
        except asyncio.TimeoutError:
            if process is not None and process.returncode is None:
                process.terminate()
                await process.wait()
            return False
        except OSError:
            return False
        finally:
            if process is not None:
                self.action_processes.discard(process)

    async def handle(self, client: UiClient, request: dict) -> None:
        kind = request.get("type")
        if kind == "visibility" and set(request) == {"type", "open"} and type(request["open"]) is bool:
            was_open = self.opened
            client.open = request["open"]
            if client.open and not was_open:
                self.refresh_usage = True
                self.wake.set()
            return
        now = time.monotonic()
        if kind == "refresh" and set(request) == {"type"}:
            if now - self.last_manual_refresh >= 10:
                self.last_manual_refresh = now
                self.refresh_usage = True
                self.wake.set()
            return
        if not self.actions_enabled:
            client.enqueue({"type": "action_result", "ok": False,
                            "message": "External actions are disabled"})
            return
        if now - client.last_action < 1:
            return
        argv = None
        if kind == "open_dashboard" and set(request) == {"type", "target"}:
            target = request["target"]
            opener = shutil.which("xdg-open")
            if isinstance(target, str) and target in DASHBOARDS and opener:
                argv = [opener, DASHBOARDS[target]]
        elif kind == "open_session" and set(request) == {"type", "threadId"}:
            thread_id = request["threadId"]
            terminal = resolve_terminal(self.terminal)
            snapshot = self.snapshot()
            known = {item.get("openTargetId") for item in snapshot["agents"]["items"]}
            if (snapshot["agents"]["state"] == "fresh" and valid_id(thread_id)
                    and thread_id in known and terminal):
                argv = [*terminal, self.binary, "resume", thread_id]
        client.last_action = now
        ok = await self.launch(argv) if argv else False
        client.enqueue({"type": "action_result", "ok": ok,
                        "message": "Opened" if ok else "Could not open this item"})

    async def accept(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        client = UiClient(reader, writer)
        sender = None
        incoming = None
        try:
            transport_socket = writer.get_extra_info("socket")
            _, uid, _ = struct.unpack("3i", transport_socket.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))
            if self.shutting_down or uid != os.getuid() or len(self.clients) >= 4:
                return
            self.clients.add(client)
            client.enqueue(self.snapshot())
            sender = asyncio.create_task(client.send())
            while True:
                # If sending fails, stop receiving too rather than leaking clients.
                incoming = asyncio.create_task(reader.readline())
                done, _ = await asyncio.wait({incoming, sender}, return_when=asyncio.FIRST_COMPLETED)
                if sender in done:
                    incoming.cancel()
                    await asyncio.gather(incoming, return_exceptions=True)
                    break
                line = incoming.result()
                if not line:
                    break
                if len(line) > MAX_UI_FRAME or not line.endswith(b"\n"):
                    break
                request = json.loads(line)
                if not isinstance(request, dict):
                    break
                await self.handle(client, request)
        except (ValueError, OSError, ProtocolError, asyncio.TimeoutError):
            pass
        finally:
            self.clients.discard(client)
            if incoming is not None and not incoming.done():
                incoming.cancel()
                await asyncio.gather(incoming, return_exceptions=True)
            if sender:
                sender.cancel()
                await asyncio.gather(sender, return_exceptions=True)
            writer.close()
            try:
                await writer.wait_closed()
            except OSError:
                pass


def secure_listener(path: Path) -> tuple[socket.socket, int]:
    directory = path.parent
    directory.mkdir(parents=True, mode=0o700, exist_ok=True)
    info = directory.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise ProtocolError("Runtime directory must be private and user-owned")
    lock = os.open(directory / "bridge.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        info = os.fstat(lock)
        if info.st_uid != os.getuid() or not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077:
            raise ProtocolError("Unsafe bridge lock")
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if path.exists() or path.is_symlink():
            info = path.lstat()
            if not stat.S_ISSOCK(info.st_mode) or info.st_uid != os.getuid():
                raise ProtocolError("Refusing to replace foreign runtime file")
            probe = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            try:
                probe.settimeout(0.2)
                result = probe.connect_ex(str(path))
                if result not in {errno.ECONNREFUSED, errno.ENOENT}:
                    raise ProtocolError("Bridge socket is already in use")
            finally:
                probe.close()
            path.unlink()
        listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            listener.bind(str(path))
            os.chmod(path, 0o600)
            listener.listen(4)
            listener.setblocking(False)
        except BaseException:
            listener.close()
            raise
        return listener, lock
    except BaseException:
        os.close(lock)
        raise


async def run(args: argparse.Namespace) -> None:
    os.umask(0o077)
    path = Path(args.socket)
    listener, lock = secure_listener(path)
    bridge = Bridge(args.codex_bin, Path(args.codex_home),
                    terminal=getattr(args, "terminal", None),
                    actions_enabled=not getattr(args, "disable_actions", False))
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)
    tasks = []
    server = None
    stopper = None
    try:
        server = await asyncio.start_unix_server(bridge.accept, sock=listener, limit=MAX_UI_FRAME + 1)
        tasks = [asyncio.create_task(bridge.monitor()), asyncio.create_task(bridge.heartbeat())]
        stopper = asyncio.create_task(stop.wait())
        done, _ = await asyncio.wait([*tasks, stopper], return_when=asyncio.FIRST_COMPLETED)
        for task in done:
            if task is not stopper:
                task.result()
    finally:
        bridge.shutting_down = True
        if server:
            server.close()
        # Python 3.13+ Server.wait_closed also waits for client transports. Close
        # those before awaiting the server, rather than deadlocking on our UI.
        for client in tuple(bridge.clients):
            client.writer.close()
        if stopper:
            stopper.cancel()
            await asyncio.gather(stopper, return_exceptions=True)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        if server:
            await asyncio.wait_for(server.wait_closed(), 5)
        listener.close()
        if path.exists() and path.lstat().st_uid == os.getuid() and stat.S_ISSOCK(path.lstat().st_mode):
            path.unlink()
        os.close(lock)


async def check_connection(binary: str, codex_home: Path) -> dict:
    """Read-only installation gate; returns capability metadata, never account data."""
    rpc = CodexConnection(binary, codex_home)
    try:
        await rpc.connect()
        await rpc.read("account/read", {"refreshToken": False})
        quotas = True
        try:
            await rpc.read("account/rateLimits/read", {"excludeResetCreditDetails": True})
        except RpcError as error:
            if error.code == -32601:
                raise
            quotas = False  # Signed out/API-key accounts can still monitor agents.
        loaded = await rpc.read("thread/loaded/list", {"limit": 100, "cursor": None})
        ids = loaded.get("data")
        if not isinstance(ids, list):
            raise ProtocolError("Unsupported thread listing")
        target = next((value for value in ids if valid_id(value)), "00000000-0000-0000-0000-000000000000")
        try:
            metadata = await rpc.read("thread/read", {"threadId": target, "includeTurns": False})
            thread = metadata.get("thread")
            if not isinstance(thread, dict) or not isinstance(thread.get("status"), dict):
                raise ProtocolError("Unsupported thread metadata")
        except RpcError as error:
            if target != "00000000-0000-0000-0000-000000000000" or error.code == -32601:
                raise
        return {"connected": True, "metadataSupported": True, "quotaAvailable": quotas}
    finally:
        await rpc.close()


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Private Codex status bridge for Quickshell")
    runtime = os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")
    parser.add_argument("--socket", default=str(Path(runtime) / "codex-quickshell/status.sock"))
    parser.add_argument("--codex-bin", default=shutil.which("codex") or "codex")
    parser.add_argument("--codex-home", default=os.environ.get("CODEX_HOME", str(Path.home() / ".codex")))
    parser.add_argument("--terminal", type=terminal_command, metavar="COMMAND",
                        help="Terminal argument prefix, for example 'foot -e'; no shell expansion")
    parser.add_argument("--disable-actions", action="store_true",
                        help="Monitor only; disable terminal and dashboard opening")
    parser.add_argument("--check", action="store_true", help="Probe existing daemon capabilities without starting a bridge")
    args = parser.parse_args(argv)
    binary = shutil.which(args.codex_bin)
    if not binary:
        parser.exit(1, "Codex executable was not found.\n")
    args.codex_bin = binary
    try:
        if args.check:
            print(json.dumps(asyncio.run(check_connection(args.codex_bin, Path(args.codex_home)))))
        else:
            asyncio.run(run(args))
    except (OSError, ProtocolError):
        parser.exit(1, "Codex status could not connect or start: check local daemon access and private runtime permissions.\n")
