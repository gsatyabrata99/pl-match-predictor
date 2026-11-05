import math
from dataclasses import replace

import pytest

from predictor import model
from predictor.model import BASELINE, Config, Match, Ratings, SeasonPrior


def flat(teams, mu=1.4):
    return Ratings({t: 1.0 for t in teams}, {t: 1.0 for t in teams}, mu, mu)


def round_robin(strength, start_gw=1):
    """Every team plays every other at home; goals/xG proportional to strength gap."""
    out, gw = [], start_gw
    for h in strength:
        for a in strength:
            if h == a:
                continue
            hx, ax = 1.5 * strength[h] / strength[a], 1.2 * strength[a] / strength[h]
            out.append(Match(gw, h, a, round(hx), round(ax), hx, ax, f"2026-01-{gw:02d}T15:00:00Z"))
            gw += 1
    return out


# ---------------------------------------------------------------- scoreline maths
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


def test_negative_rho_raises_draw_chance():
    r = flat({"A", "B"}, mu=1.2)
    assert model.predict("A", "B", r, rho=-0.1).p_draw > model.predict("A", "B", r, rho=0.0).p_draw


def test_expected_goals_follow_ratings():
    r = Ratings({"A": 1.5, "B": 1.0}, {"A": 1.0, "B": 0.5}, 1.6, 1.2)
    p = model.predict("A", "B", r)
    assert math.isclose(p.home_xg, 1.6 * 1.5 * 0.5)
    assert math.isclose(p.away_xg, 1.2 * 1.0 * 1.0)


@pytest.mark.parametrize("lam", [0.3, 1.5, 3.2])
def test_poisson_mass(lam):
    assert math.isclose(sum(model._poisson(k, lam) for k in range(30)), 1.0, abs_tol=1e-9)


# ---------------------------------------------------------------- ratings
def test_fit_ranks_stronger_teams_higher_and_is_normalised():
    s = {"Strong": 1.6, "Mid": 1.0, "Weak": 0.6, "Mid2": 1.0}
    r = model.fit(round_robin(s), set(s), prior_games=0)
    net = {t: r.attack[t] / r.defence[t] for t in s}
    assert net["Strong"] > net["Mid"] > net["Weak"]
    assert math.isclose(sum(r.attack.values()) / len(s), 1.0, abs_tol=1e-12)
    assert math.isclose(sum(r.defence.values()) / len(s), 1.0, abs_tol=1e-12)


def test_fit_converges():
    s = {"A": 1.6, "B": 1.0, "C": 0.6, "D": 1.2}
    m = round_robin(s)
    a = model.fit(m, set(s), prior_games=0)
    old, model.ITERATIONS = model.ITERATIONS, 200
    try:
        b = model.fit(m, set(s), prior_games=0)
    finally:
        model.ITERATIONS = old
    assert a.attack == pytest.approx(b.attack, abs=1e-9)


def reference_fit(matches, teams, prior=None, prior_games=8, xgw=0.7, noxg=0.5):
    """The v0.1 implementation, verbatim in logic, kept to prove the rewrite is equivalent."""
    def sig(m, side):
        g, x = (m.home_goals, m.home_xg) if side == "h" else (m.away_goals, m.away_xg)
        return (float(g), noxg) if x is None else (xgw * x + (1 - xgw) * g, 1.0)
    prior = prior or {}
    with_xg = [m for m in matches if m.home_xg is not None] or matches
    mu_h = sum(sig(m, "h")[0] for m in with_xg) / len(with_xg)
    mu_a = sum(sig(m, "a")[0] for m in with_xg) / len(with_xg)
    att = {t: 1.0 for t in teams}; dfn = {t: 1.0 for t in teams}
    for _ in range(30):
        na, nd = {}, {}
        for t in teams:
            s = es = c = ec = n = 0.0
            for m in matches:
                (hv, hw), (av, aw) = sig(m, "h"), sig(m, "a")
                if m.home == t:
                    s += hw * hv; es += hw * mu_h * dfn[m.away]; c += aw * av; ec += aw * mu_a * att[m.away]; n += hw
                elif m.away == t:
                    s += aw * av; es += aw * mu_a * dfn[m.home]; c += hw * hv; ec += hw * mu_h * att[m.home]; n += aw
            pa, pd = prior.get(t, (1.0, 1.0))
            if n == 0:
                na[t], nd[t] = pa, pd; continue
            ps, pc = es / n, ec / n
            na[t] = (s + prior_games * pa * ps) / (es + prior_games * ps)
            nd[t] = (c + prior_games * pd * pc) / (ec + prior_games * pc)
        ma, md = sum(na.values()) / len(na), sum(nd.values()) / len(nd)
        att = {t: v / ma for t, v in na.items()}; dfn = {t: v / md for t, v in nd.items()}
    return att, dfn, mu_h, mu_a


