pragma ComponentBehavior: Bound
import QtQuick
import Quickshell

// Standard OS toplevel: no compositor-specific imports or focus protocols.
CodexService {
    id: root
    property string windowTitle: "Codex status"
    property int screenMargin: 36
    dashboard: dashboardView

    FloatingWindow {
        id: window
        title: root.windowTitle
        screen: root.currentScreen
        visible: root.opened && root.currentScreen !== null
        color: root.background
        minimumSize: Qt.size(300, 280)
        implicitWidth: Math.max(300, Math.min(dashboardView.preferredPopupWidth,
            (root.currentScreen ? root.currentScreen.width : 1024) - root.screenMargin))
        implicitHeight: Math.max(280, Math.min(dashboardView.preferredHeight,
            (root.currentScreen ? root.currentScreen.height : 800) - root.screenMargin))
        onClosed: root.opened = false

        CodexDashboard {
            id: dashboardView
            anchors.fill: parent
            controller: root
            hostWindowVisible: window.visible
            onCloseRequested: root.opened = false
        }
    }
}
