"""USDA WASDE supply-and-demand estimates for the grains desk: every monthly release since April 2010.

History up to the seed's last release is read from data/wasde/history.csv.gz (built from USDA's own WASDE
data files by build_seed.py). Any later release is fetched from usda.gov's monthly CSV
(oce-wasde-report-data-YYYY-MM.csv), so a new WASDE shows up on the first build after it is posted.
Used by pipelines/wasde/run.py and pipelines/export_sales/run.py.
"""
import io, sys, time
from pathlib import Path

import numpy as np
import pandas as pd
import requests

ROOT = Path(__file__).resolve().parents[2]
SEED = ROOT / "data" / "wasde" / "history.csv.gz"
MONTHLY = "https://www.usda.gov/sites/default/files/documents/oce-wasde-report-data-{:%Y-%m}.csv"
UA = {"User-Agent": "grains-monitor/1.0 (daily build; +https://github.com/DrNas/grains-monitor)"}

# the WASDE tables the desk uses: report title -> table ("us" = U.S. units, "world" = million metric tons)
TABLES = {
    "U.S. Feed Grain and Corn Supply and Use": "us",
    "U.S. Soybeans and Products Supply and Use (Domestic Measure)": "us",
    "U.S. Wheat Supply and Use": "us",
    "World Corn Supply and Use": "world",
    "World Soybean Supply and Use": "world",
    "World Soybean Meal Supply and Use": "world",
    "World Soybean Oil Supply and Use": "world",
    "World Wheat Supply and Use": "world",
}
# (table, WASDE commodity name) -> desk key
COMMODITY = {
    ("us", "Corn"): "corn", ("world", "Corn"): "corn",
    ("us", "Oilseed, Soybean"): "soybeans", ("world", "Oilseed, Soybean"): "soybeans",
    ("us", "Meal, Soybean"): "meal", ("world", "Soybean Meal"): "meal",
    ("us", "Oil, Soybean"): "oil", ("world", "Soybean Oil"): "oil",
    ("us", "Wheat"): "wheat", ("world", "Wheat"): "wheat",
}
CANON = {  # lower-cased WASDE attribute -> canonical
    "area planted": "area_planted", "area harvested": "area_harvested", "yield per harvested acre": "yield",
    "beginning stocks": "beg_stocks", "production": "production", "imports": "imports", "supply, total": "supply",
    "total supply": "supply", "feed and residual": "feed_residual", "food, seed & industrial": "fsi",
    "ethanol & by-products": "ethanol", "ethanol for fuel": "ethanol", "domestic, total": "domestic", "domestic total": "domestic",
    "domestic": "domestic", "domestic disappearance": "domestic", "crushings": "crush", "domestic crush": "crush",
    "exports": "exports", "use, total": "use", "total use": "use", "ending stocks": "end_stocks",
    "avg. farm price": "price", "food": "food", "seed": "seed", "residual": "residual",
    "biofuel": "biofuel", "biodiesel": "biofuel", "for methyl ester": "biofuel", "methyl ester": "biofuel",
    "food, feed & other industrial": "food_other", "domestic feed": "dom_feed", "trade": "trade",
}
KEEP = ["WasdeNumber", "ReleaseDate", "ReportTitle", "Commodity", "Region", "MarketYear", "Attribute", "Value", "Unit"]


def log(*a):
    print(*a, file=sys.stderr, flush=True)


def select(raw):
    """Rows of the desk's tables from a USDA WASDE data file (the reliability tables are left out)."""
    d = raw[raw.ReportTitle.isin(TABLES) & raw.MarketYear.notna()][KEEP].copy()
    # USDA's files mix "2026-10-09" and "01/12/2021"
    d["ReleaseDate"] = pd.to_datetime(d.ReleaseDate, format="mixed").dt.strftime("%Y-%m-%d")
    return d


def monthly(month):
    """One month's USDA WASDE data file, or None when it is not posted (yet). Raises when usda.gov refuses."""
    last = None
    for attempt in range(3):
        if attempt:
            time.sleep(4 * 2 ** (attempt - 1))
        try:
            r = requests.get(MONTHLY.format(month), headers=UA, timeout=90)
            if r.status_code == 404:
                return None
            if r.status_code == 200 and r.content[:40].lstrip(b"\xef\xbb\xbf").startswith(b'"WasdeNumber"'):
                return pd.read_csv(io.StringIO(r.content.decode("utf-8-sig")), dtype=str, low_memory=False)
            if r.status_code == 200:
                return None   # an HTML page in place of the file: not posted yet
            last = f"HTTP {r.status_code}"
            if r.status_code in (401, 403):
                break   # refused: retrying will not help
        except Exception as e:
            last = str(e)[:120]
        log("  WASDE", f"{month:%Y-%m}", last)
    raise RuntimeError(f"the {month:%B %Y} WASDE could not be fetched from usda.gov ({last})")


def raw_history():
    """Seed + every later monthly release. Returns (rows, notes)."""
    d = pd.read_csv(SEED, dtype=str, low_memory=False)
    notes = []
    last = pd.Timestamp(d.ReleaseDate.max())
    month = (last + pd.offsets.MonthBegin(1)).normalize()
    now = pd.Timestamp.now(tz="UTC").tz_localize(None)
    while month <= now:
        try:
            m = monthly(month)
        except RuntimeError as e:
            notes.append(f"{e}; showing releases through {last:%B %Y}")
            break
        if m is not None:
            d = pd.concat([d, select(m)], ignore_index=True)
            log("  WASDE", f"{month:%Y-%m}", "added", m.WasdeNumber.iloc[0] if len(m) else "")
        month += pd.offsets.MonthBegin(1)
    return d.drop_duplicates(["WasdeNumber", "ReportTitle", "Commodity", "Region", "MarketYear", "Attribute"]), notes


def tidy(d):
    """Long table: com, table, region, attr, my, wasde, release, report ("Nov 2026"), value, unit."""
    d = d.copy()
    d["table"] = d.ReportTitle.map(TABLES)
    d["com"] = [COMMODITY.get(k) for k in zip(d.table, d.Commodity)]
    d["attr"] = d.Attribute.str.strip().str.lower().map(CANON)
    d = d.dropna(subset=["com", "attr"])
    d["value"] = pd.to_numeric(d.Value.str.replace(",", ""), errors="coerce")
    d["wasde"] = d.WasdeNumber.astype(int)
    d["release"] = pd.to_datetime(d.ReleaseDate, format="mixed")
    d["report"] = d.release.dt.strftime("%b %Y")
    d = d.rename(columns={"Region": "region", "MarketYear": "my", "Unit": "unit"})
    d["my"] = d.my.str.strip()
    d = d.dropna(subset=["value"])
    # attribute renames over the years can give two rows for one line in one report: keep the first
    d = d.drop_duplicates(["com", "table", "region", "attr", "my", "wasde"])
    return d[["com", "table", "region", "attr", "my", "wasde", "release", "report", "value", "unit"]].sort_values("wasde")


def load():
    raw, notes = raw_history()
    return tidy(raw), notes


def us_exports(d, com):
    """USDA's U.S. export forecast in each release: my, wasde, release, value (U.S. units)."""
    return d[(d.com == com) & (d.table == "us") & (d.region == "United States") & (d.attr == "exports")][["my", "wasde", "release", "value"]]
