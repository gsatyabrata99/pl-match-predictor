"""Walk-forward backtest of FPL expected points on a past season.

    python -m predictor.fpl backtest

For every gameweek from START_GW, each player's points are forecast using only
earlier gameweeks: player histories, team ratings fitted on matches that kicked off
before the gameweek began (with the previous season as prior, exactly as the match
predictor does) and the production model parameters. Forecasts are compared with
the points actually scored.

Historical availability flags (injury news) are not archived, so the backtest gives
the model no injury information; the live tool has it.

Baselines, using the same minutes model:
    ppg      points per appearance so far x chance of playing
    recent   average points over the last FORM_GWS team gameweeks
"""
from __future__ import annotations

import csv
import io
import json
import math
import random
from collections import defaultdict
from datetime import datetime, timezone

from . import evaluate, fpl, model, sources
from .fpl import GW, Fixture, Ratings

SEASON = "2025-26"
START_GW = 5
POSMAP = {"GK": "GKP", "GKP": "GKP", "DEF": "DEF", "MID": "MID", "FWD": "FWD"}


def load(season: str):
    files = sources.mirror_files(season, evaluate.MIRROR_REF, evaluate.CACHE)
    rows = list(csv.DictReader(io.StringIO(files["gws/merged_gw.csv"].decode("utf-8"))))
    s = sources.load_mirror(season, evaluate.MIRROR_REF, evaluate.CACHE)
    return rows, s


def spearman(x: list[float], y: list[float]) -> float:
    def ranks(v):
        order = sorted(range(len(v)), key=lambda i: v[i])
        r = [0.0] * len(v); i = 0
        while i < len(v):
            j = i
            while j + 1 < len(v) and v[order[j + 1]] == v[order[i]]:
                j += 1
            for k in range(i, j + 1):
                r[order[k]] = (i + j) / 2
            i = j + 1
        return r
    rx, ry = ranks(x), ranks(y)
    mx, my = sum(rx) / len(rx), sum(ry) / len(ry)
    num = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    den = math.sqrt(sum((a - mx) ** 2 for a in rx) * sum((b - my) ** 2 for b in ry))
    return num / den if den else 0.0


def paired_ci(diffs: list[float], reps: int = 2000, seed: int = 7) -> tuple[float, float, float]:
    rng = random.Random(seed)
    means = sorted(sum(rng.choice(diffs) for _ in diffs) / len(diffs) for _ in range(reps))
    return sum(diffs) / len(diffs), means[int(.025 * reps)], means[int(.975 * reps) - 1]


def run(season: str = SEASON) -> dict:
    cfg = model.Config.load(evaluate.PARAMS)
    rows, s = load(season)
    last = sources.load_mirror(evaluate.previous_season(season), evaluate.MIRROR_REF, evaluate.CACHE).matches()
    matches = s.matches()
    teams = set(s.teams)
    prior = model.season_prior(last, teams, cfg)
    fx_by_id = {f.id: f for f in s.fixtures}
    sc = fpl.DEFAULT_SCORING

    hist: dict[int, list[GW]] = defaultdict(list)
    pos: dict[int, str] = {}
    by_gw: dict[int, list[dict]] = defaultdict(list)
    for r in rows:
        by_gw[int(r["GW"])].append(r)
    team_gws: dict[str, list[int]] = defaultdict(list)
    for f in s.fixtures:
        if f.gw:
            for t in (f.home, f.away):
                if f.gw not in team_gws[t]:
                    team_gws[t].append(f.gw)

    results = []      # (gw, pid, pos, predicted, actual, ppg, recent)
    for gw in sorted(by_gw):
        gw_rows = by_gw[gw]
        if gw >= START_GW:
            kick = [fx_by_id[r["fixture"]].kickoff for r in gw_rows if r["fixture"] in fx_by_id]
            cutoff = min(kick)
            ratings = Ratings.from_model(model.fit([m for m in matches if m.kickoff < cutoff], teams, cfg, prior=prior),
                                         cfg.rho)
            priors = fpl.position_priors(hist, pos)
            pred, actual, meta = defaultdict(float), defaultdict(int), {}
            for r in gw_rows:
                pid = int(r["element"]); p = POSMAP[r["position"]]
                actual[pid] += int(r["total_points"])
                f = fx_by_id.get(r["fixture"])
                if f is None:
                    continue
                home = r["was_home"] == "True"
                team, opp = (f.home, f.away) if home else (f.away, f.home)
                tg = sorted(g for g in team_gws[team] if g < gw)
                prof = fpl.profile(hist.get(pid, []), p, tg, priors)
                pred[pid] += fpl.fixture_points(prof, Fixture(gw, team, opp, home, f.kickoff), ratings, sc)["total"]
                if pid not in meta:
                    h = hist.get(pid, [])
                    apps = [g for g in h if g.minutes > 0]
                    ppg = sum(g.points for g in apps) / len(apps) if apps else 0.0
                    pts_by = defaultdict(int)
                    for g in h:
                        pts_by[g.gw] += g.points
                    recent = [pts_by.get(g, 0) for g in tg[-fpl.FORM_GWS:]]
                    meta[pid] = (p, ppg * prof.p_play, sum(recent) / len(recent) if recent else 0.0,
                                 sum(g.minutes for g in h))
            for pid, (p, ppg, rec, mins_before) in meta.items():
                if mins_before > 0:                          # players with a track record this season
                    results.append((gw, pid, p, pred[pid], actual[pid], ppg, rec))
        for r in gw_rows:                                     # then reveal this gameweek
            pid = int(r["element"]); pos[pid] = POSMAP[r["position"]]
            hist[pid].append(GW(gw, int(r["minutes"]), float(r["expected_goals"] or 0), float(r["expected_assists"] or 0),
                                int(r["saves"]), int(r["bonus"]), int(r["yellow_cards"]),
                                int(r["defensive_contribution"]), int(r["total_points"])))

    return summarise(results, season)


