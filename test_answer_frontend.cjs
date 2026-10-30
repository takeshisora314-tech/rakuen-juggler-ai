const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const panel={innerHTML:'',addEventListener(){}};
const context=vm.createContext({document:{getElementById(){return panel;}},Intl,Date,setInterval(){}});
const script=fs.readFileSync('index.html','utf8').match(/<script>([\s\S]*?)<\/script>/)[1].replace(/load\(\);\s*$/,'');
vm.runInContext(script,context);
const day=vm.runInContext('expectedAnswerDay()',context);
const report={schema_version:1,policy_version:'experimental-v1',date:day,checked_at:'確認時点',snapshot_id:'id',
 predicted_models:1,complete_models:1,pending_models:0,abstained_models:0,status:'complete',models:{myj5:{status:'complete'}}};
function draw(value){context.fixture=value;vm.runInContext("DATA={forecast:{version:'experimental-v1'}};ANSWERS=fixture;drawAnswers();",context);return panel.innerHTML;}
assert.match(draw(null),/確認記録は未取得/);
assert.match(draw(report),/照合が完了/);
assert.match(draw({...report,status:'missing_forecast',predicted_models:0,complete_models:0,abstained_models:1}),/朝予想が未保存/);
assert.match(draw({...report,status:'no_predictions',predicted_models:0,complete_models:0,abstained_models:1}),/全機種が見送り/);
assert.match(draw({...report,status:'pending_results',complete_models:0,pending_models:1}),/実績公開を待って/);
assert.match(draw({...report,status:'partial_results',predicted_models:2,pending_models:1}),/残りは実績待ち/);
assert.match(draw({...report,date:'2000-01-01'}),/過去の確認結果/);
assert.doesNotMatch(draw({...report,date:'2999-01-01'}),/照合が完了/);
assert.doesNotMatch(draw({...report,complete_models:0}),/照合が完了/);
assert.doesNotMatch(draw({...report,predicted_models:0,complete_models:0}),/照合が完了/);
assert.equal(vm.runInContext("expectedAnswerDay(new Date('2026-10-30T13:59:00Z'))",context),'2026-10-29');
assert.equal(vm.runInContext("expectedAnswerDay(new Date('2026-10-30T14:00:00Z'))",context),'2026-10-30');
console.log('Answer status UI: 12 assertions passed.');
