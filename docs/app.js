/* Sanya FRC 2026 (REBUILT) Analytics — front-end app
   Loads data/analysis.json and renders an interactive dashboard.
   Every metric exposes a clickable "?" that explains it (data-driven from
   analysis.json -> metricDefs). No external/CDN dependency (Chart.js vendored). */
"use strict";

const CORE_METRICS = ["opr", "ccwm", "autoOpr", "teleopOpr", "fuelOpr", "fuelCountOpr", "towerOpr", "avgRp", "winRate"];

const state = {
  data: null,
  view: "overview",
  groupKey: "core",
  sortKey: "opr",
  sortDir: -1,      // -1 desc, +1 asc
  search: "",
  team: null,
  minMatches: 1,
  matchLevel: "qual",
  charts: {},
  availableMetrics: new Set(),
  groups: [],
  bestByMetric: {},
};

/* ------------------------------------------------------------------ utils */
const $ = (sel, el = document) => el.querySelector(sel);
const $$ = (sel, el = document) => Array.from(el.querySelectorAll(sel));
const el = (tag, attrs = {}, ...kids) => {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") n.className = v;
    else if (k === "html") n.innerHTML = v;
    else if (k.startsWith("on") && typeof v === "function") n.addEventListener(k.slice(2), v);
    else if (v !== null && v !== undefined) n.setAttribute(k, v);
  }
  for (const kid of kids) if (kid !== null && kid !== undefined) n.append(kid.nodeType ? kid : document.createTextNode(kid));
  return n;
};
const cssVar = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();

function mdef(key) {
  return (state.data && state.data.metricDefs && state.data.metricDefs[key]) ||
    { label: key, full: "", unit: "", decimals: 1, higherBetter: true, help: "（暂无说明）" };
}
function fmt(val, key) {
  if (val === null || val === undefined || Number.isNaN(val)) return "–";
  const d = mdef(key);
  const dec = d.decimals ?? 1;
  let s = Number(val).toFixed(dec);
  if (d.unit === "%") s = Math.round(Number(val)) + "";
  return s;
}
function metricValue(team, key) {
  if (key === "rank") return team.rank ?? null;
  if (team.metrics && key in team.metrics) return team.metrics[key];
  return null;
}

/* ------------------------------------------------------------- help popover */
const pop = () => document.getElementById("popover");
let popAnchor = null;
function openPopover(btn, def) {
  const p = pop();
  const higher = def.higherBetter === false ? "越低越好" : "越高越好";
  p.innerHTML = "";
  p.append(el("div", { class: "ph" }, def.label || ""));
  if (def.full) p.append(el("div", { class: "pf" }, def.full));
  p.append(el("div", {}, def.help || ""));
  const meta = [];
  if (def.unit) meta.push("单位：" + def.unit);
  meta.push(higher);
  p.append(el("div", { class: "pmeta" }, meta.join("　·　")));
  p.classList.add("show");
  const r = btn.getBoundingClientRect();
  const pw = Math.min(320, window.innerWidth - 24);
  p.style.maxWidth = pw + "px";
  let left = window.scrollX + r.left;
  left = Math.min(left, window.scrollX + window.innerWidth - pw - 12);
  left = Math.max(left, window.scrollX + 12);
  p.style.left = left + "px";
  p.style.top = (window.scrollY + r.bottom + 7) + "px";
  btn.setAttribute("aria-expanded", "true");
  popAnchor = btn;
}
function closePopover() {
  pop().classList.remove("show");
  if (popAnchor) popAnchor.setAttribute("aria-expanded", "false");
  popAnchor = null;
}
function helpBtn(metricKey) {
  return el("button", { class: "help", "data-metric": metricKey, "aria-label": "说明", "aria-expanded": "false", type: "button" }, "?");
}
document.addEventListener("click", (e) => {
  const b = e.target.closest(".help[data-metric]");
  if (b) {
    e.stopPropagation();
    if (popAnchor === b) { closePopover(); return; }
    openPopover(b, mdef(b.getAttribute("data-metric")));
    return;
  }
  if (!e.target.closest("#popover")) closePopover();
});
document.addEventListener("keydown", (e) => { if (e.key === "Escape") { closePopover(); closeMatchModal(); } });
window.addEventListener("resize", closePopover);

/* --------------------------------------------------------------- init/load */
async function boot() {
  initTheme();
  try {
    const res = await fetch("data/analysis.json", { cache: "no-store" });
    if (!res.ok) throw new Error("HTTP " + res.status);
    state.data = await res.json();
  } catch (err) {
    $("#loading").innerHTML = "";
    $("#loading").append(el("div", { class: "banner" },
      el("b", {}, "数据加载失败。"),
      el("div", {}, "无法读取 data/analysis.json（" + err.message + "）。若在本地打开，请通过本地服务器访问，或等待数据生成。")));
    return;
  }
  $("#loading").classList.add("hidden");
  prepareMeta();
  buildGroups();
  bindTabs();
  bindControls();
  renderAll();
}

