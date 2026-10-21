import QtQuick
import Quickshell
import "."

// Explicitly launched preview. Never imported by the installed shell.
Scope {
    id: preview
    property string state: Quickshell.env("CODEX_QUICKSHELL_PREVIEW_STATE") || "fresh"
    function fixture() {
        var now = Math.floor(Date.now() / 1000);
        return {
            type: "snapshot", version: 1,
            connection: {state: "connected", message: ""},
            usage: {state: state === "stale" ? "stale" : "fresh", observedAt: now, plan: "Preview",
                buckets: [{id: "codex", name: "Codex", windows: [
                    {label: "5-hour window", remainingPercent: 82, resetsAt: now + 8000, durationMinutes: 300},
                    {label: "Weekly", remainingPercent: 64, resetsAt: now + 240000, durationMinutes: 10080}
                ], credits: {balance: "20.00", hasCredits: true, unlimited: false}}]},
            agents: {state: state === "partial" ? "unavailable" : "fresh", observedAt: now,
                activeCount: state === "partial" ? null : 1, items: [
                    {id: "preview-root", parentId: null, title: "Build the desktop module", nickname: "Main agent",
                        workspace: "CodexQuickshell", model: "Preview model", state: "working",
                        openTargetId: null, openLabel: null, depth: 0},
                    {id: "preview-child", parentId: "preview-root", title: "Review status data", nickname: "Review agent",
                        workspace: "CodexQuickshell", model: "Preview model", state: "waiting_approval",
                        openTargetId: null, openLabel: null, depth: 1}
                ]}
        };
    }
    CodexStatus {
        id: status
        transportEnabled: false
        Component.onCompleted: {
            if (preview.state !== "offline") applyMessage(preview.fixture());
            openForScreen(null);
        }
    }
    Timer {
        interval: 5000
        running: preview.state !== "offline"
        repeat: true
        onTriggered: status.applyMessage(preview.fixture())
    }
}
