"""Exploratory research. Nothing here is used by the production predictor.

    python -m predictor.research margins      # proportional vs Shin vs power margin removal
    python -m predictor.research temperature  # season-ahead temperature scaling

All seasons used here have been inspected before; results are exploratory and must
be confirmed prospectively before any production change.
"""
from __future__ import annotations

import argparse
import json
import math
from datetime import datetime, timezone
from pathlib import Path

from . import benchmark, evaluate, model
from .evaluate import Row

ODDS_DIR = benchmark.DATA_DIR
OUT = evaluate.EXPERIMENTS


# ---------------------------------------------------------------- margin removal
def _bisect(f, lo: float, hi: float, iters: int = 200) -> float:
    """Root of a monotone function on [lo, hi]."""
    flo = f(lo)
    if abs(flo) < 1e-12:          # root at the boundary (e.g. odds with no margin)
        return lo
    for _ in range(iters):
        mid = (lo + hi) / 2
        if (f(mid) > 0) == (flo > 0):
            lo, flo = mid, f(mid)
        else:
            hi = mid
    return (lo + hi) / 2


def proportional(odds) -> dict[str, float]:
    return benchmark.implied(odds)[0]


def power(odds) -> dict[str, float]:
    """p_i = (1/o_i)^k, with k chosen so the probabilities sum to 1."""
    inv = [1 / o for o in odds]
    k = _bisect(lambda k: sum(x ** k for x in inv) - 1, 1.0, 10.0)
    p = [x ** k for x in inv]
    s = sum(p)
    return dict(zip("HDA", (x / s for x in p)))


def shin(odds) -> dict[str, float]:
    """Shin (1993): margin attributed to insider trading, solved for z."""
    inv = [1 / o for o in odds]
    S = sum(inv)
    probs = lambda z: [(math.sqrt(z * z + 4 * (1 - z) * x * x / S) - z) / (2 * (1 - z)) for x in inv]
    z = _bisect(lambda z: sum(probs(z)) - 1, 0.0, 0.5)
    p = probs(z)
    s = sum(p)
    return dict(zip("HDA", (x / s for x in p)))


METHODS = {"proportional": proportional, "shin": shin, "power": power}


def margin_sensitivity(odds_files: dict[str, Path]) -> dict:
    cfg = model.Config.load(evaluate.PARAMS)
    seasons = sorted(odds_files)
    data = {s: evaluate.load(s) for s in evaluate.needed(seasons)}
    matched = []
    for s in seasons:
        rows = evaluate.walk_forward(s, data[s], data[evaluate.previous_season(s)], cfg)
        rep = benchmark.match(rows, {(m.home, m.away): m.kickoff for m in data[s]},
                              benchmark.parse_odds(Path(odds_files[s]).read_bytes()))
        assert not (rep.unmatched_fixtures or rep.date_mismatches or rep.score_mismatches or rep.ambiguous)
        matched += rep.matched
    out = {}
    for market in (benchmark.PRIMARY, benchmark.SECONDARY):
        pairs = [(r, o) for r, o in matched if o.odds[market]]
        rows = [r for r, _ in pairs]
        model_p = evaluate.probabilities(rows, cfg.rho)
        ll_model = evaluate.per_match_log_loss(rows, model_p)
        out[market] = {"n": len(rows), "model": {k: evaluate.metrics(rows, model_p)[k]
                                                 for k in ("log_loss", "brier", "accuracy")}}
        for name, fn in METHODS.items():
            mp = [fn(o.odds[market]) for _, o in pairs]
            m = evaluate.metrics(rows, mp)
            d = evaluate.paired_ci(evaluate.per_match_log_loss(rows, mp), ll_model)
            fav = [p for p in mp for k in "HDA"]
            out[market][name] = {
                "log_loss": m["log_loss"], "brier": m["brier"], "accuracy": m["accuracy"],
                "mean_draw": m["draws"]["mean_predicted"],
                "mean_favourite_prob": sum(max(p.values()) for p in mp) / len(mp),
                "model_minus_market": dict(zip(("mean", "ci_low", "ci_high"), d)),
            }
    return out


# ---------------------------------------------------------------- temperature scaling
def temper(p: dict[str, float], T: float) -> dict[str, float]:
    w = {k: v ** (1 / T) for k, v in p.items()}
    s = sum(w.values())
    return {k: v / s for k, v in w.items()}


