#!/usr/bin/env python3
"""
build_saturation_page.py
========================
Läser zone_year_metrics.csv (från entso_bess_context.py) och skriver en
självbärande HTML-sida, saturation.html, med diagram per elområde.

    python build_saturation_page.py --csv data/zone_year_metrics.csv --out saturation.html
"""

import argparse
from pathlib import Path

import pandas as pd

TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>BESS market saturation by bidding zone | Bouncy Energy</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500&family=Space+Grotesk:wght@500;700&display=swap" rel="stylesheet">
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"></script>
<style>
  :root {
    --bg: #ffffff; --fg: #1c2330; --muted: #5d6675; --card: #f5f7fa; --line: #dde2ea;
    --nordic: #1f6feb; --ref: #9aa4b2; --accent: #e07a1f;
  }
  @media (prefers-color-scheme: dark) {
    :root { --bg: #11151c; --fg: #e8ecf2; --muted: #9aa4b2; --card: #1a202b; --line: #2b3342;
            --nordic: #5b9bff; --ref: #6b7686; --accent: #f0983f; }
  }
  * { box-sizing: border-box; }
  body { margin: 0; background: var(--bg); color: var(--fg);
         font-family: 'Inter', system-ui, -apple-system, 'Segoe UI', sans-serif; line-height: 1.5; }
  main { max-width: 1100px; margin: 0 auto; padding: 24px 16px 48px; }
  h1, h2 { font-family: 'Space Grotesk', 'Inter', system-ui, sans-serif; margin: 0 0 8px; }
  h1 { font-size: 1.8rem; } h2 { font-size: 1.15rem; }
  p.lead { color: var(--muted); margin: 0 0 20px; max-width: 760px; }
  .controls { display: flex; gap: 12px; align-items: center; margin: 16px 0 20px; flex-wrap: wrap; }
  select { font: inherit; padding: 6px 10px; border: 1px solid var(--line); border-radius: 6px;
           background: var(--card); color: var(--fg); }
  .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(480px, 1fr)); gap: 16px; }
  @media (max-width: 560px) { .grid { grid-template-columns: 1fr; } }
  .card { background: var(--card); border: 1px solid var(--line); border-radius: 10px; padding: 16px; }
  .card p { color: var(--muted); font-size: .85rem; margin: 0 0 10px; }
  .chart-wrap { position: relative; height: 300px; }
  .empty { color: var(--muted); font-size: .9rem; padding: 40px 8px; text-align: center; }
  .tablewrap { overflow-x: auto; margin-top: 16px; }
  table { border-collapse: collapse; width: 100%; font-size: .85rem; }
  th, td { text-align: right; padding: 6px 10px; border-bottom: 1px solid var(--line); white-space: nowrap; }
  th:first-child, td:first-child { text-align: left; }
  footer { color: var(--muted); font-size: .8rem; margin-top: 28px; }
  .legend span { display: inline-block; width: 10px; height: 10px; border-radius: 2px; margin: 0 4px 0 12px; }
</style>
</head>
<body>
<main>
  <h1>BESS market saturation by bidding zone</h1>
  <p class="lead">Market conditions that drive battery revenues in each price area, and how much battery capacity
  is already installed relative to system size. Zones in grey are reference markets for comparison.</p>

  <div class="controls">
    <label for="year">Year:</label>
    <select id="year"></select>
    <span class="legend"><span style="background:var(--nordic)"></span>Nordic <span style="background:var(--ref)"></span>Reference</span>
  </div>

  <div class="grid">
    <div class="card">
      <h2>Negative-price hours</h2>
      <p>Hours per year with negative day-ahead prices (hourly average).</p>
      <div class="chart-wrap"><canvas id="c_neg"></canvas></div>
    </div>
    <div class="card">
      <h2>Average daily spread, 4 h (EUR/MWh)</h2>
      <p>Mean of the 4 highest hours minus the 4 lowest hours each day. Gross, before losses and fees.</p>
      <div class="chart-wrap"><canvas id="c_spread"></canvas></div>
    </div>
    <div class="card">
      <h2>Peak load (GW)</h2>
      <p>Highest hourly average load in the year.</p>
      <div class="chart-wrap"><canvas id="c_peak"></canvas></div>
    </div>
    <div class="card">
      <h2>Installed BESS as % of peak load</h2>
      <p>Front-of-the-meter battery power (MW) relative to peak load.</p>
      <div class="chart-wrap"><canvas id="c_bess"></canvas></div>
      <div class="empty" id="bess_empty" style="display:none">No BESS capacity data entered for this year yet.</div>
    </div>
  </div>

  <div class="card" style="margin-top:16px">
    <h2>Spread over time (4 h, EUR/MWh)</h2>
    <p>Same scale for all zones. The current year is year-to-date.</p>
    <div class="chart-wrap" style="height:340px"><canvas id="c_trend"></canvas></div>
  </div>

  <div class="card tablewrap" style="margin-top:16px">
    <h2>Data</h2>
    <table id="tbl"></table>
  </div>

  <footer>Source: ENTSO-E Transparency Platform (load, day-ahead prices, installed capacity). Installed BESS from
  TSO and market reports entered manually. Spreads are gross and use hourly averages; partial years are year-to-date.</footer>
</main>

<script>
const DATA = /*DATA*/;
const REF = new Set(["DE_LU","NL","BE","PL"]);
const years = [...new Set(DATA.map(d => d.year))].sort();
const partial = new Set(DATA.filter(d => d.partial_year).map(d => d.year));
const sel = document.getElementById('year');
years.forEach(y => { const o = document.createElement('option'); o.value = y;
  o.textContent = y + (partial.has(y) ? ' (YTD)' : ''); sel.appendChild(o); });
