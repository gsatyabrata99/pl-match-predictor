"""Build site/data/predictions.json.

    python -m predictor.build                 # official FPL API, falls back to the mirror
    python -m predictor.build --source mirror # community mirror only
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from . import model, sources

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUT = ROOT / "site" / "data" / "predictions.json"
MANUAL = ROOT / "data" / "manual_results.csv"


def previous_season(season: str) -> str:
    start = int(season[:4])
    return f"{start - 1}-{str(start)[2:]}"


def season_for(now: datetime) -> str:
    """Premier League seasons start in August: 2026-11-05 -> '2026-27'."""
    start = now.year if now.month >= 7 else now.year - 1
    return f"{start}-{str(start + 1)[2:]}"


def load_current(source: str, season: str) -> sources.Season:
    if source in ("fpl", "auto"):
        try:
            return sources.load_fpl()
        except Exception as e:  # network blocked, API down, schema change
            if source == "fpl":
                raise
            print(f"FPL API unavailable ({e}); falling back to the mirror", file=sys.stderr)
    return sources.load_mirror(season)


def build(source: str, season: str, now: datetime) -> dict:
    current = load_current(source, season)
    filled = sources.apply_manual_results(current, MANUAL)
    matches = current.matches()
    teams = set(current.teams)

    last = sources.load_mirror(previous_season(season)).matches()
    prior, relegated = model.season_prior(last, teams)
    bt = model.backtest(last)

    # Honest out-of-sample check: ratings as of the last gameweek with xG,
    # scored against later results that the model had not seen.
    xg_gws = [m.gw for m in matches if m.home_xg is not None]
    xg_through = max(xg_gws) if xg_gws else 0
    results_through = max((m.gw for m in matches), default=0)
    holdout_from = xg_through + 1 if xg_through < results_through else max(results_through - 2, 1)
    r_before = model.fit([m for m in matches if m.gw < holdout_from], teams, prior=prior)
    holdout = []
    for m in (x for x in matches if x.gw >= holdout_from):
        p = model.predict(m.home, m.away, r_before)
        holdout.append(dict(gw=m.gw, home=m.home, away=m.away, hg=m.home_goals, ag=m.away_goals,
                            ph=round(p.p_home, 4), pd=round(p.p_draw, 4), pa=round(p.p_away, 4)))

    r = model.fit(matches, teams, prior=prior)

    stats = defaultdict(lambda: dict(p=0, w=0, d=0, l=0, gf=0, ga=0, xgf=0.0, xga=0.0, xgp=0, form=""))
    for m in matches:
        for t, gf, ga, xf, xa in ((m.home, m.home_goals, m.away_goals, m.home_xg, m.away_xg),
                                  (m.away, m.away_goals, m.home_goals, m.away_xg, m.home_xg)):
            s = stats[t]
            s["p"] += 1; s["gf"] += gf; s["ga"] += ga
            s["w" if gf > ga else "d" if gf == ga else "l"] += 1
            s["form"] = (s["form"] + ("W" if gf > ga else "D" if gf == ga else "L"))[-5:]
            if xf is not None:
                s["xgf"] += xf; s["xga"] += xa; s["xgp"] += 1

    now_iso = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    upcoming = sorted((f for f in current.fixtures if f.gw and f.kickoff > now_iso and not f.finished),
                      key=lambda f: f.kickoff)
    missing = [f"{f.home} v {f.away} (GW{f.gw})" for f in current.fixtures
               if f.gw and f.kickoff and f.kickoff < now_iso and not f.finished]
    last_teams = {m.home for m in last}

    return {
        "meta": {
            "season": season, "source": current.source, "generated": now_iso,
            "results_through_gw": results_through, "xg_through_gw": xg_through,
            "manual_results": filled, "missing": missing,
            "mu_h": r.mu_home, "mu_a": r.mu_away, "rho": model.RHO, "maxg": model.MAX_GOALS,
            "prior_games": model.PRIOR_GAMES, "xg_w": model.XG_WEIGHT, "noxg_w": model.NO_XG_WEIGHT,
            "relegated_last": relegated, "backtest": bt, "holdout_from_gw": holdout_from,
        },
        "teams": [dict(name=t, short=current.teams[t], att=round(r.attack[t], 4), dfn=round(r.defence[t], 4),
                       prior_att=round(prior[t][0], 3), prior_dfn=round(prior[t][1], 3),
                       promoted=t not in last_teams,
                       **{k: round(v, 2) if isinstance(v, float) else v for k, v in stats[t].items()})
                  for t in sorted(teams)],
        "fixtures": [dict(gw=f.gw, home=f.home, away=f.away, kickoff=f.kickoff) for f in upcoming],
        "holdout": holdout,
    }


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--source", choices=["auto", "fpl", "mirror"], default="auto")
    ap.add_argument("--season", help="season, e.g. 2026-27 (default: the season in progress)")
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--now", help="override the current time (ISO 8601), for reproducible builds")
    a = ap.parse_args(argv)
    now = datetime.fromisoformat(a.now.replace("Z", "+00:00")) if a.now else datetime.now(timezone.utc)
    now = now.astimezone(timezone.utc)
    data = build(a.source, a.season or season_for(now), now)
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(data, separators=(",", ":")))
    m = data["meta"]
    print(f"Wrote {a.out} · source={m['source']} · results through GW{m['results_through_gw']} · "
          f"xG through GW{m['xg_through_gw']} · {len(data['fixtures'])} upcoming fixtures")


if __name__ == "__main__":
    main()
