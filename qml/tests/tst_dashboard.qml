import QtQuick
import QtTest
import ".." as CodexUi

TestCase {
    id: testCase
    name: "CodexDashboard"
    when: windowShown
    visible: true
    width: 900
    height: 820

    function agent(id, state, depth, model) {
        return {id: id, title: id, nickname: "Nickname " + id, state: state,
            depth: depth, model: model, workspace: "Example", openTargetId: id === "parent" ? "parent" : null, openLabel: "Open session"};
    }
    function freshSnapshot() {
        return {agents: {state: "fresh", activeCount: 2, observedAt: 1700000000, items: [
            agent("parent", "working", 0, "gpt-6.1-sol"),
            agent("child", "working", 1, "gpt-6-astra"),
            agent("approval", "waiting_approval", 1, null),
            agent("idle", "idle", 0, "gpt-6-luna")
        ]}};
    }
    function freshUsage() {
        return {state: "fresh", plan: "Example", observedAt: 1700000000,
            buckets: [{name: "Codex", windows: [{label: "Weekly", durationMinutes: 10080,
                remainingPercent: 60, resetsAt: 1700003600}], credits: {balance: "0E-10"}}]};
    }
    QtObject {
        id: mockController
        property var snapshot: testCase.freshSnapshot()
        readonly property var agents: snapshot.agents
        property var usage: testCase.freshUsage()
        property bool transportConnected: true
        property bool heartbeatHealthy: true
        property bool online: true
        property bool agentsFresh: true
        property bool usageFresh: true
        property string actionMessage: ""
        property string transportMessage: ""
        property double now: 1700000000000
        property color foreground: "#e6edf3"
        property color secondary: "#9ca6af"
        property color accent: "#9dc4ef"
        property color background: "#111a22"
        property color borderColor: "#34424f"
        property color cardColor: "#17212c"
        property color warning: "#e8bc6a"
        property color danger: "#ec9094"
        property bool reducedMotion: true
        property string fontFamily: "sans-serif"
        property var requests: []
        function request(value) { requests = requests.concat([value]); }
    }
    CodexUi.CodexDashboard {
        id: dashboard
        controller: mockController
        width: implicitWidth
        height: preferredHeight
    }
    SignalSpy {
        id: closeSpy
        target: dashboard
        signalName: "closeRequested"
    }
    function init() {
        dashboard.width = Qt.binding(function() { return dashboard.implicitWidth; });
        mockController.agentsFresh = true;
        mockController.usageFresh = true;
        mockController.online = true;
        dashboard.hostWindowVisible = true;
        mockController.snapshot = freshSnapshot();
        mockController.usage = freshUsage();
        mockController.requests = [];
        dashboard.reset();
        closeSpy.clear();
        wait(10);
    }
    function panel() { return findChild(dashboard, "agentsPanel"); }
    function usage() { return findChild(dashboard, "usagePanel"); }
    function manySnapshot() {
        var value = freshSnapshot();
        for (var i = 0; i < 40; i++) value.agents.items.push(agent("extra" + i, "idle", 1, null));
        return value;
    }
    function test_overview_is_compact_and_details_tabs_are_roomy() {
        compare(dashboard.selectedView, "overview");
        compare(dashboard.width, 560);
        verify(dashboard.height >= 280 && dashboard.height <= 400);
        verify(findChild(dashboard, "overviewPanel").visible);
        compare(usage().visible, false);
        compare(panel().visible, false);
        compare(findChild(dashboard, "overviewWeekly").text, "60%");
        compare(findChild(dashboard, "overviewCredits").text, "0");
        var preview = findChild(dashboard, "overviewAgentRow-approval");
        verify(preview.visible);
        var position = preview.mapToItem(findChild(dashboard, "overviewPanel"), 0, 0);
        verify(position.y + preview.height <= findChild(dashboard, "overviewPanel").height);
        mouseClick(findChild(dashboard, "viewUsage"));
        tryCompare(dashboard, "width", 860);
        compare(dashboard.height, 620);
        verify(usage().visible);
        compare(findChild(dashboard, "viewAllLimits"), null);
        mouseClick(findChild(dashboard, "viewAgents"));
        verify(panel().visible);
        verify(findChild(dashboard, "agentsSearch").visible);
        compare(findChild(dashboard, "viewAllAgents"), null);
    }
    function test_agents_show_every_metadata_field_without_expansion() {
        dashboard.selectView("agents");
        wait(40);
        compare(findChild(dashboard, "configuredModel-parent").text, "Configured model: gpt-6.1-sol");
        compare(findChild(dashboard, "configuredModel-child").text, "Configured model: gpt-6-astra");
        compare(findChild(dashboard, "configuredModel-approval").text, "Configured model: Unavailable");
        var nickname = findChild(dashboard, "agentNickname-child");
        var workspace = findChild(dashboard, "agentWorkspace-child");
        compare(nickname.text, "Nickname: Nickname child");
        compare(workspace.text, "Workspace: Example");
        verify(nickname.visible && workspace.visible);
        compare(findChild(dashboard, "agentDetails-child"), null);
    }
    function test_heartbeat_preserves_focus_and_scroll() {
        dashboard.selectView("agents");
        mockController.snapshot = manySnapshot();
        wait(40);
        var open = findChild(dashboard, "agentOpen-parent");
        open.forceActiveFocus();
        tryCompare(open, "activeFocus", true);
        var list = findChild(dashboard, "agentsList");
        list.contentY = 50;
        var previousPosition = list.contentY;
        mockController.snapshot = manySnapshot();
        wait(40);
        compare(dashboard.selectedView, "agents");
        compare(list.contentY, previousPosition);
        compare(findChild(dashboard, "agentOpen-parent"), open);
        compare(open.activeFocus, true);
        panel().query = "parent";
        panel().filterMode = "active";
        dashboard.reset();
        compare(dashboard.selectedView, "overview");
        compare(panel().query, "");
        compare(panel().filterMode, "all");
        compare(dashboard.width, 560);
    }
    function test_filters_and_local_search_preserve_tree_order() {
        dashboard.selectView("agents");
        wait(30);
        mouseClick(findChild(dashboard, "agentsActiveFilter"));
        compare(panel().visibleAgentCount, 3);
        compare(findChild(dashboard, "agentsActiveFilter").checked, true);
        mouseClick(findChild(dashboard, "agentsActiveFilter"));
        compare(findChild(dashboard, "agentsActiveFilter").checked, true);
        dashboard.selectView("agents");
        panel().query = "astra";
        compare(panel().visibleAgentCount, 1);
        panel().query = "missing task";
        compare(panel().visibleAgentCount, 0);
        compare(findChild(dashboard, "emptyAgentsMessage").text, "No matching agents");
        panel().query = "";
        wait(20);
        mouseClick(findChild(dashboard, "agentsAllFilter"));
        tryCompare(panel(), "filterMode", "all");
        tryCompare(panel(), "visibleAgentCount", 4);
        compare(findChild(dashboard, "agentsAllFilter").checked, true);
    }
    function test_only_fresh_observed_open_actions_are_available() {
        dashboard.selectView("agents");
        wait(30);
        var open = findChild(dashboard, "agentOpen-parent");
        verify(open.visible);
        mouseClick(open);
        compare(mockController.requests[0].type, "open_session");
        compare(mockController.requests[0].threadId, "parent");
        mockController.agentsFresh = false;
        wait(10);
        compare(open.visible, false);
        compare(findChild(dashboard, "agentOpen-child").visible, false);
    }
    function test_fixed_dashboard_dispatch_and_responsive_layout() {
        mouseClick(findChild(dashboard, "headerUsage"));
        mouseClick(findChild(dashboard, "headerBilling"));
        compare(mockController.requests.length, 2);
        compare(mockController.requests[0].type, "open_dashboard");
        compare(mockController.requests[0].target, "usage");
        compare(mockController.requests[1].target, "billing");
        for (var i = 0; i < 2; i++) {
            dashboard.width = [640, 320][i];
            wait(30);
            compare(dashboard.wideLayout, false);
            verify(findChild(dashboard, "overviewPanel").width <= dashboard.width);
            compare(panel().visible, false);
            compare(usage().visible, false);
        }
        compare(dashboard.toolbarWrapped, true);
        verify(findChild(dashboard, "wrappedUsage").visible);
        verify(findChild(dashboard, "wrappedBilling").visible);
        compare(findChild(dashboard, "headerUsage").visible, false);
    }
    function test_header_and_tabs_stay_fixed_while_agents_scroll() {
        dashboard.selectView("agents");
        mockController.snapshot = manySnapshot();
        wait(40);
        var header = findChild(dashboard, "headerUsage").mapToItem(dashboard, 0, 0);
        var tab = findChild(dashboard, "viewUsage").mapToItem(dashboard, 0, 0);
        var list = findChild(dashboard, "agentsList");
        list.contentY = 300;
        wait(20);
        compare(findChild(dashboard, "headerUsage").mapToItem(dashboard, 0, 0).y, header.y);
        compare(findChild(dashboard, "viewUsage").mapToItem(dashboard, 0, 0).y, tab.y);
        verify(panel().bodyContentHeight > panel().bodyViewportHeight);
    }
    function test_unavailable_activity_is_not_an_empty_live_list() {
        dashboard.selectView("agents");
        mockController.agentsFresh = false;
        mockController.snapshot = {agents: {state: "unavailable", activeCount: null, items: []}};
        wait(20);
        compare(findChild(dashboard, "emptyAgentsMessage").text, "Agent activity unavailable");
        compare(findChild(dashboard, "agentsActiveFilter").text, "Active · —");
    }
    function test_narrow_overview_keeps_both_metrics_in_view() {
        for (var i = 0; i < 2; i++) {
            dashboard.width = [640, 320][i];
            wait(100);
            var weekly = findChild(dashboard, "overviewWeekly");
            var credits = findChild(dashboard, "overviewCredits");
            compare(weekly.text, "60%");
            compare(credits.text, "0");
            var overview = findChild(dashboard, "overviewPanel");
            var position = credits.mapToItem(overview, 0, 0);
            verify(position.y >= 0);
            verify(position.y + credits.height <= overview.height);
            verify(position.x >= 0 && position.x + credits.width <= overview.width);
        }
    }
    function test_missing_weekly_is_unavailable_even_with_another_window() {
        dashboard.selectView("usage");
        var value = freshUsage();
        value.buckets[0].windows[0].durationMinutes = 300;
        value.buckets[0].windows[0].label = "5-hour";
        value.buckets[0].windows[0].remainingPercent = 99;
        mockController.usage = value;
        wait(100);
        compare(findChild(dashboard, "weeklyRemaining").text, "Unavailable");
        compare(findChild(dashboard, "weeklyReset").text, "Weekly allowance not provided");
    }
    function test_separate_buckets_and_extreme_credit_details() {
        var value = freshUsage();
        value.buckets[0].credits.balance = "1e-1000";
        value.buckets.push({name: "Other model", windows: [{label: "Weekly", durationMinutes: 10080,
            remainingPercent: 90, resetsAt: null}], credits: {balance: "20.00"}});
        mockController.usage = value;
        wait(100);
        compare(findChild(dashboard, "overviewCredits").text, "See details");
        mouseClick(findChild(dashboard, "viewUsage"));
        compare(dashboard.selectedView, "usage");
        wait(100);
        compare(usage().allBuckets.length, 2);
        compare(findChild(dashboard, "weeklyRemaining").text, "60%");
        compare(findChild(dashboard, "creditDetail").text, "1e-1000");
    }
    function test_escape_closes_from_focused_child_control() {
        dashboard.selectView("agents");
        wait(30);
        var search = findChild(dashboard, "agentsSearch");
        search.forceActiveFocus();
        tryCompare(search, "activeFocus", true);
        keyClick(Qt.Key_Escape);
        tryCompare(closeSpy, "count", 1);
    }
    function test_escape_shortcut_disabled_for_hidden_panel() {
        var tab = findChild(dashboard, "viewAgents");
        tab.forceActiveFocus();
        tryCompare(tab, "activeFocus", true);
        dashboard.hostWindowVisible = false;
        keyClick(Qt.Key_Escape);
        wait(20);
        compare(closeSpy.count, 0);
        dashboard.hostWindowVisible = true;
        keyClick(Qt.Key_Escape);
        tryCompare(closeSpy, "count", 1);
    }
}
