"""Backtests desk: does trend, positioning (COT), fundamentals or seasonality predict futures returns, across the 21
Bloomberg Commodity Index markets the CFTC reports? Adapted, with permission, from an existing open-source backtest
lab: the strategies, sizing (10% annual volatility per market, 5 bp cost per unit of turnover), timing (COT known on
Friday, traded from the next session) and statistics (in-sample to 2018 vs 2019 on, recent-regime windows, the
multiple-testing noise bar) are unchanged.

Data here: daily front-month continuous prices from the prices pipeline (.work/prices/daily.csv), with roll gaps
removed as the source does for markets without contract histories; COT from the positioning pipeline's per-market
history (.work/positioning/); U.S. stocks-to-use from the WASDE history for the grains. Carry rules need a carry
history the free price feed does not have, so they are left out (the source code already skips them then).

Run by scripts/build-data.mjs; prints {data, files, latest, n, src, note, partial} as JSON on stdout.
When the latest price date is the same as the previous build's, it asks the build to reuse that result.
"""
import json, math, os, sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
WORK = ROOT / ".work"
sys.path.insert(0, str(ROOT / "pipelines" / "wasde"))

STORABLE = {"C", "S", "SM", "BO", "W", "KW", "CT", "KC", "SB", "CC", "CO", "CL", "HO", "XB", "GC", "SI", "HG", "ALI"}
NAMES = {"CO": "Brent crude", "NG": "Natural gas", "CL": "WTI crude", "HO": "ULSD", "XB": "RBOB gasoline", "C": "Corn", "S": "Soybeans",
         "SM": "Soybean meal", "BO": "Soybean oil", "W": "Chicago wheat", "KW": "KC HRW wheat", "HG": "Copper", "ALI": "Aluminum",
         "GC": "Gold", "SI": "Silver", "SB": "Sugar", "KC": "Coffee", "CC": "Cocoa", "CT": "Cotton", "LC": "Live cattle", "LH": "Lean hogs"}
GROUP = {"C": "Grains", "S": "Grains", "SM": "Grains", "BO": "Grains", "W": "Grains", "KW": "Grains", "CT": "Softs", "KC": "Softs", "SB": "Softs",
         "CC": "Softs", "LC": "Livestock", "LH": "Livestock", "NG": "Energy", "CL": "Energy", "HO": "Energy", "XB": "Energy", "CO": "Energy",
         "GC": "Metals", "SI": "Metals", "HG": "Metals", "ALI": "Metals"}
DESK = NAMES
WASDE_KEY = {"C": ("corn", 9), "S": ("soybeans", 9), "SM": ("meal", 10), "BO": ("oil", 10), "W": ("wheat", 6), "KW": ("wheat", 6)}
SPLIT = pd.Timestamp("2019-01-01")
WINDOWS = {"r_is": ("2020-01-01", "2023-12-31"), "r_oos": ("2024-01-01", "2025-12-31"), "live": ("2026-01-01", "2100-01-01")}


def log(*a):
    print(*a, file=sys.stderr, flush=True)


def avg_hold_weeks(pos):
    """Average length (weeks) of a run of the same non-zero position."""
    sg = np.sign(pd.Series(pos).fillna(0).values)
    runs, cur = [], 0
    for i, x in enumerate(sg):
        if x != 0 and i > 0 and x == sg[i - 1]:
            cur += 1
        else:
            if cur:
                runs.append(cur)
            cur = 1 if x != 0 else 0
    if cur:
        runs.append(cur)
    return round(float(np.mean(runs)), 1) if runs else None


def horizon(hw):
    return None if hw is None else ("Short-term (about a week)" if hw <= 2.5 else "Long-term (several weeks+)")
TARGET, COST = 0.10, 0.0005


TARGET, COST = 0.10, 0.0005


