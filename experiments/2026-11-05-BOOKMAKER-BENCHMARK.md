# Bookmaker benchmark — 2026-11-05

Frozen production model (v0.1, `predictor/params.json`) against closing 1X2 market odds on the 2024-25 and 2025-26 seasons. The production model was not changed or tuned. Raw output: [`2026-11-05-bookmaker-benchmark.json`](2026-11-05-bookmaker-benchmark.json). Regenerate:

```bash
python -m predictor.benchmark --odds 2024-25=experiments/data/football-data/E0_2024-25.csv \
                              --odds 2025-26=experiments/data/football-data/E0_2025-26.csv
```

## Data

| | |
|---|---|
| Source | football-data.co.uk season files `mmz4281/2425/E0.csv` and `mmz4281/2526/E0.csv`, downloaded 2026-11-05; copies and SHA-256 hashes kept in `data/football-data/` and the JSON |
| Closing odds | Columns with "C" (e.g. `AvgCH`): football-data's last odds collected before kickoff |
| Primary market | **Market-average closing** (`AvgCH/AvgCD/AvgCA`): 760 of 760 matches |
| Secondary market | **Pinnacle closing** (`PSCH/PSCD/PSCA`): 590 of 760. The Pinnacle feed stops after 2026-01-08 (170 matches of 2025-26 missing), so it was not used as primary |
| Margin removal | Inverse odds normalised to sum to 1 (proportional). Mean overround: average 4.9%, Pinnacle 3.0%, Bet365 5.6% |
| Matching | On (season, home, away), then cross-checked on UK calendar date and final score. **760 of 760 matched; 0 unmatched, ambiguous, date or score mismatches** |

The set of bookmakers behind the market average differs between the two season files, so the consensus is not composed identically in both seasons.

## Headline (market-average closing, 760 matches)

| | Log loss | Brier | 1X2 accuracy | Mean draw prob (actual 0.259) |
|---|---|---|---|---|
| **Model (v0.1)** | **0.9991** | **0.5983** | **51.8%** | **0.251** |
| Closing market | 0.9893 | 0.5915 | 52.5% | 0.241 |
| Base rates (for scale) | 1.0841 | 0.6570 | 41.7% | 0.230 |

**Model − market log loss: +0.0099, 95% paired bootstrap interval [−0.0025, +0.0216].** Brier: +0.0069 [−0.0017, +0.0151].

The market is about 1% better on log loss; the interval narrowly includes zero. Measured against the gap from base rates to the market (0.095), the model closes about 90% of it.

| Season | Model log loss | Market log loss | Model − market (95% CI) | Model / market accuracy |
|---|---|---|---|---|
| 2024-25 | 0.9614 | 0.9667 | −0.0053 [−0.0235, +0.0139] | 55.0% / 55.5% |
| 2025-26 | 1.0368 | 1.0118 | **+0.0250 [+0.0085, +0.0411]** | 48.7% / 49.5% |

In 2024-25 the model matched the closing market (nominally slightly better). In 2025-26 the market was clearly better.

Pinnacle closing (590 matches) tells the same story: model 0.9822 against 0.9739, difference +0.0083 [−0.0067, +0.0236]; 2024-25 −0.0050, 2025-26 (to 8 January) +0.0323 [+0.0106, +0.0537].

## Model versus market probabilities

Every outcome of every match, grouped by the market's probability:

| Market band | n | Market | Model | Observed |
|---|---|---|---|---|
| 0.00–0.20 | 413 | 0.147 | 0.176 | 0.136 |
| 0.20–0.35 | 1081 | 0.265 | 0.273 | 0.276 |
| 0.35–0.50 | 383 | 0.422 | 0.417 | 0.428 |
| 0.50–0.65 | 262 | 0.570 | 0.530 | 0.534 |
| 0.65–1.00 | 141 | 0.727 | 0.660 | 0.723 |

**The model is under-confident, not over-confident.** It pulls probabilities toward the middle: longshots the market prices at 15% get 18% from the model and win 14% of the time; strong favourites the market prices at 73% get 66% and win 72%. Regressing model probability on market probability gives a slope of **0.85** (1.0 = same sharpness); the model's probabilities spread 0.150 from one-third against the market's 0.166. The pattern holds in both seasons (slopes 0.83 and 0.88). The model and market pick the same favourite in 90% of matches.

The 0.50–0.65 band is the exception: there the model (0.530) is closer to the observed rate (0.534) than the market (0.570).

**Draws:** the model's mean draw probability (0.251) is closer to the observed rate (0.259) than the market's (0.241). Neither picks a draw as the most likely result.

## Interpretation

- The model is **close to, but on these seasons slightly behind, the closing market**: within 1% on log loss pooled, level in 2024-25, clearly behind in 2025-26. For a model with no team news, injuries or lineups, that is a strong result; the closing line is the hardest public benchmark.
- The main measurable weakness is **under-confidence at the extremes**, especially for strong favourites. Likely contributors are the prior and the xG/goals blend, which both shrink ratings toward average. This is a lead for future work, not a reason to change production: tuning against these seasons would use previously inspected data.
- 2025-26 was harder for the model on every comparison so far (more draws, larger gap to the market).

## Caveats

- Proportional normalisation is a simple no-vig method. It assigns the margin evenly, while bookmakers typically shade longshots more (the favourite-longshot bias). Methods such as Shin's or a power method would make the market's favourites slightly stronger and longshots weaker, which would most likely make the market a little *sharper* still. Worth checking given the gap is about 0.01.
- 760 matches over two seasons. The pooled interval includes zero; the 2025-26 interval does not.
- 2024-26 was already inspected in the held-out test, so these numbers are a description of the frozen model, not a fresh out-of-sample test.

## Research leads (exploratory; not production changes)

1. Sharpness: test whether a less-shrunk model (or a calibration step) fixes the favourite under-confidence, validated chronologically and on new fixtures.
2. Margin removal: rerun with Shin and power methods to bound how much the method matters.
3. Live benchmark: record closing odds for 2026-27 fixtures as they are played, for a genuinely untouched comparison.
