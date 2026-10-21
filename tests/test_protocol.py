import asyncio
import base64
import hashlib
import json
from pathlib import Path
import struct
import unittest
from unittest.mock import patch

from codex_status.protocol import CodexConnection, ProtocolError, RpcError

THREAD = "0199a000-0000-7000-8000-000000000001"
WEBSOCKET_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"


def server_frame(value, opcode=1, final=True, masked=False):
    payload = value if isinstance(value, bytes) else json.dumps(value).encode()
    head = bytearray([(0x80 if final else 0) | opcode])
    mask_bit = 0x80 if masked else 0
    if len(payload) < 126:
        head.append(mask_bit | len(payload))
    elif len(payload) <= 65535:
        head.append(mask_bit | 126)
        head.extend(struct.pack("!H", len(payload)))
    else:
        head.append(mask_bit | 127)
        head.extend(struct.pack("!Q", len(payload)))
    if masked:
        key = b"\x01\x02\x03\x04"
        head.extend(key)
        payload = bytes(value ^ key[index % 4] for index, value in enumerate(payload))
    return bytes(head) + payload


class FakeInput:
    def __init__(self, output):
        self.output, self.messages = output, []
        self.frames = []
        self.auto_reply = True
        self.buffer = bytearray()
        self.upgrade_request = None
        self.invalid_accept = False
        self.upgrade_status = "101 Switching Protocols"

    def write(self, data):
        self.buffer.extend(data)
        if self.upgrade_request is None:
            end = self.buffer.find(b"\r\n\r\n")
            if end < 0:
                return
            self.upgrade_request = bytes(self.buffer[:end + 4])
            del self.buffer[:end + 4]
            headers = {}
            for line in self.upgrade_request.decode("ascii").split("\r\n")[1:]:
                if ":" in line:
                    name, value = line.split(":", 1)
                    headers[name.lower()] = value.strip()
            nonce = headers["sec-websocket-key"]
            accept = base64.b64encode(
                hashlib.sha1((nonce + WEBSOCKET_GUID).encode("ascii")).digest()
            ).decode("ascii")
            if self.invalid_accept:
                accept = "incorrect-accept-value"
            self.output.feed_data(
                (f"HTTP/1.1 {self.upgrade_status}\r\n"
                 "Upgrade: websocket\r\nConnection: Upgrade\r\n"
                 f"Sec-WebSocket-Accept: {accept}\r\n\r\n").encode("ascii")
            )
        while len(self.buffer) >= 2:
            first, second = self.buffer[:2]
            if not second & 0x80:
                raise AssertionError("Client WebSocket frames must be masked")
            size = second & 0x7f
            offset = 2
            if size in (126, 127):
                width = 2 if size == 126 else 8
                if len(self.buffer) < offset + width:
                    return
                size = int.from_bytes(self.buffer[offset:offset + width], "big")
                offset += width
            if len(self.buffer) < offset + 4 + size:
                return
            key = self.buffer[offset:offset + 4]
            offset += 4
            payload = bytes(
                value ^ key[index % 4]
                for index, value in enumerate(self.buffer[offset:offset + size])
            )
            del self.buffer[:offset + size]
            opcode = first & 0x0f
            self.frames.append((opcode, payload))
            if opcode == 1:
                message = json.loads(payload)
                self.messages.append(message)
                if self.auto_reply and "method" in message and "id" in message:
                    self.output.feed_data(server_frame({"id": message["id"], "result": {}}))

    async def drain(self):
        pass

    def close(self):
        pass


class FakeProcess:
    def __init__(self):
        self.stdout = asyncio.StreamReader()
        self.stdin = FakeInput(self.stdout)
        self.returncode = None

    def terminate(self):
        self.returncode = 0

    def kill(self):
        self.returncode = -9

    async def wait(self):
        return self.returncode


class ProtocolTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.process = FakeProcess()
        self.notifications = []
        self.rpc = CodexConnection("/fixed/codex", Path("/unused"), self.notifications.append)
        self.socket_patch = patch("codex_status.protocol.control_socket", return_value=Path("/private/control.sock"))
        self.spawn_patch = patch("codex_status.protocol.asyncio.create_subprocess_exec", return_value=self.process)
        self.socket_patch.start()
        self.spawn = self.spawn_patch.start()
        await self.rpc.connect()

    async def asyncTearDown(self):
        await self.rpc.close()
        self.spawn_patch.stop()
        self.socket_patch.stop()

    async def test_handshake_and_proxy_only(self):
        self.assertTrue(self.process.stdin.upgrade_request.startswith(b"GET /rpc HTTP/1.1\r\n"))
        self.assertIn(b"Sec-WebSocket-Key:", self.process.stdin.upgrade_request)
        self.assertEqual([m["method"] for m in self.process.stdin.messages], ["initialize", "initialized"])
        self.assertTrue(self.process.stdin.messages[0]["params"]["capabilities"]["experimentalApi"])
        self.assertEqual(self.spawn.call_args.args, ("/fixed/codex", "app-server", "proxy", "--sock", "/private/control.sock"))
        self.assertNotIn("OPENAI_API_KEY", self.spawn.call_args.kwargs["env"])

    async def test_allowlist_rejects_mutations_and_unsafe_parameters(self):
        rejected = [
            ("turn/start", {}), ("thread/resume", {"threadId": THREAD}),
            ("account/logout", {}), ("account/read", {"refreshToken": True}),
            ("account/rateLimits/read", {"supportsLunaReserve": True}),
            ("thread/read", {"threadId": THREAD, "includeTurns": True}),
            ("thread/read", {"threadId": "--help", "includeTurns": False}),
            ("thread/loaded/list", {"limit": 100, "cursor": [], "unexpected": True}),
        ]
        before = len(self.process.stdin.messages)
        for method, params in rejected:
            with self.subTest(method=method, params=params), self.assertRaises(ProtocolError):
                await self.rpc.read(method, params)
        self.assertEqual(len(self.process.stdin.messages), before)

    async def test_supported_metadata_read(self):
        await self.rpc.read("thread/read", {"threadId": THREAD, "includeTurns": False})
        self.assertEqual(self.process.stdin.messages[-1]["params"], {"threadId": THREAD, "includeTurns": False})

    async def test_partial_frames_and_sparse_notification(self):
        frame = server_frame({"method": "account/rateLimits/updated",
                              "params": {"secret": "discard"}})
        self.process.stdout.feed_data(frame[:9])
        await asyncio.sleep(0)
        self.assertEqual(self.notifications, [])
        self.process.stdout.feed_data(frame[9:])
        await asyncio.sleep(0.01)
        self.assertEqual(self.notifications, ["account/rateLimits/updated"])

    async def test_unsolicited_server_request_is_declined(self):
        self.process.stdout.feed_data(server_frame({
            "id": 99, "method": "item/commandExecution/requestApproval", "params": {}}))
        await asyncio.sleep(0.01)
        self.assertEqual(self.process.stdin.messages[-1], {"id": 99, "error": {"code": -32601, "message": "Read-only status client"}})

    async def test_raw_provider_error_never_escapes(self):
        self.process.stdin.auto_reply = False
        task = asyncio.create_task(self.rpc.read("account/read", {"refreshToken": False}))
        await asyncio.sleep(0)
        request_id = self.process.stdin.messages[-1]["id"]
        self.process.stdout.feed_data(server_frame({
            "id": request_id, "error": {"code": -32601, "message": "SECRET TRANSCRIPT"}}))
        with self.assertRaises(RpcError) as error:
            await task
        self.assertNotIn("SECRET", str(error.exception))
        self.assertEqual(error.exception.code, -32601)

    async def test_malformed_frame_disconnects_and_fails_pending(self):
        self.process.stdin.auto_reply = False
        task = asyncio.create_task(self.rpc.read("account/read", {"refreshToken": False}))
        await asyncio.sleep(0)
        self.process.stdout.feed_data(server_frame(b"not json"))
        with self.assertRaises(ProtocolError):
            await task
        self.assertTrue(self.rpc.closed.is_set())

    async def test_request_deadline_clears_pending(self):
        self.process.stdin.auto_reply = False
        with patch("codex_status.protocol.REQUEST_TIMEOUT", 0.01):
            with self.assertRaises(asyncio.TimeoutError):
                await self.rpc.read("account/read", {"refreshToken": False})
        self.assertEqual(self.rpc.pending, {})

    async def test_fragmented_notification_with_interleaved_ping(self):
        payload = json.dumps({"method": "account/rateLimits/updated",
                              "params": {"ignored": "private"}}).encode()
        self.process.stdout.feed_data(server_frame(payload[:19], final=False))
        self.process.stdout.feed_data(server_frame(b"ping-value", opcode=9))
        await asyncio.sleep(0.01)
        self.assertEqual(self.notifications, [])
        self.assertIn((10, b"ping-value"), self.process.stdin.frames)
        self.process.stdout.feed_data(server_frame(payload[19:], opcode=0))
        await asyncio.sleep(0.01)
        self.assertEqual(self.notifications, ["account/rateLimits/updated"])
        self.assertFalse(self.rpc.closed.is_set())

    async def test_masked_server_frame_is_rejected_and_pending_read_fails(self):
        self.process.stdin.auto_reply = False
        pending = asyncio.create_task(self.rpc.read("account/read", {"refreshToken": False}))
        await asyncio.sleep(0)
        request_id = self.process.stdin.messages[-1]["id"]
        self.process.stdout.feed_data(server_frame(
            {"id": request_id, "result": {}}, masked=True))
        with self.assertRaises(ProtocolError):
            await pending
        self.assertTrue(self.rpc.closed.is_set())

    async def test_invalid_upgrade_never_sends_initialize(self):
        for failure in ("accept", "status"):
            with self.subTest(failure=failure):
                process = FakeProcess()
                process.stdin.invalid_accept = failure == "accept"
                if failure == "status":
                    process.stdin.upgrade_status = "200 OK"
                rpc = CodexConnection("/fixed/codex", Path("/unused"))
                try:
                    with patch("codex_status.protocol.asyncio.create_subprocess_exec",
                               return_value=process):
                        with self.assertRaises(ProtocolError):
                            await rpc.connect()
                    self.assertEqual(process.stdin.messages, [])
                    self.assertFalse(rpc.initialized)
                finally:
                    await rpc.close()

    async def test_oversized_control_frame_is_rejected(self):
        self.process.stdin.auto_reply = False
        pending = asyncio.create_task(self.rpc.read("account/read", {"refreshToken": False}))
        await asyncio.sleep(0)
        self.process.stdout.feed_data(server_frame(b"x" * 126, opcode=9))
        with self.assertRaises(ProtocolError):
            await pending
        self.assertTrue(self.rpc.closed.is_set())
