// Cash livestock and meat prices from USDA Livestock Mandatory Reporting (mpr.datamart.ams.usda.gov, no key):
//   LM_XB403 (2453) boxed beef cutout, PM: Choice and Select 600-900
//   LM_PK602 (2498) pork cutout and primals, PM, with loads
//   LM_HG201 (2511) prior-day slaughtered barrows/gilts by purchase type -> negotiated price and a calculated
//                   CME Lean Hog Index (2-day head-weighted avg of producer-sold negotiated, negotiated formula
//                   and swine/pork market formula net carcass prices)
//   LM_CT150 (2477) 5-area weekly negotiated steers (live FOB, dressed delivered)
//   LM_CT100 (2466) 5-area daily negotiated steers (thin early in the week)
import {getJSON, isoUS, num, round} from '../lib.mjs';

const B = 'https://mpr.datamart.ams.usda.gov/services/v1.1/reports';
const DAYS = 300;   // reports of daily history (~14 months, for year-ago comparisons)
const n = v => num(typeof v === 'string' ? v.replace(/,/g, '') : v);
const get = async (path, params = {}) => {
  const q = new URLSearchParams(params).toString().replace(/\+/g, '%20');
  const j = await getJSON(`${B}/${encodeURI(path)}?${q}`, {timeout: 120});   // section names have spaces; "Barrows/Gilts" keeps its slash
  return Array.isArray(j) ? j : (j.results || []);
};
const byDate = (rows, f) => { const m = new Map(); for (const r of rows) { const d = isoUS(r.report_date); if (d) m.set(d, f(r, d)); } return [...m.values()].filter(Boolean).sort((a, b) => a.d < b.d ? -1 : 1); };
const LHI_TYPES = ['Prod. Sold Negotiated', 'Prod. Sold Negotiated Formula', 'Prod. Sold Swine or Pork Market Formula'];

