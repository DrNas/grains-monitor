"""Positioning desk data: latest-week metrics for every market, crop year and trader category (levels, weekly
and 4-week changes, flow z-score, COT index, percentiles over 1/3/5/10 years and full history), a 26-week
percentile heatmap, index-trader (CIT) flows and breadth, and a weekly history file per market.
Adapted, with permission, from an existing open-source pipeline; the calculations are unchanged.

Price-based parts (technicals, trigger levels, dollar exposure, carry, risk regime) read the futures prices written
earlier in the same build by pipelines/prices; without them they are left out, as in the source.
"""
import json
import math
import os
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd


CATS = ["managed_money", "swap_dealers", "prod_merc", "other_rept"]
WIN = {"f": None, "y10": 520, "y5": 260, "y3": 156, "y1": 52}
STALE_DAYS = 21  # a market with no report in 3 weeks is excluded from cross-sectional views


# ── helpers ────────────────────────────────────────────────────────────────
def _num(v, nd=None):
    """JSON-safe number: NaN/inf -> None, optional rounding, ints stay ints."""
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if math.isnan(f) or math.isinf(f):
        return None
    if nd is None:
        return int(round(f))
    return round(f, nd)


def midrank_pct(hist, v):
    """Percentile of v within hist using mid-rank ties (0-100)."""
    h = hist[~np.isnan(hist)]
    if len(h) == 0 or v is None or np.isnan(v):
        return None
    return round(((h < v).sum() + 0.5 * (h == v).sum()) / len(h) * 100, 1)


def win(arr, w):
    return arr if (w is None or len(arr) <= w) else arr[-w:]


def pct_set(arr, wins=("f", "y5", "y3", "y1")):
    v = arr[-1]
    return {k: midrank_pct(win(arr, WIN[k]), v) for k in wins}


def cot_index(arr, w):
    a = win(arr, w)
    a = a[~np.isnan(a)]
    if len(a) == 0:
        return None
    lo, hi = a.min(), a.max()
    if hi == lo:
        return 50.0
    return round((arr[-1] - lo) / (hi - lo) * 100, 1)


def streak(d):
    """Consecutive weeks (ending now) the weekly change kept the same sign."""
    d = d[~np.isnan(d)]
    if len(d) == 0 or d[-1] == 0:
        return 0
    s = np.sign(d[-1])
    n = 0
    for x in d[::-1]:
        if np.sign(x) == s:
            n += 1
        else:
            break
    return int(n * s)


# ── per-category metrics ───────────────────────────────────────────────────
def cat_metrics(g, cat):
    """g: rows for one commodity+crop_type sorted by date."""
    L = g[f"{cat}_long"].to_numpy(float)
    S = g[f"{cat}_short"].to_numpy(float)
    Sp = g[f"{cat}_spread"].to_numpy(float)
    TL = g[f"{cat}_traders_long"].to_numpy(float)
    TS = g[f"{cat}_traders_short"].to_numpy(float)
    oi = g["open_interest"].to_numpy(float)
    N = L - S
    with np.errstate(divide="ignore", invalid="ignore"):
        lp = np.where(oi > 0, L / oi * 100, 0.0)
        sp = np.where(oi > 0, S / oi * 100, 0.0)
    npc = lp - sp

    def d(a, k=1):
        return a[-1] - a[-1 - k] if len(a) > k else 0.0

    dN = np.diff(N) if len(N) > 1 else np.array([0.0])
    hist = win(dN, 156)
    sd = np.nanstd(hist) if len(hist) > 4 else np.nan
    z = (dN[-1] / sd) if sd and not np.isnan(sd) and sd > 0 else 0.0

    return {
        "L": _num(L[-1]), "S": _num(S[-1]), "Sp": _num(Sp[-1]), "N": _num(N[-1]),
        "TL": _num(TL[-1]), "TS": _num(TS[-1]),
        "lp": _num(lp[-1], 2), "sp": _num(sp[-1], 2), "np": _num(npc[-1], 2),
        "dL": _num(d(L)), "dS": _num(d(S)), "dN": _num(d(N)), "dN4": _num(d(N, 4)),
        "dTL": _num(d(TL)), "dTS": _num(d(TS)), "dnp": _num(d(npc), 2),
        "z": _num(z, 2), "streak": streak(dN),
        "cot3": cot_index(N, 156), "cot1": cot_index(N, 52), "cot5": cot_index(N, 260),
        "p": {
            "N": pct_set(N), "L": pct_set(L), "S": pct_set(S),
            "np": pct_set(npc), "lp": pct_set(lp), "sp": pct_set(sp),
            "TL": pct_set(TL, ("f", "y3")), "TS": pct_set(TS, ("f", "y3")),
        },
        "r": {
            "N": [_num(np.nanmin(N)), _num(np.nanmax(N))],
            "np": [_num(np.nanmin(npc), 2), _num(np.nanmax(npc), 2)],
            "L": [_num(np.nanmin(L)), _num(np.nanmax(L))],
            "lp": [_num(np.nanmin(lp), 2), _num(np.nanmax(lp), 2)],
            "S": [_num(np.nanmin(S)), _num(np.nanmax(S))],
            "sp": [_num(np.nanmin(sp), 2), _num(np.nanmax(sp), 2)],
        },
        "spark": [_num(x) for x in win(N, 52)],
    }


