// Builds the dashboard's data snapshot: runs every source in scripts/sources/, keeps the previous copy of any that
// fails (state CACHED), and writes _site/index.html + _site/data/latest.json for GitHub Pages.
// Keys come from repository secrets (never written to the output). Local run: `USE_CURL=1 node scripts/build-data.mjs`
// with MMN_API_KEY etc. in the environment; `ONLY=cot,weather` runs a subset.
import fs from 'node:fs';
import {execFile} from 'node:child_process';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {cleanKey, getJSON} from './lib.mjs';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
// where the published site lives (previous snapshot is read from here). Custom domain first, then the github.io copy.
const PAGES = (process.env.PAGES_URL ? [process.env.PAGES_URL] : ['https://grains.manasbafna.com/', 'https://drnas.github.io/grains-monitor/']);

// [id, label, options]. Default: scripts/sources/<id>.mjs, data inside latest.json (the home page).
// {py: 'pipelines/<x>/run.py'}: a Python pipeline that prints {data, latest, n, src, note, partial} as JSON on stdout.
//   It may also return `cache`: kept in data/<id>.cache.json (never read by a page) and handed back to the next run
//   as the file named by the PREV_CACHE environment variable, so history that never changes is downloaded once.
//   It may return `files` ({name: object}): published as data/<id>/<name>.json (e.g. one history per market, loaded
//   by the page on demand); a failed run republishes the previous ones.
//   It gets the previous build's `latest` as PREV_LATEST and may print {reuse: true, note} when nothing new is out:
//   the previous copy (data and files) is then republished unchanged, which saves slow downloads.
// {file: true}: the data goes to data/<id>.json (read by a desk page); latest.json keeps only its status.
const SOURCES = [
  ['recap', 'Video recap'], ['calendar', 'Report calendar'], ['cot', 'COT positioning'], ['slaughter', 'Livestock slaughter'], ['livestock', 'Livestock prices'],
  ['basis', 'Cash grain basis'], ['weather', 'Weather'], ['drought', 'Drought Monitor'], ['enso', 'ENSO'],
  ['crop_progress', 'Crop progress & condition', {py: 'pipelines/crop_progress/run.py', file: true}],
  ['wasde', 'WASDE balance sheets', {py: 'pipelines/wasde/run.py', file: true}],
  ['export_sales', 'Export sales & inspections', {py: 'pipelines/export_sales/run.py', file: true}],
  ['energy', 'Energy (EIA)', {py: 'pipelines/energy/run.py', file: true}],
  ['positioning', 'Positioning (COT & CIT)', {py: 'pipelines/positioning/run.py', file: true}],
];
// what gets published besides the data: the home page, shared assets and one folder per desk
const SITE = ['index.html', 'assets', 'grains', 'energy', 'positioning'];

// Runs a Python pipeline with the build's environment (keys included) and parses the JSON it prints.
function runPy(script, cache, prevLatest, timeoutMin = 25) {
  const env = {...process.env, PREV_LATEST: prevLatest || ''};
  if (cache) { env.PREV_CACHE = path.join(ROOT, '_site', `.prev-${path.basename(path.dirname(script))}.json`); fs.mkdirSync(path.dirname(env.PREV_CACHE), {recursive: true}); fs.writeFileSync(env.PREV_CACHE, JSON.stringify(cache)); }
  return new Promise((resolve, reject) => execFile(process.env.PYTHON || 'python3', [path.join(ROOT, script)],
    {cwd: ROOT, env, timeout: timeoutMin * 60e3, maxBuffer: 512e6}, (err, out, errOut) => {
      if (env.PREV_CACHE) fs.rmSync(env.PREV_CACHE, {force: true});
      if (errOut) process.stdout.write(errOut.split('\n').filter(Boolean).map(l => `  [${path.basename(path.dirname(script))}] ${l}`).join('\n') + '\n');
      if (err) return reject(new Error((errOut || err.message).trim().split('\n').pop()));
      try { resolve(JSON.parse(out)); } catch (e) { reject(new Error(`not JSON from ${script}: ${out.slice(0, 120)}`)); }
    }));
}

async function previous() {
  for (const base of PAGES) {
    try { const snap = await getJSON(base + 'data/latest.json?t=' + Date.now(), {timeout: 30, retries: 0}); snap.base = base; return snap; } catch (e) {}
  }
  return null;
}

// a Python pipeline's published cache (data/<id>.cache.json), if there is one
async function previousCache(prev, id) {
  if (!prev?.series?.[id]?.cache) return null;
  try { return await getJSON(prev.base + prev.series[id].cache + '?t=' + Date.now(), {timeout: 120, retries: 1}); } catch (e) { return null; }
}

// previous published copy of a source: inside latest.json, or its own data/<id>.json for desk sources
async function previousOf(prev, id) {
  const s = prev?.series?.[id];
  if (!s?.file) return s || null;
  try { return await getJSON(prev.base + s.file + '?t=' + Date.now(), {timeout: 60, retries: 1}); } catch (e) { return null; }
}

