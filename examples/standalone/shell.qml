import Quickshell
import "../../qml" as Codex

// Run independently: qs -p examples/standalone
ShellRoot {
    Codex.CodexStatus {
        ipcTarget: "codex-status"
        opened: true
    }
}
