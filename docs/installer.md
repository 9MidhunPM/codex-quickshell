# Additive installation

The installer copies the module into its own directory. It never reads, patches,
or replaces an existing `shell.qml`, bar, theme, compositor configuration, or key
binding. You choose how your shell presents the module. A separate named
configuration is also available for testing alongside your current shell.

Run these commands from the checkout root. Review a plan first:

```sh
python3 scripts/install.py
python3 scripts/install.py --standalone
```

Both commands are dry runs. They show the new paths without creating files,
contacting Codex, or controlling systemd. Installation does not require the Codex
daemon to be online. Creating a service requires the Codex CLI to be on `PATH`,
or an explicit absolute `--codex-bin` path.

## Module and optional service

```sh
python3 scripts/install.py --install
```

Default destinations follow `XDG_CONFIG_HOME` and `XDG_STATE_HOME`:

| Content | Default destination |
| --- | --- |
| Copied QML module | `~/.config/quickshell/modules/CodexStatusModule/` |
| Private ownership manifest | `~/.local/state/codex-quickshell/install/manifest.json` |
| User service unit | `~/.config/systemd/user/codex-quickshell.service` |
| Optional separate shell | `~/.config/quickshell/codex-status/shell.qml` |

The service is written but is **not enabled or started** by default. To opt into
activation during installation, include `--activate` in the initial command:

```sh
python3 scripts/install.py --install --activate
```

Alternatively, enable the installed service yourself later:

```sh
systemctl --user daemon-reload
systemctl --user enable --now codex-quickshell.service
```

The service runs the backend from the checkout with the Python executable used
for installation. Keep that checkout and Python executable at their installed
locations while using this service. The copied QML does not depend on the
checkout location. Uninstall and reinstall to move the backend or change options.

Module-only installations never contact systemd or require a Codex executable:

```sh
python3 scripts/install.py --install --no-service
```

You can run the backend yourself or use an existing instance. See the runtime
guide for the private socket and one-backend-per-user requirements.

## Separate shell for any existing setup

```sh
python3 scripts/install.py --install --standalone
qs -p "${XDG_CONFIG_HOME:-$HOME/.config}/quickshell/codex-status"
```

From another terminal, open its popup through its own instance:

```sh
qs ipc -p "${XDG_CONFIG_HOME:-$HOME/.config}/quickshell/codex-status" call codex-status open
```

The wrapper instantiates one controller and creates no permanent panel. You can
bind that command in your compositor or use the module's pill from your own
configuration. Existing bars and shell instances are untouched. Do not import
another controller into the same shell if you already instantiated one.

Use the explicit path above: some Quickshell versions stop discovering named
subconfigurations when a default `quickshell/shell.qml` exists.

The generated wrapper imports the installed module using a percent-encoded file
URL. Quotes, spaces, Unicode, and URL-sensitive characters in destination paths
are treated as path data. No directory name is evaluated as QML code.

## Terminal and launch policy

No particular terminal is hardcoded by the installer. The backend chooses from
supported terminals, or you can give it a terminal command prefix:

```sh
python3 scripts/install.py --install --terminal 'foot -e'
```

The string is passed as one service argument, parsed into arguments by the
backend, and never executed through a shell. Use `--disable-actions` to disable
external launches. These options apply to a service installation and cannot be
combined with `--no-service`.

Installation performs no account lookup, browser login, model generation,
payment, credit purchase, or billing modification. Dashboard navigation remains
an explicit action inside the installed module.

## Safe ownership and uninstall

```sh
python3 scripts/install.py --uninstall --dry-run
python3 scripts/install.py --uninstall
```

For a module-only installation, repeating `--no-service` is optional when
uninstalling. If the manifest records a service, `--no-service` is refused during
uninstall so a running service is not silently left behind.

The installer refuses existing module directories, standalone configurations,
or units without a matching private ownership manifest. This includes an
unrelated service with the same name. It never overwrites those files or tries
to guess who created them.

Opt-in activation also refuses an existing global or transient unit with the
same name. An unavailable user manager prevents activation before files change.

Every created file has a SHA-256 entry in the manifest. Uninstall verifies all
remaining tracked files before changing a service or deleting a file. If a
tracked file was edited, it stops and preserves the files. Move your edits to a
safe place, restore the installed version, then retry. Missing tracked files are
safe to forget, which allows interrupted uninstalls to resume. Untracked files
are preserved, and directories are removed only when empty.

Service control also checks the user manager's loaded unit path against the
hash-verified installed file. It never stops a global or transient unit merely
because it has the same name. If the installed unit was deleted while a
definition is still loaded, uninstall stops for manual resolution. If both the
file and manager definition are absent, it removes the remaining owned files
without controlling a service. An unavailable manager preserves the installation.

Because installation never replaces existing user files, it does not create
copies of your personal configuration as backups. The private manifest records
new paths, options, and hashes only. Created files are mode `0600`, and new
directories are mode `0700`.

New files are published atomically without replacing existing paths. Failed
installations roll back their own new files. If a file changes during rollback,
the interrupted-install manifest is retained so `--uninstall` can recover after
you resolve the change. An interrupted install is never automatically resumed
over files that might now belong to you.

Installations are idempotent when all files, source bytes, and options match.
For a new release or different options, uninstall the current installation and
install the new one. Repeat the same installation options when checking
idempotence, including `--standalone`, `--terminal`, or `--activate` if used.

Service checkout paths may contain ordinary spaces. A checkout directory whose
name ends in whitespace or a backslash is refused because systemd cannot safely
represent that path in the `WorkingDirectory` setting. Rename that checkout or
use a module-only installation and run the backend yourself.

## Custom roots and fixtures

All path overrides must be absolute. `--module-dir` must be a child of
`--config-root`; it cannot overlap the separate `codex-status` shell. Config,
state, and unit roots must be separate directory trees. Symlink ancestors and
unsafe shared writable directories of used destinations are refused. Module-only
installation does not inspect or modify the unrelated user-unit directory.
Every existing ancestor must be owned by root or your user; a sticky bit does
not make another user's directory safe. Root-owned sticky `/tmp` is supported.
If your dotfiles use symlinks,
use explicit real directory paths or import the source module manually instead.

```sh
python3 scripts/install.py --install --no-service \
  --config-root /tmp/codex-demo/config \
  --state-root /tmp/codex-demo/state \
  --unit-root /tmp/codex-demo/units \
  --standalone
```

Repeat custom root flags during uninstall. A custom module path is recovered
from the manifest when uninstalling. Custom-root installations never control
the actual systemd user manager, even when generating a fixture unit;
`--activate` is refused with root overrides. No system-wide installation or
privileged command is used.
