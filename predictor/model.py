"""Team ratings and scoreline model.

Each match produces a "goal signal" per side: a blend of expected goals (xG) and
actual goals. Attack and defence ratings are solved jointly so that every team's
signal is explained by its own strength and its opponents' strength. Ratings are
anchored to a prior (last season, shrunk toward average) that is worth a fixed
number of games, so early-season noise doesn't swing them too far.

Predictions use independent Poisson goals with the Dixon-Coles low-score
adjustment.
"""
from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass, field

MAX_GOALS = 8          # scoreline grid is 0..MAX_GOALS for each side
RHO = -0.08            # Dixon-Coles low-score dependence
XG_WEIGHT = 0.7        # share of xG (vs actual goals) in the goal signal
NO_XG_WEIGHT = 0.5     # weight of a match with no xG available (goals only)
PRIOR_GAMES = 8        # how many games the prior rating is worth
PRIOR_SHRINK = 0.75    # keep 75% of last season's distance from average
ITERATIONS = 30


@dataclass
class Match:
    gw: int
    home: str
    away: str
    home_goals: int
    away_goals: int
    home_xg: float | None = None
    away_xg: float | None = None
    kickoff: str = ""

    @property
    def outcome(self) -> str:
        if self.home_goals > self.away_goals:
            return "H"
        return "A" if self.home_goals < self.away_goals else "D"


@dataclass
class Ratings:
    attack: dict[str, float]
    defence: dict[str, float]
    mu_home: float
    mu_away: float
    prior: dict[str, tuple[float, float]] = field(default_factory=dict)


@dataclass
class Prediction:
    home_xg: float
    away_xg: float
    p_home: float
    p_draw: float
    p_away: float
    grid: list[list[float]]

    @property
    def most_likely_score(self) -> tuple[int, int]:
        best = max(((i, j) for i in range(len(self.grid)) for j in range(len(self.grid))),
                   key=lambda ij: self.grid[ij[0]][ij[1]])
        return best


def _signal(m: Match, side: str) -> tuple[float, float]:
    """(goal signal, weight) for one side of a match."""
    goals, xg = (m.home_goals, m.home_xg) if side == "h" else (m.away_goals, m.away_xg)
    if xg is None:
        return float(goals), NO_XG_WEIGHT
    return XG_WEIGHT * xg + (1 - XG_WEIGHT) * goals, 1.0


def fit(matches: list[Match], teams: set[str],
        prior: dict[str, tuple[float, float]] | None = None,
        prior_games: float = PRIOR_GAMES) -> Ratings:
    """Solve schedule-adjusted attack/defence ratings (1.0 = league average)."""
    prior = prior or {}
    with_xg = [m for m in matches if m.home_xg is not None] or matches
    if with_xg:
        mu_h = sum(_signal(m, "h")[0] for m in with_xg) / len(with_xg)
        mu_a = sum(_signal(m, "a")[0] for m in with_xg) / len(with_xg)
    else:
        mu_h, mu_a = 1.5, 1.2

    att = {t: 1.0 for t in teams}
    dfn = {t: 1.0 for t in teams}
    for _ in range(ITERATIONS):
        new_att, new_dfn = {}, {}
        for t in teams:
            scored = exp_scored = conceded = exp_conceded = n = 0.0
            for m in matches:
                (hv, hw), (av, aw) = _signal(m, "h"), _signal(m, "a")
                if m.home == t:
                    scored += hw * hv; exp_scored += hw * mu_h * dfn[m.away]
                    conceded += aw * av; exp_conceded += aw * mu_a * att[m.away]; n += hw
                elif m.away == t:
                    scored += aw * av; exp_scored += aw * mu_a * dfn[m.home]
                    conceded += hw * hv; exp_conceded += hw * mu_h * att[m.home]; n += aw
            pa, pd = prior.get(t, (1.0, 1.0))
            if n == 0:
                new_att[t], new_dfn[t] = pa, pd
                continue
            # The prior behaves like `prior_games` extra games played at the prior rating.
            per_game_s, per_game_c = exp_scored / n, exp_conceded / n
            new_att[t] = (scored + prior_games * pa * per_game_s) / (exp_scored + prior_games * per_game_s)
            new_dfn[t] = (conceded + prior_games * pd * per_game_c) / (exp_conceded + prior_games * per_game_c)
        mean_a = sum(new_att.values()) / len(new_att)
        mean_d = sum(new_dfn.values()) / len(new_dfn)
        att = {t: v / mean_a for t, v in new_att.items()}
        dfn = {t: v / mean_d for t, v in new_dfn.items()}
    return Ratings(att, dfn, mu_h, mu_a, prior)


