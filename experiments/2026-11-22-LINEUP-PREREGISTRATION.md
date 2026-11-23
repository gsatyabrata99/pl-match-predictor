# Lineup ceiling — pre-registration

Team-news project, phase 2. Registered 2026-11-22, approved by the project owner with three amendments (corrected defence-data wording, a three-outcome decision rule, an exploratory defence check), and committed **before any study code was written**. Anything not defined here is reported as exploratory.

## Question

If the match predictor had known each team's **actual starting XI** before kickoff, how much better would its forecasts have been? This is an upper bound ("oracle") on the value of lineup and injury information. It decides whether phase 3 (a realistic version using only pre-match team news) is worth building.

## Data

- vaastav/Fantasy-Premier-League at the pinned commit `d7b05b51`, seasons 2022-23 to 2025-26 (2022-23 only as the prior for 2023-24).
- Starting XI: players with `starts = 1` for that fixture and team. Team-matches without exactly 11 starters (2 of 2,280) keep the unadjusted forecast and are reported.
- Test seasons: **2023-24, 2024-25, 2025-26** (1,140 matches): the seasons with complete per-player xG and starting XIs. All have been inspected before for the match model, but never with lineup information.

## Fixed

Production model v0.1 (`predictor/params.json`) and the existing walk-forward rule: each gameweek predicted from matches that kicked off before it began, with the previous season as prior. The only change is a lineup factor on each side's expected goals. The production predictor is not modified; the study lives in research code.

## Lineup factor (one specification, no tuning)

For each player before each match, his attacking contribution is
c = (season-to-date xG + xA + 450 × positional average rate) ÷ (season-to-date minutes + 450) × 90,
i.e. per-90 output shrunk toward his position's average by 450 minutes, as in the FPL model. Only matches before the forecast gameweek are used.

For a team in a match:

- **Usual XI**: the 11 players with the most minutes for that team over its previous 5 matches in the season (before gameweek 6: all its matches so far; before its first match: no adjustment).
- **L = Σ c over the actual starters ÷ Σ c over the usual XI.**
- The team's expected goals become λ × L. The opponent's expected goals are unchanged (attack side only; see limitations). The scoreline grid and ρ are as in production.

L is capped to [0.6, 1.4] to keep a single data error from dominating; the number of capped team-matches is reported.

## Primary outcome

Pooled mean log loss on the 1,140 test matches, oracle model minus v0.1, with a paired per-match bootstrap (2,000 resamples, seed 7) 95% interval.

## Secondary outcomes

Brier score, 1X2 accuracy, mean predicted draw probability against observed; per-season results; and on 2024-25 + 2025-26, the oracle model against closing market odds (market-average closing, proportional margin removal, as in the bookmaker benchmark).

## Subgroup

Matches where either team's lineup differs most from its usual XI: the top quarter of matches by max(|log L_home|, |log L_away|). Oracle minus v0.1 log loss with paired interval.

## Decision rule (three outcomes)

Let Δ = pooled log loss of the oracle model minus v0.1 (negative = oracle better), with its 95% interval.

- **Build phase 3** if Δ ≤ −0.005 (about half the measured 0.0099 gap between v0.1 and the closing market) **and** the interval lies entirely below zero.
- **Build only a minimal phase 3** (adjusting for players flagged as out, judged prospectively) if −0.005 < Δ ≤ −0.0025 **and** the interval lies entirely below zero.
- **Stop** otherwise: team news through this mechanism is not worth building.

No production change follows from any outcome.

## Exploratory defence check (secondary; does not affect the decision)

For each team in each test match: its **usual goalkeeper** is the goalkeeper with the most minutes over its previous 5 matches in the season, and its **usual defenders** are the 4 defenders with the most minutes over the same matches (same windows as the usual XI). The team-match is **flagged** if the usual goalkeeper did not start, or at least 2 usual defenders did not start. Team-matches with no previous matches are excluded.

Measure: the ratio of the opponent's actual xG to the opponent's v0.1 expected goals (Σ actual ÷ Σ predicted), for flagged and unflagged team-matches, and the difference between the two ratios with a bootstrap 95% interval (2,000 resamples over team-matches, seed 7). Reported as exploratory only.

## Limitations stated in advance

- Attack side only in the primary test. FPL does record each player's expected goals conceded, but it is the team's xG against while he was on the pitch: in 2024-25, all full-match starters had the identical value in 697 of 760 team-matches. It measures the team, not the individual, and separating individuals needs far more lineup variation than a football season provides. Missing defenders and goalkeepers are therefore not modelled in the primary test (see the exploratory check), and the ceiling found here understates the full value of lineup information.
- The oracle uses information published about 60 minutes before kickoff. Phase 3 would rely on earlier, less complete news (injury flags), so its value can only be lower than the attack-side ceiling.
- The usual-XI definition and the cap are choices made here, not tuned; a pass or fail is conditional on them.
