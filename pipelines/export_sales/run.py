"""U.S. grain and oilseed exports for the grains desk: FAS weekly export sales and FGIS export inspections, each
read against USDA's WASDE export forecast. Adapted, with permission, from an existing open-source pipeline.

Export sales (FAS ESR, key DATAGOV_API_KEY): commitments = shipped + outstanding sales. "Implied" exports =
commitments now / the average share of the final WASDE export figure that was committed by the same week over
the previous five completed marketing years. Backtested against USDA's own forecast at the same week.
Inspections (FGIS, no key): weekly inspected for export; the same pace logic on cumulative inspections.

History: completed marketing years never change, so they come from the previous run's cache (PREV_CACHE) and
only the current and previous year are downloaded. The first run downloads everything once.
Run by scripts/build-data.mjs; prints {data, cache, latest, n, src, note, partial} as JSON on stdout.

Local test without keys: EXPORTS_FIXTURE=<dir> reads <dir>/export_sales/<commodity>/MY<year>.csv,
<dir>/export_sales/countries.json and <dir>/inspections/weekly_CY<year>.csv instead of the APIs.
"""
import io, json, os, sys, time
from pathlib import Path

import numpy as np
import pandas as pd
import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "wasde"))
import wasde_data as W  # noqa: E402

KEY = os.environ.get("DATAGOV_API_KEY", "").strip().strip("'\"")
FIXTURE = os.environ.get("EXPORTS_FIXTURE")
ESR = "https://api.fas.usda.gov/api/esr"
FGIS = "https://fgisonline.ams.usda.gov/ExportGrainReport/CY{}.csv"
UA = {"User-Agent": "grains-monitor/1.0 (daily build; +https://github.com/DrNas/grains-monitor)"}
NOW = pd.Timestamp.now(tz="UTC").tz_localize(None)
FIRST_FAS_MY = 2010           # FAS marketing year 2010 = 2009/10
FIRST_CY = 2005               # inspections: enough years for five prior seasons before 2010/11

# key: (ESR code, fixture folder, WASDE key, MT -> WASDE unit, unit label, marketing year start month)
COMS = {"corn": (401, "corn", "corn", 39.368 / 1e6, "mil bu", 9),
        "soybeans": (801, "soybeans", "soybeans", 36.744 / 1e6, "mil bu", 9),
        "meal": (901, "soybean_meal", "meal", 1.10231 / 1e3, "thou short tons", 10),
        "oil": (902, "soybean_oil", "oil", 2204.62 / 1e6, "mil lb", 10),
        "wheat": (107, "wheat_all", "wheat", 36.744 / 1e6, "mil bu", 6)}
CLASSES = {"HRW": (101, "wheat_hrw"), "SRW": (102, "wheat_srw"), "HRS": (103, "wheat_hrs"), "White": (104, "wheat_white"), "Durum": (105, "wheat_durum")}
INSPECT = {"corn": ("CORN", 9, 39.368), "soybeans": ("SOYBEANS", 9, 36.744), "wheat": ("WHEAT", 6, 36.744)}
COLS = ["weeklyExports", "accumulatedExports", "outstandingSales", "currentMYNetSales", "nextMYOutstandingSales", "grossNewSales"]


def log(*a):
    print(*a, file=sys.stderr, flush=True)


def get(url, headers=None, timeout=180):
    """GET with retries and backoff; returns the response, or raises with the last error."""
    last = None
    for attempt in range(4):
        if attempt:
            time.sleep(4 * 2 ** (attempt - 1))
        try:
            r = requests.get(url, headers={**UA, **(headers or {})}, timeout=timeout)
            if r.status_code == 200:
                return r
            last = f"HTTP {r.status_code}"
            if r.status_code in (401, 403, 404):
                break
        except Exception as e:
            last = str(e)[:120]
        log("  retry", url.split("?")[0][-60:], last)
    raise RuntimeError(f"{url.split('//')[1].split('/')[0]}: {last}")