def mean_ll(rows, probs, T=1.0) -> float:
    return sum(evaluate.per_match_log_loss(rows, [temper(p, T) for p in probs])) / len(rows)


def fit_temperature(rows, probs) -> float:
    """T minimising log loss (golden-section search on log T)."""
    a, b = math.log(0.4), math.log(2.5)
    g = (math.sqrt(5) - 1) / 2
    c, d = b - g * (b - a), a + g * (b - a)
    for _ in range(80):
        if mean_ll(rows, probs, math.exp(c)) < mean_ll(rows, probs, math.exp(d)):
            b = d
        else:
            a = c
        c, d = b - g * (b - a), a + g * (b - a)
    return math.exp((a + b) / 2)


def extreme_bands(rows, probs) -> dict:
    """Mean predicted vs observed for strong favourites (>= .65) and longshots (< .20)."""
    out = {}
    for name, test in (("favourites_ge_0.65", lambda x: x >= .65), ("longshots_lt_0.20", lambda x: x < .20)):
        pts = [(p[k], r.outcome == k) for r, p in zip(rows, probs) for k in "HDA" if test(p[k])]
        out[name] = {"n": len(pts), "predicted": sum(x for x, _ in pts) / len(pts) if pts else None,
                     "observed": sum(y for _, y in pts) / len(pts) if pts else None}
    return out


def temperature_study(seasons=("2022-23", "2023-24", "2024-25", "2025-26")) -> dict:
    cfg = model.Config.load(evaluate.PARAMS)
    data = {s: evaluate.load(s) for s in evaluate.needed(seasons)}
    per = {}
    for s in seasons:
        rows = evaluate.walk_forward(s, data[s], data[evaluate.previous_season(s)], cfg)
        per[s] = (rows, evaluate.probabilities(rows, cfg.rho))
    result = {"in_season_T": {s: fit_temperature(*per[s]) for s in seasons}, "season_ahead": {},
              "expanding_window": {}}
    for i, s in enumerate(seasons[1:], start=1):
        rows, probs = per[s]
        for scheme, train in (("season_ahead", [seasons[i - 1]]), ("expanding_window", list(seasons[:i]))):
            tr_rows = [r for t in train for r in per[t][0]]
            tr_probs = [p for t in train for p in per[t][1]]
            T = fit_temperature(tr_rows, tr_probs)
            scaled = [temper(p, T) for p in probs]
            before, after = evaluate.metrics(rows, probs), evaluate.metrics(rows, scaled)
            d = evaluate.paired_ci(evaluate.per_match_log_loss(rows, probs), evaluate.per_match_log_loss(rows, scaled))
            result[scheme][s] = {
                "trained_on": train, "T": T,
                "log_loss": [before["log_loss"], after["log_loss"]], "brier": [before["brier"], after["brier"]],
                "accuracy": [before["accuracy"], after["accuracy"]],
                "change": dict(zip(("mean", "ci_low", "ci_high"), d)),
                "bands_before": extreme_bands(rows, probs), "bands_after": extreme_bands(rows, scaled),
            }
    for scheme in ("season_ahead", "expanding_window"):
        allb = [x for s in result[scheme] for x in [result[scheme][s]]]
        rows = [r for s in result[scheme] for r in per[s][0]]
        before = [p for s in result[scheme] for p in per[s][1]]
        after = [temper(p, result[scheme][s]["T"]) for s in result[scheme] for p in per[s][1]]
        d = evaluate.paired_ci(evaluate.per_match_log_loss(rows, before), evaluate.per_match_log_loss(rows, after))
        result[scheme]["pooled"] = {"n": len(rows), "log_loss": [mean_ll(rows, before), mean_ll(rows, after)],
                                    "change": dict(zip(("mean", "ci_low", "ci_high"), d))}
    return result


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("study", choices=["margins", "temperature"])
    a = ap.parse_args(argv)
    if a.study == "margins":
        res = margin_sensitivity({"2024-25": ODDS_DIR / "E0_2024-25.csv", "2025-26": ODDS_DIR / "E0_2025-26.csv"})
    else:
        res = temperature_study()
    res = {"generated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "exploratory": True,
           "model_params": model.Config.load(evaluate.PARAMS).to_dict(), "mirror_ref": evaluate.MIRROR_REF, **res}
    path = OUT / f"2026-11-05-research-{a.study}.json"
    path.write_text(json.dumps(res, indent=2))
    print(f"Wrote {path}")


if __name__ == "__main__":
    main()
