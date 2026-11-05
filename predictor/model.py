"""Team ratings and scoreline model.

Each match produces a "goal signal" per side: a blend of expected goals (xG) and
actual goals. Attack and defence ratings are solved jointly so that every team's
signal is explained by its own strength and its opponents' strength. Ratings are
anchored to a prior (last season, shrunk toward average) that is worth a fixed
number of games, so early-season noise doesn't swing them too far. League
home/away scoring averages are anchored to last season the same way.

Predictions use independent Poisson goals with the Dixon-Coles low-score
adjustment.

Every tunable number lives in :class:`Config`.
"""
from __future__ import annotations

import json
import math
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field, fields, replace
from pathlib import Path

MAX_GOALS = 8          # scoreline grid is 0..MAX_GOALS for each side
ITERATIONS = 30        # rating solver iterations (converges well before this)


@dataclass(frozen=True)
class Config:
    xg_weight: float = 0.7        # share of xG (vs actual goals) in the goal signal
    no_xg_weight: float = 0.5     # weight of a match with no xG available (goals only)
    prior_games: float = 8        # how many games last season's team rating is worth
    prior_shrink: float = 0.75    # keep this share of last season's distance from average
    mu_prior_games: float = 0     # how many matches last season's league averages are worth
    rho: float = -0.08            # Dixon-Coles low-score dependence

    @classmethod
    def load(cls, path: Path) -> "Config":
        raw = json.loads(Path(path).read_text())
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in raw.get("params", raw).items() if k in known})

    def to_dict(self) -> dict:
        return asdict(self)


# The original v0.1 settings, kept so results can always be compared against them.
BASELINE = Config()


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
class SeasonPrior:
    """Everything carried over from last season, all known before this season starts."""
    teams: dict[str, tuple[float, float]]   # team -> (attack, defence) prior
    mu_home: float                          # last season's league averages, on the
    mu_away: float                          # same blended-signal scale as the ratings
    relegated: list[str] = field(default_factory=list)


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
        n = range(len(self.grid))
        return max(((i, j) for i in n for j in n), key=lambda ij: self.grid[ij[0]][ij[1]])


def signal(m: Match, side: str, cfg: Config = BASELINE) -> tuple[float, float]:
    """(goal signal, weight) for one side of a match."""
    goals, xg = (m.home_goals, m.home_xg) if side == "h" else (m.away_goals, m.away_xg)
    if xg is None:
        return float(goals), cfg.no_xg_weight
    return cfg.xg_weight * xg + (1 - cfg.xg_weight) * goals, 1.0


def league_averages(matches: list[Match], cfg: Config = BASELINE,
                    prior: tuple[float, float] | None = None) -> tuple[float, float, int]:
    """Home and away average goal signal, anchored to last season.

    mu = (k * mu_prior + n * mu_current) / (k + n), with k = cfg.mu_prior_games and
    n = matches this season. Matches with xG define the scale when any exist, so the
    averages are on the same blended xG/goals scale as the ratings.
    Returns (mu_home, mu_away, n).
    """
    basis = [m for m in matches if m.home_xg is not None] or matches
    n = len(basis)
    cur_h = sum(signal(m, "h", cfg)[0] for m in basis) / n if n else 0.0
    cur_a = sum(signal(m, "a", cfg)[0] for m in basis) / n if n else 0.0
    k = cfg.mu_prior_games if prior else 0
    if n == 0 and not prior:
        return 1.5, 1.2, 0
    if n == 0:
        return prior[0], prior[1], 0
    if k == 0:
        return cur_h, cur_a, n
    return (k * prior[0] + n * cur_h) / (k + n), (k * prior[1] + n * cur_a) / (k + n), n


