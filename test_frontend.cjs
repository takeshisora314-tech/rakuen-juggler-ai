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
