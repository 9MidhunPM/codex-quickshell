import QtQuick
import QtQuick.Layouts
import "StatusFormat.js" as Format

Rectangle {
    id: root
    required property var controller
    readonly property var effectiveController: controller || fallbackController
    property var screen: null
    property real availableWidth: Number.POSITIVE_INFINITY
    property bool compact: expandedRowWidth > availableWidth
    readonly property real expandedWidth: symbolMetrics.width + quotaLabel.implicitWidth
        + countLabel.implicitWidth + 44
    readonly property real expandedRowWidth: {
        var total = expandedWidth;
        if (!parent) return total;
        var row = parent as RowLayout;
        var spacing = row ? row.spacing : 0;
        for (var i = 0; i < parent.children.length; i++) {
            var sibling = parent.children[i];
            if (sibling !== root && sibling.visible) total += sibling.implicitWidth + spacing;
        }
        return total;
    }
    readonly property bool available: effectiveController.online
    readonly property bool fresh: effectiveController.usageFresh
    readonly property var weeklyRemaining: Format.weekly(effectiveController.usage)
    readonly property var activeCount: effectiveController.agentsFresh
        ? effectiveController.agents.activeCount : null
    readonly property string quotaText: weeklyRemaining === null ? "—" : Format.percent(weeklyRemaining)
    readonly property string displayQuota: fresh ? quotaText
        : weeklyRemaining !== null ? quotaText + " stale"
        : !effectiveController.heartbeatHealthy ? "offline" : "—"
    readonly property string countText: activeCount === null ? "--" : String(activeCount)
    readonly property string accessibleSummary: "Codex. Weekly limit remaining: "
        + (weeklyRemaining === null ? "unavailable" : Format.percent(weeklyRemaining))
        + (fresh ? "" : ". Data " + (available ? effectiveController.usage.state : "disconnected"))
        + ". Active agents: " + (activeCount === null ? "unavailable" : activeCount)
        + ". Open status dashboard."
    implicitHeight: 34
    implicitWidth: content.implicitWidth + 22
    radius: 16
    color: root.effectiveController.pillBackground
    border.width: activeFocus ? 2 : 1.5
    border.color: activeFocus ? root.effectiveController.accent : root.effectiveController.borderColor
    enabled: controller !== null && controller !== undefined
    activeFocusOnTab: enabled
    Accessible.role: Accessible.Button
    Accessible.name: root.accessibleSummary
    Keys.onReturnPressed: root.effectiveController.toggleForScreen(root.screen)
    Keys.onSpacePressed: root.effectiveController.toggleForScreen(root.screen)

    // A host may bind its controller after creating the pill during a hot reload.
    QtObject {
        id: fallbackController
        readonly property bool online: false
        readonly property bool usageFresh: false
        readonly property bool agentsFresh: false
        readonly property bool heartbeatHealthy: false
        readonly property var usage: ({state: "unavailable", buckets: []})
        readonly property var agents: ({state: "unavailable", activeCount: null})
        readonly property color pillBackground: "#cc111a22"
        readonly property color foreground: "#e6edf3"
        readonly property color secondary: "#9ca6af"
        readonly property color accent: "#9dc4ef"
        readonly property color borderColor: "#34424f"
        readonly property string fontFamily: "sans-serif"
        function toggleForScreen(screen) {}
    }

    TextMetrics {
        id: symbolMetrics
        text: ">_"
        font.family: root.effectiveController.fontFamily
        font.pixelSize: 12
        font.bold: true
    }
    Rectangle {
        anchors.fill: parent
        radius: parent.radius
        color: root.effectiveController.foreground
        opacity: mouse.containsMouse ? 0.07 : 0
    }

    RowLayout {
        id: content
        anchors.centerIn: parent
        spacing: 7
        Text {
            text: root.compact && !root.fresh ? ">_!" : ">_"
            textFormat: Text.PlainText
            color: root.fresh ? root.effectiveController.accent : root.effectiveController.secondary
            font.family: root.effectiveController.fontFamily
            font.pixelSize: 12
            font.bold: true
        }
        Text {
            id: quotaLabel
            visible: !root.compact
            text: root.displayQuota
            textFormat: Text.PlainText
            color: root.effectiveController.foreground
            font.family: root.effectiveController.fontFamily
            font.pixelSize: 12
        }
        Rectangle {
            implicitWidth: 1
            implicitHeight: 12
            color: root.effectiveController.borderColor
        }
        Text {
            id: countLabel
            text: root.countText
            textFormat: Text.PlainText
            color: root.activeCount !== null && root.activeCount > 0
                ? root.effectiveController.accent : root.effectiveController.secondary
            font.family: root.effectiveController.fontFamily
            font.pixelSize: 12
        }
    }

    MouseArea {
        id: mouse
        anchors.fill: parent
        hoverEnabled: true
        cursorShape: Qt.PointingHandCursor
        onClicked: root.effectiveController.toggleForScreen(root.screen)
    }
}
