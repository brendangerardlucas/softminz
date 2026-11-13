/* Orthogonal in-page state: no control changes the URL hash. */
(function () {
  'use strict';
  function initial() { return {set:'all', mode:'split', sort:'smz'}; }
  function update(state, key, value) {
    const valid = {set:['all','sci'], mode:['split','combined'], sort:['smz','cost']};
    if (!valid[key] || !valid[key].includes(value)) throw new TypeError('Invalid view state');
    return Object.assign({}, state, {[key]:value});
  }
  function viewId(state) { return 'view-' + state.set + (state.mode === 'combined' ? '-combined' : ''); }
  function mount(doc) {
    const ranking = doc.getElementById('ranking');
    if (!ranking || !doc.getElementById('view-all-combined') || !doc.getElementById('view-sci-combined')) return;
    let state = initial();
    const byId = id => doc.getElementById(id);
    const links = Array.from(ranking.querySelectorAll('a'));
    const anchors = {'#set-all-anchor':['set','all'], '#set-sci-anchor':['set','sci'],
      '#all9-smz-anchor':['sort','smz'], '#rank-smz-anchor':['sort','smz'],
      '#all9-cost-anchor':['sort','cost'], '#rank-cost-anchor':['sort','cost']};
    function changeFor(link) {
      if (link.dataset.mode) return ['mode',link.dataset.mode];
      if (link.dataset.sort) return ['sort',link.dataset.sort];
      return anchors[link.getAttribute('href')];
    }
    function render() {
      byId('setnote-all').textContent = (state.mode === 'split' ? 'Ten' : 'Nine') + '-component SoftMinZ over the full v5 suite.';
      byId('setnote-sci').textContent = (state.mode === 'split' ? 'Seven' : 'Six') + '-component SoftMinZ over the science battery.';
      ['view-all','view-sci','view-all-combined','view-sci-combined'].forEach(id => {
        byId(id).style.display = id === viewId(state) ? 'block' : 'none';
      });
      [['all9','all','split'],['rank','sci','split'],['all-combined','all','combined'],['sci-combined','sci','combined']].forEach(([prefix]) => {
        ['smz','cost'].forEach(sort => { byId(prefix + '-' + sort + '-table').style.display = state.sort === sort ? 'block' : 'none'; });
      });
      links.forEach(link => {
        const change = changeFor(link); if (!change) return;
        const active = state[change[0]] === change[1];
        link.classList.toggle('on', active);
        link.setAttribute('aria-pressed', String(active));
        link.style.background = active ? 'var(--accent)' : '#fff';
        link.style.color = active ? '#fff' : 'var(--ink)';
        link.style.fontWeight = active ? '600' : '500';
      });
      ['setnote-all','setnote-sci','all9-note','all9-note-cost','ranknote','ranknote-cost'].forEach(id => {
        const active = id === 'setnote-' + state.set || id === (state.set === 'all' ? 'all9-note' : 'ranknote') + (state.sort === 'cost' ? '-cost' : '');
        byId(id).style.display = active ? 'inline' : 'none';
      });
    }
    links.forEach(link => { const change = changeFor(link); if (change) link.addEventListener('click', event => {
      event.preventDefault(); state = update(state, change[0], change[1]); render();
    }); });
    byId('mode-controls').hidden = false;
    render();
  }
  if (typeof module !== 'undefined' && module.exports) module.exports = {initial, update, viewId, mount};
  if (typeof document !== 'undefined') mount(document);
}());