# ---------------------------------------------------------------- data (new: this site's prices, COT and WASDE)
def market(tk, px, cot_dir):
    """Weekly frame in the source's layout from daily continuous prices (roll gaps removed) and the COT history."""
    p = px[px.ticker == tk].set_index("date").close.astype(float).dropna()
    p = p[p.index >= "2006-01-01"]
    if len(p) < 1500:
        return None
    r = p.pct_change()
    sd = r.rolling(60, min_periods=20).std().shift(1)
    r = r.where(~(r.abs() > 4 * sd), 0).fillna(0)          # roll gaps in the continuous series (as the source)
    idx = (1 + r.clip(-0.25, 0.25)).cumprod()
    daily = pd.DataFrame({"px": idx})
    for n in (20, 50, 100, 200, 275):
        daily[f"ma{n}"] = idx.rolling(n, min_periods=int(n * .9)).mean()
    for n in (20, 55, 100):
        daily[f"hi{n}"] = idx.shift(1).rolling(n).max()
        daily[f"lo{n}"] = idx.shift(1).rolling(n).min()
    fri = daily.resample("W-FRI").last()
    nxt = idx.reindex(idx.index.union(fri.index + pd.Timedelta(days=1))).bfill()
    fri["exec"] = nxt.reindex(fri.index + pd.Timedelta(days=1)).values     # close of the first session after Friday
    fri["ret"] = fri.exec.shift(-1) / fri.exec - 1
    fri["wk_hi55"] = fri.px.shift(1).rolling(55).max()
    fri["wk_lo55"] = fri.px.shift(1).rolling(55).min()
    for n in (20, 55, 100):
        up = (daily.px > daily[f"hi{n}"]).resample("W-FRI").max()
        dn = (daily.px < daily[f"lo{n}"]).resample("W-FRI").max()
        fri[f"bo_up{n}"], fri[f"bo_dn{n}"] = up.reindex(fri.index).fillna(False), dn.reindex(fri.index).fillna(False)
    cp = cot_dir / f"{tk}.json"
    if cp.exists():
        j = json.loads(cp.read_text())
        a = j["ct"]["all"]
        d = pd.to_datetime(j["dates"]) + pd.Timedelta(days=3)               # Tuesday positions, released Friday
        num = lambda x: pd.Series(x, index=d, dtype=float)
        cot = pd.DataFrame({"mm_n": num(a["managed_money"]["l"]) - num(a["managed_money"]["s"]), "pm_n": num(a["prod_merc"]["l"]) - num(a["prod_merc"]["s"]),
                            "pm_l": num(a["prod_merc"]["l"]), "oi": num(a["oi"])})
        cot = cot[~cot.index.duplicated(keep="last")]
        fri = fri.join(cot.reindex(fri.index, method="ffill", tolerance=pd.Timedelta(days=3)))
    fri["carry"] = np.nan
    fri["name"] = NAMES[tk]
    return fri


def stocks_use():
    """U.S. ending stocks / total use per marketing year (final WASDE estimate) for the grains."""
    try:
        import wasde_data as W
        d, _ = W.load()
    except Exception as e:
        log("WASDE not available for the fundamental rules:", e)
        return {}
    out = {}
    for tk, (com, m0) in WASDE_KEY.items():
        x = d[(d.com == com) & (d.table == "us") & (d.region == "United States") & d.attr.isin(["end_stocks", "use"])]
        fv = x.sort_values("wasde").groupby(["my", "attr"]).value.last().unstack()
        if {"end_stocks", "use"} <= set(fv.columns):
            fv = fv.dropna()
            out[tk] = ({int(my[:4]): float(r.end_stocks / r.use) for my, r in fv.iterrows() if r.use}, m0)
    return out


# ---------------------------------------------------------------- features
def pct_rank(s, n=156):
    return s.rolling(n, min_periods=52).apply(lambda a: (a[:-1] < a[-1]).mean() * 100 if len(a) > 1 else np.nan, raw=True)