async function main() {
  const now = new Date();
  const keys = {mmn: cleanKey(process.env.MMN_API_KEY), nass: cleanKey(process.env.NASS_API_KEY),
    datagov: cleanKey(process.env.DATAGOV_API_KEY), eia: cleanKey(process.env.EIA_API_KEY)};
  for (const [k, env] of [['mmn', 'MMN_API_KEY']]) if (!keys[k]) console.log(`::warning::${env} secret is not set: sources that need it will fail.`);
  const only = (process.env.ONLY || '').split(',').filter(Boolean);
  const prev = await previous();
  console.log(prev ? `previous snapshot: ${prev.generated}` : 'no previous snapshot (first run?)');

  const series = {}, failed = [], caches = {}, extra = {};
  // a desk source's extra files from the previous build (data/<id>/<name>.json)
  const previousFiles = async (old, id) => {
    const out = {};
    for (const n of old?.files || []) { try { out[n] = await getJSON(`${prev.base}data/${id}/${n}.json?t=${Date.now()}`, {timeout: 60, retries: 1}); } catch (e) {} }
    return out;
  };
  for (const [id, label, opt = {}] of SOURCES) {
    if (only.length && !only.includes(id)) {
      const old = await previousOf(prev, id); if (old) series[id] = old;
      if (opt.py) { caches[id] = await previousCache(prev, id); extra[id] = await previousFiles(old, id); }
      continue;
    }
    const t0 = Date.now();
    try {
      const pc = opt.py ? await previousCache(prev, id) : null;
      const r = opt.py ? await runPy(opt.py, pc, prev?.series?.[id]?.latest) : await (await import(`./sources/${id}.mjs`)).load({now, keys, prev: prev?.series?.[id]?.data || null});
      if (r.reuse) {   // nothing new at the source: republish the previous copy
        const old = await previousOf(prev, id);
        if (!old?.data) throw new Error('nothing new to fetch, but no previous copy to reuse');
        series[id] = {...old, state: 'OK', note: r.note || old.note || ''};
        caches[id] = pc; extra[id] = await previousFiles(old, id);
        console.log(`${id}: OK (${((Date.now() - t0) / 1000).toFixed(1)}s) unchanged, latest ${old.latest}`);
        continue;
      }
      if (opt.py) { caches[id] = r.cache || null; extra[id] = r.files || {}; }
      series[id] = {label, state: r.partial ? 'PARTIAL' : 'OK', latest: r.latest || null, n: r.n ?? null, src: r.src || '', note: r.note || '',
        built: now.toISOString(), data: r.data};
      console.log(`${id}: ${series[id].state} (${((Date.now() - t0) / 1000).toFixed(1)}s) latest ${r.latest}${r.note ? ' · ' + r.note : ''}`);
    } catch (e) {
      failed.push(id);
      const old = await previousOf(prev, id);
      const why = (e.message || String(e)).replace(/\s+/g, ' ').slice(0, 300);
      if (opt.py) { caches[id] = await previousCache(prev, id); extra[id] = await previousFiles(old, id); }   // keep the history for the next run
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
  for (const p of SITE) fs.cpSync(path.join(ROOT, p), path.join(site, p), {recursive: true});
  // desk sources: full entry in data/<id>.json, status only in latest.json
  for (const [id, , opt = {}] of SOURCES) {
    if (!opt.file || !series[id]) continue;
    const ex = extra[id] || {};
    if (Object.keys(ex).length) {
      fs.mkdirSync(path.join(site, 'data', id), {recursive: true});
      for (const [n, obj] of Object.entries(ex)) fs.writeFileSync(path.join(site, 'data', id, `${n}.json`), JSON.stringify(obj));
    }
    const files = Object.keys(ex);   // listed in both files, so the next build knows what to carry forward
    fs.writeFileSync(path.join(site, `data/${id}.json`), JSON.stringify({...series[id], file: undefined, cache: undefined, files}));
    series[id] = {...series[id], data: null, file: `data/${id}.json`, cache: undefined, files};
    if (caches[id]) { fs.writeFileSync(path.join(site, `data/${id}.cache.json`), JSON.stringify(caches[id])); series[id].cache = `data/${id}.cache.json`; }
  }
  fs.writeFileSync(path.join(site, 'data/latest.json'), JSON.stringify(snapshot));
  if (process.env.GITHUB_OUTPUT) fs.appendFileSync(process.env.GITHUB_OUTPUT, `failed=${failed.join(' ')}\n`);
  for (const id of failed) console.log(`::error title=${id} failed::${(series[id].note || '').slice(0, 400)}`);
  console.log(`wrote _site/data/latest.json (${(fs.statSync(path.join(site, 'data/latest.json')).size / 1e6).toFixed(2)} MB); failed: ${failed.join(', ') || 'none'}`);
}

main().catch(e => { console.error(e); process.exit(1); });
