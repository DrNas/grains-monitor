// Loads every desk page from a built _site in a headless browser and checks it renders with the data in that build:
// no script errors, and how many charts and tables drew. Saves a full-page screenshot per page (desktop and phone).
// Used by .github/workflows/check-pipelines.yml. Exits 1 if any page throws.
//   node scripts/check-pages.mjs [_site] [out-dir]
import http from 'node:http';
import fs from 'node:fs';
import path from 'node:path';
import {chromium} from 'playwright';

const SITE = path.resolve(process.argv[2] || '_site'), OUT = path.resolve(process.argv[3] || 'page-check');
const PAGES = ['', 'positioning/', 'grains/', 'energy/', 'macro/'];
const TYPES = {'.html': 'text/html', '.js': 'application/javascript', '.css': 'text/css', '.json': 'application/json', '.png': 'image/png'};

const server = http.createServer((req, res) => {
  let p = path.join(SITE, decodeURIComponent(req.url.split('?')[0]));
  if (p.endsWith('/')) p += 'index.html';
  if (!p.startsWith(SITE) || !fs.existsSync(p)) { res.writeHead(404); return res.end(); }
  res.writeHead(200, {'Content-Type': TYPES[path.extname(p)] || 'application/octet-stream'});
  fs.createReadStream(p).pipe(res);
}).listen(0);
const base = `http://127.0.0.1:${server.address().port}/`;
fs.mkdirSync(OUT, {recursive: true});

const browser = await chromium.launch();
const rows = [];
let bad = 0;
for (const pg of PAGES) {
  if (!fs.existsSync(path.join(SITE, pg, 'index.html'))) continue;
  for (const [vw, tag] of [[1300, 'desktop'], [390, 'phone']]) {
    const page = await browser.newPage({viewport: {width: vw, height: 900}});
    const errors = [];
    page.on('pageerror', e => errors.push(e.message));
    page.on('console', m => { if (m.type() === 'error' && !/Failed to load resource|net::/.test(m.text())) errors.push(m.text()); });
    await page.route(/youtube|ytimg|droughtmonitor|noaa\.gov/, r => r.abort());   // third-party embeds are not under test
    if (process.env.CHARTJS_FILE) await page.route(/cdnjs\.cloudflare\.com/, r => r.fulfill({path: process.env.CHARTJS_FILE, contentType: 'application/javascript'}));   // offline testing
    await page.goto(base + pg, {waitUntil: 'networkidle'});
    await page.waitForTimeout(1500);
    const stat = await page.evaluate(() => ({
      canvases: document.querySelectorAll('canvas').length,
      drawn: [...document.querySelectorAll('canvas')].filter(c => window.Chart?.getChart?.(c)?.data?.datasets?.some(d => (d.data || []).some(v => v != null))).length,
      tables: document.querySelectorAll('table').length,
      notes: [...document.querySelectorAll('.note')].map(n => n.textContent).filter(t => /not been built|No .* in this build|could not load/i.test(t)).length,
      hscroll: document.documentElement.scrollWidth > innerWidth,
    }));
    const file = `${(pg || 'home').replace(/\/$/, '')}-${tag}.png`;
    await page.screenshot({path: path.join(OUT, file), fullPage: true});
    rows.push({page: '/' + pg, view: tag, ...stat, errors: errors.length});
    if (errors.length) { bad++; console.log(`::error title=${'/' + pg} (${tag})::${errors.slice(0, 3).join(' | ').slice(0, 500)}`); }
    await page.close();
  }
}
await browser.close();
server.close();
const table = `### Page check\n\n| page | view | charts drawn / canvases | tables | "not built" notes | sideways scroll | script errors |\n|---|---|---|---|---|---|---|\n`
  + rows.map(r => `| ${r.page} | ${r.view} | ${r.drawn} / ${r.canvases} | ${r.tables} | ${r.notes} | ${r.hscroll ? 'yes' : 'no'} | ${r.errors} |`).join('\n') + '\n';
console.log(table);
if (process.env.GITHUB_STEP_SUMMARY) fs.appendFileSync(process.env.GITHUB_STEP_SUMMARY, table);
process.exit(bad ? 1 : 0);
