import QtQuick
import QtTest
import "../ThemePalette.js" as Palette

TestCase {
    name: "ThemePalette"
    function test_missing_and_partial_theme() {
        compare(Palette.color(null, "accent", "accentCyan", "#9dc4ef"), "#9dc4ef");
        compare(Palette.color({}, "accent", "accentCyan", "#9dc4ef"), "#9dc4ef");
        compare(Palette.color({accent: "#123456"}, "accent", "accentCyan", "#9dc4ef"), "#123456");
        compare(Palette.value({accent: "#123456"}, "fontFamily", "font", "sans-serif"), "sans-serif");
    }
    function test_invalid_values_fall_back() {
        var theme = {accent: "invalid color", font: 42};
        compare(Palette.color(theme, "accent", "accentCyan", "#9dc4ef"), "#9dc4ef");
        compare(Palette.value(theme, "fontFamily", "font", "sans-serif"), "sans-serif");
        compare(Palette.color({accent: {r: "invalid"}}, "accent", "accentCyan", "#9dc4ef"), "#9dc4ef");
    }
    function test_legacy_theme_properties() {
        var theme = {accentCyan: "#6699cc", font: "monospace"};
        compare(Palette.color(theme, "accent", "accentCyan", "#9dc4ef"), "#6699cc");
        compare(Palette.value(theme, "fontFamily", "font", "sans-serif"), "monospace");
        theme.accent = "#abcdef";
        compare(Palette.color(theme, "accent", "accentCyan", "#9dc4ef"), "#abcdef");
    }
    function test_qml_color_preserves_alpha() {
        var value = Qt.rgba(0.2, 0.4, 0.6, 0.3);
        compare(Palette.color({accent: value}, "accent", "accentCyan", "#9dc4ef"), value);
    }
}
