.pragma library

function text(value, fallback, limit) {
    return typeof value === "string" && value.length
        ? value.slice(0, limit || 240) : (fallback || "");
}

function numeric(value) {
    return typeof value === "number" && isFinite(value);
}

function percent(value) {
    return numeric(value) ? Math.round(Math.max(0, Math.min(100, value))) + "%" : "Unavailable";
}

function remaining(window) {
    return numeric(window.remainingPercent)
        ? Math.max(0, Math.min(100, window.remainingPercent)) / 100 : 0;
}

function date(epoch) {
    if (!numeric(epoch)) return "Reset time unavailable";
    var value = new Date(epoch * 1000);
    if (isNaN(value.getTime())) return "Reset time unavailable";
    return Qt.formatDateTime(value, "ddd, d MMM · h:mm AP");
}

function observed(epoch, now) {
    if (!numeric(epoch)) return "No update received";
    var age = Math.max(0, Math.floor(now / 1000 - epoch));
    if (age < 60) return "Updated just now";
    if (age < 3600) return "Updated " + Math.floor(age / 60) + "m ago";
    if (age < 86400) return "Updated " + Math.floor(age / 3600) + "h ago";
    return "Updated " + Math.floor(age / 86400) + "d ago";
}

function countdown(epoch, now) {
    if (!numeric(epoch)) return "";
    var seconds = Math.max(0, Math.ceil(epoch - now / 1000));
    if (!seconds) return "Reset due";
    var days = Math.floor(seconds / 86400);
    var hours = Math.floor((seconds % 86400) / 3600);
    var minutes = Math.floor((seconds % 3600) / 60);
    if (days) return "in " + days + "d " + hours + "h";
    if (hours) return "in " + hours + "h " + minutes + "m";
    return "in " + minutes + "m " + (seconds % 60) + "s";
}

function weekly(usage) {
    if (!usage || !Array.isArray(usage.buckets) || !usage.buckets.length) return null;
    // Each bucket is a separate quota. Do not combine percentages across models.
    var windows = usage.buckets[0].windows || [];
    for (var i = 0; i < windows.length; i++) {
        var window = windows[i];
        if (window.durationMinutes === 10080)
            return numeric(window.remainingPercent) ? window.remainingPercent : null;
    }
    return null;
}

function stateLabel(state) {
    return ({
        working: "Working",
        waiting_approval: "Needs approval",
        waiting_input: "Waiting for you",
        idle: "Idle",
        error: "Error",
        unavailable: "Status unavailable"
    })[state] || "Status unavailable";
}

// Work on decimal strings rather than Number: credit precision belongs to the
// provider, and a tiny nonzero value must never round down to a zero balance.
function decimalBalance(value) {
    if (numeric(value)) value = String(value);
    if (typeof value !== "string") return null;
    var raw = value.trim();
    if (!raw.length) return null;
    if (raw.length > 256) return "See details";
    var match = /^([+-]?)(?:(\d+)(?:\.(\d*))?|\.(\d+))(?:[eE]([+-]?\d+))?$/.exec(raw);
    if (!match) return raw;
    var integer = match[2] || "0";
    var fraction = match[3] !== undefined ? match[3] : (match[4] || "");
    var digits = integer + fraction;
    if (!/[1-9]/.test(digits)) return "0";
    var withoutLeading = digits.replace(/^0+/, "");
    var leadingZeros = digits.length - withoutLeading.length;
    digits = withoutLeading.replace(/0+$/, "");
    var exponent = Number(match[5] || "0");
    if (!isFinite(exponent) || Math.abs(exponent) > 1000) return "See details";
    var point = integer.length + exponent - leadingZeros;
    var negative = match[1] === "-";
    var length = (negative ? 1 : 0) + (point <= 0 ? 2 - point + digits.length
        : point >= digits.length ? point : digits.length + 1);
    if (length > 64) return "See details";
    var result;
    if (point <= 0) result = "0." + "0".repeat(-point) + digits;
    else if (point >= digits.length) result = digits + "0".repeat(point - digits.length);
    else result = digits.slice(0, point) + "." + digits.slice(point);
    return (negative ? "-" : "") + result;
}

function credits(value) {
    if (!value) return "Unavailable";
    if (value.unlimited === true) return "Unlimited";
    if (value.balanceTruncated === true) return "See details";
    var balance = decimalBalance(value.balance);
    if (balance !== null) return balance;
    if (value.hasCredits === false) return "No credits";
    if (value.hasCredits === true) return "Available · amount unavailable";
    return "Unavailable";
}

function creditDetail(value) {
    if (!value || value.unlimited === true || credits(value) !== "See details") return "";
    if (value.balanceTruncated === true || typeof value.balance === "string" && value.balance.trim().length > 256)
        return "Provider value exceeds display limit.";
    return typeof value.balance === "string" ? value.balance.trim()
        : numeric(value.balance) ? String(value.balance) : "";
}

function agentCounts(agents) {
    if (!agents || agents.state !== "fresh" || agents.activeCount === null)
        return "Activity unavailable";
    var waiting = 0, idle = 0, errors = 0;
    (agents.items || []).forEach(function(agent) {
        if (agent.state === "waiting_approval" || agent.state === "waiting_input") waiting++;
        else if (agent.state === "idle") idle++;
        else if (agent.state === "error") errors++;
    });
    return agents.activeCount + " working · " + waiting + " waiting · " + idle + " idle"
        + (errors ? " · " + errors + " errors" : "");
}

function agentSnapshot(value, online) {
    if (online && value.state === "fresh") return value;
    var items = value.items.map(function(item) {
        return {id: item.id, parentId: item.parentId, title: item.title, nickname: item.nickname,
            workspace: item.workspace,
            model: item.model, state: "unavailable", openTargetId: null, openLabel: null, depth: item.depth};
    });
    return {state: "unavailable", observedAt: value.observedAt, activeCount: null, items: items};
}

function validSnapshot(value) {
    if (!value || value.type !== "snapshot" || value.version !== 1) return false;
    if (!value.connection || !value.usage || !value.agents) return false;
    if (["connected", "connecting", "disconnected", "incompatible"].indexOf(value.connection.state) < 0)
        return false;
    if (["fresh", "stale", "unavailable"].indexOf(value.usage.state) < 0
            || ["fresh", "unavailable"].indexOf(value.agents.state) < 0) return false;
    if (!Array.isArray(value.usage.buckets) || value.usage.buckets.length > 128
            || !Array.isArray(value.agents.items) || value.agents.items.length > 500) return false;
    if (value.agents.activeCount !== null && (!numeric(value.agents.activeCount)
            || value.agents.activeCount < 0 || value.agents.activeCount % 1 !== 0)) return false;
    for (var i = 0; i < value.usage.buckets.length; i++) {
        var bucket = value.usage.buckets[i];
        if (!bucket || typeof bucket.id !== "string" || !Array.isArray(bucket.windows)
                || bucket.windows.length > 16) return false;
        for (var j = 0; j < bucket.windows.length; j++) {
            var window = bucket.windows[j];
            if (!window || typeof window.label !== "string") return false;
            if (window.remainingPercent !== null && (!numeric(window.remainingPercent)
                    || window.remainingPercent < 0 || window.remainingPercent > 100)) return false;
        }
    }
    for (var k = 0; k < value.agents.items.length; k++) {
        var agent = value.agents.items[k];
        if (!agent || typeof agent.id !== "string"
                || ["working", "waiting_approval", "waiting_input", "idle", "error", "unavailable"]
                    .indexOf(agent.state) < 0) return false;
    }
    return true;
}
