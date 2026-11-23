"""FPL expected points, built on the match predictor's published ratings.

    python -m predictor.fpl                  # writes site/data/fpl.json (run after predictor.build)
    python -m predictor.fpl backtest         # walk-forward check on 2025-26

The predictor is not changed. Team strengths, league averages and ρ are read from
site/data/predictions.json, so FPL projections use exactly the published ratings.

Per player and fixture:

    minutes     share of the player's last FORM_GWS team gameweeks played, and played 60+,
                times FPL's availability flag
    rates       season xG, xA, saves, bonus and yellows per minute, shrunk toward the
                positional average by RATE_PRIOR_MINUTES; defensive-contribution hit rate
                per 60+ appearance, shrunk by DEFCON_PRIOR_APPS
    fixture     attacking output scales with the team's expected goals in this fixture
                relative to its neutral-schedule average; saves scale with the opponent's;
                clean-sheet and goals-conceded chances come from the scoreline grid
    points      the official scoring table, read from the FPL API

All constants were fixed before the backtest was run and have not been tuned.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from . import model, sources

ROOT = Path(__file__).resolve().parent.parent
SITE_DATA = ROOT / "site" / "data"
FPL = sources.FPL

POS = {1: "GKP", 2: "DEF", 3: "MID", 4: "FWD"}
DEFCON_THRESHOLD = {"DEF": 10, "MID": 12, "FWD": 12}   # premierleague.com, 2026/27 (unchanged from 2025/26)
HORIZON = 5               # gameweeks projected
FORM_GWS = 5              # recent team gameweeks used for minutes
RATE_PRIOR_MINUTES = 450  # per-minute rates: positional average worth 5 full games
DEFCON_PRIOR_APPS = 6     # defensive-contribution hit rate: positional average worth 6 apps

# 2026/27 scoring as published in the FPL API (game_config.scoring). Used only when
# the API's own table isn't available, e.g. when backtesting a past season.
DEFAULT_SCORING = {
    "short_play": 1, "long_play": 2, "assists": 3, "saves": 1, "bonus": 1, "yellow_cards": -1,
    "goals_scored": {"GKP": 10, "DEF": 6, "MID": 5, "FWD": 4},
    "clean_sheets": {"GKP": 4, "DEF": 4, "MID": 1, "FWD": 0},
    "goals_conceded": {"GKP": -1, "DEF": -1, "MID": 0, "FWD": 0},
    "defensive_contribution": {"GKP": 0, "DEF": 2, "MID": 2, "FWD": 2},
}
SCORING_KEYS = list(DEFAULT_SCORING)


# ---------------------------------------------------------------- data
@dataclass
class GW:
    gw: int
    minutes: int
    xg: float
    xa: float
    saves: int
    bonus: int
    yellow: int
    defcon: int        # combined defensive actions (CBIT / CBIRT), not points
    points: int


@dataclass
class Fixture:
    gw: int
    team: str
    opp: str
    home: bool
    kickoff: str


@dataclass
class Ratings:
    att: dict[str, float]
    dfn: dict[str, float]
    mu_h: float
    mu_a: float
    rho: float

    @classmethod
    def from_predictions(cls, data: dict) -> "Ratings":
        return cls({t["name"]: t["att"] for t in data["teams"]}, {t["name"]: t["dfn"] for t in data["teams"]},
                   data["meta"]["mu_h"], data["meta"]["mu_a"], data["meta"]["rho"])

    @classmethod
    def from_model(cls, r: model.Ratings, rho: float) -> "Ratings":
        return cls(r.attack, r.defence, r.mu_home, r.mu_away, rho)

    def lam(self, team: str, opp: str, home: bool) -> tuple[float, float]:
        """(team's expected goals, opponent's expected goals) in this fixture."""
        if home:
            return self.mu_h * self.att[team] * self.dfn[opp], self.mu_a * self.att[opp] * self.dfn[team]
        return self.mu_a * self.att[team] * self.dfn[opp], self.mu_h * self.att[opp] * self.dfn[team]

    def neutral(self, team: str) -> tuple[float, float]:
        """Average (for, against) over every opponent, home and away."""
        opps = [o for o in self.att if o != team]
        f = a = 0.0
        for o in opps:
            for home in (True, False):
                x, y = self.lam(team, o, home); f += x; a += y
        n = 2 * len(opps)
        return f / n, a / n

    def conceded(self, team: str, opp: str, home: bool) -> tuple[float, float]:
        """(P(team keeps a clean sheet), E[floor(goals conceded / 2)]) from the scoreline grid."""
        home_team, away_team = (team, opp) if home else (opp, team)
        g = model.scoreline(*self.lam(home_team, away_team, True), self.rho).grid
        n = range(len(g))
        if home:
            dist = [sum(g[i][j] for i in n) for j in n]    # opponent is away: column sums
        else:
            dist = [sum(g[i][j] for j in n) for i in n]    # opponent is at home: row sums
        return dist[0], sum(p * (k // 2) for k, p in enumerate(dist))


# ---------------------------------------------------------------- player model
@dataclass
class Profile:
    pos: str
    p_play: float          # chance of any minutes
    p60: float             # chance of 60+ minutes
    mins_if_play: float
    xg: float              # per minute
    xa: float
    saves: float
    bonus: float
    yellow: float
    defcon_p: float        # chance of hitting the threshold in a 60+ appearance
    games: int             # team gameweeks used for minutes

    @property
    def exp_minutes(self) -> float:
        return self.p_play * self.mins_if_play


def position_priors(histories: dict[int, list[GW]], positions: dict[int, str]) -> dict[str, dict]:
    tot = defaultdict(lambda: defaultdict(float))
    for pid, hist in histories.items():
        pos = positions[pid]
        for g in hist:
            if g.minutes <= 0:
                continue
            t = tot[pos]
            t["minutes"] += g.minutes
            for k in ("xg", "xa", "saves", "bonus", "yellow"):
                t[k] += getattr(g, k)
            if g.minutes >= 60 and pos in DEFCON_THRESHOLD:
                t["apps60"] += 1
                t["hits"] += g.defcon >= DEFCON_THRESHOLD[pos]
    out = {}
    for pos in ("GKP", "DEF", "MID", "FWD"):
        t = tot[pos]
        m = t["minutes"] or 1
        out[pos] = {k: t[k] / m for k in ("xg", "xa", "saves", "bonus", "yellow")}
        out[pos]["defcon_p"] = t["hits"] / t["apps60"] if t["apps60"] else 0.0
    return out


def profile(hist: list[GW], pos: str, team_gws: list[int], priors: dict) -> Profile:
    """Player profile from gameweeks strictly before the one being forecast."""
    by_gw = defaultdict(int)
    for g in hist:
        by_gw[g.gw] += g.minutes
    recent = [by_gw.get(gw, 0) for gw in team_gws[-FORM_GWS:]]
    n = len(recent)
    played = [m for m in recent if m > 0]
    p_play = len(played) / n if n else 0.0
    p60 = sum(m >= 60 for m in recent) / n if n else 0.0
    mins_if_play = sum(played) / len(played) if played else 0.0
    minutes = sum(g.minutes for g in hist)
    pr = priors[pos]
    rate = lambda k: (sum(getattr(g, k) for g in hist) + RATE_PRIOR_MINUTES * pr[k]) / (minutes + RATE_PRIOR_MINUTES)
    apps60 = [g for g in hist if g.minutes >= 60]
    if pos in DEFCON_THRESHOLD:
        hits = sum(g.defcon >= DEFCON_THRESHOLD[pos] for g in apps60)
        defcon_p = (hits + DEFCON_PRIOR_APPS * pr["defcon_p"]) / (len(apps60) + DEFCON_PRIOR_APPS)
    else:
        defcon_p = 0.0
    return Profile(pos, p_play, p60, mins_if_play, rate("xg"), rate("xa"), rate("saves"), rate("bonus"),
                   rate("yellow"), defcon_p, n)


def fixture_points(pr: Profile, fx: Fixture, r: Ratings, sc: dict, avail: float = 1.0) -> dict:
    """Expected points for one fixture, by component."""
    lam_for, lam_against = r.lam(fx.team, fx.opp, fx.home)
    base_for, base_against = r.neutral(fx.team)
    m_att, m_def = lam_for / base_for, lam_against / base_against
    p_cs, e_half = r.conceded(fx.team, fx.opp, fx.home)
    p_play, p60 = pr.p_play * avail, pr.p60 * avail
    mins = pr.exp_minutes * avail
    pos = pr.pos
    c = {
        "appearance": (p_play - p60) * sc["short_play"] + p60 * sc["long_play"],
        "goals": pr.xg * mins * m_att * sc["goals_scored"][pos],
        "assists": pr.xa * mins * m_att * sc["assists"],
        "clean_sheet": p60 * p_cs * sc["clean_sheets"][pos],
        "conceded": (mins / 90) * e_half * sc["goals_conceded"][pos],
        "saves": (pr.saves * mins * m_def / 3) * sc["saves"] if pos == "GKP" else 0.0,
        "defcon": p60 * pr.defcon_p * sc["defensive_contribution"][pos],
        "bonus": pr.bonus * mins * sc["bonus"],
        "cards": pr.yellow * mins * sc["yellow_cards"],
    }
    c["total"] = sum(c.values())
    c["p_goal"] = 1 - math.exp(-pr.xg * mins * m_att)
    c["p_return"] = 1 - math.exp(-(pr.xg + pr.xa) * mins * m_att)
    return c


def availability(status: str, chance: int | None, offset: int) -> float:
    """FPL's flag applies to the next gameweek. Later: unavailable players stay out;
    players flagged injured with 0% are assumed half-likely back the following week and
    fully back after that (a heuristic, stated in the README)."""
    if offset == 0:
        if chance is not None:
            return chance / 100
        return 0.0 if status in ("u", "n", "s", "i") else 1.0
    if status == "u":
        return 0.0
    if status in ("i", "n") and (chance or 0) == 0:
        return 0.5 if offset == 1 else 1.0
    return 1.0


# ---------------------------------------------------------------- live build
def _get_json(path: str):
    return json.loads(sources._get(f"{FPL}/{path}"))


def history_from_live(live: dict[int, dict]) -> dict[int, list[GW]]:
    out = defaultdict(list)
    for gw, payload in sorted(live.items()):
        for el in payload.get("elements", []):
            s = el["stats"]
            out[el["id"]].append(GW(gw, s["minutes"], float(s["expected_goals"] or 0), float(s["expected_assists"] or 0),
                                    s["saves"], s["bonus"], s["yellow_cards"], s.get("defensive_contribution", 0),
                                    s["total_points"]))
    return out


def scoring_from_api(bootstrap: dict) -> dict:
    api = bootstrap.get("game_config", {}).get("scoring", {})
    sc = {}
    for k, default in DEFAULT_SCORING.items():
        v = api.get(k)
        sc[k] = {p: v.get(p, default[p]) for p in default} if isinstance(default, dict) and isinstance(v, dict) \
            else (v if isinstance(v, (int, float)) and not isinstance(default, dict) else default)
    return sc


def chip_windows(bootstrap: dict) -> list[dict]:
    """Chips as the FPL API defines them: [{name, start, stop}], one entry per chip per half."""
    return [{"name": c["name"], "start": c["start_event"], "stop": c["stop_event"]} for c in bootstrap.get("chips", [])]


def plan_gameweeks(next_gw: int, windows: list[dict], last_gw: int) -> list[int]:
    """Gameweeks to project: the usual horizon, extended to the end of the chip window
    the next gameweek falls in, so every gameweek a current chip can be played is covered."""
    end = max((w["stop"] for w in windows if w["start"] <= next_gw <= w["stop"]), default=next_gw)
    return list(range(next_gw, min(last_gw, max(next_gw + HORIZON - 1, end)) + 1))


def build(bootstrap: dict, fixtures: list[dict], live: dict[int, dict], predictions: dict, now: datetime) -> dict:
    r = Ratings.from_predictions(predictions)
    teams = {t["id"]: t for t in bootstrap["teams"]}
    tname = {i: t["name"] for i, t in teams.items()}
    sc = scoring_from_api(bootstrap)
    events = bootstrap["events"]
    nxt = next((e for e in events if e.get("is_next")), None)
    if nxt is None:
        raise RuntimeError("no upcoming gameweek: the season may be over")
    gws = [g for g in range(nxt["id"], nxt["id"] + HORIZON) if any(e["id"] == g for e in events)]
    windows = chip_windows(bootstrap)
    plan_gws = plan_gameweeks(nxt["id"], windows, max(e["id"] for e in events))

    team_fixtures: dict[str, dict[int, list[Fixture]]] = defaultdict(lambda: defaultdict(list))
    played_gws: dict[str, set] = defaultdict(set)
    for f in fixtures:
        if f["event"] is None:
            continue
        h, a = tname[f["team_h"]], tname[f["team_a"]]
        if f.get("finished") or f.get("finished_provisional"):
            played_gws[h].add(f["event"]); played_gws[a].add(f["event"])
        elif f["event"] in plan_gws:
            team_fixtures[h][f["event"]].append(Fixture(f["event"], h, a, True, f["kickoff_time"]))
            team_fixtures[a][f["event"]].append(Fixture(f["event"], a, h, False, f["kickoff_time"]))

    histories = history_from_live(live)
    positions = {e["id"]: POS[e["element_type"]] for e in bootstrap["elements"]}
    priors = position_priors(histories, positions)

    players = []
    for e in bootstrap["elements"]:
        if not e.get("can_select", True) or e.get("removed"):
            continue
        team = tname[e["team"]]
        pr = profile(histories.get(e["id"], []), positions[e["id"]], sorted(played_gws[team]), priors)
        xp, nxt_c = [], None
        for i, gw in enumerate(plan_gws):
            avail = availability(e["status"], e["chance_of_playing_next_round"], i)
            comps = [fixture_points(pr, fx, r, sc, avail) for fx in team_fixtures[team].get(gw, [])]
            xp.append(round(sum(c["total"] for c in comps), 2))
            if i == 0:
                nxt_c = {k: round(sum(c[k] for c in comps), 3) for k in comps[0]} if comps else None
                if comps and len(comps) > 1:      # double gameweek: chance of at least one
                    nxt_c["p_goal"] = round(1 - math.prod(1 - c["p_goal"] for c in comps), 3)
                    nxt_c["p_return"] = round(1 - math.prod(1 - c["p_return"] for c in comps), 3)
        players.append({
            "id": e["id"], "name": e["web_name"], "full": f"{e['first_name']} {e['second_name']}".strip(),
            "team": team, "pos": positions[e["id"]], "price": e["now_cost"] / 10,
            "owned": float(e["selected_by_percent"] or 0), "status": e["status"],
            "chance": e["chance_of_playing_next_round"], "news": e["news"] or "",
            "points": e["total_points"], "minutes": e["minutes"],
            "p_play": round(pr.p_play, 3), "p60": round(pr.p60, 3), "exp_minutes": round(pr.exp_minutes, 1),
            "xp": xp[:len(gws)], "xp_total": round(sum(xp[:len(gws)]), 2), "next": nxt_c,
            "xp_plan": xp,
        })

    team_rows = []
    for t in sorted(tname.values()):
        cells = []
        for gw in gws:
            fxs = team_fixtures[t].get(gw, [])
            cells.append([{"opp": fx.opp, "home": fx.home, "xg_for": round(r.lam(t, fx.opp, fx.home)[0], 3),
                           "xg_against": round(r.lam(t, fx.opp, fx.home)[1], 3),
                           "cs": round(r.conceded(t, fx.opp, fx.home)[0], 3)} for fx in fxs])
        team_rows.append({"name": t, "short": next(x["short_name"] for x in teams.values() if x["name"] == t),
                          "fixtures": cells})

    return {
        "meta": {"generated": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "next_gw": nxt["id"], "deadline": nxt["deadline_time"],
                 "gws": gws, "plan_gws": plan_gws, "chips": windows, "data_through_gw": max(live) if live else 0, "scoring": sc,
                 "defcon_threshold": DEFCON_THRESHOLD, "budget": bootstrap["game_config"]["rules"]["squad_total_spend"] / 10,
                 "team_limit": bootstrap["game_config"]["rules"]["squad_team_limit"],
                 "squad": {POS[et["id"]]: et["squad_select"] for et in bootstrap["element_types"]},
                 "constants": {"form_gws": FORM_GWS, "rate_prior_minutes": RATE_PRIOR_MINUTES,
                               "defcon_prior_apps": DEFCON_PRIOR_APPS, "horizon": HORIZON},
                 "ratings_from": "site/data/predictions.json", "ratings_generated": predictions["meta"]["generated"]},
        "teams": team_rows,
        "players": players,
    }


def load_live(pause: float = 0.3) -> tuple[dict, list, dict]:
    bootstrap = _get_json("bootstrap-static/")
    fixtures = _get_json("fixtures/")
    done = sorted({f["event"] for f in fixtures if f["event"] and (f.get("finished") or f.get("finished_provisional"))})
    live = {}
    for gw in done:
        live[gw] = _get_json(f"event/{gw}/live/")
        time.sleep(pause)
    return bootstrap, fixtures, live


# ---------------------------------------------------------------- team IDs
TEAM_IDS = ROOT / "data" / "fpl_team_ids.txt"


def read_team_ids(path: Path = TEAM_IDS) -> list[str]:
    """One FPL team ID per line; blank lines and # comments ignored."""
    if not path.exists():
        return []
    ids = []
    for line in path.read_text().splitlines():
        line = line.split("#", 1)[0].strip()
        if line:
            if not line.isdigit():
                raise ValueError(f"{path}: {line!r} is not a numeric FPL team ID")
            ids.append(line)
    return ids


