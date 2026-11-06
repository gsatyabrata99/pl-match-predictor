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
