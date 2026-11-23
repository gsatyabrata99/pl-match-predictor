"""Lineup-ceiling study (team-news project, phase 2). Research only.

    python -m predictor.lineup

Implements experiments/2026-11-22-LINEUP-PREREGISTRATION.md exactly: how much better
v0.1 would have been had it known each team's actual starting XI. The production
predictor is not used or changed beyond reading its parameters.
"""
from __future__ import annotations

import csv
import io
import json
import math
import random
from collections import defaultdict
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone

from . import benchmark, evaluate, model, sources
from .evaluate import Row

TEST_SEASONS = ("2023-24", "2024-25", "2025-26")
MARKET_SEASONS = ("2024-25", "2025-26")
PRIOR_MINUTES = 450
WINDOW = 5                    # previous matches defining the usual XI / back line
CAP = (0.6, 1.4)
POSMAP = {"GK": "GKP", "GKP": "GKP", "DEF": "DEF", "MID": "MID", "FWD": "FWD"}
PREREG = "experiments/2026-11-22-LINEUP-PREREGISTRATION.md"


@dataclass
class TeamMatch:
    fixture: str
    kickoff: str
    minutes: dict[int, int] = field(default_factory=dict)    # player -> minutes
    starters: set[int] = field(default_factory=set)


@dataclass
class SeasonData:
    fixtures: dict[str, tuple[int, str, str, str]]           # id -> (gw, home, away, kickoff)
    team_matches: dict[str, list[TeamMatch]]                 # team -> its matches, by kickoff
    player_rows: list[tuple[str, int, str, int, float]]      # (kickoff, player, pos, minutes, xg+xa)
    pos: dict[int, str]


def load(season: str) -> SeasonData:
    files = sources.mirror_files(season, evaluate.MIRROR_REF, evaluate.CACHE)
    rows = list(csv.DictReader(io.StringIO(files["gws/merged_gw.csv"].decode("utf-8"))))
    s = sources.load_mirror(season, evaluate.MIRROR_REF, evaluate.CACHE)
    fixtures = {f.id: (f.gw, f.home, f.away, f.kickoff) for f in s.fixtures if f.gw}
    tm: dict[tuple[str, str], TeamMatch] = {}
    player_rows, pos = [], {}
    for r in rows:
        fid = r["fixture"]
        if fid not in fixtures:
            continue
        pid, team, mins = int(r["element"]), r["team"], int(r["minutes"])
        pos[pid] = POSMAP[r["position"]]
        t = tm.setdefault((fid, team), TeamMatch(fid, fixtures[fid][3]))
        t.minutes[pid] = t.minutes.get(pid, 0) + mins
        if r.get("starts") == "1":
            t.starters.add(pid)
        player_rows.append((fixtures[fid][3], pid, pos[pid], mins,
                            float(r["expected_goals"] or 0) + float(r["expected_assists"] or 0)))
    by_team = defaultdict(list)
    for (fid, team), t in tm.items():
        by_team[team].append(t)
    for v in by_team.values():
        v.sort(key=lambda t: t.kickoff)
    player_rows.sort()
    return SeasonData(fixtures, dict(by_team), player_rows, pos)


class Contributions:
    """Season-to-date attacking contribution per 90, shrunk to positional average,
    using only player rows that kicked off before the current cutoff."""

    def __init__(self, data: SeasonData):
        self.rows, self.i = data.player_rows, 0
        self.mins, self.out = defaultdict(int), defaultdict(float)
        self.pmins, self.pout = defaultdict(int), defaultdict(float)
        self.pos = data.pos

    def advance(self, cutoff: str) -> None:
        while self.i < len(self.rows) and self.rows[self.i][0] < cutoff:
            _, pid, pos, mins, out = self.rows[self.i]
            self.mins[pid] += mins; self.out[pid] += out
            self.pmins[pos] += mins; self.pout[pos] += out
            self.i += 1

    def c(self, pid: int) -> float:
        p = self.pos[pid]
        rate = self.pout[p] / self.pmins[p] if self.pmins[p] else 0.0
        return (self.out[pid] + PRIOR_MINUTES * rate) / (self.mins[pid] + PRIOR_MINUTES) * 90


def usual(previous: list[TeamMatch], n: int, keep=lambda pid: True) -> list[int]:
    """The n players with the most minutes over the previous WINDOW matches (ties: lower id)."""
    mins = defaultdict(int)
    for t in previous[-WINDOW:]:
        for pid, m in t.minutes.items():
            if keep(pid):
                mins[pid] += m
    return sorted(mins, key=lambda p: (-mins[p], p))[:n]


