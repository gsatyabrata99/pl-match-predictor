import pytest

from predictor import lineup
from predictor.lineup import Contributions, SeasonData, TeamMatch


def data(rows, pos):
    return SeasonData({}, {}, sorted(rows), pos)


POS = {i: ("GKP" if i in (1, 21) else "DEF" if i in range(2, 6) or i in range(22, 26) else "FWD") for i in range(1, 30)}


def tm(fid, kick, starters, minutes=None):
    return TeamMatch(fid, kick, minutes or {p: 90 for p in starters}, set(starters))


def test_contributions_use_only_earlier_rows_and_shrink():
    rows = [("2025-01-01", 6, "FWD", 90, 0.9), ("2025-02-01", 6, "FWD", 90, 9.0), ("2025-01-01", 7, "FWD", 90, 0.1)]
    c = Contributions(data(rows, POS))
    c.advance("2025-01-15")
    rate = 1.0 / 180
    assert c.c(6) == pytest.approx((0.9 + 450 * rate) / (90 + 450) * 90)   # the February row is not visible yet
    c.advance("2025-03-01")
    assert c.c(6) > 1.0


def test_usual_xi_uses_last_five_matches_and_breaks_ties_by_id():
    prev = [tm(str(i), f"2025-01-{i:02d}", range(1, 12)) for i in range(1, 7)]
    prev.append(tm("7", "2025-01-07", list(range(1, 11)) + [12]))
    assert lineup.usual(prev, 11) == list(range(1, 12))       # 11 played 4 of the last 5, 12 only 1
    assert lineup.usual(prev, 1, lambda p: POS[p] == "GKP") == [1]


def side_for(starters, prev_starters=range(1, 12), rows=None):
    rows = rows or [("2025-01-01", p, POS[p], 90, 0.5 if POS[p] == "FWD" else 0.05) for p in range(1, 15)]
    c = Contributions(data(rows, POS)); c.advance("2025-02-01")
    prev = [tm("1", "2025-01-01", prev_starters)]
    return lineup.side(tm("2", "2025-02-02", starters), prev, c)


def test_full_strength_lineup_has_factor_one():
    assert side_for(range(1, 12)).L == pytest.approx(1.0)


def test_missing_forwards_lower_the_factor_and_defence_flag():
    s = side_for([1, 2, 3, 4, 5, 6, 7, 8, 9, 12, 13])             # same shape, two regulars swapped
    assert s.L == pytest.approx(1.0)                               # equal-quality replacements
    weak = side_for(list(range(1, 9)) + [12, 13, 14],
                    rows=[("2025-01-01", p, POS[p], 1800, 12.0 if p in (9, 10, 11) else 1.0) for p in range(1, 15)])
    assert weak.L < 0.8 and not weak.flagged                       # forwards out, back line intact
    gk_out = side_for([21] + list(range(2, 12)))
    assert gk_out.flagged


def test_cap_and_exclusions():
    rows = [("2025-01-01", p, POS[p], 1800, 0.2) for p in range(1, 12)] + [("2025-01-01", p, POS[p], 1800, 100.0) for p in (12, 13, 14)]
    s = side_for(list(range(1, 9)) + [12, 13, 14], rows=rows)
    assert s.L == lineup.CAP[1] and s.capped
    c = Contributions(data([], POS))
    assert lineup.side(tm("2", "2025-02-02", range(1, 12)), [], c).status == "no_history"
    assert side_for(range(1, 11)).status == "not_11_starters"


def test_ratio_ci_difference():
    a, b = [(1.0, 1.0)] * 20, [(1.2, 1.0)] * 20
    ra, rb, d, lo, hi = lineup.ratio_ci(a, b)
    assert (ra, rb) == pytest.approx((1.0, 1.2)) and d == pytest.approx(0.2) and lo == pytest.approx(0.2)
