(() => {
  'use strict';
  const $ = id => document.getElementById(id), ns = 'http://www.w3.org/2000/svg', FlowModel = window.FlowModel;
  const demo = new URLSearchParams(location.search).get('demo') === '1';
  const state = { data: null, model: null, selected: demo ? 'td-103' : null, statuses: null, availableStatuses: [], sort: 'id', direction: 1, transform: { x: 20, y: 20, scale: 1 }, layout: null, layoutKey: '', renderVersion: 0, projectVersion: 0, firstLayout: true, busy: false };
  const elk = window.ELK ? new window.ELK() : null;
  function el(tag, className, text) { const node = document.createElement(tag); if (className) node.className = className; if (text !== undefined) node.textContent = text; return node; }
  function svg(tag, attrs = {}, text) { const node = document.createElementNS(ns, tag); Object.entries(attrs).forEach(([key, value]) => node.setAttribute(key, value)); if (text !== undefined) node.textContent = text; return node; }
  function statusLabel(status) { return String(status || 'unknown').replaceAll('_', ' ').replace(/^./, c => c.toUpperCase()); }
  function statusElement(status) { return el('span', `status ${String(status).replace(/[^a-z_]/g, '')}`, statusLabel(status)); }
  function priorityLabel(p) { return p === null || p === undefined || p === '' ? '—' : `P${String(p).replace(/^P/i, '')}`; }
  function message(lines, error = false) { $('messages').replaceChildren(...lines.map(text => el('div', '', text))); $('messages').hidden = !lines.length; $('messages').setAttribute('role', error ? 'alert' : 'status'); }
  function currentFilters() { return { search: $('search').value, epic: $('epic').value, statuses: state.statuses === null ? null : [...state.statuses], priority: $('priority').value }; }
  function syncStatusSelection() {
    $('status-options').querySelectorAll('input').forEach(input => { input.checked = state.statuses === null || state.statuses.has(input.value); });
    $('status-summary').textContent = state.statuses === null ? 'All statuses' : state.statuses.size ? `${state.statuses.size} selected` : 'No statuses';
  }
  function statusOptions(statuses) {
    state.availableStatuses = statuses;
    const focused = $('status-options').contains(document.activeElement) ? document.activeElement.value : null;
    // Keep selected statuses even when a refreshed snapshot no longer contains them.
    const entries = [...new Set([...statuses, ...(state.statuses || [])])].sort();
    const fragment = document.createDocumentFragment();
    entries.forEach(status => {
      const label = el('label'), input = el('input'); input.type = 'checkbox'; input.name = 'statuses'; input.value = status;
      label.append(input, document.createTextNode(`${statusLabel(status)}${statuses.includes(status) ? '' : ' (not in snapshot)'}`)); fragment.append(label);
    });
    if (!entries.length) fragment.append(el('p', 'muted', 'No statuses in this snapshot.'));
    $('status-options').replaceChildren(fragment); syncStatusSelection();
    if (focused !== null) [...$('status-options').querySelectorAll('input')].find(input => input.value === focused)?.focus({ preventScroll: true });
  }
  function resetFilters() {
    ['epic', 'priority', 'search'].forEach(id => $(id).value = ''); state.statuses = null; statusOptions(state.availableStatuses);
  }
  function selectOptions(id, entries, defaultLabel, extra = []) {
    const control = $(id), selected = control.value;
    const options = [{ value: '', label: defaultLabel }, ...entries, ...extra];
    const fragment = document.createDocumentFragment();
    options.forEach(item => { const option = el('option', '', item.label); option.value = item.value; fragment.append(option); });
    control.replaceChildren(fragment); control.value = options.some(o => o.value === selected) ? selected : '';
  }
  function updateFilters() {
    const all = FlowModel.prepare(state.data);
    selectOptions('epic', [...all.epics.values()].map(t => ({ value: t.id, label: t.title })), 'All epics', [{ value: '__none__', label: 'No epic' }]);
    statusOptions([...new Set(all.tickets.map(t => t.status))].filter(s => typeof s === 'string' && s.length).sort());
    selectOptions('priority', [...new Set(all.tickets.map(t => t.priority))].filter(p => p !== null && p !== undefined).sort().map(p => ({ value: String(p), label: priorityLabel(p) })), 'All priorities');
  }
  async function request(url) {
    const response = await fetch(url, { cache: 'no-store' });
    let result;
    try { result = await response.json(); } catch { throw new Error('The flow service returned an invalid response.'); }
    if (!response.ok) throw new Error(result.error || `Request failed (${response.status}).`);
    return result;
  }
  async function loadProjects() {
    const result = demo ? { projects: [{ id: 'corylus-demo', name: 'Corylus · example' }] } : await request('/api/projects');
    $('project').replaceChildren(...result.projects.map(p => { const o = el('option', '', p.name); o.value = p.id; return o; }));
    const queryProject = new URLSearchParams(location.search).get('project');
    if (queryProject && result.projects.some(p => p.id === queryProject)) $('project').value = queryProject;
    if (!result.projects.length) {
      $('updated').textContent = 'No projects configured';
      message(['No td projects are configured. Configure the flow service with a project path.']);
      state.data = { tickets: [], epics: [], edges: [], warnings: [] }; await render(); return;
    }
    await refresh();
  }
  async function refresh() {
    if (state.busy) return;
    const project = $('project').value, version = state.projectVersion;
    state.busy = true; $('refresh').disabled = true;
    try {
      const data = await request(demo ? '/static/flow_demo.json' : `/api/flow?project=${encodeURIComponent(project)}`);
      if (version !== state.projectVersion || project !== $('project').value) return;
      state.data = data;
      state.selected = FlowModel.selectionAfterRefresh(state.selected, data.tickets || []);
      updateFilters(); await render();
      $('updated').textContent = `Updated ${new Date(data.updated_at || Date.now()).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}`;
    } catch (error) {
      message([`${error.message}${state.data ? ' Showing the last successful snapshot.' : ' Use Refresh to try again.'}`], true);
      $('updated').textContent = state.data ? 'Refresh failed · stale data' : 'Connection failed';
      if (!state.data) { $('graph-empty').hidden = false; $('graph-empty').textContent = 'Cannot load project tickets.'; $('table-empty').hidden = false; $('table-empty').textContent = 'No snapshot available.'; }
    } finally { state.busy = false; $('refresh').disabled = false; if (version !== state.projectVersion) refresh(); }
  }
  function card(ticket) {
    const button = el('button', `ticket-card${state.selected === ticket.id ? ' selected' : ''}`);
    button.type = 'button'; button.dataset.ticket = ticket.id; button.setAttribute('aria-pressed', state.selected === ticket.id ? 'true' : 'false');
    const top = el('span', 'card-top'); top.append(el('span', '', ticket.id), el('span', '', priorityLabel(ticket.priority)));
    button.append(top, el('span', 'card-title', ticket.title), statusElement(ticket.status));
    button.addEventListener('click', () => selectTicket(ticket.id, true));
    return button;
  }
  function renderShelf() {
    const model = state.model, list = $('independent-list');
    list.replaceChildren(...model.independent.map(card));
    if (!model.independent.length) list.append(el('p', 'muted', 'No independent tickets match these filters.'));
    $('independent-count').textContent = model.independent.length;
  }
  function renderTable() {
    if (!state.model) return;
    const rows = $('ticket-rows'); rows.replaceChildren();
    const tickets = FlowModel.sortTickets(state.model.visible, state.sort, state.direction);
    const fragment = document.createDocumentFragment();
    tickets.forEach(ticket => {
      const row = el('tr', `ticket-row${state.selected === ticket.id ? ' selected' : ''}`); row.dataset.ticket = ticket.id; row.tabIndex = 0; row.setAttribute('aria-selected', state.selected === ticket.id ? 'true' : 'false');
      row.setAttribute('aria-label', `${ticket.id}: ${ticket.title}. ${statusLabel(ticket.status)}. Press Enter for details.`);
      row.append(el('td', 'ticket-id', ticket.id), el('td', '', ticket.title), el('td', '', ticket.type || 'task'));
      const status = el('td'); status.append(statusElement(ticket.status)); row.append(status, el('td', '', priorityLabel(ticket.priority)));
      const epic = state.model.membership.get(ticket.id); row.append(el('td', '', epic ? state.model.epics.get(epic)?.title || epic : '—'));
      const dependencies = el('td');
      const prereqs = state.model.prerequisites.get(ticket.id) || [];
      if (!prereqs.length) dependencies.textContent = '—';
      prereqs.forEach((id, index) => {
        if (index) dependencies.append(document.createTextNode(', '));
        const b = el('button', 'dependency-button', id); b.type = 'button'; b.addEventListener('click', event => { event.stopPropagation(); selectTicket(id, true); }); dependencies.append(b);
      });
      row.append(dependencies, el('td', '', ticket.updated_at ? new Date(ticket.updated_at).toLocaleDateString() : '—'));
      row.addEventListener('click', () => selectTicket(ticket.id));
      row.addEventListener('keydown', event => { if (event.target !== row) return; if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); selectTicket(ticket.id); } else if (event.key === 'ArrowDown' || event.key === 'ArrowUp') { event.preventDefault(); const index = tickets.indexOf(ticket), next = tickets[index + (event.key === 'ArrowDown' ? 1 : -1)]; if (next) { selectTicket(next.id); [...$('ticket-rows').querySelectorAll('.ticket-row')].find(r => r.dataset.ticket === next.id)?.focus(); } } });
      fragment.append(row);
      if (ticket.id === state.selected) {
        const detailRow = el('tr', 'detail-row'), cell = el('td'); cell.colSpan = 8;
        const content = el('div', 'detail-content');
        for (const [title, text] of [['Description', ticket.description || 'No description provided.'], ['Acceptance criteria', ticket.acceptance || 'No acceptance criteria provided.']]) { const section = el('section'); section.append(el('h3', '', title), el('p', 'detail-text', text)); content.append(section); }
        cell.append(content);
        const hidden = state.model.hiddenConnections.get(ticket.id) || 0;
        cell.append(el('div', 'detail-meta', [ticket.id, ticket.type || 'task', (ticket.labels || []).join(', '), hidden ? `${hidden} dependency connection(s) outside the current filter` : ''].filter(Boolean).join(' · ')));
        detailRow.append(cell); fragment.append(detailRow);
      }
    });
    rows.append(fragment); $('ticket-count').textContent = tickets.length;
    $('table-summary').textContent = `${tickets.length} of ${state.model.tickets.length} records${state.selected && !tickets.some(t => t.id === state.selected) ? ` · Selected ${state.selected} is outside these filters` : ''}`;
    $('table-empty').hidden = Boolean(tickets.length); $('table-empty').textContent = state.model.tickets.length ? 'No tickets match these filters.' : 'This project has no tickets yet.';
    document.querySelectorAll('th').forEach(th => { const button = th.querySelector('[data-sort]'); if (button) th.setAttribute('aria-sort', button.dataset.sort === state.sort ? state.direction === 1 ? 'ascending' : 'descending' : 'none'); });
  }
  function titleLines(title, limit = 22) {
    const words = String(title || '').split(/\s+/), lines = [''];
    words.forEach(word => { const last = lines.length - 1; if (lines[last].length + word.length + 1 > limit && lines[last]) lines.push(word); else lines[last] += (lines[last] ? ' ' : '') + word; });
    return lines.slice(0, 2).map((line, i) => line.length > limit ? `${line.slice(0, limit - 1)}…` : i === 1 && lines.length > 2 ? `${line.slice(0, limit - 1)}…` : line);
  }
  function renderGraph(layout) {
    const scene = $('graph-scene'); scene.replaceChildren();
    const positions = new Map(), edges = [], containers = [];
    function walk(node, offsetX = 0, offsetY = 0) {
      const x = offsetX + (node.x || 0), y = offsetY + (node.y || 0);
      if (node.id.startsWith('epic:')) containers.push({ ...node, absX: x, absY: y });
      else if (node.id !== 'root') positions.set(node.id, { ...node, absX: x, absY: y });
      (node.edges || []).forEach(edge => edges.push({ ...edge, offsetX: x, offsetY: y }));
      (node.children || []).forEach(child => walk(child, x, y));
    }
    walk(layout);
    containers.forEach(node => {
      const epicId = node.id.slice(5);
      const group = svg('g', { class: 'epic-container', 'data-ticket': epicId }); group.append(svg('rect', { x: node.absX, y: node.absY, width: node.width, height: node.height, rx: 8, class: `epic-boundary${state.selected === node.id.slice(5) ? ' selected' : ''}` }));
      const epicTitle = state.model.epics.get(epicId)?.title || epicId;
      const fullLabel = `EPIC · ${epicTitle}`, labelLimit = Math.max(12, Math.floor((node.width - 36) / 7.5));
      const labelText = fullLabel.length > labelLimit ? `${fullLabel.slice(0, labelLimit - 1)}…` : fullLabel;
      const label = svg('text', { x: node.absX + 18, y: node.absY + 28, class: `epic-label${state.selected === node.id.slice(5) ? ' selected' : ''}` }, labelText);
      label.append(svg('title', {}, fullLabel));
      label.setAttribute('tabindex', '0'); label.setAttribute('role', 'button'); label.setAttribute('aria-label', `Epic: ${state.model.epics.get(epicId)?.title || epicId}`);
      label.addEventListener('click', () => selectTicket(epicId, true));
      label.addEventListener('keydown', event => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); selectTicket(epicId, true); } });
      group.append(label); scene.append(group);
      positions.set(epicId, { ...node, absX: node.absX, absY: node.absY, container: true });
    });
    edges.forEach(edge => (edge.sections || []).forEach(section => {
      const container = containers.find(c => c.id === edge.container);
      const offsetX = container ? container.absX : edge.offsetX, offsetY = container ? container.absY : edge.offsetY;
      const points = [section.startPoint, ...(section.bendPoints || []), section.endPoint];
      const path = svg('path', { d: points.map((p, i) => `${i ? 'L' : 'M'}${p.x + offsetX},${p.y + offsetY}`).join(' '), class: `graph-edge${edge.ticketSource === state.selected || edge.ticketTarget === state.selected || edge.sources?.includes(state.selected) || edge.targets?.includes(state.selected) ? ' selected-edge' : ''}` });
      if (edge.sources?.[0]) path.dataset.source = edge.ticketSource || edge.sources[0]; if (edge.targets?.[0]) path.dataset.target = edge.ticketTarget || edge.targets[0]; scene.append(path);
    }));
    positions.forEach(node => {
      if (node.container) return;
      const ticket = state.model.byId.get(node.id); if (!ticket) return;
      const group = svg('g', { transform: `translate(${node.absX},${node.absY})`, class: `node-card${state.selected === ticket.id ? ' selected' : ''}`, 'data-ticket': ticket.id, tabindex: 0, role: 'button', 'aria-label': `${ticket.id}: ${ticket.title}. ${statusLabel(ticket.status)}`, 'aria-pressed': String(state.selected === ticket.id) });
      group.append(svg('title', {}, `${ticket.id}: ${ticket.title}`), svg('rect', { width: node.width, height: node.height, rx: 6 }), svg('text', { x: 13, y: 19, class: 'node-id' }, ticket.id), svg('text', { x: node.width - 14, y: 19, 'text-anchor': 'end', class: 'node-id' }, priorityLabel(ticket.priority)));
      titleLines(ticket.title).forEach((line, i) => group.append(svg('text', { x: 13, y: 40 + i * 15, class: 'node-title' }, line)));
      group.append(svg('circle', { cx: 17, cy: 76, r: 3.5, class: `node-status-dot ${String(ticket.status).replace(/[^a-z_]/g, '')}` }), svg('text', { x: 26, y: 80, class: 'node-meta' }, statusLabel(ticket.status)));
      const hidden = state.model.hiddenConnections.get(ticket.id);
      if (hidden) group.append(svg('text', { x: node.width - 12, y: 80, 'text-anchor': 'end', class: 'node-context' }, `+${hidden} hidden link${hidden === 1 ? '' : 's'}`));
      group.addEventListener('click', () => selectTicket(ticket.id, true)); group.addEventListener('keydown', event => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); selectTicket(ticket.id, true); } }); scene.append(group);
    });
    state.positions = positions; applyTransform();
  }
  async function render() {
    if (!state.data) return;
    const version = ++state.renderVersion;
    state.model = FlowModel.prepare(state.data, currentFilters());
    renderShelf(); renderTable();
    const hidden = [...state.model.hiddenConnections.values()].filter(Boolean).length;
    message([...state.model.warnings, ...(hidden ? [`${hidden} visible ticket(s) have dependencies outside these filters. Hidden connections are marked on their cards.`] : [])]);
    const visibleEpics = new Set();
    state.model.visible.forEach(ticket => { if (ticket.type === 'epic') visibleEpics.add(ticket.id); const epic = state.model.membership.get(ticket.id); if (epic) visibleEpics.add(epic); });
    $('graph-summary').textContent = `${state.model.connectedTickets.length} connected · ${visibleEpics.size} epics · ${state.model.visibleEdges.length} links`;
    $('graph-empty').hidden = Boolean(state.model.graph.children.length);
    $('graph-empty').textContent = state.model.tickets.length ? 'No graph tickets match these filters. Independent tickets are on the right.' : 'This project has no tickets yet.';
    if (!elk) { $('graph-empty').hidden = false; $('graph-empty').textContent = 'The graph layout library could not be loaded. Ticket details remain available below.'; message(['The graph layout library could not be loaded. Refresh after restoring the static assets.'], true); return; }
    const viewportWidth = $('graph-viewport').clientWidth;
    const key = `${viewportWidth}:${JSON.stringify(state.model.graph)}`;
    try {
      const layout = key === state.layoutKey && state.layout ? state.layout : await FlowModel.layout(state.model.graph, elk, viewportWidth);
      if (version !== state.renderVersion) return;
      const changed = state.layoutKey !== key;
      state.layout = layout; state.layoutKey = key; renderGraph(layout);
      if (state.firstLayout || changed) { fit(true); state.firstLayout = false; }
    } catch { if (version === state.renderVersion) { message([...state.model.warnings, 'Graph layout failed. The ticket table is available; try filtering to a smaller view or refreshing.'], true); $('graph-scene').replaceChildren(); $('graph-empty').hidden = false; $('graph-empty').textContent = 'Unable to lay out these dependencies.'; } }
  }
  function selectTicket(id, scroll = false) {
    if (!state.model?.byId.has(id)) { message([`Ticket ${id} is not available in this project snapshot.`]); return; }
    const focused = document.activeElement, focusKind = focused?.classList?.contains('epic-label') ? 'epic' : focused?.classList?.contains('node-card') ? 'graph' : focused?.classList?.contains('ticket-row') ? 'table' : focused?.classList?.contains('ticket-card') ? 'shelf' : null;
    state.selected = id; renderShelf(); renderTable(); if (state.layout) renderGraph(state.layout);
    if (focusKind) {
      const host = ['graph', 'epic'].includes(focusKind) ? $('graph-scene') : focusKind === 'table' ? $('ticket-rows') : $('independent-list');
      const target = [...host.querySelectorAll('[data-ticket]')].find(node => node.dataset.ticket === id);
      (focusKind === 'epic' ? target?.querySelector('.epic-label') : target)?.focus({ preventScroll: true });
    }
    if (scroll) [...$('ticket-rows').querySelectorAll('.ticket-row')].find(row => row.dataset.ticket === id)?.scrollIntoView({ block: 'nearest', behavior: 'instant' });
  }
  function applyTransform() { const t = state.transform; $('graph-scene').setAttribute('transform', `translate(${t.x},${t.y}) scale(${t.scale})`); $('zoom-label').textContent = `${Math.round(t.scale * 100)}%`; }
  function fit(topAnchored = false) {
    if (!state.layout) return;
    const width = $('graph-viewport').clientWidth, height = $('graph-viewport').clientHeight;
    if (topAnchored) {
      state.transform = { scale: Math.min(1, (width - 35) / Math.max(1, state.layout.width || 1)), x: 16, y: 16 }; applyTransform(); return;
    }
    const scale = Math.max(.01, Math.min(1.25, (width - 35) / Math.max(1, state.layout.width || 1), (height - 42) / Math.max(1, state.layout.height || 1)));
    state.transform = { scale, x: (width - (state.layout.width || 0) * scale) / 2, y: (height - (state.layout.height || 0) * scale) / 2 }; applyTransform();
  }
  function zoom(factor, px = $('graph-viewport').clientWidth / 2, py = $('graph-viewport').clientHeight / 2) {
    const t = state.transform, next = Math.max(.01, Math.min(3, t.scale * factor)), ratio = next / t.scale;
    state.transform = { scale: next, x: px - (px - t.x) * ratio, y: py - (py - t.y) * ratio }; applyTransform();
  }
  $('sample-badge').hidden = !demo;
  $('filters').addEventListener('submit', event => event.preventDefault());
  ['epic', 'priority'].forEach(id => $(id).addEventListener('change', render));
  $('status-options').addEventListener('change', event => {
    const input = event.target; if (!input.matches('input[type="checkbox"]')) return;
    if (state.statuses === null) state.statuses = new Set(state.availableStatuses);
    if (input.checked) state.statuses.add(input.value); else state.statuses.delete(input.value);
    syncStatusSelection(); render();
  });
  $('status-all').addEventListener('click', () => { state.statuses = null; statusOptions(state.availableStatuses); render(); });
  $('status').addEventListener('keydown', event => { if (event.key === 'Escape') { event.preventDefault(); $('status').open = false; $('status').querySelector('summary').focus(); } });
  let searchTimer; $('search').addEventListener('input', () => { clearTimeout(searchTimer); searchTimer = setTimeout(render, 130); });
  $('clear-filters').addEventListener('click', () => { resetFilters(); render(); });
  $('project').addEventListener('change', () => { state.projectVersion++; state.selected = null; state.data = null; state.firstLayout = true; state.layout = null; $('graph-scene').replaceChildren(); $('ticket-rows').replaceChildren(); $('independent-list').replaceChildren(); $('graph-empty').hidden = false; $('graph-empty').textContent = 'Loading project…'; state.availableStatuses = []; resetFilters(); const url = new URL(location.href); url.searchParams.set('project', $('project').value); history.replaceState(null, '', url); refresh(); });
  $('refresh').addEventListener('click', () => { if ($('project').options.length) refresh(); else loadProjects().catch(error => message([error.message], true)); });
  document.querySelectorAll('[data-sort]').forEach(button => button.addEventListener('click', () => { state.direction = state.sort === button.dataset.sort ? -state.direction : 1; state.sort = button.dataset.sort; renderTable(); }));
  $('fit').addEventListener('click', () => fit()); $('zoom-in').addEventListener('click', () => zoom(1.2)); $('zoom-out').addEventListener('click', () => zoom(1 / 1.2));
  let drag = null;
  $('graph-viewport').addEventListener('pointerdown', event => { if (event.button !== 0 || event.target.closest('.node-card, .epic-label')) return; drag = { x: event.clientX, y: event.clientY, tx: state.transform.x, ty: state.transform.y }; $('graph-viewport').setPointerCapture(event.pointerId); $('graph-viewport').classList.add('dragging'); });
  $('graph-viewport').addEventListener('pointermove', event => { if (!drag) return; state.transform.x = drag.tx + event.clientX - drag.x; state.transform.y = drag.ty + event.clientY - drag.y; applyTransform(); });
  function endPan() { drag = null; $('graph-viewport').classList.remove('dragging'); }
  $('graph-viewport').addEventListener('pointerup', endPan); $('graph-viewport').addEventListener('pointercancel', endPan);
  $('graph-viewport').addEventListener('wheel', event => { event.preventDefault(); const rect = $('graph-viewport').getBoundingClientRect(); zoom(Math.exp(-event.deltaY * .0015), event.clientX - rect.left, event.clientY - rect.top); }, { passive: false });
  $('graph-viewport').addEventListener('keydown', event => {
    if (event.key === '+' || event.key === '=') { event.preventDefault(); zoom(1.2); }
    else if (event.key === '-') { event.preventDefault(); zoom(1 / 1.2); }
    else if (event.key.toLowerCase() === 'f') { event.preventDefault(); fit(); }
    else if (['ArrowRight', 'ArrowDown', 'ArrowLeft', 'ArrowUp'].includes(event.key)) { event.preventDefault(); const nodes = [...state.positions?.keys() || []], index = nodes.indexOf(state.selected), step = ['ArrowRight', 'ArrowDown'].includes(event.key) ? 1 : -1; const id = nodes[(index + step + nodes.length) % nodes.length]; if (id) selectTicket(id, true); }
  });
  let resizing = false;
  function resizeTo(value) { value = Math.max(20, Math.min(80, value)); document.documentElement.style.setProperty('--graph-height', `${value}%`); $('divider').setAttribute('aria-valuenow', String(Math.round(value))); }
  $('divider').addEventListener('pointerdown', event => { resizing = true; $('divider').setPointerCapture(event.pointerId); event.preventDefault(); });
  $('divider').addEventListener('pointermove', event => { if (!resizing) return; const rect = $('workspace').getBoundingClientRect(); resizeTo((event.clientY - rect.top) / rect.height * 100); });
  $('divider').addEventListener('pointerup', () => { resizing = false; }); $('divider').addEventListener('pointercancel', () => { resizing = false; });
  $('divider').addEventListener('keydown', event => { if (event.key === 'ArrowUp' || event.key === 'ArrowDown') { event.preventDefault(); resizeTo(Number($('divider').getAttribute('aria-valuenow')) + (event.key === 'ArrowUp' ? -5 : 5)); } });
  let resizeTimer;
  new ResizeObserver(() => { clearTimeout(resizeTimer); resizeTimer = setTimeout(() => { if (state.data && state.layout) render(); }, 100); }).observe($('graph-viewport'));
  loadProjects().catch(error => { message([error.message], true); $('updated').textContent = 'Connection failed'; $('graph-empty').hidden = false; $('graph-empty').textContent = 'Cannot load projects. Use Refresh to try again.'; });
  setInterval(() => { if (!document.hidden && state.data && !demo) refresh(); }, 30000);
})();