@dataclass
class Side:
    L: float = 1.0
    capped: bool = False
    status: str = "ok"           # ok | no_history | not_11_starters
    flagged: bool | None = None  # exploratory defence flag (None = excluded)


def side(match: TeamMatch, previous: list[TeamMatch], contrib: Contributions) -> Side:
    out = Side()
    if previous:
        gk = usual(previous, 1, lambda p: contrib.pos[p] == "GKP")
        defs = usual(previous, 4, lambda p: contrib.pos[p] == "DEF")
        out.flagged = (bool(gk) and gk[0] not in match.starters) or sum(d not in match.starters for d in defs) >= 2
    if not previous:
        out.status = "no_history"; return out
    if len(match.starters) != 11:
        out.status = "not_11_starters"; return out
    base = sum(contrib.c(p) for p in usual(previous, 11))
    L = sum(contrib.c(p) for p in match.starters) / base if base > 0 else 1.0
    out.L, out.capped = min(max(L, CAP[0]), CAP[1]), not CAP[0] <= L <= CAP[1]
    return out


def lineup_factors(season: str, rows: list[Row], data: SeasonData) -> list[tuple[Side, Side]]:
    """(home side, away side) for each walk-forward row, using only pre-gameweek data."""
    fid_of = {(h, a): fid for fid, (gw, h, a, k) in data.fixtures.items()}
    contrib = Contributions(data)
    cutoff_of = {}
    for r in rows:
        k = data.fixtures[fid_of[(r.home, r.away)]][3]
        cutoff_of[r.gw] = min(cutoff_of.get(r.gw, k), k)
    out = []
    for r in rows:
        cutoff = cutoff_of[r.gw]
        contrib.advance(cutoff)
        fid = fid_of[(r.home, r.away)]
        sides = []
        for team in (r.home, r.away):
            ms = data.team_matches[team]
            this = next(t for t in ms if t.fixture == fid)
            prev = [t for t in ms if t.kickoff < cutoff]
            sides.append(side(this, prev, contrib))
        out.append(tuple(sides))
    return out


def ratio_ci(a_pairs, b_pairs, reps=2000, seed=7):
    """Difference of ratio-of-sums (b - a) with a bootstrap interval over items."""
    rs = lambda ps: sum(x for x, _ in ps) / sum(y for _, y in ps)
    rng = random.Random(seed)
    diffs = sorted(rs([rng.choice(b_pairs) for _ in b_pairs]) - rs([rng.choice(a_pairs) for _ in a_pairs])
                   for _ in range(reps))
    return rs(a_pairs), rs(b_pairs), rs(b_pairs) - rs(a_pairs), diffs[int(.025 * reps)], diffs[int(.975 * reps) - 1]


