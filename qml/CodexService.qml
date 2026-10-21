pragma ComponentBehavior: Bound
import QtQuick
import Quickshell
import Quickshell.Io
import "StatusFormat.js" as Format
import "ThemePalette.js" as Palette

// Shared local transport and palette. Instantiate one controller per UI instance.
Scope {
    id: root
    // A partial theme is optional. Explicit property assignments override these defaults.
    property var theme: null
    property string ipcTarget: "codex-status"
    property bool ipcEnabled: true
    property var dashboard: null
    property var preferredScreen: null
    property string runtimeDirectory: Quickshell.env("XDG_RUNTIME_DIR")
        ? Quickshell.env("XDG_RUNTIME_DIR") + "/codex-quickshell" : ""
    property string socketPath: runtimeDirectory ? runtimeDirectory + "/status.sock" : ""
    property bool transportEnabled: true
    property bool reducedMotion: false
    property bool opened: false
    property var currentScreen: Quickshell.screens.length ? Quickshell.screens[0] : null
    property var snapshot: null
    property bool transportConnected: false
    property string transportMessage: "Connecting to the local status service…"
    property string actionMessage: ""
    property bool actionSucceeded: true
    property double now: Date.now()
    property double lastSnapshotAt: 0
    property int reconnectDelay: 1000
    readonly property bool heartbeatHealthy: transportConnected && lastSnapshotAt > 0
        && now - lastSnapshotAt <= 15000
    readonly property bool online: heartbeatHealthy && snapshot !== null
        && snapshot.connection.state === "connected"
    readonly property var usage: {
        if (!snapshot) return {state: "unavailable", observedAt: null, plan: null, buckets: []};
        var value = snapshot.usage;
        if (online || value.state !== "fresh") return value;
        return {state: "stale", observedAt: value.observedAt, plan: value.plan, buckets: value.buckets};
    }
    readonly property var agents: {
        if (!snapshot) return {state: "unavailable", observedAt: null, activeCount: null, items: []};
        return Format.agentSnapshot(snapshot.agents, online);
    }
    readonly property bool usageFresh: online && usage.state === "fresh"
    readonly property bool agentsFresh: online && agents.state === "fresh"
    property color background: themeColor("background", "bgPanelStrong", "#111a22")
    property color pillBackground: themeColor("pillBackground", "bgPanel", "#cc111a22")
    property color foreground: themeColor("foreground", "textMain", "#e6edf3")
    property color secondary: themeColor("secondary", "textSecondary",
        Qt.rgba(foreground.r, foreground.g, foreground.b, 0.68))
    property color accent: themeColor("accent", "accentCyan", "#9dc4ef")
    property color warning: themeColor("warning", "accentWarn", "#efc58b")
    property color danger: themeColor("danger", "accentPink", "#f3a5b1")
    property color borderColor: themeColor("borderColor", "borderSoft", "#34424f")
    property color cardColor: themeColor("cardColor", "cardBackground",
        Qt.rgba(foreground.r, foreground.g, foreground.b, 0.035))
    property string fontFamily: themeValue("fontFamily", "font", "sans-serif")

    function themeValue(name, legacyName, fallback) {
        return Palette.value(theme, name, legacyName, fallback);
    }
    function themeColor(name, legacyName, fallback) {
        return Palette.color(theme, name, legacyName, fallback);
    }
    function chooseScreen(preferred) {
        if (preferred && Quickshell.screens.indexOf(preferred) >= 0) {
            currentScreen = preferred;
            return;
        }
        if (preferredScreen && Quickshell.screens.indexOf(preferredScreen) >= 0) {
            currentScreen = preferredScreen;
            return;
        }
        if (Quickshell.screens.indexOf(currentScreen) >= 0) return;
        currentScreen = Quickshell.screens.length ? Quickshell.screens[0] : null;
    }
    function openForScreen(screen) {
        chooseScreen(screen);
        opened = true;
        Qt.callLater(function() { if (root.dashboard) root.dashboard.forceActiveFocus(); });
    }
    function toggleForScreen(screen) {
        if (opened && (!screen || screen === currentScreen)) opened = false;
        else openForScreen(screen);
    }
    function send(message) {
        if (!transport.connected) {
            actionSucceeded = false;
            actionMessage = "The local status service is disconnected.";
            return;
        }
        transport.write(JSON.stringify(message) + "\n");
        transport.flush();
    }
    function request(message) {
        actionMessage = "";
        send(message);
    }
    function applyMessage(message) {
        if (message && message.type === "snapshot") {
            if (!Format.validSnapshot(message)) {
                transportMessage = "The local service returned an unsupported status format.";
                transportConnected = false;
                transport.connected = false;
                return;
            }
            snapshot = message;
            transportMessage = Format.text(message.connection.message, "", 300);
            transportConnected = true;
            now = Date.now();
            lastSnapshotAt = now;
        } else if (message && message.type === "action_result") {
            actionSucceeded = message.ok === true;
            actionMessage = Format.text(message.message,
                actionSucceeded ? "Done." : "The action could not be completed.", 300);
        }
    }
    function disconnected(message) {
        transportConnected = false;
        transportMessage = message;
        if (transportEnabled) reconnect.restart();
    }
    onOpenedChanged: {
        if (!opened && dashboard) dashboard.reset();
        now = Date.now();
        actionMessage = "";
        if (transport.connected) send({type: "visibility", open: opened});
    }
    onTransportEnabledChanged: {
        if (transportEnabled) reconnect.restart();
        else { reconnect.stop(); transport.connected = false; }
    }
    onSocketPathChanged: {
        if (transportEnabled) { transport.connected = false; reconnect.restart(); }
    }
    Component.onCompleted: if (transportEnabled && socketPath) transport.connected = true

    Connections {
        target: Quickshell
        function onScreensChanged() {
            if (Quickshell.screens.indexOf(root.currentScreen) < 0) root.chooseScreen(null);
            if (!root.currentScreen) root.opened = false;
        }
    }
    IpcHandler {
        target: root.ipcTarget
        enabled: root.ipcEnabled && root.ipcTarget.length > 0
        function uiVersion(): string { return "0.5.0"; }
        function layoutState(): string { return JSON.stringify(root.dashboard ? root.dashboard.layoutState() : {opened: root.opened}); }
        function open(): void { root.openForScreen(null); }
        function close(): void { root.opened = false; }
        function toggle(): void { root.toggleForScreen(null); }
    }
    Socket {
        id: transport
        path: root.socketPath
        parser: SplitParser {
            onRead: data => {
                if (data.length > 524288) {
                    root.disconnected("The local service sent an oversized status message.");
                    transport.connected = false;
                    return;
                }
                try { root.applyMessage(JSON.parse(data)); }
                catch (_) {
                    root.disconnected("The local service sent an unreadable status message.");
                    transport.connected = false;
                }
            }
        }
        onConnectionStateChanged: {
            if (connected) {
                reconnect.stop();
                root.reconnectDelay = 1000;
                root.transportConnected = true;
                root.lastSnapshotAt = 0;
                root.transportMessage = "Waiting for a status update…";
                root.send({type: "visibility", open: root.opened});
            } else root.disconnected("The local status service is disconnected. Reconnecting…");
        }
        onError: root.disconnected("The local status service is unavailable. Reconnecting…")
    }
    Timer {
        id: reconnect
        interval: root.reconnectDelay
        onTriggered: {
            if (!root.transportEnabled || !root.socketPath) return;
            transport.connected = true;
            root.reconnectDelay = Math.min(30000, root.reconnectDelay * 2);
        }
    }
    Timer {
        interval: 1000
        running: root.opened || root.transportConnected
        repeat: true
        onTriggered: root.now = Date.now()
    }

}
