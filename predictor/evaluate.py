"""Leakage-free multi-season evaluation and hyperparameter tuning.

    python -m predictor.evaluate compare            # baseline vs params.json on development seasons
    python -m predictor.evaluate tune               # grid search on development seasons
    python -m predictor.evaluate compare --final    # the one-time held-out test

Seasons are split once and never mixed:

    development  2022-23, 2023-24   tuning and model selection
    test         2024-25, 2025-26   run only with --final, never used to choose anything

The test seasons were opened once, on 2026-11-05 (experiments/2026-11-05-FINAL-TEST.md).
They are now previously-inspected data: future model changes need chronological
validation, and genuinely new fixtures are the strongest independent confirmation.

Every prediction is walk-forward: a gameweek's matches are predicted from a fit on
matches that kicked off before that gameweek's first kickoff, plus a prior built
only from the previous season. Historical data is pinned to an exact commit of
vaastav/Fantasy-Premier-League and cached, so every number can be regenerated.
"""
from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import math
import random
import sys
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path

from . import model, sources
from .model import Config, Match

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "data" / "cache"
PARAMS = ROOT / "predictor" / "params.json"
EXPERIMENTS = ROOT / "experiments"
MIRROR_REF = "d7b05b51d137bfefef4b692386d18c610975b9b9"   # vaastav/Fantasy-Premier-League, 2026-11-05

DEV_SEASONS = ("2022-23", "2023-24")
TEST_SEASONS = ("2024-25", "2025-26")
EPS = 1e-12


class SealedSeasonError(RuntimeError):
    """Raised when a held-out test season is requested without --final."""


def guard(seasons, final: bool) -> None:
    sealed = [s for s in seasons if s in TEST_SEASONS]
    if sealed and not final:
        raise SealedSeasonError(f"{', '.join(sealed)} is held out for the final test; pass final=True / --final")


def previous_season(season: str) -> str:
    start = int(season[:4]) - 1
    return f"{start}-{str(start + 1)[2:]}"


# ---------------------------------------------------------------- data
def load(season: str) -> list[Match]:
    return sources.load_mirror(season, ref=MIRROR_REF, cache=CACHE).matches()


def dataset_fingerprint(seasons) -> dict:
    out = {}
    for s in seasons:
        for name, data in sources.mirror_files(s, MIRROR_REF, CACHE).items():
            out[f"{s}/{name}"] = hashlib.sha256(data).hexdigest()[:16]
    return out


# ---------------------------------------------------------------- walk-forward
@dataclass
class Row:
    season: str
    gw: int
    home: str
    away: str
    outcome: str
    home_goals: int
    away_goals: int
    lh: float
    la: float


def walk_forward(season: str, matches: list[Match], last: list[Match], cfg: Config) -> list[Row]:
    """Predict every match of a season using only information available before kickoff."""
    teams = {m.home for m in matches} | {m.away for m in matches}
    prior = model.season_prior(last, teams, cfg)
    by_gw: dict[int, list[Match]] = {}
    for m in matches:
        by_gw.setdefault(m.gw, []).append(m)
    rows = []
    for gw in sorted(by_gw):
        cutoff = min(m.kickoff for m in by_gw[gw])
        r = model.fit([m for m in matches if m.kickoff < cutoff], teams, cfg, prior=prior)
        for m in by_gw[gw]:
            lh, la = model.expected_goals(m.home, m.away, r)
            rows.append(Row(season, gw, m.home, m.away, m.outcome, m.home_goals, m.away_goals, lh, la))
    return rows


def probabilities(rows: list[Row], rho: float) -> list[dict]:
    out = []
    for r in rows:
        p = model.scoreline(r.lh, r.la, rho)
        out.append({"H": p.p_home, "D": p.p_draw, "A": p.p_away})
    return out


# ---------------------------------------------------------------- metrics
def per_match_log_loss(rows, probs) -> list[float]:
    return [-math.log(max(p[r.outcome], EPS)) for r, p in zip(rows, probs)]


