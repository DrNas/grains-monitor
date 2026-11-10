"""Macro desk: the U.S. economy, rates and Treasury liquidity, from free official sources (no keys).

- BLS public API v2: CPI (headline, core, food at home, energy), PPI (final demand, core, farm products), payrolls,
  unemployment, average hourly earnings, participation.
- BEA data mirrored by DBnomics: real GDP and consumer spending growth, PCE and core PCE prices, saving rate;
  University of Michigan sentiment.
- New York Fed: effective fed funds rate and target range, SOFR.
- U.S. Treasury: daily par yield curve, real (TIPS) curve -> breakevens.
- Treasury FiscalData: Treasury General Account cash balance (Daily Treasury Statement), bills outstanding (Monthly
  Statement of the Public Debt), bill auctions -> weekly bill issuance net of maturing bills.
The economy, policy and curve parts are adapted, with permission, from an existing open-source pipeline; the TGA
and bill-supply parts are new. A source that fails is left out and noted; the rest is still published.

Run by scripts/build-data.mjs; prints {data, latest, n, src, note, partial} as JSON on stdout.
"""
import io, json, math, sys, time
from datetime import date, datetime, timedelta, timezone

import pandas as pd
import requests

UA = {"User-Agent": "grains-monitor/1.0 (daily build; +https://github.com/DrNas/grains-monitor)"}
FD = "https://api.fiscaldata.treasury.gov/services/api/fiscal_service"
BLS = {
    "CUSR0000SA0": ("cpi", "CPI, all items (SA index)"), "CUSR0000SA0L1E": ("cpi_core", "Core CPI (SA index)"),
    "CUUR0000SA0": ("cpi_nsa", "CPI NSA"), "CUUR0000SA0L1E": ("cpi_core_nsa", "Core CPI NSA"),
    "CUSR0000SAF11": ("cpi_food_home", "CPI food at home"), "CUSR0000SA0E": ("cpi_energy", "CPI energy"),
    "WPSFD4": ("ppi", "PPI final demand (SA)"), "WPSFD49104": ("ppi_core", "PPI final demand less food and energy (SA)"),
    "WPU01": ("ppi_farm", "PPI farm products (NSA)"), "CES0000000001": ("payrolls", "Nonfarm payrolls (thousands, SA)"),
    "LNS14000000": ("unemp", "Unemployment rate (%)"), "CES0500000003": ("ahe", "Average hourly earnings ($, SA)"),
    "LNS11300000": ("lfpr", "Labor force participation (%)"),
}
DBN = {
    "gdp": ("BEA/NIPA-T10101/A191RL-Q", "Real GDP growth (% q/q annualized)"),
    "pce_real_q": ("BEA/NIPA-T10101/DPCERL-Q", "Real consumer spending growth (% q/q annualized)"),
    "pce_px": ("BEA/NIPA-T20804/DPCERG-M", "PCE price index"), "pce_core_px": ("BEA/NIPA-T20804/DPCCRG-M", "Core PCE price index"),
    "saving": ("BEA/NIPA-T20600/A072RC-M", "Personal saving rate (%)"),
}
NOTES = []


def log(*a):
    print(*a, file=sys.stderr, flush=True)


def get(url, method="get", tries=4, **kw):
    """Request with retries and backoff; None after the last failure (the caller notes what is missing)."""
    headers = {**UA, **kw.pop("headers", {})}
    last = None
    for i in range(tries):
        if i:
            time.sleep(4 * 2 ** (i - 1))
        try:
            r = getattr(requests, method)(url, headers=headers, timeout=60, **kw)
            if r.status_code == 200:
                return r
            last = f"HTTP {r.status_code}"
            if r.status_code in (401, 403, 404):
                break
        except Exception as e:
            last = str(e)[:100]
    log("  failed", url.split("?")[0][:90], last)
    return None


