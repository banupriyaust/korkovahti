"""Back-test the site's market-implied Euribor outlook against what actually happened.

Usage:  python backtest.py
Writes backtest/results.json and backtest/results.md.

For every month M since the ECB yield curve began (September 2004) the script
rebuilds the outlook exactly as build.py would have at the end of that month,
using only data available then:

  path(h) = average forward rate over M's curve days + (Euribor avg in M - curve avg in M)

and compares it with the Euribor monthly average actually published h months
later. Two simple benchmarks are scored the same way:

  * no change   - the rate stays at its month-M level
  * history     - the median historical h-month move, from data before M only

The uncertainty band is also rebuilt from data before M only, so its coverage
is measured out of sample.
"""
import csv
import io
import json
import math
import pathlib
import statistics
import urllib.request

HERE = pathlib.Path(__file__).parent
API = "https://data-api.ecb.europa.eu/service/data/"
HORIZONS = (6, 12, 24, 36)
TENORS = (("m3", "3M", 3), ("m12", "1Y", 12))


def fetch(path):
    req = urllib.request.Request(API + path, headers={"Accept": "text/csv"})
    with urllib.request.urlopen(req, timeout=180) as r:
        return list(csv.DictReader(io.StringIO(r.read().decode("utf-8"))))


def spot(p, t):
    x, y = t / p["t1"], t / p["t2"]
    a, c = (1 - math.exp(-x)) / x, (1 - math.exp(-y)) / y
    return p["b0"] + p["b1"] * a + p["b2"] * (a - math.exp(-x)) + p["b3"] * (c - math.exp(-y))


def fwd(p, t, m):
    return spot(p, m) if t <= 0 else (spot(p, t + m) * (t + m) - spot(p, t) * t) / m


def quantile(xs, q):
    s = sorted(xs)
    return s[min(len(s) - 1, int(q * len(s)))]


# Euribor monthly averages
euribor = {}
for key, code, _ in TENORS:
    rows = fetch(f"FM/M.U2.EUR.RT.MM.EURIBOR{code}D_.HSTA?format=csvdata&detail=dataonly&startPeriod=1999-01")
    euribor[key] = {r["TIME_PERIOD"]: float(r["OBS_VALUE"]) for r in rows}
months = sorted(euribor["m12"])
idx = {m: i for i, m in enumerate(months)}

# Daily Svensson parameters, grouped by month
names = {"BETA0": "b0", "BETA1": "b1", "BETA2": "b2", "BETA3": "b3", "TAU1": "t1", "TAU2": "t2"}
rows = fetch("YC/B.U2.EUR.4F.G_N_A.SV_C_YM.BETA0+BETA1+BETA2+BETA3+TAU1+TAU2"
             "?format=csvdata&detail=dataonly&startPeriod=2004-09-01")
days = {}
for r in rows:
    days.setdefault(r["TIME_PERIOD"], {})[names[r["DATA_TYPE_FM"]]] = float(r["OBS_VALUE"])
curve = {}
for d, p in days.items():
    if len(p) == 6:
        curve.setdefault(d[:7], []).append(p)