def _poisson(k: int, lam: float) -> float:
    return math.exp(-lam) * lam ** k / math.factorial(k)


def predict(home: str, away: str, r: Ratings, rho: float = RHO, max_goals: int = MAX_GOALS) -> Prediction:
    lh = r.mu_home * r.attack[home] * r.defence[away]
    la = r.mu_away * r.attack[away] * r.defence[home]
    g = [[_poisson(i, lh) * _poisson(j, la) for j in range(max_goals + 1)] for i in range(max_goals + 1)]
    g[0][0] *= 1 - lh * la * rho
    g[0][1] *= 1 + lh * rho
    g[1][0] *= 1 + la * rho
    g[1][1] *= 1 - rho
    total = sum(map(sum, g))
    g = [[v / total for v in row] for row in g]
    n = range(max_goals + 1)
    ph = sum(g[i][j] for i in n for j in n if i > j)
    pa = sum(g[i][j] for i in n for j in n if i < j)
    return Prediction(lh, la, ph, 1 - ph - pa, pa, g)


def table_points(matches: list[Match]) -> Counter:
    pts: Counter = Counter()
    for m in matches:
        pts[m.home] += {"H": 3, "D": 1, "A": 0}[m.outcome]
        pts[m.away] += {"H": 0, "D": 1, "A": 3}[m.outcome]
    return pts


def season_prior(last_season: list[Match], this_season_teams: set[str]) -> tuple[dict, list[str]]:
    """Prior ratings for this season from last season's full-season fit.

    Returning teams keep last season's rating shrunk toward average. Promoted
    teams start from the average of last season's bottom three, a reasonable
    proxy for a newly promoted side.
    """
    last_teams = {m.home for m in last_season} | {m.away for m in last_season}
    r = fit(last_season, last_teams, prior_games=0)
    pts = table_points(last_season)
    bottom3 = sorted(last_teams, key=lambda t: pts[t])[:3]
    promoted = (sum(r.attack[t] for t in bottom3) / 3, sum(r.defence[t] for t in bottom3) / 3)
    shrink = lambda v: 1 + PRIOR_SHRINK * (v - 1)
    prior = {t: (shrink(r.attack[t]), shrink(r.defence[t])) if t in last_teams else promoted
             for t in this_season_teams}
    return prior, bottom3


def backtest(matches: list[Match], start_gw: int = 4, prior_games: float = 4) -> dict:
    """Walk-forward test: predict each gameweek using only matches before it."""
    teams = {m.home for m in matches} | {m.away for m in matches}
    rows = []
    last_gw = max(m.gw for m in matches)
    for gw in range(start_gw, last_gw + 1):
        past = [m for m in matches if m.gw < gw]
        r = fit(past, teams, prior_games=prior_games)
        for m in (x for x in matches if x.gw == gw):
            p = predict(m.home, m.away, r)
            probs = {"H": p.p_home, "D": p.p_draw, "A": p.p_away}
            rows.append((max(probs, key=probs.get), m.outcome,
                         sum((probs[k] - (k == m.outcome)) ** 2 for k in "HDA")))
    n = len(rows)
    if n == 0:
        return {"n": 0}
    base = Counter(out for _, out, _ in rows)
    rate = {k: base[k] / n for k in "HDA"}
    base_brier = sum(sum((rate[k] - (k == out)) ** 2 for k in "HDA") for _, out, _ in rows) / n
    return {
        "n": n,
        "accuracy": sum(pick == out for pick, out, _ in rows) / n,
        "home_accuracy": rate["H"],
        "brier": sum(b for *_, b in rows) / n,
        "base_brier": base_brier,
    }
