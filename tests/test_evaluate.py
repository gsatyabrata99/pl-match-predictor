"""Leakage and evaluation-harness tests."""
from dataclasses import replace

import pytest

from predictor import evaluate as ev
from predictor.model import BASELINE, Config, Match

TEAMS = ["A", "B", "C", "D"]


def season(seed_goals, start_day=1):
    """Double round robin, one match per gameweek-day, deterministic goals."""
    out, gw = [], 1
    pairs = [(h, a) for h in TEAMS for a in TEAMS if h != a]
    for i, (h, a) in enumerate(pairs):
        hg, ag = seed_goals[i % len(seed_goals)]
        out.append(Match(gw, h, a, hg, ag, hg + 0.3, ag + 0.2, f"2025-{1 + i // 28:02d}-{1 + i % 28:02d}T15:00:00Z"))
        if i % 2:
            gw += 1
    return out


LAST = season([(2, 0), (1, 1), (0, 1), (3, 2)])
THIS = season([(1, 0), (2, 2), (0, 0), (1, 3), (2, 1)])


def test_predictions_ignore_future_results():
    """Changing results from gameweek g onward must not change any prediction before g."""
    cfg = Config(mu_prior_games=50)
    rows = ev.walk_forward("x", THIS, LAST, cfg)
    cut = 4
    tampered = [replace(m, home_goals=9, away_goals=0, home_xg=7.0, away_xg=0.1) if m.gw >= cut else m
                for m in THIS]
    rows2 = ev.walk_forward("x", tampered, LAST, cfg)
    for a, b in zip(rows, rows2):
        if a.gw < cut:
            assert (a.lh, a.la) == (b.lh, b.la)
    assert any((a.lh, a.la) != (b.lh, b.la) for a, b in zip(rows, rows2) if a.gw > cut)


def test_same_gameweek_results_are_not_used():
    """A match is predicted only from matches that kicked off before its gameweek began."""
    cfg = BASELINE
    rows = ev.walk_forward("x", THIS, LAST, cfg)
    gw2 = [m for m in THIS if m.gw == 2]
    tampered = [replace(m, home_goals=8, home_xg=6.0) if m is gw2[0] else m for m in THIS]
    rows2 = ev.walk_forward("x", tampered, LAST, cfg)
    for a, b in zip(rows, rows2):
        if a.gw <= 2:
            assert (a.lh, a.la) == (b.lh, b.la)


def test_first_gameweek_uses_only_the_prior():
    from predictor import model
    cfg = Config(mu_prior_games=10)
    rows = ev.walk_forward("x", THIS, LAST, cfg)
    prior = model.season_prior(LAST, set(TEAMS), cfg)
    r0 = model.fit([], set(TEAMS), cfg, prior=prior)
    for r in (r for r in rows if r.gw == 1):
        assert (r.lh, r.la) == pytest.approx(model.expected_goals(r.home, r.away, r0))
    assert (r0.mu_home, r0.mu_away) == (prior.mu_home, prior.mu_away)


def test_test_seasons_are_sealed():
    with pytest.raises(ev.SealedSeasonError):
        ev.guard(["2023-24", "2024-25"], final=False)
    ev.guard(["2024-25"], final=True)
    ev.guard(list(ev.DEV_SEASONS), final=False)
    assert not set(ev.DEV_SEASONS) & set(ev.TEST_SEASONS)


def test_tune_refuses_test_seasons():
    with pytest.raises(ev.SealedSeasonError):
        ev.tune({}, seasons=("2025-26",), progress=False)


def test_metrics():
    rows = ev.walk_forward("x", THIS, LAST, BASELINE)
    m = ev.metrics(rows, ev.probabilities(rows, BASELINE.rho))
    assert m["n"] == len(THIS)
    assert 0 < m["log_loss"] and 0 <= m["brier"] <= 2 and 0 <= m["accuracy"] <= 1
    assert sum(c["n"] for c in m["calibration"]) == 3 * len(THIS)


def test_paired_ci_brackets_a_clear_improvement():
    mean, lo, hi = ev.paired_ci([1.0] * 50, [0.9] * 50)
    assert mean == pytest.approx(-0.1) and lo == pytest.approx(-0.1) and hi == pytest.approx(-0.1)


def test_previous_season():
    assert ev.previous_season("2023-24") == "2022-23"