def fit(matches: list[Match], teams: set[str], cfg: Config = BASELINE,
        prior: SeasonPrior | dict[str, tuple[float, float]] | None = None,
        prior_games: float | None = None) -> Ratings:
    """Solve schedule-adjusted attack/defence ratings (1.0 = league average).

    `prior` may be a SeasonPrior (team ratings + league averages) or a plain
    {team: (attack, defence)} dict. `prior_games` overrides cfg.prior_games.
    """
    w_prior = cfg.prior_games if prior_games is None else prior_games
    if isinstance(prior, SeasonPrior):
        team_prior, mu_prior = prior.teams, (prior.mu_home, prior.mu_away)
    else:
        team_prior, mu_prior = (prior or {}), None
    mu_h, mu_a, _ = league_averages(matches, cfg, mu_prior)

    sig = [(m.home, m.away, *signal(m, "h", cfg), *signal(m, "a", cfg)) for m in matches]
    att = {t: 1.0 for t in teams}
    dfn = {t: 1.0 for t in teams}
    for _ in range(ITERATIONS):
        scored, exp_s, conc, exp_c, n = (defaultdict(float) for _ in range(5))
        for h, a, hv, hw, av, aw in sig:
            scored[h] += hw * hv; exp_s[h] += hw * mu_h * dfn[a]
            conc[h] += aw * av;   exp_c[h] += aw * mu_a * att[a]; n[h] += hw
            scored[a] += aw * av; exp_s[a] += aw * mu_a * dfn[h]
            conc[a] += hw * hv;   exp_c[a] += hw * mu_h * att[h]; n[a] += aw
        new_att, new_dfn = {}, {}
        for t in teams:
            pa, pd = team_prior.get(t, (1.0, 1.0))
            if n[t] == 0:
                new_att[t], new_dfn[t] = pa, pd
                continue
            # The prior behaves like `w_prior` extra games played at the prior rating.
            per_s, per_c = exp_s[t] / n[t], exp_c[t] / n[t]
            new_att[t] = (scored[t] + w_prior * pa * per_s) / (exp_s[t] + w_prior * per_s)
            new_dfn[t] = (conc[t] + w_prior * pd * per_c) / (exp_c[t] + w_prior * per_c)
        # Identification constraint: average attack and average defence are both 1.
        mean_a = sum(new_att.values()) / len(new_att)
        mean_d = sum(new_dfn.values()) / len(new_dfn)
        att = {t: v / mean_a for t, v in new_att.items()}
        dfn = {t: v / mean_d for t, v in new_dfn.items()}
    return Ratings(att, dfn, mu_h, mu_a, dict(team_prior))


def _poisson(k: int, lam: float) -> float:
    return math.exp(-lam) * lam ** k / math.factorial(k)


def expected_goals(home: str, away: str, r: Ratings) -> tuple[float, float]:
    return (r.mu_home * r.attack[home] * r.defence[away],
            r.mu_away * r.attack[away] * r.defence[home])


def scoreline(lh: float, la: float, rho: float, max_goals: int = MAX_GOALS) -> Prediction:
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


def predict(home: str, away: str, r: Ratings, rho: float = BASELINE.rho,
            max_goals: int = MAX_GOALS) -> Prediction:
    return scoreline(*expected_goals(home, away, r), rho, max_goals)


def table_points(matches: list[Match]) -> Counter:
    pts: Counter = Counter()
    for m in matches:
        pts[m.home] += {"H": 3, "D": 1, "A": 0}[m.outcome]
        pts[m.away] += {"H": 0, "D": 1, "A": 3}[m.outcome]
    return pts


def season_prior(last_season: list[Match], this_season_teams: set[str],
                 cfg: Config = BASELINE) -> SeasonPrior:
    """Prior for this season from last season's full-season fit.

    Returning teams keep last season's rating shrunk toward average. Promoted
    teams start from the average of last season's bottom three. League averages
    come from the same fit, so they share the ratings' blended-signal scale.
    """
    last_teams = {m.home for m in last_season} | {m.away for m in last_season}
    r = fit(last_season, last_teams, cfg, prior_games=0)
    pts = table_points(last_season)
    bottom3 = sorted(last_teams, key=lambda t: pts[t])[:3]
    promoted = (sum(r.attack[t] for t in bottom3) / 3, sum(r.defence[t] for t in bottom3) / 3)
    shrink = lambda v: 1 + cfg.prior_shrink * (v - 1)
    teams = {t: (shrink(r.attack[t]), shrink(r.defence[t])) if t in last_teams else promoted
             for t in this_season_teams}
    return SeasonPrior(teams, r.mu_home, r.mu_away, bottom3)
