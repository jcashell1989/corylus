/* Hermes Review — Catkin UI. Data from /api/board. Discuss is Vikunja comments. */
const INK = "#2B241B", MUTED = "#5A5347", GOLD = "#7A6020", GREEN = "#3D6B3E";
const CLAY = "#8B3232", SLATE = "#3A5563", PARCH = "#F5F0E8", SURF = "#EAE3D6";
const VERDICTS = {
  approve:   { label: "approve", color: GREEN, glyph: "✓" },
  remediate: { label: "remediate", color: CLAY, glyph: "↺" },
  split:     { label: "split", color: GOLD, glyph: "⑂" },
  human:     { label: "human", color: SLATE, glyph: "△" },
  thin:      { label: "thin", color: MUTED, glyph: "?" }
};
function judgeChip(j) {
  const verdict = j && j.verdict;
  if (!verdict) return { label: "no judge yet", color: MUTED, glyph: "–", present: false };
  const v = VERDICTS[verdict] || VERDICTS.thin;
  return { label: v.label, color: v.color, glyph: v.glyph, present: true };
}
const CLASSIF = {
  "worker-ready":     { label: "worker:ready", color: GREEN },
  "worker:escalate":  { label: "worker:escalate", color: GOLD },
  "judge-ready":      { label: "judge:ready", color: SLATE },
  "judge:escalate":   { label: "judge:escalate", color: GOLD },
  "needs-review":     { label: "needs-review", color: SLATE },
  "human-only":       { label: "human-only", color: SLATE },
  "blocked":          { label: "blocked", color: MUTED }
};
const SECTIONS = ["description", "attempt", "artifacts", "log", "history", "meta"];
const NAV = [
  ["home", "home", "o"],
  ["review", "review", "r"],
  ["queue", "queue", "q"],
  ["human", "human-only", "h"],
  ["timeline", "activity", "t"],
  ["stats", "metrics", "s"]
];

const state = {
  view: "home",
  board: null,
  cursor: 0,
  viewing: null,
  filter: "all",
  selected: {},
  open: { description: true, attempt: true, artifacts: false, log: false, history: true, meta: false },
  openArt: {},
  openCompare: {},
  railOpen: true,
  chatOpen: true,
  railW: 284,
  chatW: 372,
  reviseW: 0,
  noteMode: null,
  noteText: "",
  customWhen: "",
  chatDraft: "",
  shortcutsOpen: false,
  staged: null,
  last: null,
  toast: "",
  sessionDecided: 0,
  gPending: false,
  humanOpen: null,
  humanDraft: "",
  error: ""
};

function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, c => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
  }[c]));
}
function $(sel, root) { return (root || document).querySelector(sel); }

let applyingUrl = false;
let urlBoot = true;

function currentQuery() {
  return (window.location.search || "").replace(/^\?/, "");
}

function syncUrl() {
  if (applyingUrl) return;
  const next = HermesReviewUrl.serialize(HermesReviewUrl.snapshot(state));
  if (next === currentQuery()) {
    urlBoot = false;
    return;
  }
  const url = next ? ("?" + next) : (window.location.pathname || "/");
  if (urlBoot) {
    history.replaceState(null, "", url);
    urlBoot = false;
  } else {
    history.pushState(null, "", url);
  }
}


async function loadBoard() {
  const r = await fetch("/api/board");
  const data = await r.json();
  if (!r.ok) throw new Error(data.error || "board failed");
  state.board = data;
  state.error = "";
}

function tickets() { return (state.board && state.board.tickets) || []; }
function queueTickets() { return (state.board && state.board.queue) || []; }
function pending() {
  return tickets().filter(t => t.pending && !isFilteredOut(t));
}
function pendingAll() { return tickets().filter(t => t.pending); }
function current() {
  if (state.viewing) {
    const v = tickets().find(t => t.id === state.viewing);
    if (v) return v;
  }
  const p = pending();
  if (!p.length) return tickets()[0] || null;
  return p[Math.min(state.cursor, p.length - 1)];
}
function isFilteredOut(t) {
  const f = state.filter;
  if (f === "all") return false;
  if (f === "low") return (t.judge.confidence || 0) >= 0.7;
  if (f === "high") return (t.priority || 0) < 3;
  return t.judge.verdict !== f;
}
function greeting() {
  const h = new Date().getHours();
  if (h < 5) return "Still up";
  if (h < 12) return "Morning";
  if (h < 17) return "Afternoon";
  if (h < 22) return "Evening";
  return "Late";
}
function ago(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  const m = Math.round((Date.now() - d.getTime()) / 60000);
  if (m < 1) return "just now";
  if (m < 60) return m + "m ago";
  const h = Math.round(m / 60);
  if (h < 36) return h + "h ago";
  return Math.round(h / 24) + "d ago";
}
function sideBySide(diff) {
  const raw = String(diff || "").split("\n");
  if (!raw.length || (raw.length === 1 && !raw[0])) return null;
  const isDiff = raw.some(l => l[0] === "-" || l[0] === "+" || l.indexOf("@@") === 0);
  if (!isDiff) return raw.map(l => ({ left: "", right: l, kind: "add" }));
  const rows = [];
  let dels = [], adds = [];
  const flush = () => {
    const n = Math.max(dels.length, adds.length);
    for (let i = 0; i < n; i++) {
      rows.push({
        left: dels[i] !== undefined ? dels[i] : "",
        right: adds[i] !== undefined ? adds[i] : "",
        kind: dels[i] !== undefined && adds[i] !== undefined ? "mod" : (dels[i] !== undefined ? "del" : "add")
      });
    }
    dels = []; adds = [];
  };
  raw.forEach(l => {
    if (l[0] === "-" && l[1] !== "-") dels.push(l.slice(1));
    else if (l[0] === "+" && l[1] !== "+") adds.push(l.slice(1));
    else { flush(); rows.push({ left: l, right: l, kind: l.indexOf("@@") === 0 ? "hunk" : "ctx" }); }
  });
  flush();
  return rows.length ? rows : null;
}

async function postJSON(url, body) {
  const r = await fetch(url, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-Hermes-Review-Token": window.HERMES_REVIEW_TOKEN
    },
    body: JSON.stringify(body || {})
  });
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data.error || r.statusText);
  return data;
}

async function decide(kind, note, notBefore) {
  const ids = Object.keys(state.selected).filter(k => state.selected[k]).map(Number);
  const targets = ids.length > 1 ? ids : [current() && current().id];
  if (!targets[0]) return;
  const step = HermesReviewDisposition.intent(kind, {
    note: note,
    notBefore: notBefore,
    staged: state.staged
  });
  if (step.action === "openNote") return openNote(step.kind);
  if (step.action === "stage") { state.staged = step.kind; render(); return; }
  kind = step.kind;
  if (step.note !== undefined) note = step.note;
  if (step.notBefore !== undefined) notBefore = step.notBefore;
  try {
    for (const id of targets) {
      await postJSON("/api/tasks/" + id + "/decide", {
        kind, note: note || "", not_before: notBefore || null
      });
    }
    state.last = { ids: targets, kind };
    state.sessionDecided += targets.length;
    state.selected = {};
    state.viewing = null;
    state.noteMode = null;
    state.reviseW = 0;
    state.staged = null;
    state.toast = targets.length > 1 ? ("a verdict applies to all " + targets.length) : kind;
    state.cursor = 0;
    await loadBoard();
  } catch (e) {
    state.error = e.message;
  }
  render();
}

