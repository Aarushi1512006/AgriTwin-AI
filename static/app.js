const $ = s => document.querySelector(s);
let charts = [], farmId = null;
const CROPS = ["wheat", "tomato", "maize", "cotton", "potato"], SOILS = ["sandy", "loam", "clay"],
      STAGES = ["seedling", "vegetative", "flowering", "maturity"];
const ICON = { wheat: "🌾", tomato: "🍅", maize: "🌽", cotton: "🌿", potato: "🥔" };
const SC = { critical: "#c62828", low: "#ef6c00", adequate: "#2e7d32", excess: "#1565c0" };
const opt = (a, v) => a.map(x => `<option ${x === v ? "selected" : ""}>${x}</option>`).join("");
async function api(u, o) {
  const r = await fetch(u, o), j = await r.json();
  if (!r.ok) throw new Error(j.error || "Error");
  return j;
}
function addPlot(p = {}) {
  const d = document.createElement("div"); d.className = "prow";
  d.innerHTML = `<label>Plot name</label><input class="pn" value="${p.name || "Plot " + ($("#plots").children.length + 1)}">
  <label>Crop</label><select class="pc">${opt(CROPS, p.crop)}</select>
  <label>Soil</label><select class="ps">${opt(SOILS, p.soil || "loam")}</select>
  <label>Growth stage</label><select class="pg">${opt(STAGES, p.stage || "vegetative")}</select>
  <label>Current soil moisture (%)</label><input class="pm" type="number" value="${p.moisture || 30}">`;
  $("#plots").appendChild(d);
}
function example() {
  $("#plots").innerHTML = "";
  addPlot({ name: "Plot A", crop: "wheat", moisture: 38 });
  addPlot({ name: "Plot B", crop: "tomato", stage: "flowering", moisture: 17 });
}
async function createFarm() {
  $("#err").textContent = "";
  const plots = [...document.querySelectorAll(".prow")].map(r => ({
    name: r.querySelector(".pn").value, crop: r.querySelector(".pc").value, soil: r.querySelector(".ps").value,
    stage: r.querySelector(".pg").value, moisture: +r.querySelector(".pm").value }));
  try {
    const j = await api("/api/farm", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name: $("#name").value, size_ha: +$("#size").value, water_l_day: +$("#water").value, plots }) });
    farmId = j.id; render(await api("/api/farm/" + farmId));
  } catch (e) { $("#err").textContent = e.message; }
}
async function advance() { render(await api(`/api/farm/${farmId}/advance`, { method: "POST" })); }
function goCard(id) {
  const e = $("#card" + id); e.scrollIntoView({ behavior: "smooth", block: "center" });
  e.classList.remove("flash"); void e.offsetWidth; e.classList.add("flash");
}
const mix = (a, b, t) => "#" + [1, 3, 5].map(i => Math.round(parseInt(a.substr(i, 2), 16) * (1 - t) + parseInt(b.substr(i, 2), 16) * t)
  .toString(16).padStart(2, "0")).join("");

