const test = require('node:test');
const assert = require('node:assert/strict');
const model = require('../static/flow_model.js');
const ELK = require('../static/vendor/elk.bundled.js');
const fixture = require('../static/flow_demo.json');
function ticket(id, extra = {}) { return { id, title: id, type: 'task', status: 'open', priority: 'P1', ...extra }; }
function nestedEpics(normalized = false) {
  const tickets = [
    ticket('A', { type: 'epic' }),
    ticket('B', { type: 'epic', parent_id: 'A', depends_on: ['D'] }),
    ticket('C', { parent_id: 'B' }),
    ticket('A-task', { parent_id: 'A' }),
    ticket('D', { status: 'closed' }),
    ticket('shelf')
  ];
  if (normalized) tickets.forEach(t => { t.epic_id = t.id === 'B' || t.id === 'A-task' ? 'A' : t.id === 'C' ? 'B' : null; });
  return { tickets, edges: [{ source: 'D', target: 'B' }] };
}
function graphIds(graph) {
  const ids = [], seen = new Set(), pending = [...(graph.children || [])];
  while (pending.length) {
    const node = pending.pop();
    assert(!seen.has(node), 'graph containers cannot recursively contain themselves');
    seen.add(node);
    ids.push(node.id);
    pending.push(...(node.children || []));
  }
  return ids;
}
test('roots with outgoing edges and non-epic connected tickets stay on the open DAG canvas', () => {
  const view = model.prepare(fixture);
  assert(view.connectedTickets.some(t => t.id === 'td-101'));
  assert(view.graph.children.some(t => t.id === 'td-101'));
  assert(view.graph.children.some(t => t.id === 'td-107'));
  assert(!view.independent.some(t => t.id === 'td-101'));
  assert(!view.graph.children.some(t => t.id.toLowerCase().includes('ungrouped')));
  assert.deepEqual(view.independent.map(t => t.id), ['td-108', 'td-109', 'td-110']);
  assert.equal(view.visible.length, 12); // Includes two epic records in the table.
});
test('epic boxes enclose their own members and membership does not introduce dependency edges', () => {
  const view = model.prepare(fixture);
  const backend = view.graph.children.find(t => t.id === 'epic:td-backend');
  assert.deepEqual(backend.children.map(t => t.id), ['td-102', 'td-103', 'td-104']);
  assert.equal(view.visibleEdges.length, 7);
  assert(view.visibleEdges.some(e => e.source === 'td-103' && e.target === 'td-105'));
  assert(!view.edges.some(e => e.source === 'td-backend' || e.target === 'td-backend'));
});
test('unlinked epic members stay in their box and task-parent ancestry resolves nearest epic', () => {
  const data = { tickets: [ticket('e', { type: 'epic' }), ticket('parent', { parent_id: 'e' }), ticket('child', { parent_id: 'parent' })], epics: [{ id: 'e', title: 'Epic' }], edges: [] };
  const view = model.prepare(data);
  assert.equal(view.membership.get('child'), 'e');
  assert.deepEqual(view.independent.map(t => t.id), []);
  assert.deepEqual(view.graph.children.find(t => t.id === 'epic:e').children.map(t => t.id), ['parent', 'child']);
  assert.equal(view.visible.length, 3);
});
for (const normalized of [false, true]) {
  test(`nested epic membership and graph containers preserve hierarchy (${normalized ? 'normalized' : 'fallback'})`, () => {
    const view = model.prepare(nestedEpics(normalized));
    assert.equal(view.membership.get('B'), 'A');
    assert.equal(view.membership.get('C'), 'B');
    assert.equal(view.membership.get('A-task'), 'A');
    assert.deepEqual(view.independent.map(t => t.id), ['shelf']);
    assert.deepEqual(view.visibleEdges, [{ source: 'D', target: 'B' }]);
    const parent = view.graph.children.find(t => t.id === 'epic:A');
    assert(parent, 'A remains a box when only half its direct children are epics');
    const nested = parent.children.find(t => t.id === 'epic:B');
    assert(nested, 'B is contained by A');
    assert(nested.children.some(t => t.id === 'C'));
    assert(parent.children.some(t => t.id === 'A-task'));
    assert(!view.graph.children.some(t => t.id === 'B' || t.id === 'epic:B'));
    assert(view.graph.edges.some(e => e.sources.includes('D') && e.targets.includes('epic:B')));
    assert.equal(view.visible.find(t => t.id === 'B').parent_id, 'A');
    assert.deepEqual(model.prepare(nestedEpics(normalized), { epic: '__none__' }).visible.map(t => t.id), ['D', 'shelf']);
  });
}
test('epic filters include nested epic descendants and retain containment context', () => {
  const data = nestedEpics(true);
  const parentView = model.prepare(data, { epic: 'A' });
  assert.deepEqual(parentView.visible.map(t => t.id), ['A', 'B', 'C', 'A-task']);
  assert(graphIds(parentView.graph).includes('epic:B'));
  assert(graphIds(parentView.graph).includes('C'));
  const childView = model.prepare(data, { epic: 'B' });
  assert.deepEqual(childView.visible.map(t => t.id), ['B', 'C']);
  assert(graphIds(childView.graph).includes('epic:B'));
  assert(graphIds(childView.graph).includes('C'));
  assert.equal(childView.independent.length, 0);
});
test('empty epics remain selectable visible graph boxes', () => {
  const view = model.prepare({ tickets: [ticket('empty', { type: 'epic', epic_id: null })] });
  assert.deepEqual(view.visible.map(t => t.id), ['empty']);
  assert.equal(view.independent.length, 0);
  assert.equal(view.graph.children[0].id, 'epic:empty');
  assert.deepEqual(view.graph.children[0].children, []);
});
test('a root umbrella of child epics is a page frame and its children remain boxes', () => {
  const view = model.prepare({ tickets: [
    ticket('umbrella', { type: 'epic', epic_id: null }),
    ticket('left', { type: 'epic', parent_id: 'umbrella', epic_id: 'umbrella' }),
    ticket('right', { type: 'epic', parent_id: 'umbrella', epic_id: 'umbrella' }),
    ticket('member', { parent_id: 'left', epic_id: 'left' })
  ] });
  assert.equal(view.membership.get('left'), 'umbrella');
  assert.equal(view.independent.length, 0);
  assert(!graphIds(view.graph).includes('epic:umbrella'));
  assert(view.graph.children.some(t => t.id === 'epic:left'));
  assert(view.graph.children.some(t => t.id === 'epic:right'));
  assert(view.graph.children.find(t => t.id === 'epic:left').children.some(t => t.id === 'member'));
  assert.equal(view.visible.length, 4);
});
test('umbrella promotion preserves nested epic boxes instead of flattening them again', () => {
  const view = model.prepare({ tickets: [
    ticket('umbrella', { type: 'epic', epic_id: null }),
    ticket('left', { type: 'epic', epic_id: 'umbrella' }),
    ticket('right', { type: 'epic', epic_id: 'umbrella' }),
    ticket('nested-a', { type: 'epic', epic_id: 'left' }),
    ticket('nested-b', { type: 'epic', epic_id: 'left' })
  ] });
  assert(!graphIds(view.graph).includes('epic:umbrella'));
  const left = view.graph.children.find(n => n.id === 'epic:left');
  assert(left);
  assert.deepEqual(left.children.map(n => n.id), ['epic:nested-a', 'epic:nested-b']);
  assert(!view.graph.children.some(n => n.id === 'epic:nested-a' || n.id === 'epic:nested-b'));
});
test('search and status filters retain umbrella framing based on full-project membership', () => {
  const data = { tickets: [
    ticket('A', { type: 'epic', epic_id: null, status: 'closed' }),
    ticket('B', { type: 'epic', epic_id: 'A', status: 'closed' }),
    ticket('C', { type: 'epic', epic_id: 'A', status: 'closed' }),
    ticket('A-task', { epic_id: 'A', status: 'closed' }),
    ticket('B-child', { epic_id: 'B' })
  ] };
  for (const filters of [{ search: 'B-child' }, { statuses: ['open'] }]) {
    const view = model.prepare(data, filters);
    assert.deepEqual(view.visible.map(t => t.id), ['B-child']);
    assert(!graphIds(view.graph).includes('epic:A'), 'filtering cannot restore the umbrella box');
    const nested = view.graph.children.find(n => n.id === 'epic:B');
    assert(nested, 'nested epic box remains the visible containment context');
    assert.deepEqual(nested.children.map(n => n.id), ['B-child']);
    assert.equal(view.independent.length, 0);
  }
});
test('epic hierarchy cycles cannot create recursive graph containers', () => {
  const view = model.prepare({ tickets: [
    ticket('loop-a', { type: 'epic', parent_id: 'loop-b', epic_id: 'loop-b' }),
    ticket('loop-b', { type: 'epic', parent_id: 'loop-a', epic_id: 'loop-a' }),
    ticket('member', { parent_id: 'loop-a', epic_id: 'loop-a' })
  ] });
  const ids = graphIds(view.graph);
  assert.equal(new Set(ids).size, ids.length);
  assert(ids.includes('epic:loop-a'));
  assert(ids.includes('epic:loop-b'));
  assert(ids.includes('member'));
});
test('epic boxes top-align in dependency order and wrap at the viewport width', async () => {
  const data = { tickets: [
    ticket('downstream', { type: 'epic', epic_id: null }),
    ticket('upstream', { type: 'epic', epic_id: null }),
    ticket('third', { type: 'epic', epic_id: null }),
    ticket('down-task', { parent_id: 'downstream', epic_id: 'downstream' }),
    ticket('up-task', { parent_id: 'upstream', epic_id: 'upstream' }),
    ticket('third-task', { parent_id: 'third', epic_id: 'third' })
  ], edges: [{ source: 'up-task', target: 'down-task' }] };
  const elk = new ELK();
  const wide = await model.layout(model.prepare(data).graph, elk, 2000);
  const boxes = wide.children.filter(n => n.id.startsWith('epic:'));
  assert.equal(boxes.length, 3);
  assert.equal(new Set(boxes.map(n => n.y)).size, 1, 'all boxes share the top of their row');
  assert(boxes.find(n => n.id === 'epic:upstream').x < boxes.find(n => n.id === 'epic:downstream').x);
  const narrow = await model.layout(model.prepare(data).graph, elk, 300);
  const narrowBoxes = narrow.children.filter(n => n.id.startsWith('epic:'));
  assert.equal(new Set(narrowBoxes.map(n => n.y)).size, 3, 'each box wraps to its own row');
  assert(narrow.width <= 300, `wrapped graph width ${narrow.width} must fit the viewport`);
  assert(narrow.height > wide.height);
  const routed = [...(wide.edges || []), ...boxes.flatMap(n => n.edges || [])];
  assert(routed.some(edge => edge.sections?.length > 0), 'cross-epic dependency is routed');
});
test('nested sibling epic boxes top-align inside their parent and preserve task containment', async () => {
  const data = { tickets: [
    ticket('parent', { type: 'epic', epic_id: null }),
    ticket('left', { type: 'epic', parent_id: 'parent', epic_id: 'parent' }),
    ticket('right', { type: 'epic', parent_id: 'parent', epic_id: 'parent' }),
    ticket('parent-task-1', { parent_id: 'parent', epic_id: 'parent' }),
    ticket('parent-task-2', { parent_id: 'parent', epic_id: 'parent' }),
    ticket('left-task', { parent_id: 'left', epic_id: 'left' }),
    ticket('right-task', { parent_id: 'right', epic_id: 'right' })
  ] };
  const layout = await model.layout(model.prepare(data).graph, new ELK(), 2000);
  const parent = layout.children.find(n => n.id === 'epic:parent');
  const left = parent.children.find(n => n.id === 'epic:left');
  const right = parent.children.find(n => n.id === 'epic:right');
  assert.equal(left.y, right.y);
  assert(left.children.some(n => n.id === 'left-task'));
  assert(right.children.some(n => n.id === 'right-task'));
  for (const child of parent.children) {
    assert(child.x >= 0 && child.y >= 0);
    assert(child.x + child.width <= parent.width);
    assert(child.y + child.height <= parent.height);
  }
});
test('filters never move originally connected tickets into the independent shelf', () => {
  const view = model.prepare(fixture, { search: 'Build API' });
  assert.deepEqual(view.connectedTickets.map(t => t.id), ['td-103']);
  assert.equal(view.independent.length, 0);
  assert.equal(view.visibleEdges.length, 0);
  assert.equal(view.hiddenConnections.get('td-103'), 3);
  assert(view.graph.children.find(t => t.id === 'epic:td-backend').children.some(t => t.id === 'td-103'));
});
test('status, priority, and epic filters keep table/graph selection synchronized by ticket ids', () => {
  const view = model.prepare(fixture, { status: 'open', priority: 'P1', epic: 'td-backend' });
  assert.deepEqual(view.visible.map(t => t.id), ['td-104']);
  assert.equal(model.selectionAfterRefresh('td-104', view.tickets), 'td-104');
  assert.equal(model.selectionAfterRefresh('removed', view.tickets), null);
  assert.equal(model.prepare(fixture, { epic: '__none__' }).visible.length, 5);
});
test('multiple statuses filter table, graph, edges and independent tickets together', () => {
  const data = { tickets: [
    ticket('a', { status: 'open' }), ticket('b', { status: 'in_progress' }),
    ticket('c', { status: 'closed' }), ticket('d', { status: 'in_progress' }),
    ticket('e', { status: 'closed' })
  ], edges: [{ source: 'a', target: 'b' }, { source: 'b', target: 'c' }] };
  const view = model.prepare(data, { statuses: ['open', 'in_progress'] });
  assert.deepEqual(view.visible.map(t => t.id), ['a', 'b', 'd']);
  assert.deepEqual(view.connectedTickets.map(t => t.id), ['a', 'b']);
  assert.deepEqual(view.graph.children.map(t => t.id), ['a', 'b']);
  assert.deepEqual(view.independent.map(t => t.id), ['d']);
  assert.deepEqual(view.visibleEdges, [{ source: 'a', target: 'b' }]);
  assert.equal(view.graph.edges.length, 1);
  assert.equal(view.hiddenConnections.get('b'), 1);
});
test('all statuses includes unknown statuses and an empty selection matches nothing', () => {
  const data = { tickets: [ticket('a'), ticket('b', { status: 'custom' }), ticket('c', { status: null })] };
  assert.equal(model.prepare(data).visible.length, 3);
  assert.equal(model.prepare(data, { statuses: null }).visible.length, 3);
  const empty = model.prepare(data, { statuses: [] });
  assert.equal(empty.visible.length, 0);
  assert.equal(empty.connectedTickets.length, 0);
  assert.equal(empty.independent.length, 0);
  assert.equal(empty.graph.children.length, 0);
  assert.equal(empty.visibleEdges.length, 0);
});
test('multi-status selection intersects search, epic and priority filters', () => {
  const view = model.prepare(fixture, { statuses: ['open', 'in_progress'], priority: 'P1', epic: 'td-backend', search: 'API' });
  assert.deepEqual(view.visible.map(t => t.id), ['td-103']);
  assert.deepEqual(view.connectedTickets.map(t => t.id), ['td-103']);
  assert.equal(view.independent.length, 0);
  assert.equal(view.visibleEdges.length, 0);
});
test('dependency cycles remain visible and carry a warning', () => {
  const view = model.prepare({ tickets: [ticket('a'), ticket('b')], edges: [{ source: 'a', target: 'b' }, { source: 'b', target: 'a' }] });
  assert.equal(view.hasCycle, true);
  assert.equal(view.graph.edges.length, 2);
  assert.equal(view.independent.length, 0);
  assert(view.warnings.some(w => w.includes('cycle')));
});
test('missing prerequisites do not silently classify a ticket as independent', () => {
  const view = model.prepare({ tickets: [ticket('a', { depends_on: ['missing'] })] });
  assert.equal(view.independent.length, 0);
  assert.equal(view.graph.children[0].id, 'a');
  assert.equal(view.hiddenConnections.get('a'), 1);
  assert(view.warnings.some(w => w.includes('missing ticket')));
});
test('dependency declarations are deduplicated and child-parent loops fail safely', () => {
  const view = model.prepare({ tickets: [ticket('a', { parent_id: 'b' }), ticket('b', { parent_id: 'a', depends_on: ['a'] })], edges: [{ source: 'a', target: 'b' }] });
  assert.equal(view.edges.length, 1);
  assert.equal(view.membership.get('a'), null);
  assert.equal(view.membership.get('b'), null);
  assert.equal(view.hasCycle, false);
});
test('sort does not mutate API snapshot and uses numeric identifier order', () => {
  const tickets = [ticket('td-10'), ticket('td-2')];
  assert.deepEqual(model.sortTickets(tickets).map(t => t.id), ['td-2', 'td-10']);
  assert.deepEqual(tickets.map(t => t.id), ['td-10', 'td-2']);
});
test('empty datasets and unmatched filters produce empty valid layout inputs', () => {
  assert.equal(model.prepare({}).graph.children.length, 0);
  assert.equal(model.prepare(fixture, { search: 'does not exist' }).visible.length, 0);
});
test('normalized epic_id null is authoritative even when parent ancestry contains an epic', () => {
  const view = model.prepare({ tickets: [ticket('epic', { type: 'epic' }), ticket('child', { parent_id: 'epic', epic_id: null }), ticket('grandchild', { parent_id: 'child' })] });
  assert.equal(view.membership.get('child'), null);
  assert.equal(view.membership.get('grandchild'), null);
});
test('ten thousand fallback ancestors are visited at most once per prepare pass', () => {
  // Reverse order forces the first lookup to walk the whole chain, without recursion.
  const tickets = Array.from({ length: 10000 }, (_, i) => ticket(`chain-${i}`, { parent_id: i ? `chain-${i - 1}` : 'epic' })).reverse();
  tickets.push(ticket('epic', { type: 'epic' }));
  const view = model.prepare({ tickets });
  assert.equal(view.membership.get('chain-9999'), 'epic');
  assert.equal(view.membership.get('chain-0'), 'epic');
  assert(view.membershipVisits <= tickets.length);
});
test('ten thousand normalized null memberships never follow parent ancestry', () => {
  const tickets = Array.from({ length: 10000 }, (_, i) => ticket(`chain-${i}`, { parent_id: i ? `chain-${i - 1}` : null, epic_id: null }));
  const view = model.prepare({ tickets });
  assert.equal(view.membership.get('chain-9999'), null);
  assert.equal(view.membershipVisits, tickets.length);
});
test('prerequisite index deduplicates declarations and retains unavailable predecessors', () => {
  const view = model.prepare({ tickets: [ticket('a'), ticket('b', { depends_on: ['a', 'missing'] })], edges: [{ source: 'a', target: 'b' }, { source: 'missing', target: 'b' }] });
  assert.deepEqual(view.prerequisites.get('a'), []);
  assert.deepEqual(view.prerequisites.get('b'), ['a', 'missing']);
  assert.equal(view.edges.length, 1);
});
