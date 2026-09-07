// Exercise the home page's actual inline handlers without network or browser dependencies.
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const html = fs.readFileSync(path.join(__dirname,'../web/index.html'),'utf8');
const segment = (from,to) => html.slice(html.indexOf(from),html.indexOf(to,html.indexOf(from)));
function harness(fetch) {
  const nodes = new Map();
  const make = id => {
    const flags = new Set(id==='tab-mlb'?['active']:[]);
    return {id, textContent:'existing', innerHTML:'existing', attrs:{}, handlers:{}, tabIndex:0,
      dataset:{league:id==='tab-mlb'?'MLB':'SOCCER'},
      classList:{toggle(k,v){v?flags.add(k):flags.delete(k);}, contains:k=>flags.has(k)},
      setAttribute(k,v){this.attrs[k]=v;}, addEventListener(k,f){this.handlers[k]=f;},
      closest(s){return s==='.tab' && id.startsWith('tab-')?this:null;},
      focus(){this.focused=true;}};
  };
  const get = id => {if(!nodes.has(id))nodes.set(id,make(id));return nodes.get(id);};
  const tabs = [get('tab-mlb'),get('tab-soccer')];
  const document = {getElementById:get,querySelectorAll:()=>tabs,handlers:{},visibilityState:'visible',
    addEventListener(k,f){this.handlers[k]=f;}};
  const window = {handlers:{},addEventListener(k,f){this.handlers[k]=f;}};
  const state = {renders:0, document,window,fetch};
  const context = vm.createContext(state);
  vm.runInContext('let allGamesCache=[];let activeLeague="MLB"; function renderTab(){renders++;}',context);
  vm.runInContext(segment('  let gamesRequest = null;','  // --- 最近の動き'),context);
  vm.runInContext(segment('  function selectLeagueTab(tab)', '  async function applyLeagueTags()'),context);
  return {context,state,nodes,get,tabs,document,window,run:s=>vm.runInContext(s,context)};
}
const response = games => ({ok:true,json:async()=>({games})});
test('initial load is one request; overlapping resume events share it',async()=>{
  let calls=0,resolve;
  const h=harness(()=>{calls++;return new Promise(r=>{resolve=r;});});
  const start=html.lastIndexOf('\n  renderGames();');
  vm.runInContext(html.slice(start,html.indexOf('</script>',start)),h.context);
  h.window.handlers.pageshow({persisted:false});
  h.window.handlers.pageshow({persisted:true});
  h.document.handlers.visibilitychange();
  assert.equal(calls,1);
  resolve(response([{league:'MLB'}]));
  await h.run('gamesRequest');
  assert.equal(h.state.renders,1);
  h.window.handlers.pageshow({persisted:true});
  assert.equal(calls,2);
  resolve(response([]));await h.run('gamesRequest');
});
test('reload failures keep previous data, announce staleness, and allow retry',async()=>{
  let reply=response([{league:'MLB'}]);
  const h=harness(async()=>reply);
  await h.run('renderGames()');
  const cached=h.run('allGamesCache');
  reply={ok:false};await h.run('renderGames()');
  assert.equal(h.run('allGamesCache'),cached);
  assert.match(h.get('gamesStatus').textContent,/前回取得/);
  assert.equal(h.get('allGames').innerHTML,'existing');
  reply={ok:true,json:async()=>({games:null})};await h.run('renderGames()');
  assert.equal(h.run('allGamesCache'),cached);
  reply=response([]);await h.run('renderGames()');
  assert.equal(h.run('allGamesCache.length'),0);
  assert.equal(h.get('gamesStatus').textContent,'');
});
test('first-load failures clear loading text without displaying technical errors',async()=>{
  const h=harness(async()=>{throw new Error('private diagnostic');});
  await h.run('renderGames()');
  assert.equal(h.get('notableGames').textContent,'');
  assert.match(h.get('gamesStatus').textContent,/通信を確認/);
  assert.doesNotMatch(h.get('gamesStatus').textContent,/private/);
});
test('keyboard switches league, selection, focus and panel label together',()=>{
  const h=harness();
  let prevented=false;
  h.get('tabs').handlers.keydown({key:'ArrowRight',target:h.tabs[0],preventDefault(){prevented=true;}});
  assert.equal(h.run('activeLeague'),'SOCCER');assert.equal(prevented,true);
  assert.equal(h.tabs[1].attrs['aria-selected'],'true');assert.equal(h.tabs[0].tabIndex,-1);
  assert.equal(h.get('gamePanel').attrs['aria-labelledby'],'tab-soccer');assert.equal(h.tabs[1].focused,true);
  h.get('tabs').handlers.keydown({key:'Home',target:h.tabs[1],preventDefault(){}});
  assert.equal(h.run('activeLeague'),'MLB');
});
test('vertical, interactive, multi-touch and cancelled gestures do not switch league',()=>{
  const h=harness();const p=h.get('gamePanel');
  const touch=(x,y)=>({clientX:x,clientY:y});
  const start=(interactive=false,count=1)=>p.handlers.touchstart({touches:Array.from({length:count},()=>touch(200,100)),target:{closest:()=>interactive?{}:null}});
  const end=(x,y)=>p.handlers.touchend({touches:[],changedTouches:[touch(x,y)]});
  start();end(120,350);assert.equal(h.run('activeLeague'),'MLB');
  start(true);end(100,100);assert.equal(h.run('activeLeague'),'MLB');
  start(false,2);end(100,100);assert.equal(h.run('activeLeague'),'MLB');
  start();p.handlers.touchcancel();end(100,100);assert.equal(h.run('activeLeague'),'MLB');
  start();end(100,110);assert.equal(h.run('activeLeague'),'SOCCER');
});
test('all inline scripts parse',()=>{
  for(const match of html.matchAll(/<script([^>]*)>([\s\S]*?)<\/script>/g)) {
    if (/type="application\/ld\+json"/.test(match[1])) JSON.parse(match[2]);
    else new vm.Script(match[2]);
  }
});