def features(f, sym, SU):
    f = f.copy()
    c = f.px
    f["above200"] = c > f.ma200
    f["gold"] = f.ma50 > f.ma200
    f["stack_up"] = (c > f.ma50) & (f.ma50 > f.ma200)
    f["stack_dn"] = (c < f.ma50) & (f.ma50 < f.ma200)
    f["x20_up"] = (c > f.ma20) & (c.shift(1) <= f.ma20.shift(1))
    f["x20_dn"] = (c < f.ma20) & (c.shift(1) >= f.ma20.shift(1))
    f["x200_up"] = (c > f.ma200) & (c.shift(1) <= f.ma200.shift(1))
    f["x200_dn"] = (c < f.ma200) & (c.shift(1) >= f.ma200.shift(1))
    f["above275"] = c > f.ma275
    f["wbo_up"] = c > f.wk_hi55
    f["wbo_dn"] = c < f.wk_lo55
    f["mom12"] = c / c.shift(52) - 1
    f["mom12_1"] = c.shift(4) / c.shift(52) - 1
    f["mom3"] = c / c.shift(13) - 1
    f["mom6"] = c / c.shift(26) - 1
    if "mm_n" in f:
        f["mm_pct"] = pct_rank(f.mm_n)
        f["mm_d1"] = f.mm_n.diff()
        f["mm_d4"] = f.mm_n.diff(4)
        f["pm_pct"] = pct_rank(f.pm_n)
        f["pml_pct"] = pct_rank(f.pm_l)
        f["mm_oi"] = f.mm_n / f.oi
    # seasonal-adjusted carry (vs the same calendar month in earlier years only)
    if f.carry.notna().sum() > 100:
        adj = []
        for d, v in f.carry.items():
            past = f.carry[(f.index.month == d.month) & (f.index < d - pd.Timedelta(days=200))]
            adj.append(v - past.median() if len(past) >= 30 and not pd.isna(v) else (v if sym not in STORABLE else np.nan))
        f["carry_adj"] = adj
    else:
        f["carry_adj"] = np.nan
    # seasonality: mean return of the same calendar month in prior years
    mret = f.ret.groupby([f.index.year, f.index.month]).sum()
    seas = []
    for d in f.index:
        prev = [mret.get((y, d.month)) for y in range(d.year - 10, d.year) if (y, d.month) in mret.index]
        seas.append(np.mean(prev) if len(prev) >= 5 else np.nan)
    f["seas"] = seas
    # fundamentals: US stocks/use for the marketing year in progress vs the previous one (PSD; final estimates, see note)
    if sym in SU:
        su, m0 = SU[sym]
        my = [d.year if d.month >= m0 else d.year - 1 for d in f.index]
        f["su"] = [su.get(y) for y in my]
        f["su_prev"] = [su.get(y - 1) for y in my]
        f["su_fall"] = (f.su < f.su_prev * 0.97)
        f["su_rise"] = (f.su > f.su_prev * 1.03)
    vol = f.ret.ewm(com=12).std().shift(1) * math.sqrt(52)
    f["lev"] = (TARGET / vol).clip(upper=3)
    return f


def hold(events, weeks):
    """Event -> position held for `weeks` weeks (re-triggers extend)."""
    out = np.zeros(len(events)); left = 0
    for i, e in enumerate(events.fillna(False).values):
        if e:
            left = weeks
        out[i] = 1.0 if left > 0 else 0.0
        left -= 1
    return pd.Series(out, index=events.index)


def turtle(f, n_in=55, n_out=20):
    pos, p = [], 0
    up, dn = f.get(f"bo_up{n_in}"), f.get(f"bo_dn{n_in}")
    xo_dn, xo_up = f.get(f"bo_dn{n_out}"), f.get(f"bo_up{n_out}")
    for i in range(len(f)):
        if p == 1 and bool(xo_dn.iloc[i]):
            p = 0
        if p == -1 and bool(xo_up.iloc[i]):
            p = 0
        if bool(up.iloc[i]):
            p = 1
        elif bool(dn.iloc[i]):
            p = -1
        pos.append(p)
    return pd.Series(pos, index=f.index, dtype=float)


B = lambda s: s.fillna(False).astype(bool)


