#!/usr/bin/env python3
"""
fetch_svk_api.py
================
Hämtar aFRR- och mFRR-kapacitetsmarknad från Svenska kraftnäts öppna dataportal (https://data.svk.se, CKAN-API,
ingen token behövs) och sammanfattar månadsvis:

  - Volymviktat marginalpris (EUR/MW)
  - Medelvolym upphandlad kapacitet (MW) per publicerad timme, totalt och per elområde
  - Antal publicerade timmar

Viktigt om datat: Svenska kraftnät skriver att "för närvarande publiceras enbart timmar med avrop i Sverige".
Medelvärdena gäller alltså de timmar som publicerats, inte alla timmar under månaden.

    pip install pandas requests
    python fetch_svk_api.py --out data/saturation/se_afrr_mfrr_monthly.csv

Kolumner i datasetet (enligt portalens datakatalog): start_time_sweden, start_time_utc, bidding_zone,
reserve_product, reserve_direction, price, price_unit, volume, volume_unit.
"""

import argparse
import calendar
import json
import logging
import re
import sys
import time
from pathlib import Path

import pandas as pd

LOG = logging.getLogger("svkapi")
API = "https://data.svk.se/sv/api/3/action/datastore_search"
RESOURCES = {  # produktfamilj -> (resurs-id, första månad)
    "aFRR": ("6351d2cc-1657-43eb-b112-b8408c700529", "2022-05"),
    "mFRR": ("0c56e30d-8fce-4c27-afc8-621c230ae34d", "2023-10"),
}
ZONES = ["SE1", "SE2", "SE3", "SE4"]
PAGE = 32000  # portalens maxgräns för limit


def norm_zone(z) -> str:
    return re.sub(r"[^A-Za-z0-9]", "", str(z)).upper()  # "SE 3" / "SE_3" -> "SE3"


def norm_dir(d) -> str | None:
    s = str(d).lower()
    if "up" in s or "upp" in s:
        return "up"
    if "down" in s or "ned" in s:
        return "down"
    return None


def fetch_records(resource_id: str, start_utc: str, end_utc: str, tries: int = 3) -> list[dict] | None:
    """Hämtar alla poster med start_time_utc i [start_utc, end_utc). Paginerar med offset.
    Returnerar None om något anrop misslyckas helt (hellre ingen månad än en halv månad)."""
    import requests

    out, offset = [], 0
    while True:
        params = {
            "resource_id": resource_id,
            "filters": json.dumps({"start_time_utc": {"gte": start_utc, "lt": end_utc}}),
            "sort": "start_time_utc",
            "limit": PAGE,
            "offset": offset,
        }
        for i in range(1, tries + 1):
            try:
                r = requests.get(API, params=params, timeout=90)
                r.raise_for_status()
                data = r.json()
                if not data.get("success", False):
                    raise RuntimeError(str(data.get("error"))[:200])
                recs = data["result"]["records"]
                break
            except Exception as exc:
                LOG.warning("%s..%s försök %d/%d misslyckades: %s", start_utc, end_utc, i, tries, str(exc)[:150])
                if i == tries:
                    return None
                time.sleep(5 * i)
        out.extend(recs)
        if len(recs) < PAGE:
            return out
        offset += PAGE


def aggregate(family: str, records: list[dict]) -> pd.DataFrame:
    """Månadsaggregat per riktning. Returnerar tom DataFrame om inget hittas."""
    if not records:  # None (misslyckad hämtning) eller tom lista (inga publicerade timmar)
        return pd.DataFrame()
    df = pd.DataFrame(records)
    need = {"start_time_utc", "bidding_zone", "reserve_direction", "price", "volume"}
    if not need <= set(df.columns):
        LOG.warning("%s: saknar kolumner %s (har %s)", family, sorted(need - set(df.columns)), sorted(df.columns))
        return pd.DataFrame()
    df["price"] = pd.to_numeric(df["price"], errors="coerce")
    df["volume"] = pd.to_numeric(df["volume"], errors="coerce")
    df["zone"] = df["bidding_zone"].map(norm_zone)
    df["dir"] = df["reserve_direction"].map(norm_dir)
    df = df[df["dir"].notna() & df["volume"].notna()]
    df["month"] = df["start_time_utc"].astype(str).str[:7]

    rows = []
    for (month, d), g in df.groupby(["month", "dir"]):
        vol_sum = g["volume"].sum()
        price = (g["price"] * g["volume"]).sum() / vol_sum if vol_sum > 0 else float("nan")
        hourly_total = g.groupby("start_time_utc")["volume"].sum()
        row = {"month": month, "product": f"{family} {d}", "hours": int(hourly_total.size),
               "price_eur_mw": price, "vol_total_mw": hourly_total.mean()}
        for z in ZONES:
            gz = g[g["zone"] == z]
            row[f"vol_{z}"] = gz["volume"].mean() if len(gz) else None
        rows.append(row)
    return pd.DataFrame(rows)


def month_bounds(year: int, month: int) -> tuple[str, str]:
    start = f"{year}-{month:02d}-01T00:00:00"
    ny, nm = (year + 1, 1) if month == 12 else (year, month + 1)
    return start, f"{ny}-{nm:02d}-01T00:00:00"


def month_range(start: str, end: pd.Timestamp):
    y, m = map(int, start.split("-"))
    while (y, m) <= (end.year, end.month):
        yield y, m
        m += 1
        if m == 13:
            y, m = y + 1, 1


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default="data/saturation/se_afrr_mfrr_monthly.csv")
    ap.add_argument("--start", default=None, help="Tidigaste månad, ÅÅÅÅ-MM (annars datasetets början)")
    ap.add_argument("--refresh", action="store_true", help="Hämta om alla månader")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    old = pd.read_csv(out) if out.exists() else pd.DataFrame()
    have = set(old["month"]) if len(old) else set()

    now = pd.Timestamp.now()
    prev = now.replace(day=1) - pd.Timedelta(days=1)
    always = {now.strftime("%Y-%m"), prev.strftime("%Y-%m")}

    parts = []
    for family, (rid, first) in RESOURCES.items():
        start = max(first, args.start) if args.start else first
        for y, m in month_range(start, now):
            key = f"{y}-{m:02d}"
            if key in have and key not in always and not args.refresh:
                continue
            s, e = month_bounds(y, m)
            LOG.info("%s %s ...", family, key)
            agg = aggregate(family, fetch_records(rid, s, e))
            if len(agg):
                parts.append(agg)

    if not parts and not len(old):
        sys.exit("Ingen data hämtades från Svenska kraftnäts dataportal.")
    keep_old = [old] if len(old) else []
    df = (pd.concat(keep_old + parts, ignore_index=True)
          .drop_duplicates(["month", "product"], keep="last")
          .sort_values(["month", "product"]))
    df.to_csv(out, index=False, float_format="%.3f")
    LOG.info("Klart: %s (%d rader, %s till %s)", out, len(df), df["month"].min(), df["month"].max())


if __name__ == "__main__":
    main()
