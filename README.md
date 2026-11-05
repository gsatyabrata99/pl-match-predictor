# Premier League Match Predictor

Win, draw and loss probabilities for every Premier League fixture, from an expected-goals (xG) model that refreshes itself every day.

- **Gameweek view:** every upcoming match with its three-way probabilities, expected goals and likeliest score
- **Matchup view:** any two teams, with a full scoreline heatmap plus over 2.5 goals, both teams to score, clean sheets and fair odds
- **Team ratings:** schedule-adjusted attack and defence ratings for all 20 clubs
- **Track record:** how the model performs on matches it has not seen
- **How it works:** a plain-English walkthrough of the maths, with an interactive Poisson demo

The site is plain HTML, CSS and JavaScript with no build step. The model is dependency-free Python. A scheduled GitHub Action pulls fresh data from the official Fantasy Premier League API, rebuilds the predictions and redeploys the site to GitHub Pages.

## Quick start

```bash
git clone https://github.com/<you>/pl-match-predictor.git
cd pl-match-predictor

python -m predictor.build          # fetch data, fit the model, write site/data/predictions.json
python -m http.server -d site 8000 # open http://localhost:8000
```

Python 3.10+ is all you need. To run the tests:

```bash
pip install pytest
python -m pytest
```

### Build options

| Flag | What it does |
| --- | --- |
| `--source auto` (default) | Official FPL API, falling back to the community mirror if the API can't be reached |
| `--source fpl` | Official FPL API only; fails if unreachable |
| `--source mirror` | Community archive only (updates less often) |
| `--season 2026-27` | Season to model. Defaults to the season in progress |
| `--now 2026-11-05T22:30:00Z` | Pretend it's a different time, for reproducible builds |

## Deploying your own copy

1. Push this repository to GitHub.
2. In **Settings → Pages**, set **Source** to **GitHub Actions**.
3. In **Settings → Actions → General → Workflow permissions**, choose **Read and write permissions** so the daily job can commit refreshed data.
4. Run the **Update predictions and deploy** workflow once from the **Actions** tab (or push to `main`).

The site will be live at `https://<you>.github.io/pl-match-predictor/`. After that it rebuilds every day at 06:17 UTC and on every push to `main`.

## How the model works

1. **Goal signal.** For each match and each side, take 70% of the team's xG plus 30% of its actual goals. xG measures chance quality and predicts future scoring better than goals alone. If a match has no xG yet, its actual goals count at half weight.
2. **Ratings.** Each team gets an attack rating and a defence rating, where 1.00 is league average and a lower defence number is better. They are solved jointly and iteratively, so scoring against a strong defence counts for more than scoring against a weak one.
3. **Prior.** Early-season samples are small, so each team starts from last season's rating pulled 25% toward average. That prior is worth 4 games and fades as this season's games accumulate. Promoted clubs start from the average of last season's bottom three.
4. **Expected goals for a fixture.** `home λ = league home average × home attack × away defence`, and the same for the away side. The gap between the home and away league averages is the home advantage.
5. **Scorelines.** Each side's goals are modelled as Poisson with mean λ. The code supports the [Dixon-Coles (1997)](https://doi.org/10.1111/1467-9876.00065) low-score adjustment (ρ), currently set to 0 because it didn't help in testing. Summing the scoreline grid gives win, draw and loss.

The current values (prior 4 games, ρ = 0) are a **provisional candidate** chosen on the development seasons; see [`experiments/2026-11-05-REPORT.md`](experiments/2026-11-05-REPORT.md). v0.1 used 8 games and ρ = −0.08.

All tunable values live in the `Config` class in [`predictor/model.py`](predictor/model.py). The defaults are the v0.1 settings; if `predictor/params.json` exists, the site build uses those values instead.

### Evaluation

Model changes are judged with a fixed, leakage-tested protocol in [`predictor/evaluate.py`](predictor/evaluate.py):

| Seasons | Role |
|---|---|
| 2022-23, 2023-24 | Development: all tuning and model selection |
| 2024-25, 2025-26 | Test: sealed, evaluated once per nominated model with `--final` |
| 2026-27 | Live predictions |

- **Walk-forward predictions.** Each gameweek is predicted from matches that kicked off before that gameweek's first kickoff, plus a prior built only from the previous season. Tests tamper with future results and check earlier predictions don't move.
- **Primary metric: multiclass log loss.** Brier score, 1X2 accuracy, draw calibration and calibration bins are reported alongside, and model differences come with paired bootstrap confidence intervals.
- **Reproducible data.** Historical seasons are pinned to an exact commit of the archive and cached locally, and every experiment records file hashes. Experiment reports live in [`experiments/`](experiments/).
- **Sealed test seasons.** The code refuses to evaluate a test season without `--final`. A model is nominated *before* the test is run, and the test is not used to choose between models.

```bash
python -m predictor.evaluate compare           # v0.1 vs params.json on development seasons
python -m predictor.evaluate tune              # grid search, development seasons only
python -m predictor.evaluate compare --final   # the held-out test
```

The site's Track Record page shows a development season (currently 2023-24) until the held-out test has been run, so the test seasons aren't inspected by accident. It also shows a live check on the current season.

### Limitations

The model knows nothing about injuries, suspensions, rotation, managerial changes or team news. Ratings are the same for every future fixture; they don't project form changes. Treat probabilities as a baseline, not a tip sheet.

## Project structure

```
predictor/
  model.py      Config, ratings, Poisson + Dixon-Coles predictions
  sources.py    official FPL API and community mirror loaders
  evaluate.py   walk-forward evaluation, tuning, sealed test seasons
  build.py      CLI that fits the model and writes the site data
site/
  index.html    single-page app
  app.js        rendering + the same prediction maths in JS
  styles.css
  data/predictions.json   generated, committed by the daily job
data/
  manual_results.csv      optional: scores the data source doesn't have yet
tests/                    model, data parsing, leakage, and JS/Python parity tests
experiments/              tuning and evaluation reports with raw results
.github/workflows/        tests on every push; daily data refresh + Pages deploy
```

### Filling in missing results

If the data source is behind, add rows to `data/manual_results.csv`:

```csv
gw,home,home_goals,away_goals,away
9,Newcastle,2,1,Everton
```

Team names must match the FPL names. A manual score is only used while the source has no score for that fixture, so stale rows do no harm once real data arrives.

## Data

- Live season data: the official [Fantasy Premier League](https://fantasy.premierleague.com) API (fixtures, results, per-player xG)
- Previous seasons: [vaastav/Fantasy-Premier-League](https://github.com/vaastav/Fantasy-Premier-League)

## Roadmap

- FPL tools built on the same ratings: clean sheet odds, attacking returns and captain picks
- Recency weighting so recent form counts for more
- Scoring environment: goals rose from 2.85 to 3.28 a match between 2022-23 and 2023-24. Check whether the current-season league averages adapt fast enough, before adding any new parameter
- Stronger baselines: Elo and margin-free bookmaker probabilities

## License

MIT. An independent fan project, not affiliated with the Premier League or any club.