def strategies(f, sym):
    S = []
    def add(key, name, family, pos, event=None):
        S.append((key, name, family, pos.fillna(0).astype(float), event))
    one = pd.Series(1.0, index=f.index)
    add("long_only", "Long only (benchmark)", "Benchmark", one)
    add("above200", "Price above / below 200-day MA", "Trend", np.where(B(f.above200), 1, -1) * one)
    add("gold", "50-day MA above / below 200-day MA", "Trend", np.where(B(f.gold), 1, -1) * one)
    add("stack", "Price > 50 > 200-day MA (long) / mirror (short)", "Trend", B(f.stack_up).astype(float) - B(f.stack_dn).astype(float))
    ev_l = B(f.stack_up) & B(f.x20_up); ev_s = B(f.stack_dn) & B(f.x20_dn)
    add("stack_x20", "Price > 50 > 200 and fresh cross above 20-day (hold 4 wk) / mirror", "Trend", hold(ev_l, 4) - hold(ev_s, 4), ev_l)
    add("x200", "Cross above / below 200-day MA (hold 8 wk)", "Trend", hold(B(f.x200_up), 8) - hold(B(f.x200_dn), 8), B(f.x200_up))
    add("turtle55", "55-day breakout, exit on 20-day opposite (turtle)", "Trend", turtle(f, 55, 20))
    add("turtle20", "20-day breakout, exit on 20-day opposite", "Trend", turtle(f, 20, 20))
    add("turtle100", "100-day breakout, exit on 20-day opposite", "Trend", turtle(f, 100, 20))
    add("wbo55", "55-week high / low breakout (hold 13 wk)", "Trend", hold(B(f.wbo_up), 13) - hold(B(f.wbo_dn), 13), B(f.wbo_up))
    add("above275", "Price above / below 55-week MA", "Trend", np.where(B(f.above275), 1, -1) * one)
    for k, col in (("tsmom12", "mom12"), ("tsmom12_1", "mom12_1"), ("tsmom6", "mom6"), ("tsmom3", "mom3")):
        add(k, {"tsmom12": "12-month momentum (TSMOM)", "tsmom12_1": "12-month momentum skipping last month", "tsmom6": "6-month momentum", "tsmom3": "3-month momentum"}[k],
            "Trend", np.sign(f[col]))
    if "mm_pct" in f and f.mm_pct.notna().sum() > 200:
        lo, hi = f.mm_pct < 10, f.mm_pct > 90
        add("cot_contra", "Specs at 3-yr extremes, fade them (<10th pct long, >90th short; hold 4 wk)", "COT", hold(B(lo), 4) - hold(B(hi), 4), B(lo))
        add("cot_flow1", "Follow spec flow (net buying last week)", "COT", np.sign(f.mm_d1))
        add("cot_flow4", "Follow spec flow (net buying last 4 weeks)", "COT", np.sign(f.mm_d4))
        ev = B(f.mm_pct < 25) & B(f.x200_up)
        add("cover", "Specs short (<25th pct) + price crosses above 200-day: short covering (long 8 wk)", "COT x Trend", hold(ev, 8), ev)
        ev2 = B(f.mm_pct > 75) & B(f.x200_dn)
        add("liquid", "Specs long (>75th pct) + price crosses below 200-day: liquidation (short 8 wk)", "COT x Trend", -hold(ev2, 8), ev2)
        add("room", "Trend up with room to buy (specs <70th pct) / trend down with room to sell (>30th)", "COT x Trend",
            (B(f.stack_up) & B(f.mm_pct < 70)).astype(float) - (B(f.stack_dn) & B(f.mm_pct > 30)).astype(float))
        add("crowded", "Trend up but specs crowded (>90th pct), and mirror: trade the trend anyway", "COT x Trend",
            (B(f.stack_up) & B(f.mm_pct > 90)).astype(float) - (B(f.stack_dn) & B(f.mm_pct < 10)).astype(float))
        add("comm", "Commercials (producers/merchants) least short vs 3 yr (>80th pct) long, most short (<20th) short", "COT",
            hold(B(f.pm_pct > 80), 4) - hold(B(f.pm_pct < 20), 4), B(f.pm_pct > 80))
        add("pml_low", "Producer/merchant LONG positions low (<20th pct): long 13 wk", "COT", hold(B(f.pml_pct < 20), 13), B(f.pml_pct < 20))
        add("pml_high", "Producer/merchant LONG positions high (>80th pct): long 13 wk", "COT", hold(B(f.pml_pct > 80), 13), B(f.pml_pct > 80))
    if f.carry_adj.notna().sum() > 150:
        add("carry", "Carry sign (backwardation long / contango short, seasonal-adjusted)", "Carry", np.sign(f.carry_adj))
        add("carry_trend", "Backwardated and trend up (long) / contango and trend down (short)", "Carry x Trend",
            (B(f.carry_adj > 0) & B(f.above200)).astype(float) - (B(f.carry_adj < 0) & ~B(f.above200)).astype(float))
        if "mm_pct" in f:
            ev = B(f.mm_pct < 25) & B(f.carry_adj > 0)
            add("carry_cover", "Specs short (<25th pct) while the curve is backwardated (long 8 wk)", "Carry x COT", hold(ev, 8), ev)
    if f.seas.notna().sum() > 150:
        add("seasonal", "Seasonal: same calendar month's average return in prior 10 years", "Seasonal", np.sign(f.seas))
    if "su_fall" in f and f.su.notna().sum() > 150:
        add("fund", "US stocks/use falling vs last year (long) / rising (short)", "Fundamental", B(f.su_fall).astype(float) - B(f.su_rise).astype(float))
        add("fund_trend", "Stocks/use falling and price above 200-day (long) / rising and below (short)", "Fundamental x Trend",
            (B(f.su_fall) & B(f.above200)).astype(float) - (B(f.su_rise) & ~B(f.above200)).astype(float))
        if "mm_pct" in f:
            add("fund_cot", "Stocks/use falling and specs not long yet (<50th pct): long", "Fundamental x COT", (B(f.su_fall) & B(f.mm_pct < 50)).astype(float))
    # vote of three independent families
    votes = [np.sign(f.mom12).fillna(0)]
    if "mm_d4" in f:
        votes.append(np.sign(f.mm_d4).fillna(0))
    if f.carry_adj.notna().sum() > 150:
        votes.append(np.sign(f.carry_adj).fillna(0))
    v = sum(votes)
    add("vote", "Vote: momentum + spec flow + carry (at least 2 agree)", "Combined", np.where(v >= 2, 1, np.where(v <= -2, -1, 0)) * one)
    return S


