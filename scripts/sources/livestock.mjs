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

export async function load() {
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
      const x = days.get(d) || {d, types: {}}; x.types[r.purchase_type] = {head: n(r.head_count), net: n(r.avg_net_price), base: n(r.base_price)}; days.set(d, x);
    }
    const ser = [...days.values()].sort((a, b) => a.d < b.d ? -1 : 1).map(x => {
      const neg = x.types['Prod. Sold Negotiated'];
      const parts = LHI_TYPES.map(t => x.types[t]).filter(p => p && p.head && p.net);
      return {d: x.d, neg: neg?.net ?? null, negHead: neg?.head ?? null, base: neg?.base ?? null,
        all: x.types['Prod. Sold (All Purchase Types)']?.net ?? null,
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
      if (r.selling_basis_description === 'DRESSED DELIVERED') { x.dressed = n(r.weighted_avg_price); x.dressedHead = n(r.head_count); }
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

  if (!Object.keys(out).length) throw new Error(errors.join('; '));
  const latest = [out.beef?.at(-1)?.d, out.pork?.at(-1)?.d, out.hogs?.at(-1)?.d].filter(Boolean).sort().pop();
  return {data: out, latest, n: Object.values(out).reduce((s, a) => s + a.length, 0), partial: errors.length > 0,
    note: errors.length ? `missing: ${errors.join('; ')}` : '',
    src: 'USDA AMS Livestock Mandatory Reporting (LM_XB403, LM_PK602, LM_HG201, LM_CT150, LM_CT100)'};
}
