// Turns a built site (_site) into a preview folder that opens by double-clicking index.html: no web server needed.
// Pages become flat files (positioning.html, ...) and each data file becomes a small script (data/<id>.js),
// because browsers block a local page from fetching .json files but do load local scripts.
// Usage: node scripts/make-preview.mjs [_site] [_preview]
import fs from 'node:fs';
import path from 'node:path';

const src = path.resolve(process.argv[2] || '_site'), out = path.resolve(process.argv[3] || '_preview');
const DESKS = ['positioning', 'grains', 'energy', 'macro', 'backtests'];
fs.rmSync(out, {recursive: true, force: true});
fs.mkdirSync(path.join(out, 'assets'), {recursive: true});

// shared assets as they are
for (const f of fs.readdirSync(path.join(src, 'assets'))) fs.cpSync(path.join(src, 'assets', f), path.join(out, 'assets', f), {recursive: true});

// fetch() of data/<id>.json is answered from data/<id>.js, loaded on first use
fs.writeFileSync(path.join(out, 'assets/site-config.js'), `window.SITE_PUBLISHED = []; window.SITE_OFFLINE = true;
(() => {
  const real = window.fetch.bind(window), D = window.SITE_DATA = {}, waiting = {};
  const reply = id => id in D ? new Response(JSON.stringify(D[id]), {status: 200, headers: {'content-type': 'application/json'}}) : new Response('', {status: 404});
  window.fetch = (u, o) => {
    const m = /(?:^|\\/)data\\/(.+?)\\.json(?:[?#]|$)/.exec(String(u));
    if (!m) return real(u, o);
    const id = m[1];
    if (id in D) return Promise.resolve(reply(id));
    waiting[id] = waiting[id] || new Promise(res => {
      const s = document.createElement('script');
      s.src = 'data/' + id + '.js'; s.onload = s.onerror = () => res();
      document.head.appendChild(s);
    });
    return waiting[id].then(() => reply(id));
  };
})();
`);

// data/**/*.json -> data/**/*.js (the caches are only for the next build, so they are left out)
(function walk(dir) {
  for (const e of fs.readdirSync(dir, {withFileTypes: true})) {
    const p = path.join(dir, e.name);
    if (e.isDirectory()) { walk(p); continue; }
    if (!e.name.endsWith('.json') || e.name.endsWith('.cache.json')) continue;
    const id = path.relative(path.join(src, 'data'), p).split(path.sep).join('/').replace(/\.json$/, '');
    const o = path.join(out, 'data', id + '.js');
    fs.mkdirSync(path.dirname(o), {recursive: true});
    fs.writeFileSync(o, `SITE_DATA[${JSON.stringify(id)}] = ${fs.readFileSync(p, 'utf8').trim()};\n`);
  }
})(path.join(src, 'data'));

// pages: home stays index.html, each desk becomes <desk>.html next to it
const flat = h => h.replace(/href="(positioning|grains|energy|macro|backtests)\/"/g, 'href="$1.html"').replace(/href="\.\/"/g, 'href="index.html"');
fs.writeFileSync(path.join(out, 'index.html'), flat(fs.readFileSync(path.join(src, 'index.html'), 'utf8')));
for (const d of DESKS) {
  let h = fs.readFileSync(path.join(src, d, 'index.html'), 'utf8');
  h = h.replace('data-root="../"', 'data-root="./"').replace(/(src|href)="\.\.\/assets\//g, '$1="assets/');
  for (const f of fs.readdirSync(path.join(src, d))) {
    if (f === 'index.html') continue;
    fs.cpSync(path.join(src, d, f), path.join(out, d, f), {recursive: true});
    h = h.replaceAll(`src="${f}"`, `src="${d}/${f}"`);
  }
  fs.writeFileSync(path.join(out, d + '.html'), flat(h));
}
fs.writeFileSync(path.join(out, 'README.txt'), 'Test copy of the site. Open index.html (double-click). Charts need an internet connection for the chart library.\n');
console.log(`preview written to ${path.relative(process.cwd(), out) || out}`);
