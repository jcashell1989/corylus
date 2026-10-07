(function (root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.FlowModel = api;
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';
  const NODE_WIDTH = 184, NODE_HEIGHT = 100;
  // Apply compaction within epic boxes as well as across the whole graph.
  // Cross-epic dependencies otherwise leave long, mostly empty compound layers.
  const LAYOUT_OPTIONS = {
    'elk.algorithm': 'layered',
    'elk.direction': 'RIGHT',
    'elk.hierarchyHandling': 'INCLUDE_CHILDREN',
    'elk.edgeRouting': 'ORTHOGONAL',
    'elk.layered.nodePlacement.strategy': 'NETWORK_SIMPLEX',
    'elk.layered.compaction.postCompaction.strategy': 'EDGE_LENGTH',
    'elk.spacing.nodeNode': '8',
    'elk.layered.spacing.nodeNodeBetweenLayers': '8',
    'elk.spacing.edgeNode': '8',
    'elk.spacing.edgeEdge': '6',
    'elk.layered.spacing.edgeNodeBetweenLayers': '8',
    'elk.layered.spacing.edgeEdgeBetweenLayers': '6'
  };
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
    // Missing/null means all statuses; an explicit empty selection means none.
    const statuses = Array.isArray(filters.statuses) ? new Set(filters.statuses) :
      filters.status ? new Set([filters.status]) : null;
    function belongsTo(id, epic) {
      const seen = new Set();
      while (id && !seen.has(id)) { if (id === epic) return true; seen.add(id); id = membership.get(id); }
      return false;
    }
    const matches = t => (!query || [t.id, t.title, t.description, ...(t.labels || [])].join(' ').toLowerCase().includes(query)) &&
      (!statuses || statuses.has(t.status)) && (!filters.priority || String(t.priority) === filters.priority) &&
      (!filters.epic || (filters.epic === '__none__' ? !membership.get(t.id) && t.type !== 'epic' : belongsTo(t.id, filters.epic)));
    const visible = tickets.filter(matches), visibleIds = new Set(visible.map(t => t.id));
    const connectedTickets = visible.filter(t => connected.has(t.id));
    const independent = visible.filter(t => !connected.has(t.id) && !membership.get(t.id) && t.type !== 'epic');
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
    // Every epic-owned ticket belongs on the graph, including unlinked members.
    const graphNodes = visible.filter(t => connected.has(t.id) || membership.get(t.id) || t.type === 'epic');
    const containers = new Map();
    function ensureEpic(id) {
      if (!containers.has(id)) containers.set(id, { id: `epic:${id}`, priority: epics.get(id)?.priority ?? byId.get(id)?.priority, children: [], layoutOptions: { ...LAYOUT_OPTIONS, 'elk.padding': '[top=44,left=12,bottom=16,right=12]' } });
    }
    graphNodes.forEach(t => {
      if (t.type === 'epic') ensureEpic(t.id);
      let epic = membership.get(t.id);
      const seen = new Set([t.id]);
      while (epic && !seen.has(epic)) { seen.add(epic); ensureEpic(epic); epic = membership.get(epic); }
    });
    const children = [];
    containers.forEach((box, id) => {
      const parent = membership.get(id);
      // Broken hierarchy must remain visible without producing a recursive graph.
      let cursor = parent;
      const seen = new Set([id]);
      while (cursor && !seen.has(cursor)) { seen.add(cursor); cursor = membership.get(cursor); }
      if (cursor) warnings.push(`Epic hierarchy cycle detected at ${id}.`);
      if (parent && containers.has(parent) && !cursor) containers.get(parent).children.push(box);
      else children.push(box);
    });
    graphNodes.filter(t => t.type !== 'epic').forEach(t => {
      const node = { id: t.id, priority: t.priority, width: NODE_WIDTH, height: NODE_HEIGHT };
      const box = containers.get(membership.get(t.id));
      (box ? box.children : children).push(node);
    });
    // An umbrella is the page frame, while its membership remains in the table.
    const frames = new Set();
    const allMembers = new Map();
    tickets.forEach(t => {
      const epic = membership.get(t.id);
      if (!allMembers.has(epic)) allMembers.set(epic, []);
      allMembers.get(epic).push(t);
    });
    children.filter(box => {
      const members = allMembers.get(box.id.slice(5)) || [];
      const epicCount = members.filter(t => t.type === 'epic').length;
      return epicCount >= 2 && epicCount > members.length / 2;
    }).forEach(box => { frames.add(box.id); children.splice(children.indexOf(box), 1, ...box.children); });
    const endpoint = id => frames.has(`epic:${id}`) ? 'root' : epics.has(id) && containers.has(id) ? `epic:${id}` : id;
    const graph = { id: 'root', layoutOptions: { ...LAYOUT_OPTIONS, 'elk.padding': '[top=16,left=12,bottom=16,right=12]' }, children, edges: visibleEdges.map((e, i) => ({ id: `edge:${i}`, sources: [endpoint(e.source)], targets: [endpoint(e.target)], ticketSource: e.source, ticketTarget: e.target })) };
    return { tickets, byId, epics, membership, membershipVisits, prerequisites, connected, visible, connectedTickets, independent, edges, visibleEdges, hiddenConnections, graph, warnings: [...new Set(warnings)], hasCycle };
  }
  // Lay out each DAG independently; cross-epic links must not stretch epic boxes.
  async function layout(graph, elk, viewportWidth = 1200) {
    const available = Math.max(NODE_WIDTH + 24, viewportWidth - 24);
    const allEdges = graph.edges || [], localEdges = new Set();
    const ancestry = new Map();
    function index(node, parents = []) {
      ancestry.set(node.id, parents);
      (node.children || []).forEach(child => index(child, [...parents, node.id]));
    }
    index(graph);
    function childOf(id, container) {
      const chain = ancestry.get(id);
      if (!chain) return null;
      const pos = chain.indexOf(container);
      return pos < 0 ? null : chain[pos + 1] || id;
    }
    function ordered(items, container, edges = allEdges) {
      const byId = new Map(items.map(n => [n.id, n]));
      const outgoing = new Map(items.map(n => [n.id, new Set()])), reverse = new Map(items.map(n => [n.id, new Set()]));
      edges.forEach(e => {
        const a = childOf(e.sources[0], container), b = childOf(e.targets[0], container);
        if (a !== b && byId.has(a) && byId.has(b)) { outgoing.get(a).add(b); reverse.get(b).add(a); }
      });
      const compare = (a, b) => String(a.priority ?? 'ZZ').localeCompare(String(b.priority ?? 'ZZ'), undefined, { numeric: true }) || a.id.localeCompare(b.id);
      // Condense strongly connected components before sorting. Appending all
      // cycle members at the end would put their outgoing dependents first.
      // Both traversals are iterative so large graphs cannot overflow a stack.
      const visited = new Set(), finish = [];
      items.forEach(node => {
        if (visited.has(node.id)) return;
        visited.add(node.id);
        const stack = [{ id: node.id, next: outgoing.get(node.id).values() }];
        while (stack.length) {
          const frame = stack[stack.length - 1], next = frame.next.next();
          if (next.done) { finish.push(frame.id); stack.pop(); }
          else if (!visited.has(next.value)) { visited.add(next.value); stack.push({ id: next.value, next: outgoing.get(next.value).values() }); }
        }
      });
      const owner = new Map(), groups = [];
      finish.reverse().forEach(id => {
        if (owner.has(id)) return;
        const group = [], queue = [id], index = groups.length;
        owner.set(id, index);
        for (let i = 0; i < queue.length; i++) {
          group.push(byId.get(queue[i]));
          reverse.get(queue[i]).forEach(next => { if (!owner.has(next)) { owner.set(next, index); queue.push(next); } });
        }
        groups.push(group.sort(compare));
      });
      const links = groups.map(() => new Set()), incoming = groups.map(() => 0);
      outgoing.forEach((targets, source) => targets.forEach(target => {
        const a = owner.get(source), b = owner.get(target);
        if (a !== b && !links[a].has(b)) { links[a].add(b); incoming[b]++; }
      }));
      const ready = groups.map((_, i) => i).filter(i => !incoming[i]), result = [];
      while (ready.length) {
        ready.sort((a, b) => compare(groups[a][0], groups[b][0]));
        const index = ready.shift(); result.push(...groups[index]);
        links[index].forEach(next => { if (!--incoming[next]) ready.push(next); });
      }
      return result;
    }
    const placements = new Map();
    function place(container, width) {
      const key = `${container.id}\0${width}`;
      if (!placements.has(key)) placements.set(key, pack(container, width));
      return placements.get(key);
    }
    async function pack(container, width) {
      const top = container.id === 'root' ? 16 : 44, padding = 12, gap = 8, bottom = 8;
      const nodes = container.children || [], leaves = nodes.filter(n => !n.children), boxes = nodes.filter(n => n.children);
      const leafById = new Map(leaves.map(n => [n.id, n]));
      const links = allEdges.filter(e => leafById.has(e.sources[0]) && leafById.has(e.targets[0]));
      const adjacent = new Map(leaves.map(n => [n.id, []]));
      links.forEach(e => { adjacent.get(e.sources[0]).push(e.targets[0]); adjacent.get(e.targets[0]).push(e.sources[0]); });
      const seen = new Set();
      let components = [];
      leaves.forEach(n => {
        if (seen.has(n.id)) return;
        const ids = [n.id]; seen.add(n.id);
        for (let i = 0; i < ids.length; i++) adjacent.get(ids[i]).forEach(id => { if (!seen.has(id)) { seen.add(id); ids.push(id); } });
        components.push(ids);
      });
      if (boxes.length) {
        // Contracting a local DAG can create a cycle through a nested box:
        // a -> b plus a -> N -> b becomes block(a,b) -> N -> block(a,b).
        // Refine only components in such a cycle; other DAGs retain their
        // compact ELK layout instead of turning every leaf into a wide row.
        const owner = new Map(boxes.map(n => [n.id, n.id]));
        components.forEach((ids, i) => ids.forEach(id => owner.set(id, i)));
        const outgoing = new Map([...owner.values()].map(id => [id, new Set()]));
        const incoming = new Map([...outgoing.keys()].map(id => [id, new Set()]));
        allEdges.forEach(e => {
          const a = owner.get(childOf(e.sources[0], container.id));
          const b = owner.get(childOf(e.targets[0], container.id));
          if (a !== b && outgoing.has(a) && outgoing.has(b)) {
            outgoing.get(a).add(b); incoming.get(b).add(a);
          }
        });
        function reachable(id, neighbors) {
          const visited = new Set([id]), queue = [id];
          for (let i = 0; i < queue.length; i++) neighbors.get(queue[i]).forEach(next => {
            if (!visited.has(next)) { visited.add(next); queue.push(next); }
          });
          return visited;
        }
        const split = new Set();
        boxes.forEach(box => {
          const before = reachable(box.id, incoming), after = reachable(box.id, outgoing);
          before.forEach(id => { if (typeof id === 'number' && after.has(id)) split.add(id); });
        });
        if (split.size) {
          // Each slice occupies the interval between nested boxes in a
          // topological order of the uncontracted children. Local edges stay
          // inside a slice when possible; edges crossing slices route below.
          const slots = new Map();
          let slot = 0;
          ordered(nodes, container.id).forEach(n => {
            if (n.children) slot++;
            else slots.set(n.id, slot);
          });
          components = components.flatMap((ids, i) => {
            if (!split.has(i)) return [ids];
            const slices = new Map();
            ids.forEach(id => {
              const key = slots.get(id);
              if (!slices.has(key)) slices.set(key, []);
              slices.get(key).push(id);
            });
            return [...slices.values()];
          });
        }
      }
      const laidBoxes = await Promise.all(boxes.map(n => place(n, width - padding * 2)));
      const blocks = await Promise.all(components.map(async ids => {
        const members = new Set(ids), edges = links.filter(e => members.has(e.sources[0]) && members.has(e.targets[0]));
        edges.forEach(e => localEdges.add(e.id));
        if (ids.length === 1 && !edges.length) return { ...leafById.get(ids[0]), members: ids };
        const laid = await elk.layout({ id: `dag:${ids[0]}`, layoutOptions: { ...LAYOUT_OPTIONS, 'elk.hierarchyHandling': 'SEPARATE_CHILDREN', 'elk.padding': '[top=0,left=0,bottom=0,right=0]' }, children: ids.map(id => ({ ...leafById.get(id) })), edges: edges.map(e => ({ ...e })) });
        return { ...laid, members: ids };
      }));
      // Order components and boxes by their induced dependency graph.
      const owner = new Map();
      [...laidBoxes, ...blocks].forEach(n => (n.members || [n.id]).forEach(id => owner.set(id, n.id)));
      const projected = allEdges.map(e => ({ ...e, sources: [owner.get(childOf(e.sources[0], container.id))], targets: [owner.get(childOf(e.targets[0], container.id))] }));
      // ordered() uses ancestry, so provide temporary component ancestry only here.
      const restore = new Map();
      blocks.forEach(n => { if (!ancestry.has(n.id)) { restore.set(n.id, undefined); ancestry.set(n.id, [...(ancestry.get(container.id) || []), container.id]); } });
      const orderedBlocks = ordered([...laidBoxes, ...blocks], container.id, projected);
      restore.forEach((value, id) => { if (value === undefined) ancestry.delete(id); });
      const neighbors = new Map(orderedBlocks.map(n => [n.id, new Set()]));
      projected.forEach(e => {
        const a = e.sources[0], b = e.targets[0];
        if (a !== b && neighbors.has(a) && neighbors.has(b)) {
          neighbors.get(a).add(b); neighbors.get(b).add(a);
        }
      });
      // Every sibling epic shares this row, regardless of the viewport.
      // Include leaf blocks connected to boxes so prerequisites, nested detours,
      // and page-level diamonds continue flowing left to right.
      const besideBoxes = new Set(laidBoxes.map(n => n.id)), queue = [...besideBoxes];
      for (let i = 0; i < queue.length; i++) neighbors.get(queue[i]).forEach(id => {
        if (!besideBoxes.has(id)) { besideBoxes.add(id); queue.push(id); }
      });
      const topRow = orderedBlocks.filter(n => besideBoxes.has(n.id));
      const remaining = orderedBlocks.filter(n => !besideBoxes.has(n.id));
      // Globally unlinked members are a vertical list, never a wrapped grid.
      // A single leaf with an external dependency is still part of the flow.
      const connectedIds = new Set(allEdges.flatMap(e => [...e.sources, ...e.targets]));
      const unlinked = container.id === 'root' ? [] : remaining.filter(n =>
        n.members?.length === 1 && !connectedIds.has(n.members[0]));
      const unlinkedIds = new Set(unlinked.map(n => n.id));
      const lowerRows = remaining.filter(n => !unlinkedIds.has(n.id)).map(n => [n]);
      const rows = topRow.length ? [topRow, ...lowerRows] : lowerRows;
      let right = padding, contentBottom = top;
      const children = [], edges = [];
      function put(block, x, y) {
        if (block.members && block.children) {
          block.children.forEach(n => children.push({ ...n, x: x + n.x, y: y + n.y }));
          (block.edges || []).forEach(e => edges.push({ ...e, container: container.id, sections: (e.sections || []).map(s => ({ ...s, startPoint: { x: s.startPoint.x + x, y: s.startPoint.y + y }, endPoint: { x: s.endPoint.x + x, y: s.endPoint.y + y }, bendPoints: (s.bendPoints || []).map(p => ({ x: p.x + x, y: p.y + y })) })) }));
        } else { const node = { ...block }; delete node.members; children.push({ ...node, x, y }); }
        right = Math.max(right, x + block.width);
        contentBottom = Math.max(contentBottom, y + block.height);
      }
      let y = top;
      rows.forEach(row => {
        let x = padding, height = 0;
        row.forEach(block => { put(block, x, y); x += block.width + gap; height = Math.max(height, block.height); });
        y += height + gap;
      });
      const listX = rows.length ? right + gap : padding;
      y = top;
      unlinked.forEach(block => { put(block, listX, y); y += block.height + gap; });
      return { ...container, children, edges, width: Math.max(NODE_WIDTH + padding * 2, right + padding), height: Math.max(top + bottom, contentBottom + bottom) };
    }
    const result = await place(graph, available);
    const positions = new Map();
    function locate(node, x = 0, y = 0) { x += node.x || 0; y += node.y || 0; positions.set(node.id, { ...node, x, y }); (node.children || []).forEach(n => locate(n, x, y)); }
    locate(result);
    allEdges.filter(e => !localEdges.has(e.id)).forEach(e => {
      const sourceParents = ancestry.get(e.sources[0]) || [], targetParents = ancestry.get(e.targets[0]) || [];
      let common = 'root';
      for (let i = 0; i < Math.min(sourceParents.length, targetParents.length) && sourceParents[i] === targetParents[i]; i++) common = sourceParents[i];
      let sourceId = childOf(e.sources[0], common) || e.sources[0], targetId = childOf(e.targets[0], common) || e.targets[0];
      if (sourceId === targetId) { sourceId = e.sources[0]; targetId = e.targets[0]; }
      const a = positions.get(sourceId), b = positions.get(targetId);
      if (!a || !b) return;
      let startPoint, endPoint, bendPoints;
      if (a.x + a.width <= b.x) {
        startPoint = { x: a.x + a.width, y: a.y + a.height / 2 }; endPoint = { x: b.x, y: b.y + b.height / 2 };
        const mid = (startPoint.x + endPoint.x) / 2; bendPoints = [{ x: mid, y: startPoint.y }, { x: mid, y: endPoint.y }];
      } else {
        startPoint = { x: a.x + a.width / 2, y: a.y + a.height }; endPoint = { x: b.x + b.width / 2, y: b.y };
        const mid = (startPoint.y + endPoint.y) / 2; bendPoints = [{ x: startPoint.x, y: mid }, { x: endPoint.x, y: mid }];
      }
      result.edges.push({ ...e, container: 'root', sections: [{ startPoint, bendPoints, endPoint, incomingShape: sourceId, outgoingShape: targetId }] });
    });
    return result;
  }
  function sortTickets(tickets, field = 'id', direction = 1) {
    return [...tickets].sort((a, b) => String(a[field] ?? '').localeCompare(String(b[field] ?? ''), undefined, { numeric: true }) * direction || a.id.localeCompare(b.id));
  }
  function selectionAfterRefresh(selected, tickets) { return tickets.some(t => t.id === selected) ? selected : null; }
  return { prepare, layout, sortTickets, selectionAfterRefresh, NODE_WIDTH, NODE_HEIGHT };
});
