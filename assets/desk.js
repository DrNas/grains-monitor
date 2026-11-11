// Shared header, data loading and components for the desk pages (grains/, energy/, ...).
// A page sets <html data-root="../" data-desk="grains">, loads Chart.js, then this file, then its own script.
// Everything is under window.Desk so it cannot clash with a page's own names.
'use strict';
(() => {
  const root = document.documentElement.dataset.root || './';
  const css = v => getComputedStyle(document.documentElement).getPropertyValue(v).trim();
  const esc = s => String(s ?? '').replace(/[&<>"]/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;'})[c]);
  const ok = v => typeof v === 'number' && Number.isFinite(v);
  const fmtN = (v, d = 0) => ok(v) ? v.toLocaleString('en-US', {minimumFractionDigits: d, maximumFractionDigits: d}) : '—';
  const fmtS = (v, d = 0) => { if (!ok(v)) return '—'; const r = +v.toFixed(d); return (r > 0 ? '+' : r < 0 ? '−' : '') + fmtN(Math.abs(r), d); };
  const cls = v => ok(v) && v > 0 ? 'up' : ok(v) && v < 0 ? 'dn' : '';
  const dLabel = (s, o = {month: 'short', day: 'numeric', year: 'numeric'}) => s ? new Date(s.slice(0, 10) + 'T12:00:00Z').toLocaleDateString('en-US', {timeZone: 'UTC', ...o}) : '—';

  // Site navigation: the home page, then one entry per desk. Add a desk here (and in index.html's nav.desks) when its page goes live.
  const DESKS = [['', 'Home'], ['positioning/', 'Positioning'], ['grains/', 'Grains'], ['energy/', 'Energy'], ['macro/', 'Macro'], ['backtests/', 'Backtests']];

  const link = p => {
    if (!window.SITE_OFFLINE) return root + p;
    const m = /^([a-z]+)\/(.*)$/.exec(p);
    return m ? `${m[1]}.html${m[2]}` : `index.html${p}`;
  };

  function header(title) {
    const here = document.documentElement.dataset.desk || '';
    document.querySelector('header').innerHTML = `<div class="hrow">
      <h1><a href="${link('')}" style="color:inherit;text-decoration:none">Grains &amp; Livestock Monitor</a> <span class="muted" style="font-weight:400">· ${esc(title)}</span></h1>
      <nav class="desks">${DESKS.map(([p, n]) => `<a href="${link(p)}"${p === here + '/' || (!here && !p) ? ' class="on"' : ''}>${n}</a>`).join('')}</nav>
      <span class="sp"></span><span class="muted" id="stamp">loading…</span></div>`;
    mountSearch(document.querySelector('header .hrow'));
  }

  // ---- unified search across the desks: sections, markets and common terms. Press "/" to focus.
  const MARKETS = [['CO', 'Brent crude', 'oil'], ['NG', 'Natural gas', 'henry hub gas'], ['CL', 'WTI crude', 'oil crude'], ['HO', 'ULSD diesel heating oil', 'distillate'],
    ['XB', 'RBOB gasoline', 'gasoline'], ['C', 'Corn', 'grain'], ['S', 'Soybeans', 'beans oilseed'], ['SM', 'Soybean meal', 'meal'], ['BO', 'Soybean oil', 'bean oil'],
    ['W', 'Chicago wheat (SRW)', 'wheat'], ['KW', 'KC HRW wheat', 'wheat kansas'], ['HG', 'Copper', 'metals'], ['ALI', 'Aluminum', 'metals'], ['GC', 'Gold', 'metals'],
    ['SI', 'Silver', 'metals'], ['SB', 'Sugar', 'softs'], ['KC', 'Coffee', 'softs arabica'], ['CC', 'Cocoa', 'softs'], ['CT', 'Cotton', 'softs'],
    ['LC', 'Live cattle', 'livestock beef'], ['LH', 'Lean hogs', 'livestock pork']];
  const GRAINS = {C: 'corn', S: 'soybeans', SM: 'meal', BO: 'oil', W: 'wheat', KW: 'wheat'}, ENERGY = {NG: 'NG', CL: 'CL', HO: 'HO', XB: 'RB'};
  const SECTIONS = [
    ['Home', '', 'Daily recap and video', '#recap', 'summary'], ['Home', '', 'What changed this week', '#week', 'summary weekly'],
    ['Home', '', 'Report calendar', '#cal', 'usda wasde crop progress release dates schedule'], ['Home', '', 'Fund positioning (home chart)', '#cot', 'cot managed money'],
    ['Home', '', 'Livestock: slaughter, cutout, cash, packer margin', '#meat', 'cattle hogs beef pork'], ['Home', '', 'Cash grain basis', '#basis', 'bids elevator'],
    ['Home', '', 'Crop and feedlot weather, NOAA outlooks', '#wx', 'rain temperature forecast'], ['Home', '', 'Drought Monitor and ENSO', '#drought', 'el nino la nina'],
    ['Positioning', 'positioning/', 'Desk brief', '#brief-sec', 'cot weekly read'], ['Positioning', 'positioning/', 'Trade ideas, watchlist and scorecard', '#ideas', 'trend carry signals'],
    ['Positioning', 'positioning/', 'Positioning monitor', '#monitor', 'cot index setup score'], ['Positioning', 'positioning/', 'Trigger levels and dollar flows', '#triggers', 'breakout moving average macd atr'],
    ['Positioning', 'positioning/', 'Fund positioning heatmap', '#heat-sec', 'percentile'], ['Positioning', 'positioning/', 'Index traders (CIT)', '#cit', 'commodity index'],
    ['Grains', 'grains/', 'WASDE supply and demand, revisions', '#sd', 'balance sheet ending stocks usda'], ['Grains', 'grains/', 'Crop progress and condition, yield model', '#progress', 'nass planting harvest good excellent'],
    ['Grains', 'grains/', 'Export sales and inspections', '#exports', 'fas fgis buyers commitments'], ['Grains', 'grains/', 'Stocks-to-use vs farm price', '#su', 'price'],
    ['Energy', 'energy/', 'Signal scorecard', '#score', 'eia inventories fair value'], ['Energy', 'energy/?m=NG', 'Natural gas storage', '#mkt', 'eia storage bcf injection withdrawal steo'],
    ['Energy', 'energy/?m=CL', 'Crude oil stocks and Cushing', '#mkt', 'eia wpsr refinery runs brent'], ['Energy', 'energy/?m=HO', 'Distillate stocks and cracks', '#mkt', 'diesel crack spread'],
    ['Energy', 'energy/?m=RB', 'Gasoline stocks and cracks', '#mkt', 'rbob crack spread demand'],
    ['Macro', 'macro/', 'Rates and policy: fed funds, SOFR, yield curve', '#rates', 'fomc fed futures treasury 2s10s breakeven real yield'],
    ['Macro', 'macro/', 'Treasury liquidity: TGA and bill supply', '#liq', 'tga treasury general account bills issuance'],
    ['Macro', 'macro/', 'U.S. economy: inflation, jobs, growth', '#econ', 'cpi ppi pce payrolls unemployment gdp'],
    ['Backtests', 'backtests/', 'What the tests say', '#say', 'findings sharpe noise'], ['Backtests', 'backtests/', 'Top findings and rules across markets', '#top', 'strategy trend cot seasonal'],
  ];
  function searchIndex() {
    const out = SECTIONS.map(([desk, path, label, hash, kw]) => ({desk, label, href: link(path + hash), text: `${desk} ${label} ${kw}`.toLowerCase()}));
    for (const [t, name, kw] of MARKETS) {
      out.push({desk: 'Positioning', label: `${name}: COT history, setup and trade idea`, href: link(`positioning/?m=${t}#detail`), text: `${name} ${kw} ${t} positioning cot`.toLowerCase()});
      out.push({desk: 'Backtests', label: `${name}: every rule`, href: link(`backtests/?m=${t}#mkt`), text: `${name} ${kw} ${t} backtest`.toLowerCase()});
      if (GRAINS[t] && t !== 'KW') out.push({desk: 'Grains', label: `${name}: WASDE, crop, exports`, href: link(`grains/?c=${GRAINS[t]}#sd`), text: `${name} ${kw} grains wasde exports`.toLowerCase()});
      if (ENERGY[t]) out.push({desk: 'Energy', label: `${name}: inventories and fundamentals`, href: link(`energy/?m=${ENERGY[t]}#mkt`), text: `${name} ${kw} energy eia`.toLowerCase()});
    }
    return out;
  }
  function mountSearch(row) {
    if (!row || row.querySelector('.search')) return;
    const box = document.createElement('div');
    box.className = 'search';
    box.innerHTML = '<input type="search" placeholder="Search desks and markets  ( / )" aria-label="Search the desks"><div class="sres" role="listbox" hidden></div>';
    const stamp = row.querySelector('#stamp');
    row.insertBefore(box, stamp || null);
    const input = box.querySelector('input'), list = box.querySelector('.sres'), idx = searchIndex();
    let hits = [], pos = 0;
    const draw = () => {
      list.hidden = !hits.length;
      list.innerHTML = hits.map((h, i) => `<a href="${h.href}" class="${i === pos ? 'on' : ''}"><span class="muted">${esc(h.desk)}</span> ${esc(h.label)}</a>`).join('');
    };
    input.addEventListener('input', () => {
      const q = input.value.trim().toLowerCase().split(/\s+/).filter(Boolean);
      hits = q.length ? idx.filter(h => q.every(w => h.text.includes(w))).slice(0, 12) : [];
      pos = 0; draw();
    });
    input.addEventListener('keydown', e => {
      if (e.key === 'ArrowDown' || e.key === 'ArrowUp') { e.preventDefault(); pos = (pos + (e.key === 'ArrowDown' ? 1 : hits.length - 1)) % Math.max(hits.length, 1); draw(); }
      else if (e.key === 'Enter' && hits[pos]) location.href = hits[pos].href;
      else if (e.key === 'Escape') { input.value = ''; hits = []; draw(); input.blur(); }
    });
    input.addEventListener('blur', () => setTimeout(() => { list.hidden = true; }, 150));
    input.addEventListener('focus', () => { if (hits.length) list.hidden = false; });
    document.addEventListener('keydown', e => { if (e.key === '/' && !/^(INPUT|TEXTAREA|SELECT)$/.test(document.activeElement?.tagName || '')) { e.preventDefault(); input.focus(); } });
  }
  // a desk page opened from search (?m=CL) selects that market
  const param = k => new URLSearchParams(location.search).get(k);

  // Footer shared by the desk pages (the home page has the same lines in its own footer)
  function footer(sources) {
    document.querySelector('main').insertAdjacentHTML('beforeend', `<footer>Data: ${esc(sources)}. Rebuilt by a scheduled job; nothing is estimated or filled in, a missing number shows as —.<br>
      For information only, not investment advice. · <a href="https://manasbafna.com/">manasbafna.com</a></footer>`);
  }

  // Desk data lives in data/<id>.json. Opened as a local file, the page reads the published copy instead.
  // the site's own published address(es), from assets/site-config.js (written by the build; SITE_URLS)
  const PUBLISHED = window.SITE_PUBLISHED || ['https://grains.manasbafna.com/', 'https://drnas.github.io/grains-monitor/'];
  async function load(id) {
    const bases = location.protocol === 'file:' && PUBLISHED.length ? PUBLISHED : [root];
    for (const b of bases) {
      try { const r = await fetch(`${b}data/${id}.json?t=${Math.floor(Date.now() / 3e5)}`); if (r.ok) return await r.json(); } catch (e) {}
    }
    return null;
  }

  // "Updated" stamp in the header, from one or more loaded entries
  function stamp(entries) {
    const e = entries.filter(Boolean);
    const el = document.getElementById('stamp');
    if (!e.length) { el.textContent = 'could not load the data'; return; }
    const built = e.map(x => x.built).sort().at(-1);
    el.innerHTML = `data built ${new Date(built).toLocaleString('en-US', {month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit'})}`
      + e.filter(x => x.state !== 'OK').map(x => ` · <span class="s-${x.state}"><b>${x.state}</b></span> ${esc(x.label)}`).join('');
  }

  // Card: title, subtitle, body, and a footer with the source and how fresh the data is.
  // exp: id of a canvas inside the card that gets a PNG export button.
  function card({id = '', title, sub = '', body = '', entry = null, src = '', asof = '', exp = '', cls: c = ''}) {
    const source = src || entry?.src || '';
    const latest = asof || entry?.latest || '';
    const state = entry && entry.state !== 'OK' ? ` · <span class="s-${entry.state}"><b>${entry.state}</b></span>` : '';
    return `<div class="card ${c}"${id ? ` id="${id}"` : ''}>
      <div class="ct dct"><span>${title}</span>${exp ? `<span class="sp"></span><button class="xbtn" data-png="${exp}" title="Download this chart as a PNG">PNG</button><button class="xbtn" data-svg="${exp}" title="Download this chart as an SVG (vector, for the newsletter)">SVG</button>` : ''}</div>
      ${sub ? `<div class="cs">${sub}</div>` : ''}${body}
      ${source || latest ? `<div class="cf dcf">${source ? `Source: ${esc(source)}` : ''}${latest ? ` · Latest data: ${esc(dLabel(latest))}` : ''}${state}</div>` : ''}
    </div>`;
  }

  // Simple table: cols = [{h, k | f(row), n (numeric), c(row) -> class}]
  function table(cols, rows, {rowAttr} = {}) {
    return `<div class="tw"><table><tr>${cols.map(c => `<th${c.n ? ' class="n"' : ''}>${c.h}</th>`).join('')}</tr>${rows.map(r =>
      `<tr${rowAttr ? ' ' + rowAttr(r) : ''}>${cols.map(c => { const v = c.f ? c.f(r) : r[c.k]; return `<td class="${c.n ? 'n ' : ''}${c.c ? c.c(r) : ''}">${v ?? '—'}</td>`; }).join('')}</tr>`).join('')}</table></div>`;
  }

  // Scorecard tiles: [{label, value, sub, cls}]
  const tiles = items => `<div class="tiles">${items.map(t => `<div class="tile"><div class="cs">${t.label}</div><div class="tv ${t.cls || ''}">${t.value}</div>${t.sub ? `<div class="cs">${t.sub}</div>` : ''}</div>`).join('')}</div>`;

  // Crosshair, the same as on the home page: dotted lines at the pointer with value tags on the axes.
  const crosshair = {
    id: 'crosshair',
    afterEvent(chart, args) {
      const e = args.event, a = chart.chartArea;
      const inside = e.x >= a.left && e.x <= a.right && e.y >= a.top && e.y <= a.bottom;
      chart.$cross = e.type === 'mouseout' || !inside ? null : {x: e.x, y: e.y};
      args.changed = true;
    },
    afterDraw(chart, args, opts) {
      const p = chart.$cross; if (!p) return;
      const {ctx, chartArea: a, scales} = chart, bg = css('--btn-hover'), fg = css('--text');
      ctx.save();
      ctx.setLineDash([3, 3]); ctx.lineWidth = 1; ctx.strokeStyle = css('--muted');
      ctx.beginPath(); ctx.moveTo(p.x, a.top); ctx.lineTo(p.x, a.bottom); ctx.moveTo(a.left, p.y); ctx.lineTo(a.right, p.y); ctx.stroke();
      ctx.setLineDash([]); ctx.font = '11px -apple-system,Segoe UI,Helvetica,Arial,sans-serif'; ctx.textBaseline = 'middle';
      const tag = (text, x, y, align) => {
        const w = ctx.measureText(text).width + 10, h = 17;
        const left = align === 'right' ? x - w : align === 'center' ? Math.min(Math.max(x - w / 2, a.left), a.right - w) : x;
        ctx.fillStyle = bg; ctx.fillRect(left, y - h / 2, w, h);
        ctx.fillStyle = fg; ctx.textAlign = 'left'; ctx.fillText(text, left + 5, y);
      };
      if (opts.x && scales.x) tag(opts.x(scales.x.getValueForPixel(p.x)), p.x, a.bottom + 10, 'center');
      for (const [id, fmt] of Object.entries(opts.y || {})) {
        const sc = scales[id]; if (!sc || sc.options.display === false) continue;
        tag(fmt(sc.getValueForPixel(p.y)), sc.position === 'right' ? sc.left + 2 : sc.right - 2, p.y, sc.position === 'right' ? 'left' : 'right');
      }
      ctx.restore();
    },
  };

  const charts = {};
  function chart(id, cfg) {
    charts[id]?.destroy();
    cfg.plugins = [...(cfg.plugins || []), crosshair];
    cfg.options = {maintainAspectRatio: false, interaction: {mode: 'nearest', axis: 'x', intersect: false}, ...(cfg.options || {})};
    return (charts[id] = new Chart(document.getElementById(id), cfg));
  }

  // PNG export with the page background (a plain toBase64Image is transparent, which looks wrong pasted on white)
  document.addEventListener('click', e => {
    const b = e.target.closest('button[data-png]'); if (!b) return;
    const ch = charts[b.dataset.png]; if (!ch) return;
    const src = ch.canvas, out = document.createElement('canvas');
    out.width = src.width; out.height = src.height + 24 * devicePixelRatio;
    const ctx = out.getContext('2d');
    ctx.fillStyle = css('--card'); ctx.fillRect(0, 0, out.width, out.height);
    ctx.drawImage(src, 0, 0);
    const card = b.closest('.card'), title = card?.querySelector('.ct span')?.textContent || '', foot = card?.querySelector('.dcf')?.textContent || '';
    ctx.fillStyle = css('--muted'); ctx.font = `${11 * devicePixelRatio}px -apple-system,Segoe UI,Helvetica,Arial,sans-serif`;
    ctx.fillText(`${title} · ${foot}`.slice(0, 160), 6 * devicePixelRatio, src.height + 15 * devicePixelRatio);
    const a = document.createElement('a');
    a.href = out.toDataURL('image/png'); a.download = `${b.dataset.png}.png`; a.click();
  });

  // SVG export: the chart is drawn again onto canvas2svg's mock context (loaded on first use), giving real vector
  // paths and text. Shims fill in what that 2014 library lacks for Chart.js 4: resetTransform, line dashes, clip
  // regions and single-quoted font families; a `segment` option makes Chart.js draw lines with plain path commands (no Path2D).
  const C2S_URL = 'https://cdn.jsdelivr.net/npm/canvas2svg@1.0.16/canvas2svg.js';
  let c2sLoad = null;
  const loadC2S = () => c2sLoad ||= new Promise((ok, no) => { const s = document.createElement('script'); s.src = C2S_URL; s.onload = ok; s.onerror = () => { c2sLoad = null; no(new Error('could not load the SVG library')); }; document.head.appendChild(s); });
  async function svgOf(ch, caption) {
    await loadC2S();
    const w = Math.round(ch.width), h = Math.round(ch.height) + 24, ctx = new C2S(w, h), dashes = [];
    ctx.canvas = {getContext: () => ctx, width: w, height: h, style: {}, addEventListener() {}, removeEventListener() {}};
    ctx.resetTransform = function () { this.setTransform(1, 0, 0, 1, 0, 0); };
    ctx.__dash = [];
    ctx.setLineDash = function (a) { this.__dash = (a || []).slice(); };
    ctx.getLineDash = function () { return this.__dash.slice(); };
    const sv = ctx.save, rs = ctx.restore;
    ctx.save = function () { dashes.push(this.__dash); return sv.call(this); };
    ctx.restore = function () { this.__dash = dashes.pop() || []; return rs.call(this); };
    const ap = ctx.__applyStyleToCurrentElement;
    ctx.__applyStyleToCurrentElement = function (t) { ap.call(this, t); if (t === 'stroke' && this.__dash.length) this.__currentElement.setAttribute('stroke-dasharray', this.__dash.join(',')); };
    const cl = ctx.clip;   // the library's clip() forgets to write the current path into the clip region
    ctx.clip = function () { if (this.__currentElement?.nodeName === 'path' && this.__currentDefaultPath) this.__currentElement.setAttribute('d', this.__currentDefaultPath); return cl.call(this); };
    const pf = ctx.__parseFont;
    ctx.__parseFont = function () { const f = this.font; this.font = String(f).replace(/'/g, '"'); try { return pf.call(this); } catch (e) { this.font = '11px sans-serif'; return pf.call(this); } finally { this.font = f; } };
    const frame = {id: 'svgframe',
      beforeDraw(c) { c.ctx.save(); c.ctx.fillStyle = css('--card'); c.ctx.fillRect(0, 0, w, h); c.ctx.restore(); },
      afterDraw(c) { c.ctx.save(); c.ctx.fillStyle = css('--muted'); c.ctx.font = '11px sans-serif'; c.ctx.textBaseline = 'alphabetic'; c.ctx.fillText(caption.length > w / 5.8 ? caption.slice(0, Math.floor(w / 5.8) - 1) + '…' : caption, 6, h - 8); c.ctx.restore(); }};
    const cfg = ch.config, opts = {...cfg.options, animation: false, responsive: false, maintainAspectRatio: false, devicePixelRatio: 1,
      layout: {...(cfg.options.layout || {}), padding: {bottom: 24}}};
    const data = {...cfg.data, datasets: cfg.data.datasets.map(d => ({...d, segment: d.segment || {}}))};
    const c2 = new Chart(ctx, {platform: Chart.BasicPlatform, type: cfg.type, data, options: opts, plugins: [frame]});
    c2.draw();
    const svg = ctx.getSerializedSvg(true);
    c2.destroy();
    return svg;
  }
  document.addEventListener('click', async e => {
    const b = e.target.closest('button[data-svg]'); if (!b) return;
    const ch = charts[b.dataset.svg]; if (!ch) return;
    const card = b.closest('.card'), title = card?.querySelector('.ct span')?.textContent || '', foot = card?.querySelector('.dcf')?.textContent || '';
    const label = b.textContent; b.textContent = '…';
    try {
      const svg = await svgOf(ch, `${title} · ${foot}`);
      const a = document.createElement('a');
      a.href = URL.createObjectURL(new Blob([svg], {type: 'image/svg+xml'})); a.download = `${b.dataset.svg}.svg`; a.click();
      setTimeout(() => URL.revokeObjectURL(a.href), 5000);
    } catch (err) { alert('SVG export failed: ' + err.message); }
    b.textContent = label;
  });

  // Segmented buttons (same look as the home page): calls cb(dataset) on click
  const seg = (el, cb) => el.addEventListener('click', e => { const b = e.target.closest('button'); if (!b) return; el.querySelectorAll('button').forEach(x => x.classList.toggle('on', x === b)); cb(b.dataset); });
  const save = (k, v) => { try { localStorage.setItem('glm_' + k, JSON.stringify(v)); } catch (e) {} };
  const restore = (k, d) => { try { const v = JSON.parse(localStorage.getItem('glm_' + k)); return v ?? d; } catch (e) { return d; } };

  Chart.defaults.color = css('--muted'); Chart.defaults.borderColor = css('--grid'); Chart.defaults.font.size = 11;
  Chart.defaults.plugins.legend.labels.boxWidth = 12; Chart.defaults.animation = false;

  window.Desk = {root, link, css, esc, ok, fmtN, fmtS, cls, dLabel, header, footer, load, stamp, card, table, tiles, chart, seg, save, restore, param, mountSearch, svgOf, charts};
})();
