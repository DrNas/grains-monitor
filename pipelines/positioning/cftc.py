"""CFTC data for the positioning desk: disaggregated Commitments of Traders (futures and options combined) for
the Bloomberg Commodity Index markets the CFTC reports, and the supplemental Commodity Index Trader (CIT) report
for 13 agricultural markets. Adapted, with permission, from an existing open-source pipeline (fetching and
field mapping unchanged; markets are queried by contract code, which survives CFTC renames).
"""
import sys, time
from datetime import timedelta

import pandas as pd
import requests

UA = {"User-Agent": "grains-monitor/1.0 (daily build; +https://github.com/DrNas/grains-monitor)"}


def log(*a):
    print(*a, file=sys.stderr, flush=True)


# ── CFTC Socrata API ───────────────────────────────────────────────────────
ENDPOINT = "https://publicreporting.cftc.gov/resource/kh3c-gbw2.json"
API_LIMIT = 10000
REQUEST_DELAY = 1.2

# ── BCOM 2026 Constituents ─────────────────────────────────────────────────
# "code" is the CFTC contract market code. Market *names* change over time
# (e.g. WTI, Nat Gas and Brent were renamed in Feb 2022, which silently froze
# those series); codes are stable across renames, so we query by code and only
# fall back to the name if a code returns nothing.
# Not reported by the CFTC (LME / ICE Europe venues): Zinc, Nickel, Lead and
# Low Sulphur Gas Oil — they are listed in NOT_REPORTED for the UI.
BCOM = {
    "Brent Crude Oil":    {"ticker":"CO", "sector":"Energy",           "code":"06765T", "cftc":"BRENT LAST DAY - NEW YORK MERCANTILE EXCHANGE",          "crop":False},
    "Natural Gas":        {"ticker":"NG", "sector":"Energy",           "code":"023651", "cftc":"NAT GAS NYME - NEW YORK MERCANTILE EXCHANGE",            "crop":False},
    "WTI Crude Oil":      {"ticker":"CL", "sector":"Energy",           "code":"067651", "cftc":"WTI-PHYSICAL - NEW YORK MERCANTILE EXCHANGE",            "crop":False},
    "ULS Diesel":         {"ticker":"HO", "sector":"Energy",           "code":"022651", "cftc":"NY HARBOR ULSD - NEW YORK MERCANTILE EXCHANGE",          "crop":False},
    "RBOB Gasoline":      {"ticker":"XB", "sector":"Energy",           "code":"111659", "cftc":"GASOLINE RBOB - NEW YORK MERCANTILE EXCHANGE",           "crop":False},
    "Corn":               {"ticker":"C",  "sector":"Grains",           "code":"002602", "cftc":"CORN - CHICAGO BOARD OF TRADE",                          "crop":True},
    "Soybeans":           {"ticker":"S",  "sector":"Grains",           "code":"005602", "cftc":"SOYBEANS - CHICAGO BOARD OF TRADE",                      "crop":True},
    "Soybean Meal":       {"ticker":"SM", "sector":"Grains",           "code":"026603", "cftc":"SOYBEAN MEAL - CHICAGO BOARD OF TRADE",                  "crop":True},
    "Soybean Oil":        {"ticker":"BO", "sector":"Grains",           "code":"007601", "cftc":"SOYBEAN OIL - CHICAGO BOARD OF TRADE",                   "crop":True},
    "Wheat SRW":          {"ticker":"W",  "sector":"Grains",           "code":"001602", "cftc":"WHEAT-SRW - CHICAGO BOARD OF TRADE",                     "crop":True},
    "HRW Wheat":          {"ticker":"KW", "sector":"Grains",           "code":"001612", "cftc":"WHEAT-HRW - CHICAGO BOARD OF TRADE",                     "crop":True},
    "Copper":             {"ticker":"HG", "sector":"Industrial Metals","code":"085692", "cftc":"COPPER- #1 - COMMODITY EXCHANGE INC.",                   "crop":False},
    # COMEX outright Aluminum (191691) stopped being reported in Jun 2026; use the
    # US Midwest Premium contract, which the CFTC still publishes weekly.
    "Aluminum MWP":       {"ticker":"ALI","sector":"Industrial Metals","code":"191693", "cftc":"ALUMINUM MWP - COMMODITY EXCHANGE INC.",                 "crop":False},
    "Gold":               {"ticker":"GC", "sector":"Precious Metals",  "code":"088691", "cftc":"GOLD - COMMODITY EXCHANGE INC.",                         "crop":False},
    "Silver":             {"ticker":"SI", "sector":"Precious Metals",  "code":"084691", "cftc":"SILVER - COMMODITY EXCHANGE INC.",                       "crop":False},
    "Sugar":              {"ticker":"SB", "sector":"Softs",            "code":"080732", "cftc":"SUGAR NO. 11 - ICE FUTURES U.S.",                        "crop":False},
    "Coffee":             {"ticker":"KC", "sector":"Softs",            "code":"083731", "cftc":"COFFEE C - ICE FUTURES U.S.",                            "crop":True},
    "Cocoa":              {"ticker":"CC", "sector":"Softs",            "code":"073732", "cftc":"COCOA - ICE FUTURES U.S.",                               "crop":True},
    "Cotton":             {"ticker":"CT", "sector":"Softs",            "code":"033661", "cftc":"COTTON NO. 2 - ICE FUTURES U.S.",                        "crop":True},
    "Live Cattle":        {"ticker":"LC", "sector":"Livestock",        "code":"057642", "cftc":"LIVE CATTLE - CHICAGO MERCANTILE EXCHANGE",              "crop":False},
    "Lean Hogs":          {"ticker":"LH", "sector":"Livestock",        "code":"054642", "cftc":"LEAN HOGS - CHICAGO MERCANTILE EXCHANGE",                "crop":True},
}
NOT_REPORTED = ["Zinc", "Nickel", "Lead", "Low Sulphur Gas Oil"]

