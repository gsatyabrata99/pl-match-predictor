"""Recency-weighting study (research only; not used by the production predictor).

    python -m predictor.recency

Implements exactly the protocol in experiments/2026-11-06-RECENCY-PREREGISTRATION.md.
"""
from __future__ import annotations

import json
import math
from collections import defaultdict
from datetime import datetime, timezone

from . import evaluate, model
from .evaluate import Row
from .model import Config, Match, Ratings, SeasonPrior

HALF_LIVES = [None, 30, 60, 90, 120, 180]          # None = no decay (v0.1)
ALL_SEASONS = ("2022-23", "2023-24", "2024-25", "2025-26")
TEST_SEASONS = ("2023-24", "2024-25", "2025-26")
DRAW_BINS = [(0.0, 0.22), (0.22, 0.26), (0.26, 0.30), (0.30, 1.0)]
PREREG = "experiments/2026-11-06-RECENCY-PREREGISTRATION.md"


def _ts(iso: str) -> float:
    return datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp()


def decay(age_days: float, half_life: float | None) -> float:
    return 1.0 if half_life is None else 2 ** (-age_days / half_life)


def fit_decayed(matches: list[Match], teams: set[str], cfg: Config, prior: SeasonPrior,
                cutoff: str, half_life: float | None) -> Ratings:
    """model.fit with each match's signal weight multiplied by its decay weight.

    League averages stay unweighted (as in production). Each team's prior weight is
    cfg.prior_games x (its average decay weight), so the prior-to-data ratio is the
    same as without decay. With half_life=None this is identical to model.fit.
    """
    mu_h, mu_a, _ = model.league_averages(matches, cfg, (prior.mu_home, prior.mu_away))
    c = _ts(cutoff)
    sig = []
    for m in matches:
        d = decay((c - _ts(m.kickoff)) / 86400, half_life)
        (hv, hw), (av, aw) = model.signal(m, "h", cfg), model.signal(m, "a", cfg)
        sig.append((m.home, m.away, hv, hw, av, aw, d))
    raw = defaultdict(float)                         # undecayed signal weights per team
    for h, a, _, hw, _, aw, _ in sig:
        raw[h] += hw; raw[a] += aw
    att = {t: 1.0 for t in teams}
    dfn = {t: 1.0 for t in teams}
    for _ in range(model.ITERATIONS):
        scored, exp_s, conc, exp_c, n = (defaultdict(float) for _ in range(5))
        for h, a, hv, hw, av, aw, d in sig:
            hw_d, aw_d = hw * d, aw * d
            scored[h] += hw_d * hv; exp_s[h] += hw_d * mu_h * dfn[a]
            conc[h] += aw_d * av;   exp_c[h] += aw_d * mu_a * att[a]; n[h] += hw_d
            scored[a] += aw_d * av; exp_s[a] += aw_d * mu_a * dfn[h]
            conc[a] += hw_d * hv;   exp_c[a] += hw_d * mu_h * att[h]; n[a] += aw_d
        new_att, new_dfn = {}, {}
        for t in teams:
            pa, pd = prior.teams.get(t, (1.0, 1.0))
            if n[t] == 0:
                new_att[t], new_dfn[t] = pa, pd
                continue
            w_prior = cfg.prior_games * (n[t] / raw[t])          # 8 x average decay weight
            per_s, per_c = exp_s[t] / n[t], exp_c[t] / n[t]
            new_att[t] = (scored[t] + w_prior * pa * per_s) / (exp_s[t] + w_prior * per_s)
            new_dfn[t] = (conc[t] + w_prior * pd * per_c) / (exp_c[t] + w_prior * per_c)
        mean_a = sum(new_att.values()) / len(new_att)
        mean_d = sum(new_dfn.values()) / len(new_dfn)
        att = {t: v / mean_a for t, v in new_att.items()}
        dfn = {t: v / mean_d for t, v in new_dfn.items()}
    return Ratings(att, dfn, mu_h, mu_a, dict(prior.teams))


def walk_forward(season: str, matches: list[Match], last: list[Match], cfg: Config,
                 half_life: float | None) -> list[Row]:
    teams = {m.home for m in matches} | {m.away for m in matches}
    prior = model.season_prior(last, teams, cfg)
    by_gw: dict[int, list[Match]] = {}
    for m in matches:
        by_gw.setdefault(m.gw, []).append(m)
    rows = []
    for gw in sorted(by_gw):
        cutoff = min(m.kickoff for m in by_gw[gw])
        r = fit_decayed([m for m in matches if m.kickoff < cutoff], teams, cfg, prior, cutoff, half_life)
        for m in by_gw[gw]:
            lh, la = model.expected_goals(m.home, m.away, r)
            rows.append(Row(season, gw, m.home, m.away, m.outcome, m.home_goals, m.away_goals, lh, la))
    return rows


# ---------------------------------------------------------------- subgroups
def changed_teams(season_matches: list[Match], last: list[Match], cfg: Config, k: int = 5) -> set[str]:
    teams = {m.home for m in season_matches} | {m.away for m in season_matches}
    prior = model.season_prior(last, teams, cfg)
    end = model.fit(season_matches, teams, cfg, prior=prior)
    change = {t: abs(math.log(end.attack[t] / end.defence[t]) - math.log(prior.teams[t][0] / prior.teams[t][1]))
              for t in teams}
    return set(sorted(teams, key=change.get, reverse=True)[:k])


def promoted_teams(season_matches: list[Match], last: list[Match]) -> set[str]:
    now = {m.home for m in season_matches}
    return now - {m.home for m in last}


