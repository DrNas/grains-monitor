// Report calendar: USDA NASS's own release calendar (scraped month by month from nass.usda.gov), WASDE dates from
// data/calendar-manual.json, and rule-based weekly releases (CFTC COT, FAS export sales, EIA ethanol).
// Every time is US Eastern; each event carries a UTC instant so the page can count down in the reader's time zone.
import fs from 'node:fs';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {getText} from '../lib.mjs';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');
const MONTHS_AHEAD = 3;
// nass.usda.gov and cftc.gov sit behind firewalls that turn away non-browser user agents
const BROWSER = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36'};
const sleep = ms => new Promise(r => setTimeout(r, ms));

// NASS reports worth a futures trader's attention: [match, tier (1 = market-moving), markets]
const NASS = [
  [/^Crop Production Annual/i, 1, 'corn, soybeans, wheat'],
  [/^Crop Production$/i, 1, 'corn, soybeans, wheat'],
  [/^Grain Stocks/i, 1, 'corn, soybeans, wheat'],
  [/^Acreage$/i, 1, 'corn, soybeans, wheat'],
  [/^Prospective Plantings/i, 1, 'corn, soybeans, wheat'],
  [/^Small Grains Summary/i, 2, 'wheat'],
  [/Winter Wheat.*Seedings/i, 2, 'wheat'],
  [/^Crop Progress$/i, 2, 'corn, soybeans, wheat'],
  [/^Cattle on Feed/i, 1, 'live and feeder cattle'],
  [/^(Quarterly )?Hogs and Pigs/i, 1, 'lean hogs'],
  [/^Cattle$/i, 1, 'live and feeder cattle'],
  [/^Cold Storage/i, 2, 'hogs, cattle'],
  [/^Livestock Slaughter$/i, 3, 'cattle, hogs'],
  [/^Grain Crushings/i, 3, 'corn (ethanol)'],
  [/^Fats & Oils/i, 3, 'soybean oil, meal'],
  [/^Agricultural Prices$/i, 3, 'all'],
];

// UTC instant of a wall-clock time in New York
export function etToUTC(date, hhmm) {
  const [y, m, d] = date.split('-').map(Number), [H, M] = hhmm.split(':').map(Number);
  const guess = Date.UTC(y, m - 1, d, H + 5, M);   // EST guess, then correct by the real offset that day
  const off = new Intl.DateTimeFormat('en-US', {timeZone: 'America/New_York', timeZoneName: 'shortOffset'}).formatToParts(new Date(guess)).find(p => p.type === 'timeZoneName').value;
  const h = +(/GMT([+-]\d+)/.exec(off)?.[1] || -5);
  return new Date(Date.UTC(y, m - 1, d, H - h, M)).toISOString();
}

// US federal holidays (observed) for a year
export function holidays(y) {
  const nth = (m, wd, n) => { const d = new Date(Date.UTC(y, m, 1)); d.setUTCDate(1 + ((wd - d.getUTCDay() + 7) % 7) + 7 * (n - 1)); return d; };
  const last = (m, wd) => { const d = new Date(Date.UTC(y, m + 1, 0)); d.setUTCDate(d.getUTCDate() - ((d.getUTCDay() - wd + 7) % 7)); return d; };
  const fixed = (m, d) => { const t = new Date(Date.UTC(y, m, d)); if (t.getUTCDay() === 6) t.setUTCDate(d - 1); if (t.getUTCDay() === 0) t.setUTCDate(d + 1); return t; };
  return [fixed(0, 1), nth(0, 1, 3), nth(1, 1, 3), last(4, 1), fixed(5, 19), fixed(6, 4), nth(8, 1, 1), nth(9, 1, 2), fixed(10, 11), nth(10, 4, 4), fixed(11, 25)]
    .map(d => d.toISOString().slice(0, 10));
}
const iso = d => d.toISOString().slice(0, 10);
const addDays = (s, n) => { const t = new Date(s + 'T12:00:00Z'); t.setUTCDate(t.getUTCDate() + n); return iso(t); };
const isHol = s => holidays(+s.slice(0, 4)).includes(s);
const nextBiz = s => { let t = s; while ([0, 6].includes(new Date(t + 'T12:00:00Z').getUTCDay()) || isHol(t)) t = addDays(t, 1); return t; };