# ---------------------------------------------------------------- evaluation
def stats(r, pos, mn=52):
    r = r.dropna()
    if len(r) < mn or r.std() == 0:
        return None
    eq = r.cumsum()
    dd = float((eq - eq.cummax()).min())
    yrs = len(r) / 52
    sr = float(r.mean() / r.std() * math.sqrt(52))
    act = r[pos.reindex(r.index).abs() > 0]
    return {"ann": round(float(r.mean() * 52 * 100), 2), "vol": round(float(r.std() * math.sqrt(52) * 100), 1), "sharpe": round(sr, 2),
            "t": round(sr * math.sqrt(yrs), 2), "maxdd": round(dd * 100, 1), "hit": round(float((act > 0).mean() * 100), 1) if len(act) else None,
            "years": round(yrs, 1)}


def evaluate(f, sym):
    res = []
    for key, name, fam, pos, event in strategies(f, sym):
        w = (pos * f.lev).clip(-3, 3)
        cost = COST * w.diff().abs().fillna(0)
        r = (w * f.ret - cost).where(f.ret.notna() & f.lev.notna())
        r = r[r.index >= pd.Timestamp("2007-01-01")].dropna()
        full = stats(r, pos)
        if not full:
            continue
        r4 = (w * f.ret - 4 * cost).where(f.ret.notna() & f.lev.notna())
        r4 = r4[r4.index >= pd.Timestamp("2007-01-01")].dropna()
        s4 = stats(r4, pos)
        ins, oos = stats(r[r.index < SPLIT], pos), stats(r[r.index >= SPLIT], pos)
        trades = int((pos.diff().abs() > 0).sum())
        exp = round(float((pos.reindex(r.index).abs() > 0).mean() * 100), 1)
        row = {"market": sym, "name_m": f.name.iloc[0], "group": GROUP.get(sym), "key": key, "strategy": name, "family": fam, **full,
               "is_sharpe": ins["sharpe"] if ins else None, "oos_sharpe": oos["sharpe"] if oos else None, "oos_ann": oos["ann"] if oos else None,
               "trades": trades, "exposure": exp, "sharpe_4x_cost": s4["sharpe"] if s4 else None}
        for wk, (a, b) in WINDOWS.items():
            sw = stats(r[(r.index >= a) & (r.index <= b)], pos, 26)
            row[wk + "_sharpe"], row[wk + "_ann"] = (sw["sharpe"], sw["ann"]) if sw else (None, None)
            row[wk + "_dd"] = sw["maxdd"] if sw else None
        hw = avg_hold_weeks(pos.reindex(r.index))
        row["hold_wk"], row["horizon"] = hw, horizon(hw)
        if event is not None:
            ev = event.reindex(f.index).fillna(False)
            ev = ev & ~ev.shift(1, fill_value=False)
            fw4 = (f.exec.shift(-4) / f.exec - 1)[ev]
            fw13 = (f.exec.shift(-13) / f.exec - 1)[ev]
            sign = -1 if key in ("liquid",) else 1
            if key in ("cot_contra", "comm", "stack_x20", "x200", "wbo55"):
                sign = 1
            row.update({"events": int(ev.sum()), "fwd4": round(float(sign * fw4.mean() * 100), 2) if len(fw4.dropna()) else None,
                        "fwd13": round(float(sign * fw13.mean() * 100), 2) if len(fw13.dropna()) else None,
                        "fwd4_hit": round(float((sign * fw4.dropna() > 0).mean() * 100)) if len(fw4.dropna()) else None,
                        "base4": round(float((f.exec.shift(-4) / f.exec - 1).mean() * 100), 2)})
            if "mm_n" in f and f.oi.notna().sum() > 100:   # how specs respond after the event (change in net as % of open interest)
                d4 = ((f.mm_n.shift(-4) - f.mm_n) / f.oi * 100)
                d8 = ((f.mm_n.shift(-8) - f.mm_n) / f.oi * 100)
                row.update({"spec_d4": round(float(d4[ev].mean()), 2) if d4[ev].notna().any() else None,
                            "spec_d8": round(float(d8[ev].mean()), 2) if d8[ev].notna().any() else None,
                            "spec_d4_base": round(float(d4.mean()), 2), "spec_buy_share": round(float((d4[ev].dropna() > 0).mean() * 100)) if d4[ev].notna().any() else None})
        row["equity"] = [[str(d.date())[:7], round(float(v) * 100, 1)] for d, v in r.cumsum().resample("ME").last().items()]
        res.append(row)
    return res