# ── prices & technicals ─────────────────────────────────────────────────────
SEASONAL_CURVE = {"NG", "LC", "LH"}   # Fama-French: carry unreliable on seasonal curves


# Dollars per 1.00 of quoted price, per contract (front-month quote units from Yahoo):
# grains ¢/bu x 5,000 bu; meal $/st x 100; oil ¢/lb x 60,000; cotton ¢/lb x 50,000;
# sugar ¢/lb x 112,000; coffee ¢/lb x 37,500; cocoa $/t x 10; cattle/hogs ¢/lb x 40,000 (feeder 50,000)
CONTRACT_USD = {"C": 50, "S": 50, "W": 50, "KW": 50, "SM": 100, "BO": 600, "CT": 500, "SB": 1120,
                "KC": 375, "CC": 10, "LC": 400, "LH": 400, "FC": 500,
                # energy & metals: $/bbl x 1,000; $/MMBtu x 10,000; $/gal x 42,000; $/lb x 25,000; $/oz x 100 / 5,000
                "CL": 1000, "CO": 1000, "NG": 10000, "HO": 42000, "XB": 42000, "HG": 25000, "GC": 100, "SI": 5000}
# ALI has no $ value: its COT contract is the Midwest Premium, its price series is COMEX aluminum
PRICE_STALE_DAYS = 7
PCT_WINS = ("y1", "y3", "y5", "y10", "f")


def load_cit(c):
    """Index-trader (CIT) supplemental report, 13 ag markets (a DataFrame). Empty dict if missing."""
    if c is None or c.empty:
        return {}
    c = c.copy()
    c["date"] = pd.to_datetime(c["date"]).dt.strftime("%Y-%m-%d")
    return {t: g.drop_duplicates("date", keep="last").set_index("date").sort_index()
            for t, g in c.groupby("ticker")}


def front_close_on(prices, ticker, dates):
    """Unadjusted front-month close on/before each COT date (within 7 days), for $ exposure."""
    pg = prices.get(ticker)
    if pg is None or not len(pg):
        return pd.Series(np.nan, index=dates)
    cs = pg["close"].dropna()
    dt = pd.to_datetime(pd.Index(dates))
    idx = cs.index.searchsorted(dt, side="right") - 1
    out = [cs.iloc[i] if i >= 0 and (d - cs.index[i]).days <= 7 else np.nan for i, d in zip(idx, dt)]
    return pd.Series(out, index=dates, dtype=float)


def _usd(n, px, mult):
    if n is None or px is None or mult is None or (isinstance(px, float) and math.isnan(px)):
        return None
    return _num(n * px * mult)


def price_ok(pg, rd, latest_px):
    """Price usable only if the Yahoo series is current: within PRICE_STALE_DAYS of the COT
    report date and of the freshest price in the file. Otherwise charts and levels drop price."""
    if pg is None or not len(pg.dropna(subset=["close"])):
        return False
    last = pg.dropna(subset=["close"]).index[-1]
    return (rd - last).days <= PRICE_STALE_DAYS and (latest_px - last).days <= 5