# ---------------- economy (from the source pipeline) ----------------
def bls():
    out = {}
    ids = list(BLS)
    y = date.today().year
    for k in range(0, len(ids), 10):
        r = get("https://api.bls.gov/publicAPI/v2/timeseries/data/", method="post", headers={"Content-type": "application/json"},
                json={"seriesid": ids[k:k + 10], "startyear": str(y - 3), "endyear": str(y)})
        if r is None:
            continue
        j = r.json()
        for s in j.get("Results", {}).get("series", []):
            pts = []
            for d in s["data"]:
                if not d["period"].startswith("M") or d["period"] == "M13":
                    continue
                try:
                    pts.append([f"{d['year']}-{d['period'][1:]}", float(d["value"])])
                except ValueError:
                    pass
            out[BLS[s["seriesID"]][0]] = sorted(pts)
        time.sleep(2)
    if not out:
        NOTES.append("BLS did not answer")
    return out


def dbn(code):
    r = get(f"https://api.db.nomics.world/v22/series/{code}?observations=1")
    if r is None:
        return None
    try:
        d = r.json()["series"]["docs"][0]
        return [[p, v] for p, v in zip(d["period"], d["value"]) if v not in (None, "NA")]
    except Exception as e:
        log("dbn parse", code, e)
        return None


def dbn_find(provider_dataset, words):
    """First series in a DBnomics dataset whose name contains all words."""
    r = get(f"https://api.db.nomics.world/v22/series/{provider_dataset}?limit=200&observations=1")
    if r is None:
        return None, None
    for s in r.json().get("series", {}).get("docs", []):
        nm = (s.get("series_name") or "").lower()
        if all(w in nm for w in words):
            return s.get("series_name"), [[p, v] for p, v in zip(s["period"], s["value"]) if v not in (None, "NA")]
    return None, None


def pct(a, b):
    return None if a is None or b in (None, 0) else 100 * (a / b - 1)


def series_stats(pts, kind):
    """kind: 'index' (m/m %, y/y %), 'level' (change), 'k' (monthly change in thousands)."""
    if not pts:
        return None
    last, prev = pts[-1], pts[-2] if len(pts) > 1 else None
    o = {"period": last[0], "value": last[1], "prev_period": prev[0] if prev else None, "prev": prev[1] if prev else None}
    if kind == "index":
        o["mom"] = pct(last[1], prev[1]) if prev else None
        o["mom_prev"] = pct(prev[1], pts[-3][1]) if len(pts) > 2 else None
        yago = [p for p in pts if p[0] == f"{int(last[0][:4]) - 1}{last[0][4:]}"]
        o["yoy"] = pct(last[1], yago[0][1]) if yago else None
        py = [p for p in pts if p[0] == f"{int(prev[0][:4]) - 1}{prev[0][4:]}"] if prev else []
        o["yoy_prev"] = pct(prev[1], py[0][1]) if py and prev else None
        o["ann3"] = (((last[1] / pts[-4][1]) ** 4) - 1) * 100 if len(pts) > 3 else None
        o["spark"] = [[p[0], round(pct(p[1], q[1]), 2)] for p in pts[-24:] for q in [x for x in pts if x[0] == f"{int(p[0][:4]) - 1}{p[0][4:]}"]]
    elif kind == "k":
        o["chg"] = last[1] - prev[1] if prev else None
        o["chg_prev"] = prev[1] - pts[-3][1] if len(pts) > 2 else None
        ch = [pts[i][1] - pts[i - 1][1] for i in range(1, len(pts))]
        o["avg3"] = sum(ch[-3:]) / 3 if len(ch) >= 3 else None
        o["spark"] = [[pts[i][0], round(pts[i][1] - pts[i - 1][1], 1)] for i in range(max(1, len(pts) - 24), len(pts))]
    else:
        o["chg"] = last[1] - prev[1] if prev else None
        o["spark"] = [[p[0], p[1]] for p in pts[-24:]]
    return o


