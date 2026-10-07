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

function absoluteNodes(graph) {
  const positions = new Map();
  function visit(node, x = 0, y = 0) {
    x += node.x || 0; y += node.y || 0;
    positions.set(node.id, { ...node, x, y });
    (node.children || []).forEach(child => visit(child, x, y));
  }
  visit(graph);
  return positions;
}

function assertHorizontal(layout, pairs) {
  const positions = absoluteNodes(layout);
  for (const [source, target] of pairs) {
    const a = positions.get(source) || positions.get(`epic:${source}`);
    const b = positions.get(target) || positions.get(`epic:${target}`);
    assert(a && b, `${source} and ${target} must remain visible`);
    assert(a.x < b.x,
      `${source} prerequisite x=${a.x} must precede ${target} dependent x=${b.x}`);
  }
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
  const parents = new Map(), rectangles = new Map([['root', { x: 0, y: 0, width: layout.width, height: layout.height }]]);
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
    const id = node.type === 'epic' ? `epic:${node.id}` : node.id;
    if (node.type === 'epic' && !rectangles.has(id)) {
      assert(view.graph.edges.some(edge =>
        edge.ticketSource === node.id && edge.sources.includes('root') ||
        edge.ticketTarget === node.id && edge.targets.includes('root')),
      `${node.id} must remain a box or identify the page frame in its dependencies`);
      continue;
    }
    assert.equal(parents.get(id), epic && rectangles.has(`epic:${epic}`) ? `epic:${epic}` : 'root',
      `${node.id} must remain in its own epic or outside every epic`);
  }
  const edges = edgesOf(layout);
  assert.deepEqual(edges.map(edge => edge.id).sort(), view.graph.edges.map(edge => edge.id).sort());
  for (const edge of edges) {
    assert(edge.sections?.length > 0, `${edge.id} has no routed dependency`);
    function ownsEndpoint(shape, endpoint) {
      if (shape === 'root' && endpoint === 'root') return true;
      for (let id = endpoint; id && id !== 'root'; id = parents.get(id)) {
        if (id === shape) return true;
      }
      return false;
    }
    assert(ownsEndpoint(edge.sections[0].incomingShape, edge.sources[0]),
      `${edge.id} must start at its prerequisite card or enclosing epic boundary`);
    assert(ownsEndpoint(edge.sections[edge.sections.length - 1].outgoingShape, edge.targets[0]),
      `${edge.id} must end at its dependent card or enclosing epic boundary`);
    for (const section of edge.sections) {
      for (const point of [section.startPoint, ...(section.bendPoints || []), section.endPoint]) {
        assert(Number.isFinite(point.x) && Number.isFinite(point.y), `${edge.id} has invalid route`);
      }
      const containerId = edge.container || 'root';
      assert(rectangles.has(containerId), `${edge.id} route container ${containerId} must exist in the rendered graph`);
      const container = rectangles.get(containerId);
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
  const production = await model.layout(view.graph, elk, 1400);
  assertTopology(view, production);
  const productionArea = production.width * production.height;
  t.diagnostic(`production ${production.width.toFixed(1)} × ${production.height.toFixed(1)}, area ${productionArea.toFixed(0)}, route ${routedLength(production).toFixed(0)}`);
  assert(productionArea <= baselineArea * 0.85,
    `production area ${productionArea.toFixed(0)} must improve on baseline ${baselineArea.toFixed(0)} by at least 15%`);
});

