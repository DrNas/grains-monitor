// Builds the dashboard's data snapshot: runs every source in scripts/sources/, keeps the previous copy of any that
// fails (state CACHED), and writes _site/index.html + _site/data/latest.json for GitHub Pages.
// Keys come from repository secrets (never written to the output). Local run: `USE_CURL=1 node scripts/build-data.mjs`
// with MMN_API_KEY etc. in the environment; `ONLY=cot,weather` runs a subset.
import fs from 'node:fs';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {cleanKey, getJSON} from './lib.mjs';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
// where the published site lives (previous snapshot is read from here). Custom domain first, then the github.io copy.
const PAGES = (process.env.PAGES_URL ? [process.env.PAGES_URL] : ['https://grains.manasbafna.com/', 'https://drnas.github.io/grains-monitor/']);

const SOURCES = [
  ['recap', 'Video recap'], ['calendar', 'Report calendar'], ['cot', 'COT positioning'], ['slaughter', 'Livestock slaughter'],
  ['basis', 'Cash grain basis'], ['weather', 'Weather'], ['drought', 'Drought Monitor'], ['enso', 'ENSO'],
];

async function previous() {
  for (const base of PAGES) {
    try { return await getJSON(base + 'data/latest.json?t=' + Date.now(), {timeout: 30, retries: 0}); } catch (e) {}
  }
  return null;
}

async function main() {
  const now = new Date();
  const keys = {mmn: cleanKey(process.env.MMN_API_KEY), nass: cleanKey(process.env.NASS_API_KEY),
    datagov: cleanKey(process.env.DATAGOV_API_KEY), eia: cleanKey(process.env.EIA_API_KEY)};
  for (const [k, env] of [['mmn', 'MMN_API_KEY']]) if (!keys[k]) console.log(`::warning::${env} secret is not set: sources that need it will fail.`);
  const only = (process.env.ONLY || '').split(',').filter(Boolean);
  const prev = await previous();
  console.log(prev ? `previous snapshot: ${prev.generated}` : 'no previous snapshot (first run?)');

  const series = {}, failed = [];
  for (const [id, label] of SOURCES) {
    if (only.length && !only.includes(id)) { if (prev?.series?.[id]) series[id] = prev.series[id]; continue; }
    const t0 = Date.now();
    try {
      const mod = await import(`./sources/${id}.mjs`);
      const r = await mod.load({now, keys, prev: prev?.series?.[id]?.data || null});
      series[id] = {label, state: r.partial ? 'PARTIAL' : 'OK', latest: r.latest || null, n: r.n ?? null, src: r.src || '', note: r.note || '',
        built: now.toISOString(), data: r.data};
      console.log(`${id}: ${series[id].state} (${((Date.now() - t0) / 1000).toFixed(1)}s) latest ${r.latest}${r.note ? ' · ' + r.note : ''}`);
    } catch (e) {
      failed.push(id);
      const old = prev?.series?.[id];
      const why = (e.message || String(e)).replace(/\s+/g, ' ').slice(0, 300);
      series[id] = old?.data ? {...old, state: 'CACHED', note: `today's fetch failed (${why}); showing the copy built ${old.built}`}
        : {label, state: 'FAILED', latest: null, n: 0, src: '', note: why, built: now.toISOString(), data: null};
      console.log(`${id}: FAILED (${why})`);
    }
  }

  const snapshot = {generated: now.toISOString(), failed, series};
  const rows = Object.entries(series).map(([id, s]) => `| ${id} | ${s.state} | ${s.latest || ''} | ${(s.note || '').replace(/\|/g, '/').slice(0, 200)} |`);
  const summary = `### Data snapshot ${snapshot.generated}\n\n| source | state | latest | note |\n|---|---|---|---|\n${rows.join('\n')}\n`;
  console.log(summary);
  if (process.env.GITHUB_STEP_SUMMARY) fs.appendFileSync(process.env.GITHUB_STEP_SUMMARY, summary);

  const site = path.join(ROOT, '_site');
  fs.mkdirSync(path.join(site, 'data'), {recursive: true});
  fs.copyFileSync(path.join(ROOT, 'index.html'), path.join(site, 'index.html'));
  fs.writeFileSync(path.join(site, 'data/latest.json'), JSON.stringify(snapshot));
  if (process.env.GITHUB_OUTPUT) fs.appendFileSync(process.env.GITHUB_OUTPUT, `failed=${failed.join(' ')}\n`);
  for (const id of failed) console.log(`::error title=${id} failed::${(series[id].note || '').slice(0, 400)}`);
  console.log(`wrote _site/data/latest.json (${(fs.statSync(path.join(site, 'data/latest.json')).size / 1e6).toFixed(2)} MB); failed: ${failed.join(', ') || 'none'}`);
}

main().catch(e => { console.error(e); process.exit(1); });