def economy():
    B = bls()
    ind = []

    def add(cat, key, name, pts, kind, unit, src, note=""):
        s = series_stats(pts, kind)
        if s:
            ind.append({"cat": cat, "key": key, "name": name, "kind": kind, "unit": unit, "source": src, "note": note, **s})

    add("Inflation", "cpi", "CPI (headline)", B.get("cpi_nsa") and B.get("cpi"), "index", "%", "BLS")
    if B.get("cpi_nsa") and ind and ind[-1]["key"] == "cpi":    # y/y from NSA (as published), m/m from SA
        y = series_stats(B["cpi_nsa"], "index")
        ind[-1].update({"yoy": y["yoy"], "yoy_prev": y["yoy_prev"], "spark": y["spark"]})
    add("Inflation", "cpi_core", "Core CPI (ex food & energy)", B.get("cpi_core"), "index", "%", "BLS")
    if B.get("cpi_core_nsa") and ind and ind[-1]["key"] == "cpi_core":
        y = series_stats(B["cpi_core_nsa"], "index")
        ind[-1].update({"yoy": y["yoy"], "yoy_prev": y["yoy_prev"], "spark": y["spark"]})
    add("Inflation", "cpi_food_home", "CPI food at home", B.get("cpi_food_home"), "index", "%", "BLS", "grocery prices: demand for meat, dairy, grain-based food")
    add("Inflation", "cpi_energy", "CPI energy", B.get("cpi_energy"), "index", "%", "BLS")
    add("Inflation", "ppi", "PPI final demand", B.get("ppi"), "index", "%", "BLS")
    add("Inflation", "ppi_core", "Core PPI", B.get("ppi_core"), "index", "%", "BLS")
    add("Inflation", "ppi_farm", "PPI farm products", B.get("ppi_farm"), "index", "%", "BLS", "prices received at the farm gate (NSA)")
    for key in ("pce_px", "pce_core_px"):
        add("Inflation", key, "PCE inflation" if key == "pce_px" else "Core PCE inflation (Fed's target gauge)", dbn(DBN[key][0]), "index", "%", "BEA via DBnomics")
    add("Jobs", "payrolls", "Nonfarm payrolls (monthly change, k)", B.get("payrolls"), "k", "k", "BLS")
    add("Jobs", "unemp", "Unemployment rate", B.get("unemp"), "level", "%", "BLS")
    add("Jobs", "ahe", "Average hourly earnings", B.get("ahe"), "index", "%", "BLS", "wage growth")
    add("Jobs", "lfpr", "Participation rate", B.get("lfpr"), "level", "%", "BLS")
    for key in ("gdp", "pce_real_q"):
        add("Growth", key, DBN[key][1].replace(" (% q/q annualized)", ""), dbn(DBN[key][0]), "level", "% q/q ann.", "BEA via DBnomics")
    add("Growth", "saving", "Personal saving rate", dbn(DBN["saving"][0]), "level", "%", "BEA via DBnomics")
    try:
        _, pts = dbn_find("SCSMICH/MICS", ["sentiment"])
        if pts:
            add("Sentiment", "umich", "UMich consumer sentiment", pts, "level", "index", "University of Michigan via DBnomics")
    except Exception as e:
        log("umich", e)

    def fresh(i):   # a mirror that stopped updating: monthly older than 6 months, quarterly older than 8
        p = i["period"]
        try:
            if "Q" in p:
                y, q = p.split("-Q")
                return (date.today() - date(int(y), int(q) * 3, 1)).days <= 245
            return (date.today() - date(int(p[:4]), int(p[5:7]), 1)).days <= 190
        except Exception:
            return True
    stale = [i["name"] for i in ind if not fresh(i)]
    if stale:
        NOTES.append("stale, left out: " + ", ".join(stale))
    return [i for i in ind if fresh(i)]


# ---------------- rates (from the source pipeline) ----------------
def treasury_csv(kind, years):
    rows = []
    for yr in years:
        r = get(f"https://home.treasury.gov/resource-center/data-chart-center/interest-rates/daily-treasury-rates.csv/{yr}/all"
                f"?type={kind}&field_tdr_date_value={yr}&page&_format=csv")
        if r is not None and r.text.startswith("Date"):
            rows.append(pd.read_csv(io.StringIO(r.text)))
    if not rows:
        return None
    df = pd.concat(rows)
    df["Date"] = pd.to_datetime(df["Date"])
    return df.sort_values("Date").drop_duplicates("Date").set_index("Date")


