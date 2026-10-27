// Rendering logic tests only; these do not replace Safari/device visual checks.
const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const html = fs.readFileSync('index.html','utf8');
const elements = new Map();
const element = id => {
  if (!elements.has(id)) elements.set(id,{innerHTML:'',value:'',addEventListener(){}});
  return elements.get(id);
};
const context = vm.createContext({document:{getElementById:element},Intl,Date,URL,
  setInterval(){}, fetch(){throw new Error('Tests must not access network');}});
const script = html.match(/<script>([\s\S]*?)<\/script>/)[1].replace(/load\(\);\s*$/, '');
vm.runInContext(script,context);
const candidate = {number:2221,score:50,three_day_difference:-10,history_days:3,
  history_games:15000,rb_denominator:300,latest_games:5000,latest_difference:0};
const rows = Array.from({length:5},(_,i)=>({...candidate,number:2221+i}));
context.fixture = {forecast:{date:'2026-10-28',display_status:'preview',models:{myj5:{
  status:'ready',selection:{strategy:'balanced',paired_days:0},history_days:3,
  latest_source_date:'2026-10-26',eligible_numbers:rows.map(r=>r.number),
  rankings:{balanced:rows},strategies:{balanced:rows.slice(0,3)}}}},
  evaluation:{prospective:[],retrospective:[]}, machine_collection:{status:'partial',
  models:{myj5:{status:'partial',rows:19,missing_numbers:[2201,2202]}}}};