def summarise(results, season) -> dict:
    preds = {"model": 3, "ppg": 5, "recent": 6}
    out = {"season": season, "start_gw": START_GW, "player_gameweeks": len(results),
           "gameweeks": len({r[0] for r in results}), "generated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
           "constants": {"form_gws": fpl.FORM_GWS, "rate_prior_minutes": fpl.RATE_PRIOR_MINUTES,
                         "defcon_prior_apps": fpl.DEFCON_PRIOR_APPS},
           "note": "No historical injury/availability data: the model gets none in this backtest.",
           "methods": {}}
    gws = sorted({r[0] for r in results})
    for name, i in preds.items():
        err = [r[i] - r[4] for r in results]
        rho = [spearman([r[i] for r in results if r[0] == g], [r[4] for r in results if r[0] == g]) for g in gws]
        captain, top11 = [], []
        for g in gws:
            gr = sorted((r for r in results if r[0] == g), key=lambda r: -r[i])
            captain.append(gr[0][4])
            top11.append(sum(r[4] for r in gr[:11]))
        out["methods"][name] = {
            "mae": sum(abs(e) for e in err) / len(err), "rmse": math.sqrt(sum(e * e for e in err) / len(err)),
            "bias": sum(err) / len(err), "spearman_mean": sum(rho) / len(rho),
            "captain_points_per_gw": sum(captain) / len(captain), "top11_points_per_gw": sum(top11) / len(top11),
        }
    for name in ("ppg", "recent"):
        i = preds[name]
        out["methods"][name]["model_minus_this_abs_error"] = dict(zip(
            ("mean", "ci_low", "ci_high"), paired_ci([abs(r[3] - r[4]) - abs(r[i] - r[4]) for r in results])))
    # calibration of the model's expected points
    bins = [(0, 1), (1, 2), (2, 3), (3, 4), (4, 5), (5, 6), (6, 99)]
    out["calibration"] = []
    for lo, hi in bins:
        sel = [r for r in results if lo <= r[3] < hi]
        if sel:
            out["calibration"].append({"bin": f"{lo}-{hi if hi < 99 else '+'}", "n": len(sel),
                                       "predicted": sum(r[3] for r in sel) / len(sel),
                                       "actual": sum(r[4] for r in sel) / len(sel)})
    out["by_position"] = {}
    for p in ("GKP", "DEF", "MID", "FWD"):
        sel = [r for r in results if r[2] == p]
        out["by_position"][p] = {"n": len(sel), "predicted": sum(r[3] for r in sel) / len(sel),
                                 "actual": sum(r[4] for r in sel) / len(sel),
                                 "mae": sum(abs(r[3] - r[4]) for r in sel) / len(sel)}
    return out


def main() -> None:
    res = run()
    path = evaluate.EXPERIMENTS / f"fpl-backtest-{SEASON}.json"
    path.write_text(json.dumps(res, indent=2))
    print(f"Wrote {path}")


if __name__ == "__main__":
    main()