TRADER_CATS = ["managed_money", "swap_dealers", "prod_merc", "other_rept"]

# ── EXACT Socrata field names ───────────────────────────────────────────────
FIELDS = {
    "all": {
        "oi":    "open_interest_all",
        "mm_l":  "m_money_positions_long_all",
        "mm_s":  "m_money_positions_short_all",
        "mm_sp": "m_money_positions_spread",
        "mm_tl": "traders_m_money_long_all",
        "mm_ts": "traders_m_money_short_all",
        "sd_l":  "swap_positions_long_all",
        "sd_s":  "swap__positions_short_all",
        "sd_sp": "swap__positions_spread_all",
        "sd_tl": "traders_swap_long_all",
        "sd_ts": "traders_swap_short_all",
        "pm_l":  "prod_merc_positions_long",
        "pm_s":  "prod_merc_positions_short",
        "pm_tl": "traders_prod_merc_long_all",
        "pm_ts": "traders_prod_merc_short_all",
        "or_l":  "other_rept_positions_long",
        "or_s":  "other_rept_positions_short",
        "or_sp": "other_rept_positions_spread",
        "or_tl": "traders_other_rept_long_all",
        "or_ts": "traders_other_rept_short",
    },
    "old": {
        "oi":    "open_interest_old",
        "mm_l":  "m_money_positions_long_old",
        "mm_s":  "m_money_positions_short_old",
        "mm_sp": "m_money_positions_spread_1",
        "mm_tl": "traders_m_money_long_old",
        "mm_ts": "traders_m_money_short_old",
        "sd_l":  "swap_positions_long_old",
        "sd_s":  "swap__positions_short_old",
        "sd_sp": "swap__positions_spread_old",
        "sd_tl": "traders_swap_long_old",
        "sd_ts": "traders_swap_short_old",
        "pm_l":  "prod_merc_positions_long_1",
        "pm_s":  "prod_merc_positions_short_1",
        "pm_tl": "traders_prod_merc_long_old",
        "pm_ts": "traders_prod_merc_short_old",
        "or_l":  "other_rept_positions_long_1",
        "or_s":  "other_rept_positions_short_1",
        "or_sp": "other_rept_positions_spread_1",
        "or_tl": "traders_other_rept_long_old",
        "or_ts": "traders_other_rept_short_1",
    },
    "other": {
        "oi":    "open_interest_other",
        "mm_l":  "m_money_positions_long_other",
        "mm_s":  "m_money_positions_short_other",
        "mm_sp": "m_money_positions_spread_2",
        "mm_tl": "traders_m_money_long_other",
        "mm_ts": "traders_m_money_short_other",
        "sd_l":  "swap_positions_long_other",
        "sd_s":  "swap__positions_short_other",
        "sd_sp": "swap__positions_spread_other",
        "sd_tl": "traders_swap_long_other",
        "sd_ts": "traders_swap_short_other",
        "pm_l":  "prod_merc_positions_long_2",
        "pm_s":  "prod_merc_positions_short_2",
        "pm_tl": "traders_prod_merc_long_other",
        "pm_ts": "traders_prod_merc_short_other",
        "or_l":  "other_rept_positions_long_2",
        "or_s":  "other_rept_positions_short_2",
        "or_sp": "other_rept_positions_spread_2",
        "or_tl": "traders_other_rept_long_other",
        "or_ts": "traders_other_rept_short_2",
    }
}