def metrics(rows: list[Row], probs: list[dict]) -> dict:
    n = len(rows)
    ll = per_match_log_loss(rows, probs)
    brier = [sum((p[k] - (k == r.outcome)) ** 2 for k in "HDA") for r, p in zip(rows, probs)]
    picks = [max(p, key=p.get) for p in probs]
    draws = sum(r.outcome == "D" for r in rows)
    calib = []
    for lo in [i / 10 for i in range(10)]:
        pts = [(p[k], r.outcome == k) for r, p in zip(rows, probs) for k in "HDA" if lo <= p[k] < lo + 0.1]
        if pts:
            calib.append({"bin": f"{lo:.1f}-{lo + .1:.1f}", "n": len(pts),
                          "predicted": round(sum(x for x, _ in pts) / len(pts), 4),
                          "observed": round(sum(y for _, y in pts) / len(pts), 4)})
    return {
        "n": n,
        "log_loss": sum(ll) / n,
        "brier": sum(brier) / n,
        "accuracy": sum(pk == r.outcome for pk, r in zip(picks, rows)) / n,
        "draws": {"actual_rate": draws / n, "mean_predicted": sum(p["D"] for p in probs) / n,
                  "picked": picks.count("D"),
                  "recall": sum(pk == "D" == r.outcome for pk, r in zip(picks, rows)) / draws if draws else 0},
        "goals": {"pred_home": sum(r.lh for r in rows) / n, "actual_home": sum(r.home_goals for r in rows) / n,
                  "pred_away": sum(r.la for r in rows) / n, "actual_away": sum(r.away_goals for r in rows) / n},
        "calibration": calib,
    }


def base_rate_probs(rows: list[Row], seasons: dict[str, list[Match]]) -> list[dict]:
    """Naive baseline: last season's home/draw/away frequencies (known before kickoff)."""
    rates = {}
    for s in {r.season for r in rows}:
        last = seasons[previous_season(s)]
        rates[s] = {k: sum(m.outcome == k for m in last) / len(last) for k in "HDA"}
    return [rates[r.season] for r in rows]


def paired_ci(a: list[float], b: list[float], reps: int = 2000, seed: int = 7) -> tuple[float, float, float]:
    """Mean of (b - a) per match with a 95% bootstrap interval. Negative = b is better."""
    d = [y - x for x, y in zip(a, b)]
    rng = random.Random(seed)
    means = sorted(sum(rng.choice(d) for _ in d) / len(d) for _ in range(reps))
    return sum(d) / len(d), means[int(.025 * reps)], means[int(.975 * reps) - 1]


# ---------------------------------------------------------------- experiments
def run(cfg: Config, seasons, data) -> list[Row]:
    rows = []
    for s in seasons:
        rows += walk_forward(s, data[s], data[previous_season(s)], cfg)
    return rows


GRID = {
    "xg_weight": [0.5, 0.6, 0.7, 0.85, 1.0],
    "prior_games": [4, 8, 12, 20],
    "prior_shrink": [0.6, 0.75, 0.9],
    "mu_prior_games": [0, 40, 100, 200, 380],
}
RHO_GRID = [-0.2, -0.15, -0.1, -0.08, -0.05, 0.0, 0.05]


def tune(data, seasons=DEV_SEASONS, base: Config = model.BASELINE, progress=True) -> list[dict]:
    """Score every grid point on the given seasons by mean log loss (lower is better)."""
    guard(seasons, final=False)
    results = []
    keys = list(GRID)
    combos = list(itertools.product(*GRID.values()))
    for i, values in enumerate(combos):
        cfg = replace(base, **dict(zip(keys, values)))
        rows_by_season = {s: walk_forward(s, data[s], data[previous_season(s)], cfg) for s in seasons}
        for rho in RHO_GRID:
            entry = {**dict(zip(keys, values)), "rho": rho}
            for s, rows in rows_by_season.items():
                ll = per_match_log_loss(rows, probabilities(rows, rho))
                entry[s] = sum(ll) / len(ll)
            entry["log_loss"] = sum(entry[s] * len(rows_by_season[s]) for s in seasons) / \
                sum(len(r) for r in rows_by_season.values())
            results.append(entry)
        if progress and (i + 1) % 25 == 0:
            print(f"  {i + 1}/{len(combos)} grid points", file=sys.stderr)
    return sorted(results, key=lambda e: e["log_loss"])


