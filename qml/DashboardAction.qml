import QtQuick

StatusButton {
    required property var controller
    foreground: controller.foreground
    accent: controller.accent
    borderColor: controller.borderColor
    fontFamily: controller.fontFamily
    surface: controller.background
    quiet: true
}
