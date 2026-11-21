# FPL expected points — backtest

2026-11-13. Model committed in `aa37118` with its constants fixed **before** this backtest was written or run; nothing was tuned afterwards. Code: [`predictor/fpl_backtest.py`](../predictor/fpl_backtest.py). Raw output: [`fpl-backtest-2025-26.json`](fpl-backtest-2025-26.json). Regenerate: `python -m predictor.fpl backtest`.

## Protocol

- Season 2025-26 (same scoring rules as 2026-27, including defensive contributions), gameweeks 5–38.
- Walk-forward: each gameweek is forecast from earlier gameweeks only. Team ratings are fitted on matches that kicked off before the gameweek began, with 2024-25 as the prior and the production parameters (v0.1), exactly as the match predictor works.
- Players are scored once they have played any minutes earlier in the season: 16,146 player-gameweeks over 34 gameweeks.
- **No injury or availability information** is available historically, so the model gets none here. The live tool uses FPL's flags.
- Baselines, with the same minutes model: points per appearance so far × chance of playing (**ppg**), and the average over the last 5 team gameweeks (**recent**).

## Results

| | Model | ppg | recent |
|---|---|---|---|
| Mean absolute error | **1.607** | 1.633 | 1.699 |
| RMSE | **2.521** | 2.580 | 2.698 |
| Bias (predicted − actual) | +0.01 | −0.02 | +0.02 |
| Mean Spearman rank correlation per GW | **0.573** | 0.557 | 0.539 |
| Actual points of the top 11 predicted, per GW | **53.4** | 46.7 | 42.8 |
| Actual points of the top predicted (captain), per GW | 6.44 | 6.44 | 4.03 |

Paired difference in absolute error, model − baseline (95% bootstrap interval):

- vs ppg: **−0.026 [−0.036, −0.016]**
- vs recent: **−0.092 [−0.107, −0.077]**

The model is more accurate than both baselines, and ranks players better. The largest practical gain is in selecting a team: its top 11 scored 6.7 more points a gameweek than the ppg baseline's. Captaincy ties with ppg: both picked the same player in 20 of 34 gameweeks, and the different picks balanced out.

## Calibration

| Predicted | n | Mean predicted | Mean actual |
|---|---|---|---|
| 0–1 | 5,891 | 0.29 | 0.55 |
| 1–2 | 2,971 | 1.50 | 1.71 |
| 2–3 | 2,855 | 2.51 | 2.35 |
| 3–4 | 2,921 | 3.48 | 3.09 |
| 4–5 | 1,188 | 4.38 | 3.94 |
| 5–6 | 207 | 5.36 | 4.59 |
| 6+ | 113 | 7.43 | 6.90 |

Projections are **too spread out**: high projections run 0.4–0.8 points above outcomes, low ones about 0.25 below. Part of the high-end gap is that the backtest has no injury news (players who then miss a match still get a full projection); the rest is genuine over-confidence, mostly in minutes. Not corrected: any adjustment fitted here would be tuned on this season. A candidate for a properly validated follow-up.

By position (n, predicted, actual, MAE): GKP 1,049 / 2.38 / 2.09 / 1.71 · DEF 5,662 / 1.93 / 1.87 / 1.75 · MID 7,523 / 1.80 / 1.84 / 1.48 · FWD 1,912 / 1.92 / 2.00 / 1.63. Goalkeepers are over-projected by about 0.3.

## Reading the numbers

FPL points are very noisy (a typical absolute error of 1.6 points against an average of about 1.9), so no model predicts individual gameweeks well. What matters for decisions is ranking: who to start, buy and captain. On that the model is better than the obvious alternatives, but expected points are a guide, not a forecast to trust to the decimal.
