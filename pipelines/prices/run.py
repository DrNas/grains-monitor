"""Futures prices for the desks, from Yahoo Finance's public chart API (delayed; settlement-quality closes after the
session). Adapted, with permission, from an existing open-source pipeline; requests are sent with this site's own
user agent, spaced out and retried with backoff (Yahoo rate-limits bursts).

Writes, for the other pipelines in the same build (in .work/prices/, the source pipeline's file layout):
  daily.csv           daily OHLCV of the front-month continuous series for every positioning market, plus S&P 500
                      and VIX (history since 2006 comes from the previous run's cache; each run tops up 3 months)
  front_contract.csv  ~1 year of the current tradable contract per market (levels you can put orders at)
  report.json         fetch status, carry (front vs same month next year, annualised) and the equity risk regime
and returns for the pages: forward curves (WTI, natural gas), the fed funds and SOFR futures strips (implied
policy path), and the status table.

Run by scripts/build-data.mjs; prints {data, cache, latest, n, src, note, partial} as JSON on stdout.
"""
import io, json, math, os, sys, time
from datetime import date, datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import requests

ROOT = Path(__file__).resolve().parents[2]
WORK = Path(os.environ.get("PRICES_DIR") or ROOT / ".work" / "prices")
UA = {"User-Agent": "grains-monitor/1.0 (daily build; +https://github.com/DrNas/grains-monitor)"}
CHART = "https://query1.finance.yahoo.com/v8/finance/chart/{}"
GAP = float(os.environ.get("YAHOO_GAP", "1.0"))   # seconds between requests

# our ticker -> Yahoo continuous symbol, contract root, exchange suffix, listed months (from the source pipeline)
YAHOO = {
    "CO": ("BZ=F", "BZ", "NYM", "FGHJKMNQUVXZ"), "NG": ("NG=F", "NG", "NYM", "FGHJKMNQUVXZ"),
    "CL": ("CL=F", "CL", "NYM", "FGHJKMNQUVXZ"), "HO": ("HO=F", "HO", "NYM", "FGHJKMNQUVXZ"),
    "XB": ("RB=F", "RB", "NYM", "FGHJKMNQUVXZ"),
    "C": ("ZC=F", "ZC", "CBT", "HKNUZ"), "S": ("ZS=F", "ZS", "CBT", "FHKNQUX"), "SM": ("ZM=F", "ZM", "CBT", "FHKNQUVZ"),
    "BO": ("ZL=F", "ZL", "CBT", "FHKNQUVZ"), "W": ("ZW=F", "ZW", "CBT", "HKNUZ"), "KW": ("KE=F", "KE", "CBT", "HKNUZ"),
    "HG": ("HG=F", "HG", "CMX", "HKNUZ"), "ALI": ("ALI=F", "ALI", "CMX", "FGHJKMNQUVXZ"),
    "GC": ("GC=F", "GC", "CMX", "GJMQVZ"), "SI": ("SI=F", "SI", "CMX", "HKNUZ"),
    "SB": ("SB=F", "SB", "NYB", "HKNV"), "KC": ("KC=F", "KC", "NYB", "HKNUZ"), "CC": ("CC=F", "CC", "NYB", "HKNUZ"),
    "CT": ("CT=F", "CT", "NYB", "HKNVZ"), "LC": ("LE=F", "LE", "CME", "GJMQVZ"), "LH": ("HE=F", "HE", "CME", "GJKMNQVZ"),
}
PROXY_NOTE = {"ALI": "price series is COMEX aluminum; COT is the Midwest Premium contract"}
INDEX = {"SPX": "^GSPC", "VIX": "^VIX"}
MONTHS = "FGHJKMNQUVXZ"
ENERGY = {"CO", "NG", "CL", "HO", "XB"}   # energy contract month M expires in month M-1
NOTES = []


def log(*a):
    print(*a, file=sys.stderr, flush=True)


_last = [0.0]


def yahoo(sym, rng="3mo"):
    """Daily OHLCV DataFrame (index = date) for one Yahoo symbol; empty if Yahoo has nothing.
    rng: a Yahoo range ('5d', '3mo', '1y') or 'full' for daily bars since 2006 (Yahoo's own 'max' range silently
    switches to monthly bars, so the full history is asked for with explicit start and end times)."""
    params = {"interval": "1d", "includePrePost": "false"}
    if rng == "full":
        params.update(period1=int(datetime(2006, 1, 1, tzinfo=timezone.utc).timestamp()), period2=int(time.time()))
    else:
        params["range"] = rng
    for attempt in range(6):
        wait = _last[0] + GAP - time.time()
        if wait > 0:
            time.sleep(wait)
        _last[0] = time.time()
        try:
            r = requests.get(CHART.format(sym), params=params, headers=UA, timeout=40)
            if r.status_code == 429 or r.status_code >= 500:
                time.sleep(min(90, 10 * 2 ** attempt))   # 10, 20, 40, 80, 90 s: Yahoo's limit resets within a minute or two
                continue
            if r.status_code != 200:
                return pd.DataFrame()
            res = (r.json().get("chart") or {}).get("result") or []
            if not res or not res[0].get("timestamp"):
                return pd.DataFrame()
            q = res[0]["indicators"]["quote"][0]
            tz = res[0].get("meta", {}).get("exchangeTimezoneName") or "America/New_York"
            idx = pd.to_datetime(res[0]["timestamp"], unit="s", utc=True).tz_convert(tz).tz_localize(None).normalize()
            f = pd.DataFrame({k: q.get(k) for k in ("open", "high", "low", "close", "volume")}, index=idx).dropna(subset=["close"])
            return f[~f.index.duplicated(keep="last")]
        except Exception as e:
            log("  retry", sym, str(e)[:80])
            time.sleep(5 * 2 ** attempt)
    log("  gave up", sym)
    return pd.DataFrame()


