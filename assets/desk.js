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
  const DESKS = [['', 'Home'], ['positioning/', 'Positioning'], ['grains/', 'Grains'], ['energy/', 'Energy'], ['macro/', 'Macro']];

  function header(title) {
    const here = document.documentElement.dataset.desk || '';
    document.querySelector('header').innerHTML = `<div class="hrow">
      <h1><a href="${root}" style="color:inherit;text-decoration:none">Grains &amp; Livestock Monitor</a> <span class="muted" style="font-weight:400">· ${esc(title)}</span></h1>
      <nav class="desks">${DESKS.map(([p, n]) => `<a href="${root}${p}"${p === here + '/' || (!here && !p) ? ' class="on"' : ''}>${n}</a>`).join('')}</nav>
      <span class="sp"></span><span class="muted" id="stamp">loading…</span></div>`;
  }

  // Footer shared by the desk pages (the home page has the same lines in its own footer)
  function footer(sources) {
    document.querySelector('main').insertAdjacentHTML('beforeend', `<footer>Data: ${esc(sources)}. Rebuilt by a scheduled job; nothing is estimated or filled in, a missing number shows as —.<br>
      Some data pipelines adapted from BMR-Com, with permission.<br>For information only, not investment advice. · <a href="https://manasbafna.com/">manasbafna.com</a></footer>`);
  }

  // Desk data lives in data/<id>.json. Opened as a local file, the page reads the published copy instead.
  const PUBLISHED = ['https://grains.manasbafna.com/', 'https://drnas.github.io/grains-monitor/'];
  async function load(id) {
    const bases = location.protocol === 'file:' ? PUBLISHED : [root];
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
      <div class="ct dct"><span>${title}</span>${exp ? `<span class="sp"></span><button class="xbtn" data-png="${exp}" title="Download this chart as a PNG">PNG</button>` : ''}</div>
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

  // Segmented buttons (same look as the home page): calls cb(dataset) on click
  const seg = (el, cb) => el.addEventListener('click', e => { const b = e.target.closest('button'); if (!b) return; el.querySelectorAll('button').forEach(x => x.classList.toggle('on', x === b)); cb(b.dataset); });
  const save = (k, v) => { try { localStorage.setItem('glm_' + k, JSON.stringify(v)); } catch (e) {} };
  const restore = (k, d) => { try { const v = JSON.parse(localStorage.getItem('glm_' + k)); return v ?? d; } catch (e) { return d; } };

  Chart.defaults.color = css('--muted'); Chart.defaults.borderColor = css('--grid'); Chart.defaults.font.size = 11;
  Chart.defaults.plugins.legend.labels.boxWidth = 12; Chart.defaults.animation = false;

  window.Desk = {root, css, esc, ok, fmtN, fmtS, cls, dLabel, header, footer, load, stamp, card, table, tiles, chart, seg, save, restore};
})();
