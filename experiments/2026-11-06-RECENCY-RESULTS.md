# Recency weighting — results

Run 2026-11-06, exactly as registered in [`2026-11-06-RECENCY-PREREGISTRATION.md`](2026-11-06-RECENCY-PREREGISTRATION.md) (committed `54d3e81` before any experiment code). Code: [`predictor/recency.py`](../predictor/recency.py). Raw output: [`2026-11-06-recency.json`](2026-11-06-recency.json). Regenerate: `python -m predictor.recency`.

Implementation checks (tests): with no decay the weighted fit reproduces production walk-forward forecasts to 1e-12; when every match has the same age, decay leaves ratings unchanged, confirming the registered prior-strength rule.

## Verdict: not nominated

| Nomination condition | Required | Result |
|---|---|---|
| Season-ahead choice beats no decay in ≥ 2 of 3 test seasons | ≥ 2 | **1** |
| Pooled 95% interval entirely below zero | upper < 0 | **+0.0022** |

Recency weighting is **not nominated** as a challenger. v0.1 stays the production model.

## Primary outcome (1,140 matches, 2023-24 to 2025-26)

| | Log loss |
|---|---|
| No decay (v0.1) | 0.9777 |
| Season-ahead choice | 0.9777 |
| **Change** | **−0.0001 [−0.0023, +0.0022]** |

| Test season | Half-life chosen (on) | No decay | Choice | Change (95% CI) |
|---|---|---|---|---|
| 2023-24 | 90 days (2022-23) | 0.9350 | 0.9360 | +0.0010 [−0.0033, +0.0056] |
| 2024-25 | none (2023-24) | 0.9614 | 0.9614 | 0.0000 |
| 2025-26 | 60 days (2024-25) | 1.0368 | 1.0356 | −0.0012 [−0.0060, +0.0039] |

## Secondary outcomes (same matches)

| | No decay | Choice |
|---|---|---|
| Brier | 0.5823 | 0.5820, change −0.0003 [−0.0019, +0.0013] |
| 1X2 accuracy | 53.5% | 53.8% |
| Mean draw probability (observed 0.245) | 0.244 | 0.245 |

Draw calibration by predicted-draw bin (n, predicted → observed):

| Bin | No decay | Choice |
|---|---|---|
| < 0.22 | 238, 0.186 → 0.202 | 235, 0.185 → 0.200 |
| 0.22–0.26 | 478, 0.242 → 0.247 | 471, 0.242 → 0.246 |
| 0.26–0.30 | 381, 0.276 → 0.265 | 385, 0.275 → 0.265 |
| ≥ 0.30 | 43, 0.309 → 0.279 | 49, 0.309 → 0.286 |

Draw calibration is good in both and essentially unchanged; both slightly overstate draws above 0.26.

## Subgroups (registered)

| Subgroup | n | No decay | Choice | Change (95% CI) |
|---|---|---|---|---|
| Changed teams | 510 | 0.9341 | 0.9347 | +0.0006 [−0.0026, +0.0040] |
| Promoted teams | 324 | 0.8820 | 0.8820 | −0.0000 [−0.0036, +0.0034] |

Changed teams: 2023-24 Arsenal, Liverpool, Man Utd, Nott'm Forest, Sheffield Utd; 2024-25 Bournemouth, Chelsea, Liverpool, Man City, Southampton; 2025-26 Arsenal, Leeds, Man Utd, Sunderland, Wolves. Promoted: the three promoted clubs each season.

Recency weighting did not help the teams it was expected to help most: those whose strength changed substantially, and newly promoted sides.

## All candidates, all seasons (log loss; reported, not used for selection)

| Season | none | 30 | 60 | 90 | 120 | 180 |
|---|---|---|---|---|---|---|
| 2022-23 | 0.9909 | 0.9904 | 0.9902 | 0.9902 | 0.9902 | 0.9903 |
| 2023-24 | 0.9350 | 0.9411 | 0.9370 | 0.9360 | 0.9356 | 0.9353 |
| 2024-25 | 0.9614 | 0.9577 | **0.9568** | 0.9576 | 0.9583 | 0.9592 |
| 2025-26 | 1.0368 | 1.0367 | 1.0356 | 1.0356 | 1.0357 | 1.0360 |

## Exploratory observations (not registered)

- A 60–90 day half-life is best or near-best in three of four seasons, and the one season with a clear gain (2024-25, −0.005 at 60 days) is exactly the one where season-ahead selection picked no decay, because decay hurt in 2023-24. The benefit is real in some seasons and negative in others, and the previous season does not predict which.
- This matches the pattern from the prior-strength and temperature studies: effects of a few thousandths of log loss that change sign between seasons. Four seasons cannot separate them from noise.

## Conclusion

The registered test is a clear null result. Recency weighting is not nominated, and no production change follows. Together with the earlier studies, the evidence suggests further reweighting of the same inputs has little to offer; the remaining gap to the closing market most plausibly needs new information (lineups, injuries, rest), which is a larger, separate decision.