def contract_pair(tk, today):
    """Front tradable contract and the same month one year later (avoids seasonal bias). From the source."""
    _, root, ex, listed = YAHOO[tk]
    skip = 2 if tk in ENERGY else 1
    y, m = today.year, today.month
    for k in range(skip, skip + 14):
        mm = (m - 1 + k) % 12 + 1
        yy = y + (m - 1 + k) // 12
        code = MONTHS[mm - 1]
        if code in listed:
            return f"{root}{code}{yy % 100:02d}.{ex}", f"{root}{code}{(yy + 1) % 100:02d}.{ex}", f"{code}{yy % 100:02d}", f"{code}{(yy + 1) % 100:02d}"
    return None


def months_ahead(today, n, start=0):
    for k in range(start, start + n):
        mm = (today.month - 1 + k) % 12 + 1
        yy = today.year + (today.month - 1 + k) // 12
        yield yy, mm


def curve(root, ex, today, n, start):
    """Settle of each listed month for a strip (WTI, gas): [{m: 'Jan 27', code, v, d}]."""
    out = []
    for yy, mm in months_ahead(today, n, start):
        code = f"{MONTHS[mm - 1]}{yy % 100:02d}"
        f = yahoo(f"{root}{code}.{ex}", "5d")
        if len(f):
            out.append({"m": date(yy, mm, 1).strftime("%b %y"), "code": code, "v": round(float(f.close.iloc[-1]), 4), "d": str(f.index[-1].date())})
    return out


def policy_path(today):
    """Fed funds futures (ZQ: monthly average rate = 100 - price) and 3-month SOFR futures (SR3: average over the
    quarter that starts in the contract month), for the next 12 months / 8 quarters."""
    zq = []
    for yy, mm in months_ahead(today, 13, 0):
        code = f"{MONTHS[mm - 1]}{yy % 100:02d}"
        f = yahoo(f"ZQ{code}.CBT", "5d")
        if len(f):
            zq.append({"m": date(yy, mm, 1).strftime("%b %y"), "code": code, "rate": round(100 - float(f.close.iloc[-1]), 3), "d": str(f.index[-1].date())})
    sr = []
    q = [m for m in months_ahead(today, 27, 0) if m[1] in (3, 6, 9, 12)][:8]
    for yy, mm in q:
        code = f"{MONTHS[mm - 1]}{yy % 100:02d}"
        f = yahoo(f"SR3{code}.CME", "5d")
        if len(f):
            sr.append({"m": date(yy, mm, 1).strftime("%b %y"), "code": code, "rate": round(100 - float(f.close.iloc[-1]), 3), "d": str(f.index[-1].date())})
    return {"zq": zq, "sr3": sr}


def frame_to_rows(f):
    return [[str(i.date()), *[None if pd.isna(v) else round(float(v), 5) for v in r]] for i, r in zip(f.index, f[["open", "high", "low", "close", "volume"]].values)]


def rows_to_frame(rows):
    if not rows:
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
    d = pd.DataFrame(rows, columns=["date", "open", "high", "low", "close", "volume"])
    d.index = pd.to_datetime(d.pop("date"))
    return d


