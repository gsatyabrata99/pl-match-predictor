import math

import pytest

from predictor import fpl
from predictor.fpl import GW, Fixture, Profile, Ratings

R = Ratings({"A": 1.3, "B": 0.8, "C": 1.0}, {"A": 0.8, "B": 1.2, "C": 1.0}, 1.6, 1.3, -0.08)
SC = fpl.DEFAULT_SCORING


def test_lam_and_neutral():
    assert R.lam("A", "B", True) == pytest.approx((1.6 * 1.3 * 1.2, 1.3 * 0.8 * 0.8))
    assert R.lam("A", "B", False) == pytest.approx((1.3 * 1.3 * 1.2, 1.6 * 0.8 * 0.8))
    f, a = R.neutral("A")
    assert f == pytest.approx(sum(R.lam("A", o, h)[0] for o in "BC" for h in (True, False)) / 4)


def test_conceded_matches_scoreline_grid_from_both_sides():
    from predictor import model
    g = model.scoreline(*R.lam("A", "B", True), R.rho).grid
    p_cs_home, _ = R.conceded("A", "B", True)      # A at home keeps a clean sheet = B scores 0
    p_cs_away, e_half = R.conceded("B", "A", False)  # B away keeps a clean sheet = A scores 0
    assert p_cs_home == pytest.approx(sum(row[0] for row in g))
    assert p_cs_away == pytest.approx(sum(g[0]))
    assert e_half == pytest.approx(sum(sum(g[i]) * (i // 2) for i in range(len(g))))


def test_profile_minutes_use_only_team_gameweeks_and_shrink_rates():
    hist = [GW(1, 90, 0.5, 0.1, 0, 1, 0, 4, 8), GW(2, 0, 0, 0, 0, 0, 0, 0, 0), GW(4, 30, 0.2, 0, 0, 0, 0, 1, 1)]
    priors = {"FWD": {"xg": 0.004, "xa": 0.002, "saves": 0, "bonus": 0.005, "yellow": 0.001, "defcon_p": 0.05}}
    pr = fpl.profile(hist, "FWD", [1, 2, 4], priors)          # GW3 was a blank: not counted as missed
    assert pr.p_play == pytest.approx(2 / 3) and pr.p60 == pytest.approx(1 / 3) and pr.mins_if_play == 60
    assert pr.xg == pytest.approx((0.7 + fpl.RATE_PRIOR_MINUTES * 0.004) / (120 + fpl.RATE_PRIOR_MINUTES))
    assert pr.defcon_p == pytest.approx((0 + fpl.DEFCON_PRIOR_APPS * 0.05) / (1 + fpl.DEFCON_PRIOR_APPS))


def test_defcon_threshold_by_position():
    hist = [GW(1, 90, 0, 0, 0, 0, 0, 10, 4), GW(2, 90, 0, 0, 0, 0, 0, 11, 2)]
    priors = {p: {"xg": 0, "xa": 0, "saves": 0, "bonus": 0, "yellow": 0, "defcon_p": 0} for p in ("DEF", "MID")}
    assert fpl.profile(hist, "DEF", [1, 2], priors).defcon_p == pytest.approx(2 / (2 + fpl.DEFCON_PRIOR_APPS))
    assert fpl.profile(hist, "MID", [1, 2], priors).defcon_p == 0     # 12 needed for midfielders


def nailed(pos, **rates):
    base = dict(xg=0.0, xa=0.0, saves=0.0, bonus=0.0, yellow=0.0, defcon_p=0.0)
    base.update(rates)
    return Profile(pos, 1.0, 1.0, 90.0, games=5, **base)


def test_fixture_points_components():
    fx = Fixture(11, "A", "B", True, "")
    c = fpl.fixture_points(nailed("DEF", xg=0.1 / 90, defcon_p=0.5), fx, R, SC)
    lam_for, _ = R.lam("A", "B", True)
    m_att = lam_for / R.neutral("A")[0]
    assert c["appearance"] == 2
    assert c["goals"] == pytest.approx(0.1 * m_att * 6)
    assert c["clean_sheet"] == pytest.approx(R.conceded("A", "B", True)[0] * 4)
    assert c["defcon"] == pytest.approx(0.5 * 2)
    assert c["total"] == pytest.approx(sum(v for k, v in c.items() if k not in ("total", "p_goal", "p_return")))


def test_unavailable_player_scores_zero():
    c = fpl.fixture_points(nailed("FWD", xg=0.5 / 90), Fixture(11, "A", "B", True, ""), R, SC, avail=0.0)
    assert c["total"] == 0 and c["p_goal"] == 0


def test_stronger_fixture_raises_attack_and_clean_sheets():
    pr = nailed("DEF", xg=0.1 / 90)
    easy = fpl.fixture_points(pr, Fixture(11, "A", "B", True, ""), R, SC)
    hard = fpl.fixture_points(pr, Fixture(11, "B", "A", False, ""), R, SC)
    assert easy["goals"] / pr.xg > hard["goals"] / pr.xg and easy["clean_sheet"] > hard["clean_sheet"]


def test_availability():
    assert fpl.availability("a", None, 0) == 1 and fpl.availability("d", 75, 0) == 0.75
    assert fpl.availability("i", 0, 0) == 0 and fpl.availability("i", 0, 1) == 0.5 and fpl.availability("i", 0, 2) == 1
    assert fpl.availability("u", 0, 3) == 0


def test_scoring_reads_api_and_falls_back():
    sc = fpl.scoring_from_api({"game_config": {"scoring": {"goals_scored": {"GKP": 10, "DEF": 6, "MID": 5, "FWD": 4},
                                                            "assists": 3, "long_play": 2}}})
    assert sc["goals_scored"]["MID"] == 5 and sc["assists"] == 3 and sc["clean_sheets"] == SC["clean_sheets"]
    assert fpl.scoring_from_api({}) == SC
