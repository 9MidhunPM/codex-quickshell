pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "StatusFormat.js" as Format

// THESIS: Combine the selected tabbed focus and wide overview concepts.
// OWN-WORLD: Native theme, restrained accent, readable task cards, measured spacing.
// STORY: Scan a compact home, then see every detail in Usage or Agents.
// FIRST VIEWPORT: Pinned shortcuts and tabs above compact metrics and activity.
// FORM: Compact summary at home; full-width, fully revealed detail tabs.
Item {
    id: root
    required property var controller
    property bool hostWindowVisible: true
    readonly property bool wideLayout: width >= 680
    readonly property bool toolbarWrapped: width < 540
    readonly property string selectedView: ["overview", "usage", "agents"][tabs.currentIndex] || "overview"
    readonly property bool homeView: selectedView === "overview"
    readonly property int preferredPopupWidth: homeView ? 560 : 860
    readonly property real preferredHeight: homeView
        ? Math.min(width < 400 ? 440 : 400, Math.max(280,
            overviewPanel.preferredHeight + (width < 400 ? 28 : 32)
            + header.implicitHeight + tabs.implicitHeight + footer.implicitHeight + 30))
        : wideLayout ? 620 : 740
    readonly property string footerStatus: !controller.transportConnected ? controller.transportMessage
        : !controller.heartbeatHealthy ? "No recent update · last known data"
        : !controller.online ? (controller.transportMessage || "Codex disconnected")
        : !controller.usageFresh ? "Usage " + controller.usage.state + " · " + Format.observed(controller.usage.observedAt, controller.now)
        : !controller.agentsFresh ? "Agent activity unavailable · " + Format.observed(controller.agents.observedAt, controller.now)
        : Format.observed(controller.usage.observedAt, controller.now)
    implicitWidth: preferredPopupWidth
    implicitHeight: preferredHeight
    signal closeRequested()

    function selectView(view) {
        var index = ["overview", "usage", "agents"].indexOf(view);
        if (index >= 0) tabs.currentIndex = index;
    }
    function reset() {
        selectView("overview");
        agentPanel.reset();
        usagePanel.resetScroll();
        overviewPanel.resetScroll();
    }
    function pointFor(item) {
        var point = item.mapToItem(root, item.width / 2, item.height / 2);
        return {x: point.x, y: point.y, visible: item.visible};
    }
    function layoutState() {
        return {
            version: "0.5.0", view: selectedView, wideLayout: wideLayout,
            width: width, height: height, desiredHeight: preferredHeight,
            headerHeight: header.height, bodyViewportHeight: panes.height,
            footerHeight: footer.height, toolbarWrapped: toolbarWrapped,
            visibleAgentCount: homeView ? overviewPanel.previewAgents.length
                : selectedView === "agents" ? agentPanel.visibleAgentCount : 0,
            credits: controller.usage.buckets.map(function(bucket) { return Format.credits(bucket.credits); }),
            controls: {overview: pointFor(overviewTab), usage: pointFor(usageTab),
                agents: pointFor(agentsTab), refresh: pointFor(refreshButton), close: pointFor(closeButton),
                apiUsage: pointFor(toolbarWrapped ? wrappedUsage : apiUsage),
                billing: pointFor(toolbarWrapped ? wrappedBilling : apiBilling)}
        };
    }
    Shortcut {
        sequence: "Escape"
        context: Qt.WindowShortcut
        enabled: root.visible && root.hostWindowVisible
        onActivated: root.closeRequested()
    }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: root.width < 400 ? 14 : root.homeView ? 16 : 20
        spacing: root.homeView ? 10 : 14

        ColumnLayout {
            id: header
            Layout.fillWidth: true
            spacing: 12
            RowLayout {
                Layout.fillWidth: true
                spacing: 10
                Rectangle {
                    implicitWidth: root.homeView ? 32 : 38; implicitHeight: implicitWidth; radius: 11
                    color: Qt.rgba(root.controller.accent.r, root.controller.accent.g, root.controller.accent.b, 0.11)
                    Text {
                        anchors.centerIn: parent
                        text: ">_"
                        textFormat: Text.PlainText
                        font.family: root.controller.fontFamily
                        font.pixelSize: 17
                        font.bold: true
                        color: root.controller.accent
                    }
                }
                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: 2
                    Text {
                        Layout.fillWidth: true
                        text: "Codex"
                        textFormat: Text.PlainText
                        color: root.controller.foreground
                        font.family: root.controller.fontFamily
                        font.pixelSize: root.homeView ? 20 : 22
                        font.weight: Font.DemiBold
                        elide: Text.ElideRight
                    }
                    Text {
                        Layout.fillWidth: true
                        visible: !root.homeView
                        text: "Usage & local agents"
                        textFormat: Text.PlainText
                        color: root.controller.secondary
                        font.family: root.controller.fontFamily
                        font.pixelSize: 10
                        elide: Text.ElideRight
                    }
                }
                RowLayout {
                    visible: !root.toolbarWrapped && !root.homeView
                    spacing: 6
                    Rectangle {
                        implicitWidth: 6; implicitHeight: 6; radius: 3
                        color: root.controller.online ? root.controller.accent : root.controller.warning
                    }
                    Text {
                        text: root.controller.online ? "Connected" : "Offline"
                        textFormat: Text.PlainText
                        color: root.controller.secondary
                        font.family: root.controller.fontFamily
                        font.pixelSize: 10
                    }
                }
                DashboardAction {
                    controller: root.controller
                    id: apiUsage
                    objectName: "headerUsage"
                    visible: !root.toolbarWrapped
                    text: "API usage ↗"
                    Accessible.name: "Open API usage dashboard"
                    enabled: root.controller.transportConnected
                    onClicked: root.controller.request({type: "open_dashboard", target: "usage"})
                }
                DashboardAction {
                    controller: root.controller
                    id: apiBilling
                    objectName: "headerBilling"
                    visible: !root.toolbarWrapped
                    text: "Billing ↗"
                    Accessible.name: "Open API billing dashboard"
                    enabled: root.controller.transportConnected
                    onClicked: root.controller.request({type: "open_dashboard", target: "billing"})
                }
                DashboardAction {
                    controller: root.controller
                    id: refreshButton
                    objectName: "refreshDashboard"
                    text: "↻"
                    Accessible.name: "Refresh Codex status"
                    enabled: root.controller.transportConnected
                    onClicked: root.controller.request({type: "refresh"})
                }
                DashboardAction {
                    controller: root.controller
                    id: closeButton
                    objectName: "closeDashboard"
                    text: "×"
                    Accessible.name: "Close Codex status"
                    onClicked: root.closeRequested()
                }
            }
            RowLayout {
                visible: root.toolbarWrapped
                Layout.fillWidth: true
                spacing: 8
                DashboardAction {
                    controller: root.controller
                    id: wrappedUsage
                    objectName: "wrappedUsage"
                    Layout.fillWidth: true
                    text: "API usage ↗"
                    Accessible.name: "Open API usage dashboard"
                    enabled: root.controller.transportConnected
                    onClicked: root.controller.request({type: "open_dashboard", target: "usage"})
                }
                DashboardAction {
                    controller: root.controller
                    id: wrappedBilling
                    objectName: "wrappedBilling"
                    Layout.fillWidth: true
                    text: "Billing ↗"
                    Accessible.name: "Open API billing dashboard"
                    enabled: root.controller.transportConnected
                    onClicked: root.controller.request({type: "open_dashboard", target: "billing"})
                }
            }
        }

        TabBar {
            id: tabs
            objectName: "dashboardTabs"
            Layout.fillWidth: true
            implicitHeight: 42
            padding: 3
            spacing: 3
            background: Rectangle {
                radius: 12
                color: root.controller.cardColor
                border.width: 1
                border.color: root.controller.borderColor
            }
            DashboardTab { controller: root.controller; id: overviewTab; objectName: "viewOverview"; text: "Overview" }
            DashboardTab { controller: root.controller; id: usageTab; objectName: "viewUsage"; text: "Usage" }
            DashboardTab { controller: root.controller; id: agentsTab; objectName: "viewAgents"; text: "Agents" }
        }

        Item {
            id: panes
            objectName: "dashboardPanes"
            Layout.fillWidth: true
            Layout.fillHeight: true
            Layout.minimumHeight: 0
            OverviewPanel {
                id: overviewPanel
                objectName: "overviewPanel"
                anchors.fill: parent
                controller: root.controller
                visible: root.homeView
            }
            UsagePanel {
                id: usagePanel
                objectName: "usagePanel"
                anchors.fill: parent
                controller: root.controller
                visible: root.selectedView === "usage"
            }
            AgentsPanel {
                id: agentPanel
                objectName: "agentsPanel"
                anchors.fill: parent
                controller: root.controller
                visible: root.selectedView === "agents"
            }
        }

        RowLayout {
            id: footer
            Layout.fillWidth: true
            spacing: 12
            Text {
                objectName: "dashboardFooter"
                Layout.fillWidth: true
                text: root.footerStatus + (root.controller.actionMessage ? " · " + root.controller.actionMessage : "")
                textFormat: Text.PlainText
                color: root.controller.secondary
                font.family: root.controller.fontFamily
                font.pixelSize: 10
                wrapMode: Text.Wrap
                maximumLineCount: 2
                elide: Text.ElideRight
            }
            Text {
                visible: root.width >= 600
                text: "Local Codex daemon"
                textFormat: Text.PlainText
                color: root.controller.secondary
                font.family: root.controller.fontFamily
                font.pixelSize: 10
            }
        }
    }
}
