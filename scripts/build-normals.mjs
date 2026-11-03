// Builds data/weather-normals.json: day-of-year normals (2010-2024) for every region in scripts/regions.mjs, from the
// Open-Meteo historical archive (ERA5). Run by hand only when regions change: `node scripts/build-normals.mjs`.
// Open-Meteo's free tier counts a 15-year request as ~390 calls (limits: ~5,000/hour, ~10,000/day), so the raw
// per-point downloads are cached in .normals-cache/ and the script stops cleanly on HTTP 429: run it again an hour
// later and it picks up where it left off.
import fs from 'node:fs';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {REGIONS, ALL_POINTS} from './regions.mjs';
import {getText} from './lib.mjs';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const CACHE = path.join(ROOT, '.normals-cache');
const START = '2010-01-01', END = '2024-12-31', SMOOTH = 15;   // ±15 days around each day of year
const MAX_NEW = +(process.env.MAX_NEW || 99);                  // cap downloads per run (rate limits)

const key = p => `${p.lat.toFixed(2)}_${p.lon.toFixed(2)}`;
fs.mkdirSync(CACHE, {recursive: true});

let fetched = 0;
// three 5-year pieces per point: the same weighted cost, but small enough that the archive doesn't time out
const PIECES = [['2010-01-01', '2014-12-31'], ['2015-01-01', '2019-12-31'], ['2020-01-01', '2024-12-31']];
async function piece(p, [a, b]) {
  const u = `https://archive-api.open-meteo.com/v1/archive?latitude=${p.lat}&longitude=${p.lon}&start_date=${a}&end_date=${b}` +
    '&daily=precipitation_sum,temperature_2m_max,temperature_2m_min&precipitation_unit=inch&temperature_unit=fahrenheit&timezone=GMT';
  for (let tries = 0; tries < 16; tries++) {
    try {
      const j = JSON.parse(await getText(u, {timeout: 180, retries: 1}));   // a server timeout comes back as plain text
      if (!j.daily?.time?.length) throw new Error('no daily data');
      return j.daily;
    } catch (e) {
      if (process.env.WAIT === '0') throw e;
      const limited = /HTTP 429/.test(e.message);
      console.log(`${limited ? 'rate limited' : 'failed (' + e.message.slice(0, 80) + ')'} at ${p.name} ${a.slice(0, 4)}; waiting ${limited ? 5 : 1} minute(s)`);
      await new Promise(res => setTimeout(res, limited ? 300e3 : 60e3));
    }
  }
  return null;
}
for (const p of ALL_POINTS) {
  const f = path.join(CACHE, key(p) + '.json');
  if (fs.existsSync(f)) continue;
  if (fetched >= MAX_NEW) { console.log(`stopping after ${fetched} downloads (MAX_NEW)`); break; }
  const parts = [];
  for (const pc of PIECES) { const d = await piece(p, pc); if (!d) break; parts.push(d); await new Promise(res => setTimeout(res, 25e3)); }
  if (parts.length < PIECES.length) { console.log(`gave up on ${p.name} for now; run again later`); break; }
  const daily = {};
  for (const k of Object.keys(parts[0])) daily[k] = parts.flatMap(d => d[k]);
  fs.writeFileSync(f, JSON.stringify(daily));
  fetched++; console.log(`downloaded ${p.name}`);
}

const missing = ALL_POINTS.filter(p => !fs.existsSync(path.join(CACHE, key(p) + '.json')));
if (missing.length) { console.log(`not built yet: ${missing.length} points still to download (${missing.map(p => p.name).join(', ')})`); process.exit(0); }

// day of year 1..366 on a leap-year calendar so Feb 29 has a slot (filled from its neighbours)
const doy = s => { const [, m, d] = s.split('-').map(Number); return Math.round((Date.UTC(2024, m - 1, d) - Date.UTC(2024, 0, 1)) / 864e5) + 1; };
const pointClim = daily => {
  const sum = {p: new Array(367).fill(0), tx: new Array(367).fill(0), tn: new Array(367).fill(0)}, n = new Array(367).fill(0);
  daily.time.forEach((t, i) => {
    const P = daily.precipitation_sum[i], TX = daily.temperature_2m_max[i], TN = daily.temperature_2m_min[i];
    if (P == null || TX == null || TN == null) return;
    const k = doy(t); sum.p[k] += P; sum.tx[k] += TX; sum.tn[k] += TN; n[k]++;
  });
  const out = {};
  for (const v of ['p', 'tx', 'tn']) {
    const raw = sum[v].map((s, k) => n[k] ? s / n[k] : null);
    out[v] = [];
    for (let k = 1; k <= 366; k++) {   // circular moving average
      let s = 0, c = 0;
      for (let j = -SMOOTH; j <= SMOOTH; j++) { const kk = ((k - 1 + j + 366) % 366) + 1; if (raw[kk] != null) { s += raw[kk]; c++; } }
      out[v].push(c ? s / c : null);
    }
  }
  return out;
};

const regions = {};
for (const R of REGIONS) {
  const clims = R.points.map(([, lat, lon]) => pointClim(JSON.parse(fs.readFileSync(path.join(CACHE, key({lat, lon}) + '.json'), 'utf8'))));
  regions[R.id] = {};
  for (const v of ['p', 'tx', 'tn']) regions[R.id][v] = clims[0][v].map((_, i) => +(clims.reduce((s, c) => s + c[v][i], 0) / clims.length).toFixed(v === 'p' ? 4 : 2));
}
const out = {built: new Date().toISOString(), source: 'Open-Meteo historical archive (ERA5), daily', years: `${START.slice(0, 4)}-${END.slice(0, 4)}`,
  smoothing_days: SMOOTH, units: {p: 'inches per day', tx: '°F daily max', tn: '°F daily min'},
  note: 'Index 0 = Jan 1 on a leap-year calendar (366 days). Region value = average of its points.', regions};
fs.writeFileSync(path.join(ROOT, 'data/weather-normals.json'), JSON.stringify(out));
console.log('wrote data/weather-normals.json');
