/* All links are present without JS. Filtering is local and creates no extra URLs. */
(() => {
  const query = document.getElementById('archive-query');
  if (!query) return;
  const normalize = value => value.normalize('NFKC').toLocaleLowerCase('ja');
  const entries = [...document.querySelectorAll('[data-archive-entry]')]
    .map(element => ({ element, text: normalize(element.dataset.search || '') }));
  const count = document.getElementById('archive-count');
  const empty = document.getElementById('archive-empty');
  function filter() {
    const terms = normalize(query.value).trim().split(/\s+/u).filter(Boolean);
    let shown = 0;
    for (const { element, text } of entries) {
      const matches = terms.every(term => text.includes(term));
      element.hidden = !matches;
      if (matches) shown += 1;
    }
    count.textContent = `${entries.length}日分のうち ${shown}日分を表示`;
    empty.hidden = shown !== 0;
  }
  query.addEventListener('input', filter);
  document.getElementById('archive-reset').addEventListener('click', () => {
    query.value = '';
    filter();
    query.focus();
  });
  document.querySelector('.archive-search').hidden = false;
  filter();
})();