# ---------------- export sales (FAS ESR) ----------------
def fas_my_now(start_month):
    """FAS marketing year in force today (FAS year N = WASDE N-1/N)."""
    return NOW.year + 1 if NOW.month >= start_month else NOW.year


def esr_rows(code, folder, my):
    """Rows by country for one commodity and FAS marketing year ([] if none yet)."""
    if FIXTURE:
        p = Path(FIXTURE) / "export_sales" / folder / f"MY{my}.csv"
        return pd.read_csv(p).to_dict("records") if p.exists() else []
    r = get(f"{ESR}/exports/commodityCode/{code}/allCountries/marketYear/{my}", {"X-Api-Key": KEY})
    return r.json() or []


def totals(rows):
    """Weekly totals across countries: [[week, *COLS]] in metric tons."""
    if not rows:
        return []
    d = pd.DataFrame(rows)
    d["week"] = pd.to_datetime(d.weekEndingDate).dt.strftime("%Y-%m-%d")
    g = d.groupby("week")[COLS].sum().sort_index()
    return [[w, *map(float, v)] for w, v in zip(g.index, g.values)]


def esr_history(code, folder, start_month, cache):
    """{fas_my: weekly totals} for every marketing year, plus by-country rows for the current and previous one."""
    cur = fas_my_now(start_month)
    hist, by_country = {}, {}
    for my in range(FIRST_FAS_MY, cur + 1):
        if my < cur - 1 and str(my) in cache:
            hist[str(my)] = cache[str(my)]
            continue
        rows = esr_rows(code, folder, my)
        if rows:
            hist[str(my)] = totals(rows)
            if my >= cur - 1:
                by_country[my] = rows
        if not FIXTURE:
            time.sleep(0.3)
    return hist, by_country


def countries():
    if FIXTURE:
        c = json.loads((Path(FIXTURE) / "export_sales" / "countries.json").read_text())
    else:
        c = get(f"{ESR}/countries", {"X-Api-Key": KEY}).json()
    return {x["countryCode"]: x["countryDescription"].strip().title() for x in c}


def esr_frame(hist):
    """Long frame like the source model expects: my (WASDE label), week, COLS, wk, commit."""
    out = []
    for fmy, rows in hist.items():
        if not rows:
            continue
        d = pd.DataFrame(rows, columns=["week", *COLS])
        d["week"] = pd.to_datetime(d.week)
        d["my"] = f"{int(fmy) - 1}/{fmy[-2:]}"
        out.append(d)
    g = pd.concat(out).sort_values(["my", "week"])
    g["wk"] = g.groupby("my").cumcount() + 1
    g["commit"] = g.accumulatedExports + g.outstandingSales
    return g