def curve():
    y = datetime.now(timezone.utc).year
    df = treasury_csv("daily_treasury_yield_curve", (y - 1, y))
    if df is None:
        NOTES.append("Treasury yield curve did not answer")
        return None
    last = df.iloc[-1]

    def ago(days):
        s = df[df.index <= df.index[-1] - pd.Timedelta(days=days)]
        return s.iloc[-1] if len(s) else None
    tenors = [c for c in ["1 Mo", "3 Mo", "6 Mo", "1 Yr", "2 Yr", "3 Yr", "5 Yr", "7 Yr", "10 Yr", "20 Yr", "30 Yr"] if c in df]
    w, m, yb = ago(7), ago(30), ago(365)
    f = lambda r, t: None if r is None or pd.isna(r[t]) else float(r[t])
    s = df["10 Yr"] - df["2 Yr"]
    return {"date": str(df.index[-1].date()), "curve": [{"tenor": t, "now": f(last, t), "w1": f(w, t), "m1": f(m, t), "y1": f(yb, t)} for t in tenors],
            "s2s10_bp": round(100 * float(s.iloc[-1]), 1),
            "s2s10_chg_1m_bp": round(100 * float(s.iloc[-1] - s[s.index <= s.index[-1] - pd.Timedelta(days=30)].iloc[-1]), 1),
            "s3m10_bp": round(100 * float(last["10 Yr"] - last["3 Mo"]), 1),
            "hist": {t: [[str(d.date()), float(v)] for d, v in df[t].dropna().iloc[-260:].items()] for t in ("3 Mo", "2 Yr", "10 Yr", "30 Yr") if t in df},
            "hist_2y10y": [[str(d.date()), round(100 * float(v), 1)] for d, v in s.dropna().iloc[-260:].items()]}


def rates(cv):
    out = {}
    r = get("https://markets.newyorkfed.org/api/rates/unsecured/effr/last/500.json")
    if r is not None:
        rr = sorted(r.json()["refRates"], key=lambda x: x["effectiveDate"])
        last = rr[-1]
        out.update({"effr": last["percentRate"], "target_lo": last.get("targetRateFrom"), "target_hi": last.get("targetRateTo"), "effr_date": last["effectiveDate"],
                    "effr_hist": [[x["effectiveDate"], x["percentRate"], x.get("targetRateFrom"), x.get("targetRateTo")] for x in rr]})
        tgt = [(x["effectiveDate"], x.get("targetRateTo")) for x in rr]
        out["last_moves"] = [(tgt[i][0], round(tgt[i][1] - tgt[i - 1][1], 2)) for i in range(1, len(tgt)) if tgt[i][1] != tgt[i - 1][1]][-4:]
    else:
        NOTES.append("New York Fed (fed funds) did not answer")
    r = get("https://markets.newyorkfed.org/api/rates/secured/sofr/last/500.json")
    if r is not None:
        rr = sorted(r.json()["refRates"], key=lambda x: x["effectiveDate"])
        out.update({"sofr": rr[-1]["percentRate"], "sofr_date": rr[-1]["effectiveDate"], "sofr_hist": [[x["effectiveDate"], x["percentRate"]] for x in rr]})
    else:
        NOTES.append("New York Fed (SOFR) did not answer")
    y = date.today().year
    real = treasury_csv("daily_treasury_real_yield_curve", (y,))
    if real is not None and len(real):
        row = real.iloc[-1]
        out.update({"real10": float(row["10 YR"]), "real5": float(row["5 YR"]), "real_date": str(real.index[-1].date())})
    if cv:
        tc = {c["tenor"]: c["now"] for c in cv["curve"]}
        out.update({"y2": tc.get("2 Yr"), "y10": tc.get("10 Yr"), "y3m": tc.get("3 Mo"), "y30": tc.get("30 Yr"), "curve_date": cv["date"]})
        if out.get("real10") is not None and tc.get("10 Yr") is not None:
            out["breakeven10"] = round(tc["10 Yr"] - out["real10"], 2)
        if out.get("real5") is not None and tc.get("5 Yr") is not None:
            out["breakeven5"] = round(tc["5 Yr"] - out["real5"], 2)
        if out.get("effr") is not None and tc.get("2 Yr") is not None:
            out["y2_minus_ff"] = round(tc["2 Yr"] - out["effr"], 2)
    return out


