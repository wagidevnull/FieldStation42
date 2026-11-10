// Lays a TV-facing page out for the screen aspect ratio chosen in the settings menu.
// The page is laid out at the chosen shape and stretched to fill the window, the same
// way mpv's monitoraspect corrects video, so it looks right on the TV whatever
// resolution the output runs at. Fires 'fs42-aspect' on window after each change.
(function () {
  const RATIOS = { '16:9': 16 / 9, '4:3': 4 / 3 };
  let current = null;

  function apply(ratio) {
    current = RATIOS[ratio] ? ratio : '16:9';
    const body = document.body;
    const stretch = (window.innerWidth / window.innerHeight) / RATIOS[current];
    if (Math.abs(stretch - 1) < 0.02) {
      body.style.width = '';
      body.style.transform = '';
    } else {
      body.style.width = `${window.innerWidth / stretch}px`;
      body.style.transformOrigin = '0 0';
      body.style.transform = `scaleX(${stretch})`;
    }
    window.dispatchEvent(new CustomEvent('fs42-aspect', { detail: { ratio: current } }));
  }

  async function load() {
    try {
      const res = await fetch('/settings');
      const data = await res.json();
      apply(data.values.aspect_ratio);
    } catch (e) {
      console.warn('Could not load aspect ratio setting:', e);
    }
  }

  window.addEventListener('resize', () => { if (current) apply(current); });
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', load);
  } else {
    load();
  }

  window.fs42Aspect = { apply, current: () => current };
})();
