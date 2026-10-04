// Clinician dashboard
const $ = (id) => document.getElementById(id);
const STEP_NAMES = { flip: "Hand flips", tremor: "Tremor", taps: "Taps", voice: "Voice" };
const TEST_ORDER = ["flip", "tremor", "taps", "voice"];
const BIN_HOURS = [0.25, 0.75, 1.25, 1.75, 2.25, 2.75, 3.25, 3.75, 4.5];
let today = null;
const liveIds = new Set();

const hourOf = (ts, dayStart) => (ts - dayStart) / 3600;

function feed(text, ts = Date.now() / 1000) {
  const li = TT.el("li", { html: `<time>${TT.fmtTime(ts)}</time><span>${TT.esc(text)}</span>` });
  $("feed").prepend(li);
  while ($("feed").children.length > 30) $("feed").lastChild.remove();
}

function renderLatest(c) {
  if (!c || c.score == null) return;
  $("latest-score").textContent = Math.round(c.score);
  $("latest-level").innerHTML = TT.levelHTML(c.level || TT.levelOf(c.score));
  const src = c.source === "synthetic" ? " (synthetic history)" : c.source === "demo" ? " (demo replay)" : " (wrist)";
  $("latest-when").textContent = `${TT.fmtDay(c.ts)}, ${TT.fmtTime(c.ts)}${src}`;
  $("latest-dose").textContent = `Time since last dose: ${TT.fmtMins(c.minutes_since_dose)}`;
}

function renderTiles(s) {
  const wo = s.wearing_off;
  const onset = wo.onset_minutes != null ? `~${(wo.onset_minutes / 60).toFixed(1)} h after dose` : "not seen";
  const tiles = [
    { label: "Wearing-off pattern", value: wo.detected ? "Present" : "Not detected", note: wo.detected ? `Score falls from ${wo.peak_score} to ${wo.late_score} (−${wo.drop_points} pts)` : (wo.reason || "") },
    { label: "Decline begins", value: wo.detected ? onset.replace(" after dose", "") : "—", note: "after each dose, 14-day average" },
    { label: "Checks completed", value: s.n_checks, note: `${s.n_missed_checks} expected checks missed` },
    { label: "Daily trend", value: `${s.trend.slope_per_day > 0 ? "+" : ""}${s.trend.slope_per_day}`, note: "score points per day (14-day fit)" },
  ];
  $("tiles").innerHTML = tiles.map((t) => `<div class="tile"><div class="label">${t.label}</div><div class="value">${t.value}</div><div class="note">${TT.esc(t.note)}</div></div>`).join("");
}

function renderToday() {
  const t = today;
  if (!t) return;
  const ds = t.start;
  $("today-date").textContent = TT.fmtDay(ds + 43200);
  const pts = t.checks.filter((c) => c.score != null).map((c) => ({
    x: hourOf(c.ts, ds), y: Math.round(c.score), c, live: c.source !== "synthetic",
  }));
  const now = (Date.now() / 1000 - ds) / 3600;
  TT.lineChart($("today-chart"), {
    x: [6, 23], y: [0, 100], height: 300, band: [70, 100], bandLabel: "good",
    yTicks: [0, 25, 50, 75, 100],
    xTicks: [6, 8, 10, 12, 14, 16, 18, 20, 22].map((h) => ({ v: h, label: h === 12 ? "12 PM" : h < 12 ? `${h} AM` : `${h - 12} PM` })),
    doses: t.doses.map((d) => ({ x: hourOf(d.ts, ds), label: `Dose ${TT.fmtTime(d.ts)}` })).filter((d) => d.x >= 6 && d.x <= 23),
    series: [{ points: pts, gap: 3, endLabel: (p) => (p.x > now - 1.5 ? `${p.y}` : "") }],
    ariaLabel: `Today's composite scores with dose times`,
    tooltip: (p) => `<strong>${p.y}</strong> · ${TT.levelOf(p.y)}<br>${TT.fmtTime(p.c.ts)} · ${TT.fmtMins(p.c.minutes_since_dose)} after dose${p.live ? "<br>from the wrist" : ""}`,
  });
  $("today-desc").textContent = `${pts.length} checks today. ` + pts.map((p) => `${TT.fmtTime(p.c.ts)}: ${p.y}`).join(", ");
  const rows = t.checks.map((c) => `<tr><td>${TT.fmtTime(c.ts)}</td><td>${c.score == null ? "—" : Math.round(c.score)}</td><td>${TT.fmtMins(c.minutes_since_dose)}</td><td>${c.source}</td></tr>`).join("");
  const missed = t.missed.map((m) => `<tr><td>${m.slot}</td><td>missed</td><td>—</td><td>—</td></tr>`).join("");
  $("today-table").innerHTML = `<table class="data"><thead><tr><th>Time</th><th>Score</th><th>Since dose</th><th>Source</th></tr></thead><tbody>${rows}${missed}</tbody></table>`;
}

