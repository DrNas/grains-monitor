// CFTC Commitments of Traders, Disaggregated, futures only (Socrata dataset 72hh-3qpy). No key needed.
// Positions are as of Tuesday; CFTC publishes them Friday 3:30pm ET (Monday after a holiday week).
import {getJSON, num, pctRank, round} from '../lib.mjs';

export const MARKETS = [
  {k: 'corn', name: 'Corn', code: '002602', grp: 'Grains'},
  {k: 'soybeans', name: 'Soybeans', code: '005602', grp: 'Grains'},
  {k: 'meal', name: 'Soybean meal', code: '026603', grp: 'Grains'},
  {k: 'soyoil', name: 'Soybean oil', code: '007601', grp: 'Grains'},
  {k: 'srw', name: 'Chicago wheat (SRW)', code: '001602', grp: 'Grains'},
  {k: 'hrw', name: 'KC wheat (HRW)', code: '001612', grp: 'Grains'},
  {k: 'hrs', name: 'Spring wheat (HRS)', code: '001626', grp: 'Grains'},
  {k: 'lc', name: 'Live cattle', code: '057642', grp: 'Livestock'},
  {k: 'fc', name: 'Feeder cattle', code: '061641', grp: 'Livestock'},
  {k: 'lh', name: 'Lean hogs', code: '054642', grp: 'Livestock'},
];
const YEARS = 6;   // history fetched; percentiles use the last 3 and 5 years of it

const FIELDS = ['cftc_contract_market_code', 'market_and_exchange_names', 'report_date_as_yyyy_mm_dd', 'open_interest_all',
  'm_money_positions_long_all', 'm_money_positions_short_all', 'm_money_positions_spread',
  'prod_merc_positions_long', 'prod_merc_positions_short', 'swap_positions_long_all', 'swap__positions_short_all',
  'other_rept_positions_long', 'other_rept_positions_short', 'nonrept_positions_long_all', 'nonrept_positions_short_all'];

export async function load({now}) {
  const since = new Date(now); since.setUTCFullYear(since.getUTCFullYear() - YEARS);
  const codes = MARKETS.map(m => `'${m.code}'`).join(',');
  const q = new URLSearchParams({
    $select: FIELDS.join(','),
    $where: `cftc_contract_market_code in (${codes}) AND report_date_as_yyyy_mm_dd >= '${since.toISOString().slice(0, 10)}'`,
    $order: 'report_date_as_yyyy_mm_dd', $limit: '50000'});
  const rows = await getJSON('https://publicreporting.cftc.gov/resource/72hh-3qpy.json?' + q, {timeout: 90});
  if (!Array.isArray(rows) || !rows.length) throw new Error('CFTC returned no rows');

  const markets = [];
  for (const M of MARKETS) {
    const byDate = new Map();   // one row per report date (a renamed exchange can't double a week)
    for (const r of rows) if (r.cftc_contract_market_code === M.code) byDate.set(r.report_date_as_yyyy_mm_dd.slice(0, 10), r);
    const h = [...byDate.entries()].sort((a, b) => a[0] < b[0] ? -1 : 1).map(([d, r]) => {
      const n = f => num(r[f]) ?? 0;
      return {d, oi: n('open_interest_all'),
        mmL: n('m_money_positions_long_all'), mmS: n('m_money_positions_short_all'),
        mm: n('m_money_positions_long_all') - n('m_money_positions_short_all'),
        pm: n('prod_merc_positions_long') - n('prod_merc_positions_short'),
        sw: n('swap_positions_long_all') - n('swap__positions_short_all'),
        or: n('other_rept_positions_long') - n('other_rept_positions_short'),
        nr: n('nonrept_positions_long_all') - n('nonrept_positions_short_all')};
    });
    if (!h.length) { markets.push({...M, error: 'no rows for this contract code'}); continue; }
    const last = h[h.length - 1], ago = k => h[h.length - 1 - k];
    const window = yrs => { const c = new Date(last.d); c.setUTCFullYear(c.getUTCFullYear() - yrs); const cs = c.toISOString().slice(0, 10); return h.filter(x => x.d >= cs); };
    const w3 = window(3), w5 = window(5);
    const mm5 = w5.map(x => x.mm);
    markets.push({...M, exchange: rows.find(r => r.cftc_contract_market_code === M.code && r.report_date_as_yyyy_mm_dd.startsWith(last.d))?.market_and_exchange_names,
      latest: last.d,
      mm: last.mm, mmL: last.mmL, mmS: last.mmS, oi: last.oi, pm: last.pm, sw: last.sw,
      mmPctOI: round(last.mm / last.oi * 100, 1),
      chg1: ago(1) ? last.mm - ago(1).mm : null, chg4: ago(4) ? last.mm - ago(4).mm : null,
      oiChg1: ago(1) ? last.oi - ago(1).oi : null,
      pct3: pctRank(w3.map(x => x.mm), last.mm), pct5: pctRank(mm5, last.mm),
      min5: Math.min(...mm5), max5: Math.max(...mm5),
      // weeks in a row the managed-money net moved the same way
      streak: (() => { let s = 0, dir = 0; for (let i = h.length - 1; i > 0; i--) { const d = Math.sign(h[i].mm - h[i - 1].mm); if (!d || (dir && d !== dir)) break; dir = d; s++; } return s * dir; })(),
      hist: h});
  }
  const latest = markets.map(m => m.latest).filter(Boolean).sort().pop();
  return {data: {markets}, latest, n: rows.length, src: 'CFTC Disaggregated COT, futures only (publicreporting.cftc.gov 72hh-3qpy)'};
}