def trigger_levels(pg, ticker, front=None):
    """Price levels where the technical signals funds react to would flip. Uses the tradable
    front contract's own history when it covers 200+ sessions (levels you can put orders at),
    otherwise the roll-adjusted continuous series anchored to today's price."""
    fr = front.dropna(subset=["close"]) if front is not None else None
    if fr is not None and len(fr) >= 205:
        g = fr; c = g["close"]; src = str(g["contract"].iloc[-1])
        hi = g["high"].fillna(c); lo = g["low"].fillna(c)
    else:
        g = pg.dropna(subset=["close"])
        if len(g) < 210:
            return None
        adj, _ = back_adjust(g["close"], ticker)
        k = adj / g["close"]
        hi = (g["high"].fillna(g["close"]) * k); lo = (g["low"].fillna(g["close"]) * k)
        c = adj; src = "continuous"
    last = float(c.iloc[-1])
    tr = pd.concat([hi - lo, (hi - c.shift()).abs(), (lo - c.shift()).abs()], axis=1).max(axis=1)
    atr = float(tr.ewm(alpha=1 / 14, adjust=False).mean().iloc[-1])
    out = {"close": _num(last, 4), "atr": _num(atr, 4), "date": g.index[-1].strftime("%Y-%m-%d"), "src": src, "lv": []}
    for n in (20, 55, 100):
        H = hi.rolling(n).max().shift(); L = lo.rolling(n).min().shift()
        st = pd.Series(np.where(c > H, 1, np.where(c < L, -1, np.nan)), index=c.index).ffill()
        out["lv"].append({"k": f"d{n}", "name": f"{n}-day breakout", "state": _num(st.iloc[-1]) if not np.isnan(st.iloc[-1]) else 0,
                          "up": _num(float(hi.iloc[-n:].max()), 4), "dn": _num(float(lo.iloc[-n:].min()), 4)})
    for n in (50, 100, 200):
        m = float(c.rolling(n).mean().iloc[-1])
        out["lv"].append({"k": f"s{n}", "name": f"{n}-day average", "state": 1 if last > m else -1, "lvl": _num(m, 4)})
    ema = lambda sp: c.ewm(span=sp, adjust=False).mean()
    macd = float(ema(12).iloc[-1] - ema(26).iloc[-1])
    out["macd"] = 1 if macd > 0 else -1
    # nearest flip level in each direction
    ups, dns = [], []
    for x in out["lv"]:
        if "lvl" in x:
            (ups if x["lvl"] > last else dns).append((x["lvl"], x["name"]))
        else:
            if x["state"] != 1: ups.append((x["up"], x["name"] + " high"))
            if x["state"] != -1: dns.append((x["dn"], x["name"] + " low"))
    if ups:
        u = min(ups); out["next_up"] = {"lvl": u[0], "name": u[1], "pct": _num(u[0] / last - 1, 4), "atr": _num((u[0] - last) / atr, 2) if atr else None}
    if dns:
        d = max(dns); out["next_dn"] = {"lvl": d[0], "name": d[1], "pct": _num(d[0] / last - 1, 4), "atr": _num((d[0] - last) / atr, 2) if atr else None}
    return out


def mm_usd(g, px, mult):
    """Managed-money exposure in dollars (all crop years) at the latest front-month price."""
    if px is None or not mult or len(g) < 2:
        return None
    L = g["managed_money_long"].to_numpy(float); S = g["managed_money_short"].to_numpy(float); N = L - S
    return {"N": _num(N[-1]), "dN": _num(N[-1] - N[-2]), "dN4": _num(N[-1] - N[-5]) if len(N) > 4 else None,
            "Lusd": _usd(L[-1], px, mult), "Susd": _usd(S[-1], px, mult), "Nusd": _usd(N[-1], px, mult),
            "dNusd": _usd(N[-1] - N[-2], px, mult), "dN4usd": _usd(N[-1] - N[-5], px, mult) if len(N) > 4 else None, "px": _num(px, 4)}


def heat_row(g, weeks=26, look=156):
    """Managed-money net percentile vs the prior 3 years, for each of the last `weeks` reports."""
    N = (g["managed_money_long"] - g["managed_money_short"]).to_numpy(float)
    out = []
    for i in range(len(N) - weeks, len(N)):
        if i < 52:
            out.append(None); continue
        h = N[max(0, i - look):i + 1]
        out.append(midrank_pct(h, N[i]))
    return out


