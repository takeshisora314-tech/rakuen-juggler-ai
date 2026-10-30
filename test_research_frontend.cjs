const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const element = {innerHTML:''};
const script = fs.readFileSync('index.html','utf8').match(/<script>([\s\S]*?)<\/script>/)[1].replace(/load\(\);\s*$/, '');
element.addEventListener = () => {};
const context = vm.createContext({document:{getElementById(){return element;}},Intl,Date,setInterval(){}});
vm.runInContext(script,context);
function draw(report) {
  context.fixture = report;
  vm.runInContext("DATA={forecast:{version:'experimental-v1'},machine_records:[]};REPORT=fixture;drawResearch({id:'myj5',name:'V'});",context);
  return element.innerHTML;
}
const metrics = {count:6,positive_count:3,positive_rate:0.5,mean_difference:100,lift_vs_eligible_mean:20,low_play_count:1};
const report = {schema_version:1,policy_version:'experimental-v1',as_of_date:'2026-10-01',calendar_days:90,
  window_start:'2026-07-03',window_end_exclusive:'2026-10-01',record_count:0,
  prospective:{models:{myj5:{paired_days:0,strategies:{}}}},
  retrospective:{models:{myj5:{paired_days:2,first_date:'2026-09-28',last_date:'2026-09-29',strategies:{balanced:metrics}}}}};
assert.match(draw(null),/未取得/);
let html=draw(report);
assert.match(html,/実際の事前保存予想：比較可能0日/);
assert.match(html,/過去再計算（事前予想ではありません）：比較可能2日/);
assert.match(html,/3\/6台（50.0%）/);
assert.match(html,/基準日時点/);
assert.match(html,/設定4〜6の的中率ではありません/);
assert.match(html,/方式切替には使いません/);
assert.match(html,/30日以上の事前評価/);
assert.doesNotMatch(draw({...report,policy_version:'other'}),/50.0%/);
assert.doesNotMatch(draw({...report,as_of_date:'2999-01-01'}),/50.0%/);
const broken=JSON.parse(JSON.stringify(report));
broken.retrospective.models.myj5.strategies.balanced.positive_rate=NaN;
assert.doesNotMatch(draw(broken),/NaN|50.0%/);
vm.runInContext('drawResearch(null)',context);
assert.equal(element.innerHTML,'');
console.log('Research summary UI: 12 assertions passed.');