function openNote(kind) {
  if (state.noteMode === kind) { state.noteMode = null; state.reviseW = 0; render(); return; }
  const t = current();
  state.noteMode = kind;
  state.reviseW = kind === "remediate" ? 420 : 0;
  if (kind === "remediate") {
    const notes = (t && t.judge && t.judge.notes) || [];
    state.noteText = notes[notes.length - 1] || "";
  } else {
    state.noteText = "the next heartbeat";
    state.customWhen = "";
  }
  render();
  const el = document.getElementById("note-text");
  if (el) { el.focus(); el.setSelectionRange(el.value.length, el.value.length); }
}

function snoozeUntil() {
  const now = new Date();
  const pacific = new Date(now.toLocaleString("en-US", { timeZone: "America/Los_Angeles" }));
  const iso = (d) => {
    const pad = n => String(n).padStart(2, "0");
    const y = d.getFullYear(), m = pad(d.getMonth() + 1), day = pad(d.getDate());
    const h = pad(d.getHours()), min = pad(d.getMinutes());
    return `${y}-${m}-${day}T${h}:${min}:00-07:00`;
  };
  if (state.customWhen) return state.customWhen.length === 16 ? state.customWhen + ":00-07:00" : state.customWhen;
  if (state.noteText === "tomorrow morning") {
    const d = new Date(pacific); d.setDate(d.getDate() + 1); d.setHours(8, 0, 0, 0); return iso(d);
  }
  if (state.noteText === "Monday morning") {
    const d = new Date(pacific);
    const add = (8 - d.getDay()) % 7 || 7;
    d.setDate(d.getDate() + add); d.setHours(8, 0, 0, 0); return iso(d);
  }
  if (state.noteText === "a week from now") {
    const d = new Date(pacific); d.setDate(d.getDate() + 7); return iso(d);
  }
  const d = new Date(pacific); d.setMinutes(d.getMinutes() + 30); return iso(d);
}

async function sendComment() {
  const t = current();
  const text = state.chatDraft.trim();
  if (!t || !text) return;
  try {
    state.chatDraft = "";
    const data = await postJSON("/api/tasks/" + t.id + "/comment", { text });
    if (data.chat) t.chat = data.chat;
    else await loadBoard();
  } catch (e) { state.error = e.message; }
  render();
}

function navHtml() {
  return NAV.map(([id, label]) => {
    const on = state.view === id;
    return `<a href="#" data-view="${id}" style="font-size:14px;font-weight:700;letter-spacing:0.04em;white-space:nowrap;padding-bottom:2px;border-bottom:2px solid ${on ? GREEN : "transparent"};color:${on ? INK : MUTED}">${label}</a>`;
  }).join("");
}

function renderHome() {
  const b = state.board;
  const p = pendingAll();
  const q = queueTickets();
  const lead = p.length
    ? `${p.length} attempt${p.length === 1 ? " is" : "s are"} waiting on a verdict from you, and hermes opened a few tickets of its own along the way.`
    : q.length
      ? `Nothing is waiting on a verdict. ${q.length} ticket${q.length === 1 ? " is" : "s are"} next up for agents.`
      : "Nothing is waiting on a verdict, and the agent queue is empty.";
  const top = p.slice(0, 3).map(t => {
    const v = judgeChip(t.judge);
    return `<div data-open="${t.id}" style="padding:12px 0;border-top:1px solid rgba(43,36,27,0.10);cursor:pointer">
      <div class="mono" style="font-size:11px;display:flex"><span>${esc(t.identifier)}</span><span style="color:${v.color};margin-left:10px">${esc(v.label)}</span><span style="flex:1"></span><span style="color:${t.priority >= 3 ? CLAY : MUTED}">${esc(t.priority_label)}</span></div>
      <div style="font-size:15.5px;margin-top:4px">${esc(t.title)}</div>
    </div>`;
  }).join("") || `<div class="mono" style="font-size:11px;color:${MUTED};padding:12px 0;border-top:1px solid rgba(43,36,27,0.10)">none</div>`;
  const humans = (b.human_only || []).slice(0, 3).map(t =>
    `<div data-view="human" style="padding:12px 0;border-top:1px solid rgba(43,36,27,0.10);cursor:pointer">
      <div class="mono" style="font-size:11px;color:${SLATE}">${esc(t.identifier)} · human-only</div>
      <div style="font-size:15.5px;margin-top:4px">${esc(t.title)}</div>
    </div>`
  ).join("") || `<div class="mono" style="font-size:11px;color:${MUTED};padding:12px 0;border-top:1px solid rgba(43,36,27,0.10)">none</div>`;
  const acts = (b.activity || []).slice(0, 4).map(a =>
    `<div style="display:flex;gap:12px;padding:10px 0;border-top:1px solid rgba(43,36,27,0.10)">
      <span class="mono" style="width:82px;flex:none;font-size:11px;color:${MUTED}">${esc(a.at)}</span>
      <span style="font-size:14px">${esc(a.text)}</span>
    </div>`
  ).join("");
  const m = b.metrics || {};
  return `<div style="flex:1;overflow-y:auto;padding:40px 46px 60px;animation:fadeUp 500ms cubic-bezier(0.22,1,0.36,1) both">
    <div style="max-width:1000px">
      <div class="rule" style="margin-bottom:20px"></div>
      <h1 class="play" style="font-size:40px;line-height:1.1;margin:0">${greeting()}, Julian</h1>
      <p style="font-size:19px;line-height:1.55;color:${MUTED};margin:16px 0 0">${esc(lead)}</p>
      <div class="mono" style="font-size:11.5px;color:${MUTED};margin-top:14px">${esc(b.date_stamp)} · last ${esc((b.heartbeat || {}).last)} · next ${(b.heartbeat || {}).next}</div>
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:44px 56px;margin-top:56px">
        <div>
          <div class="mono" style="font-size:11px;letter-spacing:0.08em;color:${MUTED};display:flex;gap:12px;align-items:baseline">awaiting your verdict<span style="flex:1;height:1px;background:rgba(43,36,27,0.08)"></span><span>${p.length}</span></div>
          ${top}
          <a href="#" data-view="review" class="mono" style="display:inline-block;margin-top:14px;font-size:11px;color:${GOLD}">start reviewing →</a>
        </div>
        <div>
          <div class="mono" style="font-size:11px;letter-spacing:0.08em;color:${MUTED};display:flex;gap:12px;align-items:baseline">only you can do these<span style="flex:1;height:1px;background:rgba(43,36,27,0.08)"></span></div>
          ${humans}
          <a href="#" data-view="human" class="mono" style="display:inline-block;margin-top:14px;font-size:11px;color:${GOLD}">the human-only list →</a>
        </div>
        <div>
          <div class="mono" style="font-size:11px;letter-spacing:0.08em;color:${MUTED};display:flex;gap:12px;align-items:baseline">next up for agents<span style="flex:1;height:1px;background:rgba(43,36,27,0.08)"></span><span>${q.length}</span></div>
          ${q.slice(0, 3).map(t => {
            const c = CLASSIF[t.classification] || { label: t.classification || "ready", color: MUTED };
            return `<div data-view="queue" style="padding:12px 0;border-top:1px solid rgba(43,36,27,0.10);cursor:pointer">
              <div class="mono" style="font-size:11px;display:flex"><span>${esc(t.identifier)}</span><span style="color:${c.color};margin-left:10px">${esc(c.label)}</span><span style="flex:1"></span><span style="color:${t.priority >= 3 ? CLAY : MUTED}">${esc(t.priority_label)}</span></div>
              <div style="font-size:15.5px;margin-top:4px">${esc(t.title)}</div>
            </div>`;
          }).join("") || `<div class="mono" style="font-size:11px;color:${MUTED};padding:12px 0;border-top:1px solid rgba(43,36,27,0.10)">none</div>`}
          <a href="#" data-view="queue" class="mono" style="display:inline-block;margin-top:14px;font-size:11px;color:${GOLD}">the whole queue →</a>
        </div>
        <div>
          <div class="mono" style="font-size:11px;letter-spacing:0.08em;color:${MUTED};display:flex;gap:12px;align-items:baseline">since you last looked<span style="flex:1;height:1px;background:rgba(43,36,27,0.08)"></span></div>
          ${acts || `<div class="mono" style="font-size:11px;color:${MUTED};padding:12px 0;border-top:1px solid rgba(43,36,27,0.10)">quiet</div>`}
          <a href="#" data-view="timeline" class="mono" style="display:inline-block;margin-top:14px;font-size:11px;color:${GOLD}">all activity →</a>
        </div>
      </div>
      <div style="display:flex;gap:40px;margin-top:56px;padding-top:20px;border-top:1px solid rgba(43,36,27,0.12)">
        ${[
          [m.judge_approve, "judge approve", GREEN],
          [m.pending, "awaiting you", INK],
          [m.agreement, "agreement with the judge", GOLD],
          [state.sessionDecided, "decided this session", INK]
        ].map(([v, l, c]) => `<div><div class="mono" style="font-size:18px;color:${c}">${esc(v)}</div><div class="mono" style="font-size:10.5px;color:${MUTED};margin-top:4px">${l}</div></div>`).join("")}
      </div>
    </div>
  </div>`;
}

