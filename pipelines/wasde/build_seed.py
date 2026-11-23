"""Builds data/wasde/history.csv.gz, the WASDE history the grains desk starts from.

USDA posts each month's WASDE data as a CSV on usda.gov, but only from about 2021; earlier releases are in
USDA's historical WASDE data files. Pass any number of USDA WASDE data CSVs (the standard column layout:
WasdeNumber, ReleaseDate, ReportTitle, Commodity, Region, MarketYear, Attribute, Value, Unit, ...), for
example a combined history file and the latest monthly files:

    python pipelines/wasde/build_seed.py history.csv oce-wasde-report-data-2026-10.csv

Only the tables in wasde_data.TABLES are kept. The build adds releases after the seed's last one on its own,
so the seed only needs rebuilding if a table is added.
"""
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from wasde_data import SEED, select  # noqa: E402

if __name__ == "__main__":
    parts = [select(pd.read_csv(p, dtype=str, low_memory=False, encoding="utf-8-sig")) for p in sys.argv[1:]]
    if not parts:
        raise SystemExit(__doc__)
    d = pd.concat(parts, ignore_index=True)
    d = d.drop_duplicates(["WasdeNumber", "ReportTitle", "Commodity", "Region", "MarketYear", "Attribute"])
    d["n"] = d.WasdeNumber.astype(int)
    d = d.sort_values(["n", "ReportTitle", "Commodity", "Region", "MarketYear", "Attribute"]).drop(columns="n")
    SEED.parent.mkdir(parents=True, exist_ok=True)
    d.to_csv(SEED, index=False, compression={"method": "gzip", "mtime": 0})
    n = d.WasdeNumber.astype(int)
    print(f"{SEED}: {len(d)} rows, WASDE {n.min()}-{n.max()} ({d.ReleaseDate.min()} to {d.ReleaseDate.max()}), "
          f"{SEED.stat().st_size / 1e6:.1f} MB")