function farmMap(d) {
  const n = d.plots.length, cols = n > 3 ? Math.ceil(n / 2) : n, rows = Math.ceil(n / cols), gx = 14;
  const X0 = 100, Y0 = 48, W = 540, H = 290, tw = (W - (cols - 1) * gx) / cols, th = (H - (rows - 1) * gx) / rows;
  const wet = d.model.rain24 > 2, b = d.budget, fill = b.available ? Math.min(1, b.allocated / b.available) : 0;
  let s = `<svg viewBox="0 0 800 380" class="map"><defs><linearGradient id="gr" x1="0" y1="0" x2="0" y2="1">
    <stop offset="0" stop-color="#9bd873"/><stop offset="1" stop-color="#5fa84a"/></linearGradient></defs>
    <rect width="800" height="380" rx="18" fill="url(#gr)"/>
    <rect x="${X0 - 14}" y="${Y0 - 14}" width="${W + 28}" height="${H + 28}" rx="12" fill="#c9a66b" opacity=".6"/>
    <text x="26" y="86" font-size="46">🏡</text><text x="24" y="345" font-size="42">🚜</text>
    <text x="40" y="190" font-size="34">🌳</text><text x="52" y="250" font-size="30">🌳</text><text x="${wet ? 700 : 690}" y="40" font-size="${wet ? 34 : 40}">${wet ? "🌧️" : "☀️"}</text>
    <text x="660" y="345" font-size="30">🌳</text><text x="715" y="350" font-size="26">🌼</text>`;
  d.plots.forEach((p, i) => {
    const c = i % cols, r = Math.floor(i / cols), x = X0 + c * (tw + gx), y = Y0 + r * (th + gx);
    const soil = mix("#e2c48f", "#5b3a22", Math.min(1, p.current / 50)), irr = p.action.startsWith("IRRIGATE");
    const nx = Math.min(8, Math.floor((tw - 16) / 24)), ny = Math.min(5, Math.floor((th - 62) / 22));
    s += `<g class="tile ${p.status}" onclick="goCard(${p.id})"><title>${p.name}: ${p.current}% – ${p.action}</title>
      <rect x="${x}" y="${y}" width="${tw}" height="${th}" rx="10" fill="${soil}" stroke="${SC[p.status]}" stroke-width="3"/>`;
    for (let j = 0; j < ny; j++) {
      s += `<line x1="${x + 8}" x2="${x + tw - 8}" y1="${y + 50 + j * 22}" y2="${y + 50 + j * 22}" stroke="#0003" stroke-width="2"/>`;
      for (let k = 0; k < nx; k++)
        s += `<text class="pl" x="${x + 8 + (k + .5) * (tw - 16) / nx}" y="${y + 47 + j * 22}">${ICON[p.crop]}</text>`;
    }
    if (irr) s += `<g transform="translate(${x + tw / 2},${y + th / 2 + 14})"><circle r="7" fill="#1e88e5"/><circle class="rip" r="9"/><circle class="rip d2" r="9"/></g>`;
    s += `<rect x="${x + 6}" y="${y + 6}" width="${Math.min(tw - 12, 190)}" height="34" rx="9" fill="#000a"/>
      <text x="${x + 14}" y="${y + 20}" fill="#fff" font-size="12" font-weight="700">${p.name} · ${p.crop}</text>
      <text x="${x + 14}" y="${y + 35}" fill="${p.status === "adequate" ? "#9be79d" : p.status === "excess" ? "#90caf9" : "#ffb199"}" font-size="12">💧 ${p.current}% ${p.status}</text>
      <text x="${x + tw - 10}" y="${y + th - 8}" text-anchor="end" font-size="11" font-weight="700" fill="#fff" stroke="#0007" stroke-width="3" paint-order="stroke">${p.action}</text></g>`;
  });
  s += `<rect x="676" y="82" width="86" height="210" rx="14" fill="#fff" stroke="#546e7a" stroke-width="3"/>
    <rect x="679" y="${289 - 204 * fill}" width="80" height="${204 * fill}" rx="11" fill="#29b6f6"/>
    <text x="719" y="70" text-anchor="middle" font-size="12" font-weight="700" fill="#fff">💧 Water tank</text>
    <text x="719" y="190" text-anchor="middle" font-size="12" font-weight="700" fill="#0d3b55">${Math.round(b.allocated / 1000)}k L</text>
    <text x="719" y="206" text-anchor="middle" font-size="10" fill="#0d3b55">of ${Math.round(b.available / 1000)}k</text>`;
  if (wet) for (let i = 0; i < 45; i++)
    s += `<rect class="drop" x="${(i * 53) % 790}" y="${(i * 37) % 120}" width="2" height="14" style="animation-delay:${(i % 9) / 10}s"/>`;
  return s + "</svg>";
}
const NAME = { none: "No irrigation", now: "Irrigate now", delay: "Delay 12 h", reduce: "Reduce 50%" };
const COL = { none: "#c62828", now: "#2e7d32", delay: "#1565c0", reduce: "#ef6c00" };
function gauge(p) {
  const C = 2 * Math.PI * 34, v = Math.min(1, p.current / 60) * C;
  return `<svg width="86" height="86" viewBox="0 0 86 86"><circle cx="43" cy="43" r="34" fill="none" stroke="#e3ebe3" stroke-width="9"/>
  <circle cx="43" cy="43" r="34" fill="none" stroke="${SC[p.status]}" stroke-width="9" stroke-linecap="round" stroke-dasharray="${v} ${C}" transform="rotate(-90 43 43)"/>
  <text x="43" y="48" text-anchor="middle" font-size="17" font-weight="700">${p.current}%</text></svg>`;
}
function card(p) {
  const rows = Object.entries(p.scenarios).map(([k, s]) => `<tr class="${k === p.best ? "best" : ""}"><td>${NAME[k]}</td>
    <td>${s.mm}</td><td>${s.liters}</td><td>${s.stress_hours}</td><td>${s.over_hours}</td><td>${s.final}%</td></tr>`).join("");
  return `<div class="card ${p.status}" id="card${p.id}"><div class="head">${gauge(p)}<div class="t">
  <b style="font-size:17px">${ICON[p.crop]} ${p.name}</b> <span class="badge">${p.status}</span>
  <div class="note">${p.crop} · ${p.soil} soil · ${p.stage} · ${p.area_m2} m²</div>
  <div class="act">${p.action}${p.priority ? " · priority #" + p.priority : ""}</div></div></div>
  <canvas id="ch${p.id}" height="150"></canvas>
  <table><tr><th>What-if (48 h)</th><th>mm</th><th>Litres</th><th>Stress h</th><th>Over-wet h</th><th>Final</th></tr>${rows}</table>
  <b>Why this recommendation?</b><ul>${p.why.map(w => `<li>${w}</li>`).join("")}</ul></div>`;
}
function render(d) {
  $("#dash").hidden = false;
  charts.forEach(c => c.destroy()); charts = [];
  const w = d.weather, wet = d.model.rain24 > 2, b = d.budget, P = d.plots;
  $("#hero").classList.toggle("rainy", wet);
  $("#rain").innerHTML = wet ? Array.from({ length: 70 }, (_, i) => `<i style="left:${i * 1.45}%;animation-delay:${(i % 10) / 10}s"></i>`).join("") : "";
  const avg = P.reduce((a, p) => a + p.current, 0) / P.length, need = P.filter(p => p.action.startsWith("IRRIGATE")).length;
  $("#kpis").innerHTML = [["🌡", w[0].t + "°C", "Temperature"], ["💨", w[0].h + "%", "Humidity"], ["🌧", d.model.rain24 + " mm", "Rain next 24 h"],
    ["💧", avg.toFixed(1) + "%", "Avg soil moisture"], ["🚿", need + " / " + P.length, "Plots to irrigate"],
    ["🛢", Math.round(b.allocated / 1000) + "k / " + Math.round(b.requested / 1000) + "k L", "Allocated / requested"]]
    .map(k => `<div class="kpi"><span>${k[0]} ${k[2]}</span><b>${k[1]}</b></div>`).join("");
  $("#fname").textContent = `${d.farm.name} · ${d.farm.size_ha} ha · hour ${d.now}`;
  $("#map").innerHTML = farmMap(d);
  const m = d.model;
  $("#model").textContent = `AI model: random forest on ${m.rows} dry-hour samples` +
    (m.mae != null ? ` · hold-out MAE ${m.mae.toFixed(3)} %/h vs baseline ${m.baseline_mae.toFixed(3)}` : "") + " · click a field to jump to its details";
  $("#alerts").innerHTML = d.alerts.map(a => `<li class="${a.level}">${a.text}</li>`).join("") || "<li>No alerts 🎉</li>";
  $("#cards").innerHTML = P.map(card).join("");
  const mk = (el, cfg) => { try { charts.push(new Chart(el, cfg)); } catch (e) { console.error(e); el.insertAdjacentHTML("afterend", `<p class="note">Chart error: ${e.message}</p>`); } };
  mk($("#wx"), { type: "bar", data: { labels: w.map((_, i) => i + "h"), datasets: [
    { type: "bar", label: "Rain mm", data: w.map(x => x.r), backgroundColor: "#4fc3f7", yAxisID: "yr" },
    { type: "line", label: "Temp °C", data: w.map(x => x.t), borderColor: "#ef6c00", pointRadius: 0, tension: .4, yAxisID: "yt" }] },
    options: { plugins: { legend: { labels: { boxWidth: 10 } } }, scales: { yr: { axis: "y", position: "right", grid: { display: false }, beginAtZero: true, title: { display: true, text: "mm" } }, yt: { axis: "y", position: "left", title: { display: true, text: "°C" } }, x: { ticks: { maxTicksLimit: 8 } } } } });
  P.forEach(p => {
    const H = p.history.length, labels = [];
    for (let i = -(H - 1); i <= 48; i++) labels.push(i + "h");
    const line = (label, data, color, dash, fillIt) => ({ label, data, borderColor: color, borderDash: dash || [], pointRadius: 0, borderWidth: dash ? 2 : 2.5, tension: .3, fill: fillIt, backgroundColor: color + "22" });
    const ds = [line("Sensor (cleaned)", [...p.history, ...Array(48).fill(null)], "#333", null, true)];
    for (const k of Object.keys(p.scenarios)) ds.push(line(NAME[k], [...Array(H - 1).fill(null), ...p.scenarios[k].traj], COL[k], [5, 3]));
    ds.push(line("Stress level", Array(labels.length).fill(p.thr.low), "#c62828", [2, 2]));
    ds.push(line("Comfort min", Array(labels.length).fill(p.thr.lo), "#2e7d32", [2, 2]));
    mk($("#ch" + p.id), { type: "line", data: { labels, datasets: ds },
      options: { plugins: { legend: { labels: { boxWidth: 12, font: { size: 10 } } } },
        scales: { x: { ticks: { maxTicksLimit: 10 } }, y: { title: { display: true, text: "Soil moisture %" } } } } });
  });
}
example();
api("/api/farms/latest").then(async j => { if (j.id) { farmId = j.id; render(await api("/api/farm/" + j.id)); } });