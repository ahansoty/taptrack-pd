// Shared helpers for the TapTrack PD dashboards (no build step, no external libs).
const TT = (() => {
  const SVGNS = "http://www.w3.org/2000/svg";
  const api = async (path, opts = {}) => {
    const r = await fetch(path, { headers: { "Content-Type": "application/json" }, ...opts });
    if (!r.ok) throw new Error(`${path}: ${r.status}`);
    return r.json();
  };
  const post = (path, body = {}) => api(path, { method: "POST", body: JSON.stringify(body) });
  const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  const el = (tag, attrs = {}, parent) => {
    const n = tag.startsWith("svg:") ? document.createElementNS(SVGNS, tag.slice(4)) : document.createElement(tag);
    for (const [k, v] of Object.entries(attrs)) {
      if (k === "text") n.textContent = v;
      else if (k === "html") n.innerHTML = v;
      else n.setAttribute(k, v);
    }
    if (parent) parent.appendChild(n);
    return n;
  };
  const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const fmtTime = (ts) => new Date(ts * 1000).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
  const fmtDay = (ts) => new Date(ts * 1000).toLocaleDateString([], { weekday: "short", month: "short", day: "numeric" });
  const fmtMins = (m) => (m == null ? "no dose logged" : m < 60 ? `${Math.round(m)} min` : `${Math.floor(m / 60)} h ${Math.round(m % 60)} min`);

  const LEVEL = {
    good: { text: "Good", icon: '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="10" fill="currentColor" opacity=".15"/><path d="M7 12.5l3.2 3.2L17 9" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"/></svg>' },
    fair: { text: "Fair", icon: '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="10" fill="currentColor" opacity=".15"/><path d="M7 12h10" stroke="currentColor" stroke-width="2.4" stroke-linecap="round"/></svg>' },
    low: { text: "Low", icon: '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="10" fill="currentColor" opacity=".15"/><path d="M12 7v6M12 16.5v.5" stroke="currentColor" stroke-width="2.4" stroke-linecap="round"/></svg>' },
    none: { text: "No result", icon: "" },
  };
  const levelHTML = (lvl) => `<span class="level ${lvl}">${LEVEL[lvl]?.icon || ""}${LEVEL[lvl]?.text || ""}</span>`;
  const levelOf = (s) => (s == null ? "none" : s >= 70 ? "good" : s >= 50 ? "fair" : "low");

  function toast(msg) {
    let t = document.querySelector(".toast");
    if (!t) { t = el("div", { class: "toast", role: "status", "aria-live": "polite" }, document.body); }
    t.textContent = msg;
    t.classList.add("show");
    clearTimeout(t._h);
    t._h = setTimeout(() => t.classList.remove("show"), 4200);
  }

  // ---------------------------------------------------------------- line chart
  // opts: {x:[min,max], y:[min,max], series:[{points:[{x,y,label,live}], cls, area, band:[{x,lo,hi}]}],
  //        doses:[x], xTicks:[{v,label}], yTicks:[v], band:[lo,hi], height, xLabel, tooltip(fn)}
  function lineChart(container, opts) {
    container.innerHTML = "";
    container.classList.add("chart");
    const W = Math.max(320, container.clientWidth || 640), H = opts.height || 280;
    const m = { l: 44, r: 16, t: 26, b: 34 };
    const sx = (v) => m.l + ((v - opts.x[0]) / (opts.x[1] - opts.x[0])) * (W - m.l - m.r);
    const sy = (v) => H - m.b - ((v - opts.y[0]) / (opts.y[1] - opts.y[0])) * (H - m.t - m.b);
    const svg = el("svg:svg", { viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": opts.ariaLabel || "chart" }, container);
    const inX = (v) => v >= opts.x[0] && v <= opts.x[1];
    const inY = (v) => v >= opts.y[0] && v <= opts.y[1];
    const clipId = `clip${Math.random().toString(36).slice(2, 8)}`;
    const defs = el("svg:defs", {}, svg);
    const cp = el("svg:clipPath", { id: clipId }, defs);
    el("svg:rect", { x: m.l, y: m.t - 8, width: W - m.l - m.r, height: H - m.t - m.b + 16 }, cp);
    if (opts.band) {
      el("svg:rect", { class: "band", x: m.l, width: W - m.l - m.r, y: sy(opts.band[1]), height: sy(opts.band[0]) - sy(opts.band[1]) }, svg);
      el("svg:text", { x: W - m.r - 4, y: sy(opts.band[1]) + 14, "text-anchor": "end", text: opts.bandLabel || "" }, svg);
    }
    for (const v of opts.yTicks || []) {
      const g = el("svg:g", { class: "tick" }, svg);
      el("svg:line", { x1: m.l, x2: W - m.r, y1: sy(v), y2: sy(v) }, g);
      el("svg:text", { x: m.l - 8, y: sy(v) + 4, "text-anchor": "end", text: v }, g);
    }
    el("svg:line", { class: "axis", x1: m.l, x2: W - m.r, y1: H - m.b, y2: H - m.b }, svg);
    const narrow = W < 560;
    const ticks = (opts.xTicks || []).filter((t, i) => !narrow || i % 2 === 0);
    for (const t of ticks) {
      el("svg:text", { x: sx(t.v), y: H - m.b + 20, "text-anchor": "middle", text: t.label }, svg);
    }
    for (const d of (opts.doses || []).filter((d) => inX(d.x))) {
      const g = el("svg:g", { class: "dose" }, svg);
      el("svg:line", { x1: sx(d.x), x2: sx(d.x), y1: m.t - 6, y2: H - m.b }, g);
      el("svg:path", { d: `M${sx(d.x) - 6},${m.t - 14} h12 l-6,8 z`, fill: "var(--dose)" }, g);
      if (!narrow) el("svg:text", { x: sx(d.x) + 9, y: m.t - 6, text: d.label || "Dose" }, g);
      el("svg:title", { text: d.label || "Dose" }, g);
    }
    const plot = el("svg:g", { "clip-path": `url(#${clipId})` }, svg);
    for (const s of opts.series) {
      const pts = s.points.filter((p) => p.y != null && inX(p.x) && inY(p.y));
      const band = (s.bandPts || []).filter((p) => inX(p.x));
      if (band.length > 1) {
        const up = band.map((p) => `${sx(p.x)},${sy(p.hi)}`).join(" L");
        const dn = band.slice().reverse().map((p) => `${sx(p.x)},${sy(p.lo)}`).join(" L");
        el("svg:path", { class: "area", d: `M${up} L${dn} Z` }, plot);
      }
      if (pts.length > 1) {
        // break the line across gaps (e.g. missed checks spanning > gap)
        let d = "";
        pts.forEach((p, i) => {
          const brk = i === 0 || (s.gap && p.x - pts[i - 1].x > s.gap);
          d += `${brk ? "M" : "L"}${sx(p.x)},${sy(p.y)} `;
        });
        el("svg:path", { class: `line ${s.cls || ""}`, d }, plot);
      }
      if (s.dots !== false) for (const p of pts) el("svg:circle", { class: `dotm ${p.live ? "live" : ""}`, cx: sx(p.x), cy: sy(p.y), r: p.live ? 6 : 4.5 }, plot);
      if (s.endLabel && pts.length) {
        const p = pts[pts.length - 1];
        el("svg:text", { class: "label-strong", x: sx(p.x), y: sy(p.y) - 12, "text-anchor": "middle", text: s.endLabel(p) }, svg);
      }
    }
    if (opts.xLabel) el("svg:text", { x: W - m.r, y: H - 2, "text-anchor": "end", text: opts.xLabel }, svg);
    // hover: nearest point across series
    const tip = el("div", { class: "tooltip", role: "presentation" }, container);
    const all = opts.series.flatMap((s) => s.points.filter((p) => p.y != null && inX(p.x) && inY(p.y)));
    const cross = el("svg:line", { class: "axis", y1: m.t, y2: H - m.b, opacity: 0 }, svg);
    const hit = el("svg:rect", { class: "hit", x: m.l, y: m.t, width: W - m.l - m.r, height: H - m.t - m.b }, svg);
    const move = (evt) => {
      if (!all.length) return;
      const r = svg.getBoundingClientRect();
      const px = ((evt.clientX - r.left) / r.width) * W;
      let best = all[0];
      for (const p of all) if (Math.abs(sx(p.x) - px) < Math.abs(sx(best.x) - px)) best = p;
      cross.setAttribute("x1", sx(best.x)); cross.setAttribute("x2", sx(best.x)); cross.setAttribute("opacity", 1);
      tip.innerHTML = opts.tooltip ? opts.tooltip(best) : `${best.y}`;
      tip.style.left = `${(sx(best.x) / W) * r.width}px`;
      tip.style.top = `${(sy(best.y) / H) * r.height}px`;
      tip.classList.add("show");
    };
    hit.addEventListener("pointermove", move);
    hit.addEventListener("pointerleave", () => { tip.classList.remove("show"); cross.setAttribute("opacity", 0); });
    return { sx, sy, svg };
  }

  // ---------------------------------------------------------------- diverging color (score)
  const hex2rgb = (h) => { h = h.replace("#", ""); return [0, 2, 4].map((i) => parseInt(h.slice(i, i + 2), 16)); };
  const mix = (a, b, t) => a.map((v, i) => Math.round(v + (b[i] - v) * t));
  function scoreColor(s) {
    const lo = hex2rgb(css("--div-lo")), mid = hex2rgb(css("--div-mid")), hi = hex2rgb(css("--div-hi"));
    const MID = 60; // neutral at the "fair" midpoint
    const c = s < MID ? mix(lo, mid, Math.max(0, (s - 20) / (MID - 20))) : mix(mid, hi, Math.min(1, (s - MID) / 30));
    const lum = (0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]) / 255;
    return { bg: `rgb(${c.join(",")})`, fg: lum > 0.55 ? "#0b0b0b" : "#ffffff" };
  }

  // ---------------------------------------------------------------- websocket
  function live(onEvent, onState) {
    let ws, delay = 1000;
    const connect = () => {
      ws = new WebSocket(`${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/ws`);
      ws.onopen = () => { delay = 1000; onState && onState(true); };
      ws.onmessage = (m) => { try { onEvent(JSON.parse(m.data)); } catch (e) { console.error(e); } };
      ws.onclose = () => { onState && onState(false); setTimeout(connect, delay); delay = Math.min(delay * 2, 10000); };
    };
    connect();
  }

  function deviceBadge(target, dev) {
    if (!dev) return;
    let cls = "warn", text = "Wrist offline";
    if (dev.demo) { cls = "warn"; text = "Demo wrist"; }
    else if (dev.connected) { cls = "ok"; text = dev.state === "check" ? "Check running" : "Wrist connected"; }
    target.className = `pill ${cls}`;
    target.innerHTML = `<span class="dot" aria-hidden="true"></span>${text}`;
  }

  // simple, safe markdown subset for reports
  function md(text) {
    const lines = esc(text).split(/\r?\n/);
    let out = "", list = false;
    for (let ln of lines) {
      ln = ln.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");
      if (/^#{1,6}\s/.test(ln)) { if (list) { out += "</ul>"; list = false; } out += `<h3>${ln.replace(/^#+\s/, "")}</h3>`; }
      else if (/^\s*[-*]\s/.test(ln)) { if (!list) { out += "<ul>"; list = true; } out += `<li>${ln.replace(/^\s*[-*]\s/, "")}</li>`; }
      else if (ln.trim() === "") { if (list) { out += "</ul>"; list = false; } }
      else { if (list) { out += "</ul>"; list = false; } out += `<p>${ln}</p>`; }
    }
    return out + (list ? "</ul>" : "");
  }

  // signed-in user in the header; caregivers don't get the clinician link
  async function session() {
    const me = await api("/api/me").catch(() => ({}));
    if (!me.role) { location.href = "/login"; return me; }
    const nav = document.querySelector("nav.views");
    if (nav) {
      if (me.role !== "clinician") nav.querySelectorAll('a[href="/"]').forEach((a) => a.remove());
      el("span", { class: "avatar", text: (me.email || "?")[0].toUpperCase(), title: `${me.email} (${me.role})`, "aria-label": `Signed in as ${me.email}, ${me.role}` }, nav);
      const b = el("button", { class: "link", type: "button", text: "Sign out" }, nav);
      b.onclick = async () => { await post("/api/logout"); location.href = "/login"; };
    }
    return me;
  }

  function statusClass(node, level) {
    node.classList.remove("good", "fair", "low");
    if (["good", "fair", "low"].includes(level)) node.classList.add("status", level);
  }

  return { api, post, el, esc, css, fmtTime, fmtDay, fmtMins, levelHTML, levelOf, toast, lineChart, scoreColor, live, deviceBadge, md, session, statusClass };
})();
