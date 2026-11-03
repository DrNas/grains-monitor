// USDA AMS daily state grain bid reports (MyMarketNews, section "Report Detail"). Needs the MyMarketNews key.
// Each row is one region and delivery point (country elevator, processor, barge loading, terminal, export) with a
// basis range against a named futures month, the average cash price, and the average price a year ago.
// Rows marked current = "No" are forward (new-crop) bids and are left out.
import {getJSON, basicAuth, isoUS, num, round} from '../lib.mjs';

export const REPORTS = [
  {id: 2850, st: 'IA', name: 'Iowa'}, {id: 3192, st: 'IL', name: 'Illinois'}, {id: 3463, st: 'IN', name: 'Indiana'},
  {id: 2851, st: 'OH', name: 'Ohio'}, {id: 3225, st: 'NE', name: 'Nebraska'}, {id: 3049, st: 'MN', name: 'Southern Minnesota'},
  {id: 3186, st: 'SD', name: 'South Dakota'}, {id: 3878, st: 'ND', name: 'North Dakota'}, {id: 2886, st: 'KS', name: 'Kansas'},
  {id: 3100, st: 'OK', name: 'Oklahoma'}, {id: 2711, st: 'TX', name: 'Texas'}, {id: 2932, st: 'MO', name: 'Missouri'},
  {id: 2960, st: 'AR', name: 'Arkansas'}, {id: 2892, st: 'KY', name: 'Kentucky'}, {id: 3088, st: 'TN', name: 'Tennessee'},
  {id: 3043, st: 'IA-MN', name: 'Iowa-S. Minnesota barge terminals'}, {id: 3148, st: 'PNW', name: 'Portland export'},
];
const HISTORY = 12;   // reports per state fetched (~2.5 weeks), for the week-on-week basis change

const MONTH = /\(([FGHJKMNQUVXZ])\)/;
const signed = (c, dir) => c == null ? null : dir === 'DN' ? -Math.abs(c) : dir === 'UP' ? Math.abs(c) : 0;
const label = r => r.commodity === 'Wheat' ? (r.class ? r.class + ' wheat' : 'Wheat') : /Oats/.test(r.commodity) ? 'Oats'
  : r.commodity === 'Corn' && r.class === 'White' ? 'White corn' : r.commodity;

function parseRow(r) {
  const mMin = MONTH.exec(r['basis Min Futures Month'] || '')?.[1] || null, mMax = MONTH.exec(r['basis Max Futures Month'] || '')?.[1] || null;
  const bMin = num(r['basis Min']), bMax = num(r['basis Max']);
  return {
    date: isoUS(r.report_date), com: label(r), dp: r.delivery_point, loc: r.trade_loc || r.location_City || '',
    mode: r.trans_mode || '', bMin, bMax, mMin, mMax,
    // a single "mid" basis only when both ends are quoted against the same futures month
    mid: bMin != null && bMax != null && mMin === mMax ? (bMin + bMax) / 2 : null,
    dMin: signed(num(r['basis Min Change']), r['basis Min Direction']), dMax: signed(num(r['basis Max Change']), r['basis Max Direction']),
    price: num(r.avg_price), pMin: num(r['price Min']), pMax: num(r['price Max']), pYr: num(r.avg_price_year_ago),
  };
}

export async function load({keys}) {
  if (!keys.mmn) throw new Error('MMN_API_KEY secret is not set');
  const states = [], errors = [];
  for (const R of REPORTS) {   // one at a time: MyMarketNews is happier without bursts
    try {
      const j = await getJSON(`https://marsapi.ams.usda.gov/services/v1.2/reports/${R.id}/Report%20Detail?lastReports=${HISTORY}`,
        {headers: basicAuth(keys.mmn), timeout: 90});
      const all = (j.results || []).filter(r => r.current !== 'No').map(parseRow);
      if (!all.length) { errors.push(`${R.st}: no rows`); continue; }
      const dates = [...new Set(all.map(r => r.date))].sort();
      const last = dates.at(-1), weekAgo = dates.filter(d => d <= shift(last, -6)).at(-1) || null;
      const key = r => [r.com, r.dp, r.loc, r.mode].join('|');
      const prev = new Map(all.filter(r => r.date === weekAgo).map(r => [key(r), r]));
      const rows = all.filter(r => r.date === last).map(r => {
        const p = prev.get(key(r));
        return {...r, wk: p && r.mid != null && p.mid != null && p.mMin === r.mMin ? round(r.mid - p.mid, 1) : null,
          pWk: p && r.price != null && p.price != null ? round(r.price - p.price, 4) : null};
      });
      // state summary per commodity: country-elevator rows only (the farm-gate picture)
      const summary = {};
      for (const com of [...new Set(rows.map(r => r.com))]) {
        const ce = rows.filter(r => r.com === com && r.dp === 'Country Elevators');
        const use = ce.length ? ce : rows.filter(r => r.com === com);
        const avg = (f, rs = use) => { const v = rs.map(r => r[f]).filter(x => x != null); return v.length ? v.reduce((a, b) => a + b, 0) / v.length : null; };
        // basis is averaged only across rows quoted against the same futures month: the month most rows use
        // (around a contract roll, regions switch months on different days)
        const cnt = {}; for (const r of use) if (r.mid != null) cnt[r.mMin] = (cnt[r.mMin] || 0) + 1;
        const month = Object.entries(cnt).sort((a, b) => b[1] - a[1])[0]?.[0] || null, onM = use.filter(r => r.mid != null && r.mMin === month);
        summary[com] = {dp: ce.length ? 'Country Elevators' : use[0]?.dp, n: use.length, price: round(avg('price'), 4), pYr: round(avg('pYr'), 4),
          mid: month ? round(avg('mid', onM), 1) : null, month, nMid: onM.length,
          wk: month ? round(avg('wk', onM), 1) : null, pWk: round(avg('pWk'), 4)};
      }
      states.push({...R, date: last, weekAgo, rows, summary});
    } catch (e) { errors.push(`${R.st}: ${e.message}`); }
  }
  if (!states.length) throw new Error(errors.join('; '));
  const latest = states.map(s => s.date).sort().pop();
  return {data: {states}, latest, n: states.reduce((s, x) => s + x.rows.length, 0),
    note: errors.length ? `missing: ${errors.join('; ')}` : '', partial: errors.length > 0,
    src: 'USDA AMS MyMarketNews daily state grain bid reports'};
}

function shift(d, days) { const t = new Date(d + 'T12:00:00Z'); t.setUTCDate(t.getUTCDate() + days); return t.toISOString().slice(0, 10); }
