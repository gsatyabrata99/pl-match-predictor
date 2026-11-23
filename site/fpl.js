/* FPL Planner: renders site/data/fpl.json (built by predictor/fpl.py). */
let D, P, TEAMS, BY_ID;
const POS = ["GKP", "DEF", "MID", "FWD"];
const esc = s => String(s).replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const pct = x => `${Math.round(100 * x)}%`;
const f1 = x => x.toFixed(1);
const store = {
  get(k, d) { try { const v = localStorage.getItem(k); return v === null ? d : JSON.parse(v); } catch { return d; } },
  set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch { /* storage unavailable */ } },
};

/* ---------------------------------------------------------------- routing */
const VIEWS = ["captains", "transfers", "fixtures", "myteam", "chips", "method"];
function show() {
  const v = VIEWS.includes(location.hash.slice(1)) ? location.hash.slice(1) : "captains";
  document.querySelectorAll("[data-v]").forEach(s => s.hidden = s.dataset.v !== v);
  document.querySelectorAll("nav button").forEach(b => b.setAttribute("aria-selected", b.dataset.view === v));
}
document.querySelectorAll("nav button").forEach(b => b.onclick = () => { location.hash = b.dataset.view; });
addEventListener("hashchange", show);

function seg(el, options, value, onChange) {
  el.innerHTML = options.map(([v, l]) => `<button type="button" data-v="${v}" aria-pressed="${v === value}">${l}</button>`).join("");
  el.onclick = e => {
    const b = e.target.closest("button"); if (!b) return;
    el.querySelectorAll("button").forEach(x => x.setAttribute("aria-pressed", x === b));
    onChange(b.dataset.v);
  };
}

/* ---------------------------------------------------------------- helpers */
const short = name => TEAMS[name]?.short || name;
function oppText(team, gwIndex) {
  const cells = TEAMS[team]?.fixtures[gwIndex] || [];
  if (!cells.length) return `<span class="muted">blank</span>`;
  return cells.map(c => `${short(c.opp)}${c.home ? " (H)" : " (A)"}`).join(", ");
}
function flag(p) {
  if (p.status === "a") return "";
  const label = p.chance === null || p.chance === undefined ? { i: "Injured", s: "Suspended", u: "Unavailable", n: "Unavailable", d: "Doubtful" }[p.status] || "Flagged" : `${p.chance}% to play`;
  return `<span class="pill warn" title="${esc(p.news)}">${esc(label)}</span>`;
}
function rotation(p) { return p.p60 < 0.6 && p.p_play > 0 ? `<span class="pill" title="Played 60+ minutes in ${Math.round(p.p60 * 5)} of the last 5 team gameweeks">Rotation risk</span>` : ""; }

/* ---------------------------------------------------------------- captains */
let capPos = "ALL";
function renderCaptains() {
  const gw = D.meta.gws[0];
  document.getElementById("cap-title").textContent = `Captain picks · GW${gw}`;
  const list = P.filter(p => p.next && (capPos === "ALL" || p.pos === capPos)).sort((a, b) => b.xp[0] - a.xp[0]).slice(0, 12);
  const max = Math.max(...list.map(p => p.xp[0]), 1);
  document.getElementById("cap-list").innerHTML = list.map((p, i) => {
    const n = p.next;
    const parts = [["app", n.appearance], ["att", n.goals + n.assists], ["def", Math.max(0, n.clean_sheet + n.saves + n.defcon + n.conceded)], ["bonus", n.bonus]];
    const bar = parts.map(([k, v]) => `<i class="c-${k}" style="width:${(Math.max(v, 0) / max * 100).toFixed(1)}%"></i>`).join("");
    return `<div class="cap">
      <span class="rank num">${i + 1}</span>
      <div class="who"><b>${esc(p.name)}</b> <span class="muted small">${short(p.team)} · ${p.pos} · £${p.price.toFixed(1)}</span>
        <div class="small muted">v ${oppText(p.team, 0)} ${flag(p)} ${rotation(p)}</div></div>
      <div class="stackbar" aria-hidden="true">${bar}</div>
      <div class="capnums cn-xp"><span class="big num">${f1(p.xp[0])}</span><span class="small muted">xP</span></div>
      <div class="capnums cn-goal"><span class="num">${pct(n.p_goal)}</span><span class="small muted">to score</span></div>
      <div class="capnums cn-ret"><span class="num">${pct(n.p_return)}</span><span class="small muted">goal or assist</span></div>
    </div>`;
  }).join("") || `<p class="loading">No players with a fixture in GW${gw}.</p>`;
}

