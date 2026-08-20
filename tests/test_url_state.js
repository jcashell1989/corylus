const test = require("node:test");
const assert = require("node:assert/strict");
const url = require("../static/url_state.js");

test("empty search restores defaults", () => {
  const p = url.parse("");
  assert.equal(p.view, "home");
  assert.equal(p.task, null);
  assert.equal(p.cursor, 0);
  assert.equal(p.filter, "all");
  assert.equal(p.window, "7d");
  assert.equal(p.akind, "all");
  assert.equal(p.lane, "all");
  assert.equal(p.model, "all");
  assert.deepEqual(p.open, url.DEFAULT_OPEN);
  assert.equal(p.human, null);
  assert.equal(p.blocked, null);
});

test("invalid view, filter, task, cursor, human fall back", () => {
  const p = url.parse("?view=nope&filter=zzz&task=abc&cursor=-2&human=0&window=nope&akind=x&lane=y&model=");
  assert.equal(p.view, "home");
  assert.equal(p.filter, "all");
  assert.equal(p.window, "7d");
  assert.equal(p.akind, "all");
  assert.equal(p.lane, "all");
  assert.equal(p.model, "all");
  assert.equal(p.task, null);
  assert.equal(p.cursor, 0);
  assert.equal(p.human, null);
  assert.equal(p.blocked, null);
});

test("unknown keys are ignored", () => {
  const p = url.parse("?view=queue&bogus=1&debug=true");
  assert.equal(p.view, "queue");
  assert.equal(p.filter, "all");
});

test("open drops unknown section keys and starts from all-closed", () => {
  const p = url.parse("?open=foo,description,log");
  assert.equal(p.open.description, true);
  assert.equal(p.open.log, true);
  assert.equal(p.open.attempt, false);
  assert.equal(p.open.history, false);
  assert.equal(p.open.foo, undefined);
});

test("serialize omits default home/all/cursor 0", () => {
  assert.equal(url.serialize({
    view: "home",
    task: null,
    cursor: 0,
    filter: "all",
    open: url.DEFAULT_OPEN,
    human: null,
    blocked: null
  }), "");
});

test("roundtrip review + task + filter + cursor + human", () => {
  const src = {
    view: "review",
    task: 52,
    cursor: 3,
    filter: "thin",
    open: url.DEFAULT_OPEN,
    human: null
  };
  const q = url.serialize(src);
  assert.equal(q, "view=review&task=52&cursor=3&filter=thin");
  const p = url.parse("?" + q);
  assert.equal(p.view, src.view);
  assert.equal(p.task, src.task);
  assert.equal(p.cursor, src.cursor);
  assert.equal(p.filter, src.filter);
});

test("roundtrip custom open sections including all-collapsed", () => {
  const open = {
    description: false,
    attempt: false,
    artifacts: false,
    log: false,
    history: false,
    meta: false
  };
  const q = url.serialize({ view: "review", open: open });
  assert.match(q, /open=/);
  const p = url.parse("?" + q);
  assert.deepEqual(p.open, open);
});

test("apply writes parsed fields onto an existing state object", () => {
  const state = { view: "home", viewing: null, cursor: 0, filter: "all", open: {}, humanOpen: 9, toast: "keep" };
  url.apply(state, url.parse("?view=human&human=8&filter=high"));
  assert.equal(state.view, "human");
  assert.equal(state.humanOpen, 8);
  assert.equal(state.filter, "high");
  assert.equal(state.toast, "keep");
});

test("snapshot reads the live state fields used in the URL", () => {
  const snap = url.snapshot({
    view: "queue",
    viewing: 12,
    cursor: 1,
    filter: "low",
    open: url.DEFAULT_OPEN,
    humanOpen: null,
    blockedOpen: null,
    toast: "ignored"
  });
  assert.deepEqual(snap, {
    view: "queue",
    task: 12,
    cursor: 1,
    filter: "low",
    window: "7d",
    akind: "all",
    lane: "all",
    model: "all",
    open: url.DEFAULT_OPEN,
    human: null,
    blocked: null
  });
});

test("a history stack restores prior view state on back and forward", () => {
  const stack = [""];
  let i = 0;
  function go(partial) {
    const q = url.serialize(Object.assign({
      view: "home", task: null, cursor: 0, filter: "all",
      open: url.DEFAULT_OPEN, human: null, blocked: null
    }, partial));
    stack.splice(i + 1);
    stack.push(q);
    i = stack.length - 1;
    return url.parse(stack[i]);
  }
  function back() { if (i > 0) i -= 1; return url.parse(stack[i]); }
  function forward() { if (i < stack.length - 1) i += 1; return url.parse(stack[i]); }

  go({ view: "queue" });
  go({ view: "review", task: 52, filter: "thin" });
  const prev = back();
  assert.equal(prev.view, "queue");
  assert.equal(prev.task, null);
  const again = forward();
  assert.equal(again.view, "review");
  assert.equal(again.task, 52);
  assert.equal(again.filter, "thin");
  const home = back();
  assert.equal(home.view, "queue");
  const start = back();
  assert.equal(start.view, "home");
});

test("roundtrip window akind lane model", () => {
  const src = {
    view: "timeline",
    task: null,
    cursor: 0,
    filter: "all",
    window: "24h",
    akind: "attempt",
    lane: "worker",
    model: "openai/gpt-5.6-luna",
    open: url.DEFAULT_OPEN,
    human: null
  };
  const q = url.serialize(src);
  const p = url.parse("?" + q);
  assert.equal(p.view, "timeline");
  assert.equal(p.window, "24h");
  assert.equal(p.akind, "attempt");
  assert.equal(p.lane, "worker");
  assert.equal(p.model, "openai/gpt-5.6-luna");
});

test("attempt row serializes review task", () => {
  const q = url.serialize({
    view: "review", task: 74, cursor: 0, filter: "all",
    window: "7d", akind: "all", lane: "all", model: "all",
    open: url.DEFAULT_OPEN, human: null, blocked: null
  });
  assert.equal(q, "view=review&task=74");
});

test("applyMonitorChip sets window akind lane model", () => {
  const s = { window: "7d", akind: "all", lane: "all", model: "all" };
  assert.equal(url.applyMonitorChip(s, "window:24h"), true);
  assert.equal(s.window, "24h");
  assert.equal(url.applyMonitorChip(s, "akind:judge"), true);
  assert.equal(s.akind, "judge");
  assert.equal(url.applyMonitorChip(s, "lane:worker"), true);
  assert.equal(s.lane, "worker");
  assert.equal(url.applyMonitorChip(s, "model:z-ai/glm-5.2"), true);
  assert.equal(s.model, "z-ai/glm-5.2");
});

test("applyMonitorChip rejects unknown key and bad window", () => {
  const s = { window: "7d", akind: "all", lane: "all", model: "all" };
  assert.equal(url.applyMonitorChip(s, "nope:x"), false);
  assert.equal(url.applyMonitorChip(s, "window:nope"), false);
  assert.equal(s.window, "7d");
});

test("roundtrip blocked view and expanded row", () => {
  const q = url.serialize({
    view: "blocked", blocked: 8, open: url.DEFAULT_OPEN
  });
  assert.equal(q, "view=blocked&blocked=8");
  const state = {
    view: "home", viewing: null, cursor: 0, filter: "all",
    open: {}, humanOpen: null, blockedOpen: null
  };
  url.apply(state, url.parse("?" + q));
  assert.equal(state.view, "blocked");
  assert.equal(state.blockedOpen, 8);
});