test('filter changes relayout visible epic members into genuinely smaller bounds', async () => {
  const fixture = sprawlingFixture();
  const full = await model.layout(model.prepare(fixture).graph, elk, 1400);
  for (const filters of [{ statuses: ['open'] }, { epic: 'epic-2' }, { search: 'e2n2' }]) {
    const view = model.prepare(fixture, filters);
    const layout = await model.layout(view.graph, elk, 1400);
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
  const layout = await model.layout(view.graph, elk, 1400);
  assertTopology(view, layout);
  assert.deepEqual(view.independent.map(node => node.id), []);
  assert(layout.children.find(node => node.id === 'epic:epic-a').children.some(node => node.id === 'independent'));
});

test('real ELK lays out prerequisites left of dependents within root and nested epics', async () => {
  const view = model.prepare({
    tickets: [
      ticket('root-epic', { type: 'epic' }),
      ticket('nested-epic', { type: 'epic', parent_id: 'root-epic' }),
      ...['root-first', 'root-second', 'root-third'].map(id => ticket(id, { parent_id: 'root-epic' })),
      ...['nested-first', 'nested-second', 'nested-third'].map(id => ticket(id, { parent_id: 'nested-epic' }))
    ],
    edges: [
      { source: 'root-first', target: 'root-second' },
      { source: 'root-second', target: 'root-third' },
      { source: 'nested-first', target: 'nested-second' },
      { source: 'nested-second', target: 'nested-third' }
    ]
  });
  for (const width of [1400, 450]) {
    const layout = await model.layout(view.graph, elk, width);
    assertTopology(view, layout);
    assertHorizontal(layout, view.visibleEdges.map(edge => [edge.source, edge.target]));
  }
});

test('root epic dependencies flow horizontally on desktop and preserve order when wrapping', async () => {
  const view = model.prepare({
    tickets: [
      ticket('source-epic', { type: 'epic' }), ticket('target-epic', { type: 'epic' }),
      ticket('source', { parent_id: 'source-epic' }),
      ticket('target', { parent_id: 'target-epic' })
    ],
    edges: [{ source: 'source', target: 'target' }]
  });
  for (const width of [1400, 450]) {
    const layout = await model.layout(view.graph, elk, width);
    assertTopology(view, layout);
    const positions = absoluteNodes(layout);
    const source = positions.get('epic:source-epic'), target = positions.get('epic:target-epic');
    if (width === 1400) {
      assertHorizontal(layout, [['epic:source-epic', 'epic:target-epic'], ['source', 'target']]);
    } else {
      assert(target.y > source.y || target.y === source.y && target.x > source.x,
        'Wrapped root epics must preserve prerequisite-before-dependent reading order');
    }
  }
});

test('dependencies between nested sibling epic boxes induce horizontal ordering across blocks', async () => {
  const view = model.prepare({
    tickets: [
      ticket('root-epic', { type: 'epic' }),
      // Two direct members preserve this epic as a box instead of an umbrella frame.
      ticket('unlinked-one', { parent_id: 'root-epic' }),
      ticket('unlinked-two', { parent_id: 'root-epic' }),
      ticket('target-epic', { type: 'epic', parent_id: 'root-epic' }),
      ticket('source-epic', { type: 'epic', parent_id: 'root-epic' }),
      ticket('source', { parent_id: 'source-epic' }),
      ticket('target', { parent_id: 'target-epic' })
    ],
    edges: [{ source: 'source', target: 'target' }]
  });
  for (const width of [1400, 450]) {
    const layout = await model.layout(view.graph, elk, width);
    assertTopology(view, layout);
    assertHorizontal(layout, [['epic:source-epic', 'epic:target-epic'], ['source', 'target']]);
  }
});

test('dependencies through a nested epic keep disconnected local components in horizontal order', async () => {
  const view = model.prepare({
    tickets: [
      ticket('root-epic', { type: 'epic' }),
      ticket('nested-epic', { type: 'epic', parent_id: 'root-epic' }),
      ticket('target', { parent_id: 'root-epic' }),
      ticket('source', { parent_id: 'root-epic' }),
      ticket('nested-source', { parent_id: 'nested-epic' }),
      ticket('nested-target', { parent_id: 'nested-epic' })
    ],
    edges: [
      { source: 'source', target: 'nested-source' },
      { source: 'source', target: 'nested-epic' },
      { source: 'nested-source', target: 'nested-target' },
      { source: 'nested-target', target: 'target' },
      { source: 'nested-epic', target: 'target' }
    ]
  });
  for (const width of [1400, 450]) {
    const layout = await model.layout(view.graph, elk, width);
    assertTopology(view, layout);
    assertHorizontal(layout, view.visibleEdges.map(edge => [edge.source, edge.target]));
  }
});

test('direct outer dependency and nested detour keep an acyclic diamond horizontal', async () => {
  const view = model.prepare({
    tickets: [
      ticket('E', { type: 'epic' }),
      ticket('a', { parent_id: 'E' }), ticket('b', { parent_id: 'E' }),
      ticket('N', { type: 'epic', parent_id: 'E' }), ticket('n', { parent_id: 'N' })
    ],
    edges: [
      { source: 'a', target: 'b' }, { source: 'a', target: 'n' },
      { source: 'n', target: 'b' }
    ]
  });
  assert.equal(view.hasCycle, false);
  for (const width of [1400, 450]) {
    const layout = await model.layout(view.graph, elk, width);
    assertTopology(view, layout);
    assertHorizontal(layout, view.visibleEdges.map(edge => [edge.source, edge.target]));
    assert.equal(edgesOf(layout).length, 3, 'All three diamond routes must survive');
  }
});

test('unrelated wide no-epic DAG keeps epics first and root wrapping bounded to the viewport', async () => {
  const view = model.prepare({
    tickets: [ticket('E1', { type: 'epic' }), ticket('E2', { type: 'epic' }),
      ticket('e1', { parent_id: 'E1' }), ticket('e2', { parent_id: 'E2' }),
      ...Array.from({ length: 6 }, (_, i) => ticket(`u${i}`)), ticket('shelf')],
    edges: Array.from({ length: 5 }, (_, i) => ({ source: `u${i}`, target: `u${i + 1}` }))
  });
  for (const width of [1400, 450]) {
    const layout = await model.layout(view.graph, elk, width);
    assertTopology(view, layout);
    const positions = absoluteNodes(layout);
    const first = positions.get('epic:E1'), second = positions.get('epic:E2');
    assert.equal(first.y, 16, 'Unrelated wide DAG must not displace the first epic from the top');
    assert(positions.get('u0').y >= Math.max(first.y + first.height, second.y + second.height),
      'Unrelated no-epic DAG belongs after the root epic rows');
    if (width === 1400) assert.equal(second.y, first.y, 'Desktop epics share the top row');
    else {
      assert(second.y > first.y, 'Root epic wrapping must use viewport width, not wide DAG width');
      assert.equal(second.x, first.x, 'Wrapped epic row restarts at the left');
    }
    assertHorizontal(layout, view.visibleEdges.map(edge => [edge.source, edge.target]));
    assert.deepEqual(view.independent.map(node => node.id), ['shelf']);
  }
});

test('page-level diamond splits contracted DAG and preserves dependency order across root wrapping', async () => {
  const view = model.prepare({
    tickets: [ticket('a'), ticket('b'), ticket('N', { type: 'epic' }),
      ticket('n', { parent_id: 'N' })],
    edges: [{ source: 'a', target: 'b' }, { source: 'a', target: 'n' },
      { source: 'n', target: 'b' }]
  });
  assert.equal(view.hasCycle, false);
  for (const width of [1400, 450]) {
    const layout = await model.layout(view.graph, elk, width);
    assertTopology(view, layout);
    const positions = absoluteNodes(layout);
    if (width === 1400) assertHorizontal(layout, view.visibleEdges.map(edge => [edge.source, edge.target]));
    else for (const [source, target] of [['a', 'epic:N'], ['epic:N', 'b'], ['a', 'b']]) {
      const a = positions.get(source), b = positions.get(target);
      assert(b.y > a.y || b.y === a.y && b.x > a.x,
        `${source} prerequisite must precede ${target} in wrapped root reading order`);
    }
    assert.equal(edgesOf(layout).length, 3, 'Every page diamond route must survive');
    assert.deepEqual(view.independent, [], 'Connected no-epic tickets stay on the graph');
  }
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
  assertTopology(view, await model.layout(view.graph, elk, 1400));
});

test('dependency-linked umbrella epics route to the page frame while children remain nested boxes', async () => {
  const view = model.prepare({ tickets: [
    ticket('umbrella', { type: 'epic', epic_id: null }),
    ticket('left', { type: 'epic', epic_id: 'umbrella' }),
    ticket('right', { type: 'epic', epic_id: 'umbrella' }),
    ticket('child', { epic_id: 'left' }),
    ticket('outside', { epic_id: null })
  ], edges: [{ source: 'outside', target: 'umbrella' }, { source: 'left', target: 'right' }] });
  assert(!nodesOf(view.graph).some(node => node.id === 'epic:umbrella'));
  assert.equal(view.graph.edges.find(edge => edge.ticketTarget === 'umbrella').targets[0], 'root');
  const layout = await model.layout(view.graph, elk, 1400);
  assertTopology(view, layout);
  assert.equal(edgesOf(layout).length, 2);
});

test('deep nested epic relayout keeps ELK calls bounded instead of repeating unchanged widths', { timeout: 15000 }, async () => {
  const depth = 12, tickets = [];
  for (let index = 0; index < depth; index++) {
    tickets.push(ticket(`deep-${index}`, {
      type: 'epic', parent_id: index ? `deep-${index - 1}` : null
    }));
  }
  tickets.push(ticket('deep-source', { parent_id: `deep-${depth - 1}` }),
    ticket('deep-target', { parent_id: `deep-${depth - 1}` }));
  const view = model.prepare({ tickets, edges: [{ source: 'deep-source', target: 'deep-target' }] });
  let calls = 0;
  const countingElk = {
    async layout(graph) {
      calls++;
      // A deterministic two-card DAG isolates recursive packing cost from ELK
      // runtime. The real-ELK tests above cover routing and horizontal geometry.
      return {
        ...graph, width: 384, height: 100,
        children: graph.children.map((node, index) => ({ ...node, x: index * 200, y: 0 })),
        edges: graph.edges.map(edge => ({ ...edge, sections: [{
          startPoint: { x: 184, y: 50 }, endPoint: { x: 200, y: 50 },
          incomingShape: edge.sources[0], outgoingShape: edge.targets[0]
        }] }))
      };
    }
  };
  const layout = await model.layout(view.graph, countingElk, 300);
  assertTopology(view, layout);
  assertHorizontal(layout, [['deep-source', 'deep-target']]);
  assert(calls <= depth * 2,
    `${depth} nested epics must need at most ${depth * 2} ELK calls, received ${calls}`);
});

test('production layout preserves geometry and dependencies for 290 tickets within ten seconds', { timeout: 15000 }, async t => {
  const tickets = [], edges = [];
  for (let epic = 0; epic < 10; epic++) {
    const epicId = `perf-epic-${epic}`;
    tickets.push(ticket(epicId, { type: 'epic', epic_id: null }));
    for (let member = 0; member < 28; member++) {
      const id = `perf-${epic}-${member}`;
      tickets.push(ticket(id, { parent_id: epicId, epic_id: epicId }));
      // Several short DAGs reproduce the bounded independent components of
      // real trackers without imposing a single viewport-wide critical path.
      if (member % 4) edges.push({ source: `perf-${epic}-${member - 1}`, target: id });
    }
    if (epic) edges.push({ source: `perf-${epic - 1}-27`, target: `perf-${epic}-0` });
  }
  const started = performance.now();
  const view = model.prepare({ tickets, edges });
  const layout = await model.layout(view.graph, elk, 1400);
  const elapsed = performance.now() - started;
  t.diagnostic(`290 tickets, ${edges.length} dependencies: ${elapsed.toFixed(0)}ms, ${layout.width.toFixed(0)} × ${layout.height.toFixed(0)}`);
  assert.equal(view.visible.length, 290);
  assert.equal(view.independent.length, 0);
  assertTopology(view, layout);
  assert.equal(nodesOf(layout).length, 290);
  assert(elapsed < 10000, `290-ticket layout took ${elapsed.toFixed(0)}ms, exceeding 10000ms`);
});