def sales_model(g, wx, conv, unit):
    """Export sales pace vs USDA (unchanged from the source, minus the price-reaction study, which needs prices)."""
    final = wx.sort_values("wasde").groupby("my").value.last()
    mys = sorted(g.my.unique())
    nweeks = g.groupby("my").wk.max()
    complete = [m for m in mys if nweeks[m] >= 50 and m in final.index]
    rows = []
    for my in mys:
        prior = [m for m in complete if m < my][-5:]
        if len(prior) < 3:
            continue
        for _, r in g[g.my == my].iterrows():
            sh = [g[(g.my == m) & (g.wk == r.wk)].commit.iloc[0] / (final[m] / conv) for m in prior if len(g[(g.my == m) & (g.wk == r.wk)])]
            if not sh:
                continue
            usda = wx[(wx.my == my) & (wx.release <= r.week)].sort_values("wasde")
            nxt = wx[(wx.my == my) & (wx.release > r.week)].sort_values("wasde")
            rows.append(dict(my=my, wk=int(r.wk), week=r.week, commit=r.commit, implied=r.commit / np.mean(sh) * conv,
                             usda=usda.value.iloc[-1] if len(usda) else np.nan, next_usda=nxt.value.iloc[0] if len(nxt) else np.nan,
                             final=final[my] if my in complete else np.nan))
    r = pd.DataFrame(rows)
    test = None
    bt = r.dropna(subset=["final", "usda"]) if len(r) else r
    if len(bt):
        bt = bt.assign(err=(bt.implied / bt.final - 1).abs() * 100, err_usda=(bt.usda / bt.final - 1).abs() * 100)
        rv = bt.dropna(subset=["next_usda"])
        rv = rv[rv.next_usda != rv.usda]
        buckets = pd.cut(bt.wk, [0, 8, 17, 26, 35, 44, 53], labels=[8, 17, 26, 35, 44, 53])
        by = {int(k): {"mae_pct": round(float(x.err.mean()), 2), "mae_usda_pct": round(float(x.err_usda.mean()), 2), "n": int(x.my.nunique())}
              for k, x in bt.groupby(buckets, observed=True)}
        hit = np.sign(rv.implied - rv.usda) == np.sign(rv.next_usda - rv.usda)
        big = rv[(rv.implied / rv.usda - 1).abs() > 0.03]
        test = {"by_week": by, "n_years": int(bt.my.nunique()),
                "revision_hit": round(float(hit.mean()), 2) if len(rv) else None, "revision_n": int(rv.my.nunique()),
                "revision_hit_gap3": round(float((np.sign(big.implied - big.usda) == np.sign(big.next_usda - big.usda)).mean()), 2) if len(big) else None,
                "revision_n_gap3": int(len(big))}
    cur = mys[-1]
    c, p = g[g.my == cur], (g[g.my == mys[-2]] if len(mys) > 1 else g.iloc[0:0])
    last = c.iloc[-1]
    wk = int(last.wk)
    un = wx[wx.my == cur].sort_values("wasde").value
    usda_now = float(un.iloc[-1]) if len(un) else np.nan
    prior = complete[-5:]
    prof = [np.mean([g[(g.my == m) & (g.wk == k)].commit.iloc[0] / (final[m] / conv) for m in prior if len(g[(g.my == m) & (g.wk == k)])] or [np.nan])
            for k in range(1, 53)]
    rc = r[r.my == cur] if len(r) else r
    implied = float(rc.implied.iloc[-1]) if len(rc) else np.nan
    prev_same = p[p.wk == wk].commit
    need = (usda_now / conv - last.commit) / max(52 - wk, 1)
    near = None
    if test:
        k = min(test["by_week"], key=lambda z: abs(z - wk) if z >= wk else 99)
        near = test["by_week"][k]
    f = lambda v, n=1: None if v is None or v != v else round(float(v), n)
    return {"my": cur, "unit": unit, "as_of": str(last.week.date()), "week": wk,
            "commit": f(last.commit * conv), "shipped": f(last.accumulatedExports * conv), "outstanding": f(last.outstandingSales * conv),
            "commit_prev": f(prev_same.iloc[0] * conv) if len(prev_same) else None,
            "usda": f(usda_now), "pct_of_usda": f(100 * last.commit * conv / usda_now),
            "avg_pct": f(100 * prof[wk - 1]) if wk <= 52 else None, "implied": f(implied, 0),
            "net_last": f(last.currentMYNetSales * conv, 2), "net_4wk": f(c.currentMYNetSales.tail(4).mean() * conv, 2),
            "need_weekly": f(need * conv, 2), "next_my_outstanding": f(last.nextMYOutstandingSales * conv),
            "weeks": list(range(1, 53)),
            "cur": [f(v * conv) for v in c.commit] + [None] * (52 - len(c)),
            "prev": [f(v * conv) for v in p.commit.iloc[:52]] + [None] * max(0, 52 - len(p)),
            "avg_path": [None if v != v else f(v * usda_now) for v in prof],   # average path that ends at USDA's figure
            "net_weeks": [str(d.date()) for d in c.week.tail(20)], "net_series": [f(v * conv, 2) for v in c.currentMYNetSales.tail(20)],
            "test": None if not test else {**test, "near": near}}


