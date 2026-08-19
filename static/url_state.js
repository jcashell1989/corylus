/* Hermes Review — URL view-state codec. No DOM. Node and browser both load this. */
(function (root, factory) {
  if (typeof module === "object" && module.exports) {
    module.exports = factory();
  } else {
    root.HermesReviewUrl = factory();
  }
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  const VIEWS = ["home", "review", "queue", "human", "timeline", "stats"];
  const FILTERS = ["all", "low", "high", "approve", "remediate", "split", "human", "thin"];
  const WINDOWS = ["24h", "7d", "all"];
  const AKINDS = ["all", "attempt", "judge", "preflight", "disposition", "reaper", "call"];
  const LANES = ["all", "worker", "worker-escalate", "judge", "judge-escalate"];
  const SECTIONS = ["description", "attempt", "artifacts", "log", "history", "meta"];
  const DEFAULT_OPEN = {
    description: true,
    attempt: true,
    artifacts: false,
    log: false,
    history: true,
    meta: false
  };

  function parse(search) {
    const q = new URLSearchParams(String(search || "").replace(/^\?/, ""));
    const viewRaw = q.get("view");
    const view = VIEWS.includes(viewRaw) ? viewRaw : "home";

    const taskRaw = q.get("task");
    let task = null;
    if (taskRaw) {
      const n = Number(taskRaw);
      task = Number.isInteger(n) && n > 0 ? n : null;
    }

    const cursorRaw = q.get("cursor");
    let cursor = 0;
    if (cursorRaw) {
      const n = Number(cursorRaw);
      cursor = Number.isInteger(n) && n >= 0 ? n : 0;
    }

    const filterRaw = q.get("filter");
    const filter = FILTERS.includes(filterRaw) ? filterRaw : "all";

    const windowRaw = q.get("window");
    const window = WINDOWS.includes(windowRaw) ? windowRaw : "7d";

    const akindRaw = q.get("akind");
    const akind = AKINDS.includes(akindRaw) ? akindRaw : "all";

    const laneRaw = q.get("lane");
    const lane = LANES.includes(laneRaw) ? laneRaw : "all";

    const modelRaw = (q.get("model") || "").trim();
    const model = modelRaw && modelRaw !== "all" ? modelRaw : "all";

    const open = Object.assign({}, DEFAULT_OPEN);
    if (q.has("open")) {
      const keys = (q.get("open") || "").split(",").filter(Boolean);
      SECTIONS.forEach(function (k) { open[k] = false; });
      keys.forEach(function (k) {
        if (SECTIONS.includes(k)) open[k] = true;
      });
    }

    const humanRaw = q.get("human");
    let human = null;
    if (humanRaw) {
      const n = Number(humanRaw);
      human = Number.isInteger(n) && n > 0 ? n : null;
    }

    return {
      view: view, task: task, cursor: cursor, filter: filter,
      window: window, akind: akind, lane: lane, model: model,
      open: open, human: human
    };
  }

  function serialize(s) {
    const q = new URLSearchParams();
    const view = s && s.view;
    const task = s && s.task;
    const cursor = s && s.cursor;
    const filter = s && s.filter;
    const window = s && s.window;
    const akind = s && s.akind;
    const lane = s && s.lane;
    const model = s && s.model;
    const open = (s && s.open) || DEFAULT_OPEN;
    const human = s && s.human;

    if (view && view !== "home") q.set("view", view);
    if (task) q.set("task", String(task));
    if (cursor) q.set("cursor", String(cursor));
    if (filter && filter !== "all") q.set("filter", filter);
    if (window && window !== "7d") q.set("window", window);
    if (akind && akind !== "all") q.set("akind", akind);
    if (lane && lane !== "all") q.set("lane", lane);
    if (model && model !== "all") q.set("model", model);

    const defaulted = SECTIONS.every(function (k) {
      return Boolean(open[k]) === Boolean(DEFAULT_OPEN[k]);
    });
    if (!defaulted) {
      q.set("open", SECTIONS.filter(function (k) { return open[k]; }).join(","));
    }
    if (human) q.set("human", String(human));
    return q.toString();
  }

  function apply(state, parsed) {
    state.view = parsed.view;
    state.viewing = parsed.task;
    state.cursor = parsed.cursor;
    state.filter = parsed.filter;
    state.window = parsed.window;
    state.akind = parsed.akind;
    state.lane = parsed.lane;
    state.model = parsed.model;
    state.open = Object.assign({}, DEFAULT_OPEN, parsed.open);
    state.humanOpen = parsed.human;
  }

  function snapshot(state) {
    return {
      view: state.view,
      task: state.viewing,
      cursor: state.cursor,
      filter: state.filter,
      window: state.window || "7d",
      akind: state.akind || "all",
      lane: state.lane || "all",
      model: state.model || "all",
      open: state.open,
      human: state.humanOpen
    };
  }

  function applyMonitorChip(state, spec) {
    const raw = String(spec || "");
    const cut = raw.indexOf(":");
    if (cut <= 0 || !state) return false;
    const key = raw.slice(0, cut);
    const val = raw.slice(cut + 1);
    if (key === "window") {
      if (!WINDOWS.includes(val)) return false;
      state.window = val;
      return true;
    }
    if (key === "akind") {
      if (!AKINDS.includes(val)) return false;
      state.akind = val;
      return true;
    }
    if (key === "lane") {
      if (!LANES.includes(val)) return false;
      state.lane = val;
      return true;
    }
    if (key === "model") {
      state.model = val || "all";
      return true;
    }
    return false;
  }

  return {
    VIEWS: VIEWS,
    FILTERS: FILTERS,
    WINDOWS: WINDOWS,
    AKINDS: AKINDS,
    LANES: LANES,
    SECTIONS: SECTIONS,
    DEFAULT_OPEN: DEFAULT_OPEN,
    parse: parse,
    serialize: serialize,
    apply: apply,
    snapshot: snapshot,
    applyMonitorChip: applyMonitorChip
  };
});
