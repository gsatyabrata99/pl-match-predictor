let DATA, M, T;
const pct = (x, d = 0) => (100 * x).toFixed(d) + "%";

function predict(h, a) {
  const lh = M.mu_h * T[h].att * T[a].dfn, la = M.mu_a * T[a].att * T[h].dfn;
  const pois = (k, l) => { let p = Math.exp(-l); for (let i = 1; i <= k; i++) p *= l / i; return p; };
  const N = M.maxg, rho = M.rho;
  let G = [];
  for (let i = 0; i <= N; i++) { G.push([]); for (let j = 0; j <= N; j++) G[i].push(pois(i, lh) * pois(j, la)); }
  G[0][0] *= 1 - lh * la * rho; G[0][1] *= 1 + lh * rho; G[1][0] *= 1 + la * rho; G[1][1] *= 1 - rho;
  const s = G.flat().reduce((x, y) => x + y, 0); G = G.map(r => r.map(v => v / s));
  let ph = 0, pa = 0, o25 = 0, btts = 0, best = [0, 0, 0];
  const bestBy = { H: [0, 0, 0], D: [0, 0, 0], A: [0, 0, 0] };   // likeliest score within each result
  G.forEach((r, i) => r.forEach((v, j) => {
    if (i > j) ph += v; else if (i < j) pa += v;
    if (i + j > 2) o25 += v; if (i > 0 && j > 0) btts += v;
    if (v > best[2]) best = [i, j, v];
    const k = i > j ? "H" : i < j ? "A" : "D";
    if (v > bestBy[k][2]) bestBy[k] = [i, j, v];
  }));
  const pd = 1 - ph - pa;
  const fav = ph >= pd && ph >= pa ? "H" : pa >= pd ? "A" : "D";      // most likely result
  return { lh, la, G, ph, pa, pd, o25, btts, csH: G.reduce((x, r) => x + r[0], 0), csA: G[0].reduce((x, y) => x + y, 0), best, bestBy, fav };
}

/* header notes */
function renderNotes() {
  const chips = [`Results through <b>GW${M.results_through_gw}</b>`];
  if (M.xg_through_gw < M.results_through_gw) chips.push(`xG data through <b>GW${M.xg_through_gw}</b>`);
  if (M.missing.length) chips.push(`Awaiting result: <b>${M.missing.map(esc).join(", ")}</b>`);
  chips.push(`Updated <b>${new Date(M.generated).toLocaleString(undefined, { day: "numeric", month: "short", hour: "numeric", minute: "2-digit" })}</b>`);
  document.getElementById("notes").innerHTML = chips.map(c => `<span class="chip">${c}</span>`).join("");
}
const esc = s => String(s).replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

/* routing */
const VIEWS = ["gameweek", "matchup", "ratings", "record", "method"];
function show() {
  const v = VIEWS.includes(location.hash.slice(1)) ? location.hash.slice(1) : "gameweek";
  document.querySelectorAll("[data-v]").forEach(s => s.hidden = s.dataset.v !== v);
  document.querySelectorAll("nav button").forEach(b => b.setAttribute("aria-selected", b.dataset.view === v));
}
document.querySelectorAll("nav button").forEach(b => b.onclick = () => { location.hash = b.dataset.view; });
addEventListener("hashchange", show);

/* gameweek view */
const gwSel = document.getElementById("gw-select");
function initGW() {
  const gws = [...new Set(DATA.fixtures.map(f => f.gw))];
  gwSel.innerHTML = gws.map(g => `<option value="${g}">Gameweek ${g}</option>`).join("");
}
function bar(p) {
  const seg = (cls, v) => `<div class="${cls}" style="width:${(v * 100).toFixed(1)}%">${v >= .12 ? pct(v) : ""}</div>`;
  return `<div class="bar">${seg("h", p.ph)}${seg("d", p.pd)}${seg("a", p.pa)}</div>`;
}
// When the single likeliest score has a different result from the most likely result
// (e.g. 1–1 is the top cell but a home win is 53%), name the favourite's likeliest score.
function favLine(p, h, a) {
  const outcomeOf = ([i, j]) => i > j ? "H" : i < j ? "A" : "D";
  if (p.fav === "D" || outcomeOf(p.best) === p.fav) return "";
  const b = p.bestBy[p.fav], who = esc(T[p.fav === "H" ? h : a].short);
  return `<div class="fav">${who} win · ${b[0]}–${b[1]}</div>`;
}

