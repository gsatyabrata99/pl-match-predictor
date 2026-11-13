"""The website recomputes predictions in JavaScript. Make sure it matches Python exactly."""
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from predictor import model
from predictor.model import Ratings

APP = Path(__file__).resolve().parent.parent / "site" / "app.js"


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_js_predict_matches_python():
    src = APP.read_text()
    fn = re.search(r"function predict\(h, a\) \{.*?\n\}\n", src, re.S).group(0)
    meta = {"mu_h": 1.62, "mu_a": 1.38, "maxg": model.MAX_GOALS, "rho": model.BASELINE.rho}
    teams = {"A": {"att": 1.31, "dfn": 0.62}, "B": {"att": 0.74, "dfn": 1.18}}
    script = f"const M = {json.dumps(meta)}; const T = {json.dumps(teams)};\n{fn}\n" \
             "const p = predict('A','B'); console.log(JSON.stringify([p.ph, p.pd, p.pa, p.lh, p.la, p.best.slice(0,2)]));"
    out = json.loads(subprocess.run(["node", "-e", script], capture_output=True, text=True, check=True).stdout)
    r = Ratings({k: v["att"] for k, v in teams.items()}, {k: v["dfn"] for k, v in teams.items()}, 1.62, 1.38)
    p = model.predict("A", "B", r)
    assert out[:5] == pytest.approx([p.p_home, p.p_draw, p.p_away, p.home_xg, p.away_xg], abs=1e-12)
    assert tuple(out[5]) == p.most_likely_score


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
@pytest.mark.parametrize("lh,la,label", [(1.5808, 0.8871, "EVE win · 1–0"),   # Everton v Coventry, GW10: top cell 1–1
                                         (2.6, 0.6, ""),                     # top cell already a home win
                                         (0.6, 0.6, "")])                    # draw favoured: no extra label
def test_favourite_label_matches_python_grid(lh, la, label):
    src = APP.read_text()
    fn = re.search(r"function predict\(h, a\) \{.*?\n\}\n", src, re.S).group(0)
    fav = re.search(r"function favLine\(p, h, a\) \{.*?\n\}\n", src, re.S).group(0)
    meta = {"mu_h": lh, "mu_a": la, "maxg": model.MAX_GOALS, "rho": model.BASELINE.rho}
    teams = {"Everton": {"att": 1, "dfn": 1, "short": "EVE"}, "Coventry": {"att": 1, "dfn": 1, "short": "COV"}}
    script = (f"const M = {json.dumps(meta)}; const T = {json.dumps(teams)}; const esc = s => s;\n{fn}\n{fav}\n"
              "const p = predict('Everton','Coventry');"
              "console.log(JSON.stringify({best: p.best.slice(0,2), by: Object.fromEntries(Object.entries(p.bestBy).map(([k,v]) => [k, v.slice(0,2)])),"
              " fav: p.fav, label: favLine(p, 'Everton', 'Coventry').replace(/<[^>]+>/g, '')}));")
    out = json.loads(subprocess.run(["node", "-e", script], capture_output=True, text=True, check=True).stdout)
    p = model.scoreline(lh, la, model.BASELINE.rho)
    n = range(model.MAX_GOALS + 1)
    for k, cond in (("H", lambda i, j: i > j), ("D", lambda i, j: i == j), ("A", lambda i, j: i < j)):
        assert tuple(out["by"][k]) == max(((i, j) for i in n for j in n if cond(i, j)), key=lambda ij: p.grid[ij[0]][ij[1]])
    assert tuple(out["best"]) == p.most_likely_score
    assert out["label"] == label
