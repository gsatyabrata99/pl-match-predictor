"""Chip-planning maths in site/chips.js, run in Node against synthetic players."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

CHIPS = Path(__file__).resolve().parent.parent / "site" / "chips.js"
pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")


def players():
    """A 15-man squad (ids 1-15) plus a market. xp_plan has 3 gameweeks."""
    out, pid = [], 0
    def add(pos, team, price, xps, status="a"):
        nonlocal pid
        pid += 1
        out.append({"id": pid, "name": f"P{pid}", "pos": pos, "team": team, "price": price, "status": status,
                    "xp_plan": xps, "xp": xps, "xp_total": sum(xps)})
    for k, x in enumerate([[4, 4, 4], [1, 1, 1]]):
        add("GKP", f"T{k}", 4.5, x)
    for k, x in enumerate([[5, 2, 5], [4, 4, 4], [3, 3, 3], [2, 2, 2], [1, 6, 1]]):
        add("DEF", f"T{k + 2}", 5.0, x)
    for k, x in enumerate([[6, 6, 6], [5, 5, 5], [3, 3, 3], [2, 2, 2], [1, 1, 1]]):
        add("MID", f"T{k + 7}", 6.0, x)
    for k, x in enumerate([[7, 7, 7], [4, 4, 4], [2, 2, 2]]):
        add("FWD", f"T{k + 12}", 8.0, x)
    # market: a cheap excellent midfielder, an expensive striker, an injured star
    add("MID", "T20", 5.5, [9, 9, 9])
    add("FWD", "T21", 14.0, [10, 10, 10])
    add("FWD", "T22", 6.0, [12, 12, 12], status="i")
    for k in range(6):
        add(["GKP", "DEF", "MID", "FWD"][k % 4], f"T{30 + k}", 4.0, [0.5, 0.5, 0.5])
    return out


def run(js: str):
    script = f"const C = require({json.dumps(str(CHIPS))}); const P = {json.dumps(players())};\n" \
             "const SQ = P.slice(0, 15);\n" + js
    out = subprocess.run(["node", "-e", script], capture_output=True, text=True, check=True)
    return json.loads(out.stdout)


def test_lineup_picks_formation_captain_and_bench():
    r = run("const l = C.lineup(SQ, 0); console.log(JSON.stringify({xi: l.xi.map(p => p.id), bench: l.bench.map(p => p.id),"
            " cap: l.cap.id, value: l.value, bv: l.benchValue}));")
    assert len(r["xi"]) == 11 and len(r["bench"]) == 4 and not set(r["xi"]) & set(r["bench"])
    assert r["cap"] == 13                                   # the 7-point forward
    assert r["bv"] == 1 + 2 + 1 + 1                         # GK2, worst DEF(1), MID(1), and the 4th-worst outfielder
    assert r["value"] == pytest.approx(sum(sorted([5, 4, 3, 2, 6, 5, 3, 7, 4, 2], reverse=True)[:10]) + 4 + 7)


def test_bench_value_moves_with_the_gameweek():
    r = run("console.log(JSON.stringify([0, 1].map(i => C.lineup(SQ, i).xi.some(p => p.id === 7))));")
    assert r == [False, True]                               # the 1/6/1 defender starts only in GW index 1


def test_available_chips_respects_windows_and_usage():
    w = [{"name": n, "start": 1, "stop": 19} for n in ("wildcard", "freehit", "bboost", "3xc")] + \
        [{"name": "3xc", "start": 20, "stop": 38}]
    r = run(f"console.log(JSON.stringify(C.availableChips({json.dumps(w)}, [{{name: '3xc', event: 3}}], 11).map(c => c.name)));")
    assert r == ["wildcard", "freehit", "bboost"]


def test_assign_uses_distinct_gameweeks_and_maximises_total():
    r = run("console.log(JSON.stringify(C.assign({bboost: [10, 9, 1], freehit: [8, 2, 1], '3xc': [1, 1, 1]}, ['bboost', 'freehit'])));")
    assert r["plan"] == {"bboost": 1, "freehit": 0} and r["total"] == 17   # not both in week 0


def test_free_hit_xi_is_legal_and_within_budget():
    r = run("const f = C.freeHitXI(P, 0, 100, 3);"
            "console.log(JSON.stringify({n: f.xi.length, cost: f.xi.reduce((s, p) => s + p.price, 0),"
            " pos: f.xi.map(p => p.pos), injured: f.xi.some(p => p.status !== 'a'), teams: f.xi.map(p => p.team)}));")
    assert r["n"] == 11 and not r["injured"]
    assert r["pos"].count("GKP") == 1 and r["pos"].count("DEF") >= 3 and r["pos"].count("MID") >= 2 and r["pos"].count("FWD") >= 1
    assert r["cost"] <= 100 - (4.0 + 3 * 4.0) + 1e-9      # leaves room for the cheapest bench
    assert max(r["teams"].count(t) for t in r["teams"]) <= 3


def test_wildcard_only_makes_legal_improving_changes():
    r = run("const w = C.wildcard(P, SQ, 0.5, [0, 1, 2], 3);"
            "console.log(JSON.stringify({gain: w.gain, n: w.changes.length, bank: w.bank, ins: w.changes.map(c => c.in.id),"
            " pos: w.squad.map(p => p.pos).sort()}));")
    assert r["gain"] > 0 and r["bank"] >= -1e-9
    assert 16 in r["ins"] and 18 not in r["ins"]            # buys the cheap star midfielder, never the injured one
    assert r["pos"] == sorted(["GKP"] * 2 + ["DEF"] * 5 + ["MID"] * 5 + ["FWD"] * 3)


def test_chip_values_have_one_entry_per_gameweek():
    r = run("const v = C.chipValues(P, SQ, 0.5, [0, 1, 2], 3); console.log(JSON.stringify(v));")
    assert all(len(v) == 3 for v in r.values())
    assert r["3xc"] == [7, 7, 7] and all(x >= 0 for x in r["freehit"])
