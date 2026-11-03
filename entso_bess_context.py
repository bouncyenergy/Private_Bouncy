#!/usr/bin/env python3
"""
entso_bess_context.py
=====================
Hämtar ENTSO-E-data per elområde/budzon och bygger ett nyckeltalsunderlag för
att bedöma hur "mättad" en marknad är för BESS.

Per zon och år:
  - Topplast (MW), baserad på timmedel av faktisk last
  - Installerad sol- och vindkapacitet (MW)  [valfri proxy: högsta producerade effekt]
  - Antal timmar med negativa dagen-före-priser (och andel av året)
  - Medelpris, samt genomsnittlig daglig brutto-spread (2h och 4h, utan förluster)
  - Valfritt: BESS-MW/MWh från din egen tabell -> BESS/topplast, BESS/(sol+vind)

ENTSO-E har ingen tillförlitlig kategori för installerad BESS per zon, så
BESS-kolumnerna fylls från en egen CSV (bess_input.csv) som skapas som mall
första gången du kör skriptet.

Installation:
    pip install entsoe-py pandas python-dotenv

Token (lägg ALDRIG i koden eller i git):
    export ENTSOE_TOKEN="..."            # eller
    .env med raden ENTSOE_TOKEN=...      # och lägg .env i .gitignore

Exempel:
    python entso_bess_context.py
    python entso_bess_context.py --years 2023 2024 2025 2026 --zones SE_3 SE_4 DE_LU
    python entso_bess_context.py --gen-proxy          # om installerad kapacitet saknas
    python entso_bess_context.py --refresh            # ignorera cache

Utdata (i --out, standard ./out):
    zone_year_metrics.csv    en rad per zon och år
    bess_input.csv           mall för BESS-MW/MWh (skapas om den saknas)
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

try:  # valfritt
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

LOG = logging.getLogger("entso_bess")
TZ = "Europe/Brussels"

NORDIC_ZONES = [
    "SE_1", "SE_2", "SE_3", "SE_4",
    "NO_1", "NO_2", "NO_3", "NO_4", "NO_5",
    "DK_1", "DK_2",
    "FI",
]
REFERENCE_ZONES = ["DE_LU", "NL", "BE", "PL"]  # mer mogna/andra marknader för jämförelse

PSR_SOLAR = "B16"
PSR_WIND_ON = "B19"
PSR_WIND_OFF = "B18"


# --------------------------------------------------------------------------- #
# Hjälpfunktioner
# --------------------------------------------------------------------------- #
def get_client():
    token = os.environ.get("ENTSOE_TOKEN")
    if not token:
        sys.exit("Saknar ENTSOE_TOKEN i miljön. Se instruktionerna överst i filen.")
    try:
        from entsoe import EntsoePandasClient
    except ImportError:
        sys.exit("Installera först: pip install entsoe-py")
    return EntsoePandasClient(api_key=token)


def year_window(year: int) -> tuple[pd.Timestamp, pd.Timestamp]:
    start = pd.Timestamp(f"{year}-01-01", tz=TZ)
    end = pd.Timestamp(f"{year + 1}-01-01", tz=TZ)
    now = pd.Timestamp.now(tz=TZ).floor("D")
    return start, min(end, now)


def retry(fn, tries: int = 3, wait: float = 5.0):
    """Kör fn() med enkel omförsök-logik. Returnerar None om data saknas."""
    try:
        from entsoe.exceptions import NoMatchingDataError
    except Exception:  # äldre/nyare versioner
        NoMatchingDataError = ()  # type: ignore

    for i in range(1, tries + 1):
        try:
            return fn()
        except NoMatchingDataError:
            return None
        except Exception as exc:  # nätverk, rate limit, 5xx
            msg = str(exc)
            if "No matching data" in msg:
                return None
            LOG.warning("Försök %d/%d misslyckades: %s", i, tries, msg[:200])
            time.sleep(wait * i)
    return None


def cached(cache_dir: Path, key: str, refresh: bool, loader):
    path = cache_dir / f"{key}.pkl"
    if path.exists() and not refresh:
        return pd.read_pickle(path)
    obj = loader()
    if obj is not None and len(obj) > 0:
        cache_dir.mkdir(parents=True, exist_ok=True)
        pd.to_pickle(obj, path)
    return obj


def to_series(obj) -> pd.Series | None:
    """entsoe-py returnerar ibland Series, ibland DataFrame. Gör om till Series."""
    if obj is None:
        return None
    if isinstance(obj, pd.DataFrame):
        if obj.shape[1] == 0:
            return None
        # "Actual Load" om den finns, annars första kolumnen
        col = next((c for c in obj.columns if "Actual" in str(c)), obj.columns[0])
        obj = obj[col]
    return obj.dropna()


# --------------------------------------------------------------------------- #
# Hämtning
# --------------------------------------------------------------------------- #
def fetch_load(client, zone, year, cache_dir, refresh):
    start, end = year_window(year)
    if end <= start:
        return None

    def loader():
        return retry(lambda: client.query_load(zone, start=start, end=end))

    return to_series(cached(cache_dir, f"load_{zone}_{year}", refresh, loader))


def fetch_prices(client, zone, year, cache_dir, refresh):
    start, end = year_window(year)
    if end <= start:
        return None

    def loader():
        return retry(lambda: client.query_day_ahead_prices(zone, start=start, end=end))

    return to_series(cached(cache_dir, f"da_{zone}_{year}", refresh, loader))


def fetch_installed(client, zone, year, cache_dir, refresh) -> dict[str, float]:
    """Installerad sol/vind (MW) från ENTSO-E:s årliga rapport. NaN om saknas."""
    start = pd.Timestamp(f"{year}-01-01", tz=TZ)
    end = pd.Timestamp(f"{year + 1}-01-01", tz=TZ)

    def loader():
        return retry(
            lambda: client.query_installed_generation_capacity(zone, start=start, end=end)
        )

    df = cached(cache_dir, f"inst_{zone}_{year}", refresh, loader)
    out = {"solar_mw": np.nan, "wind_mw": np.nan}
    if df is None or len(df) == 0:
        return out
    if isinstance(df, pd.Series):
        df = df.to_frame().T
    row = df.iloc[0]
    flat = {" ".join(map(str, k)) if isinstance(k, tuple) else str(k): v for k, v in row.items()}
    solar = [v for k, v in flat.items() if "Solar" in k]
    wind = [v for k, v in flat.items() if "Wind" in k]
    if solar:
        out["solar_mw"] = float(np.nansum(solar))
    if wind:
        out["wind_mw"] = float(np.nansum(wind))
    return out


def fetch_gen_proxy(client, zone, year, cache_dir, refresh) -> dict[str, float]:
    """Proxy: högsta producerade timmedeleffekt under året (underskattar installerat)."""
    start, end = year_window(year)
    out = {"solar_mw": np.nan, "wind_mw": np.nan}
    if end <= start:
        return out
    for label, psr_list in (("solar_mw", [PSR_SOLAR]), ("wind_mw", [PSR_WIND_ON, PSR_WIND_OFF])):
        total = None
        for psr in psr_list:

            def loader(psr=psr):
                return retry(lambda: client.query_generation(zone, start=start, end=end, psr_type=psr))

            df = cached(cache_dir, f"gen_{zone}_{psr}_{year}", refresh, loader)
            s = to_series(df.iloc[:, 0] if isinstance(df, pd.DataFrame) and df.shape[1] else df)
            if s is None:
                continue
            s = s.resample("1h").mean()
            total = s if total is None else total.add(s, fill_value=0)
        if total is not None and len(total):
            out[label] = float(total.max())
    return out


# --------------------------------------------------------------------------- #
# Nyckeltal
# --------------------------------------------------------------------------- #
def hourly(s: pd.Series) -> pd.Series:
    return s.resample("1h").mean().dropna()


def daily_spread(prices_h: pd.Series, n: int) -> float:
    """Medel över dagar av (snitt av n dyraste timmar - snitt av n billigaste). Brutto, utan förluster."""
    vals = []
    for _, day in prices_h.groupby(prices_h.index.date):
        if len(day) < 20:  # hoppa över ofullständiga dygn (sommartid/hål)
            continue
        srt = np.sort(day.values)
        vals.append(srt[-n:].mean() - srt[:n].mean())
    return float(np.mean(vals)) if vals else np.nan


def price_metrics(prices: pd.Series | None) -> dict[str, float]:
    keys = ["mean_price", "neg_hours", "neg_share", "spread_2h", "spread_4h", "price_days"]
    if prices is None or len(prices) == 0:
        return {k: np.nan for k in keys}
    ph = hourly(prices)
    neg = int((ph < 0).sum())
    return {
        "mean_price": float(ph.mean()),
        "neg_hours": neg,
        "neg_share": neg / len(ph),
        "spread_2h": daily_spread(ph, 2),
        "spread_4h": daily_spread(ph, 4),
        "price_days": ph.index.normalize().nunique(),
    }


def load_metrics(load: pd.Series | None) -> dict[str, float]:
    if load is None or len(load) == 0:
        return {"peak_load_mw": np.nan, "peak_time": None, "load_days": np.nan}
    lh = hourly(load)
    return {
        "peak_load_mw": float(lh.max()),
        "peak_time": lh.idxmax().isoformat(),
        "load_days": lh.index.normalize().nunique(),
    }


# --------------------------------------------------------------------------- #
# BESS-indata (egen tabell)
# --------------------------------------------------------------------------- #
def ensure_bess_template(path: Path, zones: list[str], years: list[int]) -> None:
    if path.exists():
        return
    rows = [{"zone": z, "year": y, "bess_mw": "", "bess_mwh": ""} for z in zones for y in years]
    pd.DataFrame(rows).to_csv(path, index=False)
    LOG.info("Skapade mall %s - fyll i front-of-the-meter BESS (MW och MWh) per zon/år.", path)


def merge_bess(df: pd.DataFrame, path: Path) -> pd.DataFrame:
    if not path.exists():
        return df
    b = pd.read_csv(path)
    for c in ("bess_mw", "bess_mwh"):
        b[c] = pd.to_numeric(b[c], errors="coerce")
    df = df.merge(b[["zone", "year", "bess_mw", "bess_mwh"]], on=["zone", "year"], how="left")
    df["bess_duration_h"] = df["bess_mwh"] / df["bess_mw"]
    df["bess_pct_of_peak"] = 100 * df["bess_mw"] / df["peak_load_mw"]
    df["bess_pct_of_solar_wind"] = 100 * df["bess_mw"] / (df["solar_mw"] + df["wind_mw"])
    return df


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #
def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--zones", nargs="+", default=None, help="Budzoner, t.ex. SE_3 SE_4 DE_LU")
    ap.add_argument("--no-reference", action="store_true", help="Hoppa över referenszonerna")
    ap.add_argument("--years", nargs="+", type=int, default=None)
    ap.add_argument("--out", default="out")
    ap.add_argument("--cache", default=".entsoe_cache")
    ap.add_argument("--refresh", action="store_true", help="Ignorera cache")
    ap.add_argument("--gen-proxy", action="store_true",
                    help="Använd högsta producerad effekt som proxy när installerad kapacitet saknas")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")

    this_year = pd.Timestamp.now(tz=TZ).year
    years = args.years or list(range(this_year - 4, this_year + 1))
    zones = args.zones or (NORDIC_ZONES + ([] if args.no_reference else REFERENCE_ZONES))

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    cache_dir = Path(args.cache)
    ensure_bess_template(out_dir / "bess_input.csv", zones, years)

    client = get_client()
    rows = []
    for zone in zones:
        for year in years:
            LOG.info("Hämtar %s %d ...", zone, year)
            load = fetch_load(client, zone, year, cache_dir, args.refresh)
            prices = fetch_prices(client, zone, year, cache_dir, args.refresh)
            inst = fetch_installed(client, zone, year, cache_dir, args.refresh)
            if args.gen_proxy and (np.isnan(inst["solar_mw"]) or np.isnan(inst["wind_mw"])):
                proxy = fetch_gen_proxy(client, zone, year, cache_dir, args.refresh)
                for k in inst:
                    if np.isnan(inst[k]):
                        inst[k] = proxy[k]
                        inst["capacity_is_proxy"] = True

            row = {"zone": zone, "year": year, "partial_year": year == this_year}
            row.update(load_metrics(load))
            row.update(inst)
            row.update(price_metrics(prices))
            rows.append(row)

    df = pd.DataFrame(rows)
    if "capacity_is_proxy" not in df.columns:
        df["capacity_is_proxy"] = False
    df["capacity_is_proxy"] = df["capacity_is_proxy"].fillna(False)
    df = merge_bess(df, out_dir / "bess_input.csv")

    path = out_dir / "zone_year_metrics.csv"
    df.to_csv(path, index=False, float_format="%.3f")
    LOG.info("Klart: %s (%d rader)", path, len(df))

    with pd.option_context("display.width", 200, "display.max_columns", 30):
        cols = ["zone", "year", "peak_load_mw", "solar_mw", "wind_mw", "neg_hours", "spread_2h", "spread_4h"]
        print(df[cols].round(1).to_string(index=False))

    print(
        "\nObs:\n"
        " - Innevarande år är ofullständigt (partial_year=True): topplast och negativa timmar är underskattade.\n"
        " - Spreadar är brutto (inga förluster, avgifter eller prognosfel) och bygger på timmedel av dagen-före-pris.\n"
        " - capacity_is_proxy=True betyder att sol/vind är högsta producerad effekt, inte installerad kapacitet.\n"
        " - Fyll i out/bess_input.csv (MW och MWh, endast front-of-the-meter) och kör igen för BESS-kvoterna."
    )


if __name__ == "__main__":
    main()
