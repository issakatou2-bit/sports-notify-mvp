const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname, '../web/site-theme.js'), 'utf8');

function harness(saved, dark = false, blocked = false) {
  const events = {}, nodes = {}, root = {dataset:{}}, store = {value:saved};
  const media = {matches:dark, addEventListener:(_, handler) => {events.media=handler;}};
  const element = () => ({append(){}, appendChild(){}, addEventListener(type, handler){this[type]=handler;}});
  const document = {documentElement:root, querySelector:()=>null,
    getElementById:id=>nodes[id], createElement:()=>element(),
    addEventListener:(type, handler)=>{events[type]=handler;},
    body:{prepend(tools){nodes.tools=tools;}}};
  // Capture the select through its DOM id while keeping production event handlers intact.
  document.createElement = () => {
    const node=element();
    Object.defineProperty(node,'id',{set(id){nodes[id]=node;}});
    return node;
  };
  vm.runInNewContext(source, {document, window:{matchMedia:()=>media,addEventListener:(type,handler)=>{events[type]=handler;}},
    localStorage:{getItem(){if(blocked)throw Error('blocked');return store.value;},setItem(_,value){if(blocked)throw Error('blocked');store.value=value;}}});
  events.DOMContentLoaded();
  return {root, media, events, nodes, store};
}
test('first visit follows the device; saved manual choice takes precedence',()=>{
  assert.equal(harness(null,true).root.dataset.theme,'dark');
  assert.equal(harness(null,false).root.dataset.theme,'light');
  assert.equal(harness('light',true).root.dataset.theme,'light');
  assert.equal(harness('dark',false).root.dataset.theme,'dark');
});
test('auto follows device changes, while manual selection is retained',()=>{
  const h=harness(null);
  h.media.matches=true; h.events.media();
  assert.equal(h.root.dataset.theme,'dark');
  const select=h.nodes.themeChoice;
  select.value='light';select.change();
  assert.equal(h.store.value,'light');
  h.events.media();assert.equal(h.root.dataset.theme,'light');
  select.value='system';select.change();assert.equal(h.root.dataset.theme,'dark');
});
test('storage denied and invalid saved values still allow visible mode changes',()=>{
  assert.equal(harness('invalid',true).nodes.themeChoice.value,'system');
  const h=harness(null,false,true);
  h.nodes.themeChoice.value='dark';h.nodes.themeChoice.change();
  assert.equal(h.root.dataset.theme,'dark');
});
test('changes and cleared storage in another tab are reflected',()=>{
  const h=harness('light',true);
  h.events.storage({key:'unrelated',newValue:'dark'});
  assert.equal(h.root.dataset.theme,'light');
  h.events.storage({key:'collespo.theme',newValue:'dark'});
  assert.equal(h.nodes.themeChoice.value,'dark');
  h.events.storage({key:null,newValue:null});
  assert.equal(h.nodes.themeChoice.value,'system');
});
