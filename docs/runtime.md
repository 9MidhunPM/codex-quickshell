# Bridge runtime and optional actions

The Python bridge attaches to an **already running** Codex daemon. It does not
start a daemon, authenticate, run a model, read saved credentials, or request
conversation contents. `python3 -m codex_status --help` works without Codex
installed; `--check` performs only the supported metadata capability reads.

Codex is located on `PATH`, or selected with `--codex-bin /path/to/codex`.
`--codex-home` overrides `CODEX_HOME`; otherwise Codex's standard `~/.codex`
directory is used. The socket defaults to
`$XDG_RUNTIME_DIR/codex-quickshell/status.sock`, with `/run/user/<uid>` as the
Linux runtime fallback. The runtime directory must be private and owned by the
current user. The bridge creates a mode `0600` socket and verifies every client's
Linux `SO_PEERCRED` UID. Use one bridge per user and a matching frontend socket.

## Terminal selection

Opening an agent is an explicit desktop action, separate from telemetry. The
bridge accepts only a known, fresh, persistent thread target and appends the
literal argument vector `codex resume <thread-uuid>` to a terminal prefix.
No command shell is involved, and the thread ID cannot supply options or code.

By default the first available terminal is selected in this order:

| Executable | Argument prefix |
| --- | --- |
| `x-terminal-emulator` | `-e` |
| `kitty` | `-e` |
| `foot` | `-e` |
| `alacritty` | `-e` |
| `konsole` | `-e` |
| `wezterm` | `start --` |
| `gnome-terminal` | `--` |

Choose another terminal or supply its required flags explicitly:

```sh
python3 -m codex_status --terminal 'foot -e'
python3 -m codex_status --terminal 'wezterm start --'
```

The quoted setting is parsed into arguments, without variable expansion,
command substitution, globbing, or pipelines. Include the terminal's execute
flag. An explicitly configured executable that is absent produces an action
failure; it does not silently choose another terminal. Missing terminals do not
prevent monitoring or dashboard shortcuts from working.

## Monitor-only mode

```sh
python3 -m codex_status --disable-actions
```

This disables all terminal and browser launches, including direct socket action
requests. Visibility changes and quota refresh remain available. The default
action-enabled mode still never launches anything merely because an agent
appears or a popup opens.

Usage and Billing buttons can only open their two fixed official API Platform
dashboard URLs through `xdg-open`. They do not authenticate, query balances,
buy credits, save payment details, or change billing settings. API Platform
charges and Codex subscription quota are separate systems.

## Application lifetime

When `systemd-run` is available, explicit opens use independent transient user
services. Restarting the bridge leaves the opened terminal or browser alive.
The launcher receives `CODEX_HOME`; application output is discarded and is not
written into bridge logs. A failure reported by `systemd-run` is not retried,
because retrying could open an application twice. If the executable exists but
its user manager is unavailable, fix the desktop user service environment or
remove that unavailable launcher from the bridge's `PATH`.

Without `systemd-run`, the bridge launches a detached process with a new session
and null standard input/output/error. A daemon reaper thread collects exited
children without blocking the bridge's event loop or shutdown. The graphical
environment is inherited and `CODEX_HOME` is set explicitly. In either mode,
starting an application is allowed only in response to an explicit Open action.
