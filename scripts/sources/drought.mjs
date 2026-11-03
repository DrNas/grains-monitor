// U.S. Drought Monitor statistics (usdmdataservices.unl.edu, no key): percent of area in each drought category,
// cumulative (d1 = D1 or worse), for the U.S. and the main crop and cattle states. Weekly, maps valid Tuesday,
// released Thursday morning.
import {getJSON, round} from '../lib.mjs';

export const STATES = [['IA', 19], ['IL', 17], ['IN', 18], ['OH', 39], ['NE', 31], ['MN', 27], ['SD', 46], ['ND', 38],
  ['KS', 20], ['OK', 40], ['TX', 48], ['MO', 29], ['AR', '05'], ['CO', '08']];   // two-digit FIPS

const mdY = d => `${d.getUTCMonth() + 1}/${d.getUTCDate()}/${d.getUTCFullYear()}`;
const fix = v => round(v, 2) || 0;   // no -0
const row = r => ({d: r.mapDate.slice(0, 10), none: +r.none, d0: +r.d0, d1: +r.d1, d2: +r.d2, d3: +r.d3, d4: +r.d4});

export async function load({now}) {
  const start = new Date(now); start.setUTCDate(start.getUTCDate() - 7 * 54);   // a year and a bit: 1, 4, 52-week changes
  const qs = `startdate=${mdY(start)}&enddate=${mdY(now)}&statisticsType=1`;
  const us = (await getJSON(`https://usdmdataservices.unl.edu/api/USStatistics/GetDroughtSeverityStatisticsByAreaPercent?aoi=total&${qs}`, {timeout: 60}))
    .map(row).sort((a, b) => a.d < b.d ? -1 : 1);
  if (!us.length) throw new Error('no national rows');
  const states = [], errors = [];
  for (const [st, fips] of STATES) {
    try {
      const h = (await getJSON(`https://usdmdataservices.unl.edu/api/StateStatistics/GetDroughtSeverityStatisticsByAreaPercent?aoi=${fips}&${qs}`, {timeout: 60}))
        .map(row).sort((a, b) => a.d < b.d ? -1 : 1);
      if (!h.length) { errors.push(st); continue; }
      const L = h.at(-1), ago = k => h[h.length - 1 - k];
      states.push({st, d: L.d, d0: L.d0, d1: L.d1, d2: L.d2, d3: L.d3,
        chg1: ago(1) ? fix(L.d1 - ago(1).d1) : null, chg4: ago(4) ? fix(L.d1 - ago(4).d1) : null,
        yr: ago(52) ? ago(52).d1 : null, spark: h.slice(-26).map(x => x.d1)});
    } catch (e) { errors.push(`${st} (${e.message.slice(0, 40)})`); }
  }
  return {data: {us, states}, latest: us.at(-1).d, n: us.length + states.length,
    note: errors.length ? `missing: ${errors.join(', ')}` : '', partial: errors.length > 0,
    src: 'U.S. Drought Monitor statistics (NDMC / USDA / NOAA)'};
}
