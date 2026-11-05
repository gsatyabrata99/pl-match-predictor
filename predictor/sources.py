"""Data sources.

* ``fpl``    – the official Fantasy Premier League API (live; used in GitHub Actions).
* ``mirror`` – the community archive at github.com/vaastav/Fantasy-Premier-League,
               which also provides previous seasons for the ratings prior.

Both return a :class:`Season`: team names, every fixture, and per-match xG.
"""
from __future__ import annotations

import csv
import io
import json
import time
import urllib.request
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from .model import Match

FPL = "https://fantasy.premierleague.com/api"
MIRROR = "https://raw.githubusercontent.com/vaastav/Fantasy-Premier-League/{ref}/data"
USER_AGENT = "pl-match-predictor (+https://github.com)"


@dataclass
class Fixture:
    id: str
    gw: int | None
    kickoff: str
    home: str
    away: str
    home_goals: int | None = None
    away_goals: int | None = None
    finished: bool = False


@dataclass
class Season:
    teams: dict[str, str]                       # name -> short name
    fixtures: list[Fixture]
    xg: dict[str, tuple[float, float]] = field(default_factory=dict)  # fixture id -> (home xG, away xG)
    source: str = ""

    def matches(self) -> list[Match]:
        out = []
        for f in self.fixtures:
            if not f.finished or f.home_goals is None or f.gw is None:
                continue
            hx, ax = self.xg.get(f.id, (None, None))
            # A real match never has exactly zero xG for both sides; that pattern means
            # xG wasn't recorded (e.g. FPL only added xG from GW16 of 2022-23).
            if hx is not None and hx + ax == 0:
                hx = ax = None
            out.append(Match(f.gw, f.home, f.away, f.home_goals, f.away_goals, hx, ax, f.kickoff))
        return sorted(out, key=lambda m: m.kickoff)


def _get(url: str, retries: int = 3) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.read()
        except Exception:
            if attempt == retries - 1:
                raise
            time.sleep(2 * (attempt + 1))
    raise RuntimeError("unreachable")


def _int(v) -> int | None:
    return None if v in (None, "", "None") else int(float(v))


# ---------------------------------------------------------------- official FPL API
def parse_fpl(bootstrap: dict, fixtures: list[dict], live: dict[int, dict]) -> Season:
    """Build a Season from raw FPL API payloads (kept separate from I/O so it can be tested)."""
    teams_by_id = {t["id"]: t for t in bootstrap["teams"]}
    team_of_player = {e["id"]: e["team"] for e in bootstrap["elements"]}
    fx = [Fixture(id=str(f["id"]), gw=f.get("event"), kickoff=f.get("kickoff_time") or "",
                  home=teams_by_id[f["team_h"]]["name"], away=teams_by_id[f["team_a"]]["name"],
                  home_goals=_int(f.get("team_h_score")), away_goals=_int(f.get("team_a_score")),
                  finished=bool(f.get("finished") or f.get("finished_provisional")))
          for f in fixtures]
    side = {}  # fixture id -> {team id: "h"/"a"}
    for f in fixtures:
        side[str(f["id"])] = {f["team_h"]: 0, f["team_a"]: 1}

    xg: dict[str, list[float]] = defaultdict(lambda: [0.0, 0.0])
    for payload in live.values():
        for el in payload.get("elements", []):
            team = team_of_player.get(el["id"])
            player_xg = float(el.get("stats", {}).get("expected_goals") or 0)
            if team is None or player_xg == 0:
                continue
            # A player's xG is reported per gameweek. In a double gameweek, split it
            # across fixtures by minutes played.
            mins = []
            for ex in el.get("explain", []):
                m = next((s["value"] for s in ex.get("stats", []) if s.get("identifier") == "minutes"), 0)
                mins.append((str(ex["fixture"]), m))
            total = sum(m for _, m in mins)
            for fid, m in mins:
                if fid not in side or team not in side[fid]:
                    continue
                share = (m / total) if total else 1 / len(mins)
                xg[fid][side[fid][team]] += player_xg * share
    names = {t["name"]: t["short_name"] for t in bootstrap["teams"]}
    return Season(names, fx, {k: (v[0], v[1]) for k, v in xg.items()}, source="fpl")


