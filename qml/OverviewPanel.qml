pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "StatusFormat.js" as Format

Item {
    id: root
    required property var controller
    readonly property real preferredHeight: content.implicitHeight
    readonly property var bucket: controller.usage.buckets.length ? controller.usage.buckets[0] : null
    readonly property var weeklyWindow: bucket ? bucket.windows.filter(function(window) {
        return window.durationMinutes === 10080;
    })[0] || null : null
    readonly property var previewAgents: {
        if (!controller.agentsFresh) return [];
        var priority = {waiting_approval: 0, waiting_input: 1, error: 2, working: 3};
        return controller.agents.items.filter(function(agent) {
            return Object.prototype.hasOwnProperty.call(priority, agent.state);
        }).sort(function(a, b) { return priority[a.state] - priority[b.state]; })
            .slice(0, width < 400 ? 2 : 3);
    }
    function resetScroll() {
        var flickable = scroll.contentItem as Flickable;
        if (flickable) flickable.contentY = 0;
    }
    ScrollView {
        id: scroll
        objectName: "overviewScroll"
        anchors.fill: parent
        contentWidth: availableWidth
        clip: true
        ScrollBar.horizontal.policy: ScrollBar.AlwaysOff
        ColumnLayout {
            id: content
            width: scroll.availableWidth
            spacing: 10
            Rectangle {
                Layout.fillWidth: true
                implicitHeight: metrics.implicitHeight + 24
                radius: 12
                color: root.controller.cardColor
                border.width: 1
                border.color: root.controller.borderColor
                ColumnLayout {
                    id: metrics
                    anchors { left: parent.left; right: parent.right; top: parent.top; margins: 12 }
                    spacing: 7
                    RowLayout {
                        Layout.fillWidth: true
                        spacing: 18
                        ColumnLayout {
                            Layout.fillWidth: true
                            Layout.preferredWidth: 1
                            spacing: 3
                            Text {
                                text: "Weekly left"
                                textFormat: Text.PlainText
                                color: root.controller.secondary
                                font.family: root.controller.fontFamily
                                font.pixelSize: 11
                            }
                            Text {
                                objectName: "overviewWeekly"
                                Layout.fillWidth: true
                                text: Format.percent(root.weeklyWindow ? root.weeklyWindow.remainingPercent : null)
                                textFormat: Text.PlainText
                                color: root.controller.foreground
                                font.family: root.controller.fontFamily
                                font.pixelSize: root.weeklyWindow ? 26 : 17
                                font.weight: Font.DemiBold
                                wrapMode: Text.WrapAnywhere
                            }
                        }
                        ColumnLayout {
                            Layout.fillWidth: true
                            Layout.preferredWidth: 1
                            spacing: 3
                            Text {
                                text: "Codex credits"
                                textFormat: Text.PlainText
                                color: root.controller.secondary
                                font.family: root.controller.fontFamily
                                font.pixelSize: 11
                            }
                            Text {
                                objectName: "overviewCredits"
                                Layout.fillWidth: true
                                readonly property string balance: Format.credits(root.bucket ? root.bucket.credits : null)
                                text: balance
                                textFormat: Text.PlainText
                                color: root.controller.foreground
                                font.family: root.controller.fontFamily
                                font.pixelSize: balance.length > 14 ? 13 : 24
                                font.weight: Font.DemiBold
                                wrapMode: Text.WrapAnywhere
                            }
                        }
                    }
                    Rectangle {
                        Layout.fillWidth: true
                        implicitHeight: 4
                        radius: 2
                        color: root.controller.borderColor
                        opacity: root.weeklyWindow ? 1 : 0.45
                        Rectangle {
                            width: parent.width * (root.weeklyWindow ? Format.remaining(root.weeklyWindow) : 0)
                            height: parent.height
                            radius: 2
                            color: root.controller.accent
                            opacity: root.controller.usageFresh ? 1 : 0.45
                        }
                    }
                    Text {
                        Layout.fillWidth: true
                        text: root.weeklyWindow && Format.numeric(root.weeklyWindow.resetsAt)
                            ? "Weekly resets " + Format.countdown(root.weeklyWindow.resetsAt, root.controller.now)
                            : "Weekly reset unavailable"
                        textFormat: Text.PlainText
                        color: root.controller.secondary
                        font.family: root.controller.fontFamily
                        font.pixelSize: 10
                        wrapMode: Text.Wrap
                    }
                }
            }
            Text {
                objectName: "overviewAgentCounts"
                Layout.fillWidth: true
                text: Format.agentCounts(root.controller.agents)
                textFormat: Text.PlainText
                color: root.controller.foreground
                font.family: root.controller.fontFamily
                font.pixelSize: 11
                wrapMode: Text.Wrap
            }
            ColumnLayout {
                Layout.fillWidth: true
                spacing: 4
                Repeater {
                    model: root.previewAgents
                    delegate: RowLayout {
                        id: agent
                        required property var modelData
                        objectName: "overviewAgentRow-" + modelData.id
                        Layout.fillWidth: true
                        Layout.minimumHeight: 24
                        spacing: 8
                        Text {
                            Layout.fillWidth: true
                            text: Format.text(agent.modelData.title, "Codex session", 160)
                            textFormat: Text.PlainText
                            elide: Text.ElideRight
                            color: root.controller.foreground
                            font.family: root.controller.fontFamily
                            font.pixelSize: 11
                        }
                        Text {
                            Layout.maximumWidth: 125
                            text: Format.stateLabel(agent.modelData.state)
                            textFormat: Text.PlainText
                            elide: Text.ElideRight
                            color: agent.modelData.state === "error" ? root.controller.danger
                                : agent.modelData.state === "waiting_input" || agent.modelData.state === "waiting_approval"
                                ? root.controller.warning : root.controller.secondary
                            font.family: root.controller.fontFamily
                            font.pixelSize: 10
                        }
                    }
                }
                Text {
                    visible: !root.previewAgents.length
                    Layout.fillWidth: true
                    text: root.controller.agentsFresh ? "No agents need attention." : "Live agent activity unavailable."
                    textFormat: Text.PlainText
                    color: root.controller.secondary
                    font.family: root.controller.fontFamily
                    font.pixelSize: 11
                    wrapMode: Text.Wrap
                }
            }
        }
    }
}