def study() -> dict:
    cfg = model.Config.load(evaluate.PARAMS)
    assert cfg == model.BASELINE, "pre-registration fixes v0.1 parameters"
    matches = {s: evaluate.load(s) for s in evaluate.needed(TEST_SEASONS)}
    base_rows, orc_rows, sides_all, season_of = [], [], [], []
    xg_actual = {}
    for s in TEST_SEASONS:
        data = load(s)
        rows = evaluate.walk_forward(s, matches[s], matches[evaluate.previous_season(s)], cfg)
        sides = lineup_factors(s, rows, data)
        for m in matches[s]:
            xg_actual[(s, m.home, m.away)] = (m.home_xg, m.away_xg)
        for r, (h, a) in zip(rows, sides):
            base_rows.append(r); orc_rows.append(replace(r, lh=r.lh * h.L, la=r.la * a.L)); sides_all.append((h, a))
    pb, po = evaluate.probabilities(base_rows, cfg.rho), evaluate.probabilities(orc_rows, cfg.rho)
    llb, llo = evaluate.per_match_log_loss(base_rows, pb), evaluate.per_match_log_loss(orc_rows, po)
    diff = lambda a, b: dict(zip(("mean", "ci_low", "ci_high"), evaluate.paired_ci(a, b, reps=2000, seed=7)))
    brier = lambda rows, ps: [sum((p[k] - (k == r.outcome)) ** 2 for k in "HDA") for r, p in zip(rows, ps)]
    primary = diff(llb, llo)

    d = primary["mean"]
    if d <= -0.005 and primary["ci_high"] < 0:
        decision = "build phase 3"
    elif d <= -0.0025 and primary["ci_high"] < 0:
        decision = "build only a minimal phase 3"
    else:
        decision = "stop"

    per_season = {}
    for s in TEST_SEASONS:
        idx = [i for i, r in enumerate(base_rows) if r.season == s]
        per_season[s] = {"n": len(idx), "v01": sum(llb[i] for i in idx) / len(idx),
                         "oracle": sum(llo[i] for i in idx) / len(idx), "change": diff([llb[i] for i in idx], [llo[i] for i in idx])}

    # subgroup: top quarter by max |log L|
    dev = [max(abs(math.log(h.L)), abs(math.log(a.L))) for h, a in sides_all]
    cut = sorted(dev, reverse=True)[len(dev) // 4 - 1]
    sub = [i for i, x in enumerate(dev) if x >= cut]

    # market comparison
    market = {}
    for s in MARKET_SEASONS:
        odds = benchmark.parse_odds((benchmark.DATA_DIR / f"E0_{s}.csv").read_bytes())
        idx = [i for i, r in enumerate(orc_rows) if r.season == s]
        rows_s = [orc_rows[i] for i in idx]
        kick = {(m.home, m.away): m.kickoff for m in matches[s]}
        rep = benchmark.match(rows_s, kick, odds)
        assert len(rep.matched) == len(rows_s), "benchmark matching changed"
        market[s] = [benchmark.implied(o.odds["average_closing"])[0] for _, o in rep.matched]
    m_idx = [i for i, r in enumerate(orc_rows) if r.season in MARKET_SEASONS]
    m_probs = market[MARKET_SEASONS[0]] + market[MARKET_SEASONS[1]]
    m_rows = [orc_rows[i] for i in m_idx]
    ll_market = evaluate.per_match_log_loss(m_rows, m_probs)

    # exploratory defence check: opponent actual xG / opponent predicted xG
    flagged, unflagged = [], []
    for r, (h, a) in zip(base_rows, sides_all):
        hx, ax = xg_actual[(r.season, r.home, r.away)]
        if hx is None:
            continue
        for sd, actual_against, pred_against in ((h, ax, r.la), (a, hx, r.lh)):
            if sd.flagged is None:
                continue
            (flagged if sd.flagged else unflagged).append((actual_against, pred_against))
    un_ratio, fl_ratio, d_ratio, lo, hi = ratio_ci(unflagged, flagged)

    count = lambda pred: sum(pred(h) + pred(a) for h, a in sides_all)
    mb, mo = evaluate.metrics(base_rows, pb), evaluate.metrics(orc_rows, po)
    return {
        "generated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "preregistration": PREREG,
        "params": cfg.to_dict(), "mirror_ref": evaluate.MIRROR_REF,
        "dataset_sha256": evaluate.dataset_fingerprint(evaluate.needed(TEST_SEASONS)),
        "n": len(base_rows),
        "sides": {"total": 2 * len(sides_all), "capped": count(lambda x: x.capped),
                  "no_history": count(lambda x: x.status == "no_history"),
                  "not_11_starters": count(lambda x: x.status == "not_11_starters"),
                  "L_mean": sum(x.L for hs in sides_all for x in hs) / (2 * len(sides_all))},
        "primary": {"v01": sum(llb) / len(llb), "oracle": sum(llo) / len(llo), "change": primary},
        "decision": decision,
        "per_season": per_season,
        "secondary": {"brier": {"v01": mb["brier"], "oracle": mo["brier"], "change": diff(brier(base_rows, pb), brier(orc_rows, po))},
                      "accuracy": {"v01": mb["accuracy"], "oracle": mo["accuracy"]},
                      "draws": {"observed": mb["draws"]["actual_rate"], "v01": mb["draws"]["mean_predicted"], "oracle": mo["draws"]["mean_predicted"]},
                      "market_2024_26": {"n": len(m_rows), "oracle": sum(llo[i] for i in m_idx) / len(m_idx),
                                         "v01": sum(llb[i] for i in m_idx) / len(m_idx), "market": sum(ll_market) / len(ll_market),
                                         "oracle_minus_market": diff(ll_market, [llo[i] for i in m_idx]),
                                         "v01_minus_market": diff(ll_market, [llb[i] for i in m_idx])}},
        "subgroup_top_quarter_lineup_change": {"n": len(sub), "v01": sum(llb[i] for i in sub) / len(sub),
                                               "oracle": sum(llo[i] for i in sub) / len(sub),
                                               "change": diff([llb[i] for i in sub], [llo[i] for i in sub])},
        "exploratory_defence": {"flagged_n": len(flagged), "unflagged_n": len(unflagged),
                                "ratio_unflagged": un_ratio, "ratio_flagged": fl_ratio,
                                "difference": {"mean": d_ratio, "ci_low": lo, "ci_high": hi}},
    }


def main() -> None:
    res = study()
    path = evaluate.EXPERIMENTS / "2026-11-22-lineup.json"
    path.write_text(json.dumps(res, indent=2))
    print(f"Wrote {path}")


if __name__ == "__main__":
    main()