function renderCurve(curve) {
  const pts = curve.map((c, i) => ({ x: BIN_HOURS[i], y: c.mean, c }));
  const band = curve.map((c, i) => (c.mean != null && c.sd != null ? { x: BIN_HOURS[i], lo: Math.max(0, c.mean - c.sd), hi: Math.min(100, c.mean + c.sd) } : null)).filter(Boolean);
  TT.lineChart($("curve-chart"), {
    x: [0, 5], y: [0, 100], height: 260, yTicks: [0, 25, 50, 75, 100],
    xTicks: [0, 1, 2, 3, 4, 5].map((h) => ({ v: h, label: `${h} h` })), xLabel: "hours since dose",
    series: [{ points: pts, bandPts: band }],
    ariaLabel: "Mean score by hours since the last dose",
    tooltip: (p) => `<strong>${p.y}</strong> mean · ${p.c.bin}<br>${p.c.n} checks${p.c.sd != null ? ` · SD ${p.c.sd}` : ""}`,
  });
  $("curve-table").innerHTML = `<table class="data"><thead><tr><th>Since dose</th><th>Mean</th><th>SD</th><th>Checks</th></tr></thead><tbody>${curve.map((c) => `<tr><td>${c.bin}</td><td>${c.mean ?? "—"}</td><td>${c.sd ?? "—"}</td><td>${c.n}</td></tr>`).join("")}</tbody></table>`;
}

function renderHeatmap(hm) {
  const box = $("heatmap");
  box.className = "heat";
  box.style.gridTemplateColumns = `auto repeat(${hm.bins.length}, minmax(28px, 1fr))`;
  let html = `<div></div>` + hm.bins.map((b) => `<div class="h">${b}</div>`).join("");
  for (const r of hm.rows) {
    html += `<div class="d">${r.label}</div>`;
    r.cells.forEach((v, i) => {
      if (v == null) { html += `<div class="c empty" aria-label="${r.label}, ${hm.bins[i]}: no check"></div>`; return; }
      const col = TT.scoreColor(v);
      html += `<div class="c" style="background:${col.bg};color:${col.fg}" title="${r.label}, ${hm.bins[i]} after dose: mean ${v} (${r.n[i]} check${r.n[i] > 1 ? "s" : ""})">${v}</div>`;
    });
  }
  box.innerHTML = html;
  $("scale-bar").style.background = `linear-gradient(90deg, ${[20, 40, 60, 75, 90].map((s) => TT.scoreColor(s).bg).join(",")})`;
}

function renderBars(tests) {
  $("bars").innerHTML = TEST_ORDER.map((k) => {
    const t = tests[k];
    if (!t) return "";
    const b = (v, cls) => (v == null ? "" : `<div class="b ${cls}" style="width:${Math.max(2, v)}%"></div>`);
    return `<div class="bar-row"><span class="name">${t.label}</span><div class="track" role="img" aria-label="${t.label}: peak ${t.peak}, late ${t.late}">${b(t.peak, "s1")}${b(t.late, "s2")}</div>
      <span class="vals">${t.peak ?? "—"}<br>${t.late ?? "—"}</span></div>`;
  }).join("");
}