/* ---------------------------------------------------------------- transfers */
let trPos = "ALL", trSort = "xp_total", trDir = -1;
function renderTransfers() {
  const maxPrice = +document.getElementById("tr-price").value;
  const fit = document.getElementById("tr-fit").checked;
  const rows = P.filter(p => (trPos === "ALL" || p.pos === trPos) && p.price <= maxPrice && (!fit || p.status === "a") && p.minutes > 0)
    .map(p => ({ ...p, xp1: p.xp[0], value: p.xp_total / p.price }))
    .sort((a, b) => (trSort === "name" ? a.name.localeCompare(b.name) : a[trSort] - b[trSort]) * trDir).slice(0, 60);
  const cols = [["name", "Player"], [null, "Pos"], ["price", "£"], ["owned", "Owned"], ["xp1", `GW${D.meta.gws[0]}`], ["xp_total", `Next ${D.meta.gws.length}`], ["value", "Value"], [null, "Fixtures"]];
  document.getElementById("tr-table").innerHTML =
    `<thead><tr>${cols.map(([k, l]) => `<th ${k ? `data-k="${k}" class="sortable"` : ""}>${l}${k === trSort ? (trDir < 0 ? " ↓" : " ↑") : ""}</th>`).join("")}</tr></thead><tbody>` +
    rows.map(p => `<tr><td class="name">${esc(p.name)} <small>${short(p.team)}</small> ${flag(p)}</td><td>${p.pos}</td>
      <td>${p.price.toFixed(1)}</td><td>${p.owned.toFixed(1)}%</td><td>${f1(p.xp1)}</td><td><b>${f1(p.xp_total)}</b></td><td>${p.value.toFixed(2)}</td>
      <td class="fxmini">${D.meta.gws.map((g, i) => fxChip(p.team, i)).join("")}</td></tr>`).join("") + "</tbody>";
  document.querySelectorAll("#tr-table th[data-k]").forEach(th => th.onclick = () => {
    const k = th.dataset.k; if (k === trSort) trDir *= -1; else { trSort = k; trDir = k === "name" || k === "price" ? 1 : -1; }
    renderTransfers();
  });
}
function fxChip(team, i) {
  const cells = TEAMS[team]?.fixtures[i] || [];
  if (!cells.length) return `<span class="fxc blank" title="Blank gameweek">–</span>`;
  return cells.map(c => `<span class="fxc" style="${heat(c.xg_for, 0.8, 2.4)}" title="GW${D.meta.gws[i]} v ${esc(c.opp)}${c.home ? " (H)" : " (A)"}: ${c.xg_for.toFixed(2)} xG for, ${pct(c.cs)} clean sheet">${short(c.opp)}${c.home ? "" : "ₐ"}</span>`).join("");
}
function heat(v, lo, hi) {
  const t = Math.max(0, Math.min(1, (v - lo) / (hi - lo)));
  const mix = Math.round(10 + 75 * t);
  return `background:color-mix(in oklab, var(--heat) ${mix}%, var(--sunk));color:${mix > 50 ? "#fff" : "var(--fg)"}`;
}

/* ---------------------------------------------------------------- fixtures */
let fxMode = "attack";
function renderFixtures() {
  const att = fxMode === "attack";
  document.getElementById("fx-note").textContent = att
    ? "Each team's expected goals per fixture, from the match model. Darker means an easier fixture for attackers."
    : "Each team's clean-sheet chance per fixture, from the match model. Darker means an easier fixture for defenders and keepers.";
  const metric = c => att ? c.xg_for : c.cs;
  const rows = D.teams.map(t => ({ t, total: t.fixtures.reduce((s, cells) => s + cells.reduce((x, c) => x + metric(c), 0), 0) }))
    .sort((a, b) => b.total - a.total);
  document.getElementById("fx-table").innerHTML =
    `<thead><tr><th>Team</th>${D.meta.gws.map(g => `<th>GW${g}</th>`).join("")}<th>${att ? "Total xG" : "Total CS"}</th></tr></thead><tbody>` +
    rows.map(({ t, total }) => `<tr><td class="name">${esc(t.name)}</td>${t.fixtures.map(cells => `<td>${cells.length ? cells.map(c =>
      `<div class="fxcell" style="${att ? heat(c.xg_for, 0.8, 2.4) : heat(c.cs, 0.1, 0.5)}"><b>${short(c.opp)}</b> ${c.home ? "H" : "A"}<span>${att ? c.xg_for.toFixed(2) : pct(c.cs)}</span></div>`).join("")
      : `<div class="fxcell blank">–</div>`}</td>`).join("")}<td class="num"><b>${att ? total.toFixed(1) : total.toFixed(2)}</b></td></tr>`).join("") + "</tbody>";
}

