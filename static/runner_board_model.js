(function (root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.RunnerBoardModel = api;
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';
  const POLL_MS = 20000, STALE_MS = 60000;
  const columnLabels = { queued: 'Queued', held: 'Held', building: 'Building', reviewing: 'Reviewing', needs_decision: 'Needs decision', merged: 'Merged', stopped: 'Stopped' };
  function key(ticket) { return JSON.stringify([ticket.repo, ticket.id]); }
  function ordinal(position) { const lastTwo = position % 100; return `${position}${lastTwo >= 11 && lastTwo <= 13 ? 'th' : ({ 1: 'st', 2: 'nd', 3: 'rd' }[position % 10] || 'th')}`; }
  // Time-only legacy events cannot identify a calendar day or an elapsed duration.
  function absoluteTime(value) {
    if (typeof value !== 'string' || !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$/.test(value)) return null;
    const time = Date.parse(value); return Number.isFinite(time) ? time : null;
  }
  function sameDay(value, now = new Date()) {
    const time = absoluteTime(value); if (time === null) return false;
    const date = new Date(time);
    return date.getFullYear() === now.getFullYear() && date.getMonth() === now.getMonth() && date.getDate() === now.getDate();
  }
  function elapsed(value, now = Date.now()) {
    const time = absoluteTime(value); if (time === null || time > now) return null;
    const minutes = Math.floor((now - time) / 60000);
    return minutes < 1 ? '<1m' : minutes < 60 ? `${minutes}m` : `${Math.floor(minutes / 60)}h ${minutes % 60}m`;
  }
  function freshness(snapshot, now = Date.now(), failed = false) {
    if (!snapshot || snapshot.available !== true) return 'unavailable';
    const generated = absoluteTime(snapshot.generated_at);
    return failed || generated === null || now - generated > STALE_MS || generated - now > STALE_MS ? 'stale' : 'live';
  }
  function prepare(snapshot, now = new Date()) {
    const groups = { queued: [], held: [], building: [], reviewing: [], needs_decision: [], merged: [], stopped: [] };
    if (!snapshot || snapshot.available !== true) return { groups, mergedToday: 0, running: 0 };
    const tickets = Array.isArray(snapshot.tickets) ? snapshot.tickets : [];
    const lookup = new Map(tickets.map(ticket => [key(ticket), ticket]));
    for (const ticket of tickets) {
      if (ticket.column !== 'merged' && groups[ticket.column]) groups[ticket.column].push(ticket);
    }
    // The source array is ID-sorted; positions require an explicit source field.
    groups.queued = groups.queued.map(ticket => ({ ...ticket, queuePosition: Number.isInteger(ticket.queue_position) && ticket.queue_position > 0 ? ticket.queue_position : null }));
    const seen = new Set();
    for (const merge of Array.isArray(snapshot.merges) ? snapshot.merges : []) {
      if (!sameDay(merge.merged_at, now)) continue;
      const duplicate = JSON.stringify([merge.repo || '', merge.ticket, merge.merged_at]);
      if (seen.has(duplicate)) continue;
      seen.add(duplicate);
      const matches = tickets.filter(ticket => ticket.id === merge.ticket && (!merge.repo || ticket.repo === merge.repo));
      const ticket = merge.repo ? lookup.get(key({ repo: merge.repo, id: merge.ticket })) : matches.length === 1 ? matches[0] : null;
      groups.merged.push({ id: merge.ticket, repo: merge.repo || ticket?.repo || '', column: 'merged', merged_at: merge.merged_at, mergeMessage: merge.message || '', mergeHistory: true });
    }
    groups.merged.sort((a, b) => absoluteTime(b.merged_at) - absoluteTime(a.merged_at));
    return { groups, mergedToday: groups.merged.length, running: tickets.filter(ticket => ticket.running === true).length };
  }
  function accounting(ticket) {
    const codex = /^codex$/i.test(ticket.engine || '');
    // Schema version 1 does not supply accounting. Never estimate dollars from tokens.
    return { codex, rows: ['Input tokens', 'Cache read tokens', 'Output tokens'].map(label => ({ label, value: 'Not reported' })), cost: null };
  }
  function timeline(ticket, observed = []) {
    if (ticket.mergeHistory) return [{ time: ticket.merged_at, label: 'Recorded merge', detail: ticket.mergeMessage || '' }];
    const events = [];
    if (ticket.start_time) events.push({ time: ticket.start_time, label: 'Recorded start', detail: '' });
    if (ticket.last_event_time) events.push({ time: ticket.last_event_time, label: 'Latest recorded event', detail: ticket.phase || columnLabels[ticket.column] || '' });
    return [...events, ...observed.map(event => ({ ...event, label: `Observed on refresh: ${event.label}` }))];
  }
  return { POLL_MS, STALE_MS, columnLabels, key, ordinal, absoluteTime, sameDay, elapsed, freshness, prepare, accounting, timeline };
});
