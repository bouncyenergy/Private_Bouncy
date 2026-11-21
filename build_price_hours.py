#!/usr/bin/env python3
"""
build_price_hours.py
====================
Bygger viewer/price_hours.html: en fristående sida som visar hur många timmar per
månad som dagen-före-priset låg under, över eller mellan valfria nivåer.

Läser data/raw/<ZON>.csv.gz (skrivs av update_data.py), räknar ett histogram per
zon och månad (lådor om 1 EUR/MWh, månader i svensk lokaltid) och bäddar in det i
price_hours_template.html. Reglaget i sidan summerar lådorna, så alla heltalsnivåer
mellan LO och HI blir exakta.

    python build_price_hours.py
"""
import csv
import gzip
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent
RAW = ROOT / "data" / "raw"
ORDER = ["SE1", "SE2", "SE3", "SE4", "NO1", "NO2", "NO3", "NO4", "NO5", "DK1", "DK2", "FI", "DE"]
LO, HI = -150, 400  # EUR/MWh. Lådan 0 = pris under LO, sista lådan = pris från och med HI.
NBINS = HI - LO + 2
LOCAL = ZoneInfo("Europe/Stockholm")


def month_histograms(path: Path) -> dict:
    hist = {}
    with gzip.open(path, "rt", encoding="utf-8", newline="") as f:
        reader = csv.reader(f)
        next(reader, None)  # rubrikrad: ,price,wind,solar,load
        for row in reader:
            if len(row) < 2 or not row[1].strip():
                continue
            try:
                price = float(row[1])
                ts = datetime.fromisoformat(row[0].strip())
            except ValueError:
                continue
            if math.isnan(price):
                continue
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            local = ts.astimezone(LOCAL)
            key = f"{local.year}-{local.month:02d}"
            if price < LO:
                idx = 0
            elif price >= HI:
                idx = NBINS - 1
            else:
                idx = int(math.floor(price)) - LO + 1
            counts = hist.setdefault(key, [0] * NBINS)
            counts[idx] += 1
    return hist


def main() -> int:
    zones = {}
    for z in ORDER:
        path = RAW / f"{z}.csv.gz"
        if not path.exists():
            print(f"Varning: {path} saknas, hoppar över {z}")
            continue
        hist = month_histograms(path)
        if hist:
            zones[z] = hist
    if not zones:
        print("Inga prisdata i data/raw. Kör update_data.py först.")
        return 1

    months = sorted({m for h in zones.values() for m in h})
    payload = {
        "generated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "lo": LO,
        "hi": HI,
        "order": [z for z in ORDER if z in zones],
        "months": months,
        "zones": zones,
    }
    template = (ROOT / "price_hours_template.html").read_text(encoding="utf-8")
    assert "/*EMBED_JSON*/null" in template
    text = json.dumps(payload, separators=(",", ":")).replace("</", "<\\/")
    out = ROOT / "viewer" / "price_hours.html"
    out.parent.mkdir(exist_ok=True)
    out.write_text(template.replace("/*EMBED_JSON*/null", text), encoding="utf-8")
    print(f"Skrev {out} ({out.stat().st_size // 1024} KB, {len(zones)} zoner, {len(months)} månader)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