function renderGW() {
  const g = +gwSel.value, list = DATA.fixtures.filter(f => f.gw === g);
  document.getElementById("gw-title").textContent = `Gameweek ${g}`;
  let html = "", lastDay = "";
  for (const f of list) {
    const d = new Date(f.kickoff);
    const day = d.toLocaleDateString(undefined, { weekday: "long", day: "numeric", month: "long" });
    if (day !== lastDay) { html += `<div class="eyebrow" style="margin-top:10px">${day}</div>`; lastDay = day; }
    const p = predict(f.home, f.away);
    const time = d.toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" });
    html += `<button class="fx" data-h="${f.home}" data-a="${f.away}">
      <div class="teams"><span class="t">${f.home}<small>${time}</small></span><span class="t">${f.away}</span></div>
      <div class="probs">${bar(p)}<div class="bar-legend"><span class="num">xG ${p.lh.toFixed(2)}</span><span class="num">${p.la.toFixed(2)} xG</span></div></div>
      <div class="score"><div class="big num">${p.best[0]}–${p.best[1]}</div><div class="lbl">likeliest score</div>${favLine(p, f.home, f.away)}</div>
    </button>`;
  }
  document.getElementById("gw-list").innerHTML = html;
  document.querySelectorAll(".fx").forEach(b => b.onclick = () => {
    hSel.value = b.dataset.h; aSel.value = b.dataset.a; renderMatch(); location.hash = "matchup";
  });
}
gwSel.onchange = renderGW;

/* matchup view */
const hSel = document.getElementById("m-home"), aSel = document.getElementById("m-away");
function initMatch() {
  const opts = DATA.teams.map(t => `<option>${esc(t.name)}</option>`).join("");
  hSel.innerHTML = opts; aSel.innerHTML = opts;
  const first = DATA.fixtures[0] || { home: DATA.teams[0].name, away: DATA.teams[1].name };
  hSel.value = first.home; aSel.value = first.away;
}
function renderMatch() {
  const h = hSel.value, a = aSel.value;
  if (h === a) {
    document.getElementById("m-verdict").innerHTML = `<div style="grid-column:1/-1"><span class="muted">Pick two different teams.</span></div>`;
    document.getElementById("m-heat").innerHTML = ""; document.getElementById("m-stats").innerHTML = ""; return;
  }
  const p = predict(h, a);
  document.getElementById("m-verdict").innerHTML =
    `<div class="home"><span class="eyebrow">${T[h].short} win</span><span class="p num">${pct(p.ph)}</span><span class="muted num" style="font-size:.85rem">likeliest ${p.bestBy.H[0]}–${p.bestBy.H[1]} · xG ${p.lh.toFixed(2)}</span></div>
     <div class="draw"><span class="eyebrow">Draw</span><span class="p num">${pct(p.pd)}</span><span class="muted num" style="font-size:.85rem">likeliest ${p.bestBy.D[0]}–${p.bestBy.D[1]}</span></div>
     <div class="away"><span class="eyebrow">${T[a].short} win</span><span class="p num">${pct(p.pa)}</span><span class="muted num" style="font-size:.85rem">likeliest ${p.bestBy.A[0]}–${p.bestBy.A[1]} · xG ${p.la.toFixed(2)}</span></div>`;
  const max = p.best[2];
  let heat = `<div></div>` + [0,1,2,3,4,5].map(j => `<div class="ax">${j}${j === 5 ? "+" : ""}</div>`).join("");
  for (let i = 0; i <= 5; i++) {
    heat += `<div class="ax">${i}${i === 5 ? "+" : ""}</div>`;
    for (let j = 0; j <= 5; j++) {
      let v = 0;
      for (let ii = i; ii <= (i === 5 ? M.maxg : i); ii++) for (let jj = j; jj <= (j === 5 ? M.maxg : j); jj++) v += p.G[ii][jj];
      const mix = Math.round(8 + 82 * Math.sqrt(v / max));
      const ink = mix > 55 ? "#fff" : "var(--fg)";
      const isBest = i === p.best[0] && j === p.best[1];
      heat += `<div class="c${isBest ? " best" : ""}" title="${h} ${i}–${j} ${a}: ${pct(v, 1)}" style="background:color-mix(in oklab, var(--heat) ${mix}%, var(--sunk));color:${ink}">${(v * 100).toFixed(v < .095 ? 1 : 0)}</div>`;
    }
  }
  document.getElementById("m-heat").innerHTML = heat;
  const rows = [
    ["Over 2.5 goals", p.o25], ["Both teams score", p.btts],
    [`${T[h].short} keeps a clean sheet`, p.csH], [`${T[a].short} keeps a clean sheet`, p.csA],
    [`${T[h].short} wins or draws`, p.ph + p.pd], [`${T[a].short} wins or draws`, p.pa + p.pd],
  ];
  const fair = x => x > 0.001 ? (1 / x).toFixed(2) : "–";
  document.getElementById("m-stats").innerHTML =
    rows.map(([k, v]) => `<div class="stat"><span>${k}</span><span>${pct(v)} <span class="muted">· ${fair(v)}</span></span></div>`).join("") +
    `<p class="muted" style="font-size:.8rem;margin-top:10px">The second number is the fair decimal price: 1 ÷ chance. A bookmaker's price above it would mean the model sees value.</p>`;
}
hSel.onchange = aSel.onchange = renderMatch;

