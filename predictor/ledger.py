"""Prospective prediction ledger: an append-only record of forecasts made before kickoff.

The daily build appends one record per upcoming fixture (kicking off within
WINDOW_DAYS) whenever the forecast differs from the last one recorded for it. The
prospective forecast for a match is the latest record timestamped before kickoff.

    ledger/predictions-<season>.jsonl   model forecasts (this module)
    ledger/market-<season>.jsonl        closing odds and results (predictor.prospective)

Records are never edited or removed. `python -m predictor.ledger verify --base <git ref>`
fails if a file is anything other than its previous version with lines appended,
and the GitHub Action runs it before every commit.

Forecasts made before the ledger existed (2026-11-05) are not prospective.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LEDGER_DIR = ROOT / "ledger"
WINDOW_DAYS = 7
SCHEMA = 2   # 2: adds data["data_sha256"]; duplicates are judged without the commit hash
REQUIRED = {"schema", "fixture_id", "season", "gw", "kickoff", "home", "away", "predicted_at",
            "model_version", "params", "params_sha256", "data", "expected_goals", "probabilities"}


def predictions_path(season: str, root: Path = LEDGER_DIR) -> Path:
    return root / f"predictions-{season}.jsonl"


def model_version() -> str:
    """The exact code version: the Action's commit, else the local git HEAD."""
    if os.environ.get("GITHUB_SHA"):
        return os.environ["GITHUB_SHA"]
    try:
        sha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True,
                             check=True).stdout.strip()
        dirty = subprocess.run(["git", "status", "--porcelain", "--", "predictor"], cwd=ROOT,
                               capture_output=True, text=True).stdout.strip()
        return sha + ("-dirty" if dirty else "")
    except Exception:
        return "unknown"


def params_hash(params: dict) -> str:
    return hashlib.sha256(json.dumps(params, sort_keys=True).encode()).hexdigest()[:16]