def load_fpl(pause: float = 0.4) -> Season:
    bootstrap = json.loads(_get(f"{FPL}/bootstrap-static/"))
    fixtures = json.loads(_get(f"{FPL}/fixtures/"))
    played = sorted({f["event"] for f in fixtures if f.get("event") and (f.get("finished") or f.get("finished_provisional"))})
    live = {}
    for gw in played:
        live[gw] = json.loads(_get(f"{FPL}/event/{gw}/live/"))
        time.sleep(pause)
    return parse_fpl(bootstrap, fixtures, live)


# ---------------------------------------------------------------- community mirror
def parse_mirror(teams_rows: list[dict], fixture_rows: list[dict], gw_rows: list[dict]) -> Season:
    teams = {r["id"]: r for r in teams_rows}
    fx = [Fixture(id=r["id"], gw=_int(r["event"]), kickoff=r["kickoff_time"],
                  home=teams[r["team_h"]]["name"], away=teams[r["team_a"]]["name"],
                  home_goals=_int(r["team_h_score"]), away_goals=_int(r["team_a_score"]),
                  finished=r["finished"] == "True")
          for r in fixture_rows]
    by_id = {f.id: f for f in fx}
    xg: dict[str, list[float]] = defaultdict(lambda: [0.0, 0.0])
    for r in gw_rows:
        if "expected_goals" not in r:   # seasons before 2022-23 have no xG
            break
        f = by_id.get(r["fixture"])
        if f is None:
            continue
        xg[f.id][0 if r["team"] == f.home else 1] += float(r["expected_goals"] or 0)
    names = {r["name"]: r["short_name"] for r in teams_rows}
    return Season(names, fx, {k: (v[0], v[1]) for k, v in xg.items()}, source="mirror")


MIRROR_FILES = ("teams.csv", "fixtures.csv", "gws/merged_gw.csv")


def mirror_files(season: str, ref: str = "master", cache: Path | None = None) -> dict[str, bytes]:
    """Raw CSV bytes for one season. With a commit `ref` and a `cache` dir, files are
    downloaded once and reused, so pinned historical data is reproducible offline."""
    out = {}
    for name in MIRROR_FILES:
        local = cache / ref / season / name if cache else None
        if local and local.exists():
            out[name] = local.read_bytes()
            continue
        data = _get(f"{MIRROR.format(ref=ref)}/{season}/{name}")
        if local:
            local.parent.mkdir(parents=True, exist_ok=True)
            local.write_bytes(data)
        out[name] = data
    return out


def load_mirror(season: str, ref: str = "master", cache: Path | None = None) -> Season:
    files = mirror_files(season, ref, cache)
    rows = {k: list(csv.DictReader(io.StringIO(v.decode("utf-8")))) for k, v in files.items()}
    return parse_mirror(rows["teams.csv"], rows["fixtures.csv"], rows["gws/merged_gw.csv"])


# ---------------------------------------------------------------- manual results
def apply_manual_results(season: Season, path: Path) -> int:
    """Fill in scores the source doesn't have yet from a CSV: gw,home,home_goals,away_goals,away.

    Only fixtures that are unscored in the source are touched, so stale overrides
    are ignored once real data arrives. Returns how many fixtures were filled.
    """
    if not path.exists():
        return 0
    filled = 0
    index = {(f.gw, f.home, f.away): f for f in season.fixtures}
    for r in csv.DictReader(path.open()):
        f = index.get((int(r["gw"]), r["home"], r["away"]))
        if f is None:
            raise ValueError(f"{path}: no fixture GW{r['gw']} {r['home']} v {r['away']}")
        if f.finished and f.home_goals is not None:
            continue
        f.home_goals, f.away_goals, f.finished = int(r["home_goals"]), int(r["away_goals"]), True
        season.xg.pop(f.id, None)
        filled += 1
    return filled