function renderRail(t) {
  const p = pending();
  const filters = [
    ["all", "all"], ["approve", "approve"], ["remediate", "remediate"],
    ["split", "split"], ["human", "escalated"], ["low", "low confidence"], ["high", "high +"]
  ];
  const chips = filters.map(([id, lab]) => {
    const on = state.filter === id;
    return `<button data-filter="${id}" style="background:${on ? SURF : "transparent"};border:1px solid ${on ? "rgba(43,36,27,0.32)" : "rgba(43,36,27,0.18)"};border-radius:2px;padding:3px 7px;font-family:'Maple Mono NF',monospace;font-size:10px;color:${on ? INK : MUTED};cursor:pointer">${lab}</button>`;
  }).join("");
  const selN = Object.values(state.selected).filter(Boolean).length;
  const header = selN ? `${selN} selected · shift-click to add` : (p.length ? `${p.length} awaiting review` : "all decided");
  const rows = tickets().filter(x => x.pending || state.filter !== "all").concat(
    tickets().filter(x => !x.pending && x.disposition)
  );
  const seen = new Set();
  const list = [];
  pending().forEach(x => { seen.add(x.id); list.push(x); });
  tickets().forEach(x => { if (!seen.has(x.id) && (x.disposition || !x.pending)) list.push(x); });
  const rowHtml = list.map(item => {
    const v = judgeChip(item.judge);
    const active = t && item.id === t.id;
    const sel = !!state.selected[item.id];
    const decided = !item.pending;
    return `<div data-open="${item.id}" data-shift="1" style="padding:11px 18px 12px;border-top:1px solid rgba(43,36,27,0.10);cursor:pointer;background:${active || sel ? SURF : "transparent"};border-left:2px solid ${active || sel ? GREEN : "transparent"};opacity:${decided ? (active ? 0.8 : 0.45) : 1}">
      <div class="mono" style="font-size:11px;color:${MUTED};display:flex;gap:8px">
        <span>${esc(item.identifier)}</span><span style="flex:1"></span>
        <span style="color:${GREEN}">${sel ? "×" : ""}</span>
        <span style="color:${v.color}">${v.glyph}</span>
      </div>
      <div style="font-size:14px;line-height:1.35;margin-top:4px">${esc(item.title)}</div>
      <div class="mono" style="font-size:10px;color:${MUTED};margin-top:5px">${decided ? esc((item.disposition && item.disposition.kind) || "decided") + " · click to revisit" : (v.present ? `${esc(v.label)} · ${(item.judge.confidence || 0).toFixed(2)}` : esc(v.label))}</div>
    </div>`;
  }).join("");
  if (!state.railOpen) return "";
  return `<aside style="width:${state.railW}px;flex:none;border-right:1px solid rgba(43,36,27,0.12);overflow-y:auto;padding:18px 0 40px">
    <div class="mono" style="padding:0 18px 12px;font-size:11px;letter-spacing:0.08em;color:${MUTED}">${esc(header)}</div>
    <div style="padding:0 18px 14px;display:flex;flex-wrap:wrap;gap:6px">${chips}</div>
    ${rowHtml}
  </aside><div class="handle" data-drag="rail"></div>`;
}

function section(key, label, inner) {
  const open = state.open[key];
  return `<div>
    <div data-section="${key}" style="display:flex;align-items:baseline;gap:12px;cursor:pointer;padding:16px 0;border-top:1px solid rgba(43,36,27,0.12)">
      <span class="mono" style="font-size:11px;letter-spacing:0.08em;color:${MUTED}">${label}</span>
      <span style="flex:1;height:1px;background:rgba(43,36,27,0.08)"></span>
      <span class="mono" style="font-size:11px;color:${MUTED}">${open ? "−" : "+"}</span>
    </div>
    ${open ? `<div style="padding:0 0 24px;animation:fadeUp 320ms cubic-bezier(0.22,1,0.36,1) both">${inner}</div>` : ""}
  </div>`;
}

