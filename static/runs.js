(function () {
  'use strict';
  const Model = window.RunsModel;
  const $ = id => document.getElementById(id);
  let snapshot = null, refreshing = false, refreshFailed = false;
  const stateLabels = { running: 'Running', waiting_budget: 'Waiting on gateway budget', timed_out: 'Timed out', finished: 'Finished', failed: 'Failed or died', skipped: 'Skipped', unknown: 'Unknown' };
  function node(tag, text, className) { const item = document.createElement(tag); if (text !== undefined) item.textContent = String(text); if (className) item.className = className; return item; }
  function unknown(value) { return value === null || value === undefined || value === '' ? 'unknown' : String(value); }
  function date(value) { const time = Model.timestamp(value); return Number.isFinite(time) ? new Date(time).toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit', second: '2-digit', timeZoneName: 'short' }) : 'unknown'; }
  function elapsed(seconds) { if (!Number.isFinite(seconds) || seconds < 0) return 'unknown'; if (seconds < 60) return `${Math.floor(seconds)}s`; if (seconds < 3600) return `${Math.floor(seconds / 60)}m ${Math.floor(seconds % 60)}s`; return `${Math.floor(seconds / 3600)}h ${Math.floor(seconds % 3600 / 60)}m`; }
  function since(value) { const time = Model.timestamp(value); return Number.isFinite(time) ? elapsed((Date.now() - time) / 1000) : 'unknown'; }
  function active(run) { return ['running', 'waiting_budget'].includes(run.state); }
  function minutes(seconds) { return seconds === null ? 'unknown' : `${(seconds / 60).toFixed(1)} min`; }
  function points(value) { return value === null ? 'unpointed' : String(value); }
  function badge(state) { return node('span', stateLabels[state] || 'Unknown', `state ${Object.hasOwn(stateLabels, state) ? state : 'unknown'}`); }
  function table(target, headings, rows, empty = 'No recorded runs match this selection.') {
    const container = $(target); container.replaceChildren();
    if (!rows.length) { container.append(node('p', empty, 'empty')); return; }
    const element = node('table'), head = node('thead'), header = node('tr'), body = node('tbody');
    headings.forEach(heading => { const cell = node('th', heading); cell.scope = 'col'; header.append(cell); });
    head.append(header); element.append(head);
    rows.forEach(values => { const row = node('tr'); values.forEach((value, index) => { const cell = node('td', undefined, index ? 'numeric' : ''); if (value instanceof window.Node) cell.append(value); else cell.textContent = unknown(value); row.append(cell); }); body.append(row); });
    element.append(body); container.append(element);
  }
  function jobName(job) { return [unknown(job.ticket), job.label].filter(Boolean).join(' · '); }
  function jobDetail(job) { return `${unknown(job.kind)} · ${unknown(job.model)}`; }
  function addTime(list, label, value, type) {
    list.append(node('dt', label)); const detail = node('dd', value);
    if (type) { detail.dataset.clock = type.kind; detail.dataset.timestamp = type.timestamp || ''; detail.dataset.end = type.end || ''; }
    list.append(detail);
  }
  function renderLive() {
    const target = $('lanes'); target.replaceChildren();
    const runs = new Map((snapshot.runs || []).map(run => [run.id, run]));
    (snapshot.lanes || []).forEach(lane => {
      const card = node('article', undefined, 'lane'), heading = node('div', undefined, 'lane-header');
      heading.append(node('h3', unknown(lane.id)));
      const run = runs.get(lane.current_run_id);
      heading.append(lane.finished ? node('span', 'All jobs finished', 'state') : badge(run?.state || lane.state)); card.append(heading);
      if (run) {
        card.append(node('p', jobName(run), 'job'), node('p', jobDetail(run), 'job-meta'));
        if (lane.finished) { const finalState = node('p', undefined, 'state-note'); finalState.append(badge(run.state)); card.append(finalState); }
        const list = node('dl');
        addTime(list, 'Started', date(run.start_time));
        const seconds = Model.duration(run);
        addTime(list, 'Elapsed', active(run) ? since(run.start_time) : seconds === null ? 'unknown' : elapsed(seconds), active(run) ? { kind: 'elapsed', timestamp: run.start_time } : null);
        addTime(list, 'Since activity', since(run.last_activity), { kind: 'activity', timestamp: run.last_activity });
        addTime(list, 'Current points', points(Model.pointsOf(run)));
        if (run.state === 'waiting_budget') addTime(list, 'Next retry', date(run.next_retry));
        card.append(list);
      } else card.append(node('p', lane.finished ? 'Every listed job has completed.' : 'No current run recorded.', 'muted'));
      const next = node('p', undefined, 'next'); next.append(node('strong', 'Next queued job'));
      next.append(node('span', lane.next_job ? `${jobName(lane.next_job)} · ${jobDetail(lane.next_job)}` : lane.finished ? 'None — lane complete' : 'None recorded')); card.append(next); target.append(card);
    });
    if (!(snapshot.lanes || []).length) target.append(node('p', 'No serial-runner lanes recorded.', 'empty'));
    $('queue-count').textContent = `${(snapshot.queue || []).length} active tickets`;
    table('queue', ['Ticket / job', 'Kind / model', 'State', 'Started', 'Elapsed', 'Since activity', 'Next retry', 'Current points'], (snapshot.queue || []).map(job => {
      const label = node('div', jobName(job));
      const meta = node('div', jobDetail(job));
      const started = date(job.start_time), seconds = Model.duration(job);
      const age = node('span', active(job) ? since(job.start_time) : seconds === null ? 'unknown' : elapsed(seconds)); if (active(job)) { age.dataset.clock = 'elapsed'; age.dataset.timestamp = job.start_time || ''; }
      const activity = node('span', since(job.last_activity)); activity.dataset.clock = 'activity'; activity.dataset.timestamp = job.last_activity || '';
      return [label, meta, badge(job.state), started, age, activity, job.state === 'waiting_budget' ? date(job.next_retry) : '—', points(Model.pointsOf(job))];
    }), 'No active loop5 queue tickets recorded.');
  }
  function currentOptions() { return { window: $('window').value, points: { mode: $('points-mode').value, value: $('points-value').value, min: $('points-min').value, max: $('points-max').value } }; }
  function renderAnalytics() {
    const mode = $('points-mode').value;
    $('value-label').hidden = mode !== 'value'; $('min-label').hidden = mode !== 'range'; $('max-label').hidden = mode !== 'range';
    const normalized = $('view').value === 'normalized'; $('normalized').hidden = !normalized;
    if (!snapshot) return;
    const options = currentOptions(), result = Model.analyze(snapshot.runs || [], options);
    const invalid = mode === 'range' && options.points.min !== '' && options.points.max !== '' && Number(options.points.min) > Number(options.points.max);
    $('selection').textContent = invalid ? 'Minimum points exceeds maximum; no runs match.' : `${result.selected.length} recorded runs selected.${options.window !== 'all' && result.undated ? ` ${result.undated} undated runs cannot be placed in this window; choose all history to include them.` : ''}`;
    const headings = ['Model', 'Finished', 'Timed out', 'Budget blocked', 'Failed / died', 'Other', ...(normalized ? ['Median min / point', 'Finished builds with duration + positive points'] : ['Median duration', 'p90 duration', 'Finished with duration'])];
    table('models', headings, result.models.map(row => [row.model, row.counts.finished, row.counts.timed_out, row.counts.waiting_budget, row.counts.failed, row.counts.other, ...(normalized ? [row.medianMinutesPerPoint === null ? 'unknown' : row.medianMinutesPerPoint.toFixed(2), row.normalizedBuilds] : [minutes(row.medianSeconds), minutes(row.p90Seconds), row.durationCount])]));
    const rate = (count, total, fraction) => `${count} / ${total} (${(100 * fraction).toFixed(1)}%)`;
    table('point-outcomes', ['Model', 'Current points', 'Finished', 'Timed out', 'Budget blocked', 'Failed / died', 'Other'], result.byPoints.map(row => [row.model, points(row.points), ...['finished', 'timed_out', 'waiting_budget', 'failed', 'other'].map(key => rate(row.counts[key], row.total, row.rates[key]))]));
    table('point-rounds', ['Builder model', 'Current points', 'Approved tickets', 'Median rounds', 'p90 rounds', 'Unknown rounds'], result.roundsByPoints.map(row => [row.builder_model, points(row.points), row.approvedTickets, row.medianRounds, row.p90Rounds, row.unknownRounds]), 'No first recorded APPROVE matches this selection.');
    table('verdicts', ['Builder model', 'APPROVE', 'REJECT'], result.verdicts.map(row => [row.builder_model, row.APPROVE, row.REJECT]), 'No recorded judge verdicts match this selection.');
    table('rounds', ['Ticket', 'Builder model', 'Current points', 'Build rounds', 'Recorded build starts'], result.rounds.map(row => [row.ticket, row.builder_model, points(row.points), row.rounds, row.observed_builds]), 'No first recorded APPROVE matches this selection.');
  }
  function render() {
    const messages = [snapshot.available === false ? snapshot.message || 'Loop5 state directory is unavailable.' : '', ...(snapshot.warnings || [])].filter(Boolean);
    $('messages').hidden = !messages.length; $('messages').textContent = messages.join(' ');
    $('updated').textContent = `Last source refresh: ${date(snapshot.refreshed_at)}`;
    renderLive(); renderAnalytics();
  }
  async function refresh() {
    if (refreshing) return;
    refreshing = true; $('refresh').disabled = true;
    const controller = new AbortController(), timeout = setTimeout(() => controller.abort(), 12000);
    try {
      const response = await fetch('/api/runs', { cache: 'no-store', signal: controller.signal, credentials: 'same-origin' });
      if (!response.ok) throw new Error('Refresh failed');
      snapshot = await response.json(); refreshFailed = false; render();
    } catch (_error) {
      refreshFailed = true; $('messages').hidden = false; $('messages').textContent = snapshot ? 'Refresh failed. Showing the last successful snapshot; the source may have changed.' : 'Loop5 run data is unavailable. The viewer remains available from the navigation link.';
      if (!snapshot) { $('lanes').replaceChildren(node('p', 'No run state available.', 'empty')); $('updated').textContent = 'No successful refresh'; }
    } finally { clearTimeout(timeout); refreshing = false; $('refresh').disabled = false; }
  }
  $('refresh').addEventListener('click', refresh);
  $('filters').addEventListener('submit', event => event.preventDefault());
  $('filters').addEventListener('input', renderAnalytics);
  setInterval(() => {
    document.querySelectorAll('[data-clock]').forEach(element => {
      const start = Model.timestamp(element.dataset.timestamp), end = Model.timestamp(element.dataset.end);
      element.textContent = element.dataset.clock === 'elapsed' && Number.isFinite(start) && Number.isFinite(end) ? elapsed((end - start) / 1000) : since(element.dataset.timestamp);
    });
    if (snapshot && !refreshFailed) $('updated').textContent = `Last source refresh: ${date(snapshot.refreshed_at)} · ${since(snapshot.refreshed_at)} ago`;
  }, 1000);
  setInterval(refresh, 15000); refresh();
})();
