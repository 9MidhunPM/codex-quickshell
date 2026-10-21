// Run with: node qml/test-format.cjs
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const source = fs.readFileSync(path.join(__dirname, "StatusFormat.js"), "utf8")
    .replace(/^\.pragma library\s*/, "");
const format = vm.createContext({Qt: {formatDateTime: value => value.toISOString()}});
vm.runInContext(source, format);

const snapshot = {
    type: "snapshot", version: 1,
    connection: {state: "connected", message: ""},
    usage: {state: "fresh", observedAt: 1700000000, plan: "Example", buckets: [
        {id: "primary", name: "Codex", windows: [
            {label: "Weekly", remainingPercent: 0, resetsAt: 1700003600, durationMinutes: 10080}
        ], credits: null},
        {id: "separate-model", name: "Other model", windows: [
            {label: "Weekly", remainingPercent: 80, resetsAt: null, durationMinutes: 10080}
        ], credits: null}
    ]},
    agents: {state: "fresh", observedAt: 1700000000, activeCount: 0, items: []}
};
assert.equal(format.validSnapshot(snapshot), true);
assert.equal(format.weekly(snapshot.usage), 0, "independent buckets must not be combined");
assert.equal(format.percent(0), "0%");
assert.equal(format.percent(null), "Unavailable", "unknown quota must not become zero");
assert.equal(format.percent(NaN), "Unavailable");
assert.equal(format.credits({balance: 0, unlimited: false, hasCredits: false}), "0");
assert.equal(format.credits(null), "Unavailable");
assert.equal(format.credits({balance: null, unlimited: true}), "Unlimited");
assert.equal(format.credits({balance: "<b>literal provider value</b>", hasCredits: true}),
    "<b>literal provider value</b>", "provider strings are preserved for PlainText rendering");
assert.equal(format.credits({balance: "0", hasCredits: false}), "0");
assert.equal(format.credits({balance: "0E-10", hasCredits: false}), "0");
for (const zero of ["0E-10", "0.E-10", ".0E-10", "-0.000E-10", "0e+10", "  +0.00e-9999  "])
    assert.equal(format.credits({balance: zero}), "0", zero);
for (const [value, expected] of [
    ["1E-10", "0.0000000001"], ["-1.23E-3", "-0.00123"],
    ["+00012.3400e2", "1234"], [".005e+2", "0.5"], ["1000e-2", "10"],
    ["12345678901234567890.12345678901234567890", "12345678901234567890.1234567890123456789"],
    ["1e63", "1" + "0".repeat(63)], ["1e-62", "0." + "0".repeat(61) + "1"]
]) assert.equal(format.credits({balance: value}), expected, value);
for (const extreme of ["1e64", "1e-63", "-1e63", "1e999999", "1e-999999"] ) {
    assert.equal(format.credits({balance: extreme}), "See details", extreme);
    assert.equal(format.creditDetail({balance: extreme}), extreme);
}
assert.equal(format.creditDetail({balance: "0E-10"}), "");
const longNonzero = "0." + "0".repeat(98) + "1";
assert.equal(format.credits({balance: longNonzero}), "See details");
assert.equal(format.creditDetail({balance: longNonzero}), longNonzero);
assert.equal(format.credits({balance: "1" + "0".repeat(79) + "e-80"}), "0.1");
assert.equal(format.credits({balance: "0." + "0".repeat(254) + "1"}), "See details");
assert.equal(format.creditDetail({balance: "0." + "0".repeat(254) + "1"}),
    "Provider value exceeds display limit.");