function renderTicket(t) {
  if (!t) {
    return `<div style="width:100%;max-width:1000px;padding-top:80px">
      <div class="rule" style="margin-bottom:22px"></div>
      <h1 class="play" style="font-size:38px;margin:0 0 12px">Nothing left to judge</h1>
      <p style="font-size:17px;line-height:1.6;color:${MUTED};max-width:56ch">Every attempt has a verdict. Hermes picks up the revisions on the next heartbeat.</p>
      <div class="mono" style="font-size:11.5px;color:${MUTED}">${state.sessionDecided} decided this session</div>
    </div>`;
  }
  const v = judgeChip(t.judge);
  const notes = (t.judge.notes || []).map(n => `<p style="font-size:16px;line-height:1.6;margin:14px 0 0;max-width:62ch">${esc(n)}</p>`).join("");
  const checks = (t.judge.checks || []).map(c =>
    `<div class="mono" style="display:flex;gap:10px;font-size:12px;line-height:1.5">
      <span style="color:${c.pass ? GREEN : CLAY};width:12px">${c.pass ? "✓" : "×"}</span>
      <span>${esc(c.label)}</span><span style="color:${MUTED}">${esc(c.note || "")}</span>
    </div>`
  ).join("");
  const labels = (t.labels || []).map(l => `<span class="chip">${esc(l)}</span>`).join("");
  const desc = (t.description || []).map(p => `<p style="font-size:17px;line-height:1.6;margin:0 0 14px;max-width:64ch">${esc(p)}</p>`).join("") || `<p style="color:${MUTED}">no description</p>`;
  const sum = (t.attempt.summary || []).map(p => `<p style="font-size:17px;line-height:1.6;margin:0 0 14px;max-width:64ch">${esc(p)}</p>`).join("") || `<p style="color:${MUTED}">no attempt machine comment</p>`;
  const arts = (t.artifacts || []).map((a, i) => {
    const open = !!(state.openArt[t.id] && state.openArt[t.id][i]);
    const parsed = open ? sideBySide(a.diff) : null;
    const isNew = parsed && parsed.every(r => r.kind === "add");
    let body = "";
    if (open && parsed && isNew) {
      body = `<div class="mono" style="font-size:10px;color:${MUTED};margin-bottom:6px">new · ${esc(a.detail)}</div>
        <div style="background:${SURF};border-radius:6px;padding:14px 16px">${parsed.map(r => `<div class="mono" style="font-size:12px;line-height:1.65;white-space:pre-wrap">${esc(r.right)}</div>`).join("")}</div>`;
    } else if (open && parsed) {
      body = `<div style="display:flex;gap:20px" class="mono" style="font-size:10px;color:${MUTED}"><span style="flex:1">before</span><span style="flex:1">after</span></div>
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:1px;background:rgba(43,36,27,0.10);border-radius:6px;overflow:hidden;margin-top:6px">
          ${parsed.map(r => {
            const hunk = r.kind === "hunk";
            const lbg = hunk ? SURF : (r.kind === "del" || r.kind === "mod" ? "rgba(139,50,50,0.09)" : PARCH);
            const rbg = hunk ? SURF : (r.kind === "add" || r.kind === "mod" ? "rgba(61,107,62,0.10)" : PARCH);
            return `<span style="background:${lbg};padding:2px 12px;white-space:pre-wrap;font-family:'Maple Mono NF',monospace;font-size:12px;line-height:1.6">${esc(r.left || " ")}</span>
                    <span style="background:${rbg};padding:2px 12px;white-space:pre-wrap;font-family:'Maple Mono NF',monospace;font-size:12px;line-height:1.6">${esc(r.right || " ")}</span>`;
          }).join("")}
        </div>`;
    } else if (open) {
      body = `<div style="color:${MUTED};font-size:14px">no line-level diff captured — ${esc(a.kind)}, ${esc(a.detail)}</div>`;
    }
    return `<div>
      <div data-art="${t.id}:${i}" style="display:flex;gap:14px;padding:10px 0;border-bottom:1px solid rgba(43,36,27,0.10);font-family:'Maple Mono NF',monospace;font-size:12px;cursor:pointer">
        <span style="color:${MUTED};width:64px">${esc(a.kind)}</span>
        <span>${esc(a.name)}</span><span style="flex:1"></span>
        <span style="color:${MUTED}">${esc(a.detail)}</span>
        <span style="color:${MUTED}">${open ? "−" : "+"}</span>
      </div>
      ${open ? `<div style="padding:12px 0 20px">${body}</div>` : ""}
    </div>`;
  }).join("") || `<div style="color:${MUTED};font-size:14px">no artifacts — add git pointers on post-attempt to get a diff here</div>`;
  const log = (t.log || []).map(l =>
    `<div class="mono" style="display:flex;gap:14px;font-size:12px"><span style="color:${MUTED}">${esc(l.at)}</span><span style="color:${GREEN};width:52px">${esc(l.level)}</span><span>${esc(l.msg)}</span></div>`
  ).join("") || `<div style="color:${MUTED}">no run log captured</div>`;
  const hist = (t.history || []).map((h, i) => {
    const open = !!(state.openCompare[t.id] && state.openCompare[t.id][i]);
    return `<div style="border-left:1px solid rgba(43,36,27,0.18);padding-left:16px">
      <div class="mono" style="font-size:11px;color:${MUTED}">${esc(h.head)}</div>
      <p style="font-size:16px;line-height:1.55;margin:6px 0 0;max-width:62ch">${esc(h.note)}</p>
      ${h.comparable ? `<button data-compare="${t.id}:${i}" style="margin-top:10px;background:none;border:0;padding:0;font-family:'Maple Mono NF',monospace;font-size:11px;color:${GOLD};cursor:pointer;text-decoration:underline">compare with the current attempt ${open ? "−" : "+"}</button>` : ""}
      ${open ? `<div style="display:grid;grid-template-columns:1fr 1fr;gap:1px;background:rgba(43,36,27,0.10);border-radius:6px;margin-top:14px">
        <div style="background:${PARCH};padding:14px 16px"><div class="mono" style="font-size:10px;color:${MUTED};margin-bottom:8px">then</div><p style="margin:0;font-size:15px">${esc(h.thenText)}</p></div>
        <div style="background:${PARCH};padding:14px 16px"><div class="mono" style="font-size:10px;color:${GREEN};margin-bottom:8px">now</div><p style="margin:0;font-size:15px">${esc(h.nowText)}</p></div>
      </div>` : ""}
    </div>`;
  }).join("") || `<div style="color:${MUTED}">no prior attempts</div>`;
  const meta = [
    ["task id", t.id], ["project", t.project], ["assignee", (t.assignees || []).join(", ") || "—"],
    ["labels", (t.labels || []).join(", ")], ["priority", `${t.priority} · ${t.priority_label}`],
    ["due_date", t.due_date || "—"], ["created", t.created], ["done", String(t.done)], ["percent_done", t.percent_done]
  ].map(([k, v]) => `<span style="color:${MUTED}">${esc(k)}</span><span>${esc(v)}</span>`).join("");
  return `<div style="width:100%;max-width:1000px">
    <div class="mono" style="display:flex;gap:10px;font-size:12px;color:${MUTED}">
      <a href="${esc(t.href)}" target="_blank" style="text-decoration:underline;text-underline-offset:3px">${esc(t.identifier)} ↗</a>
      <span>·</span><span>${esc(t.project)}</span>
      <span>·</span><span>attempt ${t.attempt.n || 0} of ${t.attempt.of || 0}</span>
      <span>·</span><span>${esc(t.attempt.finished_at ? ago(t.attempt.finished_at) : "")}</span>
    </div>
    <h1 class="play" style="font-size:38px;line-height:1.14;margin:14px 0 10px">${esc(t.title)}</h1>
    <div style="display:flex;flex-wrap:wrap;gap:8px;margin-bottom:30px">${labels}</div>
    <div class="rule" style="margin-bottom:22px"></div>
    <div style="background:${SURF};padding:26px 28px 28px">
      <div class="mono" style="font-size:11px;letter-spacing:0.08em;color:${MUTED}">judge${v.present && t.judge.model ? " · " + esc(t.judge.model) : ""}</div>
      <div style="display:flex;align-items:baseline;gap:16px;margin-top:10px">
        <div style="font-size:27px;font-weight:700;color:${v.color}">${esc(v.label)}</div>
        ${v.present ? `<div style="flex:1;min-width:140px;display:flex;align-items:center;gap:10px">
          <div style="flex:1;height:2px;background:rgba(43,36,27,0.14);position:relative">
            <div style="position:absolute;left:0;top:0;bottom:0;background:${v.color};width:${Math.round((t.judge.confidence || 0) * 100)}%"></div>
          </div>
          <span class="mono" style="font-size:11px;color:${MUTED}">confidence ${(t.judge.confidence || 0).toFixed(2)}</span>
        </div>` : ""}
      </div>
      ${notes}
      <div style="display:flex;flex-direction:column;gap:7px;margin-top:20px;padding-top:16px;border-top:1px solid rgba(43,36,27,0.14)">${checks}</div>
    </div>
    <div style="margin-top:34px">
      ${section("description", "01 · original ticket", desc + `<div class="mono" style="font-size:11px;color:${MUTED};margin-top:6px">filed ${esc(t.created)} · classified ${esc(t.classification)}</div>`)}
      ${section("attempt", "02 · hermes attempt", sum + `<div class="mono" style="font-size:11px;color:${MUTED}">${esc(t.attempt.stats)}</div>`)}
      ${section("artifacts", "03 · artifacts + diff", arts)}
      ${section("log", "04 · run log", log)}
      ${section("history", "05 · prior attempts", hist)}
      ${section("meta", "06 · vikunja metadata", `<div style="display:grid;grid-template-columns:150px 1fr;gap:8px 20px" class="mono" style="font-size:12px">${meta}</div>`)}
    </div>
  </div>`;
}

