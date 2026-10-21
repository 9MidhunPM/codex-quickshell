import QtQuick
import Quickshell
import "CodexStatusModule" as Codex

// Copy the controller and pill into your own root/bar. No file patching required.
// This floating launcher is only an executable demonstration of an existing bar.
ShellRoot {
    Codex.CodexStatus {
        id: codex
        ipcTarget: "codex-status-example"
        // Each color/font can also be assigned directly.
        theme: ({accent: "#a5c9ea", fontFamily: "sans-serif"})
    }
    FloatingWindow {
        id: launcher
        title: "Example Codex launcher"
        implicitWidth: 220
        implicitHeight: 70
        color: "#111a22"
        Codex.CodexPill {
            anchors.centerIn: parent
            controller: codex
            screen: launcher.screen
            // The host supplies the space allocated to the pill's row.
            availableWidth: 200
        }
    }
}
