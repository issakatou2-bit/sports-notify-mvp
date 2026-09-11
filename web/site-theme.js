/* Apply the saved choice before the first paint, and follow the device in auto mode. */
(() => {
  'use strict';
  const key = 'collespo.theme';
  const root = document.documentElement;
  const media = window.matchMedia('(prefers-color-scheme: dark)');
  const normalize = value => ['light', 'dark'].includes(value) ? value : 'system';
  let preference = 'system';
  try { preference = normalize(localStorage.getItem(key)); } catch (_) { /* Device default still works. */ }

  function apply() {
    const dark = preference === 'dark' || (preference === 'system' && media.matches);
    root.dataset.theme = dark ? 'dark' : 'light';
    const meta = document.querySelector('meta[name="theme-color"]');
    if (meta) meta.content = dark ? '#10171d' : '#f3f1e9';
    const select = document.getElementById('themeChoice');
    if (select) select.value = preference;
  }
  apply();
  media.addEventListener('change', apply);
  window.addEventListener('storage', event => {
    if (event.key !== key && event.key !== null) return;
    preference = normalize(event.newValue);
    apply();
  });
  document.addEventListener('DOMContentLoaded', () => {
    if (document.getElementById('themeChoice')) return;
    const tools = document.createElement('div');
    tools.className = 'theme-tools';
    const label = document.createElement('label');
    label.htmlFor = 'themeChoice';
    label.textContent = '表示';
    const select = document.createElement('select');
    select.id = 'themeChoice';
    for (const [value, text] of [['system', '端末に合わせる'], ['light', 'ライト'], ['dark', 'ダーク']]) {
      const option = document.createElement('option');
      option.value = value;
      option.textContent = text;
      select.appendChild(option);
    }
    tools.append(label, select);
    const header = document.querySelector('body > header');
    if (header) header.after(tools);
    else document.body.prepend(tools);
    select.addEventListener('change', () => {
      preference = normalize(select.value);
      try { localStorage.setItem(key, preference); } catch (_) { /* Keep the choice for this page. */ }
      apply();
    });
    apply();
  }, {once: true});
})();