/* ---------------------------------------------------------------- my team */
let squad = [], ENTRIES = {};
function saveSquad() { store.set("fpl-squad", squad); store.set("fpl-bank", +document.getElementById("mt-bank").value || 0); }
function squadProblems(ids) {
  const sp = ids.map(id => BY_ID[id]).filter(Boolean), probs = [];
  for (const pos of POS) {
    const n = sp.filter(p => p.pos === pos).length, need = D.meta.squad[pos];
    if (n !== need) probs.push(`${n}/${need} ${pos}`);
  }
  const clubs = {};
  sp.forEach(p => clubs[p.team] = (clubs[p.team] || 0) + 1);
  Object.entries(clubs).filter(([, n]) => n > D.meta.team_limit).forEach(([t, n]) => probs.push(`${n} from ${t} (max ${D.meta.team_limit})`));
  return probs;
}
function canAdd(p) {
  if (squad.includes(p.id)) return "In squad";
  const sp = squad.map(id => BY_ID[id]).filter(Boolean);
  if (sp.filter(x => x.pos === p.pos).length >= D.meta.squad[p.pos]) return `${p.pos} full`;
  if (sp.filter(x => x.team === p.team).length >= D.meta.team_limit) return `${D.meta.team_limit} from ${short(p.team)}`;
  return "";
}
function renderSquad() {
  const sp = squad.map(id => BY_ID[id]).filter(Boolean);
  document.getElementById("mt-count").textContent = `${sp.length}/15 · £${sp.reduce((s, p) => s + p.price, 0).toFixed(1)}m`;
  document.getElementById("mt-squad").innerHTML = POS.map(pos => `<div class="sqrow"><span class="eyebrow">${pos}</span>${
    sp.filter(p => p.pos === pos).sort((a, b) => b.xp_total - a.xp_total).map(p => `<button type="button" class="slot" data-id="${p.id}" title="Remove ${esc(p.name)}">
      <b>${esc(p.name)}</b><span class="small muted">${short(p.team)} · £${p.price.toFixed(1)}</span><span class="small num">${f1(p.xp[0])} · ${f1(p.xp_total)}</span>${flag(p)}<span class="x" aria-hidden="true">×</span></button>`).join("")
  }</div>`).join("");
  document.querySelectorAll("#mt-squad .slot").forEach(b => b.onclick = () => { squad = squad.filter(id => id !== +b.dataset.id); saveSquad(); renderMyTeam(); });
  const probs = squadProblems(squad);
  document.getElementById("mt-validity").innerHTML = sp.length === 0
    ? "Search for players on the right, or load a team ID, to build your 15-man squad. Your squad is saved in this browser."
    : probs.length ? `Not a full squad yet: ${probs.map(esc).join(" · ")}.` : `Each player shows GW${D.meta.gws[0]} xP · next ${D.meta.gws.length} GWs. Click a player to remove him.`;
}
function renderResults() {
  const q = document.getElementById("mt-search").value.trim().toLowerCase();
  const list = (q ? P.filter(p => p.name.toLowerCase().includes(q) || p.full.toLowerCase().includes(q) || p.team.toLowerCase().includes(q) || short(p.team).toLowerCase() === q)
    : P.filter(p => p.minutes > 0)).sort((a, b) => b.xp_total - a.xp_total).slice(0, 12);
  document.getElementById("mt-results").innerHTML = list.map(p => {
    const why = canAdd(p);
    return `<div class="res-row"><div><b>${esc(p.name)}</b> <span class="small muted">${short(p.team)} · ${p.pos} · £${p.price.toFixed(1)}</span> ${flag(p)}</div>
      <span class="small num">${f1(p.xp_total)}</span>
      <button type="button" class="btn" data-id="${p.id}" ${why ? "disabled" : ""}>${why || "Add"}</button></div>`;
  }).join("") || `<p class="muted small">No players match.</p>`;
  document.querySelectorAll("#mt-results button[data-id]").forEach(b => b.onclick = () => { squad.push(+b.dataset.id); saveSquad(); renderMyTeam(); });
}
function bestXI(sp) {
  const by = pos => sp.filter(p => p.pos === pos).sort((a, b) => b.xp[0] - a.xp[0]);
  const xi = [by("GKP")[0], ...by("DEF").slice(0, 3), ...by("MID").slice(0, 2), by("FWD")[0]].filter(Boolean);
  const rest = sp.filter(p => p.pos !== "GKP" && !xi.includes(p)).sort((a, b) => b.xp[0] - a.xp[0]);
  xi.push(...rest.slice(0, 11 - xi.length));
  const bench = [...by("GKP").slice(1), ...rest.slice(11 - 7)];
  return { xi, bench };
}
function bestTransfers(sp, bank) {
  const out = [];
  const clubs = {};
  sp.forEach(p => clubs[p.team] = (clubs[p.team] || 0) + 1);
  for (const o of sp) {
    const budget = o.price + bank + 1e-9;
    let best = null;
    for (const p of P) {
      if (p.pos !== o.pos || squad.includes(p.id) || p.price > budget || p.status !== "a") continue;
      const count = (clubs[p.team] || 0) - (o.team === p.team ? 1 : 0);
      if (count >= D.meta.team_limit) continue;
      if (!best || p.xp_total > best.xp_total) best = p;
    }
    if (best && best.xp_total > o.xp_total) out.push({ out: o, in: best, gain: best.xp_total - o.xp_total });
  }
  const seen = new Set();                      // each incoming player suggested once
  return out.sort((a, b) => b.gain - a.gain).filter(m => !seen.has(m.in.id) && seen.add(m.in.id)).slice(0, 5);
}
function renderAdvice() {
  const el = document.getElementById("mt-advice");
  if (squad.length !== 15 || squadProblems(squad).length) { el.innerHTML = ""; return; }
  const sp = squad.map(id => BY_ID[id]);
  const { xi, bench } = bestXI(sp);
  const ranked = [...xi].sort((a, b) => b.xp[0] - a.xp[0]);
  const cap = ranked[0], vice = ranked[1];
  const total = xi.reduce((s, p) => s + p.xp[0], 0) + cap.xp[0];
  const shape = ["DEF", "MID", "FWD"].map(pos => xi.filter(p => p.pos === pos).length).join("-");
  const bank = +document.getElementById("mt-bank").value || 0;
  const moves = bestTransfers(sp, bank);
  el.innerHTML = `<div class="panel"><h3>Best XI for GW${D.meta.gws[0]} <span class="muted small">${shape} · ${f1(total)} xP with captain</span></h3>
      <div class="xi">${POS.map(pos => `<div class="xirow">${xi.filter(p => p.pos === pos).map(p =>
        `<div class="xip"><b>${esc(p.name)}${p === cap ? ' <span class="pill captain">C</span>' : p === vice ? ' <span class="pill">V</span>' : ""}</b><span class="small muted">v ${oppText(p.team, 0)}</span><span class="num small">${f1(p.xp[0])}</span></div>`).join("")}</div>`).join("")}</div>
      <p class="small muted">Bench, in order: ${bench.map(p => `${esc(p.name)} (${f1(p.xp[0])})`).join(", ")}.</p></div>
    <div class="panel"><h3>Best single transfers <span class="muted small">gain over the next ${D.meta.gws.length} GWs</span></h3>
      ${moves.length ? moves.map(m => `<div class="move"><span><span class="out">${esc(m.out.name)}</span> → <b>${esc(m.in.name)}</b> <span class="small muted">${short(m.in.team)} · £${m.in.price.toFixed(1)}</span></span><span class="num gain">+${f1(m.gain)}</span></div>`).join("")
        : `<p class="muted small">No single transfer improves your next-${D.meta.gws.length} projection within your bank.</p>`}
      <p class="small muted">Uses current prices. FPL sells at your purchase price plus half of any rise, so adjust the bank if needed. An extra transfer costs 4 points, so take one only if the gain beats that.</p></div>`;
}
function renderMyTeam() { renderSquad(); renderResults(); renderAdvice(); renderChips(); }

