// USDA estimated daily federally inspected slaughter (MyMarketNews report 3208, "Daily Livestock and Poultry
// Slaughter", section "Report Livestock Commodity"). Needs the MyMarketNews key. Each day's report re-states the
// previous days, so the newest report wins for every slaughter date.
import {getJSON, basicAuth, isoUS, num} from '../lib.mjs';

const SPECIES = ['Cattle', 'Hogs'];

export async function load({keys}) {
  if (!keys.mmn) throw new Error('MMN_API_KEY secret is not set');
  const url = 'https://marsapi.ams.usda.gov/services/v1.2/reports/3208/Report%20Livestock%20Commodity?lastReports=420';
  const res = (await getJSON(url, {headers: basicAuth(keys.mmn), timeout: 120})).results || [];
  if (!res.length) throw new Error('report 3208 returned no rows');

  const out = {};
  for (const sp of SPECIES) {
    const byDay = new Map();
    for (const r of res) {
      if (r.commodity !== sp || !r.slaughter_date) continue;
      const rep = isoUS(r.report_date), d = r.slaughter_date.slice(0, 10), old = byDay.get(d);
      if (old && old.rep >= rep) continue;
      byDay.set(d, {rep, d, head: num(r.slaughter), wk: num(r.week_ago), yr: num(r.year_ago)});
    }
    const daily = [...byDay.values()].sort((a, b) => a.d < b.d ? -1 : 1).map(({rep, ...x}) => x);
    // weekly totals, Sunday-Saturday weeks keyed by the Saturday (how USDA sums its week)
    const weeks = new Map();
    for (const x of daily) {
      const t = new Date(x.d + 'T12:00:00Z'), sat = new Date(t); sat.setUTCDate(t.getUTCDate() + (6 - t.getUTCDay()));
      const k = sat.toISOString().slice(0, 10), w = weeks.get(k) || {w: k, head: 0, yr: 0, days: 0, yrOK: true};
      w.head += x.head || 0; w.days++; if (x.yr == null) w.yrOK = false; else w.yr += x.yr;
      weeks.set(k, w);
    }
    const weekly = [...weeks.values()].sort((a, b) => a.w < b.w ? -1 : 1).map(w => ({w: w.w, head: w.head, yr: w.yrOK ? w.yr : null, days: w.days}));
    out[sp.toLowerCase()] = {daily: daily.slice(-90), weekly: weekly.slice(-60)};
  }
  const latest = out.cattle.daily.at(-1)?.d;
  return {data: out, latest, n: res.length, src: 'USDA AMS MyMarketNews report 3208 (estimated FI slaughter)'};
}
