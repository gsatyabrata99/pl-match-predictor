"""Team-news archive: append-only snapshots of FPL availability flags.

    ledger/team-news-<season>.jsonl

FPL publishes each player's status, chance of playing and injury news live but keeps
no history, so what was known before a match is lost once it is played. Every daily
run records the flags for any player whose flags changed since his last record (the
first run records everyone). Together the records give, for any moment, the team news
that was public then; `as_of` reconstructs it.

Records are never edited; the ledger's history check (python -m predictor.ledger
verify --history) covers this file too.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from .ledger import LEDGER_DIR, _iso, read

SCHEMA = 1
FIELDS = ("status", "chance_this", "chance_next", "news", "news_added")


def path_for(season: str, root: Path = LEDGER_DIR) -> Path:
    return root / f"team-news-{season}.jsonl"


def flags(element: dict) -> dict:
    return {"status": element.get("status"),
            "chance_this": element.get("chance_of_playing_this_round"),
            "chance_next": element.get("chance_of_playing_next_round"),
            "news": element.get("news") or "",
            "news_added": element.get("news_added")}


def latest(records: list[dict]) -> dict[int, dict]:
    out = {}
    for r in records:
        out[r["id"]] = r
    return out


def record(path: Path, bootstrap: dict, now: datetime) -> int:
    """Append a record for every player whose flags differ from his last record.
    Returns the number appended."""
    teams = {t["id"]: t["name"] for t in bootstrap["teams"]}
    nxt = next((e["id"] for e in bootstrap["events"] if e.get("is_next")), None)
    last = latest(read(path))
    new = []
    for e in bootstrap["elements"]:
        f = flags(e)
        prev = last.get(e["id"])
        if prev and all(prev.get(k) == f[k] for k in FIELDS) and prev.get("team") == teams.get(e["team"]):
            continue
        new.append({"schema": SCHEMA, "captured_at": _iso(now), "next_gw": nxt, "id": e["id"],
                    "name": e["web_name"], "team": teams.get(e["team"]), "pos": e["element_type"], **f})
    if new:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a") as fh:
            for r in new:
                fh.write(json.dumps(r, separators=(",", ":"), sort_keys=True) + "\n")
    return len(new)


def as_of(records: list[dict], when: str) -> dict[int, dict]:
    """Each player's flags as publicly known at `when` (ISO UTC): his last record captured
    at or before that time. Players first seen later are absent."""
    out = {}
    for r in records:
        if r["captured_at"] <= when:
            out[r["id"]] = r
    return out
