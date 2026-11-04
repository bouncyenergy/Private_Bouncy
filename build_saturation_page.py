#!/usr/bin/env python3
"""
build_saturation_page.py
========================
Läser zone_year_metrics.csv (från entso_bess_context.py) och skriver en
självbärande HTML-sida, saturation.html, med diagram per elområde och
knappar för att välja vilka elområden som visas.

    python build_saturation_page.py --csv data/saturation/zone_year_metrics.csv --out viewer/saturation.html
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
    --se: #1f6feb; --cable: #1a9e75; --other: #9aa4b2;
  }
  @media (prefers-color-scheme: dark) {
    :root { --bg: #11151c; --fg: #e8ecf2; --muted: #9aa4b2; --card: #1a202b; --line: #2b3342;
            --se: #5b9bff; --cable: #3cc79b; --other: #6b7686; }
  }
  * { box-sizing: border-box; }
  body { margin: 0; background: var(--bg); color: var(--fg);
         font-family: 'Inter', system-ui, -apple-system, 'Segoe UI', sans-serif; line-height: 1.5; }
  main { max-width: 1100px; margin: 0 auto; padding: 24px 16px 48px; }
  h1, h2 { font-family: 'Space Grotesk', 'Inter', system-ui, sans-serif; margin: 0 0 8px; }
  h1 { font-size: 1.8rem; } h2 { font-size: 1.15rem; }
  p.lead { color: var(--muted); margin: 0 0 20px; max-width: 780px; }
  .panel { background: var(--card); border: 1px solid var(--line); border-radius: 10px; padding: 14px 16px; margin-bottom: 16px; }
  .row { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; }
  .row + .row { margin-top: 10px; }
  .label { color: var(--muted); font-size: .8rem; min-width: 64px; }
  select, button { font: inherit; font-size: .85rem; }
  select { padding: 6px 10px; border: 1px solid var(--line); border-radius: 6px; background: var(--bg); color: var(--fg); }
  .preset { padding: 4px 10px; border: 1px solid var(--line); border-radius: 6px; background: var(--bg); color: var(--fg); cursor: pointer; }
  .preset:hover { border-color: var(--muted); }
  .chip { padding: 4px 12px; border-radius: 999px; border: 1.5px solid var(--c); background: transparent; color: var(--fg); cursor: pointer; }
  .chip[aria-pressed="true"] { background: var(--c); color: #fff; }
  .chip[data-g="se"] { --c: var(--se); } .chip[data-g="cable"] { --c: var(--cable); } .chip[data-g="other"] { --c: var(--other); }
  .legend span.dot { display: inline-block; width: 10px; height: 10px; border-radius: 2px; margin: 0 4px 0 14px; vertical-align: -1px; }
  .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(480px, 1fr)); gap: 16px; }
  @media (max-width: 560px) { .grid { grid-template-columns: 1fr; } }
  .card { background: var(--card); border: 1px solid var(--line); border-radius: 10px; padding: 16px; }
  .card p { color: var(--muted); font-size: .85rem; margin: 0 0 10px; }
  .chart-wrap { position: relative; height: 300px; }
  .empty { color: var(--muted); font-size: .9rem; padding: 40px 12px; text-align: center; }
  .tablewrap { overflow-x: auto; }
  table { border-collapse: collapse; width: 100%; font-size: .85rem; }
  th, td { text-align: right; padding: 6px 10px; border-bottom: 1px solid var(--line); white-space: nowrap; }
  th:first-child, td:first-child { text-align: left; }
  td.note { white-space: normal; min-width: 280px; text-align: left; color: var(--muted); font-size: .8rem; }
  th:last-child { text-align: left; }
  footer { color: var(--muted); font-size: .8rem; margin-top: 28px; }
</style>
</head>
<body>
<main>
  <h1>BESS market saturation by bidding zone</h1>
  <p class="lead">Market conditions that drive battery revenues in each price area, and how much battery capacity
  is already installed relative to system size. Covers Sweden, the neighbours with a direct cable to Sweden, and the Baltics.</p>

  <div class="panel">
    <div class="row">
      <span class="label">Year</span><select id="year"></select>
      <span class="legend"><span class="dot" style="background:var(--se)"></span>Sweden
        <span class="dot" style="background:var(--cable)"></span>Direct cable to Sweden
        <span class="dot" style="background:var(--other)"></span>Other</span>
    </div>
    <div class="row">
      <span class="label">Zones</span><div class="row" id="zones" style="gap:6px"></div>
    </div>
    <div class="row">
      <span class="label">Presets</span><div class="row" id="presets" style="gap:6px"></div>
    </div>
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
      <h2>Installed wind and solar as % of peak load</h2>
      <p>Installed capacity relative to the zone's highest hourly load. Above 100 % means wind and solar together could
         exceed the highest demand, a rough measure of how much flexibility the system needs.</p>
      <div class="chart-wrap" id="vre_wrap"><canvas id="c_vre"></canvas></div>
      <div class="empty" id="vre_empty" style="display:none">No installed wind and solar capacity in the data for the selected zones and year.
        ENTSO-E may not report it for every zone; run the workflow manually with the proxy option to estimate it from peak output.</div>
    </div>
    <div class="card">
      <h2>BESS as % of peak load</h2>
      <p>Solid bars: installed front-of-the-meter battery power. Outlined bars: batteries prequalified for reserve
         markets (a proxy; where available it can be higher or lower than installed).</p>
      <div class="chart-wrap" id="bess_wrap"><canvas id="c_bess"></canvas></div>
      <div class="empty" id="bess_empty" style="display:none">No BESS capacity entered for the selected zones and year yet.
        Add MW and MWh per zone in <code>data/saturation/bess_input.csv</code> and re-run the workflow.</div>
    </div>
  </div>

  <div id="preq_section" style="display:none">
    <h2 style="margin:28px 0 4px">Sweden: batteries in the reserve markets</h2>
    <p class="lead" style="margin-bottom:12px">Volumes prequalified by Svenska kraftnät, national, 1 January each year and 1 October 2026.
      Prequalified is not the same as installed or bidding: one battery can be prequalified for several products at once.</p>
    <div class="grid">
      <div class="card">
        <h2>Battery storage prequalified (MW)</h2>
        <p>Technology category "Energilager" only. Combinations with hydro or wind are not included.</p>
        <div class="chart-wrap"><canvas id="c_preq_mw"></canvas></div>
      </div>
      <div class="card">
        <h2>Battery share of all prequalified volume (%)</h2>
        <p>Batteries relative to all technologies, per product. A high share means the market is already battery-driven.</p>
        <div class="chart-wrap"><canvas id="c_preq_share"></canvas></div>
      </div>
    </div>
    <div class="card tablewrap" style="margin-top:16px">
      <h2>Prequalified volume by bidding zone, all technologies (MW)</h2>
      <p id="preq_zone_date"></p>
      <table id="tbl_zone"></table>
    </div>
  </div>

  <div id="fcr_section" style="display:none">
    <h2 style="margin:28px 0 4px">Sweden: FCR procurement (Svenska kraftnät Mimer)</h2>
    <p class="lead" style="margin-bottom:12px">What Svenska kraftnät actually buys, and at what price: hourly marginal prices and procured
      volumes, averaged per month. The latest month is month-to-date.</p>
    <div class="grid">
      <div class="card">
        <h2>FCR marginal price (EUR/MW)</h2>
        <p>Monthly average of hourly marginal prices. Falling prices while battery volume grows point to saturation.</p>
        <div class="chart-wrap"><canvas id="c_fcr_price"></canvas></div>
      </div>
      <div class="card" id="fcr_ratio_card">
        <h2>Battery-prequalified volume / procured volume</h2>
        <p>Prequalified battery MW divided by average procured MW in SE1-SE4 that month. Above 1 means batteries alone could cover the whole need.</p>
        <div class="chart-wrap"><canvas id="c_fcr_ratio"></canvas></div>
      </div>
    </div>
  </div>

  <div id="am_section" style="display:none">
    <h2 style="margin:28px 0 4px">Sweden: aFRR and mFRR capacity markets (Svenska kraftnät Data Service)</h2>
    <p class="lead" style="margin-bottom:12px">Volume-weighted marginal prices and procured capacity, monthly. Svenska kraftnät only publishes hours
      with procurement in Sweden, so averages cover published hours, not every hour of the month.</p>
    <div class="grid">
      <div class="card">
        <h2>aFRR and mFRR capacity price (EUR/MW)</h2>
        <p>Volume-weighted monthly average of marginal prices.</p>
        <div class="chart-wrap"><canvas id="c_am_price"></canvas></div>
      </div>
      <div class="card" id="am_ratio_card">
        <h2>Battery-prequalified volume / procured volume</h2>
        <p>Prequalified battery MW divided by the average procured MW per published hour that month.</p>
        <div class="chart-wrap"><canvas id="c_am_ratio"></canvas></div>
      </div>
    </div>
  </div>

  <div class="card" style="margin-top:16px">
    <h2>Spread over time (4 h, EUR/MWh)</h2>
    <p>Same scale for all selected zones. The current year is year-to-date.</p>
    <div class="chart-wrap" style="height:340px"><canvas id="c_trend"></canvas></div>
  </div>

  <div class="card tablewrap" style="margin-top:16px">
    <h2>Data</h2>
    <table id="tbl"></table>
  </div>

  <footer>Source: ENTSO-E Transparency Platform (load, day-ahead prices, installed capacity). Installed BESS from
  TSO and market reports entered manually. Spreads are gross and use hourly averages; partial years are year-to-date.
  Direct cable to Sweden: NO1, NO3, NO4, FI, DK1, DK2, DE-LU, PL, LT. EE and LV are included as part of the Baltics but connect to Sweden indirectly.</footer>
</main>

<script>
const DATA = /*DATA*/;
const PREQ = /*PREQ*/;
const PREQZ = /*PREQZ*/;
const FCR = /*FCR*/;
const AM = /*AM*/;

const ORDER = ["SE_1","SE_2","SE_3","SE_4","NO_1","NO_3","NO_4","FI","DK_1","DK_2","DE_LU","PL","LT","EE","LV","NO_2","NO_5","NL","BE"];
const SE = ["SE_1","SE_2","SE_3","SE_4"];
const CABLE = ["NO_1","NO_3","NO_4","FI","DK_1","DK_2","DE_LU","PL","LT"];
const group = z => SE.includes(z) ? 'se' : CABLE.includes(z) ? 'cable' : 'other';
const label = z => z.replace('_', ' ');

const inData = [...new Set(DATA.map(d => d.zone))];
const ZONES = ORDER.filter(z => inData.includes(z)).concat(inData.filter(z => !ORDER.includes(z)));
const selected = new Set(ZONES);

const years = [...new Set(DATA.map(d => d.year))].sort();
const partial = new Set(DATA.filter(d => d.partial_year).map(d => d.year));
const sel = document.getElementById('year');
years.forEach(y => { const o = document.createElement('option'); o.value = y;
  o.textContent = y + (partial.has(y) ? ' (YTD)' : ''); sel.appendChild(o); });
sel.value = years[years.length - 1];

const css = n => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
const gcolor = z => css('--' + group(z));
const charts = {};

// ---- zone buttons ----
const zonesEl = document.getElementById('zones');
ZONES.forEach(z => {
  const b = document.createElement('button');
  b.className = 'chip'; b.dataset.g = group(z); b.dataset.z = z; b.textContent = label(z);
  b.setAttribute('aria-pressed', 'true');
  b.addEventListener('click', () => { selected.has(z) ? selected.delete(z) : selected.add(z); syncChips(); render(); });
  zonesEl.appendChild(b);
});
function syncChips() {
  zonesEl.querySelectorAll('.chip').forEach(b => b.setAttribute('aria-pressed', selected.has(b.dataset.z)));
}
const PRESETS = [
  ['All', () => ZONES],
  ['None', () => []],
  ['Sweden', () => ZONES.filter(z => SE.includes(z))],
  ['Cable to Sweden', () => ZONES.filter(z => SE.includes(z) || CABLE.includes(z))],
  ['Nordics', () => ZONES.filter(z => /^(SE|NO|DK)_|^FI$/.test(z))],
  ['Baltics', () => ZONES.filter(z => ['EE','LV','LT'].includes(z))],
];
const presetsEl = document.getElementById('presets');
PRESETS.forEach(([name, fn]) => {
  const b = document.createElement('button'); b.className = 'preset'; b.textContent = name;
  b.addEventListener('click', () => { selected.clear(); fn().forEach(z => selected.add(z)); syncChips(); render(); });
  presetsEl.appendChild(b);
});

// ---- charts ----
function barChart(id, rows, key, scale, fmt) {
  const labels = rows.map(r => label(r.zone));
  const vals = rows.map(r => r[key] == null ? null : r[key] * scale);
  const colors = rows.map(r => gcolor(r.zone));
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

function alpha(hex, a) {
  const h = hex.replace('#', '');
  const n = parseInt(h.length === 3 ? h.split('').map(c => c + c).join('') : h, 16);
  return 'rgba(' + ((n >> 16) & 255) + ',' + ((n >> 8) & 255) + ',' + (n & 255) + ',' + a + ')';
}
function bessChart(rows) {
  const id = 'c_bess';
  if (charts[id]) charts[id].destroy();
  charts[id] = new Chart(document.getElementById(id), {
    type: 'bar',
    data: { labels: rows.map(r => label(r.zone)), datasets: [
      { label: 'Installed', data: rows.map(r => r.bess_pct_of_peak == null ? null : r.bess_pct_of_peak),
        backgroundColor: rows.map(r => gcolor(r.zone)), borderRadius: 3 },
      { label: 'Prequalified (proxy)', data: rows.map(r => r.prequal_pct_of_peak == null ? null : r.prequal_pct_of_peak),
        backgroundColor: rows.map(r => alpha(gcolor(r.zone), 0.25)), borderColor: rows.map(r => gcolor(r.zone)),
        borderWidth: 2, borderRadius: 3 } ] },
    options: { responsive: true, maintainAspectRatio: false,
      plugins: { legend: { display: false },
                 tooltip: { callbacks: { label: c => c.parsed.y == null ? 'n/a' : c.dataset.label + ': ' + c.parsed.y.toFixed(1) + ' %' } } },
      scales: { y: { beginAtZero: true, grid: { color: css('--line') }, ticks: { color: css('--muted') } },
                x: { grid: { display: false }, ticks: { color: css('--muted'), maxRotation: 60 } } } }
  });
}

function bessReason(y) {
  const shown = d => d.bess_pct_of_peak != null || d.prequal_pct_of_peak != null;
  const raw = DATA.filter(d => d.bess_mw != null || d.prequal_bess_mw != null);
  if (!raw.length)
    return 'No BESS values were found in the data. Check that data/saturation/bess_input.csv has MW filled in, then re-run the workflow.';
  if (!DATA.some(shown))
    return 'BESS values exist, but there is no peak load for those zones and years, so the percentage cannot be computed. Check the ENTSO-E load fetch for them.';
  const yrs = [...new Set(DATA.filter(d => selected.has(d.zone) && shown(d)).map(d => d.year))].sort();
  if (!yrs.length)
    return 'No BESS data for the selected zones in any year. Data exists for: ' +
      [...new Set(DATA.filter(shown).map(d => d.zone.replace('_', ' ')))].join(', ') + '.';
  return 'No BESS data for ' + y + ' in the selected zones. Years with data for these zones: ' + yrs.join(', ') + '.';
}

function vreChart(rows) {
  const id = 'c_vre';
  if (charts[id]) charts[id].destroy();
  const has = rows.some(r => r.solar_pct_of_peak != null || r.wind_pct_of_peak != null);
  document.getElementById('vre_empty').style.display = has ? 'none' : 'block';
  document.getElementById('vre_wrap').style.display = has ? 'block' : 'none';
  if (!has) return;
  const pick = (r, k) => r[k] == null ? null : r[k];
  charts[id] = new Chart(document.getElementById(id), {
    type: 'bar',
    data: { labels: rows.map(r => label(r.zone)), datasets: [
      { label: 'Wind', data: rows.map(r => pick(r, 'wind_pct_of_peak')), backgroundColor: '#0a7d8c', stack: 's' },
      { label: 'Solar', data: rows.map(r => pick(r, 'solar_pct_of_peak')), backgroundColor: '#e0a31f', stack: 's' } ] },
    options: { responsive: true, maintainAspectRatio: false,
      plugins: { legend: { position: 'bottom', labels: { color: css('--muted'), boxWidth: 12 } },
                 tooltip: { callbacks: { label: c => c.parsed.y == null ? c.dataset.label + ': n/a' :
                   c.dataset.label + ': ' + c.parsed.y.toFixed(0) + ' % of peak' + (rows[c.dataIndex].capacity_is_proxy ? ' (estimated from peak output)' : '') } } },
      scales: { y: { stacked: true, beginAtZero: true, grid: { color: css('--line') }, ticks: { color: css('--muted'), callback: v => v + '%' } },
                x: { stacked: true, grid: { display: false }, ticks: { color: css('--muted'), maxRotation: 60 } } } }
  });
}

function render() {
  const y = Number(sel.value);
  const rows = ZONES.filter(z => selected.has(z))
    .map(z => DATA.find(d => d.zone === z && d.year === y) || { zone: z, year: y });
  barChart('c_neg', rows, 'neg_hours', 1, v => Math.round(v) + ' h');
  barChart('c_spread', rows, 'spread_4h', 1, v => v.toFixed(1) + ' EUR/MWh');
  barChart('c_peak', rows, 'peak_load_mw', 0.001, v => v.toFixed(1) + ' GW');
  vreChart(rows);
  const hasBess = rows.some(r => r.bess_pct_of_peak != null || r.prequal_pct_of_peak != null);
  if (!hasBess) document.getElementById('bess_empty').textContent = bessReason(y);
  document.getElementById('bess_empty').style.display = hasBess ? 'none' : 'block';
  document.getElementById('bess_wrap').style.display = hasBess ? 'block' : 'none';
  if (hasBess) bessChart(rows);
  renderTable(rows);
  trend();
}

function renderTable(rows) {
  const cols = [['zone','Zone',v=>label(v)],['peak_load_mw','Peak load (MW)',v=>Math.round(v)],
    ['solar_mw','Solar (MW)',v=>Math.round(v)],['wind_mw','Wind (MW)',v=>Math.round(v)],
    ['neg_hours','Neg. hours',v=>Math.round(v)],['mean_price','Mean price',v=>v.toFixed(1)],
    ['spread_2h','Spread 2h',v=>v.toFixed(1)],['spread_4h','Spread 4h',v=>v.toFixed(1)],
    ['bess_mw','BESS (MW)',v=>Math.round(v)],['bess_mwh','BESS (MWh)',v=>Math.round(v)],
    ['bess_pct_of_peak','BESS % of peak',v=>v.toFixed(1)],['vre_pct_of_peak','Wind+solar % of peak',v=>Math.round(v)],['bess_pct_of_vre','BESS % of wind+solar',v=>v.toFixed(1)],
    ['prequal_bess_mw','Prequal. BESS (MW)',v=>Math.round(v)],
    ['prequal_pct_of_peak','Prequal. % of peak',v=>v.toFixed(1)],['bess_note','BESS source / note',v=>v,'note']];
  const t = document.getElementById('tbl');
  t.innerHTML = '<tr>' + cols.map(c => '<th>' + c[1] + '</th>').join('') + '</tr>' +
    rows.map(r => '<tr>' + cols.map(c => '<td' + (c[3] ? ' class="note"' : '') + '>' + (r[c[0]] == null ? '–' : c[2](r[c[0]])) + '</td>').join('') + '</tr>').join('');
}

const PALETTE = ['#1f6feb','#e07a1f','#2da44e','#bf3989','#8250df','#cf222e','#0a7d8c','#9a6700','#57606a','#0550ae',
                 '#a40e26','#116329','#6e7781','#953800','#1b7c83','#7d4e57','#d4a72c','#4c2889','#2b6a99'];
function trend() {
  const zs = ZONES.filter(z => selected.has(z));
  const datasets = zs.map(z => {
    const c = PALETTE[ZONES.indexOf(z) % PALETTE.length];
    return { label: label(z), borderColor: c, backgroundColor: c, tension: .2, pointRadius: 3,
      borderDash: group(z) === 'other' ? [5,4] : [],
      data: years.map(y => { const r = DATA.find(d => d.zone === z && d.year === y); return r && r.spread_4h != null ? r.spread_4h : null; }) };
  });
  if (charts.trend) charts.trend.destroy();
  charts.trend = new Chart(document.getElementById('c_trend'), {
    type: 'line', data: { labels: years.map(y => partial.has(y) ? y + ' YTD' : String(y)), datasets },
    options: { responsive: true, maintainAspectRatio: false, spanGaps: true,
      plugins: { legend: { position: 'bottom', labels: { color: css('--muted'), boxWidth: 12 } } },
      scales: { y: { beginAtZero: true, grid: { color: css('--line') }, ticks: { color: css('--muted') } },
                x: { grid: { display: false }, ticks: { color: css('--muted') } } } }
  });
}


// ---- Sweden: prequalified reserves ----
function preqSection() {
  if (!PREQ.length) return;
  document.getElementById('preq_section').style.display = 'block';
  const dates = [...new Set(PREQ.map(d => d.date))].sort();
  const fmtDate = d => d.slice(0, 7) === '2023-01' ? 'Jan 2023' : new Date(d).toLocaleDateString('en-GB', { month: 'short', year: 'numeric' });
  const prods = ['FFR','FCR-N','FCR-D up','FCR-D down','aFRR up','mFRR up'];
  const colors = ['#e07a1f','#1f6feb','#2da44e','#0a7d8c','#bf3989','#8250df'];
  const mw = (t, p, d) => { const r = PREQ.find(x => x.technology === t && x.product === p && x.date === d); return r ? r.mw : null; };
  const total = (p, d) => { const rs = PREQ.filter(x => x.product === p && x.date === d); return rs.length ? rs.reduce((a, r) => a + r.mw, 0) : null; };

  const line = (id, fn, fmt) => {
    if (charts[id]) charts[id].destroy();
    charts[id] = new Chart(document.getElementById(id), {
      type: 'line',
      data: { labels: dates.map(fmtDate), datasets: prods.map((p, i) => ({
        label: p, borderColor: colors[i], backgroundColor: colors[i], tension: .2, pointRadius: 3, spanGaps: false,
        data: dates.map(d => fn(p, d)) })) },
      options: { responsive: true, maintainAspectRatio: false,
        plugins: { legend: { position: 'bottom', labels: { color: css('--muted'), boxWidth: 12 } },
                   tooltip: { callbacks: { label: c => c.parsed.y == null ? c.dataset.label + ': n/a' : c.dataset.label + ': ' + fmt(c.parsed.y) } } },
        scales: { y: { beginAtZero: true, grid: { color: css('--line') }, ticks: { color: css('--muted') } },
                  x: { grid: { display: false }, ticks: { color: css('--muted') } } } }
    });
  };
  line('c_preq_mw', (p, d) => mw('Battery storage', p, d), v => Math.round(v) + ' MW');
  line('c_preq_share', (p, d) => { const b = mw('Battery storage', p, d), t = total(p, d); return b == null || !t ? null : 100 * b / t; }, v => v.toFixed(0) + ' %');

  if (PREQZ.length) {
    const d0 = PREQZ[0].date;
    document.getElementById('preq_zone_date').textContent = 'As of ' + d0 + ', rounded to nearest 10 MW. All technologies, so mostly hydro in SE1 and SE2.';
    const zs = ['SE_1','SE_2','SE_3','SE_4'];
    const head = '<tr><th>Product</th>' + zs.map(z => '<th>' + label(z) + '</th>').join('') + '</tr>';
    const body = prods.concat(['aFRR down','mFRR down']).map(p => '<tr><td>' + p + '</td>' + zs.map(z => {
      const r = PREQZ.find(x => x.zone === z && x.product === p); return '<td>' + (r ? r.mw.toLocaleString('en-GB') : '–') + '</td>'; }).join('') + '</tr>').join('');
    document.getElementById('tbl_zone').innerHTML = head + body;
  }
}

// ---- Sweden: FCR procurement from Mimer ----
function fcrSection() {
  if (!FCR.length) return;
  document.getElementById('fcr_section').style.display = 'block';
  const months = [...new Set(FCR.map(r => r.month))].sort();
  const prods = ['FCR-N', 'FCR-D up', 'FCR-D down'];
  const colors = ['#1f6feb', '#2da44e', '#e07a1f'];
  const val = (p, m, k) => { const r = FCR.find(x => x.product === p && x.month === m); return r && r[k] != null ? r[k] : null; };

  if (charts.fcr_price) charts.fcr_price.destroy();
  charts.fcr_price = new Chart(document.getElementById('c_fcr_price'), {
    type: 'line',
    data: { labels: months, datasets: prods.map((p, i) => ({
      label: p, borderColor: colors[i], backgroundColor: colors[i], tension: .2, pointRadius: 2,
      data: months.map(m => val(p, m, 'price_eur_mw')) })) },
    options: { responsive: true, maintainAspectRatio: false, spanGaps: true,
      plugins: { legend: { position: 'bottom', labels: { color: css('--muted'), boxWidth: 12 } },
                 tooltip: { callbacks: { label: c => c.parsed.y == null ? 'n/a' : c.dataset.label + ': ' + c.parsed.y.toFixed(1) + ' EUR/MW' } } },
      scales: { y: { beginAtZero: true, grid: { color: css('--line') }, ticks: { color: css('--muted') } },
                x: { grid: { display: false }, ticks: { color: css('--muted'), maxTicksLimit: 12 } } } }
  });

  const card = document.getElementById('fcr_ratio_card');
  const need = (p, m) => ['SE1', 'SE2', 'SE3', 'SE4'].reduce((a, z) => a + (val(p, m, 'vol_' + z) || 0), 0);
  const dates = [...new Set(PREQ.map(d => d.date))].sort().filter(d => months.includes(d.slice(0, 7)));
  if (!PREQ.length || !dates.length) { card.style.display = 'none'; return; }
  const bat = (p, d) => { const r = PREQ.find(x => x.technology === 'Battery storage' && x.product === p && x.date === d); return r ? r.mw : null; };
  if (charts.fcr_ratio) charts.fcr_ratio.destroy();
  charts.fcr_ratio = new Chart(document.getElementById('c_fcr_ratio'), {
    type: 'bar',
    data: { labels: dates, datasets: prods.map((p, i) => ({
      label: p, backgroundColor: colors[i], borderRadius: 3,
      data: dates.map(d => { const b = bat(p, d), n = need(p, d.slice(0, 7)); return b == null || !n ? null : b / n; }) })) },
    options: { responsive: true, maintainAspectRatio: false,
      plugins: { legend: { position: 'bottom', labels: { color: css('--muted'), boxWidth: 12 } },
                 tooltip: { callbacks: { label: c => c.parsed.y == null ? 'n/a' : c.dataset.label + ': ' + c.parsed.y.toFixed(2) + 'x' } } },
      scales: { y: { beginAtZero: true, grid: { color: css('--line') }, ticks: { color: css('--muted'), callback: v => v + 'x' } },
                x: { grid: { display: false }, ticks: { color: css('--muted') } } } }
  });
}

// ---- Sweden: aFRR / mFRR capacity markets from the SVK data portal ----
function amSection() {
  if (!AM.length) return;
  document.getElementById('am_section').style.display = 'block';
  const months = [...new Set(AM.map(r => r.month))].sort();
  const prods = ['aFRR up', 'aFRR down', 'mFRR up', 'mFRR down'];
  const colors = ['#bf3989', '#8250df', '#1f6feb', '#0a7d8c'];
  const val = (p, m, k) => { const r = AM.find(x => x.product === p && x.month === m); return r && r[k] != null ? r[k] : null; };

  if (charts.am_price) charts.am_price.destroy();
  charts.am_price = new Chart(document.getElementById('c_am_price'), {
    type: 'line',
    data: { labels: months, datasets: prods.map((p, i) => ({
      label: p, borderColor: colors[i], backgroundColor: colors[i], tension: .2, pointRadius: 2,
      data: months.map(m => val(p, m, 'price_eur_mw')) })) },
    options: { responsive: true, maintainAspectRatio: false, spanGaps: true,
      plugins: { legend: { position: 'bottom', labels: { color: css('--muted'), boxWidth: 12 } },
                 tooltip: { callbacks: { label: c => c.parsed.y == null ? 'n/a' : c.dataset.label + ': ' + c.parsed.y.toFixed(1) + ' EUR/MW' } } },
      scales: { y: { beginAtZero: true, grid: { color: css('--line') }, ticks: { color: css('--muted') } },
                x: { grid: { display: false }, ticks: { color: css('--muted'), maxTicksLimit: 12 } } } }
  });

  const card = document.getElementById('am_ratio_card');
  const dates = [...new Set(PREQ.map(d => d.date))].sort().filter(d => months.includes(d.slice(0, 7)));
  if (!PREQ.length || !dates.length) { card.style.display = 'none'; return; }
  const bat = (p, d) => { const r = PREQ.find(x => x.technology === 'Battery storage' && x.product === p && x.date === d); return r ? r.mw : null; };
  if (charts.am_ratio) charts.am_ratio.destroy();
  charts.am_ratio = new Chart(document.getElementById('c_am_ratio'), {
    type: 'bar',
    data: { labels: dates, datasets: prods.map((p, i) => ({
      label: p, backgroundColor: colors[i], borderRadius: 3,
      data: dates.map(d => { const b = bat(p, d), n = val(p, d.slice(0, 7), 'vol_total_mw'); return b == null || !n ? null : b / n; }) })) },
    options: { responsive: true, maintainAspectRatio: false,
      plugins: { legend: { position: 'bottom', labels: { color: css('--muted'), boxWidth: 12 } },
                 tooltip: { callbacks: { label: c => c.parsed.y == null ? 'n/a' : c.dataset.label + ': ' + c.parsed.y.toFixed(2) + 'x' } } },
      scales: { y: { beginAtZero: true, grid: { color: css('--line') }, ticks: { color: css('--muted'), callback: v => v + 'x' } },
                x: { grid: { display: false }, ticks: { color: css('--muted') } } } }
  });
}

sel.addEventListener('change', render);
syncChips(); render(); preqSection(); fcrSection(); amSection();
</script>
</body>
</html>
"""