def cit_metrics(g, px, mult, mm=None):
    """Latest-week index-trader metrics for one market (g indexed by date; px aligned to g.index)."""
    L = g["cit_long"].to_numpy(float); S = g["cit_short"].to_numpy(float)
    oi = g["open_interest"].to_numpy(float); N = L - S
    TL = g["cit_traders_long"].to_numpy(float)
    with np.errstate(divide="ignore", invalid="ignore"):
        npc = np.where(oi > 0, N / oi * 100, 0.0)
        lp = np.where(oi > 0, L / oi * 100, 0.0)
        ptl = np.where(TL > 0, L / TL, np.nan)
    P = px.to_numpy(float)
    Nusd = N * P * mult if mult else np.full(len(N), np.nan)

    def d(a, k=1):
        return a[-1] - a[-1 - k] if len(a) > k else None

    dN = np.diff(N) if len(N) > 1 else np.array([0.0])
    sd = np.nanstd(win(dN, 156)) if len(dN) > 4 else np.nan
    z = (dN[-1] / sd) if sd and not np.isnan(sd) and sd > 0 else 0.0
    rb = g["rebalance_window"].astype(str).str.lower().eq("true").to_numpy()
    p_last = P[-1] if len(P) and not np.isnan(P[-1]) else None
    nusd_ok = Nusd[~np.isnan(Nusd)]
    out = {
        "date": g.index[-1], "L": _num(L[-1]), "S": _num(S[-1]), "N": _num(N[-1]),
        "TL": _num(TL[-1]), "TS": _num(g["cit_traders_short"].iloc[-1]), "PTL": _num(ptl[-1]),
        "np": _num(npc[-1], 2), "lp": _num(lp[-1], 2),
        "dN": _num(d(N)), "dN4": _num(d(N, 4)), "dN13": _num(d(N, 13)), "dN52": _num(d(N, 52)),
        "dL": _num(d(L)), "dS": _num(d(S)),
        "dnp4": _num(d(npc, 4), 2), "dnp13": _num(d(npc, 13), 2),
        "z": _num(z, 2), "streak": streak(dN), "rebal": bool(rb[-1]),
        "px": _num(p_last, 4) if p_last is not None else None, "mult": mult,
        "Lusd": _usd(L[-1], p_last, mult), "Susd": _usd(S[-1], p_last, mult), "Nusd": _usd(N[-1], p_last, mult),
        "dNusd": _usd(d(N), p_last, mult), "dN4usd": _usd(d(N, 4), p_last, mult),
        "p": {"N": pct_set(N, PCT_WINS), "np": pct_set(npc, PCT_WINS), "L": pct_set(L, PCT_WINS),
              "Nusd": pct_set(nusd_ok, PCT_WINS) if len(nusd_ok) > 10 and not np.isnan(Nusd[-1]) else None},
        "cot3": cot_index(N, 156),
        "r": {"N": [_num(np.nanmin(N)), _num(np.nanmax(N))], "np": [_num(np.nanmin(npc), 2), _num(np.nanmax(npc), 2)]},
        "spark": [_num(x) for x in win(N, 52)],
    }
    if mm is not None and len(mm) > 1:
        mN = (mm["managed_money_long"] - mm["managed_money_short"]).to_numpy(float)
        out["mm"] = {"N": _num(mN[-1]), "dN": _num(mN[-1] - mN[-2]), "dN4": _num(mN[-1] - mN[-5]) if len(mN) > 4 else None,
                     "Nusd": _usd(mN[-1], p_last, mult), "dNusd": _usd(mN[-1] - mN[-2], p_last, mult)}
    return out


