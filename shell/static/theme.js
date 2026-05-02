// foliopage theme controller
// Persists user choice in localStorage; values: 'auto' | 'light' | 'dark'.
// Applies as data-theme on <html>. 'auto' = no attribute (system preference).
(function () {
  const KEY = 'foliopage-theme';
  const root = document.documentElement;

  function read() {
    try { return localStorage.getItem(KEY) || 'auto'; }
    catch { return 'auto'; }
  }
  function write(v) {
    try { localStorage.setItem(KEY, v); } catch {}
  }
  function apply(theme, animate) {
    if (animate) {
      root.classList.add('theme-transition');
      setTimeout(() => root.classList.remove('theme-transition'), 220);
    }
    if (theme === 'auto') {
      root.removeAttribute('data-theme');
    } else {
      root.setAttribute('data-theme', theme);
    }
  }

  // Apply ASAP to avoid FOUC. (Script must be loaded with `defer` removed
  // and placed in <head> for true no-flash; inline init handles that.)
  apply(read(), false);

  // Public API
  window.foliopageTheme = {
    get: read,
    set(theme) {
      if (!['auto', 'light', 'dark'].includes(theme)) return;
      write(theme);
      apply(theme, true);
      window.dispatchEvent(new CustomEvent('foliopage:theme', { detail: { theme } }));
    },
    // Compute the effective theme (resolves 'auto' against system)
    effective() {
      const v = read();
      if (v !== 'auto') return v;
      return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
    },
    // Render a 3-button segmented control into a host element
    mount(host) {
      const ICONS = {
        light: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M4.93 19.07l1.41-1.41M17.66 6.34l1.41-1.41"/></svg>',
        auto:  '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="9"/><path d="M12 3v18" stroke-linecap="round"/><path d="M12 3a9 9 0 0 1 0 18z" fill="currentColor" stroke="none"/></svg>',
        dark:  '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/></svg>',
      };
      const TITLES = { light: '浅色', auto: '跟随系统', dark: '深色' };
      host.classList.add('theme-toggle');
      host.innerHTML = '';
      ['light', 'auto', 'dark'].forEach(t => {
        const btn = document.createElement('button');
        btn.type = 'button';
        btn.title = TITLES[t];
        btn.setAttribute('aria-label', TITLES[t]);
        btn.innerHTML = ICONS[t];
        btn.addEventListener('click', () => window.foliopageTheme.set(t));
        host.appendChild(btn);
      });
      function sync() {
        const cur = read();
        host.querySelectorAll('button').forEach((btn, i) => {
          const t = ['light', 'auto', 'dark'][i];
          btn.setAttribute('aria-pressed', t === cur ? 'true' : 'false');
        });
      }
      sync();
      window.addEventListener('foliopage:theme', sync);
    },
  };
})();
