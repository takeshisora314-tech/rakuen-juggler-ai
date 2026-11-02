const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const html=fs.readFileSync('index.html','utf8'),elements=new Map(),docEvents={},winEvents={};
function element(){return {innerHTML:'',textContent:'',value:'',listeners:{},addEventListener(t,f){this.listeners[t]=f;},replaceChildren(){},appendChild(){},setAttribute(){}};}
const get=id=>{if(!elements.has(id))elements.set(id,element());return elements.get(id);};
let clock=Date.parse('2026-11-02T11:00:00Z'),version=1,failData=false,failOptional=false,calls=[];
class Clock extends Date {constructor(...args){super(...(args.length?args:[clock]));}static now(){return clock;}}
const config={models:['myj5','myj6'].map((id,i)=>({id,name:id,installations:[{from:null,until:null,numbers:[2221+i]}]}))};
const doc={visibilityState:'visible',getElementById:get,querySelectorAll(){return [];},createElement:element,addEventListener(t,f){docEvents[t]=f;}};
const context=vm.createContext({document:doc,window:{addEventListener(t,f){winEvents[t]=f;}},Intl,Date:Clock,URL,AbortController,setTimeout,clearTimeout,setInterval(){},
  async fetch(path,opts){
    calls.push(path);assert.equal(opts.cache,'no-store');
    assert.match(path,/[?&]_read=\d+/);path=path.split('?')[0];
    if(failData&&path==='data.json'||failOptional&&path==='publication_status.json')throw Error('offline');
    return {ok:true,async json(){return path==='machines.json'?config:path==='data.json'?{version,machine_records:[]}:{}}};
  }});
vm.runInContext(html.match(/<script>([\s\S]*?)<\/script>/)[1].replace(/load\(\);\s*$/,''),context);
const evaluate=s=>vm.runInContext(s,context);
(async()=>{
  await evaluate('load()');assert.equal(calls.length,5);assert.equal(evaluate('DATA.version'),1);
  assert.match(get('data-refresh-status').textContent,/表示データの確認/);
  evaluate("current='myj5';followToday=false;dateInput.value='2026-10-30';selectedResultDay='2026-10-29';");
  version=2;clock+=65000;docEvents.visibilitychange();winEvents.pageshow();winEvents.focus();
  await evaluate('refreshInFlight');
  assert.equal(calls.length,10);assert.equal(evaluate('DATA.version'),2);
  assert.equal(evaluate('current'),'myj5');assert.equal(get('layout-date').value,'2026-10-30');
  assert.equal(evaluate('selectedResultDay'),'2026-10-29');
  winEvents.focus();assert.equal(calls.length,10); // Focus/visibility duplicates are throttled.
  failData=true;clock+=65000;winEvents.focus();await evaluate('refreshInFlight');
  assert.equal(evaluate('DATA.version'),2);assert.match(get('data-refresh-status').textContent,/前回読み込んだデータ/);
  failData=false;failOptional=true;version=3;clock+=65000;winEvents.focus();await evaluate('refreshInFlight');
  assert.equal(evaluate('DATA.version'),3);assert.equal(evaluate('PUBLICATION'),null);
  assert.match(get('data-refresh-status').textContent,/一部の確認記録/);
  doc.visibilityState='hidden';clock+=65000;const count=calls.length;winEvents.focus();docEvents.visibilitychange();assert.equal(calls.length,count);
  doc.visibilityState='visible';failOptional=false;clock+=86400000;evaluate('followToday=true');
  winEvents.pageshow();await evaluate('refreshInFlight');assert.equal(get('layout-date').value,evaluate('todayJST()'));
  const timers=[];context.setTimeout=fn=>{timers.push(fn);return timers.length;};context.clearTimeout=()=>{};
  context.fetch=(path,{signal})=>new Promise((resolve,reject)=>signal.addEventListener('abort',()=>reject(Error('timed out'))));
  const stalled=evaluate('refreshSavedData(true)');assert.equal(timers.length,5);
  timers.forEach(fn=>fn());assert.equal(await stalled,false);
  assert.equal(evaluate('DATA.version'),3);assert.equal(evaluate('refreshInFlight'),null);
  console.log('Resume refresh: latest payload, preserved selection, deduplication, offline retention, optional failure, hidden state and next-day follow passed.');
})().catch(e=>{console.error(e);process.exitCode=1;});
