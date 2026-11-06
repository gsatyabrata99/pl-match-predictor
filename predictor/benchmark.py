"""Bookmaker benchmark: the frozen production model against closing 1X2 market odds.

    python -m predictor.benchmark --odds 2024-25=E0_2425.csv --odds 2025-26=E0_2526.csv

Odds come from football-data.co.uk season files (E0.csv). Closing odds are the
columns with a "C" before the outcome letter:

    AvgCH/AvgCD/AvgCA  market-average closing (primary: full coverage of 2024-26)
    PSCH/PSCD/PSCA     Pinnacle closing (secondary: sharp, low margin, but football-data's
                       Pinnacle feed stops after 2026-01-08, so it covers 590 of 760 matches)
    B365CH/...         Bet365 closing (reported for coverage only)

Implied probabilities are 1/odds normalised to sum to 1 (proportional margin
removal). Fixtures are matched on (season, home, away), which is unique within a
season, and every match is then cross-checked on UK calendar date and final score.
Anything that fails a check is reported and excluded, never silently matched.

This module only reads the production model; it never changes or tunes it.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
import shutil
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from . import evaluate, model
from .evaluate import Row

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "experiments"
DATA_DIR = OUT_DIR / "data" / "football-data"
UK = ZoneInfo("Europe/London")

# football-data.co.uk team name -> FPL team name. Unknown names raise, so a new
# promoted club can't be matched by accident.
TEAM_NAMES = {
    "Arsenal": "Arsenal", "Aston Villa": "Aston Villa", "Bournemouth": "Bournemouth",
    "Brentford": "Brentford", "Brighton": "Brighton", "Burnley": "Burnley", "Chelsea": "Chelsea",
    "Coventry": "Coventry City", "Hull": "Hull City",
    "Crystal Palace": "Crystal Palace", "Everton": "Everton", "Fulham": "Fulham",
    "Ipswich": "Ipswich", "Leeds": "Leeds", "Leicester": "Leicester", "Liverpool": "Liverpool",
    "Luton": "Luton", "Man City": "Man City", "Man United": "Man Utd", "Newcastle": "Newcastle",
    "Nott'm Forest": "Nott'm Forest", "Sheffield United": "Sheffield Utd",
    "Southampton": "Southampton", "Sunderland": "Sunderland", "Tottenham": "Spurs",
    "West Ham": "West Ham", "Wolves": "Wolves",
}

# FPL renames some clubs between seasons (Ipswich in 2024-25, Ipswich Town in 2026-27).
# Matching compares canonical names on both sides.
FPL_ALIASES = {"Ipswich Town": "Ipswich"}


def canon(name: str) -> str:
    return FPL_ALIASES.get(name, name)


MARKETS = {
    "pinnacle_closing": ("PSCH", "PSCD", "PSCA"),
    "average_closing": ("AvgCH", "AvgCD", "AvgCA"),
    "bet365_closing": ("B365CH", "B365CD", "B365CA"),
}
PRIMARY, SECONDARY = "average_closing", "pinnacle_closing"


class UnknownTeamError(ValueError):
    pass


@dataclass
class OddsRow:
    line: int
    date: str            # ISO date, UK calendar
    home: str            # FPL names
    away: str
    home_goals: int | None
    away_goals: int | None
    odds: dict[str, tuple[float, float, float] | None] = field(default_factory=dict)


@dataclass
class MatchReport:
    matched: list[tuple[Row, OddsRow]]
    unmatched_odds: list[str]
    unmatched_fixtures: list[str]
    date_mismatches: list[str]
    score_mismatches: list[str]
    ambiguous: list[str]


def _float(v: str | None) -> float | None:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if x > 1.0 else None


def _date(v: str) -> str:
    for fmt in ("%d/%m/%Y", "%d/%m/%y"):
        try:
            return datetime.strptime(v.strip(), fmt).date().isoformat()
        except ValueError:
            continue
    raise ValueError(f"unrecognised date {v!r}")


def parse_odds(raw: bytes) -> list[OddsRow]:
    text = raw.decode("utf-8-sig", errors="strict") if raw[:3] == b"\xef\xbb\xbf" else raw.decode("latin-1")
    out = []
    for i, r in enumerate(csv.DictReader(io.StringIO(text)), start=2):
        if not (r.get("HomeTeam") or "").strip():
            continue
        names = []
        for key in ("HomeTeam", "AwayTeam"):
            name = r[key].strip()
            if name not in TEAM_NAMES:
                raise UnknownTeamError(f"line {i}: unknown team {name!r}; add it to TEAM_NAMES")
            names.append(TEAM_NAMES[name])
        odds = {}
        for market, cols in MARKETS.items():
            vals = tuple(_float(r.get(c)) for c in cols)
            odds[market] = vals if all(vals) else None
        hg, ag = r.get("FTHG", ""), r.get("FTAG", "")
        out.append(OddsRow(i, _date(r["Date"]), names[0], names[1],
                           int(hg) if hg.strip() else None, int(ag) if ag.strip() else None, odds))
    return out


def implied(odds: tuple[float, float, float]) -> tuple[dict[str, float], float]:
    """Proportional margin removal. Returns ({H, D, A}: probability, overround)."""
    inv = [1 / o for o in odds]
    total = sum(inv)
    return dict(zip("HDA", (x / total for x in inv))), total - 1


def uk_date(kickoff_utc: str) -> str:
    dt = datetime.fromisoformat(kickoff_utc.replace("Z", "+00:00"))
    return dt.astimezone(UK).date().isoformat()


def match(rows: list[Row], kickoffs: dict[tuple[str, str], str], odds_rows: list[OddsRow]) -> MatchReport:
    by_pair: dict[tuple[str, str], list[OddsRow]] = {}
    for o in odds_rows:
        by_pair.setdefault((canon(o.home), canon(o.away)), []).append(o)
    rep = MatchReport([], [], [], [], [], [])
    seen = set()
    for r in rows:
        key = (r.home, r.away)
        cands = by_pair.get((canon(r.home), canon(r.away)), [])
        label = f"{r.season} GW{r.gw} {r.home} v {r.away}"
        if not cands:
            rep.unmatched_fixtures.append(label); continue
        if len(cands) > 1:
            rep.ambiguous.append(f"{label}: {len(cands)} odds rows (lines {[c.line for c in cands]})"); continue
        o = cands[0]
        seen.add((canon(r.home), canon(r.away)))
        if o.date != uk_date(kickoffs[key]):
            rep.date_mismatches.append(f"{label}: odds {o.date}, fixture {uk_date(kickoffs[key])}"); continue
        if (o.home_goals, o.away_goals) != (r.home_goals, r.away_goals):
            rep.score_mismatches.append(f"{label}: odds file {o.home_goals}-{o.away_goals}, FPL {r.home_goals}-{r.away_goals}")
            continue
        rep.matched.append((r, o))
    rep.unmatched_odds = [f"line {o.line}: {o.date} {o.home} v {o.away}" for o in odds_rows if (canon(o.home), canon(o.away)) not in seen]
    return rep


# ---------------------------------------------------------------- comparison
def bands(rows: list[Row], model_p: list[dict], market_p: list[dict], edges=(0, .2, .35, .5, .65, 1.0001)) -> list[dict]:
    """For every outcome of every match, grouped by the MARKET's probability:
    mean market probability, mean model probability, observed frequency."""
    out = []
    for lo, hi in zip(edges, edges[1:]):
        pts = [(mk[k], md[k], r.outcome == k) for r, md, mk in zip(rows, model_p, market_p) for k in "HDA"
               if lo <= mk[k] < hi]
        if pts:
            out.append({"market_band": f"{lo:.2f}-{min(hi, 1):.2f}", "n": len(pts),
                        "market": sum(p[0] for p in pts) / len(pts), "model": sum(p[1] for p in pts) / len(pts),
                        "observed": sum(p[2] for p in pts) / len(pts)})
    return out


def disagreement(rows, model_p, market_p) -> dict:
    """How the model's probabilities relate to the market's, outcome by outcome."""
    xs = [mk[k] for mk in market_p for k in "HDA"]
    ys = [md[k] for md in model_p for k in "HDA"]
    mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
    slope = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sum((x - mx) ** 2 for x in xs)
    spread = lambda ps: math.sqrt(sum((p - 1 / 3) ** 2 for p in ps) / len(ps))
    fav_agree = sum(max(md, key=md.get) == max(mk, key=mk.get) for md, mk in zip(model_p, market_p)) / len(rows)
    return {"mean_abs_diff": sum(abs(x - y) for x, y in zip(xs, ys)) / len(xs),
            "slope_model_on_market": slope,
            "spread_model": spread(ys), "spread_market": spread(xs),
            "favourite_agreement": fav_agree}


def compare(rows: list[Row], model_p: list[dict], market_p: list[dict]) -> dict:
    ll_model = evaluate.per_match_log_loss(rows, model_p)
    ll_market = evaluate.per_match_log_loss(rows, market_p)
    br = lambda ps: [sum((p[k] - (k == r.outcome)) ** 2 for k in "HDA") for r, p in zip(rows, ps)]
    mean, lo, hi = evaluate.paired_ci(ll_market, ll_model)
    bmean, blo, bhi = evaluate.paired_ci(br(market_p), br(model_p))
    return {"model": evaluate.metrics(rows, model_p), "market": evaluate.metrics(rows, market_p),
            "log_loss_model_minus_market": {"mean": mean, "ci_low": lo, "ci_high": hi},
            "brier_model_minus_market": {"mean": bmean, "ci_low": blo, "ci_high": bhi},
            "bands": bands(rows, model_p, market_p), "disagreement": disagreement(rows, model_p, market_p)}


def run(odds_files: dict[str, Path]) -> dict:
    cfg = model.Config.load(evaluate.PARAMS)
    seasons = sorted(odds_files)
    evaluate.guard(seasons, final=True)   # reporting against previously inspected seasons, not selection
    data = {s: evaluate.load(s) for s in evaluate.needed(seasons)}

    all_rows, all_model, markets, coverage, matching, files = [], [], {m: [] for m in MARKETS}, {}, {}, {}
    overrounds = {m: [] for m in MARKETS}
    for s in seasons:
        raw = Path(odds_files[s]).read_bytes()
        files[s] = {"sha256": hashlib.sha256(raw).hexdigest(), "rows": None}
        odds_rows = parse_odds(raw)
        files[s]["rows"] = len(odds_rows)
        rows = evaluate.walk_forward(s, data[s], data[evaluate.previous_season(s)], cfg)
        kickoffs = {(m.home, m.away): m.kickoff for m in data[s]}
        rep = match(rows, kickoffs, odds_rows)
        matching[s] = {"fixtures": len(rows), "odds_rows": len(odds_rows), "matched": len(rep.matched),
                       "unmatched_fixtures": rep.unmatched_fixtures, "unmatched_odds": rep.unmatched_odds,
                       "date_mismatches": rep.date_mismatches, "score_mismatches": rep.score_mismatches,
                       "ambiguous": rep.ambiguous}
        coverage[s] = {m: sum(o.odds[m] is not None for _, o in rep.matched) for m in MARKETS}
        mp = evaluate.probabilities([r for r, _ in rep.matched], cfg.rho)
        for (r, o), p in zip(rep.matched, mp):
            all_rows.append(r); all_model.append(p)
            for m in MARKETS:
                if o.odds[m]:
                    probs, over = implied(o.odds[m]); markets[m].append(probs); overrounds[m].append(over)
                else:
                    markets[m].append(None)

    result = {"generated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
              "model_params": cfg.to_dict(), "mirror_ref": evaluate.MIRROR_REF, "odds_files": files,
              "matching": matching, "coverage": coverage,
              "mean_overround": {m: (sum(v) / len(v) if v else None) for m, v in overrounds.items()},
              "comparisons": {}}
    for m in (PRIMARY, SECONDARY):
        idx = [i for i, p in enumerate(markets[m]) if p is not None]
        sub = lambda xs: [xs[i] for i in idx]
        entry = {"n": len(idx), "pooled": compare(sub(all_rows), sub(all_model), sub(markets[m])), "per_season": {}}
        for s in seasons:
            si = [i for i in idx if all_rows[i].season == s]
            entry["per_season"][s] = compare([all_rows[i] for i in si], [all_model[i] for i in si],
                                             [markets[m][i] for i in si])
        result["comparisons"][m] = entry
    return result


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--odds", action="append", required=True, metavar="SEASON=PATH",
                    help="football-data.co.uk E0.csv for a season, e.g. 2024-25=E0_2425.csv")
    ap.add_argument("--out", type=Path, default=OUT_DIR / "bookmaker-benchmark.json")
    ap.add_argument("--keep-data", action="store_true", help="copy the odds files into experiments/data/")
    a = ap.parse_args(argv)
    files = dict(x.split("=", 1) for x in a.odds)
    files = {s: Path(p) for s, p in files.items()}
    if a.keep_data:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        for s, p in list(files.items()):
            dest = DATA_DIR / f"E0_{s}.csv"
            shutil.copyfile(p, dest)
            files[s] = dest
    result = run(files)
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(result, indent=2))
    print(f"Wrote {a.out}")


if __name__ == "__main__":
    main()