sel.value = years[years.length - 1];

const css = n => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
const charts = {};

function barChart(id, rows, key, scale, fmt) {
  const labels = rows.map(r => r.zone.replace('_', ' '));
  const vals = rows.map(r => r[key] == null ? null : r[key] * scale);
  const colors = rows.map(r => REF.has(r.zone) ? css('--ref') : css('--nordic'));
  if (charts[id]) charts[id].destroy();
  charts[id] = new Chart(document.getElementById(id), {
    type: 'bar',
    data: { labels, datasets: [{ data: vals, backgroundColor: colors, borderRadius: 3 }] },
    options: { responsive: true, maintainAspectRatio: false,
      plugins: { legend: { display: false },
                 tooltip: { callbacks: { label: c => c.parsed.y == null ? 'n/a' : fmt(c.parsed.y) } } },
      scales: { y: { beginAtZero: true, grid: { color: css('--line') }, ticks: { color: css('--muted') } },
                x: { grid: { display: false }, ticks: { color: css('--muted'), maxRotation: 60 } } } }
  });
}

function render() {
  const y = Number(sel.value);
  const rows = DATA.filter(d => d.year === y);
  barChart('c_neg', rows, 'neg_hours', 1, v => Math.round(v) + ' h');
  barChart('c_spread', rows, 'spread_4h', 1, v => v.toFixed(1) + ' EUR/MWh');
  barChart('c_peak', rows, 'peak_load_mw', 0.001, v => v.toFixed(1) + ' GW');
  const hasBess = rows.some(r => r.bess_pct_of_peak != null);
  document.getElementById('bess_empty').style.display = hasBess ? 'none' : 'block';
  document.getElementById('c_bess').parentElement.style.display = hasBess ? 'block' : 'none';
  if (hasBess) barChart('c_bess', rows, 'bess_pct_of_peak', 1, v => v.toFixed(1) + ' %');
  renderTable(rows);
}

function renderTable(rows) {
  const cols = [['zone','Zone',v=>v.replace('_',' ')],['peak_load_mw','Peak load (MW)',v=>Math.round(v)],
    ['solar_mw','Solar (MW)',v=>Math.round(v)],['wind_mw','Wind (MW)',v=>Math.round(v)],
    ['neg_hours','Neg. hours',v=>Math.round(v)],['mean_price','Mean price',v=>v.toFixed(1)],
    ['spread_2h','Spread 2h',v=>v.toFixed(1)],['spread_4h','Spread 4h',v=>v.toFixed(1)],
    ['bess_mw','BESS (MW)',v=>Math.round(v)],['bess_mwh','BESS (MWh)',v=>Math.round(v)],
    ['bess_pct_of_peak','BESS % of peak',v=>v.toFixed(1)]];
  const t = document.getElementById('tbl');
  t.innerHTML = '<tr>' + cols.map(c => '<th>' + c[1] + '</th>').join('') + '</tr>' +
    rows.map(r => '<tr>' + cols.map(c => '<td>' + (r[c[0]] == null ? '–' : c[2](r[c[0]])) + '</td>').join('') + '</tr>').join('');
}

function trend() {
  const zones = [...new Set(DATA.map(d => d.zone))];
  const palette = ['#1f6feb','#e07a1f','#2da44e','#bf3989','#8250df','#cf222e','#0a7d8c','#9a6700','#57606a','#0550ae','#a40e26','#116329','#6e7781','#953800','#1b7c83','#7d4e57'];
  const datasets = zones.map((z, i) => ({
    label: z.replace('_',' '), borderColor: palette[i % palette.length], backgroundColor: palette[i % palette.length],
    borderDash: REF.has(z) ? [5,4] : [], tension: .2, pointRadius: 3,
    data: years.map(y => { const r = DATA.find(d => d.zone === z && d.year === y); return r && r.spread_4h != null ? r.spread_4h : null; })
  }));
  new Chart(document.getElementById('c_trend'), {
    type: 'line', data: { labels: years.map(y => partial.has(y) ? y + ' YTD' : String(y)), datasets },
    options: { responsive: true, maintainAspectRatio: false, spanGaps: true,
      plugins: { legend: { position: 'bottom', labels: { color: css('--muted'), boxWidth: 12 } } },
      scales: { y: { beginAtZero: true, grid: { color: css('--line') }, ticks: { color: css('--muted') } },
                x: { grid: { display: false }, ticks: { color: css('--muted') } } } }
  });
}

sel.addEventListener('change', render);
render(); trend();
</script>
</body>
</html>
"""


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", default="data/zone_year_metrics.csv")
    ap.add_argument("--out", default="saturation.html")
    args = ap.parse_args()

    df = pd.read_csv(args.csv)
    if "partial_year" in df.columns:
        df["partial_year"] = df["partial_year"].astype(str).str.lower().eq("true")
    else:
        df["partial_year"] = False

    keep = [
        "zone", "year", "partial_year", "peak_load_mw", "solar_mw", "wind_mw", "neg_hours", "mean_price",
        "spread_2h", "spread_4h", "bess_mw", "bess_mwh", "bess_pct_of_peak",
    ]
    for c in keep:
        if c not in df.columns:
            df[c] = None
    payload = df[keep].to_json(orient="records").replace("</", "<\\/")

    html = TEMPLATE.replace("/*DATA*/", payload)
    Path(args.out).write_text(html, encoding="utf-8")
    print(f"Skrev {args.out} ({len(df)} rader)")


if __name__ == "__main__":
    main()
