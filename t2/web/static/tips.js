// One fixed-position tooltip for every [data-tip], placed against the viewport so
// a scrolling pane's overflow can't clip it. Prefers above, flips below, clamps sideways.
(function () {
  const GAP = 6, MARGIN = 8;
  let tipEl = null, owner = null;

  const ensure = () => {
    if (!tipEl) {
      tipEl = document.createElement('div');
      tipEl.className = 'tip-float';
      tipEl.setAttribute('role', 'tooltip');
      document.body.appendChild(tipEl);
    }
    return tipEl;
  };

  const hide = () => {
    owner = null;
    if (tipEl) tipEl.style.display = 'none';
  };

  const show = (el) => {
    const text = el.getAttribute('data-tip');
    if (!text) return hide();
    owner = el;
    const t = ensure();
    t.textContent = text;
    t.style.display = 'block';
    t.style.left = '0px';
    t.style.top = '0px';

    const r = el.getBoundingClientRect();
    const w = t.offsetWidth, h = t.offsetHeight;
    const vw = document.documentElement.clientWidth, vh = document.documentElement.clientHeight;

    let left = r.left + r.width / 2 - w / 2;
    left = Math.max(MARGIN, Math.min(left, vw - w - MARGIN));
    let top = r.top - h - GAP;
    if (top < MARGIN) top = Math.min(r.bottom + GAP, vh - h - MARGIN);

    t.style.left = left + 'px';
    t.style.top = top + 'px';
  };

  document.addEventListener('mouseover', (e) => {
    const el = e.target.closest && e.target.closest('[data-tip]');
    if (el === owner) return;
    if (el) show(el); else hide();
  });
  document.addEventListener('mouseout', (e) => {
    if (owner && !owner.contains(e.relatedTarget)) hide();
  });
  // A swapped-in htmx fragment or a scrolled pane leaves the tip stranded.
  document.addEventListener('scroll', hide, true);
  document.addEventListener('htmx:beforeSwap', hide);
})();
