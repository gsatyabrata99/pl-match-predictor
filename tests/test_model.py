import math

import pytest

from predictor import model
from predictor.model import Match, Ratings


def flat(teams, mu=1.4):
    return Ratings({t: 1.0 for t in teams}, {t: 1.0 for t in teams}, mu, mu)


def test_grid_is_a_probability_distribution():
    r = Ratings({"A": 1.3, "B": 0.8}, {"A": 0.9, "B": 1.2}, 1.6, 1.3)
    p = model.predict("A", "B", r)
    assert math.isclose(sum(map(sum, p.grid)), 1.0, abs_tol=1e-9)
    assert math.isclose(p.p_home + p.p_draw + p.p_away, 1.0, abs_tol=1e-9)
    assert all(v >= 0 for row in p.grid for v in row)


def test_equal_teams_with_no_home_edge_are_symmetric():
    p = model.predict("A", "B", flat({"A", "B"}))
    assert math.isclose(p.p_home, p.p_away, abs_tol=1e-9)
    assert p.most_likely_score in {(0, 0), (1, 1)}


def test_dixon_coles_raises_draw_chance():
    r = flat({"A", "B"}, mu=1.2)
    plain = model.predict("A", "B", r, rho=0.0)
    adjusted = model.predict("A", "B", r, rho=model.RHO)
    assert adjusted.p_draw > plain.p_draw


def test_expected_goals_follow_ratings():
    r = Ratings({"A": 1.5, "B": 1.0}, {"A": 1.0, "B": 0.5}, 1.6, 1.2)
    p = model.predict("A", "B", r)
    assert math.isclose(p.home_xg, 1.6 * 1.5 * 0.5)
    assert math.isclose(p.away_xg, 1.2 * 1.0 * 1.0)


def round_robin(strength):
    """Every team plays every other at home; goals/xG proportional to strength gap."""
    out, gw = [], 1
    for h in strength:
        for a in strength:
            if h == a:
                continue
            hg = round(1.5 * strength[h] / strength[a])
            ag = round(1.2 * strength[a] / strength[h])
            out.append(Match(gw, h, a, hg, ag, 1.5 * strength[h] / strength[a], 1.2 * strength[a] / strength[h]))
            gw += 1
    return out


def test_fit_ranks_stronger_teams_higher():
    s = {"Strong": 1.6, "Mid": 1.0, "Weak": 0.6, "Mid2": 1.0}
    r = model.fit(round_robin(s), set(s), prior_games=0)
    net = {t: r.attack[t] / r.defence[t] for t in s}
    assert net["Strong"] > net["Mid"] > net["Weak"]
    assert math.isclose(sum(r.attack.values()) / len(s), 1.0, abs_tol=1e-9)


def test_prior_is_used_when_a_team_has_not_played():
    r = model.fit([], {"A", "B"}, prior={"A": (1.2, 0.9), "B": (0.8, 1.1)})
    assert r.attack["A"] > r.attack["B"]


def test_prior_pulls_ratings_toward_it():
    s = {"A": 1.6, "B": 0.6, "C": 1.0}
    matches = round_robin(s)
    loose = model.fit(matches, set(s), prior_games=0)
    anchored = model.fit(matches, set(s), prior={t: (1.0, 1.0) for t in s}, prior_games=50)
    assert abs(anchored.attack["A"] - 1) < abs(loose.attack["A"] - 1)


def test_matches_without_xg_use_goals():
    m = Match(1, "A", "B", 3, 0)
    assert model._signal(m, "h") == (3.0, model.NO_XG_WEIGHT)


def test_backtest_reports_metrics():
    s = {"A": 1.5, "B": 1.0, "C": 0.7, "D": 1.1}
    bt = model.backtest(round_robin(s), start_gw=4)
    assert bt["n"] > 0
    assert 0 <= bt["accuracy"] <= 1
    assert bt["brier"] >= 0


def test_season_prior_gives_promoted_teams_bottom_three_average():
    s = {"A": 1.5, "B": 1.2, "C": 1.0, "D": 0.8, "E": 0.7, "F": 0.6}
    prior, bottom3 = model.season_prior(round_robin(s), set(s) - {"F"} | {"New"})
    assert set(bottom3) == {"D", "E", "F"}
    assert prior["New"][0] < 1 < prior["New"][1]
    assert prior["A"][0] > 1


@pytest.mark.parametrize("lam", [0.3, 1.5, 3.2])
def test_poisson_mass(lam):
    assert math.isclose(sum(model._poisson(k, lam) for k in range(30)), 1.0, abs_tol=1e-9)
