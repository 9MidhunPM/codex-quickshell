import QtQuick
import Quickshell
import "../../qml" as Codex

// For shells that already provide a popup/window host, use the service directly.
ShellRoot {
    Codex.CodexService {
        id: service
        ipcTarget: "codex-status-embedded"
        dashboard: dashboardView
        opened: true
    }
    FloatingWindow {
        id: host
        title: "Embedded Codex dashboard"
        visible: service.opened
        color: service.background
        implicitWidth: dashboardView.preferredPopupWidth
        implicitHeight: dashboardView.preferredHeight
        onClosed: service.opened = false
        Codex.CodexDashboard {
            id: dashboardView
            anchors.fill: parent
            controller: service
            hostWindowVisible: host.visible
            onCloseRequested: service.opened = false
        }
    }
}
