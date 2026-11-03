// Growing-region and feedlot weather from Open-Meteo (no key): the last 30 days (analysis) and the next 16 days
// (forecast, a blend of national weather models), averaged over each region's points, against the 2010-2024 normals
// in data/weather-normals.json. One request covers every point.
import fs from 'node:fs';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {getJSON, round} from '../lib.mjs';
import {REGIONS, ALL_POINTS} from '../regions.mjs';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');
const PAST = 30, AHEAD = 16;
const HOT = 95, COLD = 10;   // °F: feedlot heat-stress highs and hard-freeze lows

const doyIdx = s => { const [, m, d] = s.split('-').map(Number); return Math.round((Date.UTC(2024, m - 1, d) - Date.UTC(2024, 0, 1)) / 864e5); };
const sum = a => a.reduce((s, x) => s + x, 0);
const mean = a => a.length ? sum(a) / a.length : null;

export async function load({now}) {
  let normals = null;
  try { normals = JSON.parse(fs.readFileSync(path.join(ROOT, 'data/weather-normals.json'), 'utf8')); } catch (e) {}
  const q = new URLSearchParams({
    latitude: ALL_POINTS.map(p => p.lat).join(','), longitude: ALL_POINTS.map(p => p.lon).join(','),
    daily: 'precipitation_sum,temperature_2m_max,temperature_2m_min', past_days: PAST, forecast_days: AHEAD,
    precipitation_unit: 'inch', temperature_unit: 'fahrenheit', timezone: 'GMT'});
  let res = await getJSON('https://api.open-meteo.com/v1/forecast?' + q, {timeout: 90});
  if (!Array.isArray(res)) res = [res];
  if (res.length !== ALL_POINTS.length) throw new Error(`expected ${ALL_POINTS.length} locations, got ${res.length}`);

  const today = now.toISOString().slice(0, 10), regions = [];
  for (const R of REGIONS) {
    const idx = ALL_POINTS.map((p, i) => p.region === R.id ? i : -1).filter(i => i >= 0);
    const days = res[idx[0]].daily.time;
    // region daily series = average of its points (a missing value at any point leaves that day out)
    const series = days.map((d, k) => {
      const vals = f => idx.map(i => res[i].daily[f][k]);
      const P = vals('precipitation_sum'), TX = vals('temperature_2m_max'), TN = vals('temperature_2m_min');
      if ([...P, ...TX, ...TN].some(v => v == null)) return null;
      const n = normals?.regions?.[R.id], j = doyIdx(d);
      return {d, fc: d >= today, p: round(mean(P), 3), tx: round(mean(TX), 1), tn: round(mean(TN), 1),
        np: n ? n.p[j] : null, ntx: n ? n.tx[j] : null, ntn: n ? n.tn[j] : null,
        hot: TX.filter(v => v >= HOT).length, cold: TN.filter(v => v <= COLD).length, pts: idx.length};
    }).filter(Boolean);
    const past = series.filter(x => !x.fc), fut = series.filter(x => x.fc);
    const win = (arr, from, to) => arr.slice(from, to);
    const stat = rows => {
      if (!rows.length) return null;
      const p = sum(rows.map(r => r.p)), np = rows.every(r => r.np != null) ? sum(rows.map(r => r.np)) : null;
      const t = mean(rows.map(r => (r.tx + r.tn) / 2)), nt = rows.every(r => r.ntx != null) ? mean(rows.map(r => (r.ntx + r.ntn) / 2)) : null;
      return {days: rows.length, from: rows[0].d, to: rows.at(-1).d, p: round(p, 2), np: round(np, 2), pPct: np ? Math.round(p / np * 100) : null,
        t: round(t, 1), tAnom: nt != null ? round(t - nt, 1) : null, tx: Math.round(Math.max(...rows.map(r => r.tx))), tn: Math.round(Math.min(...rows.map(r => r.tn))),
        hotDays: rows.filter(r => r.hot > 0).length, coldDays: rows.filter(r => r.cold > 0).length};
    };
    const m = now.getUTCMonth() + 1;
    regions.push({id: R.id, name: R.name, crops: R.crops, livestock: !!R.livestock, inSeason: R.season.includes(m),
      points: R.points.map(p => p[0]),
      last7: stat(win(past, -7)), last14: stat(win(past, -14)), last30: stat(past),
      next7: stat(win(fut, 0, 7)), next8_16: stat(win(fut, 7, 16)),
      series});
  }
  return {data: {regions, normals: normals ? {years: normals.years, built: normals.built} : null, hot: HOT, cold: COLD},
    latest: today, n: regions.length,
    note: normals ? '' : 'normals file missing: anomalies are blank (run scripts/build-normals.mjs)', partial: !normals,
    src: 'Open-Meteo forecast API (best-match model blend), normals from Open-Meteo ERA5 archive'};
}