function actionBtn(kind, label, key, decided) {
  const on = decided === kind;
  const fill = (!decided && kind === "approve") || on;
  return `<div style="display:flex;flex-direction:column;gap:7px">
    <div style="height:2px;background:${on ? GREEN : "transparent"}"></div>
    <button data-act="${kind}" class="${fill ? "btn btn-fill" : "btn"}" style="opacity:${decided && !on ? 0.4 : 1};font-weight:${on ? 700 : 400};padding:${kind === "approve" ? "10px 18px" : "10px 16px"}">${label}<span class="mono" style="font-size:11px;opacity:0.6;margin-left:10px">${key}</span></button>
  </div>`;
}

function renderReview() {
  const t = current();
  const decided = t && t.disposition && t.disposition.kind;
  const msgs = (t && t.chat) || [];
  const chat = msgs.map(m =>
    `<div><div class="mono" style="font-size:10px;letter-spacing:0.06em;color:${m.who === "me" ? GOLD : MUTED};margin-bottom:5px">${esc(m.who)}</div>
     <p style="font-size:15px;line-height:1.6;margin:0">${esc(m.text)}</p></div>`
  ).join("") || `<div class="mono" style="font-size:11px;color:${MUTED}">⌘↵ posts a Vikunja comment. Mention @bot-hermes-agent and Hermes replies on the next preflight.</div>`;
  const pause = "";
  const revise = state.noteMode === "remediate" ? `<div class="handle" data-drag="revise"></div>
    <aside style="width:${state.reviseW}px;flex:none;overflow:hidden;transition:width 400ms cubic-bezier(0.22,1,0.36,1);background:${SURF};display:flex;flex-direction:column">
      <div class="mono" style="padding:16px 22px 12px;border-bottom:1px solid rgba(43,36,27,0.14);font-size:11px;letter-spacing:0.08em;color:${MUTED}">revise note</div>
      <div style="flex:1;padding:16px 22px 0;display:flex;flex-direction:column">
        <textarea id="note-text" style="flex:1;background:${PARCH};border:1px solid rgba(43,36,27,0.24);border-radius:2px;padding:14px 15px;font-size:16px;line-height:1.6;resize:none">${esc(state.noteText)}</textarea>
      </div>
      <div style="padding:14px 22px 18px;display:flex">
        <button class="btn btn-fill" data-act="confirm-revise">send back ⌘↵</button>
        <span style="flex:1"></span>
        <button data-act="cancel-note" style="background:none;border:0;font-family:'Maple Mono NF',monospace;font-size:11px;color:${MUTED};cursor:pointer">esc</button>
      </div>
    </aside>` : "";
  return `<div style="flex:1;display:flex;min-height:0;overflow-x:auto">
    ${renderRail(t)}
    <section style="flex:1;display:flex;flex-direction:column;min-width:580px">
      <div style="flex:1;display:flex;min-height:0">
        <div style="flex:1;min-width:0;overflow-y:scroll;scrollbar-gutter:stable;padding:38px 46px 30px;display:flex;justify-content:center">${renderTicket(t)}</div>
        ${revise}
      </div>
      <div style="flex:none;border-top:1px solid rgba(43,36,27,0.12);padding:14px 46px 16px;display:flex;flex-wrap:wrap;gap:10px;align-items:flex-start">
        ${actionBtn("approve", "approve", "a", decided)}
        ${actionBtn("remediate", "revise", "r", decided)}
        ${actionBtn("noAction", "discard work", "c", decided)}
        ${actionBtn("human", "human-only", "h", decided)}
        ${actionBtn("snooze", "snooze", "s", decided)}
        <div style="display:flex;flex-direction:column;gap:7px">
          <div style="height:2px;background:transparent"></div>
          <button data-act="undo" class="btn" style="color:${state.last ? GOLD : MUTED};border-color:${state.last ? "rgba(122,96,32,0.45)" : "rgba(43,36,27,0.14)"};opacity:${state.last ? 1 : 0.4}">undo<span class="mono" style="font-size:11px;margin-left:10px">u</span></button>
        </div>
        <div style="flex:1"></div>
        <div class="mono" style="font-size:11px;color:${MUTED};padding:8px 0;display:flex;gap:8px;align-items:center">
          <span>${esc(state.toast)}</span>
          <button data-act="toggle-rail" class="btn" style="padding:5px 9px;font-size:11px;color:${state.railOpen ? INK : MUTED}">queue [</button>
          <button data-act="toggle-chat" class="btn" style="padding:5px 9px;font-size:11px;color:${state.chatOpen ? INK : MUTED}">chat ]</button>
          <button data-act="shortcuts" class="btn" style="padding:5px 9px;font-size:11px">?</button>
        </div>
      </div>
    </section>
    ${state.chatOpen && t ? `<div class="handle" data-drag="chat"></div>
      <aside style="width:${state.chatW}px;flex:none;border-left:1px solid rgba(43,36,27,0.12);display:flex;flex-direction:column;min-height:0">
        <div class="mono" style="padding:16px 20px 12px;border-bottom:1px solid rgba(43,36,27,0.10);font-size:11px;letter-spacing:0.08em;color:${MUTED}">discuss · ${esc(t.identifier)}</div>
        <div id="chat-scroll" style="flex:1;overflow-y:auto;padding:18px 20px 10px;display:flex;flex-direction:column;gap:18px">${chat}${pause}</div>
        <div style="flex:none;border-top:1px solid rgba(43,36,27,0.10);padding:12px 20px 16px">
          <textarea id="chat-draft" rows="2" placeholder="write a comment" style="width:100%;background:${PARCH};border:1px solid rgba(43,36,27,0.20);border-radius:2px;padding:10px 12px;font-size:15px;resize:none">${esc(state.chatDraft)}</textarea>
          <div style="display:flex;margin-top:8px"><button data-act="send-chat" style="background:none;border:0;font-family:'Maple Mono NF',monospace;font-size:11px;color:${GOLD};cursor:pointer;text-decoration:underline">send ⌘↵</button><span style="flex:1"></span><span class="mono" style="font-size:11px;color:${MUTED}">/ to focus</span></div>
        </div>
      </aside>` : ""}
  </div>`;
}