/* ---------------------------------------------------------------- chips */
const CHIP_ORDER = ["wildcard", "freehit", "bboost", "3xc"];
let wcResult = null;
function chipWindow() { return D.meta.chips.find(w => w.start <= D.meta.next_gw && D.meta.next_gw <= w.stop); }
function loadedEntry() { const id = store.get("fpl-entry", ""); return ENTRIES[id] ? ENTRIES[id] : null; }
function heldChips() {
  const win = D.meta.chips.filter(w => w.start <= D.meta.next_gw && D.meta.next_gw <= w.stop);
  const saved = store.get("fpl-chips", null);
  if (saved && saved.window === chipWindow()?.stop) return new Set(saved.held);
  const e = loadedEntry();
  return new Set(Chips.availableChips(win, e ? e.chips_used : [], D.meta.next_gw).map(w => w.name));
}
function renderChips() {
  const body = document.getElementById("ch-body"), win = chipWindow();
  if (!win) { body.innerHTML = `<p class="muted">No chip window is open.</p>`; return; }
  const left = win.stop - D.meta.next_gw + 1;
  document.getElementById("ch-window").innerHTML = `Use by <b>GW${win.stop}</b> · ${left} gameweek${left === 1 ? "" : "s"} left`;
  const held = heldChips();
  const names = CHIP_ORDER.filter(n => D.meta.chips.some(w => w.name === n && w.start <= D.meta.next_gw && D.meta.next_gw <= w.stop));
  document.getElementById("ch-have").innerHTML = `<span class="small muted">Chips you still have:</span>` + names.map(n =>
    `<label class="inline"><input type="checkbox" data-chip="${n}" ${held.has(n) ? "checked" : ""}> ${Chips.NAMES[n]}</label>`).join("");
  document.querySelectorAll("#ch-have input").forEach(cb => cb.onchange = () => {
    const h = [...document.querySelectorAll("#ch-have input:checked")].map(x => x.dataset.chip);
    store.set("fpl-chips", { window: win.stop, held: h }); wcResult = null; renderChips();
  });
  const e = loadedEntry();
  document.getElementById("ch-intro").textContent = `Chips from this half expire after GW${win.stop}, and only one chip can be played per gameweek. ` +
    (e ? `Chips ticked below come from ${e.name}'s FPL history; untick any you've used since.` : `Tick the chips you still have.`);

  const sp = squad.map(id => BY_ID[id]).filter(Boolean);
  if (sp.length !== 15 || squadProblems(squad).length) {
    body.innerHTML = `<div class="panel"><p class="muted">Load or build your 15-man squad on the <a href="#myteam">My team</a> tab first. The planner scores each chip against your own players.</p></div>`;
    return;
  }
  const gws = D.meta.plan_gws, idx = gws.map((g, i) => i).filter(i => gws[i] >= win.start && gws[i] <= win.stop);
  const bank = +document.getElementById("mt-bank").value || 0;
  const vals = Chips.chipValues(P, sp, bank, idx, D.meta.team_limit);
  const timed = ["bboost", "freehit", "3xc"].filter(n => held.has(n));
  const plan = Chips.assign(vals, timed).plan;               // chip -> position in idx
  const cell = (n, k) => {
    if (!held.has(n)) return `<td class="muted">–</td>`;
    const v = vals[n][k], pick = plan[n] === k;
    return `<td class="${pick ? "pick" : ""}">${pick ? "★ " : ""}${f1(v)}</td>`;
  };
  const cards = timed.map(n => {
    const k = plan[n], gw = gws[idx[k]];
    const why = { bboost: `your bench is projected ${f1(vals.bboost[k])} points`,
                  freehit: `a one-week squad would beat your XI by about ${f1(vals.freehit[k])} points`,
                  "3xc": `your captain is projected ${f1(vals["3xc"][k])}, scored a third time` }[n];
    return `<div class="kpi"><span class="eyebrow">${Chips.NAMES[n]}</span><span class="v num">GW${gw}</span><span class="s">${why}</span></div>`;
  });
  if (held.has("wildcard")) {
    const bbGw = plan.bboost !== undefined ? gws[idx[plan.bboost]] : null;
    cards.push(`<div class="kpi"><span class="eyebrow">Wildcard</span><span class="v num">${bbGw && bbGw > D.meta.next_gw ? `By GW${bbGw - 1}` : `By GW${win.stop}`}</span>
      <span class="s">${bbGw && bbGw > D.meta.next_gw ? "Before your Bench Boost, so the new 15 is the one boosted." : "Any free week before it expires."} See what it would change below.</span></div>`);
  }
  body.innerHTML = `
    <div class="kpis">${cards.join("") || `<div class="kpi"><span class="s">No chips left in this window.</span></div>`}</div>
    <div class="panel tablewrap"><h3>Chip value by gameweek <span class="muted small">projected points the chip adds, ★ = recommended</span></h3>
      <table class="ptable chiptable"><thead><tr><th>Gameweek</th><th>Bench Boost</th><th>Free Hit</th><th>Triple Captain</th><th>Your captain</th></tr></thead><tbody>
      ${idx.map((i, k) => { const l = Chips.lineup(sp, i); return `<tr><td class="name">GW${gws[i]}</td>${cell("bboost", k)}${cell("freehit", k)}${cell("3xc", k)}<td>${esc(l.cap.name)} <span class="muted small">${f1(Chips.xpAt(l.cap, i))}</span></td></tr>`; }).join("")}
      </tbody></table></div>
    ${held.has("wildcard") ? `<div class="panel" id="ch-wc"><h3>Wildcard preview</h3>
      <p class="muted small">Rebuilds your squad for the next ${Math.min(5, idx.length)} gameweeks with your current budget. Takes a few seconds.</p>
      <button class="btn" type="button" id="ch-wc-run">Plan a wildcard</button><div id="ch-wc-out"></div></div>` : ""}
    <p class="muted small">Values come from the same expected points as the rest of the planner, so they assume your squad as it is now and get less reliable further ahead. They update twice a day as fixtures, injuries and your squad change, so check again each week before playing a chip. There are no double or blank gameweeks scheduled this half; if FPL announces one, the planner picks it up automatically.</p>`;
  const run = document.getElementById("ch-wc-run");
  if (run) run.onclick = () => {
    run.disabled = true; run.textContent = "Working…";
    setTimeout(() => {
      const wIdx = idx.slice(0, 5);
      wcResult = Chips.wildcard(P, sp, bank, wIdx, D.meta.team_limit);
      showWildcard(wcResult, idx, plan, gws); run.textContent = "Recalculate"; run.disabled = false;
    }, 30);
  };
  if (wcResult) showWildcard(wcResult, idx, plan, gws);
}
function showWildcard(w, idx, plan, gws) {
  const out = document.getElementById("ch-wc-out"); if (!out) return;
  if (!w.changes.length) { out.innerHTML = `<p class="small muted">A wildcard wouldn't improve your projections meaningfully right now. Hold it.</p>`; return; }
  const bbK = plan.bboost, bbNote = bbK !== undefined
    ? ` Your Bench Boost in GW${gws[idx[bbK]]} would be worth ${f1(Chips.lineup(w.squad, idx[bbK]).benchValue)} with this squad, against ${f1(Chips.lineup(squad.map(id => BY_ID[id]), idx[bbK]).benchValue)} now.` : "";
  out.innerHTML = `<p><b>+${f1(w.gain)}</b> projected points over the next ${Math.min(5, idx.length)} gameweeks from ${w.changes.length} changes, leaving £${w.bank.toFixed(1)}m in the bank.${bbNote}</p>
    ${w.changes.map(c => `<div class="move"><span><span class="out">${esc(c.out.name)}</span> → <b>${esc(c.in.name)}</b> <span class="small muted">${short(c.in.team)} · ${c.in.pos} · £${c.in.price.toFixed(1)}</span></span><span class="num gain">+${f1(c.gain)}</span></div>`).join("")}
    <p class="small muted">A wildcard is worth playing when the gain is well beyond what your free transfers could achieve; compare with the Best single transfers on My team.</p>`;
}

