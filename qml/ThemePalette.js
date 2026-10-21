// Palette lookup accepts optional partial themes without assuming a host schema.
function value(theme, name, legacyName, fallback) {
    if (!theme || typeof theme !== "object") return fallback;
    var value = theme[name];
    if (value === undefined || value === null) value = theme[legacyName];
    return typeof value === "string" && value.length ? value : fallback;
}
function color(theme, name, legacyName, fallback) {
    if (!theme || typeof theme !== "object") return fallback;
    var value = theme[name];
    if (value === undefined || value === null) value = theme[legacyName];
    // QML color values expose rgba; CSS hex strings are safe to convert.
    if (value && typeof value === "object" && typeof value.r === "number"
        && typeof value.g === "number" && typeof value.b === "number")
        return Qt.rgba(value.r, value.g, value.b, typeof value.a === "number" ? value.a : 1);
    if (typeof value === "string" && /^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$/.test(value))
        return value;
    return fallback;
}
