const test = require("node:test");
const assert = require("node:assert/strict");
const a = require("../static/attempt_display.js");

test("git attempt with pointers: artifacts fallback offers post-attempt hint", () => {
  const got = a.noArtifactsText({ git_pointers: true, has_attempt: true });
  assert.match(got, /add git pointers/);
});

test("real non-Git attempt (has_attempt, no pointers): labeled non-Git, not missing metadata (td-4952a9)", () => {
  const got = a.noArtifactsText({ git_pointers: false, has_attempt: true });
  assert.match(got, /non-Git task/);
});

test("no hermes:attempt metadata at all: distinct from a real non-Git attempt (td-4952a9)", () => {
  const got = a.noArtifactsText({ git_pointers: false, has_attempt: false });
  assert.match(got, /no attempt metadata/);
  assert.doesNotMatch(got, /non-Git task/);
});

test("log fallback mirrors the same three cases", () => {
  assert.match(a.noLogText({ git_pointers: true, has_attempt: true }), /no run log captured$/);
  assert.match(a.noLogText({ git_pointers: false, has_attempt: true }), /non-Git task and no handoff/);
  assert.match(a.noLogText({ git_pointers: false, has_attempt: false }), /no attempt metadata/);
});