# ---------------- Treasury liquidity (new) ----------------
def fiscaldata(path, fields, filt, sort, pages=10):
    rows = []
    for page in range(1, pages + 1):
        r = get(f"{FD}/{path}", params={"fields": fields, "filter": filt, "sort": sort, "page[size]": 1000, "page[number]": page})
        if r is None:
            return rows or None
        j = r.json()
        rows += j.get("data", [])
        if page >= (j.get("meta", {}).get("total-pages") or 1):
            break
    return rows


def num(v):
    try:
        return float(str(v).replace(",", ""))
    except (TypeError, ValueError):
        return None


def liquidity():
    out = {}
    since = (date.today() - timedelta(days=3 * 366)).isoformat()
    # Treasury General Account: the closing balance row of the Daily Treasury Statement (USD millions)
    t = fiscaldata("v1/accounting/dts/operating_cash_balance", "record_date,account_type,open_today_bal,close_today_bal",
                   f"record_date:gte:{since},account_type:eq:Treasury General Account (TGA) Closing Balance", "record_date")
    if t:
        pts = sorted((x["record_date"], num(x.get("open_today_bal")) if num(x.get("close_today_bal")) is None else num(x.get("close_today_bal"))) for x in t)
        pts = [[d, round(v / 1000, 1)] for d, v in pts if v is not None]   # USD billions
        if pts:
            s = pd.Series({pd.Timestamp(d): v for d, v in pts})
            ago = lambda days: s[s.index <= s.index[-1] - pd.Timedelta(days=days)]
            w, m = ago(7), ago(30)
            out["tga"] = {"date": pts[-1][0], "bn": pts[-1][1], "chg_1w": round(pts[-1][1] - w.iloc[-1], 1) if len(w) else None,
                          "chg_1m": round(pts[-1][1] - m.iloc[-1], 1) if len(m) else None, "hist": pts}
    else:
        NOTES.append("Treasury General Account (Daily Treasury Statement) did not answer")
    # bills outstanding, monthly (Monthly Statement of the Public Debt, USD millions)
    b = fiscaldata("v1/debt/mspd/mspd_table_1", "record_date,security_type_desc,security_class_desc,total_mil_amt",
                   f"record_date:gte:{(date.today() - timedelta(days=6 * 366)).isoformat()},security_class_desc:eq:Bills", "record_date")
    if b:
        pts = sorted({x["record_date"]: num(x["total_mil_amt"]) for x in b if x.get("security_type_desc", "").lower().startswith("marketable")}.items())
        pts = [[d, round(v / 1000, 1)] for d, v in pts if v is not None]
        if pts:
            out["bills_outstanding"] = {"date": pts[-1][0], "bn": pts[-1][1], "chg_1m": round(pts[-1][1] - pts[-2][1], 1) if len(pts) > 1 else None,
                                        "chg_12m": round(pts[-1][1] - pts[-13][1], 1) if len(pts) > 12 else None, "hist": pts}
    else:
        NOTES.append("bills outstanding (Monthly Statement of the Public Debt) did not answer")
    # weekly bill issuance, gross and net of maturing bills (auction results; bills last at most 52 weeks)
    a = fiscaldata("v1/accounting/od/auctions_query", "record_date,auction_date,issue_date,maturity_date,security_type,security_term,offering_amt,total_accepted",
                   f"issue_date:gte:{(date.today() - timedelta(days=2 * 366)).isoformat()},security_type:eq:Bill", "issue_date", pages=20)
    if a:
        d = pd.DataFrame(a)
        d["amt"] = [num(x) if num(x) is not None else num(y) for x, y in zip(d.get("total_accepted"), d.get("offering_amt"))]
        d = d.dropna(subset=["amt"])
        d["issue"] = pd.to_datetime(d.issue_date, errors="coerce")
        d["mat"] = pd.to_datetime(d.maturity_date, errors="coerce")
        wk = lambda s: s.dt.to_period("W-SAT").dt.start_time
        iss = d.groupby(wk(d.issue)).amt.sum() / 1e9
        mat = d.groupby(wk(d.mat)).amt.sum() / 1e9
        start = iss.index.min() + pd.Timedelta(weeks=53)   # before this, maturing bills were issued outside the window
        idx = [x for x in iss.index.union(mat.index) if start <= x <= pd.Timestamp(date.today()) + pd.Timedelta(weeks=4)]
        rows = [[str(x.date()), round(float(iss.get(x, 0)), 1), round(float(mat.get(x, 0)), 1), round(float(iss.get(x, 0) - mat.get(x, 0)), 1)] for x in sorted(idx)]
        if rows:
            past = [r for r in rows if r[0] <= date.today().isoformat()]
            out["bill_issuance"] = {"weeks": rows, "net_4w": round(sum(r[3] for r in past[-4:]), 1), "net_13w": round(sum(r[3] for r in past[-13:]), 1),
                                    "note": "Weeks start Sunday. Upcoming weeks include auctions already announced; net = bills issued minus bills maturing, USD bn."}
    else:
        NOTES.append("bill auctions (FiscalData) did not answer")
    return out


