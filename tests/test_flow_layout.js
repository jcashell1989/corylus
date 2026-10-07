const test = require('node:test');
const assert = require('node:assert/strict');
const ELK = require('../static/vendor/elk.bundled.js');
const model = require('../static/flow_model.js');

const elk = new ELK();
const baselineOptions = {
  'elk.algorithm': 'layered',
  'elk.direction': 'RIGHT',
  'elk.hierarchyHandling': 'INCLUDE_CHILDREN',
  'elk.edgeRouting': 'ORTHOGONAL',
  'elk.spacing.nodeNode': '24',
  'elk.layered.spacing.nodeNodeBetweenLayers': '20',
  'elk.padding': '[top=16,left=12,bottom=16,right=12]'
};
const epsilon = 0.001;

function layoutGraph(graph) {
  // ELK decorates input nodes/edges. Independent copies keep before/after
  // route measurements from reading the same subsequently overwritten edges.
  return elk.layout(JSON.parse(JSON.stringify(graph)));
}

function ticket(id, extra = {}) {
  return { id, title: id, type: 'task', status: 'open', priority: 'P1', ...extra };
}

function sprawlingFixture() {
  // Cross-epic dependencies pull the compound boxes through several layers.
  // This reproduces the empty space from the original INCLUDE_CHILDREN layout.
  const tickets = [ticket('preflight')], edges = [];
  for (let epic = 0; epic < 5; epic++) {
    tickets.push(ticket(`epic-${epic}`, { type: 'epic' }));
    for (let member = 0; member < 5; member++) {
      const id = `e${epic}n${member}`;
      tickets.push(ticket(id, {
        parent_id: `epic-${epic}`, status: member < 3 ? 'open' : 'closed'
      }));
      edges.push({ source: member ? `e${epic}n${member - 1}` : 'preflight', target: id });
    }
  }
  for (let epic = 0; epic < 4; epic++) {
    edges.push({ source: `e${epic}n4`, target: `e${epic + 1}n1` });
  }
  for (let epic = 2; epic < 5; epic++) {
    edges.push({ source: 'e0n0', target: `e${epic}n4` });
  }
  return { tickets, edges };
}

function nodesOf(graph) {
  return (graph.children || []).flatMap(node => [node, ...nodesOf(node)]);
}

function edgesOf(graph) {
  return [graph, ...nodesOf(graph)].flatMap(node => node.edges || []);
}

function routedLength(graph) {
  let length = 0;
  for (const edge of edgesOf(graph)) {
    for (const section of edge.sections || []) {
      const points = [section.startPoint, ...(section.bendPoints || []), section.endPoint];
      for (let index = 1; index < points.length; index++) {
        length += Math.abs(points[index].x - points[index - 1].x) +
          Math.abs(points[index].y - points[index - 1].y);
      }
    }
  }
  return length;
}

function onBoundary(point, rectangle) {
  const right = rectangle.x + rectangle.width, bottom = rectangle.y + rectangle.height;
  const within = point.x >= rectangle.x - epsilon && point.x <= right + epsilon &&
    point.y >= rectangle.y - epsilon && point.y <= bottom + epsilon;
  return within && [Math.abs(point.x - rectangle.x), Math.abs(point.x - right),
    Math.abs(point.y - rectangle.y), Math.abs(point.y - bottom)].some(distance => distance <= epsilon);
}

function assertGeometry(graph) {
  assert(Number.isFinite(graph.width) && graph.width > 0);
  assert(Number.isFinite(graph.height) && graph.height > 0);
  for (const node of graph.children || []) {
    for (const coordinate of ['x', 'y', 'width', 'height']) {
      assert(Number.isFinite(node[coordinate]), `${node.id} has invalid ${coordinate}`);
    }
    assert(node.x >= -epsilon && node.y >= -epsilon, `${node.id} starts outside ${graph.id}`);
    assert(node.x + node.width <= graph.width + epsilon, `${node.id} exceeds ${graph.id} width`);
    assert(node.y + node.height <= graph.height + epsilon, `${node.id} exceeds ${graph.id} height`);
    if (node.children) assertGeometry(node);
  }
  const siblings = graph.children || [];
  for (let first = 0; first < siblings.length; first++) {
    for (let second = first + 1; second < siblings.length; second++) {
      const a = siblings[first], b = siblings[second];
      const overlapX = Math.min(a.x + a.width, b.x + b.width) - Math.max(a.x, b.x);
      const overlapY = Math.min(a.y + a.height, b.y + b.height) - Math.max(a.y, b.y);
      assert(overlapX <= epsilon || overlapY <= epsilon,
        `${a.id} and ${b.id} overlap inside ${graph.id}`);
    }
  }
}

