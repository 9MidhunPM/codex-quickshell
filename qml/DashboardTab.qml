import QtQuick
import QtQuick.Controls

TabButton {
    id: root
    required property var controller
    implicitHeight: 36
    font.family: controller.fontFamily
    font.pixelSize: 12
    focusPolicy: Qt.StrongFocus
    contentItem: Text {
        text: root.text
        textFormat: Text.PlainText
        horizontalAlignment: Text.AlignHCenter
        verticalAlignment: Text.AlignVCenter
        font: root.font
        color: root.checked ? root.controller.foreground : root.controller.secondary
        elide: Text.ElideRight
    }
    background: Rectangle {
        radius: 9
        color: root.checked ? Qt.rgba(root.controller.accent.r, root.controller.accent.g,
            root.controller.accent.b, 0.16) : root.hovered ? root.controller.cardColor : "transparent"
        border.width: root.visualFocus ? 2 : 0
        border.color: root.controller.accent
        Behavior on color {
            ColorAnimation { duration: root.controller.reducedMotion ? 0 : 120 }
        }
    }
}
