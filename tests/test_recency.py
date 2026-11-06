import pytest

from predictor import evaluate, model, recency
from predictor.model import BASELINE

from .test_evaluate import LAST, TEAMS, THIS


def test_decay_weights():
    assert recency.decay(0, 30) == 1.0
    assert recency.decay(30, 30) == pytest.approx(0.5)
    assert recency.decay(90, 30) == pytest.approx(0.125)
    assert recency.decay(500, None) == 1.0


def test_no_decay_is_identical_to_production_walk_forward():
    a = evaluate.walk_forward("x", THIS, LAST, BASELINE)
    b = recency.walk_forward("x", THIS, LAST, BASELINE, None)
    assert [(r.lh, r.la) for r in a] == pytest.approx([(r.lh, r.la) for r in b], abs=1e-12)


def test_uniform_decay_changes_nothing_because_prior_ratio_is_preserved():
    """If every match has the same age, decay scales data and prior alike: ratings must not move.
    This is the registered prior-strength rule; a fixed 8-game prior would fail it."""
    teams = set(TEAMS)
    prior = model.season_prior(LAST, teams, BASELINE)
    same_time = [m.__class__(**{**m.__dict__, "kickoff": "2025-03-01T15:00:00Z"}) for m in THIS[:10]]
    base = recency.fit_decayed(same_time, teams, BASELINE, prior, "2025-04-01T15:00:00Z", None)
    dec = recency.fit_decayed(same_time, teams, BASELINE, prior, "2025-04-01T15:00:00Z", 30)
    assert dec.attack == pytest.approx(base.attack, abs=1e-12)
    assert dec.defence == pytest.approx(base.defence, abs=1e-12)


def test_short_half_life_favours_recent_form():
    """A team that was poor early and strong recently rates higher with decay."""
    from predictor.model import Match
    teams = {"A", "B", "C", "D"}
    prior = model.season_prior(LAST, teams, BASELINE)
    early = [Match(1, "A", "B", 0, 3, 0.2, 2.5, "2025-01-01T15:00:00Z"),
             Match(1, "C", "D", 1, 1, 1.0, 1.0, "2025-01-01T15:00:00Z")]
    late = [Match(2, "A", "C", 3, 0, 2.5, 0.2, "2025-03-01T15:00:00Z"),
            Match(2, "B", "D", 1, 1, 1.0, 1.0, "2025-03-01T15:00:00Z")]
    cut = "2025-03-05T15:00:00Z"
    flat = recency.fit_decayed(early + late, teams, BASELINE, prior, cut, None)
    fast = recency.fit_decayed(early + late, teams, BASELINE, prior, cut, 14)
    assert fast.attack["A"] > flat.attack["A"]


def test_draw_calibration_bins_cover_all_matches():
    rows = evaluate.walk_forward("x", THIS, LAST, BASELINE)
    cal = recency.draw_calibration(rows, evaluate.probabilities(rows, BASELINE.rho))
    assert sum(b["n"] for b in cal) == len(rows)
