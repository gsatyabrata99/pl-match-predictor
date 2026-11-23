# Lineup ceiling — results

Run 2026-11-22, exactly as registered in [`2026-11-22-LINEUP-PREREGISTRATION.md`](2026-11-22-LINEUP-PREREGISTRATION.md) (`ce06acf`). Study code committed before the run (`9e573a6`). Code: [`predictor/lineup.py`](../predictor/lineup.py). Raw output: [`2026-11-22-lineup.json`](2026-11-22-lineup.json). Regenerate: `python -m predictor.lineup`.

**Implementation note.** The first run stopped with an error before producing any result: 2024-25 contains 322 rows with position "AM", FPL's Assistant Manager chip entries (managers, not players). None ever started or played a minute, so excluding them (`a4d9ed7`) cannot change any lineup, usual XI or contribution in the registration. No other change was made between registration and run.

## Verdict: STOP

| | Required to build | Result |
|---|---|---|
| Pooled change in log loss (oracle − v0.1) | ≤ −0.005 (full) or ≤ −0.0025 (minimal), interval below zero | **+0.0023 [−0.0041, +0.0091]** |

Knowing the actual starting XIs, applied through the registered attack-side lineup factor, **did not improve** the forecasts; it made them slightly worse, within noise. Under the decision rule, phase 3 does not start. No production change follows.

## Primary outcome (1,140 matches, 2023-24 to 2025-26)

| | Log loss |
|---|---|
| v0.1 | 0.9777 |
| v0.1 + actual-lineup factor | 0.9800 |
| **Change** | **+0.0023 [−0.0041, +0.0091]** |

| Season | v0.1 | Oracle | Change (95% CI) |
|---|---|---|---|
| 2023-24 | 0.9350 | 0.9353 | +0.0003 [−0.0109, +0.0112] |
| 2024-25 | 0.9614 | 0.9619 | +0.0005 [−0.0096, +0.0104] |
| 2025-26 | 1.0368 | 1.0428 | +0.0060 [−0.0054, +0.0179] |

Worse or level in all three seasons.

Lineup factors: 2,280 team-matches; 60 had no earlier match that season (no adjustment), 0 lacked exactly 11 starters, 8 were capped. Mean factor 1.013.

## Secondary outcomes

| | v0.1 | Oracle |
|---|---|---|
| Brier | 0.5823 | 0.5833, change +0.0010 [−0.0034, +0.0055] |
| 1X2 accuracy | 53.5% | 53.3% |
| Mean draw probability (observed 0.245) | 0.244 | 0.242 |

**Against the closing market (2024-25 + 2025-26, 760 matches):** market 0.9893, v0.1 0.9991 (+0.0099 [−0.0025, +0.0216]), oracle 1.0023 (+0.0131 [−0.0006, +0.0266]). The lineup factor moved the model further from the market, not closer.

## Subgroup (registered): largest lineup changes

Top quarter of matches by max |log L| (285 matches): v0.1 1.0026 → oracle 1.0169, change **+0.0143 [−0.0060, +0.0366]**. The adjustment did worst exactly where lineups changed most, which is where it was meant to help.

## Exploratory defence check (does not affect the decision)

Opponent's actual xG ÷ v0.1's predicted xG: 1.005 when the usual goalkeeper and back line started (1,538 team-matches), 1.010 when the usual goalkeeper or 2+ usual defenders did not (682). Difference +0.005 [−0.041, +0.053]: no detectable effect of back-line changes on chances conceded, with an interval wide enough to hide a modest one.

## Interpretation

The closing market prices lineups, yet adding actual lineups through this mechanism did not help the model. Two readings, which this study cannot separate:

1. **The mechanism is wrong.** Per-player attacking output, even shrunk, is a noisy measure of a player's value to the team; rotated-in players often outperform their small-sample numbers, and teams adjust tactically around absences. The subgroup result (worst where changes were largest) points this way: the factor over-reacts.
2. **Lineup effects on match outcomes are small** once team strength is well estimated: most rotations swap players of similar quality.

Exploratory, not registered: a different specification (e.g. a partial adjustment, minutes-based rather than output-based value, or position-aware replacement levels) might do better, but choosing one after seeing these results would be post-hoc. Any such attempt would need a new registration and should be judged prospectively.

## What continues

The team-news archive (phase 1) keeps running: it costs nothing, and it is the only way to have genuine pre-match team-news data if a future, separately registered approach is worth testing. The production predictor stays v0.1.