// CFTC's published COT schedule: "2026 Release Schedule Month Dates January 05* 09 ... *Delayed release ..."
async function cftcSchedule() {
  const t = (await getText('https://www.cftc.gov/MarketReports/CommitmentsofTraders/ReleaseSchedule/index.htm', {timeout: 60, headers: BROWSER}))
    .replace(/<[^>]+>/g, ' ').replace(/&nbsp;/g, ' ').replace(/\s+/g, ' ');
  const out = new Set(), MON = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December'];
  for (const [, y, body] of t.matchAll(/(20\d\d) Release Schedule Month Dates (.*?)(?=\*Delayed|20\d\d Release Schedule|$)/g))
    for (const [, mon, days] of body.matchAll(new RegExp(`(${MON.join('|')})((?: \\d{1,2}\\*?)+)`, 'g')))
      for (const dd of days.trim().split(' ')) out.add(`${y}-${String(MON.indexOf(mon) + 1).padStart(2, '0')}-${dd.replace('*', '').padStart(2, '0')}`);
  return out;
}

// Weekly releases. When a federal holiday falls earlier in the same week, each slips one business day.
// cot: the official CFTC dates when we have them for that week (otherwise the rule, marked approx).
function weekly(from, to, cot) {
  const out = [];
  for (let d = from; d <= to; d = addDays(d, 1)) {
    const wd = new Date(d + 'T12:00:00Z').getUTCDay();
    const monday = addDays(d, 1 - wd), holEarlier = n => { for (let i = 0; i < n; i++) if (isHol(addDays(monday, i))) return true; return false; };
    if (wd === 3) out.push({date: holEarlier(3) ? nextBiz(addDays(d, 1)) : d, time: holEarlier(3) ? '11:00' : '10:30', name: 'EIA weekly petroleum (ethanol output and stocks)', tier: 2, markets: 'corn', src: 'EIA', approx: holEarlier(3)});
    if (wd === 4) out.push({date: holEarlier(4) ? nextBiz(addDays(d, 1)) : d, time: '08:30', name: 'Export Sales (FAS weekly)', tier: 2, markets: 'corn, soybeans, wheat, meal, oil, beef, pork', src: 'USDA FAS', approx: holEarlier(4)});
    if (wd === 5) {
      const official = cot && [...cot].find(x => x >= d && x <= addDays(d, 4));
      const covered = cot && [...cot].some(x => x.slice(0, 4) === d.slice(0, 4));
      out.push({date: official || (holEarlier(5) ? nextBiz(addDays(d, 1)) : d), time: '15:30', name: 'Commitments of Traders (CFTC)', tier: 2, markets: 'all futures',
        src: official ? 'CFTC schedule' : 'CFTC', approx: !official && (holEarlier(5) || !covered)});
    }
  }
  return out;
}

// data/nass-calendar-cache.json: {date, time, name} rows, given tier and markets from the NASS list above
function savedNass() {
  try {
    return JSON.parse(fs.readFileSync(path.join(ROOT, 'data/nass-calendar-cache.json'), 'utf8')).events.map(e => {
      const hit = NASS.find(([re]) => re.test(e.name)); return hit ? {date: e.date, time: e.time, name: e.name, tier: hit[1], markets: hit[2], src: 'USDA NASS'} : null;
    }).filter(Boolean);
  } catch (e) { return []; }
}