def destinations(by_country, names, conv, n=10):
    """Commitments by buyer: this marketing year vs the same week last year."""
    mys = sorted(by_country)
    if len(mys) < 2:
        return None
    cur, prev = (pd.DataFrame(by_country[m]) for m in mys[-2:][::-1])
    for d in (cur, prev):
        d["week"] = pd.to_datetime(d.weekEndingDate)
        d["commit"] = d.accumulatedExports + d.outstandingSales
    last = cur.week.max()
    k = sorted(cur.week.unique()).index(last)
    pw = sorted(prev.week.unique())
    pweek = pw[min(k, len(pw) - 1)]
    t = pd.DataFrame({"cur": cur[cur.week == last].groupby("countryCode").commit.sum(),
                      "prev": prev[prev.week == pweek].groupby("countryCode").commit.sum()}).fillna(0).sort_values("cur", ascending=False)
    net = cur[cur.week == last].groupby("countryCode").currentMYNetSales.sum()
    tot_c, tot_p = t.cur.sum(), t.prev.sum()
    rows = [{"name": names.get(k, str(k)), "cur": round(float(v.cur * conv), 1), "prev": round(float(v.prev * conv), 1),
             "net_last": round(float(net.get(k, 0) * conv), 2), "share": round(float(100 * v.cur / tot_c), 1) if tot_c else None}
            for k, v in t.head(n).iterrows()]
    return {"as_of": str(pd.Timestamp(last).date()), "prev_week": str(pd.Timestamp(pweek).date()), "rows": rows,
            "total_cur": round(float(tot_c * conv), 1), "total_prev": round(float(tot_p * conv), 1)}


def wheat_classes(class_hist):
    conv = 36.744 / 1e6
    out = []
    for name, hist in class_hist.items():
        g = esr_frame(hist)
        mys = sorted(g.my.unique())
        c, p = g[g.my == mys[-1]], g[g.my == mys[-2]]
        wk = int(c.wk.max())
        ps = p[p.wk == wk].commit
        pf = p.commit.iloc[-1] if len(p) else np.nan
        out.append({"cls": name, "commit": round(float(c.commit.iloc[-1] * conv), 1),
                    "prev": round(float(ps.iloc[0] * conv), 1) if len(ps) else None,
                    "yoy_pct": round(float(100 * (c.commit.iloc[-1] / ps.iloc[0] - 1)), 1) if len(ps) and ps.iloc[0] else None,
                    "prev_share_by_now": round(float(100 * ps.iloc[0] / pf), 1) if len(ps) and pf else None,
                    "net_4wk": round(float(c.currentMYNetSales.tail(4).mean() * conv), 2)})
    return out


# ---------------- inspections (FGIS) ----------------
def fgis_year(y):
    """Weekly metric tons inspected, by grain, for one calendar year: {grain: [[week, mt]]}."""
    if FIXTURE:
        p = Path(FIXTURE) / "inspections" / f"weekly_CY{y}.csv"
        if not p.exists():
            return None
        d = pd.read_csv(p)
    else:
        try:
            r = get(FGIS.format(y), timeout=300)
        except RuntimeError as e:
            if "404" in str(e):
                return None
            raise
        d = pd.read_csv(io.BytesIO(r.content), low_memory=False, encoding="latin-1", dtype=str)
        d.columns = [c.strip() for c in d.columns]
        d["week"] = pd.to_datetime(d["Thursday"], format="%Y%m%d", errors="coerce").dt.strftime("%Y-%m-%d")
        d["mt"] = pd.to_numeric(d["Metric Ton"].str.replace(",", ""), errors="coerce")
        d["grain"] = d["Grain"].str.strip()
    d = d[d.grain.isin([g for g, _, _ in INSPECT.values()])]
    g = d.groupby(["grain", "week"]).mt.sum()
    return {gr: [[w, float(v)] for w, v in s.droplevel(0).items()] for gr, s in g.groupby(level=0)}


def inspections_history(cache):
    hist = {}
    for y in range(FIRST_CY, NOW.year + 1):
        if y < NOW.year - 1 and str(y) in cache:
            hist[str(y)] = cache[str(y)]
            continue
        v = fgis_year(y)
        if v is not None:
            hist[str(y)] = v
    return hist