function renderQueue() {
  const rows = queueTickets().map(t => {
    const c = CLASSIF[t.classification] || { label: t.classification || "ready", color: MUTED };
    const bits = [];
    if (t.snoozed) bits.push("snoozed");
    if ((t.labels || []).includes("worker:escalate")) bits.push("escalate");
    const sub = bits.length
      ? `<div class="mono" style="font-size:10.5px;color:${GOLD};margin-top:4px">${esc(bits.join(" · "))}</div>`
      : "";
    return `<div style="display:grid;grid-template-columns:110px 1fr 150px 100px 130px;gap:0;border-top:1px solid rgba(43,36,27,0.10)">
      <div style="padding:12px 12px 12px 0" class="mono"><a href="${esc(t.href)}" target="_blank">${esc(t.identifier)} ↗</a></div>
      <div style="padding:12px 12px 12px 0">${esc(t.title)}${sub}</div>
      <div style="padding:12px;color:${c.color}" class="mono">${esc(c.label)}</div>
      <div style="padding:12px;color:${t.priority >= 3 ? CLAY : MUTED}" class="mono">${esc(t.priority_label)}</div>
      <div style="padding:12px" class="mono">${esc(ago(t.age))}</div>
    </div>`;
  }).join("") || `<div class="mono" style="color:${MUTED};padding:12px 0;border-top:1px solid rgba(43,36,27,0.10)">empty</div>`;
  return `<div style="flex:1;overflow-y:auto;padding:40px 46px 60px;animation:fadeUp 500ms cubic-bezier(0.22,1,0.36,1) both">
    <h1 class="play" style="font-size:40px;margin:0 0 28px">Queue</h1>
    <div class="rule" style="margin-bottom:12px"></div>
    <div class="mono" style="font-size:11px;letter-spacing:0.08em;color:${MUTED};margin-bottom:8px">next up</div>
    <div style="max-width:1160px">${rows}</div>
  </div>`;
}

function renderHuman() {
  const rows = (state.board.human_only || []).map(t => {
    const open = state.humanOpen === t.id;
    return `<div style="max-width:720px;border-top:1px solid rgba(43,36,27,0.10);padding:14px 0">
      <div data-human="${t.id}" style="cursor:pointer">
        <div class="mono" style="font-size:11px;color:${MUTED}">${esc(t.identifier)} · ${esc(t.classification)} · ${esc(t.priority_label)} · ${open ? "−" : "+"}</div>
        <div style="font-size:19px;margin-top:6px">${esc(t.title)}</div>
        <div class="mono" style="font-size:11px;color:${MUTED};margin-top:4px">${t.due_date ? "due " + esc(t.due_date) : "no due date"}</div>
      </div>
      ${open ? `<div style="border-left:1px solid rgba(43,36,27,0.18);padding-left:16px;margin-top:12px">
        ${(t.description || []).map(p => `<p style="font-size:15px;line-height:1.6">${esc(p)}</p>`).join("")}
        ${(t.chat || []).map(m => `<div style="margin-top:10px"><div class="mono" style="font-size:10px;color:${MUTED}">${esc(m.who)}</div><div style="font-size:15px">${esc(m.text)}</div></div>`).join("")}
        <textarea data-humandraft="${t.id}" rows="2" style="width:100%;margin-top:12px;background:${PARCH};border:1px solid rgba(43,36,27,0.24);border-radius:2px;padding:10px">${esc(state.humanDraft)}</textarea>
        <div style="display:flex;gap:12px;margin-top:10px;flex-wrap:wrap">
          <button class="btn" data-human-act="note:${t.id}">add note</button>
          <button class="btn" data-human-act="${t.done ? "reopen" : "done"}:${t.id}">${t.done ? "reopen" : "mark done"}</button>
          <button data-human-act="hand:${t.id}" style="background:none;border:0;font-family:'Maple Mono NF',monospace;font-size:11px;color:${GOLD};cursor:pointer;text-decoration:underline">hand to hermes instead</button>
          <a href="${esc(t.href)}" target="_blank" class="mono" style="font-size:11px;margin-left:auto">open in vikunja ↗</a>
        </div>
      </div>` : ""}
    </div>`;
  }).join("") || `<div class="mono" style="color:${MUTED}">no human-only tasks</div>`;
  return `<div style="flex:1;overflow-y:auto;padding:40px 46px 60px;animation:fadeUp 500ms cubic-bezier(0.22,1,0.36,1) both">
    <h1 class="play" style="font-size:40px;margin:0 0 28px">Human-only</h1>${rows}
  </div>`;
}

function renderTimeline() {
  const rows = (state.board.activity || []).map(a =>
    `<div style="display:flex;gap:16px;padding:12px 0;border-top:1px solid rgba(43,36,27,0.10);max-width:900px">
      <span class="mono" style="width:112px;font-size:12px;color:${MUTED}">${esc(a.at)}</span>
      <span class="mono" style="width:88px;font-size:12px;color:${a.kind === "judged" ? GREEN : GOLD}">${esc(a.kind)}</span>
      <span style="flex:1;font-size:15px">${esc(a.text)}</span>
      <a href="#" data-open="${a.id}" class="mono" style="font-size:11px">${esc(a.ref)} ↗</a>
    </div>`
  ).join("") || `<div class="mono" style="color:${MUTED}">no activity yet</div>`;
  return `<div style="flex:1;overflow-y:auto;padding:40px 46px 60px;animation:fadeUp 500ms cubic-bezier(0.22,1,0.36,1) both">
    <h1 class="play" style="font-size:40px;margin:0 0 28px">Agent activity</h1>${rows}
  </div>`;
}

function bar(label, value, n, d, color) {
  const w = d ? Math.round((n / d) * 100) : 0;
  return `<div style="margin-bottom:18px">
    <div style="display:flex;gap:12px"><span>${esc(label)}</span><span class="mono" style="margin-left:auto">${esc(value)}</span></div>
    <div style="height:2px;background:rgba(43,36,27,0.12);margin-top:8px"><div style="height:2px;width:${w}%;background:${color}"></div></div>
  </div>`;
}

function renderStats() {
  const m = state.board.metrics || {};
  const d = m.open_judged || 1;
  return `<div style="flex:1;overflow-y:auto;padding:40px 46px 60px;animation:fadeUp 500ms cubic-bezier(0.22,1,0.36,1) both;max-width:720px">
    <h1 class="play" style="font-size:40px;margin:0 0 28px">Metrics</h1>
    ${bar("approved (judge)", m.judge_approve, m.judge_approve, d, GREEN)}
    ${bar("sent back (judge remediate)", m.judge_remediate, m.judge_remediate, d, CLAY)}
    ${bar("thin / insufficient evidence", m.judge_thin, m.judge_thin, d, MUTED)}
    ${bar("escalate to human (judge)", m.judge_human, m.judge_human, d, SLATE)}
    ${bar("awaiting your verdict", m.pending, m.pending, d, GREEN)}
    <div style="border-top:1px solid rgba(43,36,27,0.12);padding-top:24px;margin-top:12px">
      <div style="display:flex;gap:12px;margin-bottom:16px"><span class="mono" style="width:92px;color:${GOLD}">${esc(m.agreement)}</span><span style="font-weight:700;width:230px">agreement with the judge</span><span style="color:${MUTED}">Only counted when you have written a Hermes Review disposition. Empty until you start using the action bar.</span></div>
      <div style="display:flex;gap:12px"><span class="mono" style="width:92px;color:${MUTED}">—</span><span style="font-weight:700;width:230px">classifier error rate</span><span style="color:${MUTED}">No classifier lives in Vikunja yet — not invented.</span></div>
    </div>
  </div>`;
}

