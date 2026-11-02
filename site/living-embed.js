/* Native WordPress mount; assets stay on the existing Pages deployment. */
(() => {
  'use strict';
  const mount = document.getElementById('maritime-living-mount');
  if (!mount || mount.dataset.loading) return;
  mount.dataset.loading = 'true';
  const base = new URL('.', document.currentScript.src);
  const version = 'v=20261102skin';
  // Load the stylesheet alongside the markup and show the tracker only once both are ready, so it never flashes unstyled.
  const css = document.createElement('link');
  css.rel = 'stylesheet';
  css.href = new URL('living.css?' + version, base).href;
  const styled = new Promise(resolve => { css.onload = resolve; css.onerror = resolve; setTimeout(resolve, 6000); });
  document.head.append(css);
  const markup = fetch(new URL('living.html', base), {cache: 'no-cache'}).then(response => {
    if (!response.ok) throw new Error('Tracker unavailable');
    return response.text();
  });
  Promise.all([markup, styled])
    .then(([html]) => {
      const parsed = new DOMParser().parseFromString(html, 'text/html');
      const root = parsed.getElementById('maritime-living');
      if (!root) throw new Error('Tracker unavailable');
      root.dataset.feed = new URL('living-incidents.json', base).href;
      root.querySelectorAll('a[href="index.html"]').forEach(a => {a.href = base.href;});
      root.querySelectorAll('a[href="incidents.json"]').forEach(a => {a.href = new URL('living-incidents.json', base).href;});
      mount.replaceChildren(document.importNode(root, true));
      const script = document.createElement('script');
      script.src = new URL('living.js?' + version, base).href;
      mount.append(script);
    })
    .catch(() => {
      const note = mount.querySelector('.ml-loading p') || mount.firstElementChild;
      if (note) note.textContent = 'The tracker is temporarily unavailable. Please use the direct tracker link below.';
    });
})();
