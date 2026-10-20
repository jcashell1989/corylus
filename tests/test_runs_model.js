const test = require('node:test');
const assert = require('node:assert/strict');
const model = require('../static/runs_model.js');
const NOW = Date.parse('2026-01-10T12:00:00Z');
// Entirely synthetic records. Durations and counts below are independently hand-counted.
function run(id, ticket, kind, name, state, hour, minutes, extra = {}) {
  const start = new Date(NOW - hour * 3600000).toISOString();
  return { id, ticket, kind, model: name, state, start_time: start, end_time: minutes === null ? null : new Date(Date.parse(start) + minutes * 60000).toISOString(), points: 2, ...extra };
}
const fixture = [
  run('1', 'td-alpha', 'build', 'model-a', 'finished', 12, 10, { round: 1 }),
  run('2', 'td-alpha', 'judge', 'model-b', 'finished', 11, 4, { verdict: 'REJECT', builder_model: 'model-a' }),
  run('3', 'td-alpha', 'build', 'model-a', 'finished', 10, 30, { round: 2 }),
  run('4', 'td-alpha', 'judge', 'model-b', 'finished', 9, 6, { verdict: 'APPROVE', builder_model: 'model-a' }),
  run('5', 'td-beta', 'build', 'model-a', 'timed_out', 8, 75, { points: 5 }),
  run('6', 'td-beta', 'build', 'model-a', 'waiting_budget', 7, null, { points: 5 }),
  run('7', 'td-gamma', 'build', 'model-a', 'failed', 6, 3, { points: null }),
  run('8', 'td-delta', 'build', 'model-a', 'skipped', 5, null, { points: 0 }),
  run('9', 'td-epsilon', 'build', null, 'unknown', 4, null, { points: null }),
  run('10', 'td-zeta', 'build', 'model-b', 'finished', 48, 20, { points: 4 }),
  run('11', 'td-eta', 'judge', 'model-b', 'finished', 3, null, { points: null, verdict: 'APPROVE', builder_model: null }),
  { id: '12', ticket: 'td-older', kind: 'build', model: 'model-a', state: 'unknown', points: null }
];
test('every model summary and point-outcome number matches the fixture hand count', () => {
  const result = model.analyze(fixture, { window: '24h', now: NOW });
  assert.deepEqual(result.models.map(row => [row.model, row.total,
    row.durationCount, row.medianSeconds, row.p90Seconds,
    row.normalizedBuilds, row.medianMinutesPerPoint]), [
    ['model-a', 6, 2, 1200, 1800, 2, 10],
    ['model-b', 3, 2, 300, 360, 0, null],
    ['unknown', 1, 0, null, null, 0, null]
  ]);
  const keys = ['finished', 'timed_out', 'waiting_budget', 'failed', 'other'];
  assert.deepEqual(result.byPoints.map(row => [row.model, row.points, row.total,
    keys.map(key => row.counts[key]), keys.map(key => row.rates[key])]), [
    ['model-a', 0, 1, [0, 0, 0, 0, 1], [0, 0, 0, 0, 1]],
    ['model-a', 2, 2, [2, 0, 0, 0, 0], [1, 0, 0, 0, 0]],
    ['model-a', 5, 2, [0, 1, 1, 0, 0], [0, 0.5, 0.5, 0, 0]],
    ['model-a', null, 1, [0, 0, 0, 1, 0], [0, 0, 0, 1, 0]],
    ['model-b', 2, 2, [2, 0, 0, 0, 0], [1, 0, 0, 0, 0]],
    ['model-b', null, 1, [1, 0, 0, 0, 0], [1, 0, 0, 0, 0]],
    ['unknown', null, 1, [0, 0, 0, 0, 1], [0, 0, 0, 0, 1]]
  ]);
});

