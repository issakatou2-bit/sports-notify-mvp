// Exercise the home page's actual inline handlers without network or browser dependencies.
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const html = fs.readFileSync(path.join(__dirname,'../web/index.html'),'utf8');
const segment = (from,to) => html.slice(html.indexOf(from),html.indexOf(to,html.indexOf(from)));
function harness(fetch, timers = {setTimeout, clearTimeout}) {
  const nodes = new Map();
  const make = id => {
    const flags = new Set(id==='tab-mlb'?['active']:[]);
    return {id, textContent:'existing', innerHTML:'existing', attrs:{}, handlers:{}, style:{}, tabIndex:0,
      checked:true, hidden:true, disabled:false,
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
  const state = {renders:0, document,window,fetch,AbortController,...timers};
  const context = vm.createContext(state);
  vm.runInContext('let allGamesCache=[];let activeLeague="MLB"; function renderTab(){renders++;}',context);
  vm.runInContext(segment('  let gamesRequest = null;','  // --- 最近の動き'),context);
  vm.runInContext(segment('  function selectLeagueTab(tab)', '  const notificationLeagues'),context);
  vm.runInContext('let notificationClient = null;', context);
  vm.runInContext(segment('  function setStatus(text)', '  function escapeHtml(s)'),context);
  vm.runInContext(segment('  const notificationLeagues', '  document.getElementById(\'copyBtn\')'),context);
  return {context,state,nodes,get,tabs,document,window,run:s=>vm.runInContext(s,context)};
}
const response = games => ({ok:true,json:async()=>({games})});
test('initial load is one request; overlapping resume events share it',async()=>{
  let calls=0,resolve;
  const h=harness(()=>{calls++;return new Promise(r=>{resolve=r;});});
  const start=html.lastIndexOf('\n  renderGames();');
  vm.runInContext(html.slice(start,html.indexOf('</script>',start)),h.context);
  assert.match(h.get('gamesStatus').textContent,/読み込み中/);
  h.window.handlers.pageshow({persisted:false});
  h.window.handlers.pageshow({persisted:true});
  h.document.handlers.visibilitychange();
  assert.equal(calls,1);
  resolve(response([{league:'MLB'}]));
  await h.run('gamesRequest');
  assert.equal(h.state.renders,1);
  h.window.handlers.pageshow({persisted:true});
  assert.equal(calls,2);
  assert.match(h.get('gamesStatus').textContent,/更新中/);
  resolve(response([]));await h.run('gamesRequest');
});
test('reload failures keep previous data, announce staleness, and allow retry',async()=>{
  let reply=response([{league:'MLB'}]);
  const h=harness(async()=>reply);
  await h.run('renderGames()');
  const cached=h.run('allGamesCache');
  const timestamp=h.get('gamesUpdatedAt').dateTime;
  assert.ok(timestamp);
  assert.equal(h.get('gamesUpdated').hidden,false);
  reply={ok:false};await h.run('renderGames()');
  assert.equal(h.run('allGamesCache'),cached);
  assert.match(h.get('gamesStatus').textContent,/前回取得/);
  assert.equal(h.get('allGames').innerHTML,'existing');
  assert.equal(h.get('gamesRetry').hidden,false);
  assert.equal(h.get('gamesUpdatedAt').dateTime,timestamp);
  reply={ok:true,json:async()=>({games:null})};await h.run('renderGames()');
  assert.equal(h.run('allGamesCache'),cached);
  reply=response([]);await h.get('gamesRetry').handlers.click();
  assert.equal(h.run('allGamesCache.length'),0);
  assert.equal(h.get('gamesStatus').textContent,'');
  assert.equal(h.get('gamesRetry').hidden,true);
});
test('first-load failures clear loading text without displaying technical errors',async()=>{
  const h=harness(async()=>{throw new Error('private diagnostic');});
  await h.run('renderGames()');
  assert.equal(h.get('notableGames').textContent,'');
  assert.match(h.get('gamesStatus').textContent,/通信を確認/);
  assert.doesNotMatch(h.get('gamesStatus').textContent,/private/);
});
test('a stuck response body expires at 12 seconds and cannot replace the retry result',async()=>{
  let expire, signal, completeBody, started, calls=0;
  const bodyStarted=new Promise(resolve=>{started=resolve;});
  const h=harness(async(_,options)=>{
    if (++calls > 1) return response([{league:'MLB'}]);
    signal=options.signal;
    return {ok:true,json:()=>new Promise(resolve=>{completeBody=resolve;started();})};
  },{
    setTimeout(callback,ms){assert.equal(ms,12000);expire=callback;return 1;},
    clearTimeout(){}
  });
  const first=h.run('renderGames()');
  await bodyStarted;
  assert.equal(typeof completeBody,'function');
  expire();
  await first;
  assert.equal(signal.aborted,true);
  assert.equal(h.get('gamesRetry').hidden,false);
  await h.get('gamesRetry').handlers.click();
  completeBody({games:[]});
  assert.equal(h.run('allGamesCache.length'),1);
  assert.equal(h.state.renders,1);
});

test('subscribing reports each league and retries only the league that failed',async()=>{
  const h=harness();
  const calls=[];
  const tags={};
  let applied=false;
  h.state.fake={
    User:{
      PushSubscription:{optedIn:false},
      addTag(tag,value){
        calls.push([tag,value]);
        if(tag==='mlb' || applied) tags[tag]=value;
      },
      getTags(){return tags;}
    },
    Notifications:{async requestPermission(){h.state.fake.User.PushSubscription.optedIn=true;}}
  };
  h.run('notificationClient = fake;');
  h.get('notifySoccer').checked=false;
  await h.get('subscribeBtn').handlers.click();
  assert.match(h.get('status').textContent,/通知が有効/);
  assert.match(h.get('notifyMlbStatus').textContent,/保存しました/);
  assert.match(h.get('notifySoccerStatus').textContent,/保存できませんでした/);
  assert.equal(h.get('retryNotifySoccer').hidden,false);
  applied=true;
  await h.get('retryNotifySoccer').handlers.click();
  assert.deepEqual(calls,[['mlb','1'],['soccer','0'],['soccer','0']]);
  assert.match(h.get('notifySoccerStatus').textContent,/受け取らない/);
  assert.equal(h.get('retryNotifySoccer').hidden,true);
});

test('checking an existing subscription reports a read failure and keeps saved preferences',async()=>{
  const h=harness();
  let ready=false;
  h.state.fake={User:{
    PushSubscription:{optedIn:true},
    getTags(){if(!ready) throw new Error('private');return {mlb:'0',soccer:'1'};},
    addTag(){assert.fail('loading stored tags must not overwrite them');}
  }};
  h.run('notificationClient = fake;');
  await h.run('syncLeagueCheckboxesOnLoad()');
  assert.match(h.get('notifyLoadStatus').textContent,/確認できません/);
  assert.equal(h.get('retryNotifyLoad').hidden,false);
  ready=true;
  await h.get('retryNotifyLoad').handlers.click();
  assert.equal(h.get('retryNotifyLoad').hidden,true);
  assert.equal(h.get('notifyMlb').checked,false);
  assert.equal(h.get('notifySoccer').checked,true);
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

test('empty league resets stale dates and explains both empty sections',()=>{
  for (const league of ['MLB','SOCCER']) {
    const nodes=new Map();
    const document={getElementById(id){
      if(!nodes.has(id)) nodes.set(id,{textContent:'previous date',innerHTML:'previous game'});
      return nodes.get(id);
    }};
    const context=vm.createContext({document});
    vm.runInContext('const isSoccer=g=>g.league!=="MLB";let allGamesCache=[];let activeLeague='+JSON.stringify(league)+';',context);
    vm.runInContext(segment('  function renderTab() {','  let gamesRequest = null;'),context);
    vm.runInContext('renderTab()',context);
    assert.equal(nodes.get('allGames').innerHTML,nodes.get('notableGames').innerHTML);
    assert.match(nodes.get('allGames').innerHTML,/対象の.*試合がありません/);
    assert.equal(nodes.get('pickLabel').textContent,'注目試合');
    assert.equal(nodes.get('boardLabel').textContent,'試合一覧 (JST)');
  }
});