function renderLatestTests(c) {
  if (!c || !c.tests) return;
  const m = c.metrics || {};
  const r = c.results || {};
  const fmt = (v, d = 1) => (v == null ? "—" : Number(v).toFixed(d));
  const detail = {
    flip: r.flip ? `${fmt(r.flip.flips_per_s)} flips/s · amplitude ${fmt(r.flip.amplitude_g, 2)} g · decrement ${fmt(r.flip.amp_decrement_pct, 0)}%` : "",
    tremor: r.tremor ? `${fmt(r.tremor.rms_vec_mg)} mg RMS${r.tremor.dominant_hz ? ` · ${fmt(r.tremor.dominant_hz)} Hz` : ""}` : "",
    taps: r.taps ? `${fmt(r.taps.taps_per_s)} taps/s · rhythm CV ${fmt(r.taps.iti_cv, 2)}` : "",
    voice: r.voice ? `${fmt(r.voice.loudness_dbfs)} dBFS · stability CV ${fmt(r.voice.stability_cv, 2)}` : "",
  };
  $("latest-tests").innerHTML = `<table class="data"><caption class="sr-only">Latest check by test</caption><thead><tr><th>Latest check</th><th>Sub-score</th><th style="text-align:left">Measured</th></tr></thead><tbody>` +
    TEST_ORDER.map((k) => `<tr><td>${STEP_NAMES[k]}</td><td>${c.tests[k] != null ? Math.round(c.tests[k]) : "—"}</td><td style="text-align:left">${detail[k] || (r[k] && r[k].reason) || "—"}</td></tr>`).join("") + "</tbody></table>";
}

function renderSteps(active, done = {}) {
  $("steps").innerHTML = TEST_ORDER.map((k) => {
    const st = done[k] ? "done" : active === k ? "active" : "";
    const label = done[k] ? (done[k].valid === false ? "no signal" : "measured") : active === k ? activePhase : "waiting";
    return `<div class="step ${st}"><div class="t">${STEP_NAMES[k]}</div><div class="s">${label}</div></div>`;
  }).join("");
}
let activePhase = "", stepsDone = {};

function agentFeed(actions) {
  if (!actions.length) return;
  $("agent-feed").innerHTML = actions.map((a) => `<li><time>${TT.fmtTime(a.ts)}</time><span><strong>${TT.esc(a.kind.replace(/_/g, " "))}</strong> · ${TT.esc(a.detail.text || a.detail.summary || JSON.stringify(a.detail))}</span></li>`).join("");
}

async function loadAll() {
  const [status, summary, t, hm, latest, actions] = await Promise.all([
    TT.api("/api/status"), TT.api("/api/summary"), TT.api("/api/today"), TT.api("/api/heatmap"),
    TT.api("/api/checks/latest"), TT.api("/api/actions"),
  ]);
  $("pname").textContent = status.patient.name;
  $("sched").textContent = `levodopa ${status.patient.dose_times.join(", ")}`;
  TT.deviceBadge($("device"), status.device);
  const f = status.features;
  $("foot-meta").textContent = `Storage: ${status.storage === "timescale" ? "TimescaleDB (Tiger Data)" : "local SQLite"} · Records: ${f.finchnode ? "FinchNode " + f.finchnode_mode : "local"} · Reports: ${f.gemini ? "Gemini" : "template"}${f.quiet ? " · audio muted" : ""}`;
  today = t;
  renderLatest(latest);
  renderLatestTests(latest);
  renderTiles(summary);
  renderToday();
  renderCurve(summary.curve_by_time_since_dose);
  renderHeatmap(hm);
  renderBars(summary.tests);
  agentFeed(actions);
  renderSteps(null);
}