def inspections_model(hist, com, wx):
    grain, sm, bu = INSPECT[com]
    pts = [(w, v) for y in hist.values() for w, v in y.get(grain, [])]
    w = pd.Series(dict(pts)).sort_index()
    w.index = pd.to_datetime(w.index)
    w = w * bu / 1e6   # million bushels
    df = w.to_frame("mbu")
    df["my"] = [f"{x.year if x.month >= sm else x.year - 1}/{str((x.year if x.month >= sm else x.year - 1) + 1)[-2:]}" for x in df.index]
    df["wk"] = df.groupby("my").cumcount() + 1
    df["cum"] = df.groupby("my").mbu.cumsum()
    tot = df.groupby("my").mbu.sum()
    final = wx.sort_values("wasde").groupby("my").value.last()
    mys = sorted(df.my.unique())
    complete = [m for m in mys if df[df.my == m].wk.max() >= 50]
    rows = []
    for my in mys:
        prior = [m for m in complete if m < my and m in final.index][-5:]
        if len(prior) < 3:
            continue
        ratio = np.mean([final[m] / tot[m] for m in prior])
        for t, r in df[df.my == my].iterrows():
            shares = [df[(df.my == m) & (df.wk == r.wk)].cum.iloc[0] / tot[m] for m in prior if len(df[(df.my == m) & (df.wk == r.wk)])]
            if not shares:
                continue
            usda = wx[(wx.my == my) & (wx.release <= t)].sort_values("wasde")
            nxt = wx[(wx.my == my) & (wx.release > t)].sort_values("wasde")
            rows.append(dict(my=my, wk=int(r.wk), week=t, cum=r.cum, implied=r.cum / np.mean(shares) * ratio, avg_share=np.mean(shares),
                             usda=usda.value.iloc[-1] if len(usda) else np.nan, next_usda=nxt.value.iloc[0] if len(nxt) else np.nan,
                             final=final.get(my, np.nan) if my in complete else np.nan))
    r = pd.DataFrame(rows)
    test = None
    bt = r.dropna(subset=["final", "usda"])
    bt = bt[bt.my >= "2010/11"]
    if len(bt):
        bt = bt.assign(err=(bt.implied / bt.final - 1).abs() * 100, err_usda=(bt.usda / bt.final - 1).abs() * 100)
        rv = bt.dropna(subset=["next_usda"])
        rv = rv[rv.next_usda != rv.usda]
        by = {int(k): {"mae_pct": round(float(g.err.mean()), 2), "mae_usda_pct": round(float(g.err_usda.mean()), 2)}
              for k, g in bt.groupby(pd.cut(bt.wk, [0, 8, 17, 26, 35, 44, 53], labels=[8, 17, 26, 35, 44, 53]), observed=True)}
        test = {"by_week": by, "n": int(bt.my.nunique()), "revision_n": int(len(rv)),
                "revision_hit": round(float((np.sign(rv.implied - rv.usda) == np.sign(rv.next_usda - rv.usda)).mean()), 2) if len(rv) else None}
    cur_my = mys[-1]
    c = r[r.my == cur_my]
    if c.empty:
        return None
    p = df[df.my == mys[-2]]
    last = c.iloc[-1]
    un = wx[wx.my == cur_my].sort_values("wasde").value
    usda_now = float(un.iloc[-1]) if len(un) else np.nan
    wk_now = int(last.wk)
    if test:
        k = min(test["by_week"], key=lambda x: abs(x - wk_now) if x >= wk_now else 99)
        test["mae_pct"], test["mae_usda_pct"] = test["by_week"][k]["mae_pct"], test["by_week"][k]["mae_usda_pct"]
    prior5 = [m for m in complete if m in final.index][-5:]
    prof = [np.mean([df[(df.my == m) & (df.wk == k)].cum.iloc[0] / tot[m] for m in prior5 if len(df[(df.my == m) & (df.wk == k)])] or [np.nan]) for k in range(1, 53)]
    ratio_now = np.mean([final[m] / tot[m] for m in prior5])
    f = lambda v, n=1: None if v is None or v != v else round(float(v), n)
    return {"my": cur_my, "unit": "mil bu", "week": wk_now, "as_of": str(last.week.date()),
            "cum": f(last.cum), "usda": f(usda_now), "implied": f(last.implied, 0),
            "pct_of_usda": f(100 * last.cum * ratio_now / usda_now), "avg_pct": f(100 * last.avg_share),
            "weeks": list(range(1, 53)), "cur": [f(x) for x in df[df.my == cur_my].cum] + [None] * (52 - len(df[df.my == cur_my])),
            "prev": [f(x) for x in p.cum.iloc[:52]] + [None] * max(0, 52 - len(p)),
            "needed": [f(usda_now / ratio_now * s) for s in prof],
            "test": test}


