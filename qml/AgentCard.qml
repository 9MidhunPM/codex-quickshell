pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Layouts
import "StatusFormat.js" as Format

Rectangle {
    id: root
    required property var controller
    required property var agent
    readonly property color stateColor: agent.state === "error" ? controller.danger
        : agent.state === "waiting_approval" || agent.state === "waiting_input" ? controller.warning
        : agent.state === "working" ? controller.accent : controller.secondary
    readonly property bool canOpen: controller.agentsFresh && agent.openTargetId.length > 0
    implicitHeight: content.implicitHeight + 24
    radius: 12
    color: controller.cardColor
    border.width: 1
    border.color: controller.borderColor

    ColumnLayout {
        id: content
        anchors { left: parent.left; right: parent.right; top: parent.top; margins: 12 }
        spacing: 7
        RowLayout {
            Layout.fillWidth: true
            Layout.alignment: Qt.AlignTop
            spacing: 10
            Text {
                Layout.fillWidth: true
                Layout.minimumWidth: 50
                text: Format.text(root.agent.title, "Codex session", 160)
                textFormat: Text.PlainText
                color: root.controller.foreground
                font.family: root.controller.fontFamily
                font.pixelSize: 14
                font.weight: Font.DemiBold
                wrapMode: Text.Wrap
            }
            Rectangle {
                Layout.alignment: Qt.AlignTop
                implicitWidth: Math.min(stateLabel.implicitWidth + 16, Math.max(76, (root.width - 24) * 0.43))
                implicitHeight: Math.max(25, stateLabel.implicitHeight + 8)
                radius: 7
                color: Qt.rgba(root.stateColor.r, root.stateColor.g, root.stateColor.b, 0.10)
                border.width: 1
                border.color: Qt.rgba(root.stateColor.r, root.stateColor.g, root.stateColor.b, 0.28)
                Text {
                    id: stateLabel
                    anchors { fill: parent; leftMargin: 8; rightMargin: 8; topMargin: 4; bottomMargin: 4 }
                    text: Format.stateLabel(root.agent.state)
                    textFormat: Text.PlainText
                    wrapMode: Text.Wrap
                    horizontalAlignment: Text.AlignHCenter
                    verticalAlignment: Text.AlignVCenter
                    color: root.stateColor
                    font.family: root.controller.fontFamily
                    font.pixelSize: 10
                    font.weight: Font.Medium
                }
            }
        }
        Text {
            objectName: "configuredModel-" + root.agent.agentId
            Layout.fillWidth: true
            text: "Configured model: " + Format.text(root.agent.configuredModel, "Unavailable", 120)
            textFormat: Text.PlainText
            wrapMode: Text.WrapAnywhere
            color: root.controller.secondary
            font.family: root.controller.fontFamily
            font.pixelSize: 11
            lineHeight: 1.15
        }
        ColumnLayout {
            Layout.fillWidth: true
            spacing: 5
            Text {
                objectName: "agentNickname-" + root.agent.agentId
                Layout.fillWidth: true
                text: "Nickname: " + Format.text(root.agent.nickname, "Unavailable", 80)
                textFormat: Text.PlainText
                wrapMode: Text.WrapAnywhere
                color: root.controller.secondary
                font.family: root.controller.fontFamily
                font.pixelSize: 11
            }
            Text {
                objectName: "agentWorkspace-" + root.agent.agentId
                Layout.fillWidth: true
                text: "Workspace: " + Format.text(root.agent.workspace, "Unavailable", 120)
                textFormat: Text.PlainText
                wrapMode: Text.WrapAnywhere
                color: root.controller.secondary
                font.family: root.controller.fontFamily
                font.pixelSize: 11
            }
        }
        RowLayout {
            visible: root.canOpen
            Layout.fillWidth: true
            spacing: 7
            Item { Layout.fillWidth: true }
            StatusButton {
                objectName: "agentOpen-" + root.agent.agentId
                text: root.agent.openLabel || "Open"
                Accessible.name: text + " · " + root.agent.title
                visible: root.canOpen
                enabled: root.canOpen
                foreground: root.controller.foreground; accent: root.controller.accent
                surface: root.controller.background; borderColor: root.controller.borderColor
                fontFamily: root.controller.fontFamily; quiet: true
                onClicked: root.controller.request({type: "open_session", threadId: root.agent.openTargetId})
            }
        }
    }
}
