const test = require('node:test');
const assert = require('node:assert/strict');
const M = require('../static/runner_board_model.js');
const fixture = require('./fixtures/runner_state_v1.json');
const now = new Date('2026-10-09T18:00:00Z');
function snapshot(extra = {}) { return { ...fixture, available: true, ...extra }; }
function ticket(id, column, extra = {}) { return { id, repo: 'example-project', column, ...extra }; }

test('real sanitized v1 fixture preserves all active columns and cannot date a legacy merge', () => {
  const view = M.prepare(snapshot(), now);
  assert.equal(view.groups.held.length, 1);
  assert.equal(view.groups.building.length, 1);
  assert.equal(view.groups.reviewing.length, 1);
  assert.equal(view.groups.stopped.length, 1);
  assert.equal(view.mergedToday, 0);
  assert.equal(view.running, 1);
  assert.equal(M.absoluteTime('16:20:26'), null);
  assert.equal(M.elapsed('16:20:26', now.getTime()), null);
  assert.equal(M.sameDay('16:20:26', now), false);
});

test('queue-position badges use explicit positions without treating held work as queued', () => {
  const tickets = [ticket('second', 'queued', { queue_position: 2 }), ticket('held', 'held'), ticket('first', 'queued', { queue_position: 1 }), ticket('unknown', 'queued')];
  const view = M.prepare(snapshot({ tickets }), now);
  assert.deepEqual(view.groups.queued.map(t => [t.id, t.queuePosition]), [['second', 2], ['first', 1], ['unknown', null]]);
  assert.equal(view.groups.held.length, 1);
  assert.deepEqual([1, 2, 3, 4, 11, 12, 13, 21].map(M.ordinal), ['1st', '2nd', '3rd', '4th', '11th', '12th', '13th', '21st']);
});

test('merged today counts dated history even when the ticket is rerunning and deduplicates identical events', () => {
  const merged = '2026-10-09T17:00:00Z';
  const tickets = [ticket('rerun', 'building', { model: 'new-model', engine: 'codex', pr_url: 'https://github.com/example/repo/pull/2', round: 3 })];
  const merges = [{ ticket: 'rerun', merged_at: merged, message: 'Merged original run' }, { ticket: 'rerun', merged_at: merged }, { ticket: 'old', merged_at: '2026-10-07T17:00:00Z' }];
  const view = M.prepare(snapshot({ tickets, merges }), now);
  assert.equal(view.mergedToday, 1);
  assert.equal(view.groups.building.length, 1);
  assert.equal(view.groups.merged[0].repo, 'example-project');
  assert.equal(view.groups.merged[0].model, undefined);
  assert.equal(view.groups.merged[0].pr_url, undefined);
  assert.equal(view.groups.merged[0].round, undefined);
  assert.deepEqual(M.timeline(view.groups.merged[0]), [{ time: merged, label: 'Recorded merge', detail: 'Merged original run' }]);
});

test('history without a unique matching repository does not borrow current ticket data', () => {
  const view = M.prepare(snapshot({ tickets: [ticket('same', 'building'), ticket('same', 'reviewing', { repo: 'second-project' })], merges: [{ ticket: 'same', merged_at: '2026-10-09T17:00:00Z' }] }), now);
  assert.equal(view.groups.merged[0].repo, '');
  assert.equal(view.mergedToday, 1);
});

test('today respects the viewer calendar day rather than blindly slicing a UTC date', () => {
  const local = new Date(2026, 9, 9, 0, 30);
  assert.equal(M.sameDay(new Date(2026, 9, 9, 0, 5).toISOString(), local), true);
  assert.equal(M.sameDay(new Date(2026, 9, 8, 23, 55).toISOString(), local), false);
  assert.equal(M.sameDay('invalid', local), false);
});

test('freshness distinguishes stale timestamps, failed polling, future clock drift, and unavailable source', () => {
  const fresh = snapshot({ generated_at: now.toISOString() });
  assert.equal(M.freshness(fresh, now.getTime()), 'live');
  assert.equal(M.freshness(fresh, now.getTime(), true), 'stale');
  assert.equal(M.freshness(fresh, now.getTime() + M.STALE_MS + 1), 'stale');
  assert.equal(M.freshness(snapshot({ generated_at: '09:00:00' }), now.getTime()), 'stale');
  assert.equal(M.freshness(fresh, now.getTime() - M.STALE_MS - 1), 'stale');
  assert.equal(M.freshness({ available: false }, now.getTime()), 'unavailable');
  assert.equal(M.prepare({ available: false }, now).groups.building.length, 0);
  assert.equal(M.POLL_MS, 20000);
});

test('Codex accounting never estimates dollar values and missing v1 usage is explicit', () => {
  const codex = M.accounting({ engine: 'Codex', model: 'gpt-6.1-sol', usage: { input_tokens: 100, cost_usd: 999 } });
  assert.equal(codex.codex, true);
  assert.equal(codex.cost, null);
  assert(codex.rows.every(row => row.value === 'Not reported'));
  assert(!JSON.stringify(codex).includes('$'));
  const gateway = M.accounting({ engine: 'omp', model: 'gpt-6.1-sol' });
  assert.equal(gateway.codex, false);
  assert.equal(gateway.cost, null);
});

test('timeline labels only real start/latest records and explicitly identifies observed refresh transitions', () => {
  const run = ticket('live', 'reviewing', { start_time: '09:00:00', last_event_time: '2026-10-09T17:45:00Z', round: 4, phase: 'Reviewer started' });
  const events = M.timeline(run, [{ time: '2026-10-09T17:46:00Z', label: 'Reviewing', detail: 'Round 4' }]);
  assert.equal(events.length, 3);
  assert.equal(events[0].time, '09:00:00');
  assert.equal(events[0].label, 'Recorded start');
  assert.equal(events[1].label, 'Latest recorded event');
  assert.equal(events[2].label, 'Observed on refresh: Reviewing');
  assert(!events.some(event => /Round [123]/.test(event.detail)));
  assert.deepEqual(M.timeline(ticket('queued', 'queued')), []);
});