/* ---------------------------------------------------------------- boot */
function renderNotes() {
  const m = D.meta, dl = new Date(m.deadline);
  document.getElementById("notes").innerHTML = [
    `Next: <b>GW${m.next_gw}</b>`, `Deadline <b>${dl.toLocaleString(undefined, { weekday: "short", day: "numeric", month: "short", hour: "numeric", minute: "2-digit" })}</b>`,
    `Data through <b>GW${m.data_through_gw}</b>`, `Updated <b>${new Date(m.generated).toLocaleString(undefined, { day: "numeric", month: "short", hour: "numeric", minute: "2-digit" })}</b>`,
  ].map(c => `<span class="chip">${c}</span>`).join("");
  document.getElementById("m-defcon").textContent = `${m.defcon_threshold.DEF} for defenders, ${m.defcon_threshold.MID} for midfielders and forwards`;
}
show();
fetch("data/fpl.json", { cache: "no-cache" })
  .then(r => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json(); })
  .then(d => {
    D = d; P = d.players; BY_ID = Object.fromEntries(P.map(p => [p.id, p])); TEAMS = Object.fromEntries(d.teams.map(t => [t.name, t]));
    renderNotes();
    const posOpts = [["ALL", "All"], ...POS.map(p => [p, p])];
    seg(document.getElementById("cap-pos"), posOpts, capPos, v => { capPos = v; renderCaptains(); });
    seg(document.getElementById("tr-pos"), posOpts, trPos, v => { trPos = v; renderTransfers(); });
    seg(document.getElementById("fx-mode"), [["attack", "Attack"], ["defence", "Clean sheets"]], fxMode, v => { fxMode = v; renderFixtures(); });
    const prices = [...new Set(P.map(p => Math.ceil(p.price)))].sort((a, b) => a - b);
    const priceSel = document.getElementById("tr-price");
    priceSel.innerHTML = prices.map(x => `<option value="${x}">£${x}.0m</option>`).join("");
    priceSel.value = prices[prices.length - 1];
    priceSel.onchange = renderTransfers;
    document.getElementById("tr-fit").onchange = renderTransfers;
    squad = store.get("fpl-squad", []).filter(id => BY_ID[id]);
    document.getElementById("mt-bank").value = (+store.get("fpl-bank", 0)).toFixed(1);
    document.getElementById("mt-bank").oninput = () => { saveSquad(); renderAdvice(); };
    document.getElementById("mt-search").oninput = renderResults;
    document.getElementById("mt-clear").onclick = () => { squad = []; saveSquad(); renderMyTeam(); };
    renderCaptains(); renderTransfers(); renderFixtures(); renderMyTeam();
    return fetch("data/fpl-teams.json", { cache: "no-cache" }).then(r => r.ok ? r.json() : null).catch(() => null);
  })
  .then(t => {
    ENTRIES = (t && t.entries) || {};
    const sel = document.getElementById("mt-entry");
    const ids = Object.keys(ENTRIES);
    sel.innerHTML = `<option value="">${ids.length ? "Choose…" : "None configured"}</option>` + ids.map(id => `<option value="${esc(id)}">${esc(ENTRIES[id].name || id)}</option>`).join("");
    sel.disabled = !ids.length;
    const loadEntry = (id, note) => {
      const e = ENTRIES[id]; if (!e) return;
      squad = e.picks.filter(x => BY_ID[x]);
      document.getElementById("mt-bank").value = (e.bank / 10).toFixed(1);
      store.set("fpl-entry", id); store.set("fpl-entry-gw", e.gw); store.set("fpl-chips", null);
      saveSquad(); renderMyTeam();
      document.getElementById("mt-loaded").textContent = note || `Loaded ${e.name}'s squad from the GW${e.gw} deadline.`;
    };
    sel.onchange = () => loadEntry(sel.value);
    // Remember the chosen team and refresh it automatically once FPL publishes a newer squad.
    const remembered = store.get("fpl-entry", "");
    if (ENTRIES[remembered]) {
      sel.value = remembered;
      if (ENTRIES[remembered].gw > store.get("fpl-entry-gw", 0))
        loadEntry(remembered, `Updated to ${ENTRIES[remembered].name}'s squad from the GW${ENTRIES[remembered].gw} deadline.`);
    }
    renderChips();
  })
  .catch(e => {
    document.getElementById("cap-list").innerHTML = `<p class="loading">Couldn't load projections (${esc(e.message)}). If you opened this file directly, serve the folder instead: <code>python -m http.server -d site</code></p>`;
  });