results = {"origins": None, "tenors": {}}
records = []
for key, _, tm in TENORS:
    series = [euribor[key][m] for m in months]
    out = {}
    for h in HORIZONS:
        errs = {"market": [], "nochange": [], "history": []}
        inside = 0
        hits = total_dir = 0
        origins = []
        for m, cs in sorted(curve.items()):
            i = idx.get(m)
            if i is None or i + h >= len(months) or len(cs) < 10:
                continue
            now = series[i]
            spread = now - statistics.fmean(spot(p, tm / 12) for p in cs)
            implied = statistics.fmean(fwd(p, h / 12, tm / 12) for p in cs) + spread
            actual = series[i + h]
            past = [series[j + h] - series[j] for j in range(0, i - h + 1)]   # moves fully known at M
            med = quantile(past, .5)
            lo, hi = implied + quantile(past, .25) - med, implied + quantile(past, .75) - med
            errs["market"].append(implied - actual)
            errs["nochange"].append(now - actual)
            errs["history"].append(now + med - actual)
            inside += lo <= actual <= hi
            if abs(implied - now) >= 0.10:               # market priced a clear move
                total_dir += 1
                hits += (implied - now) * (actual - now) > 0
            origins.append(m)
            if key == "m12" and h == 12:
                records.append({"origin": m, "now": round(now, 3), "implied": round(implied, 3),
                                "actual": round(actual, 3), "lo": round(lo, 3), "hi": round(hi, 3)})
        score = lambda e: {"n": len(e), "bias": round(statistics.fmean(e), 3),
                           "mae": round(statistics.fmean(abs(x) for x in e), 3),
                           "rmse": round(math.sqrt(statistics.fmean(x * x for x in e)), 3)}
        out[h] = {"market": score(errs["market"]), "nochange": score(errs["nochange"]),
                  "history": score(errs["history"]),
                  "band_coverage": round(inside / len(origins), 3),
                  "direction": {"calls": total_dir, "hit_rate": round(hits / total_dir, 3) if total_dir else None},
                  "first": origins[0], "last": origins[-1]}
    results["tenors"][key] = out

# The same 12-month, 12-ahead test split by period, to show where the method struggles
periods = (("2004-09", "2007-12", "Pre-crisis"), ("2008-01", "2014-12", "Crisis and euro debt crisis"),
           ("2015-01", "2021-12", "Negative rates"), ("2022-01", "2099-12", "Inflation and hikes"))
results["by_period"] = []
for a, b, label in periods:
    sel = [r for r in records if a <= r["origin"] <= b]
    if sel:
        results["by_period"].append({
            "period": label, "from": sel[0]["origin"], "to": sel[-1]["origin"], "n": len(sel),
            "market_mae": round(statistics.fmean(abs(r["implied"] - r["actual"]) for r in sel), 3),
            "nochange_mae": round(statistics.fmean(abs(r["now"] - r["actual"]) for r in sel), 3),
            "market_bias": round(statistics.fmean(r["implied"] - r["actual"] for r in sel), 3)})
results["m12_h12_records"] = records

out_dir = HERE / "backtest"
out_dir.mkdir(exist_ok=True)
(out_dir / "results.json").write_text(json.dumps(results, indent=1), encoding="utf-8")

lab = {"m3": "3-month Euribor", "m12": "12-month Euribor"}
md = ["# Back-test results", "",
      f"Origins: {results['tenors']['m12'][6]['first']} onward, scored against realised monthly averages "
      f"up to {months[-1]}. Errors in percentage points; bias = average of (predicted - actual).", ""]
for key in results["tenors"]:
    md += [f"## {lab[key]}", "",
           "| Horizon | Origins | Market MAE | No-change MAE | History MAE | Market bias | Band coverage (target 50 %) | Direction hit rate |",
           "|---|---|---|---|---|---|---|---|"]
    for h, r in results["tenors"][key].items():
        d = r["direction"]
        md.append(f"| {h} months | {r['market']['n']} | {r['market']['mae']:.2f} | {r['nochange']['mae']:.2f} | "
                  f"{r['history']['mae']:.2f} | {r['market']['bias']:+.2f} | {r['band_coverage']:.0%} | "
                  f"{(f'{d['hit_rate']:.0%} of {d['calls']}') if d['calls'] else 'n/a'} |")
    md.append("")
md += ["## 12-month Euribor, 12 months ahead, by period", "",
       "| Period | Origins | Market MAE | No-change MAE | Market bias |", "|---|---|---|---|---|"]
for p in results["by_period"]:
    md.append(f"| {p['period']} ({p['from']} to {p['to']}) | {p['n']} | {p['market_mae']:.2f} | "
              f"{p['nochange_mae']:.2f} | {p['market_bias']:+.2f} |")
(out_dir / "results.md").write_text("\n".join(md) + "\n", encoding="utf-8")
print("\n".join(md))
