// Shared HTTP helpers. On GitHub's runners this is plain fetch. Set USE_CURL=1 to send requests through curl instead
// (handy behind a proxy that Node's fetch can't use). Every request has a timeout and a couple of retries.
import {execFile} from 'node:child_process';

const UA = 'grains-monitor daily build (+https://github.com/DrNas/grains-monitor)';
const sleep = ms => new Promise(r => setTimeout(r, ms));

function curl(url, {headers = {}, timeout = 60}) {
  const args = ['-sS', '-L', '-m', String(timeout), '-A', headers['User-Agent'] || UA, '-w', '\n%{http_code}', url];
  for (const [k, v] of Object.entries(headers)) if (k !== 'User-Agent') args.push('-H', `${k}: ${v}`);
  return new Promise((resolve, reject) => execFile('curl', args, {maxBuffer: 256e6}, (err, out) => {
    if (err) return reject(new Error(`curl: ${err.message.split('\n')[0]}`));
    const i = out.lastIndexOf('\n');
    resolve({status: +out.slice(i + 1), text: out.slice(0, i)});
  }));
}

export async function getText(url, {headers = {}, timeout = 60, retries = 2, okStatuses = [200]} = {}) {
  headers = {'User-Agent': UA, Accept: '*/*', ...headers};
  let last;
  for (let a = 0; a <= retries; a++) {
    if (a) await sleep(2000 * a);
    try {
      let status, text;
      if (process.env.USE_CURL) ({status, text} = await curl(url, {headers, timeout}));
      else {
        const r = await fetch(url, {headers, signal: AbortSignal.timeout(timeout * 1000)});
        status = r.status; text = await r.text();
      }
      if (okStatuses.includes(status)) return text;
      last = new Error(`HTTP ${status} from ${new URL(url).host}: ${text.slice(0, 160).replace(/\s+/g, ' ')}`);
      if (status >= 400 && status < 500 && status !== 429) break;   // a client error won't fix itself
    } catch (e) { last = e; }
  }
  throw last;
}

export async function getJSON(url, opts = {}) {
  const t = await getText(url, {...opts, headers: {Accept: 'application/json', ...(opts.headers || {})}});
  try { return JSON.parse(t); } catch (e) { throw new Error(`not JSON from ${new URL(url).host}: ${t.slice(0, 120)}`); }
}

export const basicAuth = key => ({Authorization: 'Basic ' + Buffer.from(key + ':').toString('base64')});
export const cleanKey = k => (k || '').trim().replace(/^["']|["']$/g, '');   // tolerate a pasted newline or quotes

// "MM/DD/YYYY" -> "YYYY-MM-DD"
export const isoUS = s => { const m = /^(\d{1,2})\/(\d{1,2})\/(\d{4})/.exec(s || ''); return m ? `${m[3]}-${m[1].padStart(2, '0')}-${m[2].padStart(2, '0')}` : null; };
export const num = v => v === null || v === undefined || v === '' ? null : (Number.isFinite(+v) ? +v : null);
export const round = (v, d = 2) => v == null || !Number.isFinite(v) ? null : Math.round(v * 10 ** d) / 10 ** d;

// percentile rank of x within arr (0-100): share of values strictly below plus half of ties
export function pctRank(arr, x) {
  const v = arr.filter(Number.isFinite); if (!v.length || !Number.isFinite(x)) return null;
  let below = 0, eq = 0; for (const a of v) { if (a < x) below++; else if (a === x) eq++; }
  return Math.round((below + eq / 2) / v.length * 100);
}
