import asyncio
import argparse
import io
import json
import os
from pathlib import Path
import signal
import stat
import tempfile
import time
import runpy
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

from codex_status.protocol import ProtocolError, RpcError, control_socket
from codex_status.service import (Bridge, UiClient, main, resolve_terminal,
                                  run as run_bridge, secure_listener,
                                  terminal_command)

ROOT = "0199a000-0000-7000-8000-000000000001"
CHILD = "0199a000-0000-7000-8000-000000000002"


def thread(identifier=ROOT):
    return {"id": identifier, "name": "A task", "status": {"type": "active", "activeFlags": []},
            "canAcceptDirectInput": True, "ephemeral": False}


class FakeClock:
    """Control bridge scheduling without replacing the event loop's clock."""

    def __init__(self, now=100.0):
        self.now = now

    def monotonic(self):
        return self.now

    def time(self):
        return 1_700_000_000 + self.now


class ServiceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.bridge = Bridge("/fixed/codex", Path("/unused"))
        self.client = UiClient(None, None)

    async def test_unknown_id_and_shell_payload_cannot_launch(self):
        with patch.object(self.bridge, "launch", new_callable=AsyncMock) as launch:
            for value in [ROOT, "$(touch /tmp/forbidden)", "--help", [ROOT]]:
                self.client.last_action = 0
                await self.bridge.handle(self.client, {"type": "open_session", "threadId": value})
            launch.assert_not_called()

    async def test_open_only_known_fresh_target_with_argument_vector(self):
        self.bridge.agents = {"state": "fresh", "observedAt": time.time(), "activeCount": 1,
                              "items": [{"id": CHILD, "openTargetId": ROOT}]}
        with patch("codex_status.service.shutil.which", return_value="/usr/bin/kitty"), \
             patch.object(self.bridge, "launch", new_callable=AsyncMock, return_value=True) as launch:
            await self.bridge.handle(self.client, {"type": "open_session", "threadId": ROOT})
            launch.assert_awaited_once_with(["/usr/bin/kitty", "-e", "/fixed/codex", "resume", ROOT])
            self.bridge.agents["observedAt"] -= 30
            self.client.last_action = 0
            await self.bridge.handle(self.client, {"type": "open_session", "threadId": ROOT})
            self.assertEqual(launch.await_count, 1)

    async def test_only_fixed_dashboard_urls_are_launchable(self):
        with patch("codex_status.service.shutil.which", return_value="/usr/bin/xdg-open"), \
             patch.object(self.bridge, "launch", new_callable=AsyncMock, return_value=True) as launch:
            await self.bridge.handle(self.client, {"type": "open_dashboard", "target": "billing"})
            launch.assert_awaited_once_with(["/usr/bin/xdg-open", "https://platform.openai.com/settings/organization/billing"])
            self.client.last_action = 0
            await self.bridge.handle(self.client, {"type": "open_dashboard", "target": "https://evil.test"})
            self.assertEqual(launch.await_count, 1)

    async def test_monitor_only_blocks_all_open_actions_but_keeps_refresh(self):
        self.bridge.actions_enabled = False
        self.bridge.agents = {"state": "fresh", "observedAt": time.time(), "activeCount": 1,
                              "items": [{"id": ROOT, "openTargetId": ROOT}]}
        with patch.object(self.bridge, "launch", new_callable=AsyncMock) as launch, \
             patch("codex_status.service.shutil.which") as which:
            await self.bridge.handle(self.client, {"type": "open_session", "threadId": ROOT})
            await self.bridge.handle(self.client, {"type": "open_dashboard", "target": "usage"})
            which.assert_not_called()
            launch.assert_not_called()
        self.bridge.refresh_usage = False
        await self.bridge.handle(self.client, {"type": "refresh"})
        self.assertTrue(self.bridge.refresh_usage)
        await self.bridge.handle(self.client, {"type": "visibility", "open": True})
        self.assertTrue(self.client.open)
        self.assertFalse(await self.bridge.launch(["/unused/program"]))

    async def test_custom_terminal_arguments_are_literal_and_session_tail_is_fixed(self):
        self.bridge.terminal = terminal_command("foot --title 'Codex $(not-a-command)' -e")
        self.bridge.agents = {"state": "fresh", "observedAt": time.time(), "activeCount": 1,
                              "items": [{"id": ROOT, "openTargetId": ROOT}]}
        with patch("codex_status.service.shutil.which", return_value="/usr/bin/foot"), \
             patch.object(self.bridge, "launch", new_callable=AsyncMock, return_value=True) as launch:
            await self.bridge.handle(self.client, {"type": "open_session", "threadId": ROOT})
        launch.assert_awaited_once_with([
            "/usr/bin/foot", "--title", "Codex $(not-a-command)", "-e",
            "/fixed/codex", "resume", ROOT,
        ])

    async def test_absent_terminal_and_unsupported_requests_do_not_launch(self):
        self.bridge.agents = {"state": "fresh", "observedAt": time.time(), "activeCount": 1,
                              "items": [{"id": ROOT, "openTargetId": ROOT}]}
        with patch("codex_status.service.shutil.which", return_value=None), \
             patch.object(self.bridge, "launch", new_callable=AsyncMock) as launch:
            for request in [
                {"type": "open_session", "threadId": ROOT},
                {"type": "open_dashboard", "target": "usage"},
                {"type": "open_session", "threadId": ROOT, "command": "/bin/sh"},
                {"type": "execute", "argv": ["/bin/sh"]},
            ]:
                self.client.last_action = 0
                await self.bridge.handle(self.client, request)
            launch.assert_not_called()

    async def test_detached_fallback_preserves_environment_without_shell_or_blocking(self):
        process, reaper = Mock(), Mock()
        command = ["/usr/bin/foot", "-e", "/fixed/codex", "resume", ROOT]
        with patch("codex_status.service.shutil.which", return_value=None), \
             patch("codex_status.service.subprocess.Popen", return_value=process) as spawn, \
             patch("codex_status.service.threading.Thread", return_value=reaper) as thread_mock, \
             patch.dict(os.environ, {"WAYLAND_DISPLAY": "wayland-example"}):
            self.assertTrue(await self.bridge.launch(command))
        self.assertEqual(spawn.call_args.args, (command,))
        options = spawn.call_args.kwargs
        self.assertEqual(options["env"]["CODEX_HOME"], "/unused")
        self.assertEqual(options["env"]["WAYLAND_DISPLAY"], "wayland-example")
        self.assertTrue(options["start_new_session"])
        self.assertEqual(options["stdin"], options["stdout"])
        self.assertEqual(options["stdout"], options["stderr"])
        self.assertNotIn("shell", options)
        thread_mock.assert_called_once_with(target=process.wait, daemon=True,
                                           name="codex-quickshell-open-reaper")
        reaper.start.assert_called_once_with()
        process.wait.assert_not_called()

    async def test_failed_detached_launch_is_reported_safely(self):
        with patch("codex_status.service.shutil.which", return_value=None), \
             patch("codex_status.service.subprocess.Popen", side_effect=FileNotFoundError), \
             patch("codex_status.service.threading.Thread") as reaper:
            self.assertFalse(await self.bridge.launch(["/missing/terminal"]))
        reaper.assert_not_called()

    async def test_failed_systemd_launch_does_not_duplicate_application(self):
        process = AsyncMock()
        process.wait.return_value = 1
        with patch("codex_status.service.shutil.which", return_value="/usr/bin/systemd-run"), \
             patch("codex_status.service.asyncio.create_subprocess_exec", return_value=process), \
             patch("codex_status.service.subprocess.Popen") as fallback:
            self.assertFalse(await self.bridge.launch(["/unused/application"]))
        fallback.assert_not_called()

    async def test_account_change_clears_previous_usage(self):
        self.bridge.usage = {"state": "fresh", "plan": "old-account", "buckets": [{"credits": "private"}]}
        rpc = AsyncMock()
        rpc.read.return_value = {"account": {"type": "apiKey"}}
        await self.bridge.read_usage(rpc)
        self.assertEqual(self.bridge.usage["state"], "unavailable")
        self.assertNotIn("private", json.dumps(self.bridge.snapshot()))
        rpc.read.assert_awaited_once_with("account/read", {"refreshToken": False})

    async def test_sparse_account_notification_invalidates_without_using_payload(self):
        self.bridge.usage = {"state": "fresh", "buckets": [{"id": "old"}]}
        self.bridge.notification("account/updated")
        self.assertEqual(self.bridge.usage["state"], "unavailable")
        self.assertTrue(self.bridge.wake.is_set())

    async def test_account_change_during_quota_request_discards_inflight_values(self):
        async def read(method, params):
            if method == "account/read":
                return {"account": {"type": "chatgpt", "planType": "pro", "email": "private"}}
            self.bridge.notification("account/updated")
            return {"rateLimits": {"primary": {"usedPercent": 12, "windowDurationMins": 10080}}}

        rpc = AsyncMock()
        rpc.read.side_effect = read
        await self.bridge.read_usage(rpc)
        self.assertEqual(self.bridge.usage["state"], "unavailable")
        self.assertIsNone(self.bridge.identity)

    async def test_account_change_during_identity_read_never_requests_old_account_quota(self):
        async def read(method, params):
            self.bridge.notification("account/updated")
            return {"account": {"type": "chatgpt", "planType": "pro"},
                    "workspaceRouting": {"chatgptAccountId": "previous-account"}}

        rpc = AsyncMock()
        rpc.read.side_effect = read
        await self.bridge.read_usage(rpc)
        rpc.read.assert_awaited_once_with("account/read", {"refreshToken": False})
        self.assertEqual(self.bridge.usage["state"], "unavailable")
        self.assertEqual(self.bridge.usage["buckets"], [])
        self.assertIsNone(self.bridge.identity)
        self.assertTrue(self.bridge.refresh_usage)

    async def test_quota_for_different_workspace_is_not_published(self):
        rpc = AsyncMock()
        rpc.read.side_effect = [
            {"account": {"type": "chatgpt", "planType": "plus"},
             "workspaceRouting": {"chatgptAccountId": "current-account"}},
            {"accountId": "other-account",
             "rateLimits": {"primary": {"usedPercent": 12, "windowDurationMins": 10080},
                            "credits": {"balance": "PRIVATE_BALANCE",
                                        "hasCredits": True, "unlimited": False}}},
        ]
        await self.bridge.read_usage(rpc)
        self.assertEqual(rpc.read.await_count, 2)
        self.assertEqual(self.bridge.usage["state"], "unavailable")
        self.assertEqual(self.bridge.usage["buckets"], [])
        self.assertNotIn("PRIVATE_BALANCE", json.dumps(self.bridge.snapshot()))

    async def test_successful_handshake_does_not_reset_failed_monitoring_backoff(self):
        clock = FakeClock()
        connections, delays = [], []

        def connection(*args):
            rpc = SimpleNamespace(connect=AsyncMock(), close=AsyncMock(),
                                  closed=asyncio.Event())
            connections.append(rpc)
            return rpc

        async def sleep(delay):
            delays.append(delay)
            clock.now += delay
            if len(delays) == 7:
                raise asyncio.CancelledError()

        # The first required monitoring read fails after every successful
        # handshake, as it would against an incompatible daemon version.
        with patch("codex_status.service.CodexConnection", side_effect=connection), \
             patch("codex_status.service.time", clock), \
             patch("codex_status.service.asyncio", SimpleNamespace(sleep=sleep)), \
             patch.object(self.bridge, "read_usage", new_callable=AsyncMock), \
             patch.object(self.bridge, "read_agents", new_callable=AsyncMock,
                          side_effect=RpcError(-32601)):
            with self.assertRaises(asyncio.CancelledError):
                await self.bridge.monitor()

        self.assertEqual(delays, [1, 2, 4, 8, 16, 30, 30])
        self.assertEqual(len(connections), len(delays))
        for rpc in connections:
            rpc.connect.assert_awaited_once()
            rpc.close.assert_awaited_once()
        self.assertEqual(self.bridge.connection["state"], "incompatible")
        self.assertIsNone(self.bridge.agents["activeCount"])

    async def test_popup_and_rate_notification_burst_share_quota_cooldown(self):
        clock = FakeClock()
        self.bridge.clients.add(self.client)
        quota_times, identity_times = [], []
        wake_times = iter([100.1, 100.2, 101, 105, 109.999, 110, 110.01])

        async def read(method, params):
            if method == "account/read":
                identity_times.append(clock.monotonic())
                return {"account": {"type": "chatgpt", "planType": "plus"}}
            if method == "account/rateLimits/read":
                quota_times.append(clock.monotonic())
                return {"rateLimits": {"primary": {"usedPercent": 25}}}
            self.fail(f"Unexpected RPC method: {method}")

        rpc = SimpleNamespace(connect=AsyncMock(), close=AsyncMock(),
                              closed=asyncio.Event(), read=AsyncMock(side_effect=read))

        async def wait_for(awaitable, timeout):
            # This replaces only the bridge's wake wait. No real sleeps, network
            # traffic, or event-loop clock changes are needed to cross 10s.
            awaitable.close()
            try:
                clock.now = next(wake_times)
            except StopIteration:
                raise asyncio.CancelledError() from None
            for _ in range(5):
                await self.bridge.handle(self.client, {"type": "visibility", "open": False})
                await self.bridge.handle(self.client, {"type": "visibility", "open": True})
                self.bridge.notification("account/rateLimits/updated")
                await self.bridge.handle(self.client, {"type": "refresh"})
            return True

        with patch("codex_status.service.CodexConnection", return_value=rpc), \
             patch("codex_status.service.time", clock), \
             patch("codex_status.service.asyncio",
                   SimpleNamespace(wait_for=wait_for, TimeoutError=asyncio.TimeoutError)), \
             patch.object(self.bridge, "read_agents", new_callable=AsyncMock):
            with self.assertRaises(asyncio.CancelledError):
                await self.bridge.monitor()

        self.assertEqual(quota_times, [100, 110])
        self.assertEqual(identity_times, [100, 110])
        rpc.connect.assert_awaited_once()
        rpc.close.assert_awaited_once()

    async def test_open_actions_run_in_separate_user_services_with_literal_arguments(self):
        self.bridge.binary = "/opt/Codex Builds/codex"
        self.bridge.codex_home = Path("/home/test/Codex Data")
        self.bridge.agents = {
            "state": "fresh", "observedAt": time.time(), "activeCount": 1,
            "items": [{"id": ROOT, "openTargetId": ROOT}],
        }
        executables = {
            "kitty": "/usr/bin/kitty", "xdg-open": "/usr/bin/xdg-open",
            "systemd-run": "/usr/bin/systemd-run",
        }
        process = AsyncMock()
        process.wait.return_value = 0
        process.returncode = 0
        with patch("codex_status.service.shutil.which", side_effect=executables.get), \
             patch("codex_status.service.asyncio.create_subprocess_exec",
                   new_callable=AsyncMock, return_value=process) as spawn, \
             patch("codex_status.service.asyncio.create_subprocess_shell",
                   new_callable=AsyncMock) as shell:
            await self.bridge.handle(self.client, {"type": "open_session", "threadId": ROOT})
            self.client.last_action = 0
            await self.bridge.handle(self.client, {"type": "open_dashboard", "target": "billing"})

        self.assertEqual(spawn.await_count, 2)
        commands = [list(call.args) for call in spawn.await_args_list]
        expected_apps = [
            ["/usr/bin/kitty", "-e", "/opt/Codex Builds/codex", "resume", ROOT],
            ["/usr/bin/xdg-open", "https://platform.openai.com/settings/organization/billing"],
        ]
        units = []
        for command, expected in zip(commands, expected_apps):
            self.assertEqual(command[0], "/usr/bin/systemd-run")
            self.assertIn("--user", command)
            self.assertIn("--collect", command)
            self.assertIn("--service-type=exec", command)
            self.assertIn("--expand-environment=no", command)
            self.assertIn("--setenv=CODEX_HOME=/home/test/Codex Data", command)
            self.assertEqual(command[command.index("--") + 1:], expected)
            units.append(next(arg for arg in command if arg.startswith("--unit=")))
        self.assertNotEqual(units[0], units[1])
        shell.assert_not_awaited()
        self.assertEqual(self.bridge.action_processes, set())

    async def test_listing_pagination_and_no_resuming(self):
        calls = []

        async def read(method, params):
            calls.append((method, params))
            if method == "thread/loaded/list":
                return {"data": [ROOT] if params["cursor"] is None else [CHILD],
                        "nextCursor": "next" if params["cursor"] is None else None}
            return {"thread": thread(params["threadId"])}

        rpc = AsyncMock()
        rpc.read.side_effect = read
        await self.bridge.read_agents(rpc)
        self.assertEqual(self.bridge.agents["activeCount"], 2)
        self.assertEqual({method for method, _ in calls}, {"thread/loaded/list", "thread/read"})
        self.assertTrue(all(not params["includeTurns"] for method, params in calls if method == "thread/read"))

    async def test_raced_metadata_does_not_fabricate_complete_count(self):
        async def read(method, params):
            if method == "thread/loaded/list":
                return {"data": [ROOT, CHILD]}
            if params["threadId"] == CHILD:
                raise RpcError(-32000)
            return {"thread": thread()}

        rpc = AsyncMock()
        rpc.read.side_effect = read
        await self.bridge.read_agents(rpc)
        self.assertIsNone(self.bridge.agents["activeCount"])
        self.assertEqual(self.bridge.agents["state"], "unavailable")

    async def test_queue_is_bounded_and_retains_latest(self):
        for number in range(100):
            self.client.enqueue({"number": number})
        self.assertEqual(self.client.queue.qsize(), 2)
        self.assertEqual((await self.client.queue.get())["number"], 98)
        self.assertEqual((await self.client.queue.get())["number"], 99)

    async def test_manual_refresh_is_coalesced(self):
        self.bridge.refresh_usage = False
        await self.bridge.handle(self.client, {"type": "refresh"})
        self.assertTrue(self.bridge.refresh_usage)
        self.bridge.refresh_usage = False
        await self.bridge.handle(self.client, {"type": "refresh"})
        self.assertFalse(self.bridge.refresh_usage)

    async def test_sigterm_closes_idle_ui_client_before_waiting_for_server_shutdown(self):
        """An attached Quickshell client must not block a service restart."""
        loop = asyncio.get_running_loop()
        handlers, servers = {}, []
        ready = asyncio.Event()
        start_server = asyncio.start_unix_server
        original_umask = os.umask(0o077)
        os.umask(original_umask)
        run_task = readiness_task = writer = None

        async def idle_monitor(_bridge):
            await asyncio.Event().wait()

        async def start_and_record(*args, **kwargs):
            server = await start_server(*args, **kwargs)
            servers.append(server)
            ready.set()
            return server

        with tempfile.TemporaryDirectory() as folder:
            socket_path = Path(folder) / "status.sock"
            args = SimpleNamespace(socket=str(socket_path), codex_bin="/unused/codex",
                                   codex_home="/unused/codex-home")
            try:
                with patch.object(loop, "add_signal_handler",
                                  side_effect=lambda sig, callback: handlers.__setitem__(sig, callback)), \
                     patch("codex_status.service.asyncio.start_unix_server",
                           new=start_and_record), \
                     patch.object(Bridge, "monitor", new=idle_monitor), \
                     patch.object(Bridge, "heartbeat", new=idle_monitor):
                    run_task = asyncio.create_task(run_bridge(args))
                    readiness_task = asyncio.create_task(ready.wait())
                    done, _ = await asyncio.wait(
                        {run_task, readiness_task}, timeout=1,
                        return_when=asyncio.FIRST_COMPLETED,
                    )
                    if run_task in done:
                        try:
                            await run_task
                        except PermissionError:
                            self.skipTest(
                                "Sandbox denies Unix sockets; run shutdown regression on the host"
                            )
                    self.assertIn(readiness_task, done, "Private listener did not become ready")
                    reader, writer = await asyncio.open_unix_connection(str(socket_path))
                    # Receiving a snapshot proves the server accepted this client
                    # and is holding an active connection when SIGTERM arrives.
                    snapshot = json.loads(await asyncio.wait_for(reader.readline(), 1))
                    self.assertEqual(snapshot["type"], "snapshot")
                    handlers[signal.SIGTERM]()
                    await asyncio.wait_for(run_task, 1)
                    self.assertEqual(await asyncio.wait_for(reader.read(), 1), b"")
                    self.assertFalse(servers[0].is_serving())
                    self.assertFalse(socket_path.exists())
            finally:
                # Close the test peer even when exercising the old deadlock, so a
                # failing regression never leaves the test event loop blocked.
                if writer is not None:
                    writer.close()
                    await writer.wait_closed()
                for task in (run_task, readiness_task):
                    if task is not None and not task.done():
                        task.cancel()
                await asyncio.gather(
                    *(task for task in (run_task, readiness_task) if task is not None),
                    return_exceptions=True,
                )
                os.umask(original_umask)


