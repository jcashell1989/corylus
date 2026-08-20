const test = require("node:test");
const assert = require("node:assert/strict");
const d = require("../static/disposition.js");

test("approve first press stages and does not post", () => {
  assert.deepEqual(d.intent("approve", { staged: null }), { action: "stage", kind: "approve" });
});

test("approve while staged posts", () => {
  const got = d.intent("approve", { staged: "approve" });
  assert.equal(got.action, "post");
  assert.equal(got.kind, "approve");
});

test("Escape path is not a post: staging then a different kind re-stages", () => {
  assert.deepEqual(d.intent("human", { staged: "approve" }), { action: "stage", kind: "human" });
});

test("discard first press stages", () => {
  assert.deepEqual(d.intent("noAction", { staged: null }), { action: "stage", kind: "noAction" });
});

test("discard confirm with note posts", () => {
  const got = d.intent("noAction", { staged: "noAction", note: "discarded" });
  assert.equal(got.action, "post");
  assert.equal(got.note, "discarded");
});

test("remediate without a note still opens the note overlay", () => {
  assert.deepEqual(d.intent("remediate", { staged: null }), { action: "openNote", kind: "remediate" });
});

test("snooze without when still opens the overlay", () => {
  assert.deepEqual(d.intent("snooze", { staged: null }), { action: "openNote", kind: "snooze" });
});

test("confirmNote is empty for approve and discarded for noAction", () => {
  assert.equal(d.confirmNote("approve"), "");
  assert.equal(d.confirmNote("human"), "");
  assert.equal(d.confirmNote("noAction"), "discarded");
});

test("Escape is a clear, never a post", () => {
  assert.deepEqual(d.onEscape(), { action: "clear" });
  assert.notEqual(d.onEscape().action, "post");
});

test("close-overlay: clicking the scrim itself closes it", () => {
  const scrim = {};
  assert.equal(d.closesOverlay(scrim, scrim), true);
});

test("close-overlay: a click bubbling up from card content does not close it (td-8fdc53)", () => {
  const scrim = {};
  const confirmButton = {};
  assert.equal(d.closesOverlay(scrim, confirmButton), false);
});

test("in-flight confirm is ignored, not re-posted (td-8fdc53)", () => {
  const got = d.intent("approve", { staged: "approve", inFlight: true });
  assert.deepEqual(got, { action: "wait" });
});

test("in-flight guard beats staging a fresh kind, not just a repeat", () => {
  const got = d.intent("human", { staged: "approve", inFlight: true });
  assert.deepEqual(got, { action: "wait" });
});

test("once not in flight, confirm posts again (guard releases after settling)", () => {
  const got = d.intent("approve", { staged: "approve", inFlight: false });
  assert.equal(got.action, "post");
});