function overlays() {
  let html = "";
  if (state.error) html += `<div style="position:fixed;bottom:16px;left:22px;background:${CLAY};color:${PARCH};padding:8px 12px;font-size:13px;z-index:30">${esc(state.error)}</div>`;
  if (state.shortcutsOpen) {
    const keys = [
      ["j / k", "next / previous"], ["a", "stage approve"], ["r", "revise"], ["c", "stage discard"],
      ["h", "human-only"], ["s", "snooze"], ["u", "undo"], ["1–6", "toggle sections"],
      ["[ / ]", "queue / discuss"], ["g then o/r/q/h/t/s", "go to view"], ["/", "focus discuss"], ["?", "this card"]
    ];
    html += `<div class="scrim" data-act="close-overlay"><div class="card" onclick="event.stopPropagation()">
      <div class="rule" style="margin-bottom:16px"></div>
      <h2 class="play" style="font-size:28px;margin:0 0 18px">Keys</h2>
      <div style="display:grid;grid-template-columns:70px 1fr;gap:8px 16px">
        ${keys.map(([k, w]) => `<span class="mono" style="color:${GOLD}">${k}</span><span style="font-size:15px">${w}</span>`).join("")}
      </div>
      <div class="mono" style="font-size:11px;color:${MUTED};margin-top:18px">esc to close</div>
    </div></div>`;
  }
  if (state.noteMode === "snooze") {
    const choices = [
      ["the next heartbeat", "in ~30 min"],
      ["tomorrow morning", "08:00"],
      ["Monday morning", "next Monday 08:00"],
      ["a week from now", "+7 days"]
    ];
    html += `<div class="scrim" data-act="close-overlay"><div class="card" style="max-width:460px" onclick="event.stopPropagation()">
      <div class="rule" style="margin-bottom:16px"></div>
      <h2 class="play" style="font-size:26px;margin:0 0 8px">Snooze ${esc((current() || {}).identifier || "")}</h2>
      <div class="mono" style="font-size:11px;color:${MUTED};margin-bottom:14px">until when?</div>
      ${choices.map(([lab, when]) => `<div data-snooze="${esc(lab)}" style="display:flex;gap:10px;padding:8px 0;cursor:pointer;font-size:15px">
        <span class="mono">${state.noteText === lab ? "[×]" : "[ ]"}</span><span>${lab}</span><span class="mono" style="margin-left:auto;color:${MUTED}">${when}</span>
      </div>`).join("")}
      <div style="display:flex;gap:10px;align-items:center;margin-top:8px">
        <span class="mono" style="font-size:12px">${state.customWhen ? "[×]" : "[ ]"}</span>
        <input id="custom-when" type="datetime-local" value="${esc(state.customWhen)}" style="border:1px solid rgba(43,36,27,0.24);background:${PARCH};padding:6px 8px;border-radius:2px">
      </div>
      <button class="btn btn-fill" data-act="confirm-snooze" style="margin-top:18px">snooze until ${esc(state.customWhen || state.noteText)}</button>
    </div></div>`;
  }
  if (state.staged === "noAction") {
    html += `<div class="scrim" data-act="close-overlay"><div class="card" style="max-width:460px" onclick="event.stopPropagation()">
      <div style="width:32px;height:2px;background:${CLAY};margin-bottom:16px"></div>
      <h2 class="play" style="font-size:26px;margin:0 0 12px">Discard the work on ${esc((current() || {}).identifier || "")}?</h2>
      <p style="font-size:16px;line-height:1.55;color:${MUTED}">The attempt is thrown away and the ticket closes with no action. Hermes will not pick it up again.</p>
      <button class="btn" data-act="confirm-stage" style="margin-top:16px;background:${CLAY};color:${PARCH};border-color:${CLAY}">confirm discard</button>
    </div></div>`;
  }
  if (state.staged === "approve") {
    html += `<div class="scrim" data-act="close-overlay"><div class="card" style="max-width:460px" onclick="event.stopPropagation()">
      <div class="rule" style="margin-bottom:16px"></div>
      <h2 class="play" style="font-size:26px;margin:0 0 12px">Approve ${esc((current() || {}).identifier || "")}?</h2>
      <p style="font-size:16px;line-height:1.55;color:${MUTED}">This writes the verdict to Vikunja. Press confirm, or Escape to cancel.</p>
      <button class="btn btn-fill" data-act="confirm-stage" style="margin-top:16px">confirm</button>
    </div></div>`;
  }
  if (state.staged === "human") {
    html += `<div class="scrim" data-act="close-overlay"><div class="card" style="max-width:460px" onclick="event.stopPropagation()">
      <div class="rule" style="margin-bottom:16px"></div>
      <h2 class="play" style="font-size:26px;margin:0 0 12px">Mark ${esc((current() || {}).identifier || "")} human-only?</h2>
      <p style="font-size:16px;line-height:1.55;color:${MUTED}">Agents will stop working this ticket. Press confirm, or Escape to cancel.</p>
      <button class="btn btn-fill" data-act="confirm-stage" style="margin-top:16px">confirm</button>
    </div></div>`;
  }
  return html;
}

function render() {
  const app = document.getElementById("app");
  if (!state.board) {
    app.innerHTML = `<div style="padding:40px;color:${MUTED}">loading…</div>`;
    return;
  }
  const body = {
    home: renderHome,
    review: renderReview,
    queue: renderQueue,
    human: renderHuman,
    timeline: renderTimeline,
    stats: renderStats
  }[state.view]();
  app.innerHTML = `<header style="display:flex;align-items:center;gap:28px;padding:0 22px;height:54px;border-bottom:1px solid rgba(43,36,27,0.12);flex:none">
    <img src="/static/assets/logo-mark-black.svg" alt="" width="20" height="20" style="opacity:0.85">
    <nav style="display:flex;gap:22px;align-items:center">${navHtml()}</nav>
  </header>${body}${overlays()}`;
  const cs = document.getElementById("chat-scroll");
  if (cs) cs.scrollTop = cs.scrollHeight;
  syncUrl();
}

function startDrag(e, key, dir, min, max) {
  e.preventDefault();
  const startX = e.clientX;
  const startW = state[key];
  const move = ev => {
    state[key] = Math.max(min, Math.min(max, startW + dir * (ev.clientX - startX)));
    render();
  };
  const up = () => {
    window.removeEventListener("mousemove", move);
    window.removeEventListener("mouseup", up);
  };
  window.addEventListener("mousemove", move);
  window.addEventListener("mouseup", up);
}