test('finite window boundaries distinguish 24h, 7d and 30d exactly', () => {
  const records = [24, 168, 720, 721].map(hours =>
    run(String(hours), 'td-window', 'build', 'model-a', 'finished', hours, 1));
  assert.deepEqual(model.analyze(records, { window: '24h', now: NOW }).selected.map(row => row.id), ['24']);
  assert.deepEqual(model.analyze(records, { window: '7d', now: NOW }).selected.map(row => row.id), ['24', '168']);
  assert.deepEqual(model.analyze(records, { window: '30d', now: NOW }).selected.map(row => row.id), ['24', '168', '720']);
  assert.equal(model.analyze(records, { window: 'all', now: NOW }).selected.length, 4);
});
test('hand counts, median, nearest-rank p90 and unknown attribution', () => {
  const result = model.analyze(fixture, { window: '24h', now: NOW });
  assert.equal(result.selected.length, 10);
  assert.equal(result.undated, 1);
  const a = result.models.find(row => row.model === 'model-a');
  assert.deepEqual(a.counts, { finished: 2, timed_out: 1, waiting_budget: 1, failed: 1, other: 1 });
  assert.equal(a.total, 6); assert.equal(a.durationCount, 2); assert.equal(a.medianSeconds, 1200); assert.equal(a.p90Seconds, 1800);
  assert.equal(a.normalizedBuilds, 2); assert.equal(a.medianMinutesPerPoint, 10);
  const b = result.models.find(row => row.model === 'model-b');
  assert.deepEqual(b.counts, { finished: 3, timed_out: 0, waiting_budget: 0, failed: 0, other: 0 });
  assert.equal(b.durationCount, 2); assert.equal(b.medianSeconds, 300); assert.equal(b.p90Seconds, 360);
  assert.equal(b.medianMinutesPerPoint, null);
  assert.deepEqual(result.models.find(row => row.model === 'unknown').counts, { finished: 0, timed_out: 0, waiting_budget: 0, failed: 0, other: 1 });
  assert.deepEqual(result.verdicts, [{ builder_model: 'model-a', APPROVE: 1, REJECT: 1 }, { builder_model: 'unknown', APPROVE: 1, REJECT: 0 }]);
  assert.deepEqual(result.roundsByPoints, [{ builder_model: 'model-a', points: 2, approvedTickets: 1, knownRounds: [2], unknownRounds: 0, medianRounds: 2, p90Rounds: 2 }, { builder_model: 'unknown', points: null, approvedTickets: 1, knownRounds: [], unknownRounds: 1, medianRounds: null, p90Rounds: null }]);
  assert.deepEqual(result.rounds, [{ ticket: 'td-alpha', builder_model: 'model-a', points: 2, rounds: 2, observed_builds: 2 }, { ticket: 'td-eta', builder_model: 'unknown', points: null, rounds: null, observed_builds: 0 }]);
});
test('windows include only dated recorded events; all includes undated records', () => {
  assert.equal(model.analyze(fixture, { window: '7d', now: NOW }).selected.length, 11);
  assert.equal(model.analyze(fixture, { window: '30d', now: NOW }).selected.length, 11);
  assert.equal(model.analyze(fixture, { window: 'all', now: NOW }).selected.length, 12);
  assert.equal(model.analyze(fixture, { window: 'all', now: NOW }).models.find(row => row.model === 'model-a').counts.other, 2);
  assert.equal(model.inWindow(run('x', 't', 'build', 'm', 'running', -1, null), '24h', NOW), false);
  assert.equal(model.inWindow(run('x', 't', 'build', 'm', 'running', -1, null), 'all', NOW), false);
});
test('single/range/unpointed filters keep missing separate from zero', () => {
  assert.equal(model.analyze(fixture, { window: 'all', now: NOW, points: { mode: 'value', value: '2' } }).selected.length, 4);
  assert.equal(model.analyze(fixture, { window: 'all', now: NOW, points: { mode: 'range', min: '2', max: '4' } }).selected.length, 5);
  assert.equal(model.analyze(fixture, { window: 'all', now: NOW, points: { mode: 'unpointed' } }).selected.length, 4);
  const zero = model.analyze(fixture, { window: 'all', now: NOW, points: { mode: 'value', value: '0' } });
  assert.equal(zero.selected.length, 1); assert.equal(zero.models[0].medianMinutesPerPoint, null);
  assert.equal(model.matchesPoints({ points: undefined }, { mode: 'value', value: 0 }), false);
  assert.equal(model.pointsOf({ points: '2' }), null);
});
test('point outcome denominators and rates are hand-counted per model and point', () => {
  const rows = model.analyze(fixture, { window: '24h', now: NOW }).byPoints;
  const a2 = rows.find(row => row.model === 'model-a' && row.points === 2);
  assert.equal(a2.total, 2); assert.deepEqual(a2.rates, { finished: 1, timed_out: 0, waiting_budget: 0, failed: 0, other: 0 });
  const a5 = rows.find(row => row.model === 'model-a' && row.points === 5);
  assert.equal(a5.total, 2); assert.deepEqual(a5.rates, { finished: 0, timed_out: 0.5, waiting_budget: 0.5, failed: 0, other: 0 });
  const unpointed = rows.find(row => row.model === 'model-a' && row.points === null);
  assert.equal(unpointed.total, 1); assert.equal(unpointed.counts.failed, 1);
});
test('build rounds use all history and first recorded approval; unknown timestamps remain unknown', () => {
  const records = [run('a', 't', 'build', 'model-a', 'finished', 50, 10, { round: 1 }), run('b', 't', 'build', 'model-a', 'finished', 10, 20, { round: 2 }), run('c', 't', 'judge', 'model-b', 'finished', 9, 2, { verdict: 'APPROVE', builder_model: 'model-a' }), run('d', 't', 'judge', 'model-b', 'finished', 8, 2, { verdict: 'APPROVE', builder_model: 'model-a' })];
  const result = model.analyze(records, { window: '24h', now: NOW });
  assert.equal(result.rounds.length, 1); assert.equal(result.rounds[0].rounds, 2);
  assert.equal(model.analyze([...records, { ticket: 't', kind: 'build', state: 'unknown' }], { window: '24h', now: NOW }).rounds[0].rounds, null);
});
test('duration never fabricates a finish; malformed and negative values stay unknown', () => {
  assert.equal(model.duration({ start_time: '2026-01-01T00:00:00Z' }), null);
  assert.equal(model.duration({ start_time: 'bad', end_time: 'bad' }), null);
  assert.equal(model.duration({ duration_seconds: -3 }), null);
  assert.equal(model.duration({ duration_seconds: 0 }), 0);
  assert.equal(model.quantile([], 0.9), null);
});

