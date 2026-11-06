"""Prospective evaluation: pre-kickoff ledger forecasts against closing odds and results.

    python -m predictor.prospective market   # append closing odds + results for finished matches
    python -m predictor.prospective report   # score ledger forecasts against the market

Timing: ledger forecasts are made by the daily build, typically hours to days before
kickoff, with no team news. Closing odds are the last prices before kickoff and can
reflect late team news. Both timestamps are kept, so the comparison stays
interpretable: the model is being asked to forecast earlier than the market.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import statistics
import sys
from datetime import datetime, timezone
from pathlib import Path

from . import benchmark, evaluate, ledger, sources
from .evaluate import Row

FD_URL = "https://www.football-data.co.uk/mmz4281/{code}/E0.csv"


def season_code(season: str) -> str:
    return season[2:4] + season[5:7]          # "2026-27" -> "2627"


def market_path(season: str, root: Path = ledger.LEDGER_DIR) -> Path:
    return root / f"market-{season}.jsonl"


def key(home: str, away: str, date: str) -> tuple[str, str, str]:
    return benchmark.canon(home), benchmark.canon(away), date


def record_market(season: str, raw: bytes, url: str, now: datetime, path: Path) -> int:
    """Append closing odds and results for finished matches not yet recorded."""
    existing = {key(r["home"], r["away"], r["date"]) for r in ledger.read(path)}
    sha = hashlib.sha256(raw).hexdigest()
    new = []
    for o in benchmark.parse_odds(raw):
        k = key(o.home, o.away, o.date)
        if k in existing or o.home_goals is None or not o.odds["average_closing"]:
            continue
        probs, over = benchmark.implied(o.odds["average_closing"])
        new.append({"schema": 1, "season": season, "date": o.date, "home": o.home, "away": o.away,
                    "result": [o.home_goals, o.away_goals], "retrieved_at": ledger._iso(now),
                    "source_url": url, "file_sha256": sha,
                    "closing_odds": {m: o.odds[m] for m in benchmark.MARKETS if o.odds[m]},
                    "average_closing_implied": {k2: round(v, 6) for k2, v in probs.items()},
                    "average_closing_overround": round(over, 6)})
        existing.add(k)
    if new:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a") as fh:
            for rec in new:
                fh.write(json.dumps(rec, separators=(",", ":"), sort_keys=True) + "\n")
    return len(new)


def score(predictions: list[dict], market: list[dict]) -> dict:
    """Join each fixture's last pre-kickoff forecast to its closing odds and result."""
    forecasts = ledger.latest_before_kickoff(predictions)
    by_key = {key(m["home"], m["away"], m["date"]): m for m in market}
    rows, model_p, market_p, lead_hours, unmatched = [], [], [], [], []
    for f in sorted(forecasts.values(), key=lambda r: r["kickoff"]):
        m = by_key.get(key(f["home"], f["away"], benchmark.uk_date(f["kickoff"])))
        if m is None:
            unmatched.append(f"GW{f['gw']} {f['home']} v {f['away']}")
            continue
        hg, ag = m["result"]
        outcome = "H" if hg > ag else "A" if hg < ag else "D"
        rows.append(Row(f["season"], f["gw"], f["home"], f["away"], outcome, hg, ag, *f["expected_goals"]))
        model_p.append(f["probabilities"]); market_p.append(m["average_closing_implied"])
        k = datetime.fromisoformat(f["kickoff"].replace("Z", "+00:00"))
        p = datetime.fromisoformat(f["predicted_at"].replace("Z", "+00:00"))
        lead_hours.append((k - p).total_seconds() / 3600)
    out = {"forecasts": len(forecasts), "scored": len(rows), "awaiting_result_or_odds": unmatched,
           "model_versions": sorted({f["model_version"] for f in forecasts.values()})}
    if rows:
        out["lead_time_hours"] = {"min": min(lead_hours), "median": statistics.median(lead_hours),
                                  "max": max(lead_hours)}
        out["comparison"] = benchmark.compare(rows, model_p, market_p) if len(rows) >= 2 else None
    return out


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["market", "report"])
    ap.add_argument("--season", default=None)
    a = ap.parse_args(argv)
    from .build import season_for
    now = datetime.now(timezone.utc)
    season = a.season or season_for(now)
    if a.cmd == "market":
        url = FD_URL.format(code=season_code(season))
        try:
            raw = sources._get(url)
        except Exception as e:
            print(f"Closing odds unavailable ({e}); nothing recorded", file=sys.stderr)
            return
        n = record_market(season, raw, url, now, market_path(season))
        print(f"Recorded closing odds for {n} new matches")
        return
    result = score(ledger.read(ledger.predictions_path(season)), ledger.read(market_path(season)))
    out = evaluate.EXPERIMENTS / f"prospective-{season}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"generated": ledger._iso(now), "season": season, **result}, indent=2))
    c = result.get("comparison")
    if c:
        d = c["log_loss_model_minus_market"]
        print(f"{result['scored']} prospective matches · model log loss {c['model']['log_loss']:.4f} · "
              f"market {c['market']['log_loss']:.4f} · difference {d['mean']:+.4f} [{d['ci_low']:+.4f}, {d['ci_high']:+.4f}]")
    else:
        print(f"{result['forecasts']} forecasts recorded, {result['scored']} scored so far")


if __name__ == "__main__":
    main()
