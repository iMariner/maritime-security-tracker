/* Native WordPress mount; assets stay on the existing Pages deployment. */
(() => {
  'use strict';
  const mount = document.getElementById('maritime-living-mount');
  if (!mount || mount.dataset.loading) return;
  mount.dataset.loading = 'true';
  const base = new URL('.', document.currentScript.src);
  fetch(new URL('living.html', base), {cache: 'no-cache'})
    .then(response => {
      if (!response.ok) throw new Error('Tracker unavailable');
      return response.text();
    })
    .then(html => {
      const parsed = new DOMParser().parseFromString(html, 'text/html');
      const root = parsed.getElementById('maritime-living');
      if (!root) throw new Error('Tracker unavailable');
      root.dataset.feed = new URL('living-incidents.json', base).href;
      root.querySelectorAll('a[href="index.html"]').forEach(a => {a.href = base.href;});
      root.querySelectorAll('a[href="incidents.json"]').forEach(a => {a.href = new URL('living-incidents.json', base).href;});
      const css = document.createElement('link');
      css.rel = 'stylesheet';
      css.href = new URL('living.css?v=20261021', base).href;
      document.head.append(css);
      mount.replaceChildren(document.importNode(root, true));
      const script = document.createElement('script');
      script.src = new URL('living.js?v=20261021', base).href;
      mount.append(script);
    })
    .catch(() => {
      mount.firstElementChild.textContent = 'The tracker is temporarily unavailable. Please use the direct tracker link below.';
    });
})();
