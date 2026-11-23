/* Chip planning maths for the FPL Planner. Pure functions (no page code) so they can be
   tested in Node. Players are objects from fpl.json; `i` indexes meta.plan_gws. */
(function (root) {
  const OUTFIELD = ["DEF", "MID", "FWD"];
  const MIN = { DEF: 3, MID: 2, FWD: 1 }, MAX = { DEF: 5, MID: 5, FWD: 3 };
  const NAMES = { bboost: "Bench Boost", freehit: "Free Hit", wildcard: "Wildcard", "3xc": "Triple Captain" };

  const xpAt = (p, i) => (p.xp_plan || p.xp)[i] || 0;

  /** Best XI for gameweek i from a 15-man squad: 1 GK, formation minimums, best of the rest. */
  function lineup(squad, i) {
    const by = pos => squad.filter(p => p.pos === pos).sort((a, b) => xpAt(b, i) - xpAt(a, i));
    const xi = [by("GKP")[0], ...by("DEF").slice(0, 3), ...by("MID").slice(0, 2), by("FWD")[0]].filter(Boolean);
    const rest = squad.filter(p => p.pos !== "GKP" && !xi.includes(p)).sort((a, b) => xpAt(b, i) - xpAt(a, i));
    xi.push(...rest.slice(0, Math.max(0, 11 - xi.length)));
    const bench = squad.filter(p => !xi.includes(p));
    const cap = xi.reduce((a, b) => (xpAt(b, i) > xpAt(a, i) ? b : a), xi[0]);
    const sum = xi.reduce((s, p) => s + xpAt(p, i), 0);
    return { xi, bench, cap, value: sum + (cap ? xpAt(cap, i) : 0), benchValue: bench.reduce((s, p) => s + xpAt(p, i), 0) };
  }

  /** Chips still available in the window that contains `gw`. */
  function availableChips(windows, used, gw) {
    return windows.filter(w => w.start <= gw && gw <= w.stop)
      .filter(w => !(used || []).some(u => u.name === w.name && u.event >= w.start && u.event <= w.stop));
  }

  /** Best XI one gameweek can field with a whole budget (Free Hit): greedy by projected points
     with a budget check, then upgrade passes. Bench is assumed to be the cheapest legal fodder. */
  function freeHitXI(players, i, budget, limit) {
    const pool = players.filter(p => p.status === "a" && xpAt(p, i) > 0);
    const cheapest = pos => Math.min(...players.filter(p => p.pos === pos).map(p => p.price));
    const reserve = cheapest("GKP") + 3 * Math.min(...OUTFIELD.map(cheapest));
    let money = budget - reserve;
    const floor = Math.min(...OUTFIELD.map(cheapest)), gkFloor = cheapest("GKP");
    const xi = [], clubs = {}, count = { GKP: 0, DEF: 0, MID: 0, FWD: 0 };
    const fits = p => {
      if ((clubs[p.team] || 0) >= limit) return false;
      if (p.pos === "GKP" ? count.GKP >= 1 : count[p.pos] >= MAX[p.pos]) return false;
      const after = { ...count, [p.pos]: count[p.pos] + 1 };
      const slots = 11 - xi.length - 1;
      const needOut = OUTFIELD.reduce((s, q) => s + Math.max(0, MIN[q] - after[q]), 0) + (after.GKP ? 0 : 1);
      if (needOut > slots) return false;
      const minRest = (after.GKP ? 0 : gkFloor) + Math.max(0, slots - (after.GKP ? 0 : 1)) * floor;
      return p.price + minRest <= money + 1e-9;
    };
    for (const p of [...pool].sort((a, b) => xpAt(b, i) - xpAt(a, i))) {
      if (xi.length === 11) break;
      if (fits(p)) { xi.push(p); money -= p.price; clubs[p.team] = (clubs[p.team] || 0) + 1; count[p.pos]++; }
    }
    for (let improved = true, guard = 0; improved && guard < 50; guard++) {   // upgrade passes
      improved = false;
      for (const o of [...xi]) {
        const best = pool.filter(p => p.pos === o.pos && !xi.includes(p) && p.price <= o.price + money + 1e-9
          && (clubs[p.team] || 0) - (p.team === o.team ? 1 : 0) < limit && xpAt(p, i) > xpAt(o, i))
          .sort((a, b) => xpAt(b, i) - xpAt(a, i))[0];
        if (best) {
          xi[xi.indexOf(o)] = best; money += o.price - best.price;
          clubs[o.team]--; clubs[best.team] = (clubs[best.team] || 0) + 1; improved = true;
        }
      }
    }
    const cap = xi.reduce((a, b) => (xpAt(b, i) > xpAt(a, i) ? b : a), xi[0]);
    return { xi, value: xi.reduce((s, p) => s + xpAt(p, i), 0) + (cap ? xpAt(cap, i) : 0) };
  }

  /** Value of each chip in each gameweek index, for one squad. */
  function chipValues(players, squad, bank, idx, limit) {
    const budget = squad.reduce((s, p) => s + p.price, 0) + bank;
    const out = { bboost: [], "3xc": [], freehit: [] };
    for (const i of idx) {
      const l = lineup(squad, i);
      out.bboost.push(l.benchValue);
      out["3xc"].push(l.cap ? xpAt(l.cap, i) : 0);
      out.freehit.push(Math.max(0, freeHitXI(players, i, budget, limit).value - l.value));
    }
    return out;
  }

  /** One chip per gameweek: the assignment of chips to distinct gameweeks with the largest total. */
  function assign(values, chips) {
    let best = { total: -Infinity, plan: {} };
    const n = chips.length ? values[chips[0]].length : 0;
    (function go(k, used, total, plan) {
      if (k === chips.length) { if (total > best.total) best = { total, plan: { ...plan } }; return; }
      const c = chips[k];
      for (let g = 0; g < n; g++) {
        if (used.has(g)) continue;
        used.add(g); plan[c] = g;
        go(k + 1, used, total + values[c][g], plan);
        used.delete(g); delete plan[c];
      }
    })(0, new Set(), 0, {});
    return chips.length ? best : { total: 0, plan: {} };
  }

  /** Wildcard: repeatedly make the transfer that most improves projected XI points over the
     given gameweeks, with no point cost, until nothing improves (at most 15 changes). */
  function wildcard(players, squad, bank, idx, limit) {
    const score = sq => idx.reduce((s, i) => s + lineup(sq, i).value, 0);
    let cur = [...squad], money = bank, base = score(cur), now = base;
    const changes = [];
    for (let step = 0; step < 15; step++) {
      const clubs = {};
      cur.forEach(p => clubs[p.team] = (clubs[p.team] || 0) + 1);
      let best = null;
      for (const o of cur) {
        for (const p of players) {
          if (p.pos !== o.pos || p.status !== "a" || cur.includes(p) || p.price > o.price + money + 1e-9) continue;
          if ((clubs[p.team] || 0) - (p.team === o.team ? 1 : 0) >= limit) continue;
          if ((p.xp_total || 0) <= (o.xp_total || 0) - 1) continue;            // prune obvious downgrades
          const sq = cur.map(x => (x === o ? p : x));
          const s = score(sq);
          if (!best || s > best.s) best = { s, o, p, sq };
        }
      }
      if (!best || best.s <= now + 0.5) break;                                // ignore negligible gains
      changes.push({ out: best.o, in: best.p, gain: best.s - now });
      money += best.o.price - best.p.price; cur = best.sq; now = best.s;
    }
    return { squad: cur, changes, gain: now - base, bank: money };
  }

  const api = { xpAt, lineup, availableChips, freeHitXI, chipValues, assign, wildcard, NAMES };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.Chips = api;
})(typeof window !== "undefined" ? window : globalThis);
