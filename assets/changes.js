// "What changed this week" on the home page: the headline moves from each desk, computed in the browser from the
// desks' own data files (no AI, nothing estimated). A desk whose data is missing is simply left out.
'use strict';
(async () => {
  const box = document.getElementById('week-card');
  if (!box || !window.Desk) return;
  const D = Desk, {fmtN, fmtS, esc} = D;
  const [pos, wa, ex, cp, en, ma] = await Promise.all(['positioning', 'wasde', 'export_sales', 'crop_progress', 'energy', 'macro'].map(D.load));
  const k = v => v == null ? '—' : (Math.abs(v) >= 1000 ? fmtS(v / 1000, 1) + 'k' : fmtS(v, 0));
  const pct = (v, d = 1) => D.ok(v) ? fmtS(v, d) + '%' : '—';
  const sign = v => `<span class="${D.cls(v)}">`;
  const groups = [];

  // ---- positioning: fund flows, crowding, the week's price moves
  const S = pos?.data?.snapshot;
  if (S) {
    const rows = (S.commodities || []).filter(c => !c.stale && c.v?.all?.cats?.managed_money).map(c => ({c, mm: c.v.all.cats.managed_money}));
    const by = (f, d) => rows.slice().sort((a, b) => d * (f(a) - f(b)));
    const L = [];
    const buys = by(r => r.mm.z || 0, -1).filter(r => (r.mm.z || 0) >= 1).slice(0, 3), sells = by(r => r.mm.z || 0, 1).filter(r => (r.mm.z || 0) <= -1).slice(0, 3);
    const fl = r => `<b>${esc(r.c.name)}</b> ${sign(r.mm.dN)}${k(r.mm.dN)}</span> (${fmtS(r.mm.z, 1)}σ)`;
    if (buys.length) L.push(`Biggest fund buying: ${buys.map(fl).join(', ')} contracts.`);
    if (sells.length) L.push(`Biggest fund selling: ${sells.map(fl).join(', ')} contracts.`);
    const hot = rows.filter(r => r.mm.cot3 >= 90).map(r => r.c.name), cold = rows.filter(r => r.mm.cot3 <= 10).map(r => r.c.name);
    if (hot.length || cold.length) L.push(`Crowded on the 3-year COT index: ${hot.length ? `long ${hot.map(esc).join(', ')}` : ''}${hot.length && cold.length ? '; ' : ''}${cold.length ? `short ${cold.map(esc).join(', ')}` : ''}.`);
    const px = (S.commodities || []).filter(c => c.px && D.ok(c.px.r1w)).sort((a, b) => Math.abs(b.px.r1w) - Math.abs(a.px.r1w)).slice(0, 4);
    if (px.length) L.push(`Biggest price moves on the week: ${px.map(c => `${esc(c.name)} ${sign(c.px.r1w)}${pct(c.px.r1w * 100)}</span>`).join(', ')}.`);
    if (L.length) groups.push(['Positioning', 'positioning/', `CFTC report of ${D.dLabel(S.report_date)}`, L]);
  }

  // ---- grains: WASDE revisions, crop progress, export pace
  const L2 = [];
  const W = wa?.data?.commodities;
  if (W) {
    const rv = ['corn', 'soybeans', 'wheat'].map(c => { const u = W[c]?.us; if (!u) return null; const my = Object.keys(u).sort().at(-1), it = u[my].items;
      return it.end_stocks ? `${esc(W[c].label)} ${my} ending stocks ${fmtN(it.end_stocks.value, 0)} ${esc(W[c].unit)} (${sign(it.end_stocks.change)}${fmtS(it.end_stocks.change, 0)}</span>)` : null; }).filter(Boolean);
    if (rv.length) L2.push(`WASDE ${esc(wa.data.report)}: ${rv.join('; ')}.`);
  }
  const C = cp?.data?.crops;
  if (C) {
    const newest = Object.values(C).flatMap(c => (c.progress || []).map(x => x.last?.date)).filter(Boolean).sort().at(-1);
    const recent = d => newest && (new Date(newest) - new Date(d)) / 864e5 <= 21;   // a crop with no report in 3 weeks is out of season
    const pr = ['corn', 'soybeans', 'wheat'].map(c => { const s = (C[c]?.progress || []).filter(x => x.last && recent(x.last.date)).sort((a, b) => a.last.date < b.last.date ? 1 : -1)[0]; if (!s) return null;
      return `${esc(C[c].label)} ${esc(s.stage.toLowerCase())} ${fmtN(s.last.pct, 0)}% (5-yr ${fmtN(s.last.avg5, 0)}%, ${sign(s.last.pct - s.last.avg5)}${fmtS(s.last.pct - s.last.avg5, 0)}</span>)`; }).filter(Boolean);
    if (pr.length) L2.push(`Crop progress (week to ${D.dLabel(newest, {month: 'short', day: 'numeric'})}): ${pr.join('; ')}.`);
  }
  const E = ex?.data?.commodities;
  if (E) {
    const sl = ['corn', 'soybeans', 'wheat'].map(c => { const s = E[c]?.sales; if (!s) return null;
      return `${c} ${fmtN(s.pct_of_usda, 0)}% of USDA (usually ${fmtN(s.avg_pct, 0)}%)`; }).filter(Boolean);
    if (sl.length) L2.push(`Export commitments: ${sl.join(', ')}.`);
  }
  if (L2.length) groups.push(['Grains', 'grains/', '', L2]);

  // ---- energy: inventories against the 5-year average
  const M = en?.data?.markets;
  if (M) {
    const st = ['NG', 'CL', 'HO', 'RB'].filter(s => M[s]).map(s => { const x = M[s].stocks;
      return `${esc(M[s].name.split(' / ').at(-1))} ${sign(x.wow)}${fmtS(x.wow, s === 'NG' ? 0 : 1)}</span> on the week, ${sign(x.dev_pct)}${pct(x.dev_pct)}</span> vs 5-yr`; });
    if (st.length) groups.push(['Energy', 'energy/', `EIA week to ${D.dLabel(M.CL?.stocks?.date || M.NG?.stocks?.date)}`, [`Inventories: ${st.join('; ')}.`]]);
  }

  // ---- macro: rates and Treasury cash
  const R = ma?.data?.rates, Q = ma?.data?.curve, T = ma?.data?.liquidity?.tga;
  if (R || T) {
    const L4 = [];
    if (R?.effr != null) L4.push(`Fed funds ${fmtN(R.target_lo, 2)}–${fmtN(R.target_hi, 2)}%; 2-year ${fmtN(R.y2, 2)}%${Q ? `, 2s10s ${fmtS(Q.s2s10_bp, 0)} bp (${fmtS(Q.s2s10_chg_1m_bp, 0)} in a month)` : ''}.`);
    const z = ma?.data?.policy?.zq;
    if (z?.length) L4.push(`Futures price fed funds at ${fmtN(z.at(-1).rate, 2)}% for ${esc(z.at(-1).m)} (${fmtS(z.at(-1).vs_effr_bp, 0)} bp vs now).`);
    if (T) L4.push(`Treasury cash (TGA) $${fmtN(T.bn, 0)}bn, ${sign(T.chg_1w)}${fmtS(T.chg_1w, 0)}bn</span> on the week.`);
    if (L4.length) groups.push(['Macro', 'macro/', '', L4]);
  }

  if (!groups.length) { box.closest('section')?.remove(); return; }
  box.innerHTML = D.card({title: 'The week across the desks', sub: 'Computed from each desk\'s latest data at every build; follow a heading to the desk.',
    body: groups.map(([h, href, sub, L]) => `<div style="margin-top:6px"><a href="${href}" style="color:var(--text);font-weight:600;text-decoration:none">${h} →</a>${sub ? ` <span class="cs">${sub}</span>` : ''}<ul class="glance" style="margin:2px 0 4px">${L.map(l => `<li>${l}</li>`).join('')}</ul></div>`).join('')});
})();