def lab(px, cot_dir):
    SU = stocks_use()
    rows, coverage = [], {}
    for tk in NAMES:
        f = market(tk, px, cot_dir)
        if f is None or len(f) < 300:
            continue
        f = features(f, tk, SU)
        rr = evaluate(f, tk); rows += rr
        coverage[tk] = {"name": NAMES[tk], "from": str(f.index[0].date()), "to": str(f.index[-1].date()), "source": "daily front-month continuous (roll gaps removed); COT from 2006"}
        log(tk, len(rr), "strategies")
    df = pd.DataFrame([{k: v for k, v in r.items() if k != "equity"} for r in rows])
    n_tests = int(len(df[df.key != "long_only"]))
    yrs = float(df.years.median())
    noise = round(math.sqrt(2 * math.log(max(n_tests, 2))) / math.sqrt(yrs), 2)
    # robustness: same sign in and out of sample, positive full Sharpe
    df["robust"] = (df.is_sharpe > 0) & (df.oos_sharpe > 0) & (df.sharpe > 0) & (df.trades >= 10)
    df["enough"] = (df.trades >= 10) & (df.exposure >= 5)
    df["beats_noise"] = df.sharpe >= noise
    # family / strategy summaries across markets
    strat = df[df.key != "long_only"].groupby(["key", "strategy", "family"]).agg(
        markets=("market", "count"), median_sharpe=("sharpe", "median"), mean_sharpe=("sharpe", "mean"), pos_share=("sharpe", lambda s: round(100 * (s > 0).mean())),
        robust_share=("robust", lambda s: round(100 * s.mean())), median_oos=("oos_sharpe", "median"), median_hit=("hit", "median"), median_dd=("maxdd", "median")).reset_index()
    strat = strat.sort_values("median_sharpe", ascending=False)
    fam = df[df.key != "long_only"].groupby("family").agg(tests=("market", "count"), median_sharpe=("sharpe", "median"), pos_share=("sharpe", lambda s: round(100 * (s > 0).mean())),
                                                          robust_share=("robust", lambda s: round(100 * s.mean())), median_oos=("oos_sharpe", "median")).reset_index().sort_values("median_sharpe", ascending=False)
    elig = df[(df.key != "long_only") & (df.exposure >= 10) & df.enough]
    top = elig.sort_values("sharpe", ascending=False).head(10)
    bottom = elig.sort_values("sharpe").head(10)
    top_oos = elig[elig.robust].sort_values("oos_sharpe", ascending=False).head(10)
    # per-market learnings
    per = {}
    order = {"Grains": 0, "Softs": 1, "Livestock": 2, "Dairy": 3, "Energy": 4, "Metals": 5}
    for sym, g in sorted(df.groupby("market"), key=lambda x: (order.get(GROUP.get(x[0]), 9), x[0])):
        g2 = g[(g.key != "long_only") & (g.exposure >= 10) & g.enough].sort_values("sharpe", ascending=False)
        lo = g[g.key == "long_only"]
        best = g2[g2.robust].head(3)
        worst = g2.tail(3)
        txt = []
        if len(best):
            txt.append("Best rules that held up out of sample: " + "; ".join(f"{r.strategy} (Sharpe {r.sharpe}, OOS {r.oos_sharpe}, hit {r.hit}%, max DD {r.maxdd}%)" for r in best.itertuples()) + ".")
        else:
            txt.append("No rule was positive both before and after 2019.")
        txt.append("Worst: " + "; ".join(f"{r.strategy} (Sharpe {r.sharpe})" for r in worst.itertuples()) + ".")
        if len(lo):
            txt.append(f"Long-only benchmark Sharpe {lo.sharpe.iloc[0]} (at 10% vol).")
        nb = g2[g2.beats_noise & g2.robust]
        txt.append(f"{len(nb)} rule(s) beat the noise bar (Sharpe ≥ {noise}) and held up out of sample." if len(nb) else f"None beat the noise bar (Sharpe ≥ {noise}), so treat the ranking as weak evidence.")
        fams = g2.groupby("family").sharpe.max().sort_values(ascending=False)
        txt.append("Best family here: " + ", ".join(f"{k} {v:.2f}" for k, v in fams.head(3).items()) + ".")
        per[sym] = {"name": g.name_m.iloc[0], "group": g.group.iloc[0], "read": " ".join(txt)}
    # cross-market learnings
    L = []
    s_ok = strat[(strat.markets >= 10)]
    for r in s_ok.head(6).itertuples():
        L.append(f"{r.strategy}: median Sharpe {r.median_sharpe:.2f} across {r.markets} markets, positive in {r.pos_share}%, held up out of sample in {r.robust_share}% (median OOS {r.median_oos:.2f}).")
    worst_s = s_ok.sort_values("median_sharpe").head(4)
    L.append("Weakest across markets: " + "; ".join(f"{r.strategy} (median Sharpe {r.median_sharpe:.2f})" for r in worst_s.itertuples()) + ".")
    for fam_name in ("COT", "COT x Trend", "Carry", "Fundamental", "Fundamental x Trend", "Seasonal", "Trend"):
        x = fam[fam.family == fam_name]
        if len(x):
            x = x.iloc[0]
            L.append(f"{fam_name} rules: median Sharpe {x.median_sharpe:.2f} over {x.tests} tests, {x.pos_share}% positive, {x.robust_share}% robust out of sample.")
    dairy_top = 0
    if dairy_top >= 5:
        L.append(f"{dairy_top} of the top 10 are dairy trend rules (Class IV, butter, nonfat). Dairy futures settle to USDA monthly averages of weekly prices, so their prices move in slow, persistent steps that breakout and moving-average rules capture; the edge survives 4x costs and 2019+ data, but these contracts are thin, so real slippage is larger than modelled.")
    L.append(f"Multiple testing: {n_tests} rule-market tests; the best Sharpe expected from pure luck is about {noise}. Single strategy-market winners below that bar are likely noise; rules that work across many markets are more trustworthy.")
    ev_keys = ["stack_x20", "x200", "cover", "liquid", "wbo55", "cot_contra", "carry_cover", "pml_low"]
    spec = df[df.key.isin(ev_keys)].groupby(["key", "strategy"]).agg(markets=("market", "count"), events=("events", "sum"), fwd4=("fwd4", "median"), fwd13=("fwd13", "median"),
                                                                       fwd4_hit=("fwd4_hit", "median"), spec_d4=("spec_d4", "median"), spec_d8=("spec_d8", "median"),
                                                                       spec_base=("spec_d4_base", "median"), spec_buy_share=("spec_buy_share", "median")).reset_index() if "spec_d4" in df else pd.DataFrame()
    for r in spec.itertuples():
        if r.key in ("stack_x20", "cover", "x200", "wbo55") and not pd.isna(r.spec_d4):
            L.append(f"After '{r.strategy}' ({int(r.events)} events, {r.markets} markets): specs added a median {r.spec_d4:+.1f}% of open interest over 4 weeks "
                     f"({r.spec_d8:+.1f}% over 8; normal 4-week drift {r.spec_base:+.1f}%), buying in {r.spec_buy_share:.0f}% of cases; price median {r.fwd4:+.1f}% after 4 weeks, {r.fwd13:+.1f}% after 13.")
    out = {"generated": date.today().isoformat(), "spec_response": spec.round(2).to_dict("records"), "split": str(SPLIT.date()), "target_vol": TARGET, "cost_bp": COST * 1e4, "n_tests": n_tests, "noise_sharpe": noise,
           "coverage": coverage, "learnings": L, "per_market": per,
           "families": fam.round(2).to_dict("records"), "strategies": strat.round(2).to_dict("records"),
           "top": top.round(2).to_dict("records"), "bottom": bottom.round(2).to_dict("records"), "top_oos": top_oos.round(2).to_dict("records"),
           "results": [{**{k: (None if isinstance(v, float) and math.isnan(v) else v) for k, v in r.items() if k != "equity"},
                        "robust": bool(rb), "enough": bool(en)} for r, rb, en in zip(rows, df.robust, df.enough)]}
    equity = {}
    for r in rows:
        equity.setdefault(r["market"], {})[r["key"]] = r["equity"]
    return out, equity