def cit_aggregate(cit, rd, snaps):
    """Complex-wide index flow, in lots and dollars, by sector and market (snaps: ticker -> cit metrics)."""
    rows = []
    for t, g in cit.items():
        if (rd - pd.to_datetime(g.index[-1])).days > STALE_DAYS or len(g) < 14 or t not in snaps:
            continue
        m = snaps[t]
        N = g["cit_net"].to_numpy(float); oi = g["open_interest"].to_numpy(float)
        npc = np.where(oi > 0, N / oi * 100, 0.0)
        mm = m.get("mm") or {}
        rows.append({"t": t, "sector": g["sector"].iloc[-1], "name": g["commodity"].iloc[-1],
                     "N": m["N"], "dN": N[-1] - N[-2], "dN4": N[-1] - N[-5], "dN13": N[-1] - N[-14],
                     "dnp4": npc[-1] - npc[-5], "dnp13": npc[-1] - npc[-14],
                     "Lusd": m.get("Lusd"), "Susd": m.get("Susd"), "Nusd": m.get("Nusd"),
                     "dNusd": m.get("dNusd"), "dN4usd": m.get("dN4usd"),
                     "mmN": mm.get("N"), "mmdN": mm.get("dN"), "mmNusd": mm.get("Nusd"), "mmdNusd": mm.get("dNusd")})
    if not rows:
        return None
    r = pd.DataFrame(rows)
    allg = pd.concat([g.assign(t=t)[["cit_net", "t"]] for t, g in cit.items()])
    allg.index = pd.to_datetime(allg.index)
    w = allg.pivot_table(index=allg.index, columns="t", values="cit_net").sort_index()
    br = ((w.diff(4) > 0).sum(axis=1) / w.notna().sum(axis=1) * 100).dropna()
    usd_cols = ["Lusd", "Susd", "Nusd", "dNusd", "dN4usd", "mmNusd", "mmdNusd"]

    def tot(df):
        o = {k: _num(df[k].sum(min_count=1)) for k in usd_cols}
        o.update({k: _num(df[k].sum()) for k in ["N", "dN", "dN4", "mmN", "mmdN"]})
        o["dnp4"] = _num(df.dnp4.mean(), 2); o["dnp13"] = _num(df.dnp13.mean(), 2); o["n"] = len(df)
        o["adding4"] = int((df.dN4 > 0).sum())
        return o

    last = max(g.index[-1] for g in cit.values()); ld = pd.to_datetime(last)
    return {
        "date": last, "n": len(r),
        "adding4": int((r.dN4 > 0).sum()), "adding13": int((r.dN13 > 0).sum()),
        "avg_dnp4": _num(r.dnp4.mean(), 2), "avg_dnp13": _num(r.dnp13.mean(), 2),
        "rebal": bool(ld.month == 1 and ld.day <= 20),
        "breadth4": _num(br.iloc[-1], 1) if len(br) else None,
        "breadth4_pct": midrank_pct(br.to_numpy(float), br.iloc[-1]) if len(br) else None,
        "breadth_hist": {"dates": [d.strftime("%Y-%m-%d") for d in br.index[-520:]],
                         "v": [_num(x, 1) for x in br.iloc[-520:]]},
        "total": tot(r),
        "sectors": {k: tot(v) for k, v in r.groupby("sector")},
        "markets": [{k: (_num(v) if isinstance(v, (int, float, np.floating, np.integer)) and k not in ("dnp4", "dnp13") else
                         (_num(v, 2) if k in ("dnp4", "dnp13") else v)) for k, v in row.items()} for row in rows],
        "top_in": [{"name": x["name"], "dnp4": _num(x["dnp4"], 2), "dN4": _num(x["dN4"])} for x in r.sort_values("dnp4", ascending=False).head(3).to_dict("records")],
        "top_out": [{"name": x["name"], "dnp4": _num(x["dnp4"], 2), "dN4": _num(x["dN4"])} for x in r.sort_values("dnp4").head(3).to_dict("records")],
    }


# Markets whose continuous "=F" series has large roll gaps (seasonal / quarterly curves).
ROLL_ADJUST = {"C", "S", "SM", "BO", "W", "KW", "SB", "KC", "CC", "CT", "LC", "LH", "NG"}


PRICES_DIR = Path(os.environ.get("PRICES_DIR") or Path(__file__).resolve().parents[2] / ".work" / "prices")


