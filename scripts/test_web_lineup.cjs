const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const html=fs.readFileSync(path.join(__dirname,'../web/lineup.html'),'utf8');
const script=[...html.matchAll(/<script[^>]*>([\s\S]*?)<\/script>/g)].find(m=>m[1].includes('const SLOT_ORDER'));
const sample={season:'2026',updated_at:'2026-09-11T12:00:00Z',pitchers:[{id:'p',name:'Pitcher',era:'2.00'}],
  batters:Object.fromEntries(['C','1B','2B','3B','SS','LF','CF','RF','DH'].map((slot,i)=>[slot,[{id:String(i),name:slot,ops:'.800'}]]))};
async function harness(data=sample) {
  const nodes={},store={};
  const element=()=>({children:[],dataset:{},classList:{add(){},remove(){}},setAttribute(){},addEventListener(){},focus(){},
    appendChild(child){this.children.push(child);},set innerHTML(value){this.children=[];this._html=value;}});
  for(const m of html.slice(0,script.index).matchAll(/\bid="([^"]+)"/g))nodes[m[1]]=element();
  const context=vm.createContext({document:{getElementById:id=>nodes[id]||null,createElement:element},
    window:{},location:{origin:'https://example.test',pathname:'/lineup.html'},
    localStorage:{getItem:key=>store[key]||null,setItem:(key,value)=>{store[key]=value;}},
    fetch:async()=>({ok:data!==null,json:async()=>structuredClone(data)}),AbortController,setTimeout,clearTimeout});
  vm.runInContext(script[1],context);
  await new Promise(resolve=>setImmediate(resolve));
  return {nodes,store,run:code=>vm.runInContext(code,context)};
}
test('boot finds the picker before attaching handlers and renders all positions',async()=>{
  const h=await harness();
  assert.equal(h.nodes.slots.children.length,10);
  assert.equal(h.nodes.randomBtn.disabled,false);
  assert.equal(h.nodes.loadError.hidden,true);
});
test('failed loading shows recovery and does not overwrite the saved lineup',async()=>{
  const h=await harness(null);
  assert.equal(h.nodes.loadError.hidden,false);
  assert.equal(h.nodes.randomBtn.disabled,true);
  assert.equal(Object.keys(h.store).length,0);
  assert.equal(h.nodes.slots.children.length,10);
});
test('saved ids restore current stats and reject a previous season',async()=>{
  const h=await harness();
  h.run("selection.C=DATA.batters.C[0]; save(); DATA.batters.C[0].ops='.950'; selection={}; load();");
  assert.equal(h.run('selection.C.ops'),'.950');
  h.run("DATA.season='2027'; load();");
  assert.equal(h.run('Object.keys(selection).length'),0);
});
test('one batter cannot occupy two fielding slots; pitcher plus DH remains possible',async()=>{
  const h=await harness();
  h.run("DATA.batters.DH=[DATA.batters.C[0]]; selection.C=DATA.batters.C[0];");
  assert.equal(h.run("candidatesFor('DH').length"),0);
  h.run("selection={P:DATA.batters.C[0]};");
  assert.equal(h.run("candidatesFor('DH').length"),1);
});
