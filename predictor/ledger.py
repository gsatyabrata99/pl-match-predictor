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
SCHEMA = 1
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


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def record(path: Path, season: str, now: datetime, version: str, params: dict, data_state: dict,
           forecasts: list[dict]) -> int:
    """Append forecasts for fixtures kicking off within WINDOW_DAYS of `now`.

    Each forecast: fixture_id, gw, kickoff, home, away, lh, la, ph, pd, pa.
    A record is only added when the forecast or model differs from the last one
    recorded for that fixture. Returns the number of records appended.
    """
    now_iso, horizon = _iso(now), _iso(now + timedelta(days=WINDOW_DAYS))
    last = {}
    for rec in read(path):
        last[rec["fixture_id"]] = rec
    phash = params_hash(params)
    new = []
    for f in forecasts:
        if not (now_iso < f["kickoff"] <= horizon):
            continue
        probs = {"H": round(f["ph"], 6), "D": round(f["pd"], 6), "A": round(f["pa"], 6)}
        prev = last.get(str(f["fixture_id"]))
        if prev and prev["probabilities"] == probs and prev["params_sha256"] == phash \
                and prev["model_version"].split("-")[0] == version.split("-")[0]:
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


def latest_before_kickoff(records: list[dict]) -> dict[str, dict]:
    """The prospective forecast per fixture: the last record made before kickoff."""
    out = {}
    for rec in records:
        if rec["predicted_at"] < rec["kickoff"]:
            cur = out.get(rec["fixture_id"])
            if cur is None or rec["predicted_at"] >= cur["predicted_at"]:
                out[rec["fixture_id"]] = rec
    return out


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


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    v = sub.add_parser("verify", help="check schema, pre-kickoff timestamps and append-only history")
    v.add_argument("--base", help="git ref to compare against, e.g. HEAD")
    a = ap.parse_args(argv)
    problems = verify(a.base)
    for p in problems:
        print("LEDGER ERROR:", p, file=sys.stderr)
    if problems:
        sys.exit(1)
    print("Ledger OK")


if __name__ == "__main__":
    main()