function onEvent(e) {
  switch (e.type) {
    case "hello": case "device": TT.deviceBadge($("device"), e.device || e); break;
    case "check_started":
      stepsDone = {}; activePhase = "instructions";
      $("live-sub").textContent = e.source === "demo" ? "Simulated check running (demo replay)…" : "Check running on the wrist…";
      $("live-result").innerHTML = "";
      renderSteps("flip"); feed("Check started"); break;
    case "step":
      activePhase = e.phase === "instruct" ? "instructions" : e.phase === "record" ? `recording ${e.seconds} s` : "done";
      if (e.phase === "done") { stepsDone[e.step] = e.result || {}; }
      renderSteps(e.phase === "done" ? TEST_ORDER[TEST_ORDER.indexOf(e.step) + 1] : e.step, stepsDone);
      if (e.phase === "done") feed(`${STEP_NAMES[e.step]} measured`);
      break;
    case "check_cancelled": $("live-sub").textContent = "Check cancelled on the wrist."; feed("Check cancelled"); break;
    case "check_result": {
      liveIds.add(e.id);
      $("live-sub").textContent = "Latest result from the wrist:";
      $("live-result").innerHTML = `<div class="hero"><span class="num">${e.score ?? "—"}</span><span class="of">/ 100</span>${TT.levelHTML(e.level)}</div><p class="sub">${TT.fmtMins(e.minutes_since_dose)} after last dose</p>`;
      renderSteps(null, stepsDone);
      feed(`Check finished: score ${e.score}`);
      TT.toast(`New wrist check: ${e.score} (${e.level})`);
      renderLatest(e); renderLatestTests(e);
      if (today) { today.checks.push(e); renderToday(); }
      refreshSoon();
      break;
    }
    case "dose":
      feed("Dose logged" + (e.source === "button" ? " (red button)" : ""), e.ts);
      if (today) { today.doses.push({ ts: e.ts }); renderToday(); }
      break;
    case "passive": feed(`Passive tremor sample: ${e.rms_mg.toFixed(0)} mg`, e.ts); break;
    case "alert": feed(e.text); TT.toast(e.text); break;
    case "agent_action": TT.api("/api/actions").then(agentFeed); feed(`Agent: ${e.kind.replace(/_/g, " ")}`); break;
    case "report": showReport(e.report); break;
  }
}
let refreshTimer;
function refreshSoon() { clearTimeout(refreshTimer); refreshTimer = setTimeout(() => loadAll().catch(console.error), 1500); }

function showReport(r) {
  $("rep-neuro").innerHTML = TT.md(r.neurologist_report);
  $("rep-patient").innerHTML = TT.md(r.patient_summary);
  $("report-sub").textContent = `Generated ${TT.fmtTime(r.generated_at)} by ${r.engine}. Patterns only, no medication advice.`;
}

$("btn-check").onclick = async (ev) => {
  ev.target.disabled = true;
  try {
    const r = await TT.post("/api/check/start", {});
    TT.toast(r.simulate ? "No wrist device: running a simulated check" : "Check started: follow the wrist");
  } catch (e) { TT.toast("Could not start a check"); }
  setTimeout(() => (ev.target.disabled = false), 3000);
};
$("btn-dose").onclick = async () => { await TT.post("/api/dose", { source: "dashboard" }); TT.toast("Dose logged"); };
$("btn-report").onclick = async (ev) => {
  ev.target.disabled = true; ev.target.textContent = "Generating…";
  try { showReport(await TT.post("/api/report", {})); }
  catch (e) { TT.toast("Report generation failed"); }
  ev.target.disabled = false; ev.target.textContent = "Generate visit report";
};
for (const [tab, panel, other, otherPanel] of [["tab-neuro", "rep-neuro", "tab-patient", "rep-patient"], ["tab-patient", "rep-patient", "tab-neuro", "rep-neuro"]]) {
  $(tab).onclick = () => { $(tab).setAttribute("aria-selected", "true"); $(other).setAttribute("aria-selected", "false"); $(panel).hidden = false; $(otherPanel).hidden = true; };
}
window.addEventListener("resize", () => { clearTimeout(window._rs); window._rs = setTimeout(() => loadAll(), 250); });

loadAll().catch((e) => { console.error(e); TT.toast("Could not load data"); });
TT.api("/api/report/latest").then((r) => r && r.neurologist_report && showReport(r)).catch(() => {});
TT.live(onEvent);
