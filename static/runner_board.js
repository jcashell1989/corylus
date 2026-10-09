(() => {
  'use strict';
  const M = window.RunnerBoardModel;
  const state = { snapshot: null, failure: '', selected: null, timer: null, busy: false, heldOpen: false, observations: new Map(), tickets: new Map(), options: {}, pane: null };
  function el(tag, className, text) { const node = document.createElement(tag); if (className) node.className = className; if (text !== undefined) node.textContent = text; return node; }
  function detailFor(ticket) { return state.options.lookupTicket?.(ticket.repo, ticket.id) || state.tickets.get(M.key(ticket)) || null; }
  function titleFor(ticket) { return detailFor(ticket)?.title || 'Title unavailable'; }
  function prettyTime(value) { const time = M.absoluteTime(value); return time === null ? value ? `${value} (date unavailable)` : 'Unavailable' : new Date(time).toLocaleString(); }
  function selectionKey(ticket) { return `${M.key(ticket)}${ticket.mergeHistory ? `:${ticket.merged_at}` : ''}`; }
  function link(href, text) { const node = el('a', 'runner-link', text); node.href = href; node.target = '_blank'; node.rel = 'noopener noreferrer'; return node; }
  function safePr(value) { try { const url = new URL(value); return url.protocol === 'https:' && url.host === 'github.com' && !url.username && !url.password && !url.search && !url.hash && /^\/[^/]+\/[^/]+\/pull\/[1-9]\d*\/?$/.test(url.pathname) ? url.href : null; } catch { return null; } }
  function allCards(view) { return Object.values(view.groups).flat(); }
  function card(ticket) {
    const key = selectionKey(ticket), button = el('button', `runner-card${state.selected === key ? ' selected' : ''}`);
    button.type = 'button'; button.dataset.runnerKey = key; button.setAttribute('aria-pressed', String(state.selected === key));
    button.setAttribute('aria-label', `${ticket.id}: ${titleFor(ticket)}. ${M.columnLabels[ticket.column]}. Open runner details.`);
    const top = el('span', 'runner-card-top'); top.append(el('span', '', ticket.id), el('span', 'muted', ticket.repo || 'Repository unavailable'));
    button.append(top);
    if (ticket.queuePosition) button.append(el('span', 'runner-queue-badge', ticket.queuePosition === 1 ? 'Next up' : M.ordinal(ticket.queuePosition)));
    button.append(el('span', 'runner-card-title', titleFor(ticket)));
    if (ticket.column === 'held' && ticket.hold_reason) button.append(el('span', 'runner-reason', ticket.hold_reason));
    if (ticket.column === 'needs_decision') {
      const blockers = ticket.blockers || [];
      button.append(el('span', 'runner-reason', blockers.length ? blockers[0] : 'Decision details unavailable'));
      if (blockers.length > 1) button.append(el('span', 'muted', `+${blockers.length - 1} more blockers`));
    }
    const model = ticket.model ? `${ticket.model}${ticket.engine ? ` · ${ticket.engine}` : ''}` : ticket.engine || 'Model unavailable', age = M.elapsed(ticket.mergeHistory ? ticket.merged_at : ticket.start_time);
    button.append(el('span', 'runner-card-meta', ticket.mergeHistory ? `Merged${age ? ` · ${age} ago` : ''}` : `${model}${age ? ` · ${age}` : ''}`));
    if (!ticket.mergeHistory && ticket.round) button.append(el('span', 'muted', `Round ${ticket.round}${ticket.running ? ' · Running' : ''}`));
    if (!ticket.mergeHistory && ticket.last_event_time) button.append(el('span', 'muted', `Latest: ${prettyTime(ticket.last_event_time)}`));
    if (ticket.column === 'reviewing' && ticket.reviewed_head) button.append(el('span', 'muted', `Reviewed ${ticket.reviewed_head.slice(0, 8)}`));
    if (ticket.column === 'stopped' && ticket.phase) button.append(el('span', 'runner-reason', ticket.phase));
    const pr = safePr(ticket.pr_url); if (pr) button.append(el('span', 'runner-pr-label', `PR #${new URL(pr).pathname.split('/').pop()}`));
    button.addEventListener('click', () => { state.selected = key; render(); state.pane.querySelector('.runner-drawer h3')?.focus(); });
    return button;
  }
  function cards(container, entries, empty = 'No tickets') { container.append(...entries.map(card)); if (!entries.length) container.append(el('p', 'runner-empty muted', empty)); }
  function column(label, entries, className = '') {
    const section = el('section', `runner-column ${className}`); section.setAttribute('aria-label', label);
    section.append(el('h3', '', `${label} (${entries.length})`)); const list = el('div', 'runner-card-list'); cards(list, entries); section.append(list); return section;
  }
  function row(list, label, value) { list.append(el('dt', '', label), el('dd', '', value === undefined || value === null || value === '' ? 'Unavailable' : String(value))); }
  function drawer(ticket) {
    const aside = el('aside', 'runner-drawer'); aside.setAttribute('aria-label', 'Runner ticket details');
    const close = el('button', 'runner-drawer-close', 'Close details'); close.type = 'button'; close.dataset.runnerAction = 'close'; close.addEventListener('click', () => { const key = state.selected; state.selected = null; render(); [...state.pane.querySelectorAll('[data-runner-key]')].find(node => node.dataset.runnerKey === key)?.focus(); });
    aside.append(close, el('p', 'muted', `${ticket.id} · ${ticket.repo || 'Repository unavailable'}`));
    const title = el('h3', '', titleFor(ticket)); title.tabIndex = -1; aside.append(title);
    aside.append(el('p', '', `${M.columnLabels[ticket.column]}${!ticket.mergeHistory && ticket.round ? ` · Round ${ticket.round}` : ''}`));
    const actions = el('div', 'runner-drawer-actions'), pr = safePr(ticket.pr_url); if (pr) actions.append(link(pr, 'Open PR'));
    if (detailFor(ticket) && state.options.openTicket) {
      const open = el('button', '', 'Open in td view'); open.type = 'button'; open.dataset.runnerAction = 'open-ticket'; open.addEventListener('click', () => state.options.openTicket(ticket.repo, ticket.id)); actions.append(open);
    } else actions.append(el('span', 'muted', 'Ticket view unavailable for this repository'));
    aside.append(actions);
    if (ticket.column === 'needs_decision') {
      aside.append(el('h4', '', 'Needs decision'));
      const blockers = el('ul', 'runner-blockers'); (ticket.blockers?.length ? ticket.blockers : ['Decision details unavailable']).forEach(blocker => blockers.append(el('li', '', blocker))); aside.append(blockers);
    }
    aside.append(el('h4', '', 'Timeline'));
    const timeline = el('ol', 'runner-timeline');
    const events = M.timeline(ticket, state.observations.get(M.key(ticket)) || []);
    for (const event of events) { const item = el('li'); item.append(el('time', 'muted', prettyTime(event.time)), el('strong', '', event.label)); if (event.detail) item.append(el('span', '', event.detail)); timeline.append(item); }
    if (!events.length) aside.append(el('p', 'muted', 'Event times unavailable')); else aside.append(timeline);
    aside.append(el('p', 'runner-note muted', ticket.mergeHistory ? 'Only the dated merge record is available. Model, PR, and usage details for this historical run are not reported.' : 'The source provides the start and latest event. Refresh observations are recorded only while this page is open. Earlier round history is unavailable.'));
    aside.append(el('h4', '', 'Details')); const details = el('dl', 'runner-details');
    row(details, 'Repository', ticket.repo); row(details, 'Queue name', ticket.name);
    if (!ticket.mergeHistory) { row(details, 'Phase', ticket.phase); row(details, 'Started', prettyTime(ticket.start_time)); row(details, 'Latest event', prettyTime(ticket.last_event_time)); row(details, 'Reviewed commit', ticket.reviewed_head); row(details, 'Hold reason', ticket.hold_reason); }
    else row(details, 'Merged', prettyTime(ticket.merged_at));
    const source = detailFor(ticket); if (source?.description) { row(details, 'Description', source.description); }
    if (source?.acceptance) row(details, 'Acceptance', source.acceptance);
    aside.append(details, el('h4', '', 'Model & usage')); const usage = el('dl', 'runner-details');
    if (ticket.mergeHistory) row(usage, 'Usage', 'Not reported for this historical merge');
    else { row(usage, 'Model', ticket.model); row(usage, 'Harness', ticket.engine); const accounting = M.accounting(ticket); accounting.rows.forEach(item => row(usage, item.label, item.value)); if (!accounting.codex) row(usage, 'Cost', accounting.cost || 'Not reported'); }
    aside.append(usage); return aside;
  }
  function render() {
    if (!state.pane) return;
    const active = document.activeElement, focusedKey = active?.dataset.runnerKey, focusedAction = active?.dataset.runnerAction;
    const view = M.prepare(state.snapshot), freshness = M.freshness(state.snapshot, Date.now(), Boolean(state.failure));
    const heading = el('div', 'runner-heading'), intro = el('div'); intro.append(el('h2', '', 'Runner board'), el('p', 'muted', 'All runner repositories · Read-only · Refreshes every 20 seconds'));
    const status = el('span', `runner-live ${freshness}`, freshness === 'live' ? 'Live' : freshness === 'stale' ? 'Stale snapshot' : 'Unavailable'); status.setAttribute('role', 'status'); heading.append(intro, status);
    const fragment = document.createDocumentFragment(); fragment.append(heading);
    if (state.failure || !state.snapshot?.available) { const warning = el('p', 'runner-warning', state.failure ? `${state.failure}${state.snapshot ? ' Showing the last successful snapshot.' : ''}` : 'Runner state is unavailable. Configure a local state source for the viewer.'); warning.setAttribute('role', 'status'); fragment.append(warning); }
    if (state.snapshot) fragment.append(el('p', 'runner-summary muted', `Snapshot: ${prettyTime(state.snapshot.generated_at)} · ${view.running} running · ${view.groups.queued.length} queued · ${view.groups.held.length} held · ${view.mergedToday} merged today`));
    if (freshness === 'stale' && !state.failure) fragment.append(el('p', 'runner-warning', 'The source snapshot is older than one minute or its timestamp is unavailable. Counts may be out of date.'));
    if (state.snapshot?.available) {
      const selected = allCards(view).find(ticket => selectionKey(ticket) === state.selected); if (!selected) state.selected = null;
      const layout = el('div', `runner-layout${state.selected ? ' has-drawer' : ''}`), board = el('div', 'runner-columns');
      const queued = column('Queued', view.groups.queued), held = el('details', 'runner-held'); held.open = state.heldOpen;
      if (view.groups.queued.some(ticket => !ticket.queuePosition)) queued.append(el('p', 'runner-note muted', 'Queue order is not reported by this source. Cards follow source order.'));
      held.append(el('summary', '', `Held (${view.groups.held.length})`)); const heldList = el('div', 'runner-card-list'); cards(heldList, view.groups.held, 'No held tickets'); held.append(heldList); held.addEventListener('toggle', () => { state.heldOpen = held.open; }); queued.append(held);
      const merged = column('Merged today', view.groups.merged), stopped = el('div', 'runner-stopped'); stopped.append(el('h4', '', `Stopped (${view.groups.stopped.length})`)); cards(stopped, view.groups.stopped, 'No stopped tickets'); merged.append(stopped);
      if (state.snapshot.merges.some(merge => M.absoluteTime(merge.merged_at) === null)) merged.append(el('p', 'runner-note muted', 'Merge records without dates are excluded from today’s total.'));
      board.append(queued, column('Building', view.groups.building), column('Reviewing', view.groups.reviewing), column('Needs decision', view.groups.needs_decision, 'runner-decision'), merged); layout.append(board);
      if (selected) layout.append(drawer(selected));
      fragment.append(layout);
    }
    state.pane.replaceChildren(fragment);
    if (focusedKey) [...state.pane.querySelectorAll('[data-runner-key]')].find(node => node.dataset.runnerKey === focusedKey)?.focus({ preventScroll: true });
    if (focusedAction) [...state.pane.querySelectorAll('[data-runner-action]')].find(node => node.dataset.runnerAction === focusedAction)?.focus({ preventScroll: true });
  }
  function observe(next) {
    if (!state.snapshot) return;
    const current = new Set((next.tickets || []).map(M.key));
    for (const key of state.observations.keys()) if (!current.has(key)) state.observations.delete(key);
    const previous = new Map((state.snapshot.tickets || []).map(ticket => [M.key(ticket), ticket]));
    for (const ticket of next.tickets || []) {
      const old = previous.get(M.key(ticket)); if (!old || old.column === ticket.column && old.round === ticket.round && old.phase === ticket.phase) continue;
      const observations = state.observations.get(M.key(ticket)) || [];
      observations.push({ time: new Date().toISOString(), label: M.columnLabels[ticket.column] || ticket.column, detail: `${ticket.round ? `Round ${ticket.round} · ` : ''}${ticket.phase || ''}` });
      state.observations.set(M.key(ticket), observations.slice(-30));
    }
  }
  async function refresh() {
    if (state.busy) return; state.busy = true;
    const controller = new AbortController(), timeout = setTimeout(() => controller.abort(), 10000);
    try {
      const response = await fetch('/api/runner', { cache: 'no-store', signal: controller.signal });
      if (!response.ok) throw new Error('Runner refresh failed.');
      const snapshot = await response.json();
      if (snapshot.available !== true) throw new Error('Runner state is unavailable.');
      if (snapshot.schema_version !== 1 || !Array.isArray(snapshot.tickets) || !Array.isArray(snapshot.merges)) throw new Error('Runner state has an unsupported schema.');
      observe(snapshot); state.snapshot = snapshot; state.failure = '';
    } catch (error) { state.failure = error.name === 'AbortError' ? 'Runner refresh timed out.' : error instanceof SyntaxError ? 'Runner service returned an invalid response.' : error.message; }
    finally { clearTimeout(timeout); state.busy = false; render(); }
  }
  function updateTickets(project, data) {
    const repo = typeof project === 'string' ? project : project?.repo || project?.name || project?.id;
    for (const [key, ticket] of state.tickets) if (ticket.repo === repo) state.tickets.delete(key);
    for (const ticket of data?.tickets || []) state.tickets.set(M.key({ repo, id: ticket.id }), { ...ticket, repo });
    render();
  }
  function initialize(options = {}) {
    if (!M) throw new Error('RunnerBoardModel must load before RunnerBoard.');
    state.options = options; state.pane = document.getElementById('runner-board-pane'); if (!state.pane) return;
    clearInterval(state.timer); render(); refresh(); state.timer = setInterval(refresh, M.POLL_MS);
  }
  window.RunnerBoard = { initialize, updateTickets, refresh, setVisible(visible) { if (state.pane) state.pane.hidden = !visible; if (visible) render(); }, stop() { clearInterval(state.timer); state.timer = null; } };
})();
