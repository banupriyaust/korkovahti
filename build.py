"""Rebuild korkovahti.html from template.html with fresh ECB data.

Usage:  python build.py
Everything comes from the ECB Data Portal (free to reuse): monthly Euribor
averages, the deposit rate and the yield curve. No EMMI daily fixings are used.
"""
import calendar
import csv
import io
import json
import math
import pathlib
import urllib.request

HERE = pathlib.Path(__file__).parent
API = "https://data-api.ecb.europa.eu/service/data/"
START = "1999-01"


def fetch(path):
    req = urllib.request.Request(API + path, headers={"Accept": "text/csv"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return list(csv.DictReader(io.StringIO(r.read().decode("utf-8"))))


def monthly(code):
    rows = fetch(f"FM/M.U2.EUR.RT.MM.EURIBOR{code}D_.HSTA?format=csvdata&startPeriod={START}")
    rows.sort(key=lambda r: r["TIME_PERIOD"])
    assert rows[0]["TIME_PERIOD"] == START, rows[0]["TIME_PERIOD"]
    return [r["TIME_PERIOD"] for r in rows], [round(float(r["OBS_VALUE"]), 3) for r in rows]


series = {}
periods = None
for key, code in (("m1", "1M"), ("m3", "3M"), ("m6", "6M"), ("m12", "1Y")):
    p, v = monthly(code)
    if periods is None:
        periods = p
    assert p == periods, f"{key} covers different months"
    series[key] = v

dfr_rows = fetch("FM/B.U2.EUR.4F.KR.DFR.LEV?format=csvdata&startPeriod=1999-01-01")
dfr_rows.sort(key=lambda r: r["TIME_PERIOD"])
dfr = [[r["TIME_PERIOD"], float(r["OBS_VALUE"])] for r in dfr_rows]

yc = fetch("YC/B.U2.EUR.4F.G_N_A.SV_C_YM.?format=csvdata&lastNObservations=1")
par = {r["DATA_TYPE_FM"]: float(r["OBS_VALUE"]) for r in yc}
curve_date = next(r["TIME_PERIOD"] for r in yc if r["DATA_TYPE_FM"] == "BETA0")
sv = {"b0": par["BETA0"], "b1": par["BETA1"], "b2": par["BETA2"], "b3": par["BETA3"],
      "t1": par["TAU1"], "t2": par["TAU2"]}



def spot(p, t):
    x, y = t / p["t1"], t / p["t2"]
    a, c = (1 - math.exp(-x)) / x, (1 - math.exp(-y)) / y
    return p["b0"] + p["b1"] * a + p["b2"] * (a - math.exp(-x)) + p["b3"] * (c - math.exp(-y))


# Gap between Euribor and the yield curve, measured over the latest full month,
# then applied to today's curve to estimate where each Euribor stands now.
last = periods[-1]
hist = fetch("YC/B.U2.EUR.4F.G_N_A.SV_C_YM.BETA0+BETA1+BETA2+BETA3+TAU1+TAU2"
             f"?format=csvdata&startPeriod={last}-01&endPeriod={last}-"
             f"{calendar.monthrange(int(last[:4]), int(last[5:]))[1]}")
days = {}
for r in hist:
    days.setdefault(r["TIME_PERIOD"], {})[r["DATA_TYPE_FM"]] = float(r["OBS_VALUE"])
days = [{"b0": d["BETA0"], "b1": d["BETA1"], "b2": d["BETA2"], "b3": d["BETA3"],
         "t1": d["TAU1"], "t2": d["TAU2"]} for d in days.values() if len(d) == 6]
assert len(days) >= 15, f"only {len(days)} curve days in {last}"
spread, est = {}, {}
for key, m in (("m1", 1), ("m3", 3), ("m6", 6), ("m12", 12)):
    avg = sum(spot(p, m / 12) for p in days) / len(days)
    spread[key] = round(series[key][-1] - avg, 4)
    est[key] = round(spot(sv, m / 12) + spread[key], 3)

data = {
    "start": START,
    "lastMonth": last,
    "series": series,
    "dfr": dfr,
    "sv": sv,
    "curveDate": curve_date,
    "spread": spread,
    "est": est,
}

# Back-test summary (from backtest.py) for the "How accurate is this?" panel
bt_file = HERE / "backtest" / "results.json"
if bt_file.exists():
    bt = json.loads(bt_file.read_text(encoding="utf-8"))["tenors"]
    data["bt"] = {k: {h: {"market": v[h]["market"]["mae"], "nochange": v[h]["nochange"]["mae"],
                          "band": v[h]["band_coverage"], "hit": v[h]["direction"]["hit_rate"]}
                      for h in ("6", "12", "24")} for k, v in bt.items()}
    data["btFrom"] = bt["m12"]["6"]["first"]

page = (HERE / "template.html").read_text(encoding="utf-8").replace(
    "/*__DATA__*/null", json.dumps(data, separators=(",", ":")))
(HERE / "korkovahti.html").write_text(page, encoding="utf-8")

# The public site: the same page as a complete document (korkovahti.html is the
# bare fragment that Claude's artifact host wraps itself).
head, body = page.split('<div class="wrap">', 1)
pub = HERE / "public"
pub.mkdir(exist_ok=True)
(pub / "index.html").write_text(
    '<!doctype html><html lang="en"><head><meta charset="utf-8">'
    '<meta name="viewport" content="width=device-width,initial-scale=1">'
    '<meta name="description" content="Euribor for home-loan borrowers in Finland and the euro area: '
    'history, current level, what markets expect, and what it means for your monthly payment.">'
    "<style>body{margin:0}img{max-width:100%}[hidden]{display:none!important}</style>"
    + head + '</head><body><div class="wrap">' + body + "</body></html>", encoding="utf-8")

print("estimated today:", est)
print(f"months {periods[0]}..{periods[-1]} ({len(periods)}), curve {curve_date}, "
      f"deposit rate {dfr[-1][1]} since {dfr[-1][0]}, {len(page)} bytes")