export async function load({keys = {}} = {}) {
  const out = {}, errors = [];
  const tryPart = async (name, fn) => { try { out[name] = await fn(); } catch (e) { errors.push(`${name}: ${e.message.slice(0, 80)}`); } };

  await tryPart('beef', async () => byDate(await get('2453/Current Cutout Values', {lastReports: DAYS}), (r, d) => {
    const c = n(r.choice_600_900_current), s = n(r.select_600_900_current);
    return c ? {d, choice: c, select: s, spread: c && s ? round(c - s, 2) : null} : null;
  }));

  await tryPart('pork', async () => byDate(await get('2498/Cutout and Primal Values', {lastReports: DAYS}), (r, d) => {
    const c = n(r.pork_carcass);
    return c ? {d, carcass: c, loin: n(r.pork_loin), butt: n(r.pork_butt), picnic: n(r.pork_picnic), rib: n(r.pork_rib), ham: n(r.pork_ham), belly: n(r.pork_belly), loads: n(r.total_loads_date_1)} : null;
  }));

  await tryPart('hogs', async () => {
    const rows = await get('2511/Barrows/Gilts', {lastReports: DAYS});
    const days = new Map();   // keyed by slaughter date (for_date_begin)
    for (const r of rows) {
      const d = isoUS(r.for_date_begin || r.report_date); if (!d) continue;
      const x = days.get(d) || {d, types: {}}; x.types[r.purchase_type] = {head: n(r.head_count), net: n(r.avg_net_price), base: n(r.base_price), cw: n(r.avg_carcass_weight), lw: n(r.avg_live_weight)}; days.set(d, x);
    }
    const ser = [...days.values()].sort((a, b) => a.d < b.d ? -1 : 1).map(x => {
      const neg = x.types['Prod. Sold Negotiated'];
      const parts = LHI_TYPES.map(t => x.types[t]).filter(p => p && p.head && p.net);
      return {d: x.d, neg: neg?.net ?? null, negHead: neg?.head ?? null, base: neg?.base ?? null,
        all: x.types['Prod. Sold (All Purchase Types)']?.net ?? null, allHead: x.types['Prod. Sold (All Purchase Types)']?.head ?? null,
        cw: x.types['Prod. Sold (All Purchase Types)']?.cw ?? null,
        _w: parts.reduce((s, p) => s + p.head * p.net, 0), _h: parts.reduce((s, p) => s + p.head, 0),
        // negotiated and swine/pork market formula must be there; USDA withholds the small negotiated-formula
        // price on many days (confidentiality), and then the index is weighted over the two that are published
        _k: x.types['Prod. Sold Negotiated']?.net && x.types['Prod. Sold Swine or Pork Market Formula']?.net ? 1 : 0};
    });
    // 2-day head-weighted index (this day and the previous slaughter day)
    return ser.map((x, i) => {
      const p = ser[i - 1];
      const lhi = p && x._k && p._k ? round((x._w + p._w) / (x._h + p._h), 2) : null;
      const {_w, _h, _k, ...rest} = x; return {...rest, lhi};
    });
  });

  await tryPart('cattleWeekly', async () => {
    const rows = await get('2477/Detail', {q: 'class_description=STEER;grade_description=Total all grades', lastReports: 70});
    const wk = new Map();
    for (const r of rows) {
      const d = isoUS(r.report_date); if (!d) continue;
      const x = wk.get(d) || {d};
      if (r.selling_basis_description === 'LIVE FOB') { x.live = n(r.weighted_avg_price); x.liveHead = n(r.head_count); x.liveWt = n(r.weight_range_avg); }
      if (r.selling_basis_description === 'DRESSED DELIVERED') { x.dressed = n(r.weighted_avg_price); x.dressedHead = n(r.head_count); x.dressedWt = n(r.weight_range_avg); }
      wk.set(d, x);
    }
    return [...wk.values()].filter(x => x.live || x.dressed).sort((a, b) => a.d < b.d ? -1 : 1);
  });

  await tryPart('cattleDaily', async () => {
    const rows = await get('2466/Detail', {q: 'class_description=STEER;grade_description=Total all grades', lastReports: 10});
    const days = new Map();
    for (const r of rows) {
      const d = isoUS(r.report_date); if (!d) continue;
      const x = days.get(d) || {d};
      if (r.selling_basis_description === 'LIVE FOB') { x.live = n(r.weighted_avg_price); x.liveHead = n(r.head_count); x.lo = n(r.price_range_low); x.hi = n(r.price_range_high); }
      if (r.selling_basis_description === 'DRESSED DELIVERED') { x.dressed = n(r.weighted_avg_price); x.dressedHead = n(r.head_count); }
      days.set(d, x);
    }
    return [...days.values()].sort((a, b) => a.d < b.d ? -1 : 1);
  });

  // Planned slaughter.
  //   hogs: LM_HG201 "14-Day Scheduled Swine": head scheduled for delivery to packers on each of the next 14 days
  //         (packer-owned and contracted hogs already lined up). Compared over the next 7 delivery days with the
  //         same window in the report a week and a year earlier.
  //   cattle: LM_CT106 (2656) daily committed and delivered fed cattle: head packers committed to buy for upcoming
  //         delivery, and head delivered that day, each with USDA's week-ago and year-ago figures.
  await tryPart('hogSched', async () => {
    const rows = await get('2511/14-Day Scheduled Swine', {lastReports: 270});
    const reps = new Map();
    for (const r of rows) {
      const rd = isoUS(r.report_date), dd = isoUS(r.delivery_date), h = n(r.head_count); if (!rd || !dd || h == null) continue;
      const x = reps.get(rd) || []; x.push({d: dd, head: h}); reps.set(rd, x);
    }
    const dates = [...reps.keys()].sort(); if (!dates.length) throw new Error('no scheduled swine rows');
    const next7 = rd => { const days = reps.get(rd).filter(x => x.d >= rd).sort((a, b) => a.d < b.d ? -1 : 1);
      return {from: days[0]?.d, to: days[Math.min(6, days.length - 1)]?.d, head: days.slice(0, 7).reduce((s, x) => s + x.head, 0)}; };
    const nearest = target => dates.filter(d => d <= target).pop() || null;
    const last = dates.at(-1), shift = (d, k) => { const t = new Date(d + 'T12:00:00Z'); t.setUTCDate(t.getUTCDate() + k); return t.toISOString().slice(0, 10); };
    const wk = nearest(shift(last, -7)), yr = nearest(shift(last, -364));
    return {report: last, days: reps.get(last).sort((a, b) => a.d < b.d ? -1 : 1),
      next7: next7(last), next7Wk: wk ? {report: wk, ...next7(wk)} : null, next7Yr: yr && yr < shift(last, -300) ? {report: yr, ...next7(yr)} : null,
      // the next-7-day total from each report, for a trend line
      trend: dates.slice(-120).map(d => ({d, head: next7(d).head}))};
  });

  await tryPart('cattleCommit', async () => {
    const rows = await get('2656/Summary', {lastReports: 70});
    const days = new Map();
    for (const r of rows) {
      const d = isoUS(r.report_date_end); if (!d) continue;
      const x = days.get(d) || {d}, k = r.purchasing_basis === 'Committed' ? 'c' : r.purchasing_basis === 'Delivered' ? 'del' : null; if (!k) continue;
      x[k] = n(r.current_volume); x[k + 'Wk'] = n(r.week_ago_volume); x[k + 'Yr'] = n(r.year_ago_volume); days.set(d, x);
    }
    return [...days.values()].sort((a, b) => a.d < b.d ? -1 : 1);
  });

  // Packer gross margins (before kill and processing costs, which are not public). Everything on a carcass basis:
  //   beef $/cwt = Choice cutout + steer drop (dressed equivalent) - 5-area dressed steer price, weekly: the cutout
  //                and drop are averaged over the week the cattle traded (the 7 days before the report date)
  //   pork $/cwt = pork cutout + hog drop (dressed equivalent) - net price of all producer-sold hogs, daily
  //   $/head = $/cwt x the average carcass weight in the same USDA report / 100
  // Drop values: MyMarketNews 2829 (steer, daily) and 2835 (hog, weekly), "Report Totals", needs the MMN key.
  await tryPart('margins', async () => {
    if (!keys.mmn) throw new Error('MMN_API_KEY not set (drop values)');
    const auth = {headers: {Authorization: 'Basic ' + Buffer.from(keys.mmn + ':').toString('base64')}, timeout: 120};
    const drop = async (id, sub) => (await getJSON(`https://marsapi.ams.usda.gov/services/v1.2/reports/${id}/Report%20Totals?lastReports=${id === 2829 ? DAYS : 70}`, auth)).results
      .filter(r => r.sub_Group === sub).map(r => ({d: isoUS(r.report_date), v: n(r.dressed_equivalent_value), live: n(r.total_value)}))
      .filter(x => x.d && x.v).sort((a, b) => a.d < b.d ? -1 : 1);
    const sd = await drop(2829, 'Steer Drop'), hd = await drop(2835, 'Hog Drop');
    const onOrBefore = (ser, d) => { let v = null; for (const x of ser) { if (x.d > d) break; v = x; } return v; };
    const avgIn = (ser, f, from, to) => { const v = ser.filter(x => x.d >= from && x.d < to && x[f] != null).map(x => x[f]); return v.length ? v.reduce((a, b) => a + b, 0) / v.length : null; };
    const shift = (d, k) => { const t = new Date(d + 'T12:00:00Z'); t.setUTCDate(t.getUTCDate() + k); return t.toISOString().slice(0, 10); };

    const beefM = (out.cattleWeekly || []).filter(w => w.dressed && w.dressedWt).map(w => {
      const from = shift(w.d, -7), cut = avgIn(out.beef || [], 'choice', from, w.d), dv = avgIn(sd.map(x => ({d: x.d, v: x.v})), 'v', from, w.d);
      if (cut == null || dv == null) return null;
      const cwt = cut + dv - w.dressed;
      return {d: w.d, cutout: round(cut, 2), drop: round(dv, 2), cattle: w.dressed, wt: w.dressedWt, perCwt: round(cwt, 2), perHead: Math.round(cwt * w.dressedWt / 100)};
    }).filter(Boolean);

    const cutByDay = new Map((out.pork || []).map(x => [x.d, x.carcass]));
    const porkM = (out.hogs || []).filter(h => h.all && h.cw && cutByDay.has(h.d)).map(h => {
      const dv = onOrBefore(hd, shift(h.d, 7));   // the hog drop is dated the Monday of the week it covers
      if (!dv) return null;
      const cwt = cutByDay.get(h.d) + dv.v - h.all;
      return {d: h.d, cutout: cutByDay.get(h.d), drop: dv.v, hog: h.all, wt: h.cw, perCwt: round(cwt, 2), perHead: Math.round(cwt * h.cw / 100)};
    }).filter(Boolean);
    return {beef: beefM, pork: porkM, steerDrop: sd.at(-1) || null, hogDrop: hd.at(-1) || null};
  });

  if (!Object.keys(out).length) throw new Error(errors.join('; '));
  const latest = [out.beef?.at(-1)?.d, out.pork?.at(-1)?.d, out.hogs?.at(-1)?.d].filter(Boolean).sort().pop();
  return {data: out, latest, n: Object.values(out).reduce((s, a) => s + a.length, 0), partial: errors.length > 0,
    note: errors.length ? `missing: ${errors.join('; ')}` : '',
    src: 'USDA AMS Livestock Mandatory Reporting (LM_XB403, LM_PK602, LM_HG201, LM_CT150, LM_CT100)'};
}