document.addEventListener("click", async e => {
  const a = e.target.closest("[data-view]");
  if (a) { e.preventDefault(); state.view = a.getAttribute("data-view"); render(); return; }
  const open = e.target.closest("[data-open]");
  if (open) {
    e.preventDefault();
    const id = Number(open.getAttribute("data-open"));
    if (e.shiftKey || e.metaKey) {
      state.selected[id] = !state.selected[id];
    } else {
      state.viewing = id;
      state.view = "review";
      const idx = pending().findIndex(t => t.id === id);
      if (idx >= 0) state.cursor = idx;
    }
    render(); return;
  }
  const filt = e.target.closest("[data-filter]");
  if (filt) { state.filter = filt.getAttribute("data-filter"); render(); return; }
  const sec = e.target.closest("[data-section]");
  if (sec) { const k = sec.getAttribute("data-section"); state.open[k] = !state.open[k]; render(); return; }
  const art = e.target.closest("[data-art]");
  if (art) {
    const [tid, i] = art.getAttribute("data-art").split(":");
    state.openArt[tid] = state.openArt[tid] || {};
    state.openArt[tid][i] = !state.openArt[tid][i];
    render(); return;
  }
  const cmp = e.target.closest("[data-compare]");
  if (cmp) {
    const [tid, i] = cmp.getAttribute("data-compare").split(":");
    state.openCompare[tid] = state.openCompare[tid] || {};
    state.openCompare[tid][i] = !state.openCompare[tid][i];
    render(); return;
  }
  const snooze = e.target.closest("[data-snooze]");
  if (snooze) { state.noteText = snooze.getAttribute("data-snooze"); state.customWhen = ""; render(); return; }
  const hum = e.target.closest("[data-human]");
  if (hum && !e.target.closest("[data-human-act]")) {
    const id = Number(hum.getAttribute("data-human"));
    state.humanOpen = state.humanOpen === id ? null : id;
    render(); return;
  }
  const ha = e.target.closest("[data-human-act]");
  if (ha) {
    const [action, id] = ha.getAttribute("data-human-act").split(":");
    const note = action === "note" ? (state.humanDraft || "") : "";
    try {
      await postJSON("/api/tasks/" + id + "/human", { action, note });
      state.humanDraft = "";
      await loadBoard();
    } catch (err) { state.error = err.message; }
    render(); return;
  }
  const act = e.target.closest("[data-act]");
  if (!act) return;
  const name = act.getAttribute("data-act");
  if (name === "approve") decide("approve");
  else if (name === "remediate") decide("remediate");
  else if (name === "noAction") decide("noAction");
  else if (name === "human") decide("human");
  else if (name === "snooze") decide("snooze");
  else if (name === "confirm-revise") decide("remediate", (document.getElementById("note-text") || {}).value || state.noteText);
  else if (name === "confirm-snooze") decide("snooze", state.noteText, snoozeUntil());
  else if (name === "confirm-stage" && state.staged) decide(state.staged, HermesReviewDisposition.confirmNote(state.staged));
  else if (name === "cancel-note" || name === "close-overlay") { state.noteMode = null; state.staged = null; state.shortcutsOpen = false; state.reviseW = 0; render(); }
  else if (name === "toggle-rail") { state.railOpen = !state.railOpen; render(); }
  else if (name === "toggle-chat") { state.chatOpen = !state.chatOpen; render(); }
  else if (name === "shortcuts") { state.shortcutsOpen = !state.shortcutsOpen; render(); }
  else if (name === "send-chat") sendComment();
  else if (name === "undo") { state.toast = "undo is session-local — re-open the ticket in Vikunja if you need a hard revert"; render(); }
});

document.addEventListener("input", e => {
  if (e.target.id === "note-text") state.noteText = e.target.value;
  if (e.target.id === "chat-draft") state.chatDraft = e.target.value;
  if (e.target.id === "custom-when") { state.customWhen = e.target.value; state.noteText = ""; }
  if (e.target.hasAttribute("data-humandraft")) state.humanDraft = e.target.value;
});

document.addEventListener("mousedown", e => {
  const h = e.target.closest("[data-drag]");
  if (!h) return;
  const k = h.getAttribute("data-drag");
  if (k === "rail") startDrag(e, "railW", 1, 200, 520);
  if (k === "chat") startDrag(e, "chatW", 1, 280, 680);
  if (k === "revise") startDrag(e, "reviseW", 1, 300, 900);
});

window.addEventListener("keydown", e => {
  const tag = (e.target.tagName || "").toLowerCase();
  const typing = tag === "textarea" || tag === "input" || tag === "select" || e.target.isContentEditable;
  if (typing) {
    if (e.key === "Escape") { e.target.blur(); state.noteMode = null; state.reviseW = 0; render(); }
    if ((e.metaKey || e.ctrlKey) && e.key === "Enter") {
      e.preventDefault();
      if (state.noteMode === "remediate") decide("remediate", state.noteText);
      else if (state.noteMode === "snooze") decide("snooze", state.noteText, snoozeUntil());
      else sendComment();
    }
    return;
  }
  if (state.gPending) {
    state.gPending = false;
    const map = { o: "home", q: "queue", h: "human", t: "timeline", s: "stats", r: "review" };
    if (map[e.key]) { e.preventDefault(); state.view = map[e.key]; render(); }
    return;
  }
  if (e.key === "g") { state.gPending = true; return; }
  if (e.key === "?") { e.preventDefault(); state.shortcutsOpen = !state.shortcutsOpen; render(); return; }
  if (e.key === "Escape") { state.shortcutsOpen = false; state.noteMode = null; state.staged = null; state.selected = {}; state.reviseW = 0; render(); return; }
  if (state.staged) {
    if (e.key === "Enter") {
      e.preventDefault();
      decide(state.staged, HermesReviewDisposition.confirmNote(state.staged));
    }
    return;
  }
  if (state.noteMode || state.shortcutsOpen) return;
  if (state.view !== "review") return;
  if (e.key === "j") { e.preventDefault(); state.cursor = Math.min(pending().length - 1, state.cursor + 1); state.viewing = null; render(); }
  else if (e.key === "k") { e.preventDefault(); state.cursor = Math.max(0, state.cursor - 1); state.viewing = null; render(); }
  else if (e.key === "a") { e.preventDefault(); decide("approve"); }
  else if (e.key === "r") { e.preventDefault(); openNote("remediate"); }
  else if (e.key === "c") { e.preventDefault(); decide("noAction"); }
  else if (e.key === "h") { e.preventDefault(); decide("human"); }
  else if (e.key === "s") { e.preventDefault(); decide("snooze"); }
  else if (e.key === "[") { e.preventDefault(); state.railOpen = !state.railOpen; render(); }
  else if (e.key === "]") { e.preventDefault(); state.chatOpen = !state.chatOpen; render(); }
  else if (e.key === "/") { e.preventDefault(); state.chatOpen = true; render(); const el = document.getElementById("chat-draft"); if (el) el.focus(); }
  else if (e.key >= "1" && e.key <= "6") { e.preventDefault(); const k = SECTIONS[Number(e.key) - 1]; state.open[k] = !state.open[k]; render(); }
  else if (e.key === "e") { e.preventDefault(); SECTIONS.forEach(k => state.open[k] = !e.shiftKey); render(); }
});

window.addEventListener("resize", () => {
  const w = window.innerWidth;
  state.chatOpen = w >= 1280;
  state.railOpen = w >= 1040;
  render();
});

window.addEventListener("popstate", () => {
  applyingUrl = true;
  HermesReviewUrl.apply(state, HermesReviewUrl.parse(window.location.search));
  render();
  applyingUrl = false;
});

loadBoard().then(() => {
  applyingUrl = true;
  HermesReviewUrl.apply(state, HermesReviewUrl.parse(window.location.search));
  const w = window.innerWidth;
  state.chatOpen = w >= 1280;
  state.railOpen = w >= 1040;
  render();
  applyingUrl = false;
  syncUrl();
}).catch(err => {
  document.getElementById("app").innerHTML = `<div style="padding:40px;color:${CLAY}">${esc(err.message)}</div>`;
});
