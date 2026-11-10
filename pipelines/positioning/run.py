"""Positioning desk: CFTC Commitments of Traders for the Bloomberg Commodity Index markets the CFTC reports
(futures and options combined, by crop year where the CFTC splits it), plus the Commodity Index Trader report.

Run by scripts/build-data.mjs; prints {data, files, latest, n, src, note, partial} as JSON on stdout.
data = the latest-week snapshot (every market, crop year and trader category) and the market list;
files = one weekly history per market, published as data/positioning/<ticker>.json and loaded by the page
only when a market is opened. No key.

Local test without the API: POSITIONING_FIXTURE=<dir> reads <dir>/bcom_cot_master.csv and <dir>/cit_master.csv
(the column layout cftc.process_records / cftc.cit_rows_for produce).
"""
import json, math, os, sys, time
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import cftc  # noqa: E402
import desk  # noqa: E402

FIXTURE = os.environ.get("POSITIONING_FIXTURE")
log = cftc.log


def fetch_cot():
    rows, missing = [], []
    for name, meta in cftc.BCOM.items():
        raw = cftc.fetch_commodity(meta, since_date="2006-01-01")
        if not raw:
            missing.append(name)
            continue
        r = cftc.process_records(raw, name, meta, crop_type="all")
        if meta["crop"]:
            for ct in ("old", "other"):
                if cftc.FIELDS[ct]["mm_l"] in raw[-1]:
                    r += cftc.process_records(raw, name, meta, crop_type=ct)
        rows += r
        log(f"  COT {name}: {len(raw)} reports, latest {raw[-1].get('report_date_as_yyyy_mm_dd', '')[:10]}")
        time.sleep(cftc.REQUEST_DELAY)
    return pd.DataFrame(rows), missing


def fetch_cit():
    rows, missing = [], []
    for name, meta in cftc.CIT_MARKETS.items():
        r = cftc.cit_rows_for(name, meta, cftc.cit_get(meta["code"], "2006-01-01"))
        if not r:
            missing.append(name)
        rows += r
        time.sleep(cftc.DELAY)
    return pd.DataFrame(rows), missing


def finish_cit(df):
    """Weekly flows and the January index-rebalance window (as in the source)."""
    if df.empty:
        return df
    df = df.drop_duplicates(["date", "commodity"], keep="last").sort_values(["commodity", "date"]).reset_index(drop=True)
    g = df.groupby("commodity", sort=False)
    df["cit_net_chg_1w"] = g["cit_net"].diff()
    df["cit_net_chg_4w"] = g["cit_net"].diff(4)
    df["cit_net_pct_oi_chg_4w"] = g["cit_net_pct_oi"].diff(4).round(3)
    dt = pd.to_datetime(df["date"])
    df["rebalance_window"] = (dt.dt.month == 1) & (dt.dt.day <= 20)
    return df


def clean(o):
    if isinstance(o, dict):
        return {k: clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [clean(v) for v in o]
    if isinstance(o, (float, np.floating)):
        return float(o) if math.isfinite(o) else None
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, np.bool_):
        return bool(o)
    return o


def latest_report():
    """The newest report date the CFTC has published (one small request)."""
    import requests
    r = requests.get(cftc.ENDPOINT, params={"$select": "max(report_date_as_yyyy_mm_dd) as d"}, headers=cftc.UA, timeout=60)
    r.raise_for_status()
    return (r.json() or [{}])[0].get("d", "")[:10]


def main():
    notes = []
    prev = os.environ.get("PREV_LATEST", "")
    if not FIXTURE and prev and not os.environ.get("FORCE"):
        try:
            if latest_report() == prev:
                print(json.dumps({"reuse": True, "note": ""}))
                log(f"CFTC has nothing after {prev}: reusing the previous build")
                return
        except Exception as e:
            log("could not check the latest report date:", e)
    if FIXTURE:
        cot = pd.read_csv(Path(FIXTURE) / "bcom_cot_master.csv", low_memory=False)
        cot = cot[[c for c in cot.columns if not c.startswith("pctile_")]]
        cit = pd.read_csv(Path(FIXTURE) / "cit_master.csv", dtype={"date": str})
    else:
        cot, miss = fetch_cot()
        if miss:
            notes.append("COT not returned: " + ", ".join(miss))
        try:
            cit, miss = fetch_cit()
            if miss:
                notes.append("CIT not returned: " + ", ".join(miss))
        except Exception as e:
            cit = pd.DataFrame()
            notes.append(f"CIT report failed ({str(e)[:80]})")
    if cot.empty:
        raise SystemExit("no COT data from the CFTC")
    cot["date"] = pd.to_datetime(cot["date"]).dt.strftime("%Y-%m-%d")
    for col in cot.columns:
        if col not in ("date", "commodity", "ticker", "sector", "crop_type", "is_crop"):
            cot[col] = pd.to_numeric(cot[col], errors="coerce")
    cot = cot.drop_duplicates(["commodity", "crop_type", "date"], keep="last").sort_values(["commodity", "crop_type", "date"]).reset_index(drop=True)
    cit = finish_cit(cit)
    snapshot, manifest, series = desk.build(cot, cftc.BCOM, cit)
    stale = [c["name"] for c in manifest["commodities"] if c["stale"]]
    if stale:
        notes.append("no report in 3 weeks: " + ", ".join(stale))
    manifest["not_reported"] = cftc.NOT_REPORTED
    log(f"report {manifest['report_date']}, {len(manifest['commodities'])} markets, CIT {len(manifest.get('cit_tickers', []))}")
    print(json.dumps(clean({"data": {"snapshot": snapshot, "manifest": manifest}, "files": series,
                            "latest": manifest["report_date"], "n": len(manifest["commodities"]),
                            "src": "CFTC Commitments of Traders (disaggregated, futures and options combined) and Commodity Index Trader supplement",
                            "note": "; ".join(notes), "partial": bool([n for n in notes if not n.startswith("no report in 3 weeks")])}),
                     separators=(",", ":"), allow_nan=False, default=str))


if __name__ == "__main__":
    main()