BESS_COLS = ["bess_mw", "bess_mwh", "bess_pct_of_peak", "bess_note", "note", "prequal_bess_mw",
             "prequal_basis", "prequal_pct_of_peak", "bess_duration_h", "bess_pct_of_solar_wind"]


def merge_bess_input(df: pd.DataFrame, path: str) -> pd.DataFrame:
    """Läser BESS-filen direkt när sidan byggs och räknar andel av topplast. Det gör att en ändring i
    bess_input.csv slår igenom vid nästa bygge, även om ENTSO-E-datat är från en tidigare körning."""
    f = Path(path)
    if not f.exists():
        print(f"Obs: {path} saknas - BESS-diagrammet blir tomt.")
        return df
    b = pd.read_csv(f)
    for c in ("year", "bess_mw", "bess_mwh", "prequal_bess_mw"):
        if c in b.columns:
            b[c] = pd.to_numeric(b[c], errors="coerce")
    df = df.drop(columns=[c for c in BESS_COLS if c in df.columns])
    df["year"] = pd.to_numeric(df["year"], errors="coerce")
    cols = ["zone", "year"] + [c for c in ("bess_mw", "bess_mwh", "note", "prequal_bess_mw", "prequal_basis")
                               if c in b.columns]
    df = df.merge(b[cols].drop_duplicates(["zone", "year"], keep="last"), on=["zone", "year"], how="left")
    if "note" in df.columns:
        df = df.rename(columns={"note": "bess_note"})
    for c in ("bess_mw", "bess_mwh", "prequal_bess_mw"):
        if c not in df.columns:
            df[c] = None
    peak = df["peak_load_mw"]
    df["bess_pct_of_peak"] = 100 * df["bess_mw"] / peak
    df["prequal_pct_of_peak"] = 100 * df["prequal_bess_mw"] / peak
    n_inst, n_pre = int(df["bess_mw"].notna().sum()), int(df["prequal_bess_mw"].notna().sum())
    n_ok = int((df["bess_pct_of_peak"].notna() | df["prequal_pct_of_peak"].notna()).sum())
    print(f"BESS-fil: {n_inst} rader med installerat, {n_pre} med förkvalificerat; {n_ok} rader har topplast och kan visas.")
    return df


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", default="data/saturation/zone_year_metrics.csv")
    ap.add_argument("--out", default="viewer/saturation.html")
    ap.add_argument("--prequal-tech", default="data/saturation/se_prequalified_by_technology.csv")
    ap.add_argument("--prequal-zone", default="data/saturation/se_prequalified_by_zone.csv")
    ap.add_argument("--fcr", default="data/saturation/se_fcr_monthly.csv")
    ap.add_argument("--bess-input", default="data/saturation/bess_input.csv")
    ap.add_argument("--afrr-mfrr", default="data/saturation/se_afrr_mfrr_monthly.csv")
    args = ap.parse_args()

    df = pd.read_csv(args.csv)
    if "partial_year" in df.columns:
        df["partial_year"] = df["partial_year"].astype(str).str.lower().eq("true")
    else:
        df["partial_year"] = False

    df = merge_bess_input(df, args.bess_input)

    for c in ("solar_mw", "wind_mw"):
        df[c] = pd.to_numeric(df[c], errors="coerce") if c in df.columns else float("nan")
    if "capacity_is_proxy" not in df.columns:
        df["capacity_is_proxy"] = False
    df["capacity_is_proxy"] = df["capacity_is_proxy"].astype(str).str.lower().eq("true")
    if "bess_mw" not in df.columns:               # BESS-filen saknas: kolumnen måste ändå finnas
        df["bess_mw"] = float("nan")
    df["bess_mw"] = pd.to_numeric(df["bess_mw"], errors="coerce")
    vre = df["solar_mw"] + df["wind_mw"]          # NaN om någon av delarna saknas (undviker halv summa)
    df["solar_pct_of_peak"] = 100 * df["solar_mw"] / df["peak_load_mw"]
    df["wind_pct_of_peak"] = 100 * df["wind_mw"] / df["peak_load_mw"]
    df["vre_pct_of_peak"] = 100 * vre / df["peak_load_mw"]
    df["bess_pct_of_vre"] = 100 * df["bess_mw"] / vre
    print(f"Sol/vind: {int(vre.notna().sum())} av {len(df)} rader har både sol och vind.")

    keep = [
        "zone", "year", "partial_year", "peak_load_mw", "solar_mw", "wind_mw", "neg_hours", "mean_price",
        "spread_2h", "spread_4h", "bess_mw", "bess_mwh", "bess_pct_of_peak", "bess_note",
        "prequal_bess_mw", "prequal_pct_of_peak",
        "solar_pct_of_peak", "wind_pct_of_peak", "vre_pct_of_peak", "bess_pct_of_vre", "capacity_is_proxy",
    ]
    for c in keep:
        if c not in df.columns:
            df[c] = None
    payload = df[keep].to_json(orient="records").replace("</", "<\\/")

    def load_json(path, cols):
        f = Path(path)
        if not f.exists():
            return "[]"
        d = pd.read_csv(f)
        return d[cols].to_json(orient="records").replace("</", "<\\/")

    preq = load_json(args.prequal_tech, ["date", "technology", "product", "mw"])
    preqz = load_json(args.prequal_zone, ["date", "zone", "product", "mw"])
    fcr = load_json(args.fcr, ["month", "product", "price_eur_mw", "vol_total_mw",
                               "vol_SE1", "vol_SE2", "vol_SE3", "vol_SE4", "vol_DK2"])

    am = load_json(args.afrr_mfrr, ["month", "product", "price_eur_mw", "vol_total_mw",
                                    "vol_SE1", "vol_SE2", "vol_SE3", "vol_SE4"])

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    html = TEMPLATE.replace("/*DATA*/", payload).replace("/*PREQZ*/", preqz).replace("/*FCR*/", fcr).replace("/*AM*/", am).replace("/*PREQ*/", preq)
    out.write_text(html, encoding="utf-8")
    print(f"Skrev {out} ({len(df)} rader)")


if __name__ == "__main__":
    main()