def main():
    px_path = WORK / "prices" / "daily.csv"
    cot_dir = WORK / "positioning"
    if not px_path.exists() or not cot_dir.exists():
        raise SystemExit("needs this build's prices and positioning output (.work/prices, .work/positioning)")
    px = pd.read_csv(px_path, parse_dates=["date"])
    latest = str(px[px.ticker.isin(NAMES)].date.max().date())
    if os.environ.get("PREV_LATEST") == latest and not os.environ.get("FORCE"):
        print(json.dumps({"reuse": True, "note": ""}))
        log(f"no new price day since {latest}: reusing the previous result")
        return
    out, equity = lab(px, cot_dir)
    clean = lambda o: json.loads(json.dumps(o, default=lambda x: None if x is None or (isinstance(x, float) and math.isnan(x)) else (bool(x) if isinstance(x, np.bool_) else float(x))).replace("NaN", "null"))
    print(json.dumps({"data": clean(out), "files": clean(equity), "latest": latest, "n": len(out["coverage"]),
                      "src": "Futures prices (Yahoo Finance, delayed), CFTC Commitments of Traders, USDA WASDE",
                      "note": "carry rules left out: no carry history in the free price feed", "partial": False},
                     separators=(",", ":")))


if __name__ == "__main__":
    main()