function assertTopology(view, layout) {
  assertGeometry(layout);
  const laidOut = nodesOf(layout), input = nodesOf(view.graph);
  assert.deepEqual(laidOut.map(node => node.id).sort(), input.map(node => node.id).sort());
  const parents = new Map(), rectangles = new Map([['root', { x: 0, y: 0 }]]);
  function visit(graph, offset = { x: 0, y: 0 }) {
    for (const node of graph.children || []) {
      parents.set(node.id, graph.id);
      const rectangle = { ...node, x: offset.x + node.x, y: offset.y + node.y };
      rectangles.set(node.id, rectangle);
      visit(node, rectangle);
    }
  }
  visit(layout);
  for (const node of view.connectedTickets) {
    const epic = view.membership.get(node.id);
    assert.equal(parents.get(node.id), epic ? `epic:${epic}` : 'root',
      `${node.id} must remain in its own epic or outside every epic`);
  }
  const edges = edgesOf(layout);
  assert.deepEqual(edges.map(edge => edge.id).sort(), view.graph.edges.map(edge => edge.id).sort());
  for (const edge of edges) {
    assert(edge.sections?.length > 0, `${edge.id} has no routed dependency`);
    assert.equal(edge.sections[0].incomingShape, edge.sources[0], `${edge.id} must start at its prerequisite`);
    assert.equal(edge.sections[edge.sections.length - 1].outgoingShape, edge.targets[0],
      `${edge.id} must end at its dependent ticket`);
    for (const section of edge.sections) {
      for (const point of [section.startPoint, ...(section.bendPoints || []), section.endPoint]) {
        assert(Number.isFinite(point.x) && Number.isFinite(point.y), `${edge.id} has invalid route`);
      }
      const container = rectangles.get(edge.container || 'root');
      for (const [point, id] of [[section.startPoint, section.incomingShape],
        [section.endPoint, section.outgoingShape]]) {
        assert(rectangles.has(id), `${edge.id} route endpoint must identify an existing card`);
        assert(onBoundary({ x: point.x + container.x, y: point.y + container.y }, rectangles.get(id)),
          `${edge.id} route must meet ${id}'s card boundary`);
      }
    }
  }
}

test('real ELK keeps compound epic membership and cross-epic dependencies while reducing sprawling bounds', async t => {
  const view = model.prepare(sprawlingFixture());
  const prior = {
    ...view.graph, layoutOptions: baselineOptions,
    children: view.graph.children.map(node => node.children ? {
      ...node, layoutOptions: { 'elk.padding': '[top=44,left=12,bottom=16,right=12]' }
    } : node)
  };
  const baseline = await layoutGraph(prior);
  const compact = await layoutGraph(view.graph);
  assertTopology(view, compact);
  const baselineArea = baseline.width * baseline.height;
  const compactArea = compact.width * compact.height;
  const baselineLength = routedLength(baseline), compactLength = routedLength(compact);
  t.diagnostic(`baseline ${baseline.width.toFixed(1)} × ${baseline.height.toFixed(1)}, area ${baselineArea.toFixed(0)}, route ${baselineLength.toFixed(0)}; compact ${compact.width.toFixed(1)} × ${compact.height.toFixed(1)}, area ${compactArea.toFixed(0)}, route ${compactLength.toFixed(0)}`);
  assert(compactArea <= baselineArea * 0.85,
    `compound layout area ${compactArea.toFixed(0)} must improve on baseline ${baselineArea.toFixed(0)} by at least 15%`);
  assert(compactLength < baselineLength,
    `routed dependency length ${compactLength.toFixed(0)} must improve on baseline ${baselineLength.toFixed(0)}`);
});

test('filter changes relayout visible epic members into genuinely smaller bounds', async () => {
  const fixture = sprawlingFixture();
  const full = await layoutGraph(model.prepare(fixture).graph);
  for (const filters of [{ statuses: ['open'] }, { epic: 'epic-2' }, { search: 'e2n2' }]) {
    const view = model.prepare(fixture, filters);
    const layout = await layoutGraph(view.graph);
    assertTopology(view, layout);
    assert(layout.width * layout.height < full.width * full.height * 0.75,
      `filter ${JSON.stringify(filters)} must shrink the layout area by at least 25%`);
    assert.equal(view.independent.length, 0, 'filtered connected nodes stay on the canvas');
  }
});

test('disconnected dependency components pack without overlapping epics or unassigned tickets', async () => {
  const data = {
    tickets: [
      ticket('epic-a', { type: 'epic' }), ticket('epic-b', { type: 'epic' }),
      ticket('a', { parent_id: 'epic-a' }), ticket('b', { parent_id: 'epic-a' }),
      ticket('c', { parent_id: 'epic-b' }), ticket('d', { parent_id: 'epic-b' }),
      ticket('u'), ticket('v'), ticket('independent', { parent_id: 'epic-a' })
    ],
    edges: [{ source: 'a', target: 'b' }, { source: 'c', target: 'd' }, { source: 'u', target: 'v' }]
  };
  const view = model.prepare(data);
  assertTopology(view, await layoutGraph(view.graph));
  assert.deepEqual(view.independent.map(node => node.id), ['independent']);
});

test('cycles across epic boundaries remain routed and visible in the real ELK layout', async () => {
  const view = model.prepare({
    tickets: [
      ticket('epic', { type: 'epic' }), ticket('a', { parent_id: 'epic' }),
      ticket('b', { parent_id: 'epic' }), ticket('unassigned')
    ],
    edges: [
      { source: 'a', target: 'b' }, { source: 'b', target: 'unassigned' },
      { source: 'unassigned', target: 'a' }
    ]
  });
  assert.equal(view.hasCycle, true);
  assertTopology(view, await layoutGraph(view.graph));
});