def draw_calibration(rows: list[Row], probs: list[dict]) -> list[dict]:
    out = []
    for lo, hi in DRAW_BINS:
        pts = [(p["D"], r.outcome == "D") for r, p in zip(rows, probs) if lo <= p["D"] < hi]
        out.append({"bin": f"{lo:.2f}-{hi:.2f}", "n": len(pts),
                    "predicted": sum(x for x, _ in pts) / len(pts) if pts else None,
                    "observed": sum(y for _, y in pts) / len(pts) if pts else None})
    return out


def brier(rows, probs) -> list[float]:
    return [sum((p[k] - (k == r.outcome)) ** 2 for k in "HDA") for r, p in zip(rows, probs)]


def diff(a: list[float], b: list[float]) -> dict:
    """Mean of (b - a) with the registered paired bootstrap. Negative = b better."""
    return dict(zip(("mean", "ci_low", "ci_high"), evaluate.paired_ci(a, b, reps=2000, seed=7)))


# ---------------------------------------------------------------- study
def study() -> dict:
    cfg = Config.load(evaluate.PARAMS)
    assert cfg == model.BASELINE, "pre-registration fixes v0.1 parameters"
    data = {s: evaluate.load(s) for s in evaluate.needed(ALL_SEASONS)}
    prev = evaluate.previous_season
    runs = {(s, h): walk_forward(s, data[s], data[prev(s)], cfg, h) for s in ALL_SEASONS for h in HALF_LIVES}
    probs = {k: evaluate.probabilities(v, cfg.rho) for k, v in runs.items()}
    ll = {k: evaluate.per_match_log_loss(runs[k], probs[k]) for k in runs}
    mean = lambda xs: sum(xs) / len(xs)

    label = lambda h: "none" if h is None else str(h)
    grid = {s: {label(h): {"log_loss": mean(ll[(s, h)]), "brier": mean(brier(runs[(s, h)], probs[(s, h)])),
                           "accuracy": evaluate.metrics(runs[(s, h)], probs[(s, h)])["accuracy"]}
                for h in HALF_LIVES} for s in ALL_SEASONS}

    choice = {t: min(HALF_LIVES, key=lambda h: mean(ll[(prev(t), h)])) for t in TEST_SEASONS}

    # pooled season-ahead choice vs no decay, same matches
    rows_c = [r for t in TEST_SEASONS for r in runs[(t, choice[t])]]
    p_c = [p for t in TEST_SEASONS for p in probs[(t, choice[t])]]
    rows_0 = [r for t in TEST_SEASONS for r in runs[(t, None)]]
    p_0 = [p for t in TEST_SEASONS for p in probs[(t, None)]]
    assert [(r.season, r.home, r.away) for r in rows_c] == [(r.season, r.home, r.away) for r in rows_0]
    ll_c, ll_0 = evaluate.per_match_log_loss(rows_c, p_c), evaluate.per_match_log_loss(rows_0, p_0)
    m_c, m_0 = evaluate.metrics(rows_c, p_c), evaluate.metrics(rows_0, p_0)

    per_season = {}
    for t in TEST_SEASONS:
        a, b = ll[(t, None)], ll[(t, choice[t])]
        per_season[t] = {"chosen": label(choice[t]), "chosen_on": prev(t),
                         "no_decay": mean(a), "choice": mean(b), "change": diff(a, b)}
    wins = sum(per_season[t]["choice"] < per_season[t]["no_decay"] for t in TEST_SEASONS)
    pooled_change = diff(ll_0, ll_c)

    # subgroups
    sub = {}
    groups = {"changed_teams": {t: changed_teams(data[t], data[prev(t)], cfg) for t in TEST_SEASONS},
              "promoted_teams": {t: promoted_teams(data[t], data[prev(t)]) for t in TEST_SEASONS}}
    for name, members in groups.items():
        idx = [i for i, r in enumerate(rows_0) if r.home in members[r.season] or r.away in members[r.season]]
        a, b = [ll_0[i] for i in idx], [ll_c[i] for i in idx]
        sub[name] = {"teams": {t: sorted(v) for t, v in members.items()}, "n": len(idx),
                     "no_decay": mean(a), "choice": mean(b), "change": diff(a, b)}

    nominated = wins >= 2 and pooled_change["ci_high"] < 0
    return {
        "generated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "preregistration": PREREG, "params": cfg.to_dict(), "mirror_ref": evaluate.MIRROR_REF,
        "dataset_sha256": evaluate.dataset_fingerprint(evaluate.needed(ALL_SEASONS)),
        "grid": grid, "season_ahead_choice": {t: label(h) for t, h in choice.items()},
        "primary": {"n": len(rows_c), "no_decay": mean(ll_0), "choice": mean(ll_c), "change": pooled_change},
        "per_season": per_season, "seasons_improved": wins,
        "secondary": {
            "brier": {"no_decay": m_0["brier"], "choice": m_c["brier"],
                      "change": diff(brier(rows_0, p_0), brier(rows_c, p_c))},
            "accuracy": {"no_decay": m_0["accuracy"], "choice": m_c["accuracy"]},
            "draws": {"observed": m_0["draws"]["actual_rate"], "no_decay": m_0["draws"]["mean_predicted"],
                      "choice": m_c["draws"]["mean_predicted"]},
            "draw_calibration": {"no_decay": draw_calibration(rows_0, p_0), "choice": draw_calibration(rows_c, p_c)},
        },
        "subgroups": sub,
        "nomination": {"rule": "choice better in >= 2 of 3 test seasons AND pooled 95% CI entirely below zero",
                       "seasons_improved": wins, "pooled_ci_high": pooled_change["ci_high"], "nominated": nominated},
    }


def main() -> None:
    res = study()
    path = evaluate.EXPERIMENTS / "2026-11-06-recency.json"
    path.write_text(json.dumps(res, indent=2))
    print(f"Wrote {path}")


if __name__ == "__main__":
    main()