def main():
    cache = {}
    if os.environ.get("PREV_CACHE") and Path(os.environ["PREV_CACHE"]).exists():
        cache = json.loads(Path(os.environ["PREV_CACHE"]).read_text())
    today = date.today()
    WORK.mkdir(parents=True, exist_ok=True)
    report = {"fetched_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
              "source": "Yahoo Finance chart API (front-month continuous)", "markets": {}, "carry": {}, "regime": {}}
    # ---- continuous daily history (cache + 3-month top-up; full history on the first run)
    daily, new_cache = [], {"daily": {}}
    for tk, sym in [(k, v[0]) for k, v in YAHOO.items()] + list(INDEX.items()):
        old = rows_to_frame(cache.get("daily", {}).get(tk))
        f = yahoo(sym, "3mo" if len(old) > 200 else "full")
        if len(f):
            f = f[f.index >= "2006-01-01"]
            allf = pd.concat([old[old.index < f.index.min()], f]) if len(old) else f
        else:
            allf = old
            if tk in YAHOO:
                NOTES.append(f"{tk}: no new prices")
        if tk in YAHOO:
            report["markets"][tk] = {"yahoo": sym, "rows_fetched": int(len(f)), "last": str(allf.index.max().date()) if len(allf) else None,
                                     "status": "ok" if len(f) else ("kept previous" if len(allf) else "no data")}
            if tk in PROXY_NOTE:
                report["markets"][tk]["note"] = PROXY_NOTE[tk]
        if len(allf):
            new_cache["daily"][tk] = frame_to_rows(allf)
            daily.append(allf.assign(ticker=tk))
    if not daily:
        raise SystemExit("Yahoo returned no prices at all")
    allp = pd.concat(daily)
    allp.index.name = "date"
    allp = allp.reset_index()[["date", "ticker", "open", "high", "low", "close", "volume"]]
    allp["volume"] = allp["volume"].fillna(0).astype("int64")
    allp.to_csv(WORK / "daily.csv", index=False, date_format="%Y-%m-%d")
    # ---- risk regime: S&P 500 vs 200-day, VIX (from the source)
    try:
        spx = allp[allp.ticker == "SPX"].set_index("date")["close"]
        vix = allp[allp.ticker == "VIX"].set_index("date")["close"]
        s200 = spx.rolling(200).mean()
        report["regime"] = {"spx": round(float(spx.iloc[-1]), 2), "spx_200d": round(float(s200.iloc[-1]), 2), "spx_above_200d": bool(spx.iloc[-1] > s200.iloc[-1]),
                            "vix": round(float(vix.iloc[-1]), 2), "date": str(spx.index[-1].date())}
        report["regime"]["risk_off"] = (not report["regime"]["spx_above_200d"]) and report["regime"]["vix"] > 25
    except Exception as e:
        report["regime"] = {"error": str(e)[:100]}
    # ---- carry and the tradable front contract (from the source)
    fr = []
    for tk in YAHOO:
        p = contract_pair(tk, today)
        if not p:
            continue
        f1, f2 = yahoo(p[0], "1y"), yahoo(p[1], "5d")
        if len(f1):
            fr.append(f1.assign(ticker=tk, contract=YAHOO[tk][1] + p[2]))
        if len(f1) and len(f2):
            p1, p2 = float(f1["close"].iloc[-1]), float(f2["close"].iloc[-1])
            c = math.log(p1 / p2) if p1 > 0 and p2 > 0 else None
            report["carry"][tk] = {"front": p[2], "deferred": p[3], "p_front": round(p1, 4), "p_deferred": round(p2, 4),
                                   "carry_ann": round(c, 4) if c is not None else None, "date": str(f1.index[-1].date())}
        else:
            report["carry"][tk] = {"front": p[2], "deferred": p[3], "carry_ann": None, "status": "contract data unavailable on Yahoo"}
    if fr:
        fc = pd.concat(fr)
        fc.index.name = "date"
        fc = fc.reset_index()
        fc["volume"] = fc["volume"].fillna(0).astype("int64")
        fc[["date", "ticker", "contract", "open", "high", "low", "close", "volume"]].to_csv(WORK / "front_contract.csv", index=False, date_format="%Y-%m-%d")
    ok = sum(1 for m in report["markets"].values() if m["status"] == "ok")
    report["summary"] = {"markets_ok": ok, "markets_total": len(YAHOO), "carry_ok": sum(1 for c in report["carry"].values() if c.get("carry_ann") is not None)}
    (WORK / "report.json").write_text(json.dumps(report))
    # ---- curves and the policy path, for the energy and macro pages
    curves = {"CL": curve("CL", "NYM", today, 13, 1), "NG": curve("NG", "NYM", today, 13, 1)}
    pol = policy_path(today)
    (WORK / "curves.json").write_text(json.dumps({"curves": curves, "policy": pol}))
    for k, v in (("WTI curve", curves["CL"]), ("gas curve", curves["NG"]), ("fed funds futures", pol["zq"]), ("SOFR futures", pol["sr3"])):
        if not v:
            NOTES.append(f"{k}: no contracts returned")
    last = max(m["last"] for m in report["markets"].values() if m["last"])
    log(f"prices: {ok}/{len(YAHOO)} markets, carry {report['summary']['carry_ok']}, curves CL {len(curves['CL'])} NG {len(curves['NG'])}, ZQ {len(pol['zq'])}, SR3 {len(pol['sr3'])}")
    print(json.dumps({"data": {"report": report, "curves": curves, "policy": pol}, "cache": new_cache, "latest": last, "n": ok,
                      "src": "Yahoo Finance (CME, ICE and COMEX futures, delayed); S&P 500 and VIX",
                      "note": "; ".join(NOTES), "partial": ok < len(YAHOO) - 2},
                     separators=(",", ":"), default=str))


if __name__ == "__main__":
    main()