async function nassMonth(y, m) {
  const html = await getText(`https://www.nass.usda.gov/Publications/Calendar/reports_by_date.php?view=c&js=1&month=${m}&year=${y}`, {timeout: 60, headers: BROWSER});
  // No calendar table: either NASS hasn't posted that year yet (it posts a whole year at once, so only possible for
  // a later year), or the firewall sent a block/challenge page with HTTP 200. Return null; the caller decides.
  const i = html.indexOf('<table class="calendar">'); if (i < 0) return null;
  const tab = html.slice(i, html.indexOf('</table>', i)), out = [];
  for (const [, cell] of tab.matchAll(/<td class="calendar[^"]*"\s*>([\s\S]*?)<\/td>/g)) {
    const day = /^\s*&nbsp;(\d+)/.exec(cell)?.[1]; if (!day) continue;
    const date = `${y}-${String(m).padStart(2, '0')}-${day.padStart(2, '0')}`;
    let time = null;
    for (const t of cell.matchAll(/(\d{1,2}):(\d\d) ([ap]m) ET|report_id=(\d+)">([^<]+)<\/a>/g)) {
      if (t[1]) { time = `${String((+t[1] % 12) + (t[3] === 'pm' ? 12 : 0)).padStart(2, '0')}:${t[2]}`; continue; }
      const name = t[5].replace(/\s+/g, ' ').trim(), hit = NASS.find(([re]) => re.test(name));
      if (hit && time) out.push({date, time, name, tier: hit[1], markets: hit[2], src: 'USDA NASS', id: +t[4]});
    }
  }
  return out;
}

export async function load({now, prev}) {
  const today = iso(now), notes = [];
  let partial = false;
  const from = addDays(today, -7), to = addDays(today, 31 * MONTHS_AHEAD);
  let events = [];
  for (let k = -1; k < MONTHS_AHEAD; k++) {
    const d = new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth() + k, 1));
    try {
      const ev = await nassMonth(d.getUTCFullYear(), d.getUTCMonth() + 1);
      if (ev === null) {
        if (d.getUTCFullYear() > now.getUTCFullYear()) { notes.push(`NASS has not posted ${d.toISOString().slice(0, 7)} yet`); continue; }
        throw new Error('page came back without its calendar (likely blocked)');
      }
      events.push(...ev);
    } catch (e) {
      // NASS's firewall turns requests away now and then: keep that month's NASS dates from the last good build,
      // or failing that from the saved copy in data/nass-calendar-cache.json
      const ym = d.toISOString().slice(0, 7);
      let old = (prev?.events || []).filter(x => x.src === 'USDA NASS' && x.date.startsWith(ym)).map(({at, ...x}) => x), from = 'the last good build';
      if (!old.length) { old = savedNass().filter(x => x.date.startsWith(ym)); from = 'the saved NASS calendar'; }
      events.push(...old);
      notes.push(`NASS ${ym}: ${e.message.slice(0, 60)}${old.length ? ` (kept ${old.length} dates from ${from})` : ''}`);
      if (k >= 0 && !old.length) partial = true;
    }
    await sleep(1500);
  }
  const manual = JSON.parse(fs.readFileSync(path.join(ROOT, 'data/calendar-manual.json'), 'utf8'));
  for (const ev of manual.events) for (const date of ev.dates) events.push({date, time: ev.time, name: ev.name, tier: 1, markets: 'corn, soybeans, wheat, meal, oil, cattle, hogs', src: 'USDA WAOB'});
  if (!manual.events.some(e => e.dates.some(d => d >= addDays(today, 60)))) notes.push('WASDE dates run out within 60 days: add the next year to data/calendar-manual.json');
  let cot = null;
  try { cot = await cftcSchedule(); if (!cot.size) throw new Error('no dates found on the page'); }
  catch (e) { notes.push(`CFTC schedule: ${e.message.slice(0, 80)} (COT dates from the usual rule)`); cot = null; }
  events.push(...weekly(from, to, cot));
  events = events.filter(e => e.date >= from && e.date <= to)
    .map(e => ({...e, at: etToUTC(e.date, e.time)}))
    .sort((a, b) => a.at < b.at ? -1 : a.at > b.at ? 1 : a.tier - b.tier);
  return {partial, data: {events, holidays: [...holidays(now.getUTCFullYear()), ...holidays(now.getUTCFullYear() + 1)]}, latest: today, n: events.length,
    note: notes.join(' · '), src: 'USDA NASS release calendar, USDA WASDE schedule, CFTC/FAS/EIA weekly rules'};
}