def load_prices():
    """Futures prices written earlier in the same build by pipelines/prices (the source's file layout).
    Missing files (the price source failed) leave the price-based parts out, as the source does."""
    daily, rep_p, front = PRICES_DIR / "daily.csv", PRICES_DIR / "report.json", PRICES_DIR / "front_contract.csv"
    if not daily.exists():
        return {}, {}, {}
    p = pd.read_csv(daily, parse_dates=["date"])
    rep = json.loads(rep_p.read_text()) if rep_p.exists() else {}
    fr = {}
    if front.exists():
        f = pd.read_csv(front, parse_dates=["date"])
        fr = {tk: g.set_index("date").sort_index() for tk, g in f.groupby("ticker")}
    return {tk: g.set_index("date").sort_index() for tk, g in p.groupby("ticker")}, rep, fr


def back_adjust(close, ticker):
    """Remove roll gaps from an unadjusted front-month series (ratio back-adjust).
    A day counts as a roll gap when its log move exceeds 3.5x the trailing 60-day
    stdev; that day's return is set to zero. Applied only to markets with
    seasonal/quarterly curves, where Yahoo's roll creates 5-25% jumps."""
    c = close.where(close > 0)
    lr = np.log(c / c.shift())
    if ticker in ROLL_ADJUST:
        sd = lr.rolling(60, min_periods=20).std().shift()
        gap = lr.abs() > 3.5 * sd
        lr = lr.mask(gap, 0.0)
    lr = lr.fillna(0.0)
    adj = np.exp(lr.cumsum())
    return adj / adj.iloc[-1] * close.iloc[-1], int(gap.sum()) if ticker in ROLL_ADJUST else 0


def rsi(c, n=14):
    d = c.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    return 100 - 100 / (1 + up / dn.replace(0, np.nan))


def px_metrics(g, carry=None, ticker=None, front=None):
    """Trend from the roll-adjusted continuous series; levels and short-term
    technicals from the tradable front contract when its history is long enough."""
    g = g.dropna(subset=["close"])
    if len(g) < 60:
        return None
    adj, ngaps = back_adjust(g["close"], ticker)
    def ret(s, n):
        return float(s.iloc[-1] / s.iloc[-1 - n] - 1) if len(s) > n and s.iloc[-1 - n] > 0 else None
    r12, r6 = ret(adj, 252), ret(adj, 126)
    s200 = float(adj.rolling(200).mean().iloc[-1]) if len(adj) >= 200 else None
    vs200 = (float(adj.iloc[-1]) / s200 - 1) if s200 else None
    trend = 0.0
    if r12:
        sg = 1 if r12 > 0 else -1
        conf = int(r6 is not None and np.sign(r6) == sg) + int(vs200 is not None and np.sign(vs200) == sg)
        trend = sg * {2: 1.0, 1: 0.5, 0: 0.0}[conf]
    lra = np.log(adj / adj.shift())
    hi52, lo52 = float(adj.iloc[-252:].max()), float(adj.iloc[-252:].min())
    rng52 = (float(adj.iloc[-1]) - lo52) / (hi52 - lo52) * 100 if hi52 > lo52 else None

    # short-term: the actual contract if we have >= 30 sessions of it, else adjusted series
    src, contract = None, None
    if front is not None and len(front.dropna(subset=["close"])) >= 30:
        src = front.dropna(subset=["close"]); contract = str(src["contract"].iloc[-1])
    else:
        src = pd.DataFrame({"close": adj, "high": adj, "low": adj})
    c, h, l = src["close"], src["high"].fillna(src["close"]), src["low"].fillna(src["close"])
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    atr = tr.ewm(alpha=1 / 14, adjust=False).mean()
    lr = np.log(c / c.shift()).replace([np.inf, -np.inf], np.nan)
    sma = lambda n: (float(c.rolling(n).mean().iloc[-1]) if len(c) >= n else None)
    cy = None
    if carry and carry.get("carry_ann") is not None:
        cy = {"ann": carry["carry_ann"], "front": carry.get("front"), "deferred": carry.get("deferred"),
              "seasonal": ticker in SEASONAL_CURVE}
    return {
        "date": c.index[-1].strftime("%Y-%m-%d"), "close": _num(c.iloc[-1], 4), "contract": contract,
        "r1w": _num(ret(c, 5), 4), "r4w": _num(ret(c, 20), 4), "r13w": _num(ret(adj, 63), 4),
        "r26w": _num(r6, 4), "r52w": _num(r12, 4), "vs200": _num(vs200, 4),
        "sma20": _num(sma(20), 4), "sma50": _num(sma(50), 4),
        "rsi": _num(rsi(c).iloc[-1], 1), "atr": _num(atr.iloc[-1], 4),
        "rv20": _num(lr.iloc[-20:].std() * np.sqrt(252), 4),
        "rv60": _num(lra.iloc[-60:].std() * np.sqrt(252), 4),
        "rng52": _num(rng52, 1), "hi20": _num(float(h.iloc[-20:].max()), 4), "lo20": _num(float(l.iloc[-20:].min()), 4),
        "trend": trend, "carry": cy, "roll_gaps_removed": ngaps,
        "spark": [_num(x, 4) for x in adj.iloc[-260::5]],
    }


