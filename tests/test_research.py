import pytest

from predictor import research as R
from predictor.evaluate import Row

ODDS = (1.5, 4.2, 7.0)


@pytest.mark.parametrize("method", list(R.METHODS))
def test_margin_methods_return_probabilities(method):
    p = R.METHODS[method](ODDS)
    assert sum(p.values()) == pytest.approx(1)
    assert p["H"] > p["D"] > p["A"]


def test_shin_and_power_shade_longshots_more_than_proportional():
    prop, shin, power = (R.METHODS[m](ODDS) for m in ("proportional", "shin", "power"))
    assert shin["A"] < prop["A"] and power["A"] < prop["A"]
    assert shin["H"] > prop["H"] and power["H"] > prop["H"]


def test_no_margin_means_all_methods_agree():
    fair = (2.0, 4.0, 4.0)        # implied probabilities already sum to 1
    for m in R.METHODS.values():
        assert m(fair) == pytest.approx({"H": .5, "D": .25, "A": .25}, abs=1e-6)


def test_temperature_scaling():
    p = {"H": .5, "D": .3, "A": .2}
    assert R.temper(p, 1.0) == pytest.approx(p)
    sharp, flat = R.temper(p, 0.5), R.temper(p, 2.0)
    assert sharp["H"] > p["H"] > flat["H"]
    assert max(sharp, key=sharp.get) == max(flat, key=flat.get) == "H"   # ordering preserved


def test_fit_temperature_recovers_sharpening_when_model_is_too_flat():
    rows = [Row("s", 1, "A", "B", "H", 1, 0, 1.5, 1.0)] * 70 + [Row("s", 1, "A", "B", "A", 0, 1, 1.5, 1.0)] * 30
    probs = [{"H": .55, "D": .25, "A": .20}] * 100
    assert R.fit_temperature(rows, probs) < 1