def compare(old: Config, new: Config, seasons, data) -> dict:
    out = {"seasons": list(seasons), "per_season": {}}
    rows_o, rows_n = run(old, seasons, data), run(new, seasons, data)
    p_o, p_n = probabilities(rows_o, old.rho), probabilities(rows_n, new.rho)
    base = base_rate_probs(rows_o, data)
    out["old"], out["new"], out["base_rates"] = metrics(rows_o, p_o), metrics(rows_n, p_n), metrics(rows_o, base)
    ll_o, ll_n = per_match_log_loss(rows_o, p_o), per_match_log_loss(rows_n, p_n)
    out["log_loss_change"] = dict(zip(("mean", "ci_low", "ci_high"), paired_ci(ll_o, ll_n)))
    for s in seasons:
        idx = [i for i, r in enumerate(rows_o) if r.season == s]
        sub = lambda xs: [xs[i] for i in idx]
        out["per_season"][s] = {"old": metrics(sub(rows_o), sub(p_o)), "new": metrics(sub(rows_n), sub(p_n)),
                                "base_rates": metrics(sub(rows_o), sub(base))}
    return out


def needed(seasons) -> list[str]:
    return sorted(set(seasons) | {previous_season(s) for s in seasons})


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    t = sub.add_parser("tune", help="grid search on development seasons")
    t.add_argument("--out", type=Path, default=EXPERIMENTS / "tuning.json")
    c = sub.add_parser("compare", help="baseline vs a candidate config")
    c.add_argument("--params", type=Path, default=PARAMS)
    c.add_argument("--final", action="store_true", help="run the test seasons (already inspected on 2026-11-05)")
    c.add_argument("--out", type=Path)
    a = ap.parse_args(argv)

    if a.cmd == "tune":
        data = {s: load(s) for s in needed(DEV_SEASONS)}
        results = tune(data)
        # Chronological check: choose on the first development season, score on the second.
        first_best = min(results, key=lambda e: e[DEV_SEASONS[0]])
        report = {
            "generated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "objective": "mean multiclass log loss, walk-forward",
            "seasons": list(DEV_SEASONS), "mirror_ref": MIRROR_REF,
            "dataset_sha256": dataset_fingerprint(needed(DEV_SEASONS)),
            "grid": {**GRID, "rho": RHO_GRID}, "baseline": model.BASELINE.to_dict(),
            "best": results[0], "chosen_on_first_season": first_best, "top": results[:25],
            # Sensitivity: best achievable log loss for each value of each parameter.
            "marginals": {k: {str(v): min(e["log_loss"] for e in results if e[k] == v)
                              for v in (GRID[k] if k in GRID else RHO_GRID)}
                          for k in [*GRID, "rho"]},
            "n_configs": len(results),
        }
        a.out.parent.mkdir(parents=True, exist_ok=True)
        a.out.write_text(json.dumps(report, indent=2))
        print(json.dumps({"best": results[0], "chosen_on_first_season": first_best}, indent=2))
        return

    seasons = TEST_SEASONS if a.final else DEV_SEASONS
    guard(seasons, a.final)
    data = {s: load(s) for s in needed(seasons)}
    new = Config.load(a.params)
    result = compare(model.BASELINE, new, seasons, data)
    result.update(old_params=model.BASELINE.to_dict(), new_params=new.to_dict(), mirror_ref=MIRROR_REF,
                  dataset_sha256=dataset_fingerprint(needed(seasons)),
                  generated=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
    text = json.dumps(result, indent=2)
    if a.out:
        a.out.parent.mkdir(parents=True, exist_ok=True)
        a.out.write_text(text)
    print(text)


if __name__ == "__main__":
    main()
