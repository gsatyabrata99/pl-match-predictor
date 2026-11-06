# Recency weighting — pre-registration

Registered 2026-11-06, approved by the project owner, committed **before any recency experiment code was written or run**. The results report will be checked against this document; anything not defined here is reported as exploratory.

## Question

Does exponential recency weighting of current-season matches improve v0.1's forecasts, with everything else held fixed?

## Fixed

- Production parameters (v0.1): xG weight 0.7, no-xG weight 0.5, prior 8 games, prior shrink 0.75, league-average prior 0, Dixon-Coles ρ = −0.08.
- Previous-season prior: built exactly as in production (full, unweighted fit of the previous season).
- League home/away averages: unweighted current-season averages, exactly as in production.
- Data: vaastav/Fantasy-Premier-League at `d7b05b51`, seasons 2021-22 to 2025-26.
- Walk-forward rule: each gameweek predicted from matches that kicked off before that gameweek's first kickoff.
- The production predictor is not modified. The weighted fit lives in research code.

## Candidates

No decay (= v0.1), and half-lives h ∈ {30, 60, 90, 120, 180} days.

## Weighting

For a forecast made at cutoff time c, a current-season match played at time tᵢ gets decay weight dᵢ = 2^(−(c − tᵢ)/h), with (c − tᵢ) in days. This multiplies the match's existing signal weight (1.0 with xG, 0.5 without) in every sum of the rating solver.

## Prior strength (held constant relative to the data)

Without decay, a team with n (signal-weighted) matches combines its data with a prior worth 8 games, so the prior's share is 8 : n.

With decay, the team's decayed data total is Σdᵢwᵢ. Its prior weight is set to **8 × (Σdᵢwᵢ / Σwᵢ)**, i.e. 8 times the team's average decay weight. The prior-to-data ratio is then 8 : n, the same as without decay. Recency changes *which* matches count most within the season, not how much the season counts against the prior.

## Validation

Season-ahead: for each test season t ∈ {2023-24, 2024-25, 2025-26}, the half-life (including no decay) is chosen by lowest mean log loss on season t−1 alone, then evaluated on t. Selection seasons: 2022-23 → 2023-24, 2023-24 → 2024-25, 2024-25 → 2025-26. Every candidate's results are also reported for every season (2022-23 to 2025-26).

## Primary outcome

Pooled mean log loss of the season-ahead choices on the three test seasons (1,140 matches), against no decay on the same matches. Paired per-match bootstrap, 2,000 resamples, seed 7, 95% interval.

## Secondary outcomes

On the same matches: Brier score, 1X2 accuracy, mean predicted draw probability against observed draw rate, and draw calibration in bins of predicted draw probability: < 0.22, 0.22–0.26, 0.26–0.30, ≥ 0.30. Paired intervals for Brier.

## Subgroups (season-ahead choice vs no decay, log loss difference with paired interval)

1. **Changed teams.** For each team-season, change = |log(net_end) − log(net_prior)|, where net = attack ÷ defence, net_prior is the team's start-of-season prior and net_end is the production v0.1 fit on all of that season's matches (with its prior). The top quarter of teams per season (5 of 20) are "changed". Subgroup = matches involving at least one changed team. (This uses end-of-season information to define the group; acceptable for a diagnostic.)
2. **Promoted teams.** Matches involving a team promoted that season (not in the previous season's league).
3. **Draws.** The draw calibration above.

## Nomination rule

Recency weighting is nominated as a challenger to v0.1 only if **both**:

- the season-ahead choice has lower log loss than no decay in at least 2 of the 3 test seasons, and
- the pooled 95% interval for (choice − no decay) lies entirely below zero.

All seasons used here have been inspected before. A pass therefore only nominates a challenger; it does not deploy one. Deployment would require prospective evidence against v0.1 and a separate decision. No production change follows automatically from any result.