def fetch_entries(ids: list[str], current_gw: int) -> dict:
    """Latest squad and bank for each team ID (public FPL data, fetched server-side
    because the FPL API doesn't allow browsers on other sites to call it)."""
    out = {}
    for i in ids:
        try:
            entry = _get_json(f"entry/{i}/")
            picks = _get_json(f"entry/{i}/event/{current_gw}/picks/")
            history = _get_json(f"entry/{i}/history/")
        except Exception as e:
            print(f"Team {i}: could not fetch ({e})", file=sys.stderr)
            continue
        out[i] = {"name": entry.get("name") or i, "gw": current_gw,
                  "picks": [p["element"] for p in picks.get("picks", [])],
                  "bank": (picks.get("entry_history") or {}).get("bank", 0),
                  "chips_used": [{"name": c["name"], "event": c["event"]} for c in history.get("chips", [])]}
    return out


# ---------------------------------------------------------------- CLI
def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", nargs="?", default="build", choices=["build", "backtest"])
    ap.add_argument("--out", type=Path, default=SITE_DATA / "fpl.json")
    a = ap.parse_args(argv)
    if a.cmd == "backtest":
        from .fpl_backtest import main as bt
        bt(); return
    predictions = json.loads((SITE_DATA / "predictions.json").read_text())
    try:
        bootstrap, fixtures, live = load_live()
    except Exception as e:
        # Keep the last good file rather than publishing projections built on nothing.
        print(f"FPL API unavailable ({e}); keeping the existing {a.out.name}", file=sys.stderr)
        return
    now = datetime.now(timezone.utc)
    # Archive this run's team news first: it is the one input that can't be recovered later.
    from . import teamnews
    from .build import season_for
    n = teamnews.record(teamnews.path_for(season_for(now)), bootstrap, now)
    print(f"Team news: {n} player flag changes recorded")
    data = build(bootstrap, fixtures, live, predictions, now)
    a.out.write_text(json.dumps(data, separators=(",", ":")))
    current = next((e["id"] for e in bootstrap["events"] if e.get("is_current")), None)
    entries = fetch_entries(read_team_ids(), current) if current else {}
    (a.out.parent / "fpl-teams.json").write_text(json.dumps({"entries": entries}, separators=(",", ":")))
    top = sorted(data["players"], key=lambda p: -p["xp"][0])[:3] if data["players"] and data["meta"]["gws"] else []
    print(f"Wrote {a.out} · GW{data['meta']['next_gw']} · {len(data['players'])} players · top: "
          + ", ".join(f"{p['name']} {p['xp'][0]:.1f}" for p in top))


if __name__ == "__main__":
    main()
