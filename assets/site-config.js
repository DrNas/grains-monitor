window.SITE_PUBLISHED = []; window.SITE_OFFLINE = true;
(() => {
  const real = window.fetch.bind(window), D = window.SITE_DATA = {}, waiting = {};
  const reply = id => id in D ? new Response(JSON.stringify(D[id]), {status: 200, headers: {'content-type': 'application/json'}}) : new Response('', {status: 404});
  window.fetch = (u, o) => {
    const m = /(?:^|\/)data\/(.+?)\.json(?:[?#]|$)/.exec(String(u));
    if (!m) return real(u, o);
    const id = m[1];
    if (id in D) return Promise.resolve(reply(id));
    waiting[id] = waiting[id] || new Promise(res => {
      const s = document.createElement('script');
      s.src = 'data/' + id + '.js'; s.onload = s.onerror = () => res();
      document.head.appendChild(s);
    });
    return waiting[id].then(() => reply(id));
  };
})();
