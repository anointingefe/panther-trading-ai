/* Move the existing nodes, retaining their IDs, state and trading event handlers. */
window.setupPantherWorkspace = function () {
  const workspace = document.querySelector('.workspace');
  const definitions = [
    ['overview', 'Overview', ['.metrics-grid', '.hero-grid', '.approval-panel', '.rationale-panel', '.activity-panel']],
    ['markets', 'Markets', ['.market-panel', '.table-panel', '.candle-panel']],
    ['execution', 'Execution', ['.positions-panel', '.demo-auto-panel', '.exit-panel', '.live-panel']],
    ['research', 'Research', ['.research-panel', '.intelligence-panel', '.advisor-panel', '.learning-panel', '.edge-panel']],
    ['performance', 'Performance', ['.target-grid', '.journal-panel']],
    ['settings', 'Settings', ['.broker-panel', '.beast-panel']],
  ];
  const views = new Map();
  definitions.forEach(([id, title, selectors]) => {
    const view = document.createElement('section');
    view.id = id;
    view.className = 'workspace-view';
    view.setAttribute('aria-label', title);
    selectors.forEach(selector => {
      const panel = document.querySelector(selector);
      if (panel) view.append(panel);
    });
    workspace.append(view);
    views.set(id, { view, title });
  });
  const oldGrid = document.querySelector('.lower-grid');
  if (oldGrid && !oldGrid.children.length) oldGrid.remove();
  const aliases = {
    'command-section': 'overview', 'signals-section': 'overview',
    'targets-section': 'performance', 'backtests-section': 'research',
    'risk-section': 'execution', 'broker-section': 'settings',
  };
  const links = [...document.querySelectorAll('.nav-list a')];
  const title = document.getElementById('workspace-title');
  function revealActiveLink() {
    const active = links.find(link => link.hasAttribute('aria-current'));
    if (active) active.parentElement.scrollLeft = active.offsetLeft - links[0].offsetLeft;
  }
  function showView(hash, focus) {
    const requested = hash.replace(/^#/, '');
    const id = views.has(requested) ? requested : (aliases[requested] || 'overview');
    views.forEach(({ view }, key) => { view.hidden = key !== id; });
    title.textContent = views.get(id).title;
    document.title = `${views.get(id).title} | PANTHER Trading AI`;
    links.forEach(link => {
      const active = link.hash === `#${id}`;
      link.classList.toggle('active', active);
      if (active) link.setAttribute('aria-current', 'page');
      else link.removeAttribute('aria-current');
    });
    revealActiveLink();
    if (focus) {
      window.scrollTo({ top: 0, behavior: 'instant' });
      title.focus({ preventScroll: true });
    }
  }
  [...links, document.querySelector('.brand')].forEach(link => {
    link.addEventListener('click', event => {
      if (event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
      event.preventDefault();
      const hash = link.classList.contains('brand') ? '#overview' : link.hash;
      if (location.hash !== hash) history.pushState(null, '', hash);
      showView(hash, true);
    });
  });
  window.addEventListener('popstate', () => showView(location.hash, true));
  window.addEventListener('hashchange', () => showView(location.hash, true));
  window.addEventListener('resize', revealActiveLink);
  showView(location.hash, false);
};
