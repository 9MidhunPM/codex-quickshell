import QtQuick
import QtQuick.Controls

Button {
    id: root
    property color foreground: "#e6edf3"
    property color surface: "#202a34"
    property color borderColor: "#465360"
    property color accent: "#9dc4ef"
    property string fontFamily: "sans-serif"
    property bool quiet: false
    property int fontSize: 12
    implicitHeight: 34
    implicitWidth: Math.max(32, label.implicitWidth + 20)
    padding: 8
    hoverEnabled: true
    focusPolicy: Qt.StrongFocus
    Accessible.name: text
    Accessible.role: Accessible.Button
    contentItem: Text {
        id: label
        text: root.text
        textFormat: Text.PlainText
        color: root.enabled ? root.foreground : Qt.rgba(root.foreground.r, root.foreground.g, root.foreground.b, 0.45)
        font.family: root.fontFamily
        font.pixelSize: root.fontSize
        horizontalAlignment: Text.AlignHCenter
        verticalAlignment: Text.AlignVCenter
        elide: Text.ElideRight
    }
    background: Rectangle {
        radius: 8
        color: root.down ? Qt.lighter(root.surface, 1.35)
            : root.hovered ? Qt.lighter(root.surface, 1.15)
            : root.quiet ? "transparent" : root.surface
        border.width: root.visualFocus ? 2 : 1
        border.color: root.visualFocus ? root.accent : root.borderColor
    }
}