def clean(o):
    """NaN / inf -> None, recursively (JSON has no NaN)."""
    if isinstance(o, dict):
        return {k: clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [clean(v) for v in o]
    if isinstance(o, (float, np.floating)):
        return float(o) if np.isfinite(o) else None
    if isinstance(o, np.integer):
        return int(o)
    return o


def main():
    if not KEY and not FIXTURE:
        raise SystemExit("DATAGOV_API_KEY is not set")
    cache = {}
    if os.environ.get("PREV_CACHE") and Path(os.environ["PREV_CACHE"]).exists():
        cache = json.loads(Path(os.environ["PREV_CACHE"]).read_text())
    wd, notes = W.load()
    out, errors, new_cache, latest = {}, [], {"esr": {}, "insp": {}}, []
    names = None
    try:
        names = countries()
    except Exception as e:
        errors.append(f"country names ({str(e)[:60]})")
    # export sales
    for com, (code, folder, wkey, conv, unit, sm) in COMS.items():
        try:
            hist, byc = esr_history(code, folder, sm, cache.get("esr", {}).get(folder, {}))
            new_cache["esr"][folder] = hist
            o = sales_model(esr_frame(hist), W.us_exports(wd, wkey), conv, unit)
            o["destinations"] = destinations(byc, names or {}, conv)
            out.setdefault(com, {})["sales"] = o
            latest.append(o["as_of"])
            log(com, "sales ok", o["as_of"], o["commit"], unit, "USDA", o["usda"])
        except Exception as e:
            errors.append(f"{com} sales ({str(e)[:80]})")
            log(com, "sales FAILED", e)
    try:
        ch = {}
        for name, (code, folder) in CLASSES.items():
            ch[name], _ = esr_history(code, folder, 6, cache.get("esr", {}).get(folder, {}))
            new_cache["esr"][folder] = ch[name]
        if "wheat" in out:
            out["wheat"]["sales"]["classes"] = wheat_classes(ch)
    except Exception as e:
        errors.append(f"wheat classes ({str(e)[:80]})")
    # inspections
    try:
        ih = inspections_history(cache.get("insp", {}))
        new_cache["insp"] = ih
        for com in INSPECT:
            o = inspections_model(ih, com, W.us_exports(wd, com))
            if o:
                out.setdefault(com, {})["inspections"] = o
                latest.append(o["as_of"])
                log(com, "inspections ok", o["as_of"], o["cum"])
    except Exception as e:
        errors.append(f"inspections ({str(e)[:80]})")
        log("inspections FAILED", e)
        if cache.get("insp"):
            new_cache["insp"] = cache["insp"]
    if not out:
        raise SystemExit("every export source failed: " + "; ".join(errors))
    note = "; ".join(errors + [n for n in notes])
    print(json.dumps(clean({"data": {"commodities": out, "wasde": wd.report.iloc[-1]}, "cache": new_cache,
                            "latest": max(latest) if latest else None, "n": len(out),
                            "src": "USDA FAS Export Sales Reporting; USDA AMS FGIS export inspections; USDA WASDE",
                            "note": note, "partial": bool(errors)}),
                     separators=(",", ":"), allow_nan=False, default=str))


if __name__ == "__main__":
    main()