def policy_path(rt):
    """Fed funds and SOFR futures strips written earlier in the build by pipelines/prices (Yahoo), with the implied
    change from today's effective rate."""
    from pathlib import Path
    import os
    p = Path(os.environ.get("PRICES_DIR") or Path(__file__).resolve().parents[2] / ".work" / "prices") / "curves.json"
    try:
        pol = json.loads(p.read_text()).get("policy") or {}
    except Exception:
        return None
    base = rt.get("effr")
    for k in ("zq", "sr3"):
        for x in pol.get(k, []):
            x["vs_effr_bp"] = None if base is None else round(100 * (x["rate"] - base))
    return pol if pol.get("zq") or pol.get("sr3") else None


def read(ind, rt, cv, lq):
    g = {i["key"]: i for i in ind}
    txt = []
    if "cpi" in g and g["cpi"].get("yoy") is not None:
        c, cc = g["cpi"], g.get("cpi_core", {})
        txt.append(f"Inflation: CPI {c['yoy']:.1f}% y/y ({c['period']}), core {cc.get('yoy') or 0:.1f}%; core 3-month annualized {cc.get('ann3') or 0:.1f}%"
                   + (f"; core PCE {g['pce_core_px']['yoy']:.1f}%" if g.get("pce_core_px", {}).get("yoy") is not None else "") + ".")
    if "payrolls" in g and g["payrolls"].get("chg") is not None:
        p, u = g["payrolls"], g.get("unemp", {})
        txt.append(f"Jobs: payrolls {p['chg']:+.0f}k in {p['period']} (3-month average {p.get('avg3') or 0:+.0f}k), unemployment {u.get('value') or 0:.1f}%"
                   + (f" ({u['chg']:+.1f})" if u.get("chg") is not None else "") + (f", wages {g['ahe']['yoy']:.1f}% y/y" if g.get("ahe", {}).get("yoy") is not None else "") + ".")
    if "gdp" in g:
        txt.append(f"Growth: real GDP {g['gdp']['value']:.1f}% annualized in {g['gdp']['period']}" + (f", consumer spending {g['pce_real_q']['value']:.1f}%" if "pce_real_q" in g else "") + ".")
    if rt.get("effr") is not None:
        txt.append(f"Policy: fed funds target {rt.get('target_lo')}-{rt.get('target_hi')}% (effective {rt['effr']:.2f}%)"
                   + (f"; 2-year Treasury {rt['y2']:.2f}%" if rt.get("y2") is not None else "")
                   + (f" ({rt['y2_minus_ff']:+.2f} vs fed funds: market {'pricing cuts' if rt['y2_minus_ff'] < -0.15 else 'pricing hikes' if rt['y2_minus_ff'] > 0.15 else 'expecting little change'})" if rt.get("y2_minus_ff") is not None else "")
                   + (f"; 10-year breakeven inflation {rt['breakeven10']:.2f}%, real 10-year {rt['real10']:.2f}%" if rt.get("breakeven10") is not None else "") + "."
                   + (f" {rt['path_note']}." if rt.get("path_note") else ""))
    if lq.get("tga"):
        t = lq["tga"]
        txt.append(f"Liquidity: Treasury cash (TGA) ${t['bn']:,.0f}bn" + (f" ({t['chg_1m']:+,.0f}bn in a month: a rising TGA drains bank reserves)" if t.get("chg_1m") is not None else "")
                   + (f"; net bill issuance {lq['bill_issuance']['net_4w']:+,.0f}bn over 4 weeks" if lq.get("bill_issuance") else "") + ".")
    if "ppi_farm" in g and g["ppi_farm"].get("yoy") is not None:
        txt.append(f"Farm prices (PPI farm products) {g['ppi_farm']['yoy']:+.1f}% y/y; food-at-home CPI {g.get('cpi_food_home', {}).get('yoy') or 0:+.1f}% y/y.")
    txt.append("For ags: high real yields and a firm dollar weigh on fund demand for commodities; sticky inflation keeps rates high (carry and storage costs up); "
               "a weak job market or falling real incomes hits meat and dairy demand first.")
    return " ".join(txt)