test('round aggregates use independently counted ticket rounds within current points', () => {
  const records = [
    run('a1', 'one', 'build', 'builder', 'finished', 15, 10, { round: 1 }),
    run('a2', 'one', 'judge', 'judge', 'finished', 14, 2, { verdict: 'APPROVE', builder_model: 'builder' }),
    run('b1', 'three', 'build', 'builder', 'finished', 13, 10, { round: 1 }),
    run('b2', 'three', 'build', 'builder', 'finished', 12, 10, { round: 2 }),
    run('b3', 'three', 'build', 'builder', 'finished', 11, 10, { round: 3 }),
    run('b4', 'three', 'judge', 'judge', 'finished', 10, 2, { verdict: 'APPROVE', builder_model: 'builder' })
  ];
  assert.deepEqual(model.analyze(records, { window: 'all', now: NOW }).roundsByPoints, [{ builder_model: 'builder', points: 2, approvedTickets: 2, knownRounds: [1, 3], unknownRounds: 0, medianRounds: 2, p90Rounds: 3 }]);
});

test('budget retries retain one explicit build round and missing round metadata stays unknown', () => {
  const records = [
    run('a1', 'retry', 'build', 'builder', 'waiting_budget', 15, 1, { round: 1 }),
    run('a2', 'retry', 'build', 'builder', 'finished', 14, 10, { round: 1 }),
    run('a3', 'retry', 'judge', 'judge', 'finished', 13, 2, { verdict: 'APPROVE', builder_model: 'builder' })
  ];
  const result = model.analyze(records, { window: 'all', now: NOW });
  assert.equal(result.rounds[0].rounds, 1); assert.equal(result.rounds[0].observed_builds, 2);
  delete records[0].round;
  const unknown = model.analyze(records, { window: 'all', now: NOW });
  assert.equal(unknown.rounds[0].rounds, null); assert.equal(unknown.roundsByPoints[0].unknownRounds, 1);
});
