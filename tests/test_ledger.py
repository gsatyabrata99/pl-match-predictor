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


DATA = {"source": "fpl", "data_sha256": "aaaa"}


def test_new_commit_alone_does_not_duplicate_a_forecast(tmp_path):
    """The GW10 bug: every Action data commit changed the hash and re-recorded everything."""
    path = tmp_path / "p.jsonl"
    later = datetime(2026, 11, 6, 6, 17, tzinfo=timezone.utc)
    assert ledger.record(path, "2026-27", NOW, "commit1", PARAMS, DATA, [fc(1, "2026-11-06T20:00:00Z")]) == 1
    assert ledger.record(path, "2026-27", later, "commit2", PARAMS, DATA, [fc(1, "2026-11-06T20:00:00Z")]) == 0
    assert ledger.read(path)[0]["model_version"] == "commit1"


@pytest.mark.parametrize("change", ["probabilities", "params", "data"])
def test_each_defining_input_creates_a_new_record(tmp_path, change):
    path = tmp_path / "p.jsonl"
    later = datetime(2026, 11, 6, 6, 17, tzinfo=timezone.utc)
    ledger.record(path, "2026-27", NOW, "c1", PARAMS, DATA, [fc(1, "2026-11-06T20:00:00Z")])
    before = path.read_text()
    f = fc(1, "2026-11-06T20:00:00Z", ph=0.52, pd=0.29, pa=0.19) if change == "probabilities" else fc(1, "2026-11-06T20:00:00Z")
    params = {**PARAMS, "rho": 0.0} if change == "params" else PARAMS
    data = {**DATA, "data_sha256": "bbbb"} if change == "data" else DATA
    assert ledger.record(path, "2026-27", later, "c1", params, data, [f]) == 1
    assert path.read_text().startswith(before)          # appended, never rewritten


def test_schema1_record_is_superseded_once(tmp_path):
    path = tmp_path / "p.jsonl"
    ledger.record(path, "2026-27", NOW, "c1", PARAMS, {"source": "fpl"}, [fc(1, "2026-11-06T20:00:00Z")])
    later = datetime(2026, 11, 6, 6, 17, tzinfo=timezone.utc)
    assert ledger.record(path, "2026-27", later, "c2", PARAMS, DATA, [fc(1, "2026-11-06T20:00:00Z")]) == 1
    assert ledger.record(path, "2026-27", later, "c3", PARAMS, DATA, [fc(1, "2026-11-06T20:00:00Z")]) == 0


def test_data_fingerprint_tracks_results_and_xg():
    from predictor.model import Match
    a = [Match(1, "A", "B", 1, 0, 1.2, 0.4, "2026-08-16T14:00:00Z"), Match(1, "C", "D", 0, 0, None, None, "2026-08-16T14:00:00Z")]
    assert ledger.data_fingerprint(a) == ledger.data_fingerprint(list(reversed(a)))
    assert ledger.data_fingerprint(a) != ledger.data_fingerprint(a[:1])
    b = [Match(1, "A", "B", 1, 0, 1.3, 0.4, "2026-08-16T14:00:00Z"), a[1]]
    assert ledger.data_fingerprint(a) != ledger.data_fingerprint(b)


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
    latest, fixed = out["latest_pre_kickoff"], out["fixed_24h"]
    assert latest["scored"] == 2 and latest["lead_time_hours"]["min"] == pytest.approx(21.0)
    assert latest["comparison"]["model"]["n"] == 2
    # Friday's match was first forecast 21h ahead, so only Saturday's is on the 24h track.
    assert fixed["forecasts"] == 1 and fixed["scored"] == 1 and fixed["comparison"] is None


def test_canonical_names():
    assert benchmark.canon("Ipswich Town") == benchmark.canon("Ipswich") == "Ipswich"
    assert prospective.season_code("2026-27") == "2627"


def test_fixed_horizon_picks_the_forecast_standing_24h_before_kickoff():
    k = "2026-11-08T14:00:00Z"
    recs = [dict(fixture_id="1", kickoff=k, predicted_at="2026-11-05T06:17:00Z", v="3 days out"),
            dict(fixture_id="1", kickoff=k, predicted_at="2026-11-07T06:17:00Z", v="31h out"),
            dict(fixture_id="1", kickoff=k, predicted_at="2026-11-08T06:17:00Z", v="8h out")]
    assert ledger.fixed_horizon(recs)["1"]["v"] == "31h out"
    assert ledger.latest_before_kickoff(recs)["1"]["v"] == "8h out"
    assert ledger.forecast_at(recs, 72)["1"]["v"] == "3 days out"
    assert "1" not in ledger.forecast_at(recs, 96)


def test_status_reports_coverage_and_missing_odds(tmp_path):
    preds = tmp_path / "p.jsonl"
    ledger.record(preds, "2026-27", NOW, "abc", PARAMS, {}, [
        fc(1, "2026-11-06T20:00:00Z"), fc(2, "2026-11-07T12:30:00Z", home="Leeds", away="Spurs")])
    later = datetime(2026, 11, 7, 18, 0, tzinfo=timezone.utc)
    rep = ledger.status(ledger.read(preds), [], later)
    assert rep["fixtures_forecast"] == 2 and rep["latest_track_eligible"] == 2 and rep["fixed_24h_track_eligible"] == 1
    assert rep["kicked_off"] == 2 and len(rep["kicked_off_missing_odds_or_result"]) == 2
    assert rep["fixtures"][0]["lead_hours_first"] == 21.0 and not rep["integrity_problems"]


def test_verify_history_flags_any_commit_that_rewrites_lines(tmp_path, monkeypatch):
    import subprocess
    g = lambda *a: subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *a], cwd=tmp_path,
                                  check=True, capture_output=True)
    g("init", "-q"); (tmp_path / "ledger").mkdir()
    f = tmp_path / "ledger" / "predictions-2026-27.jsonl"
    f.write_text('{"a":1}\n'); g("add", "."); g("commit", "-qm", "1")
    f.write_text('{"a":1}\n{"a":2}\n'); g("commit", "-qam", "append")
    monkeypatch.setattr(ledger, "ROOT", tmp_path)
    assert ledger.verify_history(tmp_path / "ledger") == []
    f.write_text('{"a":99}\n{"a":2}\n'); g("commit", "-qam", "tamper")
    problems = ledger.verify_history(tmp_path / "ledger")
    assert len(problems) == 1 and "edited or removed" in problems[0]
