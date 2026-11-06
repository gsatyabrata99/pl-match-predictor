import json
from datetime import datetime, timezone

import pytest

from predictor import benchmark, ledger, prospective

NOW = datetime(2026, 11, 5, 23, 0, tzinfo=timezone.utc)
PARAMS = {"prior_games": 8, "rho": -0.08}


def fc(fid, kickoff, ph=0.5, pd=0.3, pa=0.2, home="Everton", away="Coventry City"):
    return dict(fixture_id=fid, gw=10, kickoff=kickoff, home=home, away=away, lh=1.6, la=1.0, ph=ph, pd=pd, pa=pa)


def test_records_only_upcoming_fixtures_inside_window(tmp_path):
    path = tmp_path / "p.jsonl"
    n = ledger.record(path, "2026-27", NOW, "abc", PARAMS, {}, [
        fc(1, "2026-11-06T20:00:00Z"),           # tomorrow: recorded
        fc(2, "2026-11-05T20:00:00Z"),           # already kicked off: never recorded
        fc(3, "2026-11-21T12:30:00Z"),           # beyond the 7-day window
    ])
    recs = ledger.read(path)
    assert n == 1 and [r["fixture_id"] for r in recs] == ["1"]
    assert recs[0]["predicted_at"] == "2026-11-05T23:00:00Z" and recs[0]["model_version"] == "abc"
    assert not ledger.check_records(recs)


def test_unchanged_forecasts_are_not_duplicated_but_changes_are_appended(tmp_path):
    path = tmp_path / "p.jsonl"
    ledger.record(path, "2026-27", NOW, "abc", PARAMS, {}, [fc(1, "2026-11-06T20:00:00Z")])
    later = datetime(2026, 11, 6, 6, 17, tzinfo=timezone.utc)
    assert ledger.record(path, "2026-27", later, "abc", PARAMS, {}, [fc(1, "2026-11-06T20:00:00Z")]) == 0
    assert ledger.record(path, "2026-27", later, "abc", PARAMS, {}, [fc(1, "2026-11-06T20:00:00Z", ph=0.52, pd=0.29, pa=0.19)]) == 1
    before = path.read_text()
    ledger.record(path, "2026-27", later, "def", PARAMS, {}, [fc(1, "2026-11-06T20:00:00Z", ph=0.52, pd=0.29, pa=0.19)])
    assert path.read_text().startswith(before)          # appended, never rewritten
    assert ledger.latest_before_kickoff(ledger.read(path))["1"]["model_version"] == "def"


def test_latest_before_kickoff_ignores_anything_after_kickoff():
    recs = [dict(fixture_id="1", kickoff="2026-11-06T20:00:00Z", predicted_at="2026-11-06T06:17:00Z", v=1),
            dict(fixture_id="1", kickoff="2026-11-06T20:00:00Z", predicted_at="2026-11-06T21:00:00Z", v=2)]
    assert ledger.latest_before_kickoff(recs)["1"]["v"] == 1


def test_verification_catches_rewrites_and_late_forecasts():
    assert ledger.check_append_only("a\nb\n", "a\nb\nc\n") == []
    assert ledger.check_append_only("a\nb\n", "a\nX\nc\n")
    late = {k: None for k in ledger.REQUIRED} | {"predicted_at": "2026-11-06T21:00:00Z",
                                                 "kickoff": "2026-11-06T20:00:00Z",
                                                 "probabilities": {"H": .5, "D": .3, "A": .2}}
    assert any("not before kickoff" in p for p in ledger.check_records([late]))


ODDS = ("Div,Date,Time,HomeTeam,AwayTeam,FTHG,FTAG,FTR,B365CH,B365CD,B365CA,AvgCH,AvgCD,AvgCA\n"
        "E0,06/11/2026,20:00,Everton,Coventry,2,1,H,1.9,3.6,4.2,1.95,3.6,4.1\n"
        "E0,07/11/2026,12:30,Leeds,Tottenham,,,,,,,,,\n")


def test_market_recorder_appends_finished_matches_once(tmp_path):
    path = tmp_path / "m.jsonl"
    raw = ODDS.encode("latin-1")
    assert prospective.record_market("2026-27", raw, "u", NOW, path) == 1
    assert prospective.record_market("2026-27", raw, "u", NOW, path) == 0
    rec = ledger.read(path)[0]
    assert rec["home"] == "Everton" and rec["away"] == "Coventry City" and rec["result"] == [2, 1]
    assert sum(rec["average_closing_implied"].values()) == pytest.approx(1)


def test_score_joins_forecast_to_market_by_canonical_names_and_uk_date(tmp_path):
    preds = tmp_path / "p.jsonl"; market = tmp_path / "m.jsonl"
    ledger.record(preds, "2026-27", NOW, "abc", PARAMS, {}, [
        fc(1, "2026-11-06T20:00:00Z"),
        fc(2, "2026-11-07T12:30:00Z", home="Ipswich Town", away="Hull City")])
    raw = (ODDS + "E0,07/11/2026,12:30,Ipswich,Hull,0,0,D,2.4,3.3,3.0,2.4,3.3,3.0\n").encode("latin-1")
    prospective.record_market("2026-27", raw, "u", NOW, market)
    out = prospective.score(ledger.read(preds), ledger.read(market))
    assert out["scored"] == 2 and out["lead_time_hours"]["min"] == pytest.approx(21.0)
    assert out["comparison"]["model"]["n"] == 2


def test_canonical_names():
    assert benchmark.canon("Ipswich Town") == benchmark.canon("Ipswich") == "Ipswich"
    assert prospective.season_code("2026-27") == "2627"