def test_rewritten_fit_matches_v01_reference():
    s = {"A": 1.6, "B": 1.0, "C": 0.6, "D": 1.2, "E": 0.9}
    matches = round_robin(s)
    matches[3] = replace(matches[3], home_xg=None, away_xg=None)   # include a goals-only match
    prior = {"A": (1.2, 0.8), "B": (1.0, 1.0), "C": (0.8, 1.2), "D": (1.1, 0.9), "E": (0.9, 1.1)}
    att, dfn, mh, ma = reference_fit(matches, set(s), prior)
    r = model.fit(matches, set(s), BASELINE, prior=prior)
    assert r.attack == pytest.approx(att, abs=1e-12)
    assert r.defence == pytest.approx(dfn, abs=1e-12)
    assert (r.mu_home, r.mu_away) == pytest.approx((mh, ma))


def test_prior_is_used_when_a_team_has_not_played():
    r = model.fit([], {"A", "B"}, prior={"A": (1.2, 0.9), "B": (0.8, 1.1)})
    assert r.attack["A"] > r.attack["B"]


def test_prior_pulls_ratings_toward_it():
    s = {"A": 1.6, "B": 0.6, "C": 1.0}
    m = round_robin(s)
    loose = model.fit(m, set(s), prior_games=0)
    anchored = model.fit(m, set(s), prior={t: (1.0, 1.0) for t in s}, prior_games=50)
    assert abs(anchored.attack["A"] - 1) < abs(loose.attack["A"] - 1)


def test_matches_without_xg_use_goals():
    assert model.signal(Match(1, "A", "B", 3, 0), "h") == (3.0, BASELINE.no_xg_weight)


# ---------------------------------------------------------------- league averages
def two_matches():
    return [Match(1, "A", "B", 2, 0, 1.0, 1.0), Match(2, "B", "A", 1, 1, 2.0, 0.5)]


def test_league_average_formula():
    cfg = Config(xg_weight=0.5, mu_prior_games=6)
    mh, ma, n = model.league_averages(two_matches(), cfg, prior=(1.5, 1.1))
    cur_h = ((0.5 * 1.0 + 0.5 * 2) + (0.5 * 2.0 + 0.5 * 1)) / 2     # blended signal, same scale as ratings
    cur_a = ((0.5 * 1.0 + 0.5 * 0) + (0.5 * 0.5 + 0.5 * 1)) / 2
    assert n == 2
    assert mh == pytest.approx((6 * 1.5 + 2 * cur_h) / 8)
    assert ma == pytest.approx((6 * 1.1 + 2 * cur_a) / 8)


def test_league_average_without_prior_weight_is_current_season():
    cfg = Config(xg_weight=1.0, mu_prior_games=0)
    assert model.league_averages(two_matches(), cfg, prior=(9.0, 9.0))[:2] == pytest.approx((1.5, 0.75))


def test_league_average_before_any_match_is_the_prior():
    assert model.league_averages([], Config(mu_prior_games=100), prior=(1.5, 1.2))[:2] == (1.5, 1.2)


def test_league_average_uses_xg_matches_only_when_available():
    m = two_matches() + [Match(3, "A", "B", 9, 9)]          # a goals-only outlier
    assert model.league_averages(m, Config(xg_weight=1.0))[:2] == pytest.approx((1.5, 0.75))


def test_season_prior_carries_league_averages_on_ratings_scale():
    s = {"A": 1.5, "B": 1.2, "C": 1.0, "D": 0.8, "E": 0.7, "F": 0.6}
    cfg = Config(xg_weight=0.6)
    p = model.season_prior(round_robin(s), set(s) - {"F"} | {"New"}, cfg)
    last = round_robin(s)
    assert p.mu_home == pytest.approx(sum(model.signal(m, "h", cfg)[0] for m in last) / len(last))
    assert set(p.relegated) == {"D", "E", "F"}
    assert p.teams["New"][0] < 1 < p.teams["New"][1]
    assert p.teams["A"][0] > 1


def test_fit_with_season_prior_blends_league_average():
    s = {"A": 1.2, "B": 0.9}
    prior = SeasonPrior({t: (1.0, 1.0) for t in s}, 1.0, 1.0)
    early = model.fit(round_robin(s)[:1], set(s), Config(mu_prior_games=1000), prior=prior)
    assert early.mu_home == pytest.approx(1.0, abs=0.01)


def test_config_round_trips(tmp_path):
    cfg = Config(xg_weight=0.6, rho=-0.1, mu_prior_games=100)
    path = tmp_path / "params.json"
    path.write_text('{"params": %s, "note": "ignored"}' % __import__("json").dumps(cfg.to_dict()))
    assert Config.load(path) == cfg


def test_production_params_are_explicit_and_v01():
    """Guards against the live model changing by accident. Update deliberately with a decision record."""
    from pathlib import Path
    import json
    path = Path(__file__).resolve().parent.parent / "predictor" / "params.json"
    raw = json.loads(path.read_text())
    assert raw["status"] == "production"
    assert set(raw["params"]) == {f for f in Config.__dataclass_fields__}
    assert Config.load(path) == BASELINE


def test_build_requires_params_file(tmp_path, monkeypatch):
    from predictor import build, evaluate
    monkeypatch.setattr(evaluate, "PARAMS", tmp_path / "missing.json")
    with pytest.raises(FileNotFoundError):
        build.active_config()