/* ratings view */
let sortKey = "net", sortDir = -1;
const cols = [
  ["#", null], ["Team", "name"], ["Net", "net"], ["Attack", "att"], ["Defence", "dfn"],
  ["P", "p"], ["W-D-L", null], ["GF", "gf"], ["GA", "ga"], ["xGF/g", "xgfg"], ["xGA/g", "xgag"], ["Form", null],
];
let rows = [];
function renderTable() {
  const r = [...rows].sort((x, y) => (sortKey === "name" ? x.name.localeCompare(y.name) : x[sortKey] - y[sortKey]) * sortDir);
  const maxNet = Math.max(...rows.map(t => t.net));
  document.getElementById("r-table").innerHTML =
    `<thead><tr>${cols.map(([l, k]) => `<th ${k ? `data-k="${k}"` : ""}>${l}${k === sortKey ? (sortDir < 0 ? " ↓" : " ↑") : ""}</th>`).join("")}</tr></thead><tbody>` +
    r.map((t, i) => `<tr><td>${i + 1}</td><td class="name">${t.name}<small>${t.promoted ? "PROMOTED" : ""}</small></td>
      <td>${t.net.toFixed(2)}<span class="meter"><i style="width:${(t.net / maxNet * 100).toFixed(0)}%"></i></span></td>
      <td>${t.att.toFixed(2)}</td><td>${t.dfn.toFixed(2)}</td><td>${t.p}</td><td>${t.w}-${t.d}-${t.l}</td>
      <td>${t.gf}</td><td>${t.ga}</td><td>${t.xgfg.toFixed(2)}</td><td>${t.xgag.toFixed(2)}</td>
      <td><span class="form">${[...t.form].map(c => `<b class="${c}">${c}</b>`).join("")}</span></td></tr>`).join("") + "</tbody>";
  document.querySelectorAll("#r-table th[data-k]").forEach(th => th.onclick = () => {
    const k = th.dataset.k; if (k === sortKey) sortDir *= -1; else { sortKey = k; sortDir = (k === "dfn" || k === "ga" || k === "xgag" || k === "name") ? 1 : -1; }
    renderTable();
  });
}
function renderScatter() {
  const W = 720, H = 420, L = 56, R = 24, Tp = 24, B = 48;
  const xs = rows.map(t => t.att), ys = rows.map(t => t.dfn);
  const x0 = Math.floor(Math.min(...xs) * 10) / 10 - .05, x1 = Math.ceil(Math.max(...xs) * 10) / 10 + .05;
  const y0 = Math.floor(Math.min(...ys) * 10) / 10 - .05, y1 = Math.ceil(Math.max(...ys) * 10) / 10 + .05;
  const X = v => L + (v - x0) / (x1 - x0) * (W - L - R);
  const Y = v => Tp + (v - y0) / (y1 - y0) * (H - Tp - B);   // low (good) defence at top
  let s = "";
  for (let v = Math.ceil(x0 * 10) / 10; v <= x1 + 1e-9; v += .1) s += `<line x1="${X(v)}" x2="${X(v)}" y1="${Tp}" y2="${H - B}" stroke="var(--line)" stroke-width="${Math.abs(v - 1) < 1e-9 ? 1.5 : .6}"/><text x="${X(v)}" y="${H - B + 18}" text-anchor="middle" font-size="11" fill="var(--muted)">${v.toFixed(1)}</text>`;
  for (let v = Math.ceil(y0 * 10) / 10; v <= y1 + 1e-9; v += .1) s += `<line x1="${L}" x2="${W - R}" y1="${Y(v)}" y2="${Y(v)}" stroke="var(--line)" stroke-width="${Math.abs(v - 1) < 1e-9 ? 1.5 : .6}"/><text x="${L - 8}" y="${Y(v) + 4}" text-anchor="end" font-size="11" fill="var(--muted)">${v.toFixed(1)}</text>`;
  s += `<text x="${(L + W - R) / 2}" y="${H - 8}" text-anchor="middle" font-size="12" fill="var(--muted)">Attack rating → creates more</text>`;
  s += `<text transform="translate(14 ${(Tp + H - B) / 2}) rotate(-90)" text-anchor="middle" font-size="12" fill="var(--muted)">Defence rating (↑ concedes less)</text>`;
  s += `<text x="${W - R - 6}" y="${Tp + 14}" text-anchor="end" font-size="11" fill="var(--good)">Strong at both ends</text>`;
  s += `<text x="${L + 6}" y="${H - B - 8}" font-size="11" fill="var(--bad)">Struggling at both ends</text>`;
  for (const t of rows) {
    const cx = X(t.att), cy = Y(t.dfn);
    s += `<circle cx="${cx}" cy="${cy}" r="5" fill="${t.promoted ? "var(--away)" : "var(--home)"}" stroke="var(--surface)" stroke-width="1.5"><title>${t.name}: attack ${t.att.toFixed(2)}, defence ${t.dfn.toFixed(2)}</title></circle>`;
    s += `<text x="${cx + 8}" y="${cy + 4}" font-size="11" fill="var(--fg)">${t.short}</text>`;
  }
  document.getElementById("scatter").innerHTML = s;
}