function prepareMeta() {
  const m = state.data.meta || {};
  document.title = (m.eventShort ? m.eventShort + " · " : "") + "三亚 FRC 2026 数据分析";
  $("#brandTitle").textContent = "三亚 FRC 2026 · REBUILT 数据分析";
  $("#brandSub").textContent = (m.eventName || "") + (m.eventDates ? "　·　" + m.eventDates : "");
  if (m.generatedAt) $("#genChip").textContent = "更新于 " + fmtDate(m.generatedAt);
  $("#footMeta").textContent = [m.eventName, m.season && ("赛季 " + m.season), m.gameName].filter(Boolean).join("　·　");
  if (m.eventUrl) $("#srcLink").href = m.eventUrl;

  // available metrics = defined AND present on at least one team
  const avail = new Set();
  for (const t of state.data.teams || []) {
    for (const k of Object.keys(t.metrics || {})) if (state.data.metricDefs[k]) avail.add(k);
  }
  if ((state.data.teams || []).some(t => t.rank != null)) avail.add("rank");
  state.availableMetrics = avail;

  // best value per metric across all teams (for highlight)
  for (const k of avail) {
    const def = mdef(k);
    let best = null;
    for (const t of state.data.teams) {
      const v = metricValue(t, k);
      if (v == null) continue;
      if (best === null || (def.higherBetter === false ? v < best : v > best)) best = v;
    }
    state.bestByMetric[k] = best;
  }
  if (!avail.has(state.sortKey)) state.sortKey = avail.has("opr") ? "opr" : [...avail][0];
}

function buildGroups() {
  const filt = (arr) => arr.filter(k => state.availableMetrics.has(k));
  const groups = [{ key: "core", label: "综合", metrics: filt(CORE_METRICS) }];
  for (const g of state.data.metricGroups || []) {
    const metrics = filt(g.metrics || []);
    if (metrics.length) groups.push({ key: g.key, label: g.label.split("·")[0].trim(), metrics });
  }
  state.groups = groups;
}

