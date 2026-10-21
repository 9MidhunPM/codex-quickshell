import QtQuick
import QtQuick.Layouts
import QtTest
import ".." as CodexUi

TestCase {
    id: testCase
    name: "CodexPill"
    when: windowShown
    visible: true
    width: 1200
    height: 100

    QtObject {
        id: mockController
        property bool online: true
        property bool usageFresh: true
        property bool agentsFresh: true
        property bool heartbeatHealthy: true
        property var usage: ({state: "fresh", buckets: [{windows: [
            {label: "Weekly", remainingPercent: 64, durationMinutes: 10080}
        ]}]})
        property var agents: ({state: "fresh", activeCount: 1})
        property color pillBackground: "#111a22"
        property color foreground: "#e6edf3"
        property color secondary: "#9ca6af"
        property color accent: "#9dc4ef"
        property color borderColor: "#34424f"
        property string fontFamily: "sans-serif"
        function toggleForScreen(screen) {}
    }
    RowLayout {
        id: row
        spacing: 4
        Rectangle {
            id: sibling
            implicitWidth: 500
            implicitHeight: 34
        }
        CodexUi.CodexPill {
            id: pill
            controller: null
            availableWidth: 1000
        }
    }
    function init() {
        pill.controller = null;
        pill.availableWidth = 1000;
        sibling.implicitWidth = 500;
        sibling.visible = true;
        mockController.agents = {state: "fresh", activeCount: 1};
        wait(0);
    }
    function test_null_and_undefined_controller_are_safe() {
        compare(pill.enabled, false);
        compare(pill.countText, "--");
        compare(pill.displayQuota, "offline");
        verify(pill.implicitWidth > 0);
        pill.controller = undefined;
        wait(0);
        compare(pill.countText, "--");
        compare(pill.enabled, false);
        pill.controller = mockController;
        wait(0);
        compare(pill.enabled, true);
        compare(pill.quotaText, "64%");
        compare(pill.countText, "1");
        pill.controller = null;
        wait(0);
        compare(pill.enabled, false);
        compare(pill.countText, "--");
    }
    function test_default_width_has_no_host_layout_assumptions() {
        var component = Qt.createComponent("../CodexPill.qml");
        compare(component.status, Component.Ready);
        var standalone = component.createObject(testCase, {controller: mockController}) as CodexUi.CodexPill;
        verify(standalone !== null);
        compare(standalone.availableWidth, Number.POSITIVE_INFINITY);
        compare(standalone.compact, false);
        standalone.destroy();
    }
    function test_unknown_count_is_distinct_from_zero() {
        pill.controller = mockController;
        mockController.agents = {state: "fresh", activeCount: null};
        wait(0);
        compare(pill.countText, "--");
        mockController.agents = {state: "fresh", activeCount: 0};
        wait(0);
        compare(pill.countText, "0");
    }
    function test_compaction_is_stable() {
        pill.controller = mockController;
        wait(0);
        pill.availableWidth = pill.expandedRowWidth + 20;
        wait(20);
        compare(pill.compact, false);
        var expandedWidth = pill.implicitWidth;
        var rowWidth = pill.expandedRowWidth;
        pill.availableWidth = rowWidth - 1;
        wait(20);
        compare(pill.compact, true);
        verify(pill.implicitWidth < expandedWidth);
        compare(pill.expandedRowWidth, rowWidth);
        wait(80);
        compare(pill.compact, true);
        compare(pill.expandedRowWidth, rowWidth);
    }
    function test_compaction_reacts_to_sibling_visibility() {
        pill.controller = mockController;
        pill.availableWidth = 700;
        wait(0);
        compare(pill.compact, false);
        sibling.implicitWidth = 900;
        wait(0);
        compare(pill.compact, true);
        sibling.visible = false;
        wait(0);
        compare(pill.compact, false);
    }
}
