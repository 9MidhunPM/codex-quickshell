pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "StatusFormat.js" as Format

Item {
    id: root
    required property var controller
    readonly property var allBuckets: controller.usage.buckets || []
    readonly property bool fresh: controller.usageFresh
    readonly property real preferredHeight: content.implicitHeight
    implicitHeight: preferredHeight
    implicitWidth: 300

    function resetScroll() {
        var flickable = scroll.contentItem as Flickable;
        if (flickable) flickable.contentY = 0;
    }

    function windowsFor(bucket) {
        var windows = (bucket.windows || []).slice();
        windows.sort(function(a, b) {
            return (a.durationMinutes === 10080 ? 0 : 1) - (b.durationMinutes === 10080 ? 0 : 1);
        });
        if (!windows.some(function(window) { return window.durationMinutes === 10080; }))
            windows.unshift({label: "Weekly", remainingPercent: null, resetsAt: null,
                durationMinutes: 10080, unavailable: true});
        return windows;
    }
    function resetText(window) {
        if (!Format.numeric(window.resetsAt))
            return window.unavailable ? "Weekly allowance not provided" : "Reset time unavailable";
        var countdown = Format.countdown(window.resetsAt, controller.now);
        return (countdown === "Reset due" ? countdown : "Resets " + countdown)
            + "\n" + Format.date(window.resetsAt);
    }

    ScrollView {
        id: scroll
        objectName: "usageScroll"
        anchors.fill: parent
        clip: true
        contentWidth: availableWidth
        ScrollBar.horizontal.policy: ScrollBar.AlwaysOff
        ScrollBar.vertical.policy: ScrollBar.AsNeeded

        ColumnLayout {
            id: content
            width: scroll.availableWidth
            spacing: 12

            RowLayout {
                Layout.fillWidth: true
                spacing: 8
                Text {
                    Layout.fillWidth: true
                    text: "CODEX ALLOWANCE"
                    textFormat: Text.PlainText
                    color: root.controller.secondary
                    font.family: root.controller.fontFamily
                    font.pixelSize: 10
                    font.weight: Font.DemiBold
                    font.letterSpacing: 1.15
                    elide: Text.ElideRight
                }
                Text {
                    objectName: "usagePlan"
                    Layout.maximumWidth: Math.max(70, content.width * 0.4)
                    text: Format.text(root.controller.usage.plan, "Plan unavailable", 40)
                    textFormat: Text.PlainText
                    color: root.controller.secondary
                    font.family: root.controller.fontFamily
                    font.pixelSize: 11
                    elide: Text.ElideRight
                }
            }

            Rectangle {
                visible: root.controller.usage.state !== "fresh" || !root.fresh
                Layout.fillWidth: true
                implicitHeight: freshnessText.implicitHeight + 20
                radius: 10
                color: root.controller.cardColor
                border.color: root.controller.borderColor
                Text {
                    id: freshnessText
                    anchors.fill: parent
                    anchors.margins: 10
                    text: root.allBuckets.length ? "Last known limits · "
                        + Format.observed(root.controller.usage.observedAt, root.controller.now)
                        : "Limits unavailable. Waiting for Codex."
                    textFormat: Text.PlainText
                    wrapMode: Text.Wrap
                    color: root.controller.secondary
                    font.family: root.controller.fontFamily
                    font.pixelSize: 11
                }
            }

            Repeater {
                id: bucketRepeater
                model: root.allBuckets.length ? root.allBuckets
                    : [{name: "Codex usage", windows: [], credits: null}]
                delegate: GridLayout {
                    id: bucket
                    required property var modelData
                    required property int index
                    Layout.fillWidth: true
                    columns: width >= 560 ? 2 : 1
                    columnSpacing: 12
                    rowSpacing: 12

                    RowLayout {
                        Layout.fillWidth: true
                        Layout.columnSpan: bucket.columns
                        spacing: 8
                        Text {
                            Layout.fillWidth: true
                            text: Format.text(bucket.modelData.name, "Codex usage", 120)
                            textFormat: Text.PlainText
                            color: root.controller.foreground
                            font.family: root.controller.fontFamily
                            font.pixelSize: 12
                            font.weight: Font.DemiBold
                            wrapMode: Text.Wrap
                        }
                        Text {
                            visible: root.allBuckets.length > 1
                            text: (bucket.index + 1) + " / " + root.allBuckets.length
                            textFormat: Text.PlainText
                            color: root.controller.secondary
                            font.family: root.controller.fontFamily
                            font.pixelSize: 10
                        }
                    }

                    Rectangle {
                        objectName: "quotaCard"
                        Layout.fillWidth: true
                        Layout.alignment: Qt.AlignTop
                        Layout.preferredWidth: 400
                        implicitHeight: quotaContent.implicitHeight + 32
                        radius: 14
                        color: root.controller.cardColor
                        border.width: 1
                        border.color: root.controller.borderColor

                        ColumnLayout {
                            id: quotaContent
                            anchors.left: parent.left
                            anchors.right: parent.right
                            anchors.top: parent.top
                            anchors.margins: 16
                            spacing: 14

                            Repeater {
                                model: root.windowsFor(bucket.modelData)
                                delegate: ColumnLayout {
                                    id: quota
                                    required property var modelData
                                    required property int index
                                    readonly property bool primary: modelData.durationMinutes === 10080
                                    readonly property bool available: Format.numeric(modelData.remainingPercent)
                                    Layout.fillWidth: true
                                    spacing: quota.primary ? 7 : 6

                                    Rectangle {
                                        visible: quota.index > 0
                                        Layout.fillWidth: true
                                        implicitHeight: 1
                                        color: root.controller.borderColor
                                        opacity: 0.6
                                        Layout.bottomMargin: 4
                                    }
                                    RowLayout {
                                        Layout.fillWidth: true
                                        Text {
                                            Layout.fillWidth: true
                                            text: quota.primary ? "Weekly"
                                                : Format.text(quota.modelData.label, "Usage window", 60)
                                            textFormat: Text.PlainText
                                            color: root.controller.foreground
                                            font.family: root.controller.fontFamily
                                            font.pixelSize: quota.primary ? 14 : 12
                                            font.weight: Font.DemiBold
                                            wrapMode: Text.Wrap
                                        }
                                        Text {
                                            visible: !quota.primary
                                            text: Format.percent(quota.modelData.remainingPercent)
                                                + (quota.available ? " left" : "")
                                            textFormat: Text.PlainText
                                            color: root.fresh ? root.controller.accent : root.controller.secondary
                                            font.family: root.controller.fontFamily
                                            font.pixelSize: 13
                                            font.weight: Font.DemiBold
                                        }
                                    }
                                    RowLayout {
                                        visible: quota.primary
                                        Layout.fillWidth: true
                                        Layout.topMargin: 2
                                        spacing: 8
                                        Text {
                                            objectName: "weeklyRemaining"
                                            text: quota.available
                                                ? Format.percent(quota.modelData.remainingPercent) : "Unavailable"
                                            textFormat: Text.PlainText
                                            color: root.controller.foreground
                                            font.family: root.controller.fontFamily
                                            font.pixelSize: quota.available ? 36 : 22
                                            font.weight: Font.DemiBold
                                        }
                                        Text {
                                            visible: quota.available
                                            Layout.alignment: Qt.AlignBottom
                                            Layout.bottomMargin: 6
                                            Layout.fillWidth: true
                                            text: "remaining"
                                            textFormat: Text.PlainText
                                            color: root.controller.secondary
                                            font.family: root.controller.fontFamily
                                            font.pixelSize: 11
                                        }
                                    }
                                    Rectangle {
                                        objectName: quota.primary ? "weeklyProgress" : "windowProgress"
                                        Layout.fillWidth: true
                                        implicitHeight: quota.primary ? 7 : 4
                                        radius: height / 2
                                        color: root.controller.borderColor
                                        opacity: quota.available ? 1 : 0.45
                                        Rectangle {
                                            width: parent.width * Format.remaining(quota.modelData)
                                            height: parent.height
                                            radius: height / 2
                                            color: root.controller.accent
                                            opacity: root.fresh ? 1 : 0.45
                                        }
                                    }
                                    Text {
                                        objectName: quota.primary ? "weeklyReset" : "windowReset"
                                        Layout.fillWidth: true
                                        text: root.resetText(quota.modelData)
                                        textFormat: Text.PlainText
                                        wrapMode: Text.Wrap
                                        color: root.controller.secondary
                                        font.family: root.controller.fontFamily
                                        font.pixelSize: 11
                                        lineHeight: 1.25
                                    }
                                }
                            }
                        }
                    }

                    Rectangle {
                        objectName: "creditCard"
                        Layout.fillWidth: true
                        Layout.alignment: Qt.AlignTop
                        Layout.preferredWidth: 300
                        implicitHeight: creditContent.implicitHeight + 32
                        radius: 14
                        color: root.controller.cardColor
                        border.width: 1
                        border.color: root.controller.borderColor

                        ColumnLayout {
                            id: creditContent
                            anchors.left: parent.left
                            anchors.right: parent.right
                            anchors.top: parent.top
                            anchors.margins: 16
                            spacing: 7
                            Text {
                                text: "Codex credits"
                                textFormat: Text.PlainText
                                color: root.controller.foreground
                                font.family: root.controller.fontFamily
                                font.pixelSize: 14
                                font.weight: Font.DemiBold
                            }
                            Text {
                                objectName: "creditBalance"
                                Layout.fillWidth: true
                                readonly property string balance: Format.credits(bucket.modelData.credits)
                                text: balance
                                textFormat: Text.PlainText
                                wrapMode: Text.WrapAnywhere
                                color: root.controller.foreground
                                font.family: root.controller.fontFamily
                                font.pixelSize: balance.length > 14 ? 15 : 28
                                font.weight: Font.DemiBold
                            }
                            Text {
                                Layout.fillWidth: true
                                text: bucket.modelData.credits && bucket.modelData.credits.unlimited === true
                                    ? "Unlimited additional usage"
                                    : "For additional Codex usage"
                                textFormat: Text.PlainText
                                wrapMode: Text.Wrap
                                color: root.controller.secondary
                                font.family: root.controller.fontFamily
                                font.pixelSize: 10
                                lineHeight: 1.2
                            }
                            Text {
                                objectName: "creditDetail"
                                visible: text.length > 0
                                Layout.fillWidth: true
                                text: Format.creditDetail(bucket.modelData.credits)
                                textFormat: Text.PlainText
                                wrapMode: Text.WrapAnywhere
                                color: root.controller.secondary
                                font.family: root.controller.fontFamily
                                font.pixelSize: 11
                                lineHeight: 1.25
                            }
                        }
                    }
                }
            }

            Text {
                Layout.fillWidth: true
                text: "Codex credits and API Platform balance are separate."
                textFormat: Text.PlainText
                wrapMode: Text.Wrap
                color: root.controller.secondary
                font.family: root.controller.fontFamily
                font.pixelSize: 10
                lineHeight: 1.3
                Layout.bottomMargin: 2
            }
        }
    }
}
