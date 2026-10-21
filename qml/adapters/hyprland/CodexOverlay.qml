pragma ComponentBehavior: Bound
import QtQuick
import Quickshell
import Quickshell.Hyprland
import Quickshell.Wayland
import "../.." as Codex

// Opt-in adapter. Requires Hyprland plus its focus-grab protocol.
Codex.CodexService {
    id: root
    property int topMargin: 58
    property int rightMargin: 18
    property string layerNamespace: "codex-status"
    dashboard: dashboardView
    preferredScreen: {
        var focused = Hyprland.focusedMonitor;
        for (var i = 0; focused && i < Quickshell.screens.length; i++) {
            var candidate = Quickshell.screens[i];
            var monitor = Hyprland.monitorFor(candidate);
            if (monitor && monitor.name === focused.name) return candidate;
        }
        return null;
    }
    PanelWindow {
        id: panel
        screen: root.currentScreen
        visible: root.opened && root.currentScreen !== null
        color: "transparent"
        anchors { top: true; right: true }
        margins { top: root.topMargin; right: root.rightMargin }
        implicitWidth: Math.max(1, Math.min(dashboardView.preferredPopupWidth,
            (root.currentScreen ? root.currentScreen.width : 1024) - 36))
        implicitHeight: Math.max(1, Math.min(
            (root.currentScreen ? root.currentScreen.height : 800) - 90,
            dashboardView.preferredHeight))
        exclusionMode: ExclusionMode.Ignore
        WlrLayershell.layer: WlrLayer.Overlay
        WlrLayershell.namespace: root.layerNamespace
        WlrLayershell.keyboardFocus: WlrKeyboardFocus.OnDemand

        HyprlandFocusGrab {
            windows: [panel]
            active: panel.visible
            onCleared: root.opened = false
        }
        Rectangle {
            id: surface
            anchors.fill: parent
            radius: 24
            color: root.background
            border.width: 1
            border.color: root.borderColor
            clip: true
            focus: true
            Keys.onEscapePressed: root.opened = false

            Codex.CodexDashboard {
                id: dashboardView
                anchors.fill: parent
                controller: root
                hostWindowVisible: panel.visible
                onCloseRequested: root.opened = false
            }
        }
    }
}