class RuntimePathTests(unittest.TestCase):
    def test_terminal_command_parses_argument_vector_without_expansion(self):
        self.assertEqual(terminal_command("'/opt/Terminal App/terminal' --title '$HOME' -e"),
                         ("/opt/Terminal App/terminal", "--title", "$HOME", "-e"))
        for invalid in ("", "  ", "'broken", "foot\0 -e", "a" * 4097):
            with self.subTest(invalid=invalid[:20]), self.assertRaises(argparse.ArgumentTypeError):
                terminal_command(invalid)

    def test_terminal_discovery_uses_known_argument_prefixes(self):
        for executable, expected in [
            ("foot", ["/bin/foot", "-e"]),
            ("wezterm", ["/bin/wezterm", "start", "--"]),
            ("gnome-terminal", ["/bin/gnome-terminal", "--"]),
        ]:
            with self.subTest(executable=executable), \
                 patch("codex_status.service.shutil.which",
                       side_effect=lambda name: f"/bin/{name}" if name == executable else None):
                self.assertEqual(resolve_terminal(None), expected)

    def test_explicit_missing_terminal_does_not_silently_change_configuration(self):
        with patch("codex_status.service.shutil.which", return_value=None) as which:
            self.assertIsNone(resolve_terminal(("my-terminal", "--")))
        which.assert_called_once_with("my-terminal")

    def test_help_needs_neither_codex_nor_a_running_daemon(self):
        with patch("sys.stdout", new_callable=io.StringIO) as output, \
             patch("codex_status.service.shutil.which") as which, \
             patch("codex_status.service.run") as run:
            with self.assertRaises(SystemExit) as result:
                main(["--help"])
        self.assertEqual(result.exception.code, 0)
        self.assertIn("--terminal", output.getvalue())
        self.assertIn("--disable-actions", output.getvalue())
        run.assert_not_called()
        # Building argparse defaults may locate Codex; no executable is run.
        which.assert_called_once_with("codex")

    def test_entry_module_is_import_safe(self):
        with patch("codex_status.service.main") as entry:
            runpy.run_module("codex_status", run_name="codex_status_import_test")
        entry.assert_not_called()

    def test_refuses_public_runtime_directory(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)
            path.chmod(0o755)
            with self.assertRaises(ProtocolError):
                secure_listener(path / "status.sock")

    def test_refuses_foreign_file_without_replacing_it(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "status.sock"
            path.write_text("keep me")
            with self.assertRaises(ProtocolError):
                secure_listener(path)
            self.assertEqual(path.read_text(), "keep me")

    def test_private_listener_and_duplicate_lock(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "status.sock"
            try:
                listener, lock = secure_listener(path)
            except PermissionError:
                self.skipTest("Sandbox denies Unix socket creation; live runtime test required")
            try:
                self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
                with self.assertRaises(BlockingIOError):
                    secure_listener(path)
            finally:
                listener.close()
                path.unlink(missing_ok=True)
                os.close(lock)

    def test_control_directory_must_be_private(self):
        with tempfile.TemporaryDirectory() as folder:
            control = Path(folder) / "app-server-control"
            control.mkdir(mode=0o755)
            with self.assertRaises(ProtocolError):
                control_socket(Path(folder))
