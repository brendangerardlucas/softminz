'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const ui = require('./head_to_head.js');

class Element {
  constructor() { this.textContent=''; this.value=''; this.disabled=true; this.children=[]; this.attributes={}; this.events={}; }
  set innerHTML(_) { throw new Error('Untrusted data must not enter innerHTML'); }
  setAttribute(k,v) { this.attributes[k]=v; }
  append(...nodes) { this.children.push(...nodes); }
  replaceChildren(...nodes) { this.children=nodes; }
  addEventListener(name,callback) { this.events[name]=callback; }
}
function fixture() {
  const data={components:[{key:'tb',label:'Terminal-Bench'},{key:'nhr',label:'Non-hallucination'}],models:[
    {slug:'a',name:'Astra',z:[1.138118894,.414214892],mean_z:.776,worst_z:.414,softminz:1.21,cost_task:5.0241839},
    {slug:'b',name:'Opus',z:[1.403595288,.041725635],mean_z:.723,worst_z:.042,softminz:1.16,cost_task:null},
    {slug:'c',name:'<script>not executable</script>',z:[-1.,1.5],mean_z:.25,worst_z:-1.,softminz:-.2,cost_task:1.},
  ]};
  const ids=['h2h-data','h2h-model-a','h2h-model-b','h2h-controls','h2h-swap','h2h-rows','h2h-status',
    'h2h-a-header','h2h-b-header','h2h-summary-a','h2h-summary-b'];
  for (const metric of ['mean','worst','score','cost']) for(const side of ['a','b']) ids.push('h2h-'+metric+'-'+side);
  const elements=Object.fromEntries(ids.map(id=>[id,new Element()]));
  elements['h2h-data'].textContent=JSON.stringify(data);
  elements['h2h-model-a'].value='a'; elements['h2h-model-b'].value='b';
  return {data,elements,doc:{getElementById:id=>elements[id]||null,createElement:()=>new Element()}};
}

test('delta uses full precision, not rounded displayed z-scores',()=>{
  const result=ui.compare({z:[1.138118894]},{z:[1.403595288]})[0];
  assert.equal(ui.formatZ(result.a),'1.138'); assert.equal(ui.formatZ(result.b),'1.404');
  assert.equal(ui.formatDelta(result.delta),'−0.265');
});
test('same model, swap antisymmetry and zero display',()=>{
  const a={z:[-1.23,.9,2.]},b={z:[.7,-.2,2.]};
  assert(ui.compare(a,a).every(x=>x.delta===0));
  ui.compare(a,b).forEach((r,i)=>assert(r.delta === -ui.compare(b,a)[i].delta));
  assert.equal(ui.formatDelta(-0),'0.000'); assert.equal(ui.formatDelta(-.0001),'0.000');
  assert.equal(ui.formatDelta(.372489),'+0.372'); assert.equal(ui.deltaClass(-.0001),'h2h-tie');
});
test('invalid or incomplete comparison arrays are rejected',()=>{
  for (const b of [{z:[1,2]},{z:[NaN]},{z:[Infinity]},{z:[]}]) assert.throws(()=>ui.compare({z:[1]},b));
});
test('initial mount renders exact pair and missing price without treating it as free',()=>{
  const f=fixture(); assert(ui.mount(f.doc));
  assert.equal(f.elements['h2h-controls'].disabled,false);
  assert.equal(f.elements['h2h-rows'].children.length,2);
  assert.equal(f.elements['h2h-rows'].children[0].children[3].textContent,'−0.265');
  assert.equal(f.elements['h2h-cost-b'].textContent,'—');
});
test('swap button changes models and reverses every delta',()=>{
  const f=fixture(); ui.mount(f.doc);
  f.elements['h2h-swap'].events.click();
  assert.equal(f.elements['h2h-model-a'].value,'b'); assert.equal(f.elements['h2h-model-b'].value,'a');
  assert.equal(f.elements['h2h-rows'].children[0].children[3].textContent,'+0.265');
  assert.equal(f.elements['h2h-rows'].children[1].children[3].textContent,'−0.372');
  assert.equal(f.elements['h2h-a-header'].textContent,'Opus z');
});
test('select change, same-model zeros and hostile names use text-only DOM',()=>{
  const f=fixture(); ui.mount(f.doc);
  f.elements['h2h-model-a'].value='c'; f.elements['h2h-model-a'].events.change();
  assert.equal(f.elements['h2h-a-header'].textContent,'<script>not executable</script> z');
  f.elements['h2h-model-b'].value='c'; f.elements['h2h-model-b'].events.change();
  assert(f.elements['h2h-rows'].children.every(r=>r.children[3].textContent==='0.000'));
  assert(f.elements['h2h-status'].textContent.includes('all Δz values are zero'));
});
test('malformed payload leaves controls disabled and server-rendered content untouched',()=>{
  const f=fixture(); f.elements['h2h-data'].textContent='invalid';
  assert.equal(ui.mount(f.doc),null); assert.equal(f.elements['h2h-controls'].disabled,true);
  assert.equal(f.elements['h2h-rows'].children.length,0);
});
test('null model in valid JSON preserves harmless disabled fallback',()=>{
  const f=fixture(); f.data.models=[null];
  f.elements['h2h-data'].textContent=JSON.stringify(f.data);
  assert.equal(ui.mount(f.doc),null); assert.equal(f.elements['h2h-controls'].disabled,true);
});
test('no widget present is a harmless no-op',()=>assert.equal(ui.mount({getElementById:()=>null}),null));