CAT_PREFIX = {
    "managed_money": "mm",
    "swap_dealers":  "sd",
    "prod_merc":     "pm",
    "other_rept":    "or",
}

# ── Helpers ────────────────────────────────────────────────────────────────
def si(val):
    """Safe int parse."""
    try:
        v = int(val)
        return 0 if pd.isna(v) else v
    except (TypeError, ValueError):
        return 0

def _get(where):
    url = (f"{ENDPOINT}?$where={where}"
           f"&$order=report_date_as_yyyy_mm_dd ASC&$limit={API_LIMIT}")
    for attempt in range(3):
        try:
            r = requests.get(url, headers=UA, timeout=60)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            log(f"  (attempt {attempt+1}) error: {e}")
            time.sleep(3 * (attempt + 1))
    return []


def fetch_commodity(meta, since_date="2006-01-01"):
    """Fetch all records for a commodity since a date — by contract code
    (stable across CFTC renames), falling back to the market name."""
    date_clause = f" AND report_date_as_yyyy_mm_dd >= '{since_date}'"
    if meta.get("code"):
        data = _get(f"cftc_contract_market_code='{meta['code']}'" + date_clause)
        if data:
            return data
    enc = meta["cftc"].replace("'", "''")
    return _get(f"market_and_exchange_names='{enc}'" + date_clause)

# ── Process raw API records into flat rows ─────────────────────────────────
def process_records(raw, commodity_name, meta, crop_type="all"):
    """Convert list of raw API dicts into a list of flat row dicts."""
    fmap = FIELDS[crop_type]
    rows = []
    for rec in raw:
        date_str = rec.get("report_date_as_yyyy_mm_dd", "")[:10]
        if not date_str:
            continue

        oi = si(rec.get(fmap["oi"]))

        row = {
            "date":           date_str,
            "commodity":      commodity_name,
            "ticker":         meta["ticker"],
            "sector":         meta["sector"],
            "crop_type":      crop_type,
            "is_crop":        meta["crop"],
            "open_interest":  oi,
        }

        for cat, pfx in CAT_PREFIX.items():
            L  = si(rec.get(fmap[f"{pfx}_l"]))
            S  = si(rec.get(fmap[f"{pfx}_s"]))
            Sp = si(rec.get(fmap.get(f"{pfx}_sp",""))) if fmap.get(f"{pfx}_sp") else 0
            TL = si(rec.get(fmap[f"{pfx}_tl"]))
            TS = si(rec.get(fmap[f"{pfx}_ts"]))

            net    = L - S
            lp     = (L / oi * 100) if oi > 0 else 0.0
            sp_pct = (S / oi * 100) if oi > 0 else 0.0
            np_pct = lp - sp_pct
            ppt_l  = (L / TL) if TL > 0 else 0.0
            ppt_s  = (S / TS) if TS > 0 else 0.0

            prefix = f"{cat}"
            row[f"{prefix}_long"]          = L
            row[f"{prefix}_short"]         = S
            row[f"{prefix}_spread"]        = Sp
            row[f"{prefix}_net"]           = net
            row[f"{prefix}_traders_long"]  = TL
            row[f"{prefix}_traders_short"] = TS
            row[f"{prefix}_long_pct_oi"]   = round(lp, 3)
            row[f"{prefix}_short_pct_oi"]  = round(sp_pct, 3)
            row[f"{prefix}_net_pct_oi"]    = round(np_pct, 3)
            row[f"{prefix}_per_trader_l"]  = round(ppt_l, 1)
            row[f"{prefix}_per_trader_s"]  = round(ppt_s, 1)

        rows.append(row)
    return rows


# ── Commodity Index Trader (supplemental) report ──────────────────────────────
CIT_ENDPOINT = "https://publicreporting.cftc.gov/resource/4zgm-a668.json"
CIT_LIMIT = 10000
DELAY = 1.2

