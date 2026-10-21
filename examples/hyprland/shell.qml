import Quickshell
import "CodexStatusModule/adapters/hyprland" as CodexHyprland

// Optional overlay. Requires Hyprland; the portable module does not import it.
ShellRoot {
    CodexHyprland.CodexOverlay {
        ipcTarget: "codex-status-hyprland"
        layerNamespace: "codex-status-hyprland"
        opened: true
        topMargin: 58
        rightMargin: 18
    }
}
