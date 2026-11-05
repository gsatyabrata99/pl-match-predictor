import pytest

from predictor import sources


def fpl_payload():
    bootstrap = {
        "teams": [{"id": 1, "name": "Arsenal", "short_name": "ARS"},
                  {"id": 2, "name": "Spurs", "short_name": "TOT"},
                  {"id": 3, "name": "Fulham", "short_name": "FUL"}],
        "elements": [{"id": 10, "team": 1}, {"id": 11, "team": 1}, {"id": 20, "team": 2}, {"id": 30, "team": 3}],
    }
    fixtures = [
        {"id": 100, "event": 1, "kickoff_time": "2026-08-22T14:00:00Z", "team_h": 1, "team_a": 2,
         "team_h_score": 2, "team_a_score": 1, "finished": True},
        {"id": 101, "event": 1, "kickoff_time": "2026-08-25T19:00:00Z", "team_h": 3, "team_a": 1,
         "team_h_score": 0, "team_a_score": 0, "finished": True},
        {"id": 102, "event": 2, "kickoff_time": "2026-08-30T14:00:00Z", "team_h": 2, "team_a": 3,
         "team_h_score": None, "team_a_score": None, "finished": False},
    ]
    minutes = lambda m: [{"identifier": "minutes", "value": m}]
    live = {1: {"elements": [
        # Arsenal player in a double gameweek: 90 + 30 minutes, 0.8 xG -> 0.6 / 0.2
        {"id": 10, "stats": {"expected_goals": "0.80"},
         "explain": [{"fixture": 100, "stats": minutes(90)}, {"fixture": 101, "stats": minutes(30)}]},
        {"id": 11, "stats": {"expected_goals": "1.00"}, "explain": [{"fixture": 100, "stats": minutes(90)}]},
        {"id": 20, "stats": {"expected_goals": "0.45"}, "explain": [{"fixture": 100, "stats": minutes(90)}]},
        {"id": 30, "stats": {"expected_goals": "0.30"}, "explain": [{"fixture": 101, "stats": minutes(90)}]},
    ]}}
    return bootstrap, fixtures, live


def test_parse_fpl_sums_xg_per_fixture_and_splits_double_gameweeks():
    s = sources.parse_fpl(*fpl_payload())
    assert s.teams == {"Arsenal": "ARS", "Spurs": "TOT", "Fulham": "FUL"}
    assert s.xg["100"] == pytest.approx((1.6, 0.45))
    assert s.xg["101"] == pytest.approx((0.30, 0.2))
    matches = s.matches()
    assert [(m.home, m.away, m.home_goals, m.away_goals) for m in matches] == [
        ("Arsenal", "Spurs", 2, 1), ("Fulham", "Arsenal", 0, 0)]
    assert len(s.fixtures) == 3


def test_parse_mirror():
    teams = [{"id": "1", "name": "Arsenal", "short_name": "ARS"}, {"id": "2", "name": "Spurs", "short_name": "TOT"}]
    fixtures = [{"id": "5", "event": "1", "kickoff_time": "2026-08-22T14:00:00Z", "team_h": "1", "team_a": "2",
                 "team_h_score": "3.0", "team_a_score": "1.0", "finished": "True"}]
    gws = [{"fixture": "5", "team": "Arsenal", "expected_goals": "1.2"},
           {"fixture": "5", "team": "Arsenal", "expected_goals": "0.3"},
           {"fixture": "5", "team": "Spurs", "expected_goals": "0.7"}]
    s = sources.parse_mirror(teams, fixtures, gws)
    m = s.matches()[0]
    assert (m.home_goals, m.away_goals) == (3, 1)
    assert (m.home_xg, m.away_xg) == pytest.approx((1.5, 0.7))


def test_manual_results_fill_only_missing_scores(tmp_path):
    s = sources.parse_fpl(*fpl_payload())
    csv = tmp_path / "manual.csv"
    csv.write_text("gw,home,home_goals,away_goals,away\n1,Arsenal,9,9,Spurs\n2,Spurs,1,2,Fulham\n")
    assert sources.apply_manual_results(s, csv) == 1
    scores = {(m.home, m.away): (m.home_goals, m.away_goals) for m in s.matches()}
    assert scores[("Arsenal", "Spurs")] == (2, 1)      # source wins over a stale override
    assert scores[("Spurs", "Fulham")] == (1, 2)


def test_manual_results_reject_unknown_fixture(tmp_path):
    s = sources.parse_fpl(*fpl_payload())
    csv = tmp_path / "manual.csv"
    csv.write_text("gw,home,home_goals,away_goals,away\n1,Arsenal,1,0,Liverpool\n")
    with pytest.raises(ValueError):
        sources.apply_manual_results(s, csv)


def test_all_zero_xg_is_treated_as_missing():
    teams = [{"id": "1", "name": "Arsenal", "short_name": "ARS"}, {"id": "2", "name": "Spurs", "short_name": "TOT"}]
    fixtures = [{"id": "5", "event": "1", "kickoff_time": "2022-08-06T14:00:00Z", "team_h": "1", "team_a": "2",
                 "team_h_score": "2", "team_a_score": "0", "finished": "True"}]
    gws = [{"fixture": "5", "team": "Arsenal", "expected_goals": "0"},
           {"fixture": "5", "team": "Spurs", "expected_goals": "0.0"}]
    m = sources.parse_mirror(teams, fixtures, gws).matches()[0]
    assert m.home_xg is None and m.away_xg is None


def test_seasons_without_an_xg_column():
    teams = [{"id": "1", "name": "Arsenal", "short_name": "ARS"}, {"id": "2", "name": "Spurs", "short_name": "TOT"}]
    fixtures = [{"id": "5", "event": "1", "kickoff_time": "2021-08-14T14:00:00Z", "team_h": "1", "team_a": "2",
                 "team_h_score": "1", "team_a_score": "1", "finished": "True"}]
    m = sources.parse_mirror(teams, fixtures, [{"fixture": "5", "team": "Arsenal"}]).matches()[0]
    assert (m.home_goals, m.home_xg) == (1, None)