# Names match bcom_cot_master.csv so the two files join on (date, commodity).
CIT_MARKETS = {
    "Corn":          {"ticker": "C",  "sector": "Grains",    "code": "002602"},
    "Soybeans":      {"ticker": "S",  "sector": "Grains",    "code": "005602"},
    "Soybean Meal":  {"ticker": "SM", "sector": "Grains",    "code": "026603"},
    "Soybean Oil":   {"ticker": "BO", "sector": "Grains",    "code": "007601"},
    "Wheat SRW":     {"ticker": "W",  "sector": "Grains",    "code": "001602"},
    "HRW Wheat":     {"ticker": "KW", "sector": "Grains",    "code": "001612"},
    "Cotton":        {"ticker": "CT", "sector": "Softs",     "code": "033661"},
    "Sugar":         {"ticker": "SB", "sector": "Softs",     "code": "080732"},
    "Coffee":        {"ticker": "KC", "sector": "Softs",     "code": "083731"},
    "Cocoa":         {"ticker": "CC", "sector": "Softs",     "code": "073732"},
    "Live Cattle":   {"ticker": "LC", "sector": "Livestock", "code": "057642"},
    "Lean Hogs":     {"ticker": "LH", "sector": "Livestock", "code": "054642"},
    "Feeder Cattle": {"ticker": "FC", "sector": "Livestock", "code": "061641"},
}

# Socrata field names (lower-case; note the CFTC's own "postions" typo)
CIT_F = {
    "oi": "open_interest_all",
    "cit_l": "cit_positions_long_all", "cit_s": "cit_positions_short_all",
    "cit_tl": "traders_cit_long_all", "cit_ts": "traders_cit_short_all",
    "nc_l": "ncomm_postions_long_all_nocit", "nc_s": "ncomm_postions_short_all_nocit",
    "nc_sp": "ncomm_postions_spread_all_nocit",
    "nc_tl": "traders_noncomm_long_all_nocit", "nc_ts": "traders_noncomm_short_all_nocit",
    "cm_l": "comm_positions_long_all_nocit", "cm_s": "comm_positions_short_all_nocit",
    "cm_tl": "traders_comm_long_all_nocit", "cm_ts": "traders_comm_short_all_nocit",
    "nr_l": "nonrept_positions_long_all", "nr_s": "nonrept_positions_short_all",
}


def cit_get(code, since):
    url = (f"{CIT_ENDPOINT}?$where=cftc_contract_market_code='{code}' AND "
           f"report_date_as_yyyy_mm_dd >= '{since}'"
           f"&$order=report_date_as_yyyy_mm_dd ASC&$limit={CIT_LIMIT}")
    for attempt in range(3):
        try:
            r = requests.get(url, headers=UA, timeout=60)
            r.raise_for_status()
            return r.json()
        except Exception as e:  # noqa: BLE001
            log(f"    retry {attempt + 1}: {e}")
            time.sleep(3 * (attempt + 1))
    return []


def cit_rows_for(name, meta, raw):
    out = []
    for rec in raw:
        rec = {k.lower(): v for k, v in rec.items()}
        d = (rec.get("report_date_as_yyyy_mm_dd") or "")[:10]
        if not d:
            continue
        v = {k: si(rec.get(f)) for k, f in CIT_F.items()}
        oi = v["oi"]
        pct = (lambda x: round(x / oi * 100, 3) if oi > 0 else 0.0)
        out.append({
            "date": d, "commodity": name, "ticker": meta["ticker"], "sector": meta["sector"],
            "open_interest": oi,
            "cit_long": v["cit_l"], "cit_short": v["cit_s"], "cit_net": v["cit_l"] - v["cit_s"],
            "cit_traders_long": v["cit_tl"], "cit_traders_short": v["cit_ts"],
            "cit_long_pct_oi": pct(v["cit_l"]), "cit_net_pct_oi": pct(v["cit_l"] - v["cit_s"]),
            "cit_per_trader_l": round(v["cit_l"] / v["cit_tl"], 1) if v["cit_tl"] else 0.0,
            "noncomm_long": v["nc_l"], "noncomm_short": v["nc_s"], "noncomm_spread": v["nc_sp"],
            "noncomm_net": v["nc_l"] - v["nc_s"],
            "noncomm_traders_long": v["nc_tl"], "noncomm_traders_short": v["nc_ts"],
            "comm_long": v["cm_l"], "comm_short": v["cm_s"], "comm_net": v["cm_l"] - v["cm_s"],
            "comm_traders_long": v["cm_tl"], "comm_traders_short": v["cm_ts"],
            "nonrept_long": v["nr_l"], "nonrept_short": v["nr_s"],
        })
    return out


