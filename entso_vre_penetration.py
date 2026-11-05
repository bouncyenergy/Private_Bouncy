#!/usr/bin/env python3
"""
entso_vre_penetration.py
========================
Mäter hur stor andel väderberoende kraft (vind + sol) är i förhållande till elanvändningen i varje elområde,
enbart med data från ENTSO-E Transparency Platform. Använder faktisk produktion och last, så den fungerar även
för zoner där installerad kapacitet inte rapporteras.

Per zon och år (vre_penetration.csv):
  energi      vind-, sol- och total andel av årsförbrukningen (%)
  toppnivå    99:e percentilen av timvis (vind+sol)/last, samt andel timmar där vind+sol >= 50 % / 100 % av lasten
  kapacitet   (99,9:e percentilen av vind+sol-produktionen) / topplast, en kapacitetsproxy utan installerad effekt
  flexbehov   residuallast = last - (vind+sol): lägsta residuallast, medelvärdet av dygnets variation (max-min)
              och största 3-timmarsförändring, allt som % av topplasten

Prissamband med Sverige (price_coupling.csv): för varje granne med kabel (och svenska zoner emellan) andelen timmar
med exakt samma dagen-före-pris och medelvärdet av absolut prisskillnad.

Återanvänder klient, cache och omförsökslogik från entso_bess_context.py (lägg skripten i samma mapp).

    export ENTSOE_TOKEN="..."
    python entso_vre_penetration.py --years 2024 2025 2026 --out data/saturation
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

import entso_bess_context as ctx  # klient, cache, retry, fetch_load, fetch_prices

LOG = logging.getLogger("vre")
PSR = {"wind_on": "B19", "wind_off": "B18", "solar": "B16"}
ZONES = ctx.NORDIC_ZONES + ctx.CABLE_AND_BALTIC_ZONES + ctx.REFERENCE_ZONES

# (granne, svensk zon): direktkabel enligt tidigare genomgång, samt svenska zoner emellan
PAIRS = [
    ("DE_LU", "SE_4"), ("PL", "SE_4"), ("LT", "SE_4"), ("DK_2", "SE_4"),
    ("DK_1", "SE_3"), ("FI", "SE_3"), ("NO_1", "SE_3"),
    ("FI", "SE_1"), ("NO_4", "SE_1"), ("NO_4", "SE_2"), ("NO_3", "SE_2"),
    ("SE_1", "SE_2"), ("SE_2", "SE_3"), ("SE_3", "SE_4"),
]


def pick_actual(obj) -> pd.Series | None:
    """entsoe-py returnerar DataFrame (ofta MultiIndex-kolumner). Välj 'Actual Aggregated', annars första kolumnen."""
    if obj is None:
        return None
    if isinstance(obj, pd.Series):
        return obj.dropna()
    if not isinstance(obj, pd.DataFrame) or obj.shape[1] == 0:
        return None
    cols = list(obj.columns)
    agg = [c for c in cols if "Aggregated" in str(c)]
    chosen = agg[0] if agg else cols[0]
    s = obj[chosen]
    if isinstance(s, pd.DataFrame):  # dubblettkolumner
        s = s.iloc[:, 0]
    return s.dropna()


def fetch_gen(client, zone: str, psr: str, year: int, cache_dir: Path, refresh: bool) -> pd.Series | None:
    start, end = ctx.year_window(year)
    if end <= start:
        return None

    def loader():
        return ctx.retry(lambda: client.query_generation(zone, start=start, end=end, psr_type=psr),
                         label=f"produktion {psr} {zone} {year}")

    obj = ctx.cached(cache_dir, f"gen_{zone}_{psr}_{year}", ctx.stale(year, refresh), loader)
    s = pick_actual(obj)
    return None if s is None or len(s) == 0 else ctx.hourly(s)


def vre_metrics(load: pd.Series, wind: pd.Series | None, solar: pd.Series | None) -> dict | None:
    """Beräknar penetrationsmått från timserier (MW). Returnerar None om underlaget är för litet."""
    df = pd.DataFrame({"load": load, "wind": wind, "solar": solar})
    df["vre"] = df[["wind", "solar"]].sum(axis=1, min_count=1)
    df = df[(df["load"] > 0) & df["vre"].notna()]
    if len(df) < 24 * 7:
        return None
    peak = df["load"].max()
    ratio = df["vre"] / df["load"]
    resid = df["load"] - df["vre"]
    daily = resid.groupby(resid.index.date).agg(["max", "min", "count"])
    daily = daily[daily["count"] >= 20]
    wsum = df["wind"].sum() if "wind" in df and df["wind"].notna().any() else 0.0
    ssum = df["solar"].sum() if "solar" in df and df["solar"].notna().any() else 0.0
    lsum = df["load"].sum()
    ramp = resid.diff(3).abs().dropna()
    return {
        "load_peak_mw": float(peak), "load_mean_mw": float(df["load"].mean()),
        "wind_share_pct": 100 * wsum / lsum, "solar_share_pct": 100 * ssum / lsum, "vre_share_pct": 100 * (wsum + ssum) / lsum,
        "vre_p99_pct": 100 * float(ratio.quantile(0.99)), "vre_max_pct": 100 * float(ratio.max()),
        "hours_vre_ge50_pct": 100 * float((ratio >= 0.5).mean()), "hours_vre_ge100_pct": 100 * float((ratio >= 1.0).mean()),
        "vre_peak_mw": float(df["vre"].quantile(0.999)), "vre_peak_to_load_peak_pct": 100 * float(df["vre"].quantile(0.999)) / peak,
        "resid_min_pct_of_peak": 100 * float(resid.min()) / peak,
        "resid_swing_pct_of_peak": 100 * float((daily["max"] - daily["min"]).mean()) / peak if len(daily) else np.nan,
        "ramp3h_p99_pct_of_peak": 100 * float(ramp.quantile(0.99)) / peak if len(ramp) else np.nan,
        "hours": int(len(df)),
    }


def coupling_metrics(a: pd.Series | None, b: pd.Series | None) -> dict | None:
    if a is None or b is None:
        return None
    d = pd.DataFrame({"a": ctx.hourly(a), "b": ctx.hourly(b)}).dropna()
    if len(d) < 24 * 7:
        return None
    diff = (d["a"] - d["b"]).abs()
    return {"equal_price_pct": 100 * float((diff < 0.01).mean()), "mean_abs_diff": float(diff.mean()), "hours": int(len(d))}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--zones", nargs="+", default=None)
    ap.add_argument("--years", nargs="+", type=int, default=None, help="Standard: de tre senaste åren")
    ap.add_argument("--out", default="data/saturation")
    ap.add_argument("--cache", default=".entsoe_cache")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--refresh", action="store_true")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    LOG.setLevel(logging.DEBUG if args.verbose else logging.INFO)

    this_year = pd.Timestamp.now(tz=ctx.TZ).year
    years = args.years or [this_year - 2, this_year - 1, this_year]
    zones = args.zones or ZONES
    out_dir = Path(args.out); out_dir.mkdir(parents=True, exist_ok=True)
    cache_dir = Path(args.cache)
    ctx.get_client()  # validerar token direkt
    from concurrent.futures import ThreadPoolExecutor

    def zone_job(zone: str):
        client = ctx.get_client(); rows, fails = [], 0
        for year in years:
            t0 = time.time()
            try:
                load = ctx.to_series(ctx.fetch_load(client, zone, year, cache_dir, args.refresh))
                if load is None:
                    LOG.warning("%s %d: ingen last", zone, year); continue
                won = fetch_gen(client, zone, PSR["wind_on"], year, cache_dir, args.refresh)
                woff = fetch_gen(client, zone, PSR["wind_off"], year, cache_dir, args.refresh)
                sol = fetch_gen(client, zone, PSR["solar"], year, cache_dir, args.refresh)
                wind = None
                if won is not None or woff is not None:
                    wind = pd.concat([x for x in (won, woff) if x is not None], axis=1).sum(axis=1, min_count=1)
                m = vre_metrics(ctx.hourly(load), wind, sol)
                if m is None:
                    LOG.warning("%s %d: för lite data för penetrationsmått", zone, year); continue
                m.update({"zone": zone, "year": year, "partial_year": year == this_year, "has_wind": wind is not None, "has_solar": sol is not None})
                rows.append(m)
            except Exception as exc:
                fails += 1; LOG.error("Misslyckades för %s %d (%s: %s)", zone, year, type(exc).__name__, ctx._clean(exc, 300))
            LOG.info("%s %d klar på %.0fs", zone, year, time.time() - t0)
        return rows, fails

    LOG.info("Penetration: %d zoner x %d år, %d trådar", len(zones), len(years), args.workers)
    rows, nfail = [], 0
    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as ex:
        for r, f in ex.map(zone_job, zones):
            rows.extend(r); nfail += f
    if not rows:
        sys.exit("Inga penetrationsmått kunde beräknas.")
    df = pd.DataFrame(rows).sort_values(["year", "zone"])
    cols = ["zone", "year", "partial_year", "has_wind", "has_solar", "load_peak_mw", "load_mean_mw", "wind_share_pct", "solar_share_pct", "vre_share_pct",
            "vre_p99_pct", "vre_max_pct", "hours_vre_ge50_pct", "hours_vre_ge100_pct", "vre_peak_mw", "vre_peak_to_load_peak_pct",
            "resid_min_pct_of_peak", "resid_swing_pct_of_peak", "ramp3h_p99_pct_of_peak", "hours"]
    df[cols].to_csv(out_dir / "vre_penetration.csv", index=False, float_format="%.2f")
    LOG.info("Skrev %s (%d rader, %d misslyckade)", out_dir / "vre_penetration.csv", len(df), nfail)

    # ---- prissamband med Sverige ----
    def pair_job(item):
        (nb, se), year = item
        client = ctx.get_client()
        try:
            a = ctx.to_series(ctx.fetch_prices(client, nb, year, cache_dir, args.refresh))
            b = ctx.to_series(ctx.fetch_prices(client, se, year, cache_dir, args.refresh))
            m = coupling_metrics(a, b)
            return None if m is None else {"zone": nb, "se_zone": se, "year": year, **m}
        except Exception as exc:
            LOG.error("Prissamband %s-%s %d misslyckades (%s)", nb, se, year, ctx._clean(exc, 200)); return None

    items = [(p, y) for p in PAIRS for y in years]
    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as ex:
        pr = [r for r in ex.map(pair_job, items) if r]
    if pr:
        pd.DataFrame(pr).sort_values(["year", "se_zone", "zone"]).to_csv(out_dir / "price_coupling.csv", index=False, float_format="%.2f")
        LOG.info("Skrev %s (%d rader)", out_dir / "price_coupling.csv", len(pr))

    with pd.option_context("display.width", 200, "display.max_columns", 20):
        last = df[df["year"] == df["year"].max()]
        print(last[["zone", "year", "vre_share_pct", "vre_p99_pct", "hours_vre_ge100_pct", "resid_swing_pct_of_peak"]].round(1).to_string(index=False))
    print("\nObs: produktionsdata för sol och vind är det ENTSO-E-rapporterade och kan sakna småskalig sol bakom mätaren; "
          "has_wind/has_solar=False betyder att zonen saknar den serien, och då är andelen en nedre gräns.")


if __name__ == "__main__":
    main()
