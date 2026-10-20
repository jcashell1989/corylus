(function (root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.RunsModel = api;
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';
  const WINDOWS = { '24h': 86400000, '7d': 604800000, '30d': 2592000000 };
  const OUTCOMES = ['finished', 'timed_out', 'waiting_budget', 'failed', 'other'];
  function timestamp(value) { return typeof value === 'string' && value ? Date.parse(value) : NaN; }
  function pointsOf(run) { return typeof run.points === 'number' && Number.isFinite(run.points) && run.points >= 0 ? run.points : null; }
  function matchesPoints(run, filter = {}) {
    const points = pointsOf(run);
    if (filter.mode === 'unpointed') return points === null;
    if (filter.mode === 'value') return points !== null && points === Number(filter.value);
    if (filter.mode === 'range') return points !== null && (filter.min === '' || filter.min === null || filter.min === undefined || points >= Number(filter.min)) && (filter.max === '' || filter.max === null || filter.max === undefined || points <= Number(filter.max));
    return true;
  }
  function outcome(run) { return OUTCOMES.includes(run.state) && run.state !== 'other' ? run.state : 'other'; }
  function duration(run) {
    if (typeof run.duration_seconds === 'number' && Number.isFinite(run.duration_seconds) && run.duration_seconds >= 0) return run.duration_seconds;
    const start = timestamp(run.start_time), end = timestamp(run.end_time);
    return Number.isFinite(start) && Number.isFinite(end) && end >= start ? (end - start) / 1000 : null;
  }
  function quantile(values, p) {
    if (!values.length) return null;
    const sorted = [...values].sort((a, b) => a - b);
    if (p === 0.5) { const middle = Math.floor(sorted.length / 2); return sorted.length % 2 ? sorted[middle] : (sorted[middle - 1] + sorted[middle]) / 2; }
    return sorted[Math.max(0, Math.ceil(p * sorted.length) - 1)];
  }
  function counts() { return Object.fromEntries(OUTCOMES.map(key => [key, 0])); }
  function inWindow(run, window, now) {
    const time = timestamp(run.start_time || run.end_time);
    if (!WINDOWS[window]) return !Number.isFinite(time) || time <= now;
    // Events without a recorded timestamp cannot be assigned to a finite window.
    return Number.isFinite(time) && time >= now - WINDOWS[window] && time <= now;
  }
  function analyze(runs, options = {}) {
    const now = options.now ?? Date.now();
    const selected = runs.filter(run => inWindow(run, options.window || '24h', now) && matchesPoints(run, options.points));
    const models = new Map(), verdicts = new Map(), byPoints = new Map();
    selected.forEach(run => {
      const name = run.model || 'unknown';
      if (!models.has(name)) models.set(name, { model: name, counts: counts(), durations: [], minutesPerPoint: [], normalizedBuilds: 0 });
      const row = models.get(name); row.counts[outcome(run)]++;
      const seconds = duration(run), points = pointsOf(run);
      if (run.state === 'finished' && seconds !== null) {
        row.durations.push(seconds);
        if (run.kind === 'build' && points > 0) { row.minutesPerPoint.push(seconds / 60 / points); row.normalizedBuilds++; }
      }
      if (run.kind === 'judge' && ['APPROVE', 'REJECT'].includes(run.verdict)) {
        const builder = run.builder_model || 'unknown';
        if (!verdicts.has(builder)) verdicts.set(builder, { builder_model: builder, APPROVE: 0, REJECT: 0 });
        verdicts.get(builder)[run.verdict]++;
      }
      const key = `${name}\0${points === null ? 'unpointed' : points}`;
      if (!byPoints.has(key)) byPoints.set(key, { model: name, points, counts: counts(), total: 0 });
      byPoints.get(key).counts[outcome(run)]++; byPoints.get(key).total++;
    });
    // Count distinct explicit round values; repeated attempts within a round count once.
    // Use all supplied history so changing the window does not truncate build rounds.
    const rounds = [], tickets = new Set(selected.filter(run => run.kind === 'judge' && run.verdict === 'APPROVE').map(run => run.ticket));
    tickets.forEach(ticket => {
      const approves = runs.filter(run => run.ticket === ticket && run.kind === 'judge' && run.verdict === 'APPROVE' && Number.isFinite(timestamp(run.end_time || run.start_time))).sort((a, b) => timestamp(a.end_time || a.start_time) - timestamp(b.end_time || b.start_time));
      const approval = approves[0];
      if (!approval || !selected.includes(approval)) return;
      const end = timestamp(approval.end_time || approval.start_time);
      const builds = runs.filter(run => run.ticket === ticket && run.kind === 'build' && Number.isFinite(timestamp(run.start_time)) && timestamp(run.start_time) <= end);
      const hasUndatedBuilds = runs.some(run => run.ticket === ticket && run.kind === 'build' && !Number.isFinite(timestamp(run.start_time)));
      const completeRounds = builds.length > 0 && !hasUndatedBuilds && builds.every(run => Number.isInteger(run.round) && run.round > 0);
      const roundCount = completeRounds ? new Set(builds.map(run => run.round)).size : null;
      rounds.push({ ticket, builder_model: approval.builder_model || 'unknown', points: pointsOf(approval), rounds: roundCount, observed_builds: builds.length });
    });
    const roundGroups = new Map();
    rounds.forEach(row => {
      const key = `${row.builder_model}\0${row.points === null ? 'unpointed' : row.points}`;
      if (!roundGroups.has(key)) roundGroups.set(key, { builder_model: row.builder_model, points: row.points, approvedTickets: 0, knownRounds: [], unknownRounds: 0 });
      const group = roundGroups.get(key); group.approvedTickets++;
      if (row.rounds === null) group.unknownRounds++; else group.knownRounds.push(row.rounds);
    });
    return {
      selected, models: [...models.values()].sort((a, b) => a.model.localeCompare(b.model)).map(row => ({ ...row, total: Object.values(row.counts).reduce((a, b) => a + b, 0), durationCount: row.durations.length, medianSeconds: quantile(row.durations, 0.5), p90Seconds: quantile(row.durations, 0.9), medianMinutesPerPoint: quantile(row.minutesPerPoint, 0.5) })),
      verdicts: [...verdicts.values()].sort((a, b) => a.builder_model.localeCompare(b.builder_model)),
      byPoints: [...byPoints.values()].map(row => ({ ...row, rates: Object.fromEntries(OUTCOMES.map(key => [key, row.counts[key] / row.total])) })).sort((a, b) => a.model.localeCompare(b.model) || (a.points ?? Infinity) - (b.points ?? Infinity)),
      roundsByPoints: [...roundGroups.values()].sort((a, b) => a.builder_model.localeCompare(b.builder_model) || (a.points ?? Infinity) - (b.points ?? Infinity)).map(row => ({ ...row, medianRounds: quantile(row.knownRounds, 0.5), p90Rounds: quantile(row.knownRounds, 0.9) })),
      rounds: rounds.sort((a, b) => a.ticket.localeCompare(b.ticket)),
      undated: runs.filter(run => !Number.isFinite(timestamp(run.start_time || run.end_time)) && matchesPoints(run, options.points)).length
    };
  }
  return { analyze, duration, inWindow, matchesPoints, outcome, pointsOf, quantile, timestamp };
});