vm.runInContext("DATA=fixture;drawForecast({id:'myj5',name:'V'});",context);
assert.match(element('forecast-panel').innerHTML,/全5台/);
assert.match(element('forecast-panel').innerHTML,/2225/);
assert.match(element('forecast-panel').innerHTML,/設定4〜6期待度モデルは未完成/);
assert.match(element('evaluation-panel').innerHTML,/まだ事前予想の評価実績はありません/);
vm.runInContext("delete DATA.forecast.models.myj5.rankings;drawForecast({id:'myj5',name:'V'});",context);
assert.match(element('forecast-panel').innerHTML,/2223/);
assert.doesNotMatch(element('forecast-panel').innerHTML,/2225/);
vm.runInContext("drawForecast({id:'myj6',name:'VI'});drawSources();",context);
assert.doesNotMatch(element('forecast-panel').innerHTML,/優先度 50/);
assert.match(element('source-status').innerHTML,/19台取得／未取得台番 2201・2202/);
console.log('Frontend: 8 assertions passed; new rankings, legacy snapshots, missing data, no fake accuracy.');
context.today=new Intl.DateTimeFormat('sv-SE',{timeZone:'Asia/Tokyo',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date());
vm.runInContext("PUBLICATION={date:today,checked_at:new Date().toISOString(),status:'available',deadline_status:'verified_on_time',snapshot_id:'same',ready_models:['myj5'],abstained_models:['myj6']};DATA.forecast.snapshot_id='different';drawPublication();",context);
assert.match(element('publication-panel').innerHTML,/一致しません/);
assert.doesNotMatch(element('publication-panel').innerHTML,/7時前に公開先で確認済み/);
vm.runInContext("DATA.forecast.snapshot_id='same';drawPublication();",context);
assert.match(element('publication-panel').innerHTML,/7時前に公開先で確認済み/);
assert.match(element('publication-panel').innerHTML,/予想あり1機種/);
vm.runInContext("PUBLICATION.date='2020-01-01';drawPublication();",context);
assert.match(element('publication-panel').innerHTML,/今日の公開状態は未確認/);
assert.doesNotMatch(element('publication-panel').innerHTML,/7時前に公開先で確認済み/);
vm.runInContext("PUBLICATION=null;drawPublication();",context);
assert.match(element('publication-panel').innerHTML,/生成時刻だけでは/);
console.log('Publication UI: 7 assertions passed; no stale or mismatched success claims.');
context.pairedSamples=['2026-10-24','2026-10-25'].map(date=>({date,kind:'prospective',version:'experimental-v1',models:{myj5:{status:'complete',strategies:Object.fromEntries(['balanced','dip','rb'].map(key=>[key,{count:3,positive_count:key==='dip'?2:1,mean_difference:key==='dip'?300:100,lift_vs_eligible_mean:key==='dip'?200:0,low_play_count:1}]))}}}));
const compare=()=>vm.runInContext("pairedPerformance(pairedSamples,'myj5','experimental-v1','2026-10-27')",context);
assert.equal(compare().days,2);
assert.equal(compare().summaries.dip.positive,4);
assert.equal(compare().summaries.dip.count,6);
assert.equal(compare().summaries.dip.lift,200);
context.pairedSamples.push({...context.pairedSamples[0],kind:'retrospective',date:'2026-10-23'});
context.pairedSamples.push({...context.pairedSamples[0],version:'different',date:'2026-10-22'});
context.pairedSamples.push({...context.pairedSamples[0],date:'2026-10-27'});
assert.equal(compare().days,2);
context.pairedSamples.push(context.pairedSamples[0]);
assert.equal(compare().days,1);
delete context.pairedSamples[1].models.myj5.strategies.rb;
assert.equal(compare().days,0);
vm.runInContext("DATA.evaluation.prospective=[];DATA.forecast.version='experimental-v1';drawForecast({id:'myj5',name:'V'});",context);
assert.match(element('evaluation-panel').innerHTML,/3方式の同条件比較：0日/);
assert.match(element('evaluation-panel').innerHTML,/成績を0%とは表示しません/);
assert.match(element('evaluation-panel').innerHTML,/プラス台率は設定4〜6の的中率ではありません/);
console.log('Paired strategy comparison: 10 assertions passed.');
context.answerFixture={date:'2026-10-27',models:{myj5:{selected_strategy:'balanced',prediction_results:[
  {rank:1,number:2237,score:80,status:'available',actual:{games:2000,bb:8,rb:3,difference:0}},
  {rank:2,number:2235,score:70,status:'pending_results',actual:null}]}}};
const answers=()=>vm.runInContext("predictionResultHTML(answerFixture,'myj5')",context);
assert.match(answers(),/2026-10-27 朝の予想順位と当日の実績/);
assert.match(answers(),/予想1位/);
assert.ok(answers().indexOf('2237番')<answers().indexOf('2235番'));
assert.match(answers(),/差枚 0枚/);
assert.match(answers(),/当日実績：取得待ち/);
assert.match(answers(),/低稼働/);
delete context.answerFixture.models.myj5.prediction_results;
context.answerFixture.models.myj5.strategies={balanced:{results:[{number:2221,games:5000,bb:20,rb:15,difference:-100}]}};
assert.match(answers(),/2221番/);
assert.match(answers(),/差枚 -100枚/);
console.log('Prediction versus actuals: 8 assertions passed.');
vm.runInContext("DATA.history_coverage={as_of_date:'2026-10-28',window_days:90,complete_days:20,partial_days:16,missing_days:54,days:[{date:'2026-10-26',expected_rows:150,verified_rows:130,incomplete_models:['myj5']}]};drawSources();",context);
assert.match(element('source-status').innerHTML,/全台の数値あり：20日／一部不足：16日／数値未取得：54日/);
assert.match(element('source-status').innerHTML,/130\/150台/);
assert.match(element('source-status').innerHTML,/未取得を休業や実績0とは扱いません/);
assert.doesNotMatch(element('source-status').innerHTML,/最大2営業日/);
console.log('Historical numeric coverage: 4 assertions passed.');
const manifest=JSON.parse(fs.readFileSync('manifest.json','utf8'));
assert.equal(manifest.display,'standalone');
assert.equal(manifest.scope,'./');
assert.equal(manifest.start_url,'./index.html');
assert.match(html,/name="apple-mobile-web-app-capable" content="yes"/);
assert.match(html,/rel="apple-touch-icon" href="app-icon.png"/);
assert.match(html,/閲覧には通信が必要/);
const icon=fs.readFileSync(manifest.icons[0].src);
assert.equal(icon.subarray(1,4).toString(),'PNG');
assert.equal(icon.readUInt32BE(16),512);
assert.equal(icon.readUInt32BE(20),512);
console.log('Home Screen configuration: 9 assertions passed.');