def read(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def is_same_forecast(prev: dict, probs: dict, phash: str, data_hash: str | None) -> bool:
    """Fixture + model configuration + input-data fingerprint + probabilities.
    A previous record without a fingerprint (schema 1) never counts as the same."""
    prev_data = prev.get("data", {}).get("data_sha256")
    return (prev["probabilities"] == probs and prev["params_sha256"] == phash
            and data_hash is not None and prev_data == data_hash)


def data_fingerprint(matches) -> str:
    """Hash of every input the ratings are fitted on: results and xG of finished matches."""
    rows = sorted((m.kickoff, m.home, m.away, m.home_goals, m.away_goals,
                   None if m.home_xg is None else round(m.home_xg, 4),
                   None if m.away_xg is None else round(m.away_xg, 4)) for m in matches)
    return hashlib.sha256(json.dumps(rows).encode()).hexdigest()[:16]


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def record(path: Path, season: str, now: datetime, version: str, params: dict, data_state: dict,
           forecasts: list[dict]) -> int:
    """Append forecasts for fixtures kicking off within WINDOW_DAYS of `now`.

    Each forecast: fixture_id, gw, kickoff, home, away, lh, la, ph, pd, pa.
    A record is added only when something that defines the forecast differs from
    the last record for that fixture: the model configuration (params_sha256), the
    input data (data["data_sha256"]) or the probabilities. The commit hash is stored
    for audit but does not by itself create a new record, since every data commit
    by the Action changes it. Returns the number of records appended.
    """
    now_iso, horizon = _iso(now), _iso(now + timedelta(days=WINDOW_DAYS))
    last = {}
    for rec in read(path):
        last[rec["fixture_id"]] = rec
    phash = params_hash(params)
    data_hash = data_state.get("data_sha256")
    new = []
    for f in forecasts:
        if not (now_iso < f["kickoff"] <= horizon):
            continue
        probs = {"H": round(f["ph"], 6), "D": round(f["pd"], 6), "A": round(f["pa"], 6)}
        prev = last.get(str(f["fixture_id"]))
        if prev and is_same_forecast(prev, probs, phash, data_hash):
            continue
        new.append({
            "schema": SCHEMA, "fixture_id": str(f["fixture_id"]), "season": season, "gw": f["gw"],
            "kickoff": f["kickoff"], "home": f["home"], "away": f["away"], "predicted_at": now_iso,
            "model_version": version, "params": params, "params_sha256": phash, "data": data_state,
            "expected_goals": [round(f["lh"], 4), round(f["la"], 4)], "probabilities": probs,
        })
    if new:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a") as fh:
            for rec in new:
                fh.write(json.dumps(rec, separators=(",", ":"), sort_keys=True) + "\n")
    return len(new)


def _dt(iso: str) -> datetime:
    return datetime.fromisoformat(iso.replace("Z", "+00:00"))


def forecast_at(records: list[dict], hours_before: float = 0.0) -> dict[str, dict]:
    """Per fixture, the forecast standing `hours_before` kickoff: the last record made
    at or before that moment (strictly before kickoff when hours_before is 0).

    Records are appended only when a forecast changes, so the last record before a
    cutoff is exactly the forecast that was standing at that cutoff.
    """
    out = {}
    for rec in records:
        cutoff = _dt(rec["kickoff"]) - timedelta(hours=hours_before)
        made = _dt(rec["predicted_at"])
        ok = made < cutoff if hours_before == 0 else made <= cutoff
        if ok:
            cur = out.get(rec["fixture_id"])
            if cur is None or rec["predicted_at"] >= cur["predicted_at"]:
                out[rec["fixture_id"]] = rec
    return out


def latest_before_kickoff(records: list[dict]) -> dict[str, dict]:
    """Track 1: the last forecast made before kickoff."""
    return forecast_at(records, 0.0)


FIXED_HORIZON_HOURS = 24


def fixed_horizon(records: list[dict], hours: float = FIXED_HORIZON_HOURS) -> dict[str, dict]:
    """Track 2: the forecast standing `hours` before kickoff, for a consistent lead time.
    Fixtures first forecast less than `hours` ahead are not eligible."""
    return forecast_at(records, hours)


def status(records: list[dict], market: list[dict], now: datetime) -> dict:
    """Coverage report: fixtures forecast, eligibility per track, timestamps, odds coverage."""
    by_fixture: dict[str, list[dict]] = {}
    for r in records:
        by_fixture.setdefault(r["fixture_id"], []).append(r)
    latest, fixed = latest_before_kickoff(records), fixed_horizon(records)
    rows = []
    for fid, recs in sorted(by_fixture.items(), key=lambda kv: kv[1][0]["kickoff"]):
        first = min(r["predicted_at"] for r in recs)
        last = max(r["predicted_at"] for r in recs)
        k = recs[0]
        rows.append({"fixture_id": fid, "gw": k["gw"], "match": f"{k['home']} v {k['away']}", "kickoff": k["kickoff"],
                     "records": len(recs), "first_forecast": first, "last_forecast": last,
                     "lead_hours_first": round((_dt(k["kickoff"]) - _dt(first)).total_seconds() / 3600, 1),
                     "fixed_24h_eligible": fid in fixed, "kicked_off": k["kickoff"] <= _iso(now)})
    played = [r for r in rows if r["kicked_off"]]
    from .benchmark import canon, uk_date
    have_odds = {(canon(m["home"]), canon(m["away"]), m["date"]) for m in market}
    missing_odds = [r["match"] + f" (GW{r['gw']})" for r in played
                    if (canon(by_fixture[r["fixture_id"]][0]["home"]), canon(by_fixture[r["fixture_id"]][0]["away"]),
                        uk_date(r["kickoff"])) not in have_odds]
    return {"checked_at": _iso(now), "records": len(records), "fixtures_forecast": len(rows),
            "latest_track_eligible": len(latest), "fixed_24h_track_eligible": len(fixed),
            "kicked_off": len(played), "kicked_off_missing_odds_or_result": missing_odds,
            "integrity_problems": check_records(records), "fixtures": rows}


# ---------------------------------------------------------------- verification
def check_records(records: list[dict]) -> list[str]:
    problems = []
    for i, rec in enumerate(records, start=1):
        missing = REQUIRED - set(rec)
        if missing:
            problems.append(f"record {i}: missing {sorted(missing)}"); continue
        if not rec["predicted_at"] < rec["kickoff"]:
            problems.append(f"record {i}: predicted_at {rec['predicted_at']} is not before kickoff {rec['kickoff']}")
        p = rec["probabilities"]
        if abs(p["H"] + p["D"] + p["A"] - 1) > 1e-4:
            problems.append(f"record {i}: probabilities sum to {p['H'] + p['D'] + p['A']}")
    return problems


def check_append_only(old_text: str, new_text: str) -> list[str]:
    if not new_text.startswith(old_text):
        return ["existing lines were changed or removed; the ledger is append-only"]
    return []


def verify(base: str | None, root: Path = LEDGER_DIR) -> list[str]:
    problems = []
    for path in sorted(root.glob("predictions-*.jsonl")):
        problems += [f"{path.name}: {p}" for p in check_records(read(path))]
    for path in sorted(root.glob("*.jsonl")):
        if base:
            rel = path.relative_to(ROOT).as_posix()
            old = subprocess.run(["git", "show", f"{base}:{rel}"], cwd=ROOT, capture_output=True, text=True)
            if old.returncode == 0:
                problems += [f"{path.name}: {p}" for p in check_append_only(old.stdout, path.read_text())]
    return problems


def verify_history(root: Path = LEDGER_DIR) -> list[str]:
    """Check every committed version of every ledger file: each must extend the one before.

    Catches an edit or deletion made by any commit, including a person's push, not
    just the current run's changes. Needs full git history (fetch-depth: 0 in CI).
    """
    problems = []
    rel_dir = root.relative_to(ROOT).as_posix()
    files = subprocess.run(["git", "log", "--format=", "--name-only", "--", rel_dir], cwd=ROOT,
                           capture_output=True, text=True).stdout.split()
    for rel in sorted(set(f for f in files if f.endswith(".jsonl"))):
        commits = subprocess.run(["git", "log", "--reverse", "--format=%H", "--", rel], cwd=ROOT,
                                 capture_output=True, text=True).stdout.split()
        prev, prev_sha = "", None
        for sha in commits:
            cur = subprocess.run(["git", "show", f"{sha}:{rel}"], cwd=ROOT, capture_output=True, text=True)
            text = cur.stdout if cur.returncode == 0 else ""
            if not text.startswith(prev):
                problems.append(f"{rel}: commit {sha[:10]} edited or removed lines that existed at {prev_sha[:10]}")
            prev, prev_sha = text, sha
    return problems


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    v = sub.add_parser("verify", help="check schema, pre-kickoff timestamps and append-only history")
    v.add_argument("--base", help="git ref to compare against, e.g. HEAD")
    v.add_argument("--history", action="store_true", help="also check every committed version of the ledger")
    st = sub.add_parser("status", help="print coverage, timestamps and odds coverage")
    st.add_argument("--season")
    a = ap.parse_args(argv)
    if a.cmd == "status":
        from datetime import timezone
        from .build import season_for
        now = datetime.now(timezone.utc)
        season = a.season or season_for(now)
        rep = status(read(predictions_path(season)), read(LEDGER_DIR / f"market-{season}.jsonl"), now)
        print(f"LEDGER STATUS {season} at {rep['checked_at']}")
        print(f"  records {rep['records']} · fixtures forecast {rep['fixtures_forecast']} · "
              f"latest-track eligible {rep['latest_track_eligible']} · 24h-track eligible {rep['fixed_24h_track_eligible']}")
        print(f"  kicked off {rep['kicked_off']} · missing odds/result {len(rep['kicked_off_missing_odds_or_result'])} · "
              f"integrity problems {len(rep['integrity_problems'])}")
        for f in rep["fixtures"]:
            print(f"  GW{f['gw']:>2} {f['kickoff']} {f['match']:<34} records {f['records']} first {f['first_forecast']} "
                  f"({f['lead_hours_first']}h ahead) 24h-eligible {'yes' if f['fixed_24h_eligible'] else 'no'}")
        for m in rep["kicked_off_missing_odds_or_result"]:
            print(f"  awaiting odds/result: {m}")
        return
    problems = verify(a.base) + (verify_history() if a.history else [])
    for p in problems:
        print("LEDGER ERROR:", p, file=sys.stderr)
    if problems:
        sys.exit(1)
    print("Ledger OK")


if __name__ == "__main__":
    main()