/* record view */
function renderRecord() {
  const b = M.backtest, H = DATA.holdout;
  const last = M.results_through_gw, from = M.holdout_from_gw;
  const span = from === last ? `GW${from}` : `GW${from}–${last}`;
  document.getElementById("oos-title").textContent = `Live test: ${span}`;
  document.getElementById("oos-note").textContent = `These predictions used only matches before GW${from}, so the model had not seen any of these results.`;
  const outcome = o => o.hg > o.ag ? "H" : o.hg < o.ag ? "A" : "D";
  const pick = o => [["H", o.ph], ["D", o.pd], ["A", o.pa]].sort((x, y) => y[1] - x[1])[0][0];
  const hits = H.filter(o => pick(o) === outcome(o)).length;
  document.getElementById("bt-method").textContent =
    `Historical walk-forward backtest of the ${b.season} season: every gameweek was predicted using only matches played before it, plus ratings carried over from the season before. The model never saw a result before predicting it.`;
  document.getElementById("kpis").innerHTML = [
    [pct(b.accuracy), `Correct picks, ${b.season} backtest`, `${b.n} matches, each predicted using only earlier games`],
    [pct(b.home_accuracy), "Always picking the home team", `Same ${b.season} matches: the simple guess to beat`],
    [b.brier.toFixed(3), "Probability error (Brier)", `vs ${b.base_brier.toFixed(3)} for flat base rates. Lower is better`],
    [`${hits}/${H.length}`, `Live test, ${span}`, "Picks correct on unseen matches this season"],
  ].map(([v, l, s]) => `<div class="kpi"><span class="v num">${v}</span><span style="font-weight:600">${l}</span><span class="s">${s}</span></div>`).join("");
  const name = o => outcome(o) === "H" ? T[o.home].short : outcome(o) === "A" ? T[o.away].short : "Draw";
  document.getElementById("oos").innerHTML = H.map(o => {
    const hit = pick(o) === outcome(o);
    const pAct = { H: o.ph, D: o.pd, A: o.pa }[outcome(o)];
    return `<div class="res"><span class="eyebrow">GW${o.gw}</span><span class="m">${o.home} v ${o.away}</span><span class="sc">${o.hg}–${o.ag}</span>
      <div><div class="minibar"><div class="h" style="width:${o.ph * 100}%"></div><div class="d" style="width:${o.pd * 100}%"></div><div class="a" style="width:${o.pa * 100}%"></div></div>
      <span class="muted" style="font-size:.75rem">${name(o)} given ${pct(pAct)}</span></div>
      <span class="mark ${hit ? "hit" : "miss"}" title="${hit ? "Favourite won" : "Favourite didn't win"}">${hit ? "✓" : "✗"}</span></div>`;
  }).join("");
}

