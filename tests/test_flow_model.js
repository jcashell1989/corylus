const test = require('node:test');
const assert = require('node:assert/strict');
const model = require('../static/flow_model.js');
const fixture = require('../static/flow_demo.json');
function ticket(id, extra = {}) { return { id, title: id, type: 'task', status: 'open', priority: 'P1', ...extra }; }
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
test('independent tickets retain epic membership and task-parent ancestry resolves nearest epic', () => {
  const data = { tickets: [ticket('e', { type: 'epic' }), ticket('parent', { parent_id: 'e' }), ticket('child', { parent_id: 'parent' })], epics: [{ id: 'e', title: 'Epic' }], edges: [] };
  const view = model.prepare(data);
  assert.equal(view.membership.get('child'), 'e');
  assert.deepEqual(view.independent.map(t => t.id), ['parent', 'child']);
  assert.equal(view.visible.length, 3);
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
