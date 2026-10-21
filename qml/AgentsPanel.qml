pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "StatusFormat.js" as Format

Item {
    id: root
    required property var controller
    property string filterMode: "all"
    property string query: ""
    readonly property int visibleAgentCount: rows.count
    readonly property real bodyContentHeight: list.contentHeight
    readonly property real bodyViewportHeight: list.height
    readonly property int allAgentCount: controller.agents.items.length
    readonly property int activeAgentCount: controller.agents.items.filter(function(agent) {
        return root.isActive(agent);
    }).length
    function isActive(agent) {
        return ["working", "waiting_approval", "waiting_input", "error"].indexOf(agent.state) >= 0;
    }
    function normalized(agent) {
        return {
            agentId: agent.id,
            title: Format.text(agent.title, "Codex session", 160),
            nickname: Format.text(agent.nickname, "", 80),
            workspace: Format.text(agent.workspace, "", 120),
            configuredModel: Format.text(agent.model, "", 120),
            state: agent.state,
            openTargetId: Format.text(agent.openTargetId, "", 100),
            openLabel: Format.text(agent.openLabel, "", 40),
            depth: Math.max(0, Math.min(4, agent.depth || 0))
        };
    }
    function reconcile() {
        var all = controller.agents.items;
        var search = query.trim().toLowerCase();
        var selected = all.filter(function(agent) {
            if (root.filterMode === "active" && !root.isActive(agent)) return false;
            if (!search) return true;
            return [agent.title, agent.nickname, agent.workspace, agent.model, Format.stateLabel(agent.state)]
                .join(" ").toLowerCase().indexOf(search) >= 0;
        }).map(function(agent) { return root.normalized(agent); });

        // Update roles in place. A routine status heartbeat must not replace
        // the model and destroy an agent's focused control or scroll position.
        for (var i = 0; i < selected.length; i++) {
            var expected = selected[i];
            var existing = -1;
            for (var j = i; j < rows.count; j++) {
                if (rows.get(j).agentId === expected.agentId) { existing = j; break; }
            }
            if (existing < 0) rows.insert(i, expected);
            else {
                if (existing !== i) rows.move(existing, i, 1);
                var current = rows.get(i);
                Object.keys(expected).forEach(function(key) {
                    if (current[key] !== expected[key]) rows.setProperty(i, key, expected[key]);
                });
            }
        }
        if (rows.count > selected.length) rows.remove(selected.length, rows.count - selected.length);
    }
    function reset() {
        filterMode = "all";
        query = "";
        list.positionViewAtBeginning();
    }
    onFilterModeChanged: { reconcile(); list.positionViewAtBeginning(); }
    onQueryChanged: { reconcile(); list.positionViewAtBeginning(); }
    Component.onCompleted: reconcile()
    Connections {
        target: root.controller
        function onAgentsChanged() { root.reconcile(); }
    }
    ListModel { id: rows }

    ColumnLayout {
        anchors.fill: parent
        spacing: 10
        RowLayout {
            Layout.fillWidth: true
            spacing: 8
            Text {
                Layout.fillWidth: true
                text: "Agent activity"
                textFormat: Text.PlainText
                color: root.controller.foreground
                font.family: root.controller.fontFamily
                font.pixelSize: 16
                font.weight: Font.DemiBold
            }
        }
        Text {
            objectName: "agentCounts"
            Layout.fillWidth: true
            text: Format.agentCounts(root.controller.agents)
            textFormat: Text.PlainText
            wrapMode: Text.Wrap
            color: root.controller.secondary
            font.family: root.controller.fontFamily
            font.pixelSize: 12
        }
        RowLayout {
            Layout.fillWidth: true
            spacing: 6
            StatusButton {
                objectName: "agentsAllFilter"
                checkable: true
                autoExclusive: true
                checked: root.filterMode === "all"
                text: "All · " + root.allAgentCount
                Accessible.name: "Show all agents"
                foreground: root.filterMode === "all" ? root.controller.accent : root.controller.secondary
                accent: root.controller.accent; surface: root.controller.background
                borderColor: root.filterMode === "all" ? root.controller.accent : root.controller.borderColor
                fontFamily: root.controller.fontFamily; quiet: true
                onClicked: root.filterMode = "all"
            }
            StatusButton {
                objectName: "agentsActiveFilter"
                checkable: true
                autoExclusive: true
                checked: root.filterMode === "active"
                text: "Active · " + (root.controller.agentsFresh ? root.activeAgentCount : "—")
                Accessible.name: "Show working and attention agents"
                foreground: root.filterMode === "active" ? root.controller.accent : root.controller.secondary
                accent: root.controller.accent; surface: root.controller.background
                borderColor: root.filterMode === "active" ? root.controller.accent : root.controller.borderColor
                fontFamily: root.controller.fontFamily; quiet: true
                onClicked: root.filterMode = "active"
            }
            TextField {
                id: search
                objectName: "agentsSearch"
                Layout.fillWidth: true
                Layout.minimumWidth: 60
                implicitHeight: 34
                text: root.query
                placeholderText: "Find an agent…"
                Accessible.name: "Find an agent by task, model, nickname or workspace"
                selectByMouse: true
                color: root.controller.foreground
                placeholderTextColor: root.controller.secondary
                font.family: root.controller.fontFamily
                font.pixelSize: 12
                leftPadding: 10
                rightPadding: 10
                onTextEdited: root.query = text
                background: Rectangle {
                    radius: 8
                    color: root.controller.cardColor
                    border.width: search.activeFocus ? 2 : 1
                    border.color: search.activeFocus ? root.controller.accent : root.controller.borderColor
                }
            }
        }
        Item {
            Layout.fillWidth: true
            Layout.fillHeight: true
            Layout.minimumHeight: 0
            ListView {
                id: list
                objectName: "agentsList"
                anchors.fill: parent
                clip: true
                spacing: 8
                boundsBehavior: Flickable.StopAtBounds
                model: rows
                cacheBuffer: height
                ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }
                delegate: Item {
                    id: row
                    required property string agentId
                    required property string title
                    required property string nickname
                    required property string workspace
                    required property string configuredModel
                    required property string state
                    required property string openTargetId
                    required property string openLabel
                    required property int depth
                    // Reserve the scrollbar gutter independently of content
                    // height, which depends on each wrapped card's width.
                    width: Math.max(0, list.width - 12)
                    height: card.implicitHeight
                    Rectangle {
                        visible: row.depth > 0
                        x: (row.depth - 1) * 12 + 4
                        y: 0
                        width: 1
                        height: parent.height + list.spacing
                        color: root.controller.borderColor
                    }
                    Rectangle {
                        visible: row.depth > 0
                        x: (row.depth - 1) * 12 + 4
                        y: 25
                        width: 8
                        height: 1
                        color: root.controller.borderColor
                    }
                    AgentCard {
                        id: card
                        x: row.depth * 12
                        width: row.width - x
                        controller: root.controller
                        agent: ({agentId: row.agentId, title: row.title, nickname: row.nickname,
                            workspace: row.workspace, configuredModel: row.configuredModel, state: row.state,
                            openTargetId: row.openTargetId, openLabel: row.openLabel})
                    }
                }
            }
            Column {
                anchors.centerIn: parent
                width: Math.min(parent.width - 32, 300)
                spacing: 8
                visible: rows.count === 0
                Text {
                    objectName: "emptyAgentsMessage"
                    width: parent.width
                    text: !root.controller.agentsFresh ? "Agent activity unavailable"
                        : root.allAgentCount === 0 ? "No loaded agents" : root.query.trim().length
                        ? "No matching agents" : "No active agents"
                    textFormat: Text.PlainText
                    horizontalAlignment: Text.AlignHCenter
                    wrapMode: Text.Wrap
                    color: root.controller.foreground
                    font.family: root.controller.fontFamily
                    font.pixelSize: 15
                    font.weight: Font.Medium
                }
                Text {
                    width: parent.width
                    text: !root.controller.agentsFresh ? "Waiting for a fresh activity update from Codex."
                        : root.allAgentCount === 0
                        ? "Loaded Codex sessions and their subagents will appear here."
                        : root.query.trim().length ? "Try another task, model or workspace."
                        : "Working agents and those waiting for you will appear here."
                    textFormat: Text.PlainText
                    horizontalAlignment: Text.AlignHCenter
                    wrapMode: Text.Wrap
                    color: root.controller.secondary
                    font.family: root.controller.fontFamily
                    font.pixelSize: 12
                    lineHeight: 1.2
                }
            }
        }
    }
}
