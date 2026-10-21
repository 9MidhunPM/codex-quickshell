"""Bounded JSON-RPC connection to the existing Codex daemon.

This module deliberately has no generic public RPC method. The daemon itself is
powerful; the method and parameter allowlist here is the monitoring boundary.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import os
from pathlib import Path
import stat
import struct
from typing import Callable
from uuid import UUID

from . import __version__

MAX_FRAME = 2 * 1024 * 1024
REQUEST_TIMEOUT = 8.0


class ProtocolError(Exception):
    """A safe error category, never a raw provider response."""


class RpcError(ProtocolError):
    def __init__(self, code: int | None = None):
        super().__init__("Codex rejected a monitoring request")
        self.code = code


def valid_id(value: object) -> bool:
    if not isinstance(value, str) or len(value) != 36:
        return False
    try:
        return str(UUID(value)) == value.lower()
    except ValueError:
        return False


def control_socket(codex_home: Path) -> Path:
    """Validate both the public control directory and the symlink target."""
    directory = codex_home / "app-server-control"
    info = directory.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise ProtocolError("Unsafe Codex control directory")
    link = directory / "app-server-control.sock"
    if link.lstat().st_uid != os.getuid():
        raise ProtocolError("Unsafe Codex control socket owner")
    target = link.resolve(strict=True)
    parent, sock = target.parent.stat(), target.stat()
    if (parent.st_uid != os.getuid() or parent.st_mode & 0o077
            or sock.st_uid != os.getuid() or not stat.S_ISSOCK(sock.st_mode)):
        raise ProtocolError("Unsafe Codex control socket")
    return target


class CodexConnection:
    def __init__(self, binary: str, codex_home: Path,
                 on_notification: Callable[[str], None] | None = None):
        self.binary = binary
        self.codex_home = codex_home
        self.on_notification = on_notification
        self.process: asyncio.subprocess.Process | None = None
        self.reader_task: asyncio.Task | None = None
        self.pending: dict[int, asyncio.Future] = {}
        self.sequence = 0
        self.write_lock = asyncio.Lock()
        self.closed = asyncio.Event()
        self.initialized = False

    async def connect(self) -> None:
        sock = control_socket(self.codex_home)
        # The proxy needs no API credential. Do not hand inherited API keys to it.
        env = {key: value for key, value in os.environ.items()
               if key not in {"OPENAI_API_KEY", "OPENAI_ADMIN_KEY"}}
        env["CODEX_HOME"] = str(self.codex_home)
        self.process = await asyncio.create_subprocess_exec(
            self.binary, "app-server", "proxy", "--sock", str(sock),
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL, env=env, limit=MAX_FRAME + 1,
        )
        # `proxy` is a byte tunnel to the existing daemon's WebSocket endpoint,
        # not the NDJSON transport of a standalone `app-server` process.
        try:
            await self._upgrade()
        except (ValueError, asyncio.IncompleteReadError) as error:
            raise ProtocolError("Invalid Codex WebSocket upgrade") from error
        self.reader_task = asyncio.create_task(self._read())
        await self._request("initialize", {
            "clientInfo": {"name": "codex_quickshell", "title": "Codex status", "version": __version__},
            # Installed 0.163 exposes the read-only direct-input capability only
            # to experimental clients. Mutating RPCs remain disallowed below.
            "capabilities": {"experimentalApi": True},
        })
        await self._write({"method": "initialized"})
        self.initialized = True

    async def _upgrade(self) -> None:
        assert self.process is not None and self.process.stdin is not None and self.process.stdout is not None
        key = base64.b64encode(os.urandom(16)).decode("ascii")
        request = ("GET /rpc HTTP/1.1\r\nHost: localhost\r\nUpgrade: websocket\r\n"
                   "Connection: Upgrade\r\nSec-WebSocket-Key: " + key
                   + "\r\nSec-WebSocket-Version: 13\r\n\r\n")
        self.process.stdin.write(request.encode("ascii"))
        await asyncio.wait_for(self.process.stdin.drain(), REQUEST_TIMEOUT)

        async def headers() -> bytes:
            data = bytearray()
            while not data.endswith(b"\r\n\r\n"):
                data.extend(await self.process.stdout.readexactly(1))
                if len(data) > 8192:
                    raise ProtocolError("Oversized Codex upgrade response")
            return bytes(data)

        response = await asyncio.wait_for(headers(), REQUEST_TIMEOUT)
        lines = response.decode("ascii").split("\r\n")
        if len(lines[0].split()) < 2 or lines[0].split()[:2] != ["HTTP/1.1", "101"]:
            raise ProtocolError("Codex WebSocket upgrade refused")
        fields = {}
        for line in lines[1:]:
            if not line:
                continue
            name, sep, value = line.partition(":")
            if not sep or name.lower() in fields:
                raise ProtocolError("Invalid Codex upgrade response")
            fields[name.lower()] = value.strip()
        expected = base64.b64encode(hashlib.sha1(
            (key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode("ascii")
        ).digest()).decode("ascii")
        if (fields.get("sec-websocket-accept") != expected
                or fields.get("upgrade", "").lower() != "websocket"
                or "upgrade" not in fields.get("connection", "").lower().replace(" ", "").split(",")
                or "sec-websocket-extensions" in fields):
            raise ProtocolError("Invalid Codex WebSocket upgrade")

    async def _frame(self, opcode: int, data: bytes) -> None:
        if self.process is None or self.process.stdin is None or self.closed.is_set():
            raise ProtocolError("Codex disconnected")
        if len(data) > MAX_FRAME:
            raise ProtocolError("Oversized monitoring frame")
        header = bytes([0x80 | opcode])
        if len(data) < 126:
            header += bytes([0x80 | len(data)])
        elif len(data) <= 65535:
            header += bytes([0x80 | 126]) + struct.pack("!H", len(data))
        else:
            header += bytes([0x80 | 127]) + struct.pack("!Q", len(data))
        mask = os.urandom(4)
        masked = bytes(value ^ mask[index % 4] for index, value in enumerate(data))
        async with self.write_lock:
            self.process.stdin.write(header + mask + masked)
            await asyncio.wait_for(self.process.stdin.drain(), REQUEST_TIMEOUT)

    async def _message(self) -> bytes | None:
        assert self.process is not None and self.process.stdout is not None
        stream = self.process.stdout
        data = bytearray()
        fragmented = False
        while True:
            head = await stream.readexactly(2)
            final, opcode = bool(head[0] & 0x80), head[0] & 0x0F
            if head[0] & 0x70 or head[1] & 0x80:
                raise ProtocolError("Unsupported Codex frame")
            length = head[1] & 0x7F
            if length == 126:
                length = struct.unpack("!H", await stream.readexactly(2))[0]
            elif length == 127:
                length = struct.unpack("!Q", await stream.readexactly(8))[0]
            if length > MAX_FRAME or len(data) + length > MAX_FRAME:
                raise ProtocolError("Oversized Codex message")
            if opcode >= 8 and (not final or length > 125):
                raise ProtocolError("Invalid Codex control frame")
            payload = await stream.readexactly(length)
            if opcode == 8:
                if length == 1:
                    raise ProtocolError("Invalid Codex close frame")
                return None
            if opcode == 9:
                await self._frame(10, payload)
                continue
            if opcode == 10:
                continue
            if opcode == 1 and not fragmented:
                data.extend(payload)
            elif opcode == 0 and fragmented:
                data.extend(payload)
            else:
                raise ProtocolError("Unsupported Codex message type")
            if final:
                return bytes(data)
            fragmented = True

    async def _write(self, message: dict) -> None:
        if self.process is None or self.process.stdin is None or self.closed.is_set():
            raise ProtocolError("Codex disconnected")
        data = json.dumps(message, ensure_ascii=True, allow_nan=False, separators=(",", ":")).encode()
        await self._frame(1, data)

    async def _request(self, method: str, params: dict) -> dict:
        self.sequence += 1
        request_id = self.sequence
        future = asyncio.get_running_loop().create_future()
        self.pending[request_id] = future
        try:
            await self._write({"id": request_id, "method": method, "params": params})
            result = await asyncio.wait_for(future, REQUEST_TIMEOUT)
            if not isinstance(result, dict):
                raise ProtocolError("Unsupported Codex response")
            return result
        finally:
            self.pending.pop(request_id, None)
            if not future.done():
                future.cancel()

    async def read(self, method: str, params: dict | None = None) -> dict:
        params = {} if params is None else params
        if not self.initialized:
            raise ProtocolError("Codex handshake incomplete")
        allowed = (
            method == "account/read" and params == {"refreshToken": False}
            or method == "account/rateLimits/read" and params == {"excludeResetCreditDetails": True}
            or method == "thread/loaded/list" and set(params) <= {"cursor", "limit"}
               and params.get("limit") == 100
               and (params.get("cursor") is None or isinstance(params["cursor"], str)
                    and len(params["cursor"]) <= 4096)
            or method == "thread/read" and set(params) == {"threadId", "includeTurns"}
               and valid_id(params["threadId"]) and params["includeTurns"] is False
        )
        if not allowed:
            raise ProtocolError("Monitoring method or parameters not permitted")
        return await self._request(method, params)

    async def _read(self) -> None:
        try:
            assert self.process is not None and self.process.stdout is not None
            while True:
                payload = await self._message()
                if payload is None:
                    break
                message = json.loads(payload)
                if not isinstance(message, dict):
                    raise ProtocolError("Invalid Codex response")
                # No approvals, tool calls, or authentication callbacks can be
                # executed through this monitoring connection.
                if "method" in message:
                    if "id" in message:
                        await self._write({"id": message["id"], "error": {
                            "code": -32601, "message": "Read-only status client"}})
                    elif message["method"] in {"account/updated", "account/rateLimits/updated"}:
                        if self.on_notification:
                            self.on_notification(message["method"])
                    continue
                request_id = message.get("id")
                if type(request_id) is not int:
                    continue
                future = self.pending.get(request_id)
                if future is None or future.done():
                    continue
                if "error" in message:
                    error = message["error"]
                    code = error.get("code") if isinstance(error, dict) else None
                    future.set_exception(RpcError(code if type(code) is int else None))
                else:
                    future.set_result(message.get("result"))
        except (ValueError, TypeError, OSError, ProtocolError, asyncio.IncompleteReadError):
            pass
        finally:
            self.closed.set()
            for future in list(self.pending.values()):
                if not future.done():
                    future.set_exception(ProtocolError("Codex disconnected"))

    async def close(self) -> None:
        self.closed.set()
        if self.reader_task:
            self.reader_task.cancel()
            await asyncio.gather(self.reader_task, return_exceptions=True)
        if self.process:
            if self.process.stdin:
                self.process.stdin.close()
            if self.process.returncode is None:
                try:
                    self.process.terminate()
                except ProcessLookupError:
                    pass
                try:
                    await asyncio.wait_for(self.process.wait(), 2)
                except asyncio.TimeoutError:
                    self.process.kill()
                    await self.process.wait()
