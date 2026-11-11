/* Positioning analysis engine, adapted with permission from an existing open-source desk (dollar-free CIT text added). */
/* ===========================================================
   COT INSIGHTS — trader-style read of the weekly positioning snapshot
   -----------------------------------------------------------
   Pure functions over data/web/snapshot.json. No network.

   Per market (Managed Money = specs, Producer/Merchant = commercials):
     • Regime      — COT Index (Williams) over the chosen look-back
     • Flow        — w/w net change split into new longs / long liquidation /
                     new shorts / short covering; size as a z-score of weekly
                     changes over 3y; buying/selling streak; OI confirmation
     • Commercials — producer/merchant net percentile vs specs (divergence)
     • Risk flags  — squeeze fuel (big gross short base, covering started),
                     liquidation risk (big gross long base, longs exiting)
     • Setup score — −100…+100 contrarian score, tempered by flow: a crowded
                     short still being sold hard is not yet a long setup.
   This is a positioning read, not a price forecast.
   =========================================================== */
var COTInsights = (function () {
  /* from the source's data-store.js (a page-wide helper there) */
  function fmtDate(iso) { if (!iso) return '–'; var d = new Date(iso + 'T12:00:00Z'); return d.toLocaleDateString('en-US', { timeZone: 'UTC', month: 'short', day: 'numeric', year: 'numeric' }); }
  var WIN_LBL = { f: 'since 2006', y5: '5y', y3: '3y', y1: '1y' };

  function k(n) { if (n == null) return '–'; var a = Math.abs(n); return (n < 0 ? '−' : '') + (a >= 1e6 ? (a / 1e6).toFixed(2) + 'M' : a >= 1000 ? (a / 1000).toFixed(1) + 'k' : String(Math.round(a))); }
  function sk(n) { return (n > 0 ? '+' : '') + k(n); }
  function ord(p) { if (p == null) return '–'; var r = Math.round(p); var s = (r % 100 >= 11 && r % 100 <= 13) ? 'th' : ({ 1: 'st', 2: 'nd', 3: 'rd' }[r % 10] || 'th'); return r + s; }
  function clamp(v, a, b) { return Math.max(a, Math.min(b, v)); }

  function cotIdx(c, win) {
    if (win === 'y3') return c.cot3; if (win === 'y1') return c.cot1; if (win === 'y5') return c.cot5;
    var r = c.r && c.r.N; if (!r || r[1] === r[0]) return 50;
    return Math.round((c.N - r[0]) / (r[1] - r[0]) * 1000) / 10;
  }

  function regime(cot) {
    if (cot >= 90) return { key: 'xl', lbl: 'Extreme long', tone: 'bear' };
    if (cot >= 75) return { key: 'sl', lbl: 'Stretched long', tone: 'bear' };
    if (cot <= 10) return { key: 'xs', lbl: 'Extreme short', tone: 'bull' };
    if (cot <= 25) return { key: 'ss', lbl: 'Stretched short', tone: 'bull' };
    if (cot >= 60) return { key: 'nl', lbl: 'Neutral, long lean', tone: 'flat' };
    if (cot <= 40) return { key: 'ns', lbl: 'Neutral, short lean', tone: 'flat' };
    return { key: 'n', lbl: 'Neutral', tone: 'flat' };
  }

  function flowSize(z) { var a = Math.abs(z || 0); return a >= 2 ? 'heavy' : a >= 1.25 ? 'strong' : a >= 0.5 ? 'moderate' : 'light'; }

  /* Decompose the weekly net change into its gross components */
  function driver(c) {
    var dL = c.dL || 0, dS = c.dS || 0, parts = [];
    var newL = Math.max(dL, 0), liqL = Math.max(-dL, 0), newS = Math.max(dS, 0), cov = Math.max(-dS, 0);
    var main, tag;
    if ((c.dN || 0) >= 0) {
      if (cov >= newL) { main = 'short covering'; tag = 'cover'; } else { main = 'new buying'; tag = 'buy'; }
    } else {
      if (liqL >= newS) { main = 'long liquidation'; tag = 'liq'; } else { main = 'fresh shorting'; tag = 'short'; }
    }
    if (newL) parts.push('longs ' + sk(newL)); if (liqL) parts.push('longs ' + sk(-liqL));
    if (newS) parts.push('shorts ' + sk(newS)); if (cov) parts.push('shorts ' + sk(-cov));
    return { main: main, tag: tag, detail: parts.join(', '), grossIn: newL + newS, grossOut: liqL + cov };
  }

  function analyzeOne(cm, crop, win) {
    var v = cm.v[crop] || cm.v.all; if (!v) return null;
    var mm = v.cats.managed_money, pm = v.cats.prod_merc, sd = v.cats.swap_dealers;
    if (!mm || mm.N == null) return null;
    var cot = cotIdx(mm, win), pN = mm.p.N[win], pmP = pm ? pm.p.N[win] : null;
    var reg = regime(cot), drv = driver(mm), size = flowSize(mm.z);
    var rng = mm.r.N[1] - mm.r.N[0];
    var mv4 = rng > 0 ? (mm.dN4 || 0) / rng * 100 : 0; /* 4-week move as % of historical range */
    var flags = [];

    /* commercial divergence */
    var comm = null;
    if (pmP != null) {
      if (pN >= 80 && pmP <= 20) comm = { tone: 'bear', txt: 'commercials hedging heavily into spec length (P/M net ' + ord(pmP) + ' pct)' };
      else if (pN <= 20 && pmP >= 80) comm = { tone: 'bull', txt: 'commercials buying into spec selling (P/M net ' + ord(pmP) + ' pct)' };
    }
    /* squeeze fuel / liquidation risk */
    var pS = mm.p.S[win], pL = mm.p.L[win], pTS = mm.p.TS ? mm.p.TS.y3 : null, pTL = mm.p.TL ? mm.p.TL.y3 : null;
    if (pS >= 85) flags.push({ tone: 'bull', key: 'squeeze', txt: 'large spec short base (gross shorts ' + ord(pS) + ' pct' + (pTS != null && pTS >= 75 ? ', ' + mm.TS + ' short traders' : '') + ')' + ((mm.dS || 0) < -0.02 * mm.S ? ' — covering has started' : '') });
    if (pL >= 85) flags.push({ tone: 'bear', key: 'liq', txt: 'large spec long base (gross longs ' + ord(pL) + ' pct' + (pTL != null && pTL >= 75 ? ', ' + mm.TL + ' long traders' : '') + ')' + ((mm.dL || 0) < -0.02 * mm.L ? ' — longs starting to exit' : '') });
    if (Math.abs(mm.streak) >= 4) flags.push({ tone: mm.streak > 0 ? 'bull' : 'bear', key: 'streak', txt: Math.abs(mm.streak) + ' straight weeks of net ' + (mm.streak > 0 ? 'buying' : 'selling') });
    if (Math.abs(mv4) >= 25) flags.push({ tone: mv4 > 0 ? 'bull' : 'bear', key: 'fast', txt: 'fast repositioning: ' + Math.round(Math.abs(mv4)) + '% of the historical range in 4 weeks' });

    /* OI confirmation */
    var oiTxt = '';
    if (v.doi != null && v.oi) {
      var oiPct = v.doi / v.oi * 100;
      if (Math.abs(oiPct) >= 1) {
        if (v.doi > 0 && drv.grossIn > drv.grossOut) oiTxt = 'new money coming in (OI ' + sk(v.doi) + ')';
        else if (v.doi < 0 && drv.grossOut > drv.grossIn) oiTxt = 'positions being closed out (OI ' + sk(v.doi) + ')';
      }
    }

    /* setup score: contrarian base + commercial confirmation + flow timing */
    var s = (50 - cot) * 1.0;
    if (pmP != null) s += (pmP - 50) * 0.4;
    var z = mm.z || 0;
    if (cot <= 25 && mm.dN > 0) s += 8 + Math.min(12, z * 5);           /* turning up from a short extreme */
    if (cot >= 75 && mm.dN < 0) s -= 8 + Math.min(12, -z * 5);          /* rolling over from a long extreme */
    if (cot <= 25 && z <= -1) s -= 15;                                   /* still being sold hard: wait */
    if (cot >= 75 && z >= 1) s += 15;                                    /* still being bought hard: wait */
    s = Math.round(clamp(s, -100, 100));
    var setup = s >= 45 ? { lbl: 'Contrarian long setup', tone: 'bull' } : s >= 25 ? { lbl: 'Bullish lean', tone: 'bull' }
      : s <= -45 ? { lbl: 'Contrarian short setup', tone: 'bear' } : s <= -25 ? { lbl: 'Bearish lean', tone: 'bear' } : { lbl: 'No clear edge', tone: 'flat' };

    /* the one-line read */
    var side = mm.N >= 0 ? 'long' : 'short';
    var read = reg.lbl + ': funds net ' + side + ' ' + k(Math.abs(mm.N)) + ' (' + ord(pN) + ' pct ' + WIN_LBL[win] + ', COT index ' + Math.round(cot) + '). ';
    if (Math.abs(mm.dN || 0) > 0) read += (mm.dN > 0 ? 'Net bought ' : 'Net sold ') + k(Math.abs(mm.dN)) + ' w/w (' + size + ', ' + (z >= 0 ? '+' : '−') + Math.abs(z).toFixed(1) + 'σ), mainly ' + drv.main + (oiTxt ? '; ' + oiTxt : '') + '. ';
    if (comm) read += 'Note ' + comm.txt + '. ';
    var hot = flags.filter(function (f) { return f.key === 'squeeze' || f.key === 'liq'; })[0];
    if (hot) read += 'Watch: ' + hot.txt + '.';

    return {
      name: cm.name, ticker: cm.ticker, sector: cm.sector, isCrop: cm.is_crop, crop: crop, date: v.date, stale: cm.stale,
      mm: mm, pm: pm, sd: sd, oi: v.oi, doi: v.doi, cot: cot, pN: pN, pmP: pmP, reg: reg, drv: drv, size: size,
      z: z, mv4: mv4, comm: comm, flags: flags, oiTxt: oiTxt, score: s, setup: setup, read: read.trim()
    };
  }

  function analyze(snap, opts) {
    opts = opts || {}; var win = opts.win || 'y3', crop = opts.crop || 'all';
    var rows = [];
    (snap.commodities || []).forEach(function (cm) {
      if (cm.stale && !opts.includeStale) return;
      var ct = (crop !== 'all' && cm.v[crop]) ? crop : 'all';
      var r = analyzeOne(cm, ct, win); if (r) rows.push(r);
    });

    /* sector roll-up */
    var secs = {};
    rows.forEach(function (r) {
      var s = secs[r.sector] || (secs[r.sector] = { sector: r.sector, n: 0, cot: 0, buy: 0, sell: 0, dnp: 0, names: [] });
      s.n++; s.cot += r.cot; s.dnp += (r.mm.dnp || 0); if (r.mm.dN > 0) s.buy++; else if (r.mm.dN < 0) s.sell++; s.names.push(r.name);
    });
    var sectors = Object.keys(secs).map(function (k2) { var s = secs[k2]; s.cot = s.cot / s.n; return s; });

    var by = function (f, dir) { return rows.slice().sort(function (a, b) { return dir * (f(a) - f(b)); }); };
    var buys = rows.filter(function (r) { return r.mm.dN > 0; }).length, sells = rows.filter(function (r) { return r.mm.dN < 0; }).length;
    return {
      win: win, crop: crop, date: snap.report_date, rows: rows, sectors: sectors,
      breadth: { buys: buys, sells: sells, n: rows.length },
      cit: snap.cit_agg || null,
      topBuys: by(function (r) { return r.z; }, -1).filter(function (r) { return r.z >= 0.75; }).slice(0, 4),
      topSells: by(function (r) { return r.z; }, 1).filter(function (r) { return r.z <= -0.75; }).slice(0, 4),
      crowdedLong: by(function (r) { return r.cot; }, -1).filter(function (r) { return r.cot >= 80; }).slice(0, 5),
      crowdedShort: by(function (r) { return r.cot; }, 1).filter(function (r) { return r.cot <= 20; }).slice(0, 5),
      longSetups: by(function (r) { return r.score; }, -1).filter(function (r) { return r.score >= 45; }),
      shortSetups: by(function (r) { return r.score; }, 1).filter(function (r) { return r.score <= -45; }),
      squeeze: rows.filter(function (r) { return r.flags.some(function (f) { return f.key === 'squeeze'; }); }),
      liqRisk: rows.filter(function (r) { return r.flags.some(function (f) { return f.key === 'liq'; }); }),
      divergences: rows.filter(function (r) { return r.comm; })
    };
  }

  /* ---------- narrative ---------- */
  function names(arr, fmt) { return arr.map(fmt || function (r) { return r.name; }).join(', '); }
  function brief(a) {
    var L = [], W = WIN_LBL[a.win];
    var b = a.breadth, tilt;
    if (b.buys > b.sells * 1.5) tilt = 'risk-on: funds were net buyers in ' + b.buys + ' of ' + b.n + ' markets';
    else if (b.sells > b.buys * 1.5) tilt = 'risk-off: funds were net sellers in ' + b.sells + ' of ' + b.n + ' markets';
    else tilt = 'mixed: ' + b.buys + ' markets net bought, ' + b.sells + ' net sold';
    L.push({ h: 'Tape', t: 'Week ending ' + fmtDate(a.date) + ' — spec flow was ' + tilt + '.' });
    var sec = a.sectors.slice().sort(function (x, y) { return y.dnp - x.dnp; });
    if (sec.length > 1) {
      var top = sec[0], bot = sec[sec.length - 1];
      L.push({ h: 'Sectors', t: 'Strongest spec inflow in ' + top.sector + ' (' + (top.dnp >= 0 ? '+' : '') + top.dnp.toFixed(1) + ' pts of OI), weakest in ' + bot.sector + ' (' + (bot.dnp >= 0 ? '+' : '') + bot.dnp.toFixed(1) + ' pts). Most crowded sector by COT index: ' + a.sectors.slice().sort(function (x, y) { return y.cot - x.cot; })[0].sector + '; least: ' + a.sectors.slice().sort(function (x, y) { return x.cot - y.cot; })[0].sector + '.' });
    }
    var fl = [];
    if (a.topBuys.length) fl.push('biggest buying in ' + names(a.topBuys, function (r) { return r.name + ' (' + sk(r.mm.dN) + ', ' + r.drv.main + ', +' + r.z.toFixed(1) + 'σ)'; }));
    if (a.topSells.length) fl.push('biggest selling in ' + names(a.topSells, function (r) { return r.name + ' (' + sk(r.mm.dN) + ', ' + r.drv.main + ', −' + Math.abs(r.z).toFixed(1) + 'σ)'; }));
    if (fl.length) L.push({ h: 'Flows', t: fl.join('; ') + '.' });
    var cr = [];
    if (a.crowdedLong.length) cr.push('crowded long: ' + names(a.crowdedLong, function (r) { return r.name + ' (' + Math.round(r.cot) + ')'; }));
    if (a.crowdedShort.length) cr.push('crowded short: ' + names(a.crowdedShort, function (r) { return r.name + ' (' + Math.round(r.cot) + ')'; }));
    if (cr.length) L.push({ h: 'Crowding', t: 'COT index ' + W + ' — ' + cr.join('; ') + '.' });
    var st = [];
    if (a.longSetups.length) st.push('long side: ' + names(a.longSetups, function (r) { return r.name + ' (' + r.score + ')'; }));
    if (a.shortSetups.length) st.push('short side: ' + names(a.shortSetups, function (r) { return r.name + ' (' + r.score + ')'; }));
    L.push({ h: 'Contrarian setups', t: st.length ? st.join('; ') + '. Score blends crowding, commercial positioning and whether flow has started to turn.' : 'none — no market combines extreme positioning with a confirming turn in flow this week.' });
    var rk = [];
    if (a.squeeze.length) rk.push('short-squeeze fuel in ' + names(a.squeeze));
    if (a.liqRisk.length) rk.push('long-liquidation risk in ' + names(a.liqRisk));
    if (a.divergences.length) rk.push('spec/commercial divergence in ' + names(a.divergences, function (r) { return r.name + ' (' + (r.comm.tone === 'bull' ? 'bullish' : 'bearish') + ')'; }));
    if (rk.length) L.push({ h: 'Risk map', t: rk.join('; ') + '.' });
    var ci = a.cit;
    if (ci) {
      var pf = function (v) { return (v >= 0 ? '+' : '') + v.toFixed(2); };
      var usd = function (v) { if (v == null) return '–'; var x = Math.abs(v); return (v < 0 ? '−' : '+') + '$' + (x >= 1e9 ? (x / 1e9).toFixed(2) + 'bn' : (x / 1e6).toFixed(0) + 'm'); };
      var usdL = function (v) { if (v == null) return '–'; return '$' + (Math.abs(v) >= 1e9 ? (v / 1e9).toFixed(1) + 'bn' : (v / 1e6).toFixed(0) + 'm'); };
      var T = ci.total || {};
      /* adapted: without futures prices there are no dollar figures, so report contracts instead */
      var t = T.Nusd == null
        ? 'Index traders (CIT, ' + ci.n + ' ag markets) are net long ' + k(T.N) + ' contracts. Week: index ' + sk(T.dN) + ' lots vs managed money ' + sk(T.mmdN) + ' lots. '
        : 'Index traders (CIT, ' + ci.n + ' ag markets) are net long ' + usdL(T.Nusd) + ' (long ' + usdL(T.Lusd) + ', short ' + usdL(T.Susd) + '). ' +
          'Week: index ' + usd(T.dNusd) + ' (' + sk(T.dN) + ' lots) vs managed money ' + usd(T.mmdNusd) + ' (' + sk(T.mmdN) + ' lots). ';
      var secs = Object.keys(ci.sectors || {}).map(function (k2) { var x = ci.sectors[k2]; return T.Nusd == null ? k2 + ' index ' + sk(x.dN) + ' / funds ' + sk(x.mmdN) + ' lots' : k2 + ' index ' + usd(x.dNusd) + ' / funds ' + usd(x.mmdNusd); });
      if (secs.length) t += 'By sector: ' + secs.join('; ') + '. ';
      var mk = (ci.markets || []).filter(function (m) { return m.dNusd != null; }).sort(function (x, y) { return y.dNusd - x.dNusd; });
      if (mk.length) t += 'Biggest index buying: ' + mk.slice(0, 3).filter(function (m) { return m.dNusd > 0; }).map(function (m) { return m.name + ' ' + usd(m.dNusd); }).join(', ') +
        '; selling: ' + mk.slice(-3).reverse().filter(function (m) { return m.dNusd < 0; }).map(function (m) { return m.name + ' ' + usd(m.dNusd); }).join(', ') + '. ';
      t += 'Over 4 weeks index money added in ' + ci.adding4 + ' of ' + ci.n + ' markets' + (ci.breadth4_pct != null ? ' (breadth ' + ord(ci.breadth4_pct) + ' percentile)' : '') + '.' +
        (ci.rebal ? ' January reweight window: moves this week are mostly mechanical rebalancing.' :
          (ci.adding4 >= Math.ceil(ci.n * 0.75) ? ' Broad-based adding = allocation flow into the complex.' :
           ci.adding4 <= Math.floor(ci.n * 0.25) ? ' Broad-based cutting = allocation flow out of the complex.' : ''));
      L.push({ h: 'Index flows', t: t });
    }
    return L;
  }

  /* Rows for league tables & scatter plots: percentiles of P/M and MM positions
     over look-back `win`, both in contracts and as % of OI. Stale markets skipped. */
  function scatterRows(snap, win, crop) {
    win = win || 'f'; var out = [], idx = 0;
    (snap.commodities || []).forEach(function (cm) {
      var i = idx++; if (cm.stale) return;
      var v = (crop && crop !== 'all' && cm.v[crop]) ? cm.v[crop] : cm.v.all; if (!v) return;
      var mm = v.cats.managed_money, pm = v.cats.prod_merc; if (!mm || !pm) return;
      out.push({
        comm: cm.name, ticker: cm.ticker, idx: i,
        pSP: pm.p.S[win], mSP: mm.p.S[win], pLP: pm.p.L[win], mLP: mm.p.L[win], pNP: pm.p.N[win], mNP: mm.p.N[win],
        pS: pm.S, mS: mm.S, pL: pm.L, mL: mm.L, pN: pm.N, mN: mm.N,
        mSPoi: mm.p.sp[win], mLPoi: mm.p.lp[win], mNPoi: mm.p.np[win],
        pSPo: pm.p.sp[win], mSPo: mm.p.sp[win], pLPo: pm.p.lp[win], mLPo: mm.p.lp[win], pNPo: pm.p.np[win], mNPo: mm.p.np[win],
        pSo: pm.sp, mSo: mm.sp, pLo: pm.lp, mLo: mm.lp, pNo: pm.np, mNo: mm.np,
        mDN: mm.dN, mZ: mm.z, pDN: pm.dN
      });
    });
    return out;
  }

  /* ===========================================================
     TRADE IDEAS — research rules first, positioning & technicals second
     -----------------------------------------------------------
     1. Trend (time-series momentum; Moskowitz–Ooi–Pedersen, Baltas): sign of the
        12m return, confirmed by the 6m return and price vs 200-day. Partial
        confirmation = half weight.
     2. Carry (Gorton–Hayashi–Rouwenhorst, Erb–Harvey): front vs same month next
        year, annualised. Ignored on seasonal curves (NG, cattle, hogs; Fama–French).
        Trend+carry agree → full size; trend alone → half; conflict → flat.
     3. Size: inverse volatility (60d realised), 10% vol target per full position,
        capped (half-Kelly spirit); halved in an equity risk-off regime
        (S&P < 200d and VIX > 25; Daniel–Moskowitz crash risk).
     4. COT overlay: trend trades into crowded positioning are cut in half;
        contrarian COT setups become tactical ideas only once price confirms
        (close > 20d SMA and 4w return turning in the setup's direction).
     5. Levels: stop 2×ATR(14), target 2R; RSI flags stretched entries.
     Ideas are a systematic read of positioning + price, not advice.
     =========================================================== */
  var CARRY_MIN = 0.02, VOL_TARGET = 0.10, MAX_W = 2.0;
  function pctf(x, d) { return x == null ? '–' : (x >= 0 ? '+' : '−') + Math.abs(x * 100).toFixed(d == null ? 1 : d) + '%'; }
  function pxf(v) { if (v == null) return '–'; var a = Math.abs(v); return a >= 1000 ? v.toFixed(0) : a >= 100 ? v.toFixed(1) : a >= 10 ? v.toFixed(2) : v.toFixed(3); }

  function ideas(snap, a) {
    var reg = snap.regime || {}, riskOff = !!reg.risk_off, out = [], flat = [], watch = [], board = [];
    var byTk = {}; a.rows.forEach(function (r) { byTk[r.ticker] = r; });
    (snap.commodities || []).forEach(function (cm) {
      var r = byTk[cm.ticker], px = cm.px; if (!r || !px || px.close == null) return;
      var t = px.trend || 0, dir = t > 0 ? 1 : t < 0 ? -1 : 0;
      var cy = px.carry, cAnn = cy && cy.ann != null ? cy.ann : null;
      var cSig = (cAnn == null || cy.seasonal || Math.abs(cAnn) < CARRY_MIN) ? 0 : (cAnn > 0 ? 1 : -1);
      var cTxt = cAnn == null ? 'carry n/a' : (cy.seasonal ? 'carry ignored (seasonal curve)' : (cAnn > 0 ? 'backwardation ' : 'contango ') + pctf(cAnn) + '/yr (' + cy.front + ' vs ' + cy.deferred + ')');
      var base = 0, rule;
      if (!dir) rule = 'no trend';
      else if (cSig === dir) { base = 1; rule = 'trend + carry agree'; }
      else if (cSig === 0) { base = 0.5; rule = 'trend only'; }
      else rule = 'trend and carry conflict';
      var size = base * Math.abs(t);
      var notes = [], crowdAgainst = false;
      if (size > 0) {
        if (dir > 0 && r.cot >= 85) { size *= 0.5; crowdAgainst = true; notes.push('funds already crowded long (COT idx ' + Math.round(r.cot) + ') — size halved'); }
        if (dir < 0 && r.cot <= 15) { size *= 0.5; crowdAgainst = true; notes.push('funds already crowded short (COT idx ' + Math.round(r.cot) + ') — size halved'); }
        if (dir > 0 && r.cot <= 35) notes.push('room for funds to buy: positioning light (COT idx ' + Math.round(r.cot) + ')');
        if (dir < 0 && r.cot >= 65) notes.push('liquidation fuel: funds still long (COT idx ' + Math.round(r.cot) + ')');
        if (riskOff) { size *= 0.5; notes.push('risk-off regime (S&P < 200d, VIX ' + reg.vix + ') — size halved'); }
      }
      var vol = px.rv60 || px.rv20 || null;
      var w = vol ? Math.min(MAX_W, VOL_TARGET / vol) * size : 0;
      var row = { name: cm.name, ticker: cm.ticker, sector: cm.sector, px: px, trend: t, dir: dir, carry: cAnn, cTxt: cTxt, rule: rule, size: size, vol: vol, w: w, cot: r.cot, r: r };
      board.push(row);

      var lv = function (d, mult) {
        var atr = px.atr || 0, stop = px.close - d * 2 * atr, tgt = px.close + d * 4 * atr;
        return { entry: px.close, stop: stop, target: tgt, stopPct: (stop / px.close - 1), tgtPct: (tgt / px.close - 1) };
      };
      var tech = [];
      if (px.rsi != null) {
        if (px.rsi >= 70) tech.push('RSI ' + px.rsi.toFixed(0) + ' overbought');
        else if (px.rsi <= 30) tech.push('RSI ' + px.rsi.toFixed(0) + ' oversold');
        else tech.push('RSI ' + px.rsi.toFixed(0));
      }
      if (px.rng52 != null && px.rng52 >= 95) tech.push('at top of 52-wk range');
      if (px.rng52 != null && px.rng52 <= 5) tech.push('at bottom of 52-wk range');
      if (px.sma20) tech.push(px.close > px.sma20 ? 'above 20d SMA' : 'below 20d SMA');

      if (size > 0) {
        var stretched = (dir > 0 && px.rsi >= 70) || (dir < 0 && px.rsi <= 30);
        var conv = size >= 0.75 && !crowdAgainst ? 'High' : size >= 0.4 ? 'Medium' : 'Low';
        out.push({
          kind: 'Systematic', side: dir > 0 ? 'LONG' : 'SHORT', dir: dir, row: row, conv: conv, lv: lv(dir),
          why: [
            'Trend (roll-adjusted): 12m ' + pctf(px.r52w) + ', 6m ' + pctf(px.r26w) + ', ' + pctf(px.vs200) + ' vs 200d' + (Math.abs(t) < 1 ? ' — partial confirmation' : ''),
            'Carry: ' + cTxt + ' → ' + rule,
            'COT: ' + r.reg.lbl.toLowerCase() + ', ' + (r.mm.dN >= 0 ? 'net bought ' : 'net sold ') + COTInsights.k(Math.abs(r.mm.dN)) + ' w/w (' + r.drv.main + ')',
            'Technicals: ' + tech.join(', ')
          ].concat(notes),
          timing: stretched ? 'Stretched (RSI ' + px.rsi.toFixed(0) + ') — better entry on a pullback toward the 20d SMA ' + pxf(px.sma20) + '.' : 'Entry at market is consistent with the rules.'
        });
      } else {
        var cs = r.score;
        var confirmUp = px.close > px.sma20 && (px.r4w || 0) > 0, confirmDn = px.close < px.sma20 && (px.r4w || 0) < 0;
        if (cs >= 45 || cs <= -45) {
          var d2 = cs > 0 ? 1 : -1, ok = d2 > 0 ? confirmUp : confirmDn;
          var item = {
            kind: 'Tactical (COT contrarian)', side: d2 > 0 ? 'LONG' : 'SHORT', dir: d2, row: row, conv: ok ? 'Low' : 'Watch', lv: lv(d2),
            why: ['COT: ' + r.read, 'Price: 4w ' + pctf(px.r4w) + ', ' + (px.close > px.sma20 ? 'above' : 'below') + ' 20d SMA (' + pxf(px.sma20) + '); trend rule says ' + rule + (dir ? ' (' + (dir > 0 ? 'up' : 'down') + ')' : ''), 'Technicals: ' + tech.join(', ')],
            timing: ok ? 'Price has started to confirm the positioning turn — small tactical size only; the 12m trend is not on side.' : 'Not yet confirmed by price — wait for a close ' + (d2 > 0 ? 'above' : 'below') + ' the 20d SMA (' + pxf(px.sma20) + ') with the 4-week return turning ' + (d2 > 0 ? 'positive' : 'negative') + '.'
          };
          if (ok) { item.row = Object.assign({}, row, { size: 0.25, w: vol ? Math.min(MAX_W, VOL_TARGET / vol) * 0.25 : 0 }); out.push(item); }
          else watch.push(item);
        } else flat.push(row);
      }
    });
    var totW = out.reduce(function (s, i) { return s + (i.row.w || 0); }, 0) || 1;
    out.forEach(function (i) { i.riskShare = (i.row.w || 0) / totW; });
    var rank = { High: 3, Medium: 2, Low: 1, Watch: 0 };
    out.sort(function (x, y) { return (rank[y.conv] - rank[x.conv]) || (y.riskShare - x.riskShare); });
    return { ideas: out, watch: watch, flat: flat, board: board, regime: reg, riskOff: riskOff, pricesAt: snap.prices_fetched };
  }

  return { analyze: analyze, brief: brief, scatterRows: scatterRows, ideas: ideas, pctf: pctf, pxf: pxf, k: k, sk: sk, ord: ord, WIN_LBL: WIN_LBL, cotIdx: cotIdx };
})();
