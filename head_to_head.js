/* Embedded by public_watch.py. No dependencies or network requests. */
(function () {
  'use strict';
  function formatZ(value) {
    return (Math.abs(value) < 0.0005 ? 0 : value).toFixed(3).replace('-', '−');
  }
  function formatDelta(value) {
    return (value >= 0.0005 ? '+' : '') + formatZ(value);
  }
  function deltaClass(value) {
    return Math.abs(value) < 0.0005 ? 'h2h-tie' : value > 0 ? 'h2h-positive' : 'h2h-negative';
  }
  function compare(a, b) {
    if (!Array.isArray(a.z) || !Array.isArray(b.z) || a.z.length !== b.z.length ||
        !a.z.length || !a.z.every(Number.isFinite) || !b.z.every(Number.isFinite)) {
      throw new TypeError('Expected matching finite cohort z-score arrays');
    }
    return a.z.map(function (value, i) { return {a: value, b: b.z[i], delta: value - b.z[i]}; });
  }
  function mount(doc) {
    var source = doc.getElementById('h2h-data');
    if (!source) return null;
    var data;
    try { data = JSON.parse(source.textContent); } catch (_) { return null; }
    if (!data || !Array.isArray(data.components) || !data.components.length ||
        !data.components.every(function (c) { return c && typeof c.key === 'string' && typeof c.label === 'string'; }) ||
        !Array.isArray(data.models) || !data.models.length ||
        !data.models.every(function (m) {
          return m && typeof m.slug === 'string' && typeof m.name === 'string' &&
            Array.isArray(m.z) && m.z.length === data.components.length && m.z.every(Number.isFinite) &&
            Number.isFinite(m.mean_z) && Number.isFinite(m.worst_z) && Number.isFinite(m.softminz) &&
            (m.cost_task === null || Number.isFinite(m.cost_task));
        })) return null;
    var models = new Map(data.models.map(function (m) { return [m.slug, m]; }));
    if (models.size !== data.models.length) return null;
    var aSelect = doc.getElementById('h2h-model-a');
    var bSelect = doc.getElementById('h2h-model-b');
    var controls = doc.getElementById('h2h-controls');
    var swapButton = doc.getElementById('h2h-swap');
    var body = doc.getElementById('h2h-rows');
    var status = doc.getElementById('h2h-status');
    if (!aSelect || !bSelect || !controls || !swapButton || !body || !status) return null;
    function cell(tag, text, className) {
      var node = doc.createElement(tag);
      node.textContent = text;
      if (className) node.className = className;
      return node;
    }
    function set(id, text) { doc.getElementById(id).textContent = text; }
    function render() {
      var a = models.get(aSelect.value), b = models.get(bSelect.value);
      if (!a || !b) return;
      var rows = compare(a, b).map(function (pair, i) {
        var row = doc.createElement('tr');
        row.setAttribute('data-component', data.components[i].key);
        var label = cell('th', data.components[i].label);
        label.scope = 'row';
        var delta = cell('td', formatDelta(pair.delta), 'num ' + deltaClass(pair.delta));
        var winner = deltaClass(pair.delta) === 'h2h-tie' ? 'tie at displayed precision' :
          'favors ' + (pair.delta > 0 ? a.name : b.name);
        delta.setAttribute('aria-label', formatDelta(pair.delta) + ', ' + winner);
        row.append(label, cell('td', formatZ(pair.a), 'num'), cell('td', formatZ(pair.b), 'num'), delta);
        return row;
      });
      body.replaceChildren.apply(body, rows);
      ['h2h-a-header', 'h2h-summary-a'].forEach(function (id) { set(id, a.name + (id === 'h2h-a-header' ? ' z' : '')); });
      ['h2h-b-header', 'h2h-summary-b'].forEach(function (id) { set(id, b.name + (id === 'h2h-b-header' ? ' z' : '')); });
      [['a', a], ['b', b]].forEach(function (entry) {
        var side = entry[0], model = entry[1];
        set('h2h-mean-' + side, formatZ(model.mean_z));
        set('h2h-worst-' + side, formatZ(model.worst_z));
        set('h2h-score-' + side, model.softminz.toFixed(2).replace('-', '−'));
        set('h2h-cost-' + side, model.cost_task === null ? '—' : '$' + model.cost_task.toFixed(4));
      });
      status.textContent = a.slug === b.slug ? 'Same model selected: all Δz values are zero.' :
        'Comparing ' + a.name + ' against ' + b.name + '.';
    }
    function swap() {
      var previous = aSelect.value;
      aSelect.value = bSelect.value;
      bSelect.value = previous;
      render();
    }
    aSelect.addEventListener('change', render);
    bSelect.addEventListener('change', render);
    swapButton.addEventListener('click', swap);
    render();
    controls.disabled = false;
    return {render: render, swap: swap};
  }
  if (typeof module !== 'undefined' && module.exports) {
    module.exports = {formatZ: formatZ, formatDelta: formatDelta, deltaClass: deltaClass, compare: compare, mount: mount};
  }
  if (typeof document !== 'undefined') mount(document);
}());
