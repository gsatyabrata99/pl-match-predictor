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
3. **Prior.** Early-season samples are small, so each team starts from last season's rating pulled 25% toward average. That prior is worth 8 games and fades as this season's games accumulate. Promoted clubs start from the average of last season's bottom three.
4. **Expected goals for a fixture.** `home λ = league home average × home attack × away defence`, and the same for the away side. The gap between the home and away league averages is the home advantage.
5. **Scorelines.** Each side's goals are modelled as Poisson with mean λ, using the [Dixon-Coles (1997)](https://doi.org/10.1111/1467-9876.00065) adjustment for low scores. Summing the scoreline grid gives win, draw and loss.

All tunable constants live at the top of [`predictor/model.py`](predictor/model.py).

### Performance

In a walk-forward test on 2025-26, where each gameweek was predicted using only the matches before it, the model:

- picked the correct result **48.6%** of the time, against 42.0% for always backing the home team
- scored a Brier score of **0.620**, against 0.655 for flat base rates (lower is better)

The site also shows a live hold-out test on the current season.

### Limitations

The model knows nothing about injuries, suspensions, rotation, managerial changes or team news. Ratings are the same for every future fixture; they don't project form changes. Treat probabilities as a baseline, not a tip sheet.

## Project structure

```
predictor/
  model.py      ratings, Poisson + Dixon-Coles predictions, backtest
  sources.py    official FPL API and community mirror loaders
  build.py      CLI that fits the model and writes the site data
site/
  index.html    single-page app
  app.js        rendering + the same prediction maths in JS
  styles.css
  data/predictions.json   generated, committed by the daily job
data/
  manual_results.csv      optional: scores the data source doesn't have yet
tests/                    model, data parsing, and JS/Python parity tests
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
- Model tuning: fit ρ, the xG weight and the prior strength by maximum likelihood
- Recency weighting so recent form counts for more

## License

MIT. An independent fan project, not affiliated with the Premier League or any club.
