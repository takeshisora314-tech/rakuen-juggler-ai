const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const {estimateGrapes,compareGrapeOtherPay}=require('./grape_estimator.js');
const html=fs.readFileSync('index.html','utf8'),elements=new Map();
function element(id){if(!elements.has(id))elements.set(id,{innerHTML:'',textContent:'',value:'',listeners:{},addEventListener(type,fn){this.listeners[type]=fn;}});return elements.get(id);}
const ids=['grape-bb','grape-rb','grape-pay','grape-replay','grape-other','grape-error'];
for(const id of ids){const tag=html.match(new RegExp('<input id="'+id+'"[^>]+>'))[0];element(id).value=tag.match(/value="([^"]+)"/)[1];}
const context=vm.createContext({document:{getElementById:element,querySelectorAll(selector){assert.equal(selector,'.grape-settings input');return ids.map(element);}},Intl,Date,URL,estimateGrapes,compareGrapeOtherPay,setInterval(){},fetch(){throw Error('No network');}});
const script=html.match(/<script>([\s\S]*?)<\/script>/)[1].replace(/load\(\);\s*$/,'');
vm.runInContext(script,context);
for(const id of ids)assert.equal(typeof element(id).listeners.input,'function');
context.config={models:[{id:'myj6',name:'VI',installations:[{from:'2026-10-27',until:null,numbers:[2201,2202,2203]}]}]};
context.rows=[{date:'2026-10-31',model_id:'myj6',number:2201,games:6000,bb:20,rb:20,difference:-790},{date:'2026-10-31',model_id:'myj6',number:2202,games:2000,bb:5,rb:5,difference:-100}];
vm.runInContext("CONFIG=config;DATA={machine_records:rows};current='myj6';dateInput.value='2026-10-31';drawGrapes();",context);
const box=element('grape-results');assert.match(box.innerHTML,/2201番/);assert.match(box.innerHTML,/差枚誤差のみの範囲/);assert.match(box.innerHTML,/3,000G未満/);assert.match(box.innerHTML,/2203番：実績未取得/);
assert.match(box.innerHTML,/打ち方・小役条件で変わる幅の例/);
assert.match(box.innerHTML,/0.03〜0.09枚\/G/);
assert.match(box.innerHTML,/実際の誤差を測った値ではありません/);
const before=box.innerHTML;element('grape-other').value='.12';element('grape-other').listeners.input();assert.notEqual(box.innerHTML,before);
assert.match(box.innerHTML,/0.09〜0.15枚\/G/);
element('grape-pay').value='';element('grape-pay').listeners.input();assert.match(box.innerHTML,/計算条件を確認/);
vm.runInContext("current='neoim';drawGrapes()",context);assert.match(box.textContent,/対象外/);
console.log('Grape UI: startup, all six listeners, actual rows, sensitivity updates and invalid/missing inputs passed.');