# ── builders ───────────────────────────────────────────────────────────────
def build(df, bcom_meta=None, cit_df=None):
    """df: COT rows (cftc.process_records); cit_df: CIT rows. Returns (snapshot, manifest, {ticker: series})."""
    series_out = {}
    df = df.copy()
    df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
    report_date = df["date"].max()
    rd = pd.to_datetime(report_date)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    meta_by_name = bcom_meta or {}
    order = list(meta_by_name.keys()) or sorted(df["commodity"].unique())

    manifest = {"report_date": report_date, "generated": now,
                "data_from": df["date"].min(), "commodities": []}
    snapshot = {"report_date": report_date, "generated": now, "commodities": []}
    prices, prep, fronts = load_prices()
    cit = load_cit(cit_df)
    latest_px = max((g.dropna(subset=["close"]).index[-1] for g in prices.values() if len(g.dropna(subset=["close"]))), default=rd)
    heat = {"dates": None, "rows": []}
    mm_rows = []
    cit_snaps = {}
    if cit:
        manifest["cit_tickers"] = sorted(cit.keys())
    if prep:
        snapshot["regime"] = prep.get("regime")
        snapshot["prices_fetched"] = prep.get("fetched_at")
        manifest["prices_fetched"] = prep.get("fetched_at")

    for name in order:
        cd = df[df["commodity"] == name]
        if cd.empty:
            continue
        first = cd.iloc[0]
        m = meta_by_name.get(name, {})
        ticker = m.get("ticker", first["ticker"])
        sector = m.get("sector", first["sector"])
        is_crop = bool(m.get("crop", str(first["is_crop"]).lower() == "true"))
        crop_types = [c for c in ["all", "old", "other"] if (cd["crop_type"] == c).any()]
        last = cd[cd["crop_type"] == "all"]["date"].max()
        stale = (rd - pd.to_datetime(last)).days > STALE_DAYS

        manifest["commodities"].append({
            "name": name, "ticker": ticker, "sector": sector, "is_crop": is_crop,
            "code": m.get("code"), "cftc": m.get("cftc"),
            "crop_types": crop_types, "last_date": last, "stale": stale,
        })

        # ── series file ──
        all_dates = sorted(cd[cd["crop_type"] == "all"]["date"].unique())
        ser = {"name": name, "ticker": ticker, "sector": sector, "is_crop": is_crop,
               "dates": all_dates, "ct": {}}
        snap = {"name": name, "ticker": ticker, "sector": sector, "is_crop": is_crop,
                "date": last, "stale": stale, "v": {}}
        pg = prices.get(ticker)
        pok = price_ok(pg, rd, latest_px)
        snap["px_ok"] = bool(pok)
        if pok:
            snap["px"] = px_metrics(pg, (prep.get("carry") or {}).get(ticker), ticker, fronts.get(ticker))
            note = ((prep.get("markets") or {}).get(ticker) or {}).get("note")
            if snap["px"] and note:
                snap["px"]["note"] = note
            # weekly close aligned to each COT report date (last close on/before Tuesday)
            cs = back_adjust(pg["close"].dropna(), ticker)[0]
            idx = cs.index.searchsorted(pd.to_datetime(all_dates), side="right") - 1
            ser["px"] = [(_num(cs.iloc[i], 4) if i >= 0 and (pd.to_datetime(d) - cs.index[i]).days <= 7 else None)
                         for i, d in zip(idx, all_dates)]
        cg = cit.get(ticker)
        if cg is not None and len(cg) > 1:
            mult = CONTRACT_USD.get(ticker)
            cpx = front_close_on(prices, ticker, cg.index) if pok else pd.Series(np.nan, index=cg.index)
            cr = cg.reindex(all_dates)
            cpa = front_close_on(prices, ticker, all_dates) if pok else pd.Series(np.nan, index=all_dates)
            col = lambda k: [_num(x) for x in cr[k]]
            ser["cit"] = {"l": col("cit_long"), "s": col("cit_short"), "tl": col("cit_traders_long"), "ts": col("cit_traders_short"),
                          "oi": col("open_interest"), "ncl": col("noncomm_long"), "ncs": col("noncomm_short"),
                          "cml": col("comm_long"), "cms": col("comm_short"), "nrl": col("nonrept_long"), "nrs": col("nonrept_short"),
                          "px": [_num(x, 4) for x in cpa], "mult": mult}
            mmg = (cd[cd["crop_type"] == "all"].drop_duplicates("date", keep="last").set_index("date").sort_index())
            snap["cit"] = cit_metrics(cg, cpx, mult, mmg)
            cit_snaps[ticker] = snap["cit"]
        for ct in crop_types:
            g = (cd[cd["crop_type"] == ct].drop_duplicates("date", keep="last")
                 .set_index("date").reindex(all_dates))
            blk = {"oi": [_num(x) for x in g["open_interest"]]}
            for cat in CATS:
                blk[cat] = {
                    "l": [_num(x) for x in g[f"{cat}_long"]],
                    "s": [_num(x) for x in g[f"{cat}_short"]],
                    "sp": [_num(x) for x in g[f"{cat}_spread"]],
                    "tl": [_num(x) for x in g[f"{cat}_traders_long"]],
                    "ts": [_num(x) for x in g[f"{cat}_traders_short"]],
                }
            ser["ct"][ct] = blk

            gv = g.dropna(subset=["open_interest"]).reset_index()
            if len(gv) < 2:
                continue
            oi = gv["open_interest"].to_numpy(float)
            snap["v"][ct] = {
                "date": gv["date"].iloc[-1],
                "oi": _num(oi[-1]), "doi": _num(oi[-1] - oi[-2]),
                "doi4": _num(oi[-1] - oi[-5]) if len(oi) > 4 else None,
                "poi": pct_set(oi, ("f", "y3")),
                "cats": {cat: cat_metrics(gv, cat) for cat in CATS},
            }
        if pok:
            try:
                snap["trig"] = trigger_levels(pg, ticker, fronts.get(ticker))
            except Exception as e:  # noqa: BLE001
                print("  trigger levels failed", ticker, e)
        ga = cd[cd["crop_type"] == "all"].drop_duplicates("date", keep="last").set_index("date").sort_index()
        mult = CONTRACT_USD.get(ticker)
        fpx = front_close_on(prices, ticker, [ga.index[-1]]).iloc[-1] if pok else np.nan
        mu = mm_usd(ga, None if np.isnan(fpx) else float(fpx), mult)
        if mu:
            snap["mm_usd"] = mu
            mm_rows.append(dict(mu, name=name, ticker=ticker, sector=sector))
        if len(ga) > 60 and not stale:
            hr = heat_row(ga)
            if heat["dates"] is None:
                heat["dates"] = list(ga.index[-26:])
            heat["rows"].append({"name": name, "ticker": ticker, "sector": sector, "v": hr})
        series_out[ticker] = ser
        snapshot["commodities"].append(snap)

    snapshot["heat"] = heat
    if mm_rows:
        r = pd.DataFrame(mm_rows)
        def tot(df):
            return {k: _num(df[k].sum(min_count=1)) for k in ["Nusd", "dNusd", "dN4usd", "Lusd", "Susd", "N", "dN"]}
        snapshot["mm_usd"] = {"total": tot(r), "sectors": {k: tot(v) for k, v in r.groupby("sector")},
                              "markets": [{k: v for k, v in x.items()} for x in mm_rows]}
    if cit and cit_snaps:
        agg = cit_aggregate(cit, rd, cit_snaps)
        if agg:
            snapshot["cit_agg"] = agg
    return snapshot, manifest, series_out
