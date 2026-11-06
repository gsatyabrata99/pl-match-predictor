import pytest

from predictor import benchmark as bm
from predictor.evaluate import Row

HEADER = "Div,Date,Time,HomeTeam,AwayTeam,FTHG,FTAG,FTR,B365CH,B365CD,B365CA,PSCH,PSCD,PSCA,AvgCH,AvgCD,AvgCA\n"


def csv_bytes(*lines, bom=False):
    text = HEADER + "".join(l + "\n" for l in lines)
    return (b"\xef\xbb\xbf" if bom else b"") + text.encode("latin-1")


def row(season, gw, home, away, hg, ag):
    o = "H" if hg > ag else "A" if hg < ag else "D"
    return Row(season, gw, home, away, o, hg, ag, 1.5, 1.1)


def test_parse_maps_names_and_reads_closing_odds():
    rows = bm.parse_odds(csv_bytes("E0,16/08/2024,20:00,Man United,Tottenham,1,0,H,2.1,3.5,3.6,2.15,3.55,3.7,2.1,3.5,3.6"))
    r = rows[0]
    assert (r.date, r.home, r.away, r.home_goals, r.away_goals) == ("2024-08-16", "Man Utd", "Spurs", 1, 0)
    assert r.odds["pinnacle_closing"] == (2.15, 3.55, 3.7)


def test_parse_handles_bom_two_digit_years_and_missing_odds():
    rows = bm.parse_odds(csv_bytes("E0,16/08/24,20:00,Arsenal,Wolves,2,0,H,1.2,7,15,,,,1.2,7,14", bom=True))
    assert rows[0].date == "2024-08-16"
    assert rows[0].odds["pinnacle_closing"] is None
    assert rows[0].odds["average_closing"] == (1.2, 7.0, 14.0)


def test_unknown_team_is_an_error_not_a_guess():
    with pytest.raises(bm.UnknownTeamError):
        bm.parse_odds(csv_bytes("E0,16/08/2024,20:00,Atlantis FC,Arsenal,0,1,A,5,4,1.6,5,4,1.6,5,4,1.6"))


def test_implied_removes_margin_proportionally():
    p, over = bm.implied((2.0, 3.5, 4.0))
    raw = [1 / 2.0, 1 / 3.5, 1 / 4.0]
    assert sum(p.values()) == pytest.approx(1.0)
    assert over == pytest.approx(sum(raw) - 1)
    assert p["H"] == pytest.approx(raw[0] / sum(raw))


def test_uk_date_uses_london_time():
    assert bm.uk_date("2024-08-16T19:00:00Z") == "2024-08-16"
    assert bm.uk_date("2024-12-31T23:30:00Z") == "2024-12-31"     # GMT in winter
    assert bm.uk_date("2024-07-31T23:30:00Z") == "2024-08-01"     # BST in summer


def test_matching_flags_problems_instead_of_matching_silently():
    odds = bm.parse_odds(csv_bytes(
        "E0,16/08/2024,20:00,Man United,Fulham,1,0,H,2,3.5,4,2,3.5,4,2,3.5,4",       # good
        "E0,17/08/2024,15:00,Arsenal,Wolves,2,0,H,1.2,7,15,1.2,7,15,1.2,7,15",       # date mismatch
        "E0,17/08/2024,15:00,Everton,Brighton,0,3,A,2.5,3.3,2.9,2.5,3.3,2.9,2.5,3.3,2.9",  # score mismatch
        "E0,18/08/2024,16:30,Chelsea,Man City,0,2,A,4,4,1.8,4,4,1.8,4,4,1.8",        # no fixture
    ))
    rows = [row("2024-25", 1, "Man Utd", "Fulham", 1, 0), row("2024-25", 1, "Arsenal", "Wolves", 2, 0),
            row("2024-25", 1, "Everton", "Brighton", 0, 2), row("2024-25", 1, "Spurs", "Leicester", 1, 1)]
    kick = {("Man Utd", "Fulham"): "2024-08-16T19:00:00Z", ("Arsenal", "Wolves"): "2024-08-18T14:00:00Z",
            ("Everton", "Brighton"): "2024-08-17T14:00:00Z", ("Spurs", "Leicester"): "2024-08-19T19:00:00Z"}
    rep = bm.match(rows, kick, odds)
    assert [(r.home, o.home) for r, o in rep.matched] == [("Man Utd", "Man Utd")]
    assert len(rep.date_mismatches) == 1 and "Arsenal" in rep.date_mismatches[0]
    assert len(rep.score_mismatches) == 1 and "Everton" in rep.score_mismatches[0]
    assert rep.unmatched_fixtures == ["2024-25 GW1 Spurs v Leicester"]
    assert any("Chelsea v Man City" in u for u in rep.unmatched_odds)


def test_duplicate_odds_rows_are_ambiguous():
    line = "E0,16/08/2024,20:00,Man United,Fulham,1,0,H,2,3.5,4,2,3.5,4,2,3.5,4"
    rep = bm.match([row("2024-25", 1, "Man Utd", "Fulham", 1, 0)], {("Man Utd", "Fulham"): "2024-08-16T19:00:00Z"},
                   bm.parse_odds(csv_bytes(line, line)))
    assert rep.ambiguous and not rep.matched


def test_compare_identical_probabilities_has_zero_difference():
    rows = [row("s", 1, "A", "B", 1, 0), row("s", 1, "C", "D", 0, 0), row("s", 2, "A", "C", 0, 2)]
    p = [{"H": .5, "D": .3, "A": .2}, {"H": .4, "D": .35, "A": .25}, {"H": .45, "D": .3, "A": .25}]
    c = bm.compare(rows, p, p)
    assert c["log_loss_model_minus_market"]["mean"] == pytest.approx(0)
    assert c["disagreement"]["slope_model_on_market"] == pytest.approx(1)
    assert c["disagreement"]["favourite_agreement"] == 1