assert.equal(format.credits({balance: null, balanceTruncated: true}), "See details");
assert.equal(format.creditDetail({balance: null, balanceTruncated: true}), "Provider value exceeds display limit.");
assert.equal(format.creditDetail({balance: "1e100", unlimited: true}), "");
assert.equal(format.credits({balance: "", hasCredits: false}), "No credits");
assert.equal(format.credits({balance: null, hasCredits: true}), "Available · amount unavailable");
assert.equal(format.date(null), "Reset time unavailable");
assert.equal(format.date(1700000000), "2023-11-14T22:13:20.000Z", "timestamps are Unix seconds");
assert.equal(format.text("<b>literal</b>"), "<b>literal</b>", "text stays literal for QML PlainText");
assert.equal(format.text("x".repeat(1000)).length, 240);
assert.equal(format.countdown(1700003600, 1700000000000), "in 1h 0m");
assert.equal(format.countdown(1700000000, 1700000000000), "Reset due");
assert.equal(format.weekly({buckets: [{windows: [{label: "Weekly", durationMinutes: 9000, remainingPercent: 90}]}]}),
    null, "only the exact seven-day window is weekly");

const clone = () => JSON.parse(JSON.stringify(snapshot));
const partial = clone();
partial.agents.state = "unavailable";
partial.agents.activeCount = null;
assert.equal(format.validSnapshot(partial), true, "partial activity is supported");
for (const invalid of [
    {...snapshot, version: 99},
    {...snapshot, agents: {...snapshot.agents, activeCount: -1}},
    {...snapshot, agents: {...snapshot.agents, activeCount: 1.5}},
    {...snapshot, agents: {...snapshot.agents, items: [{id: "x", state: "invented"}]}},
    {...snapshot, usage: {...snapshot.usage, buckets: [{id: "bad", windows: null}]}}
]) assert.equal(format.validSnapshot(invalid), false);
const invalidQuota = clone();
invalidQuota.usage.buckets[0].windows[0].remainingPercent = 101;
assert.equal(format.validSnapshot(invalidQuota), false);
const manyBuckets = clone();
manyBuckets.usage.buckets = Array.from({length: 128}, (_, index) => ({
    id: "bucket-" + index, name: "Bucket " + index, windows: [], credits: null
}));
assert.equal(format.validSnapshot(manyBuckets), true, "all 128 bridge-supported buckets are accepted");
manyBuckets.usage.buckets.push({id: "extra", name: "Extra", windows: [], credits: null});
assert.equal(format.validSnapshot(manyBuckets), false);

const tree = [
    {id: "root", parentId: null, title: "Root", state: "working", openTargetId: "root", depth: 0},
    {id: "child", parentId: "root", title: "Child", nickname: "Sample A", state: "working", openTargetId: "root", depth: 1},
    {id: "grandchild", parentId: "child", title: "Grandchild", state: "waiting_input", openTargetId: "root", depth: 2},
    {id: "other", parentId: null, title: "Other", state: "idle", openTargetId: "other", depth: 0}
];
const liveAgents = {state: "fresh", observedAt: 1700000000, activeCount: 2, items: tree};
assert.equal(format.agentCounts(liveAgents), "2 working · 1 waiting · 1 idle");
assert.equal(format.agentCounts({...liveAgents, state: "unavailable"}), "Activity unavailable");
const urgent = {...liveAgents, items: [...tree,
    {id: "approval", state: "waiting_approval"}, {id: "error", state: "error"}]};
assert.equal(format.agentCounts(urgent), "2 working · 2 waiting · 1 idle · 1 errors");
assert.equal(format.agentSnapshot(liveAgents, true), liveAgents);
for (const unavailable of [
    format.agentSnapshot(liveAgents, false),
    format.agentSnapshot({...liveAgents, state: "unavailable", activeCount: null}, true)
]) {
    assert.equal(unavailable.activeCount, null);
    assert.equal(unavailable.state, "unavailable");
    assert.equal(unavailable.items.length, 4);
    assert.equal(unavailable.items[1].nickname, "Sample A");
    for (const item of unavailable.items) {
        assert.equal(item.state, "unavailable", "cached agents must not retain Working badges");
        assert.equal(item.openTargetId, null, "unavailable sessions must not expose Open actions");
    }
}
assert.equal(tree[0].state, "working", "projection never mutates provider input");
console.log("Status format checks passed.");
