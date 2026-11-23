from datetime import datetime, timezone

from predictor import ledger, teamnews

T0 = datetime(2026, 11, 22, 23, 0, tzinfo=timezone.utc)
T1 = datetime(2026, 11, 23, 11, 0, tzinfo=timezone.utc)


def boot(**overrides):
    els = [{"id": 1, "web_name": "Raya", "team": 1, "element_type": 1, "status": "a", "chance_of_playing_this_round": None,
            "chance_of_playing_next_round": None, "news": "", "news_added": None},
           {"id": 2, "web_name": "Isak", "team": 2, "element_type": 4, "status": "a", "chance_of_playing_this_round": None,
            "chance_of_playing_next_round": None, "news": "", "news_added": None}]
    for pid, changes in overrides.items():
        els[int(pid[1:]) - 1].update(changes)
    return {"teams": [{"id": 1, "name": "Arsenal"}, {"id": 2, "name": "Liverpool"}],
            "events": [{"id": 12, "is_next": True}], "elements": els}


def test_first_run_records_everyone_then_only_changes(tmp_path):
    p = tmp_path / "tn.jsonl"
    assert teamnews.record(p, boot(), T0) == 2
    assert teamnews.record(p, boot(), T1) == 0
    injured = {"status": "d", "chance_of_playing_next_round": 75, "news": "Shoulder - 75%", "news_added": "2026-11-23T10:00:00Z"}
    before = p.read_text()
    assert teamnews.record(p, boot(p2=injured), T1) == 1
    assert p.read_text().startswith(before)                     # appended, never rewritten
    rec = ledger.read(p)[-1]
    assert (rec["name"], rec["team"], rec["status"], rec["chance_next"], rec["next_gw"]) == ("Isak", "Liverpool", "d", 75, 12)


def test_transfer_between_clubs_is_recorded(tmp_path):
    p = tmp_path / "tn.jsonl"
    teamnews.record(p, boot(), T0)
    assert teamnews.record(p, boot(p2={"team": 1}), T1) == 1


def test_as_of_reconstructs_what_was_public(tmp_path):
    p = tmp_path / "tn.jsonl"
    teamnews.record(p, boot(), T0)
    teamnews.record(p, boot(p2={"status": "i", "chance_of_playing_next_round": 0, "news": "Hamstring"}), T1)
    recs = ledger.read(p)
    assert teamnews.as_of(recs, "2026-11-23T10:59:59Z")[2]["status"] == "a"
    assert teamnews.as_of(recs, "2026-11-23T11:00:00Z")[2]["status"] == "i"
    assert teamnews.as_of(recs, "2026-11-22T00:00:00Z") == {}


def test_history_check_covers_the_archive(tmp_path, monkeypatch):
    import subprocess
    g = lambda *a: subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *a], cwd=tmp_path, check=True, capture_output=True)
    g("init", "-q"); d = tmp_path / "ledger"; d.mkdir()
    p = teamnews.path_for("2026-27", d)
    teamnews.record(p, boot(), T0); g("add", "."); g("commit", "-qm", "1")
    p.write_text(p.read_text().replace('"Raya"', '"Edited"')); g("commit", "-qam", "tamper")
    monkeypatch.setattr(ledger, "ROOT", tmp_path)
    assert any("edited or removed" in x for x in ledger.verify_history(d))
