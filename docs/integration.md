# Integration

Create one `CodexStatus` controller per UI instance, then place any number of
`CodexPill` controls in your own monitor bars. Each pill accepts `screen` and
`availableWidth`; neither its position nor the rest of the row is owned by this
module. Existing files are edited only by you.

The installer copies QML into `modules/CodexStatusModule` beneath the Quickshell
config root. The relative import in the README assumes your `shell.qml` is at
that root. Adjust the import for nested shells. For source examples, run them
from the checkout as documented beside each example; preserve the root import
boundary required by Quickshell's file scanner.

## Theme and behavior

`theme` is optional. It can be a partial JavaScript object or a QML theme object.
Missing/null/invalid values use defaults. Direct controller property assignments
override theme bindings:

```qml
Codex.CodexStatus {
    id: codex
    ipcTarget: "my-codex-status"
    accent: "#b7d7aa"
    background: "#151a19"
    fontFamily: "sans-serif"
    reducedMotion: true
}
```

Available tokens: `background`, `pillBackground`, `foreground`, `secondary`,
`accent`, `warning`, `danger`, `borderColor`, `cardColor`, `fontFamily`.
The optional legacy aliases are defined in `CodexService.qml`; a host is not
required to provide any theme object.

`preferredScreen` sets the default display. Clicking a pill opens on its screen;
IPC opens on the current/preferred available screen. If a monitor disappears,
the controller selects another available display. The host owns the bar's
exclusive zone, layout constraints, scaling rules, and monitor creation.

## Bring your own window

Use `CodexService` instead of `CodexStatus` when your shell already owns a popup:
set the service's `dashboard` to your `CodexDashboard`, bind the dashboard's
`controller` to the service and `hostWindowVisible` to the actual host visibility,
then handle `closeRequested` by setting `service.opened = false`. Also bind the
host's visibility to `service.opened`. See `examples/embedded/shell.qml`.

The optional `qml/adapters/hyprland/CodexOverlay.qml` adds a layer window and
Hyprland focus grab. Only import that adapter on Hyprland. Its top/right margins
and layer namespace are configurable; the default module never loads it.
The additive installer copies the portable module only. Use the source adapter
from the checkout, or copy its directory beside your manually maintained module.

## IPC and transport

The default target is `codex-status`, with `open`, `close`, `toggle`, `uiVersion`
and `layoutState` methods. Always select your intended configuration with `-p`:

```sh
qs ipc -p /path/to/your/config call my-codex-status toggle
```

Set `ipcEnabled: false` if your host supplies its own IPC. Give multiple
controllers in the same instance distinct targets. Prefer one controller so
there is one status transport and dashboard state.

The frontend defaults to `$XDG_RUNTIME_DIR/codex-quickshell/status.sock`.
Override `socketPath` when running a bridge with a custom `--socket` location.
The graphical session must set `XDG_RUNTIME_DIR`; if it is absent, the backend
uses `/run/user/<uid>` but the frontend requires an explicit `socketPath`.
Set `transportEnabled: false` only for an explicit synthetic preview or a host
that feeds validated snapshots itself. A disconnected backend never prevents
the UI loading; it displays a reconnecting state.

## Navigation

Home fits the essential allowance/activity summary and compact API shortcuts.
Usage and Agents show their complete details directly and scroll as necessary.
Tab/Shift+Tab moves focus; buttons support Enter/Space; Escape closes the window.
Closing returns the next open to Home. Use the explicit close control for the
standard window; the Hyprland adapter also supports outside-click dismissal.