/* method view */
const lam = document.getElementById("lam");
function renderPois() {
  const l = +lam.value; document.getElementById("lam-v").textContent = l.toFixed(1);
  let p = Math.exp(-l), out = [], acc = 0;
  for (let k = 0; k <= 5; k++) { if (k) p *= l / k; out.push([String(k), p]); acc += p; }
  out.push(["6+", Math.max(0, 1 - acc)]);
  const top = Math.max(...out.map(o => o[1]));
  document.getElementById("pbars").innerHTML = out.map(([k, v]) => `<div><span class="num">${pct(v)}</span><i style="height:${(v / top * 72).toFixed(1)}%"></i><span>${k}</span></div>`).join("");
}
lam.oninput = renderPois;

renderPois(); show();

fetch("data/predictions.json", { cache: "no-cache" })
  .then(r => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json(); })
  .then(d => {
    DATA = d; M = d.meta; T = Object.fromEntries(d.teams.map(t => [t.name, t]));
    rows = d.teams.map(t => ({ ...t, net: t.att / t.dfn, xgfg: t.xgp ? t.xgf / t.xgp : 0, xgag: t.xgp ? t.xga / t.xgp : 0 }));
    document.getElementById("pg").textContent = M.prior_games;
    document.getElementById("dc-note").innerHTML = M.rho === 0
      ? "Many models add the <b>Dixon-Coles</b> correction, a small adjustment to 0–0, 1–0, 0–1 and 1–1. In testing on past seasons it didn't improve predictions, so it is currently switched off."
      : `Plain Poisson can misjudge low-scoring results, so the model applies the <b>Dixon-Coles</b> correction (ρ = ${M.rho}), a small adjustment to 0–0, 1–0, 0–1 and 1–1 used in academic and betting models.`;
    document.getElementById("mus").textContent = `${M.mu_h.toFixed(2)} expected goals at home, ${M.mu_a.toFixed(2)} away`;
    renderNotes(); initGW(); initMatch();
    if (!d.fixtures.length) document.getElementById("gw-list").innerHTML = `<p class="loading">No upcoming fixtures. The season is over.</p>`;
    else renderGW();
    renderMatch(); renderTable(); renderScatter(); renderRecord();
  })
  .catch(e => {
    document.getElementById("gw-list").innerHTML = `<p class="loading">Couldn't load predictions (${esc(e.message)}). If you opened index.html directly, serve the folder instead: <code>python -m http.server -d site</code></p>`;
  });
