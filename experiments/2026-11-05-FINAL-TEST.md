# Held-out test — 2026-11-05

Run once, at commit `3b12340`, with both models frozen and the candidate nominated beforehand ([tuning report](2026-11-05-REPORT.md)). No parameter was changed after this run. Raw output: [`2026-11-05-final-test.json`](2026-11-05-final-test.json).

| | v0.1 (incumbent) | Candidate (nominated) |
|---|---|---|
| Prior games | 8 | 4 |
| Dixon-Coles ρ | −0.08 | 0 |
| Everything else | identical | identical |

Seasons: 2024-25 and 2025-26, 760 matches, walk-forward from GW1 with previous-season priors. Data: vaastav/Fantasy-Premier-League at `d7b05b51`.

## Result

| Model | Log loss | Brier | 1X2 accuracy | Mean draw prob | Actual draw rate |
|---|---|---|---|---|---|
| Base rates (last season's H/D/A) | 1.0841 | 0.6570 | 41.7% | 0.230 | 0.259 |
| v0.1 | 0.9991 | 0.5983 | 51.8% | 0.251 | 0.259 |
| **Candidate** | **1.0010** | **0.5992** | **51.7%** | **0.233** | **0.259** |

**Candidate − v0.1 log loss: +0.0019, 95% paired bootstrap interval [−0.0024, +0.0062].** The candidate is slightly worse, in both seasons, and the difference is not statistically distinguishable from zero.

| Season | v0.1 log loss | Candidate log loss | Draw rate |
|---|---|---|---|
| 2024-25 | 0.9614 | 0.9644 | 0.245 |
| 2025-26 | 1.0368 | 1.0376 | 0.274 |

**Unbiased estimate for the nominated candidate:** log loss 1.0010, Brier 0.5992, accuracy 51.7%.

## Secondary checks

- **Both models beat the base-rate baseline by about 0.085 log loss**, in both test seasons. This is the robust finding of the whole exercise.
- **Draws:** neither model picks a draw as its single most likely outcome (as expected). The test seasons had far more draws (24.5%, 27.4%) than the development seasons (22.2%). Setting ρ to 0 lowered predicted draw probability, which helped on development and hurt here.
- **Aggregate goals:** predicted 1.54 home / 1.30 away against 1.52 / 1.32 actual, for both models.
- **Calibration:** close in the bins holding most predictions. Outcomes given under 10% happened about 2% of the time (n = 44) for both models.

## Interpretation

The development-season gain did not replicate. The most likely explanation is the draw rate: it moved between periods, and ρ is the parameter that controls draws. Combined with the earlier chronological check, the evidence says these two parameters are sensitive to season-level conditions, and a 0.2% log loss difference is below what four seasons can resolve.

Any analysis or parameter change after this point is **exploratory** and must be labelled as such. The test seasons are no longer untouched for future model selection.
