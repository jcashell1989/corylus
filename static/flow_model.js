(function (root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.FlowModel = api;
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';
  const NODE_WIDTH = 184, NODE_HEIGHT = 100;
  function prepare(data, filters = {}) {
    const tickets = (data.tickets || []).map(t => ({ ...t, id: String(t.id) }));
    const byId = new Map(tickets.map(t => [t.id, t]));
    const epics = new Map((data.epics || []).map(e => [String(e.id), { ...e, id: String(e.id) }]));
    tickets.filter(t => t.type === 'epic').forEach(t => { if (!epics.has(t.id)) epics.set(t.id, t); });
    const warnings = [...(data.warnings || [])];
    const membership = new Map();
    let membershipVisits = 0;
    function epicOf(ticket) {
      if (membership.has(ticket.id)) return membership.get(ticket.id);
      const trail = [], seen = new Set();
      let current = ticket.id, result = null;
      while (current) {
        if (membership.has(current)) { result = membership.get(current); break; }
        if (seen.has(current)) break;
        const ancestor = byId.get(current);
        if (!ancestor) break;
        membershipVisits++;
        seen.add(current); trail.push(current);
        if (ancestor.type === 'epic') break;
        // The backend already resolves membership. An explicit null is authoritative.
        if (ancestor.epic_id !== undefined) {
          result = ancestor.epic_id ? String(ancestor.epic_id) : null;
          break;
        }
        const parent = ancestor.parent_id ? String(ancestor.parent_id) : null;
        if (parent && epics.has(parent)) { result = parent; break; }
        current = parent;
      }
      // Cache every visited ancestor, including null and cyclic ancestry results.
      trail.forEach(id => membership.set(id, result));
      return result;
    }
    tickets.forEach(epicOf);
    const rawEdges = [...(data.edges || [])];
    tickets.forEach(t => (t.depends_on || []).forEach(source => rawEdges.push({ source: String(source), target: t.id })));
    const edges = [], seenEdges = new Set(), connected = new Set();
    const prerequisites = new Map(tickets.map(t => [t.id, []]));
    for (const raw of rawEdges) {
      const source = String(raw.source), target = String(raw.target), key = `${source}\0${target}`;
      if (seenEdges.has(key)) continue;
      seenEdges.add(key);
      if (prerequisites.has(target)) prerequisites.get(target).push(source);
      // Unknown prerequisites still mean a ticket is connected. Never quietly move it to the shelf.
      connected.add(source); connected.add(target);
      if (!byId.has(source) || !byId.has(target)) { warnings.push(`Dependency ${source} → ${target} references a missing ticket.`); continue; }
      edges.push({ source, target });
    }
    const query = (filters.search || '').trim().toLowerCase();
    const matches = t => (!query || [t.id, t.title, t.description, ...(t.labels || [])].join(' ').toLowerCase().includes(query)) &&
      (!filters.status || t.status === filters.status) && (!filters.priority || String(t.priority) === filters.priority) &&
      (!filters.epic || (filters.epic === '__none__' ? !membership.get(t.id) && t.type !== 'epic' : membership.get(t.id) === filters.epic || t.id === filters.epic));
    const visible = tickets.filter(matches), visibleIds = new Set(visible.map(t => t.id));
    const connectedTickets = visible.filter(t => connected.has(t.id));
    const independent = visible.filter(t => !connected.has(t.id) && t.type !== 'epic');
    const visibleEdges = edges.filter(e => visibleIds.has(e.source) && visibleIds.has(e.target));
    const hiddenConnections = new Map(visible.map(t => [t.id, 0]));
    edges.forEach(e => {
      if (visibleIds.has(e.source) && !visibleIds.has(e.target)) hiddenConnections.set(e.source, hiddenConnections.get(e.source) + 1);
      if (visibleIds.has(e.target) && !visibleIds.has(e.source)) hiddenConnections.set(e.target, hiddenConnections.get(e.target) + 1);
    });
    rawEdges.forEach(e => {
      if (visibleIds.has(String(e.target)) && !byId.has(String(e.source))) hiddenConnections.set(String(e.target), Math.max(1, hiddenConnections.get(String(e.target))));
    });
    // Iterative Kahn pass avoids stack overflow on large projects; cycles remain visible in ELK.
    const incoming = new Map(tickets.map(t => [t.id, 0])), outgoing = new Map(tickets.map(t => [t.id, []]));
    edges.forEach(e => { incoming.set(e.target, incoming.get(e.target) + 1); outgoing.get(e.source).push(e.target); });
    const queue = tickets.filter(t => incoming.get(t.id) === 0).map(t => t.id);
    for (let i = 0; i < queue.length; i++) outgoing.get(queue[i]).forEach(id => { incoming.set(id, incoming.get(id) - 1); if (!incoming.get(id)) queue.push(id); });
    const hasCycle = queue.length < tickets.length;
    if (hasCycle) warnings.push('Dependency cycle detected. The graph shows the relationships; it is not a valid DAG.');
    const graphNodes = connectedTickets.filter(t => t.type !== 'epic');
    // Dependency-linked epic records themselves must also appear as cards, outside their own container.
    connectedTickets.filter(t => t.type === 'epic').forEach(t => graphNodes.push(t));
    const epicGroups = new Map();
    graphNodes.forEach(t => { const epic = membership.get(t.id); if (epic) { if (!epicGroups.has(epic)) epicGroups.set(epic, []); epicGroups.get(epic).push(t); } });
    const node = t => ({ id: t.id, width: NODE_WIDTH, height: NODE_HEIGHT });
    const children = graphNodes.filter(t => !membership.get(t.id)).map(node);
    epicGroups.forEach((members, id) => children.push({ id: `epic:${id}`, children: members.map(node), layoutOptions: { 'elk.padding': '[top=44,left=12,bottom=16,right=12]' } }));
    const graph = { id: 'root', layoutOptions: { 'elk.algorithm': 'layered', 'elk.direction': 'RIGHT', 'elk.hierarchyHandling': 'INCLUDE_CHILDREN', 'elk.edgeRouting': 'ORTHOGONAL', 'elk.spacing.nodeNode': '24', 'elk.layered.spacing.nodeNodeBetweenLayers': '20', 'elk.padding': '[top=16,left=12,bottom=16,right=12]' }, children, edges: visibleEdges.map((e, i) => ({ id: `edge:${i}`, sources: [e.source], targets: [e.target] })) };
    return { tickets, byId, epics, membership, membershipVisits, prerequisites, connected, visible, connectedTickets, independent, edges, visibleEdges, hiddenConnections, graph, warnings: [...new Set(warnings)], hasCycle };
  }
  function sortTickets(tickets, field = 'id', direction = 1) {
    return [...tickets].sort((a, b) => String(a[field] ?? '').localeCompare(String(b[field] ?? ''), undefined, { numeric: true }) * direction || a.id.localeCompare(b.id));
  }
  function selectionAfterRefresh(selected, tickets) { return tickets.some(t => t.id === selected) ? selected : null; }
  return { prepare, sortTickets, selectionAfterRefresh, NODE_WIDTH, NODE_HEIGHT };
});
