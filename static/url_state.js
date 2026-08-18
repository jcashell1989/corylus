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

    return { view: view, task: task, cursor: cursor, filter: filter, open: open, human: human };
  }

  function serialize(s) {
    const q = new URLSearchParams();
    const view = s && s.view;
    const task = s && s.task;
    const cursor = s && s.cursor;
    const filter = s && s.filter;
    const open = (s && s.open) || DEFAULT_OPEN;
    const human = s && s.human;

    if (view && view !== "home") q.set("view", view);
    if (task) q.set("task", String(task));
    if (cursor) q.set("cursor", String(cursor));
    if (filter && filter !== "all") q.set("filter", filter);

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
    state.open = Object.assign({}, DEFAULT_OPEN, parsed.open);
    state.humanOpen = parsed.human;
  }

  function snapshot(state) {
    return {
      view: state.view,
      task: state.viewing,
      cursor: state.cursor,
      filter: state.filter,
      open: state.open,
      human: state.humanOpen
    };
  }

  return {
    VIEWS: VIEWS,
    FILTERS: FILTERS,
    SECTIONS: SECTIONS,
    DEFAULT_OPEN: DEFAULT_OPEN,
    parse: parse,
    serialize: serialize,
    apply: apply,
    snapshot: snapshot
  };
});