def clean(o):
    if isinstance(o, dict):
        return {k: clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [clean(v) for v in o]
    if isinstance(o, float):
        return o if math.isfinite(o) else None
    return o


def main():
    ind, cv, rt, lq = [], None, {}, {}
    for name, fn in (("economy", lambda: economy()), ("curve", lambda: curve())):
        try:
            v = fn()
            if name == "economy":
                ind = v
            else:
                cv = v
        except Exception as e:
            NOTES.append(f"{name} failed ({str(e)[:80]})")
    try:
        rt = rates(cv)
    except Exception as e:
        NOTES.append(f"rates failed ({str(e)[:80]})")
    try:
        lq = liquidity()
    except Exception as e:
        NOTES.append(f"Treasury liquidity failed ({str(e)[:80]})")
    pol = policy_path(rt)
    if pol and pol.get("zq"):
        z = pol["zq"]
        far = z[-1]
        rt["path_note"] = f"Fed funds futures price {far['rate']:.2f}% for {far['m']} ({far['vs_effr_bp']:+d} bp vs today's effective rate)" if far.get("vs_effr_bp") is not None else None
    if not ind and not rt and not cv and not lq:
        raise SystemExit("every macro source failed: " + "; ".join(NOTES))
    dates = [x for x in [rt.get("effr_date"), (cv or {}).get("date"), (lq.get("tga") or {}).get("date")] if x]
    print(json.dumps(clean({"data": {"indicators": ind, "rates": rt, "curve": cv, "liquidity": lq, "policy": pol, "read": read(ind, rt, cv, lq)},
                            "latest": max(dates) if dates else None, "n": len(ind),
                            "src": "BLS; BEA and University of Michigan via DBnomics; New York Fed; U.S. Treasury (yield curves, Daily Treasury Statement, Monthly Statement of the Public Debt, auctions)",
                            "note": "; ".join(NOTES), "partial": bool([n for n in NOTES if not n.startswith("stale")])}),
                     separators=(",", ":"), default=str))


if __name__ == "__main__":
    main()
