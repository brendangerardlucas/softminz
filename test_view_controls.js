const {test} = require('node:test');
const assert = require('node:assert/strict');
const ui = require('./view_controls.js');
test('benchmark, metric and sort changes compose independently', () => {
  let state = ui.initial();
  state = ui.update(state, 'set', 'sci');
  state = ui.update(state, 'mode', 'combined');
  state = ui.update(state, 'sort', 'cost');
  assert.deepEqual(state, {set:'sci', mode:'combined', sort:'cost'});
  assert.equal(ui.viewId(state), 'view-sci-combined');
  state = ui.update(state, 'set', 'all');
  assert.deepEqual(state, {set:'all', mode:'combined', sort:'cost'});
  assert.equal(ui.viewId(state), 'view-all-combined');
  state = ui.update(state, 'mode', 'split');
  assert.equal(ui.viewId(state), 'view-all');
});