function fmtDate(iso) {
  try { const d = new Date(iso); return d.toLocaleString("zh-CN", { month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit" }); }
  catch { return iso; }
}

/* --------------------------------------------------------------- theme/tabs */
function initTheme() {
  const saved = localStorage.getItem("sanya-theme");
  if (saved) document.documentElement.setAttribute("data-theme", saved);
  $("#themeBtn").addEventListener("click", () => {
    const cur = document.documentElement.getAttribute("data-theme");
    const sysDark = window.matchMedia("(prefers-color-scheme: dark)").matches;
    const eff = cur || (sysDark ? "dark" : "light");
    const next = eff === "dark" ? "light" : "dark";
    document.documentElement.setAttribute("data-theme", next);
    localStorage.setItem("sanya-theme", next);
    rerenderCharts();
  });
}
function bindTabs() {
  $$(".tab").forEach(t => t.addEventListener("click", () => switchView(t.dataset.view)));
}
function switchView(v) {
  state.view = v;
  $$(".tab").forEach(t => t.classList.toggle("active", t.dataset.view === v));
  $$(".view").forEach(s => s.classList.toggle("active", s.id === "view-" + v));
  closePopover();
  if (v === "team") renderTeam();
  if (v === "matches") renderMatches();
  window.scrollTo({ top: 0, behavior: "smooth" });
}

function bindControls() {
  $("#search").addEventListener("input", (e) => { state.search = e.target.value.trim().toLowerCase(); renderTable(); });
  $("#teamBack").addEventListener("click", () => switchView("overview"));
}

function renderAll() {
  renderNotes();
  renderMinFilter();
  renderGroupSeg();
  renderTable();
  renderTeamPicker();
  renderGlossary();
  renderAbout();
  renderMatchSeg();
}

/* --------------------------------------------------------------- notes/banner */
function renderNotes() {
  const m = state.data.meta || {};
  const host = $("#notes"); host.innerHTML = "";
  const notes = (m.notes || []).slice();
  if (m.isMock) notes.unshift("⚠️ 当前为占位示例数据，非真实比赛结果。");
  $("#ovCount").textContent = `${(state.data.teams || []).length} 支队伍 · 排位赛 ${m.counts?.qualPlayed ?? "?"}/${m.counts?.qualTotal ?? "?"} 场` +
    (m.counts?.playoffPlayed ? ` · 淘汰赛 ${m.counts.playoffPlayed} 场` : "");
  if (!notes.length) return;
  const b = el("div", { class: "banner" });
  b.append(el("b", {}, "说明 · Notes"));
  const ul = el("ul", {});
  notes.forEach(n => ul.append(el("li", {}, n)));
  b.append(ul);
  host.append(b);
}

/* ---------------------------------------------------------------- overview */
function renderGroupSeg() {
  const seg = $("#groupSeg"); seg.innerHTML = "";
  state.groups.forEach(g => {
    const b = el("button", { class: state.groupKey === g.key ? "active" : "", type: "button" }, g.label);
    b.addEventListener("click", () => {
      state.groupKey = g.key;
      const metrics = activeMetrics();
      if (!metrics.includes(state.sortKey)) { state.sortKey = metrics.find(k => k !== "rank") || metrics[0]; state.sortDir = -1; }
      renderGroupSeg(); renderTable();
    });
    seg.append(b);
  });
}
function activeMetrics() {
  const g = state.groups.find(x => x.key === state.groupKey) || state.groups[0];
  return g.metrics;
}
function renderMinFilter() {
  const controls = document.querySelector("#view-overview .controls");
  if (!controls || document.getElementById("minSel")) return;
  const wrap = el("div", { class: "nowrap small muted", style: "display:flex;align-items:center;gap:6px" }, "出场≥");
  const sel = el("select", { id: "minSel", style: "width:auto" });
  [["1", "全部"], ["2", "2 场"], ["3", "3 场"], ["4", "4 场"], ["5", "5 场"]].forEach(([v, l]) => sel.append(el("option", { value: v }, l)));
  sel.value = String(state.minMatches);
  sel.addEventListener("change", () => { state.minMatches = Number(sel.value); renderTable(); });
  wrap.append(sel);
  controls.append(wrap);
}

function sortedTeams(metrics) {
  const teams = (state.data.teams || []).filter(t => {
    if ((t.metrics.matchesPlayed || 0) < state.minMatches) return false;
    if (!state.search) return true;
    return String(t.team).includes(state.search) || (t.name || "").toLowerCase().includes(state.search);
  });
  const key = state.sortKey;
  const def = mdef(key);
  teams.sort((a, b) => {
    let va = metricValue(a, key), vb = metricValue(b, key);
    va = va == null ? -Infinity : va; vb = vb == null ? -Infinity : vb;
    if (va === vb) return (a.rank ?? 999) - (b.rank ?? 999);
    return state.sortDir * (va < vb ? -1 : 1) * -1; // handled below
  });
  // Simpler stable compare:
  teams.sort((a, b) => {
    let va = metricValue(a, key), vb = metricValue(b, key);
    if (va == null && vb == null) return (a.rank ?? 999) - (b.rank ?? 999);
    if (va == null) return 1; if (vb == null) return -1;
    return state.sortDir === -1 ? vb - va : va - vb;
  });
  return teams;
}

function renderTable() {
  if (state.view !== "overview") { /* still build so switching is instant */ }
  const metrics = activeMetrics();
  const head = $("#ovHead"); head.innerHTML = "";
  head.append(el("th", { class: "left sticky-l", onclick: () => setSort("rank") },
    el("span", { class: "th-in", style: "justify-content:flex-start" },
      el("span", {}, "队伍 Team"),
      sortArrow("rank"))));
  metrics.forEach(k => {
    if (k === "rank") return;
    const d = mdef(k);
    const th = el("th", { title: d.full || d.label });
    const inner = el("span", { class: "th-in" }, el("span", { onclick: () => setSort(k) }, d.label), helpBtn(k), sortArrow(k));
    th.append(inner);
    th.addEventListener("click", (e) => { if (!e.target.closest(".help")) setSort(k); });
    head.append(th);
  });

  const body = $("#ovBody"); body.innerHTML = "";
  const teams = sortedTeams(metrics);
  // per-column min/max for data bars among displayed teams
  const range = {};
  metrics.forEach(k => {
    const vals = teams.map(t => metricValue(t, k)).filter(v => v != null);
    range[k] = vals.length ? { min: Math.min(...vals), max: Math.max(...vals) } : { min: 0, max: 1 };
  });

  teams.forEach(t => {
    const tr = el("tr", {});
    const teamCell = el("td", { class: "left sticky-l" });
    teamCell.append(
      el("span", { class: "rankcell", style: "display:inline-block;min-width:26px" }, t.rank != null ? "#" + t.rank : ""),
      el("span", { class: "team-link", onclick: () => openTeam(t.team) }, " " + (t.name || ("Team " + t.team))),
      el("div", { class: "team-num" }, "#" + t.team + (t.record ? `　${t.record.w}-${t.record.l}-${t.record.t || 0}` : "")));
    tr.append(teamCell);

    metrics.forEach(k => {
      if (k === "rank") return;
      const v = metricValue(t, k);
      const td = el("td", {});
      if (v != null) {
        const d = mdef(k);
        const r = range[k];
        let frac = 0;
        if (r.max !== r.min) frac = (v - r.min) / (r.max - r.min);
        if (d.higherBetter === false) frac = 1 - frac;
        frac = Math.max(0, Math.min(1, frac));
        td.append(el("span", { class: "databar", style: `width:${(frac * 100).toFixed(1)}%` }));
        const isBest = state.bestByMetric[k] != null && Math.abs(v - state.bestByMetric[k]) < 1e-9;
        if (isBest) td.classList.add("best");
        const span = el("span", { class: "cellval" }, fmt(v, k) + (d.unit === "%" ? "%" : ""));
        if (k === "ccwm" || d.higherBetter !== false) { if (v < 0) span.classList.add("neg"); }
        td.append(span);
      } else td.append(el("span", { class: "cellval muted" }, "–"));
      tr.append(td);
    });
    body.append(tr);
  });
}
function sortArrow(key) {
  const active = state.sortKey === key;
  return el("span", { class: "arr" }, active ? (state.sortDir === -1 ? "▼" : "▲") : "");
}
function setSort(key) {
  if (state.sortKey === key) state.sortDir = -state.sortDir;
  else { state.sortKey = key; state.sortDir = (mdef(key).higherBetter === false) ? 1 : -1; }
  renderTable();
}

/* ---------------------------------------------------------------- team view */
function renderTeamPicker() {
  const sel = $("#teamSelect"); sel.innerHTML = "";
  (state.data.teams || []).slice().sort((a, b) => (a.rank ?? 999) - (b.rank ?? 999)).forEach(t => {
    sel.append(el("option", { value: t.team }, `#${t.rank ?? "?"}　${t.team}　${t.name || ""}`));
  });
  sel.addEventListener("change", () => { state.team = Number(sel.value); renderTeam(); });
}
function openTeam(teamNum) { state.team = teamNum; switchView("team"); }

function eventAvg(key) {
  const vals = (state.data.teams || []).map(t => metricValue(t, key)).filter(v => v != null);
  return vals.length ? vals.reduce((a, b) => a + b, 0) / vals.length : null;
}

function renderTeam() {
  const teams = state.data.teams || [];
  if (state.team == null && teams.length) state.team = teams[0].team;
  const t = teams.find(x => x.team === state.team);
  $("#teamPicker").classList.remove("hidden");
  $("#teamSelect").value = String(state.team);
  const host = $("#teamContent"); host.innerHTML = "";
  if (!t) { host.append(el("p", { class: "muted" }, "未找到该队伍。")); return; }

  // hero
  host.append(el("div", { class: "team-hero" },
    el("span", { class: "big" }, t.name || ("Team " + t.team)),
    el("span", { class: "chip" }, "#" + t.team),
    t.rank != null ? el("span", { class: "chip" }, "排名 #" + t.rank) : null,
    t.record ? el("span", { class: "chip" }, `战绩 ${t.record.w}-${t.record.l}-${t.record.t || 0}`) : null));
  if (t.school) host.append(el("div", { class: "muted small", style: "margin-bottom:14px" }, t.school + (t.country ? "　·　" + t.country : "")));

  // stat tiles (key metrics with "?")
  const tileKeys = ["opr", "dpr", "ccwm", "autoOpr", "teleopOpr", "fuelOpr", "towerOpr", "fuelCountOpr", "avgRp", "winRate", "climbRate"]
    .filter(k => state.availableMetrics.has(k) && metricValue(t, k) != null);
  const tiles = el("div", { class: "tiles", style: "margin-bottom:18px" });
  tileKeys.forEach(k => {
    const d = mdef(k), v = metricValue(t, k), avg = eventAvg(k);
    const tile = el("div", { class: "tile" });
    tile.append(el("div", { class: "k" }, d.label, helpBtn(k)));
    tile.append(el("div", { class: "v" }, fmt(v, k), el("small", {}, d.unit === "%" ? "%" : (d.unit || ""))));
    if (avg != null) {
      const diff = v - avg;
      const better = (d.higherBetter === false) ? diff < 0 : diff > 0;
      tile.append(el("div", { class: "sub" }, `均值 ${fmt(avg, k)} · `,
        el("span", { class: better ? "pos" : "neg" }, (diff >= 0 ? "+" : "") + fmt(diff, k))));
    }
    tiles.append(tile);
  });
  host.append(tiles);

  // charts row
  const row = el("div", { class: "two-col" });
  const c1 = el("div", { class: "card" });
  c1.append(el("div", { class: "section-head", style: "margin-top:0" }, el("h3", { style: "margin:0" }, "OPR 随比赛推进的变化"), helpBtnInline("opr")));
  const trendKeys = Object.keys(t.trends || {}).filter(k => state.availableMetrics.has(k) || k === "opr");
  const trendSeg = el("div", { class: "seg", style: "margin-bottom:10px" });
  c1.append(trendSeg);
  const cb1 = el("div", { class: "chart-box" }, el("canvas", { id: "trendChart" }));
  c1.append(cb1);
  row.append(c1);

  const c2 = el("div", { class: "card" });
  c2.append(el("div", { class: "section-head", style: "margin-top:0" }, el("h3", { style: "margin:0" }, "各班次投料 OPR 画像"),
    el("span", { class: "muted small" }, "本队 vs 全场均值")));
  const cb2 = el("div", { class: "chart-box" }, el("canvas", { id: "compChart" }));
  c2.append(cb2);
  row.append(c2);
  host.append(row);

  // per-match table
  if ((t.matches || []).length) {
    const mc = el("div", { class: "card", style: "margin-top:14px" });
    mc.append(el("h3", {}, "每场比赛"));
    mc.append(buildTeamMatches(t));
    host.append(mc);
  }

  // draw charts
  drawTrend(t, trendKeys, trendSeg);
  drawComp(t);
}
function helpBtnInline(key) { const s = el("span", {}, helpBtn(key)); return s; }

function buildTeamMatches(t) {
  const wrap = el("div", { class: "table-scroll", style: "box-shadow:none;border:none" });
  const table = el("table", { class: "data" });
  const thead = el("thead", {}, el("tr", {},
    el("th", { class: "left" }, "场次"), el("th", { class: "left" }, "联盟"),
    el("th", { class: "left" }, "队友"), el("th", { class: "left" }, "对手"),
    el("th", {}, "本方"), el("th", {}, "对方"), el("th", {}, "结果")));
  const tbody = el("tbody", {});
  t.matches.forEach(mm => {
    const tr = el("tr", { style: "cursor:pointer" },
      el("td", { class: "left" }, matchLabel(mm)),
      el("td", { class: "left" }, el("span", { class: mm.color === "Red" ? "neg" : "" }, mm.color === "Red" ? "红" : "蓝")),
      el("td", { class: "left team-num" }, (mm.partners || []).join(", ") || "–"),
      el("td", { class: "left team-num" }, (mm.opponents || []).join(", ") || "–"),
      el("td", {}, mm.allianceScore ?? "–"),
      el("td", {}, mm.oppScore ?? "–"),
      el("td", {}, el("span", { class: mm.win ? "pos" : "neg" }, mm.win ? "胜" : "负")));
    tr.addEventListener("click", () => { const gm = findMatch(mm.level, mm.num); if (gm) openMatchModal(gm); });
    tbody.append(tr);
  });
  table.append(thead, tbody); wrap.append(table); return wrap;
}
function matchLabel(mm) {
  const map = { qual: "排位赛", playoff: "淘汰赛", Qualification: "排位赛", Playoff: "淘汰赛", Final: "决赛" };
  return (map[mm.level] || mm.level || "") + " " + (mm.num ?? "");
}
function officialMatchUrl(m) {
  const s = (state.data.meta || {}).season || "2026";
  const ev = (state.data.meta || {}).event || "";
  const phase = m.level === "qual" ? "qualifications" : "playoffs";
  return `https://frc-events.firstinspires.org/${s}/${ev}/${phase}/${m.num}`;
}
function findMatch(level, num) {
  return (state.data.matches || []).find(m => m.level === level && m.num === num);
}

/* ------------------------------------------------------------------- charts */
function baseChartOpts(extra = {}) {
  const grid = cssVar("--grid"), muted = cssVar("--text-muted");
  return Object.assign({
    responsive: true, maintainAspectRatio: false,
    interaction: { mode: "index", intersect: false },
    plugins: {
      legend: { display: false },
      tooltip: { backgroundColor: cssVar("--surface-1"), titleColor: cssVar("--text-primary"),
        bodyColor: cssVar("--text-secondary"), borderColor: cssVar("--axis"), borderWidth: 1, padding: 10 },
    },
    scales: {
      x: { grid: { color: grid, drawTicks: false }, ticks: { color: muted, font: { size: 11 } }, border: { color: cssVar("--axis") } },
      y: { grid: { color: grid, drawTicks: false }, ticks: { color: muted, font: { size: 11 } }, border: { display: false }, beginAtZero: false },
    },
  }, extra);
}
function destroyChart(id) { if (state.charts[id]) { state.charts[id].destroy(); delete state.charts[id]; } }

const SERIES_VARS = ["--s1", "--s2", "--s3", "--s5", "--s8", "--s6", "--s7", "--s4"];
function seriesColor(i) { return cssVar(SERIES_VARS[i % SERIES_VARS.length]); }

let currentTrendKey = "opr";
function drawTrend(t, trendKeys, segHost) {
  if (!trendKeys.length) trendKeys = ["opr"];
  if (!trendKeys.includes(currentTrendKey)) currentTrendKey = trendKeys[0];
  segHost.innerHTML = "";
  trendKeys.forEach(k => {
    const b = el("button", { class: currentTrendKey === k ? "active" : "", type: "button" }, mdef(k).label);
    b.addEventListener("click", () => { currentTrendKey = k; drawTrend(t, trendKeys, segHost); });
    segHost.append(b);
  });
  destroyChart("trendChart");
  const series = t.trends[currentTrendKey] || [];
  const ctx = document.getElementById("trendChart");
  if (!ctx) return;
  state.charts["trendChart"] = new Chart(ctx, {
    type: "line",
    data: {
      labels: series.map(p => "第" + p.m + "场"),
      datasets: [{
        label: mdef(currentTrendKey).label, data: series.map(p => p.v),
        borderColor: seriesColor(0), backgroundColor: "transparent",
        borderWidth: 2, pointRadius: 3, pointBackgroundColor: seriesColor(0), tension: 0.25,
      }],
    },
    options: baseChartOpts(),
  });
}

function drawComp(t) {
  destroyChart("compChart");
  const keys = ["transitionOpr", "shift1Opr", "shift2Opr", "shift3Opr", "shift4Opr", "endgameFuelOpr"]
    .filter(k => state.availableMetrics.has(k) && metricValue(t, k) != null);
  const ctx = document.getElementById("compChart");
  if (!ctx || !keys.length) return;
  state.charts["compChart"] = new Chart(ctx, {
    type: "bar",
    data: {
      labels: keys.map(k => mdef(k).label),
      datasets: [
        { label: t.name || ("Team " + t.team), data: keys.map(k => metricValue(t, k)), backgroundColor: seriesColor(0), borderRadius: 4, barPercentage: 0.72, categoryPercentage: 0.7 },
        { label: "全场均值", data: keys.map(k => eventAvg(k)), backgroundColor: cssVar("--axis"), borderRadius: 4, barPercentage: 0.72, categoryPercentage: 0.7 },
      ],
    },
    options: baseChartOpts({ plugins: { legend: { display: true, labels: { color: cssVar("--text-secondary"), boxWidth: 12, font: { size: 11 } } },
      tooltip: { backgroundColor: cssVar("--surface-1"), titleColor: cssVar("--text-primary"), bodyColor: cssVar("--text-secondary"), borderColor: cssVar("--axis"), borderWidth: 1 } } }),
  });
}
function rerenderCharts() {
  if (state.view === "team" && state.team != null) renderTeam();
}

/* ----------------------------------------------------------------- matches */
function renderMatchSeg() {
  const seg = $("#matchSeg"); if (!seg) return; seg.innerHTML = "";
  [["qual", "排位赛"], ["playoff", "淘汰赛"]].forEach(([k, lab]) => {
    const b = el("button", { class: state.matchLevel === k ? "active" : "", type: "button" }, lab);
    b.addEventListener("click", () => { state.matchLevel = k; renderMatchSeg(); renderMatches(); });
    seg.append(b);
  });
}
function renderMatches() {
  const all = (state.data.matches || []).filter(m => m.level === state.matchLevel)
    .sort((a, b) => (a.num || 0) - (b.num || 0));
  $("#mCount").textContent = all.length + " 场";
  const head = $("#mHead"); head.innerHTML = "";
  head.append(el("tr", {},
    el("th", { class: "left" }, "场次"),
    el("th", { class: "left" }, "红方"), el("th", {}, "红分"),
    el("th", {}, "蓝分"), el("th", { class: "left" }, "蓝方"), el("th", {}, "胜"), el("th", {}, "")));
  const body = $("#mBody"); body.innerHTML = "";
  if (!all.length) { body.append(el("tr", {}, el("td", { class: "left muted", colspan: 7 }, "暂无该阶段比赛数据。"))); return; }
  all.forEach(m => {
    const redWin = (m.redScore ?? -1) > (m.blueScore ?? -1);
    const blueWin = (m.blueScore ?? -1) > (m.redScore ?? -1);
    const tr = el("tr", { style: "cursor:pointer" });
    tr.addEventListener("click", () => openMatchModal(m));
    tr.append(
      el("td", { class: "left nowrap" }, matchLabel(m)),
      el("td", { class: "left team-num" }, (m.red || []).join(", ")),
      el("td", { class: redWin ? "pos" : "" }, m.redScore ?? "–"),
      el("td", { class: blueWin ? "pos" : "" }, m.blueScore ?? "–"),
      el("td", { class: "left team-num" }, (m.blue || []).join(", ")),
      el("td", {}, redWin ? "红" : (blueWin ? "蓝" : "–")),
      el("td", { style: "color:var(--accent)" }, "详情 ›"));
    body.append(tr);
  });
}

// component-key -> label for the match-detail breakdown (order = display order)
const BD_ROWS = [
  ["auto", "自动总分"], ["teleop", "手动总分"], ["tower", "爬塔总分"],
  ["fuel", "燃料(Hub)得分"], ["autoFuel", "自动投料"], ["teleopFuel", "手动投料"],
  ["transition", "转场班次"], ["shift1", "第 1 班次"], ["shift2", "第 2 班次"],
  ["shift3", "第 3 班次"], ["shift4", "第 4 班次"], ["endgameFuel", "终局投料"],
  ["autoTower", "自动爬塔"], ["endgameTower", "终局爬塔"],
  ["fuelCount", "燃料吞吐(个)"], ["foul", "获得犯规分"], ["rp", "排位分 RP"],
];
const RP_BADGES = [["energized", "Energized"], ["supercharged", "Supercharged"], ["traversal", "Traversal"]];

function ensureMatchModal() {
  let ov = document.getElementById("matchOverlay");
  if (ov) return ov;
  ov = el("div", { id: "matchOverlay", class: "overlay" });
  ov.addEventListener("click", (e) => { if (e.target === ov) closeMatchModal(); });
  const modal = el("div", { class: "modal card", id: "matchModal" });
  ov.append(modal);
  document.body.append(ov);
  return ov;
}
function closeMatchModal() {
  const ov = document.getElementById("matchOverlay");
  if (ov) ov.classList.remove("show");
}
function openMatchModal(m) {
  closePopover();
  const ov = ensureMatchModal();
  const modal = document.getElementById("matchModal");
  modal.innerHTML = "";
  const rd = (m.detail && m.detail.Red) || {}, bd = (m.detail && m.detail.Blue) || {};
  const redWin = (m.redScore ?? -1) > (m.blueScore ?? -1);
  const blueWin = (m.blueScore ?? -1) > (m.redScore ?? -1);

  // header
  const head = el("div", { class: "modal-head" });
  head.append(el("div", {},
    el("div", { class: "modal-title" }, matchLabel(m)),
    el("a", { class: "official-link", href: officialMatchUrl(m), target: "_blank", rel: "noopener" }, "官方明细 ↗")));
  head.append(el("button", { class: "icon-btn", "aria-label": "关闭", onclick: closeMatchModal }, "✕"));
  modal.append(head);

  // scoreboard
  const sb = el("div", { class: "scoreboard" });
  sb.append(allianceHead("红方", m.red, m.redScore, redWin, "red"));
  sb.append(el("div", { class: "vs" }, "VS"));
  sb.append(allianceHead("蓝方", m.blue, m.blueScore, blueWin, "blue"));
  modal.append(sb);

  // RP badges
  const badgeRow = el("div", { class: "badge-row" });
  [["red", rd], ["blue", bd]].forEach(([side, d]) => {
    const got = RP_BADGES.filter(([k]) => d[k]);
    if (got.length) badgeRow.append(el("div", { class: "badges " + side },
      ...got.map(([, lab]) => el("span", { class: "badge " + side }, lab))));
  });
  if (badgeRow.children.length) modal.append(badgeRow);

  // breakdown comparison table
  const rows = BD_ROWS.filter(([k]) => rd[k] != null || bd[k] != null);
  if (rows.length) {
    const tbl = el("table", { class: "bd-table" });
    tbl.append(el("thead", {}, el("tr", {},
      el("th", { class: "r" }, "红"), el("th", { class: "c" }, "项目"), el("th", { class: "l" }, "蓝"))));
    const tb = el("tbody", {});
    rows.forEach(([k, lab]) => {
      const rv = rd[k], bv = bd[k];
      const rMore = rv != null && bv != null && rv > bv;
      const bMore = rv != null && bv != null && bv > rv;
      tb.append(el("tr", {},
        el("td", { class: "r " + (rMore ? "hi-red" : "") }, fmtBd(rv)),
        el("td", { class: "c" }, lab),
        el("td", { class: "l " + (bMore ? "hi-blue" : "") }, fmtBd(bv))));
    });
    tbl.append(tb);
    modal.append(el("div", { class: "bd-wrap" }, tbl));
  } else {
    modal.append(el("p", { class: "muted small" }, "该场暂无得分明细。"));
  }
  modal.append(el("div", { class: "muted small", style: "margin-top:10px" },
    "点击“官方明细”可在 FRC Events 官网查看该场完整记录。"));
  ov.classList.add("show");
}
function allianceHead(name, teams, score, win, side) {
  return el("div", { class: "al " + side + (win ? " win" : "") },
    el("div", { class: "al-name" }, name, win ? el("span", { class: "wintag" }, "胜") : null),
    el("div", { class: "al-score" }, score ?? "–"),
    el("div", { class: "al-teams team-num" }, (teams || []).join("  ")));
}
function fmtBd(v) {
  if (v === true) return "✓";
  if (v == null) return "–";
  return Number.isInteger(v) ? String(v) : String(Math.round(v * 10) / 10);
}

/* ---------------------------------------------------------------- glossary */
function renderGlossary() {
  const host = $("#glossList"); host.innerHTML = "";
  const groups = state.groups;
  const seen = new Set();
  groups.forEach(g => {
    if (g.key === "core") return;
    host.append(el("h3", { style: "margin:14px 0 2px;font-size:14px", class: "muted" }, g.label));
    g.metrics.forEach(k => {
      if (seen.has(k)) return; seen.add(k);
      host.append(glossItem(k));
    });
  });
  // any metric not in a named group
  [...state.availableMetrics].forEach(k => { if (!seen.has(k)) { seen.add(k); host.append(glossItem(k)); } });
}
function glossItem(k) {
  const d = mdef(k);
  return el("div", { class: "gitem" },
    el("h3", {}, d.label, el("span", { class: "full" }, d.full || ""),
      el("span", { class: "tag" }, d.higherBetter === false ? "越低越好" : "越高越好"),
      d.unit ? el("span", { class: "tag" }, "单位 " + d.unit) : null),
    el("p", {}, d.help || ""));
}

/* ------------------------------------------------------------------- about */
function renderAbout() {
  const m = state.data.meta || {};
  const host = $("#aboutBody"); host.innerHTML = `
    <p>本页展示 2026 FRC《REBUILT presented by Haas》赛季 <b>${escapeHtml(m.eventName || "")}</b>（赛事代码 <code>${escapeHtml(m.event || "")}</code>）的队伍数据分析。数据来源为 <a href="https://frc-events.firstinspires.org/" target="_blank" rel="noopener">FRC Events 官方 API</a>；OPR 及各分项指标由本站基于比赛得分明细独立计算。</p>

    <h3>OPR 是怎么算的？</h3>
    <p>OPR（Offensive Power Rating，进攻贡献值）把“每支队伍对联盟得分的平均贡献”当作未知数，用<b>最小二乘法</b>从全部比赛结果中解出来。设计矩阵 <code>A</code> 的每一行对应“某场比赛中某个联盟”，该联盟 3 支队伍所在列为 1、其余为 0；向量 <code>b</code> 是这个联盟该场的得分。求解：</p>
    <div class="formula">minimize ‖A·x − b‖²  ⇒  (AᵀA) x = Aᵀ b</div>
    <p>解出的 <code>x</code> 即每队的 OPR。把 <code>b</code> 换成不同的分项（自动得分、燃料得分、爬塔得分、某个班次的燃料……）再解一次，就得到对应的<b>分项 OPR</b>。把 <code>b</code> 换成对手得分得到 DPR，换成净胜分得到 CCWM。</p>

    <h3>随时间变化的 OPR</h3>
    <p>“OPR 趋势”是在第 <code>k</code> 场排位赛结束后，只用前 <code>k</code> 场重新解一次最小二乘，得到截至该场的 OPR 估计。随着比赛增多，估计通常趋于稳定。</p>

    <h3>REBUILT 专项指标</h3>
    <p>本赛季比赛由自动阶段、以及分为 <b>4 个 25 秒班次（Shift）</b> 的手动阶段组成，双方 Hub 轮流激活。若数据源提供逐班次的燃料明细，则按班次分别计算“班次 OPR”，衡量各队在不同班次窗口的投料效率；否则回退到自动/手动燃料 OPR。爬塔（Tower）按高度 L1/L2/L3 = 10/20/30 分计。</p>

    <h3>局限性</h3>
    <ul>
      <li>OPR 假设“联盟得分 = 各队贡献之和”，忽略了配合增益、防守干扰等交互效应。</li>
      <li>比赛场次较少时（尤其赛事早期或淘汰赛），OPR 噪声较大，请谨慎解读。</li>
      <li>本站为独立分析工具，与 FIRST® 官方无隶属关系。</li>
    </ul>
    <p class="muted small">生成时间：${escapeHtml(m.generatedAt || "")} · 数据源：${escapeHtml(m.dataSource || "FRC Events API")}</p>
  `;
}
function escapeHtml(s) { return String(s).replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c])); }

boot();
