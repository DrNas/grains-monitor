"""WASDE balance sheets for the grains desk: U.S. balance with this month's revisions and each line's revision
path, how far USDA usually revises from first to final estimate, stocks-to-use vs farm price, and key countries
from the world tables. Adapted, with permission, from an existing open-source pipeline.

Run by scripts/build-data.mjs; prints {data, latest, n, src, note, partial} as JSON on stdout. No key.
"""
import json, sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import wasde_data as W  # noqa: E402

COMS = {"corn": "Corn", "soybeans": "Soybeans", "meal": "Soybean meal", "oil": "Soybean oil", "wheat": "Wheat"}
UNITS = {"corn": "mil bu", "soybeans": "mil bu", "wheat": "mil bu", "meal": "thou short tons", "oil": "mil lb"}
COUNTRIES = {"corn": ["World", "World Less China", "United States", "Brazil", "Argentina", "Ukraine", "European Union", "China", "Mexico", "Japan"],
             "soybeans": ["World", "World Less China", "United States", "Brazil", "Argentina", "Paraguay", "China", "European Union"],
             "meal": ["World", "United States", "Argentina", "Brazil", "European Union", "China"],
             "oil": ["World", "United States", "Argentina", "Brazil", "European Union", "China", "India"],
             "wheat": ["World", "World Less China", "United States", "Russia", "European Union", "Canada", "Australia", "Argentina",
                       "Ukraine", "Kazakhstan", "China", "India", "Egypt"]}


def balance(x, years=3, hist=18):
    """Latest release for the last `years` marketing years: value, change vs the previous release, revision path."""
    mys = sorted(x.my.unique())[-years:]
    out = {}
    for my in mys:
        y = x[x.my == my]
        last = y.wasde.max()
        prev = y[y.wasde < last].wasde.max() if (y.wasde < last).any() else None
        row = {}
        for a, g in y.groupby("attr"):
            g = g.sort_values("wasde")
            cur = g[g.wasde == last].value
            pv = g[g.wasde == prev].value if prev is not None else pd.Series(dtype=float)
            row[a] = {"value": float(cur.iloc[0]) if len(cur) else None,
                      "change": round(float(cur.iloc[0] - pv.iloc[0]), 3) if len(cur) and len(pv) else None,
                      "first": float(g.value.iloc[0]), "unit": g.unit.iloc[-1],
                      "history": [[r.report, float(r.value)] for r in g.itertuples()][-hist:]}
        out[my] = {"report": y[y.wasde == last].report.iloc[0], "items": row}
    return out


def final_values(x):
    """Last estimate for each marketing year, one column per line."""
    return x.sort_values("wasde").groupby(["my", "attr"]).value.last().unstack()


def stocks_use_vs_price(fv):
    if not {"end_stocks", "use", "price"} <= set(fv.columns):
        return None
    f = fv.dropna(subset=["end_stocks", "use", "price"]).copy()
    f["su"] = 100 * f.end_stocks / f.use
    f = f.iloc[:-1]   # drop the current projection year
    if len(f) < 6:
        return None
    lx, ly = np.log(f.su), np.log(f.price)
    b, a = np.polyfit(lx, ly, 1)
    return {"my": f.index.tolist(), "stocks_use_pct": f.su.round(2).tolist(), "price": f.price.round(3).tolist(),
            "fit": {"elasticity": round(float(b), 3), "intercept": round(float(a), 3),
                    "r2": round(float(np.corrcoef(lx, ly)[0, 1] ** 2), 3)}}


def revision_stats(x, attr):
    """How far USDA moves `attr` from its first estimate to its final one, by completed marketing year."""
    y = x[x.attr == attr].sort_values("wasde")
    rows = [dict(my=my, first=float(g.value.iloc[0]), final=float(g.value.iloc[-1])) for my, g in y.groupby("my") if len(g) >= 12]
    r = pd.DataFrame(rows)
    if r.empty or (r["first"] == 0).any():
        return None
    r["pct"] = 100 * (r.final / r["first"] - 1)
    return {"my": r.my.tolist(), "first": r["first"].tolist(), "final": r.final.tolist(), "pct": r.pct.round(2).tolist(),
            "mean_abs_pct": round(float(r.pct.abs().mean()), 2)}


def main():
    d, notes = W.load()
    out = {}
    for com, label in COMS.items():
        us = d[(d.com == com) & (d.table == "us") & (d.region == "United States")]
        if us.empty:
            notes.append(f"{com}: no U.S. rows")
            continue
        entry = {"label": label, "unit": UNITS[com], "us": balance(us),
                 "stocks_use_vs_price": stocks_use_vs_price(final_values(us)),
                 "revisions": {a: revision_stats(us, a) for a in ("yield", "production", "exports", "end_stocks", "crush", "feed_residual", "ethanol", "domestic")
                               if a in us.attr.unique()}}
        wd = d[(d.com == com) & (d.table == "world")]
        entry["world"] = {c: balance(wd[wd.region == c], years=2, hist=0) for c in COUNTRIES[com] if c in set(wd.region)}
        for c in entry["world"].values():   # no revision paths for countries: keeps the file small
            for my in c.values():
                for it in my["items"].values():
                    it.pop("history", None)
        out[com] = entry
    if not out:
        raise SystemExit("no WASDE data: " + "; ".join(notes))
    last = d[d.wasde == d.wasde.max()]
    print(json.dumps({"data": {"report": last.report.iloc[0], "wasde": int(last.wasde.iloc[0]), "release": last.release.iloc[0].strftime("%Y-%m-%d"),
                               "commodities": out},
                      "latest": last.release.iloc[0].strftime("%Y-%m-%d"), "n": len(out),
                      "src": "USDA World Agricultural Supply and Demand Estimates (WASDE)",
                      "note": "; ".join(notes), "partial": bool(notes)},
                     separators=(",", ":"), allow_nan=False, default=lambda o: None).replace("NaN", "null"))


if __name__ == "__main__":
    main()
