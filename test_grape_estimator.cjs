const assert=require('node:assert/strict');
const {estimateGrapes,compareGrapeOtherPay}=require('./grape_estimator.js');
const opts={bbNet:240,rbNet:96,grapePay:8,replayDenominator:8,otherPayPerGame:.04,differenceError:80};
// Independent coin ledger: 6000 games, 750 replay, 1000 grapes, 240 other coins.
const row={games:6000,bb:20,rb:20,difference:8000+2250+240+4800+1920-18000};
const r=estimateGrapes(row,opts);assert.equal(r.count,1000);assert.equal(r.denominator,6);
assert(r.denominatorLow<6 && r.denominatorHigh>6);
assert.equal(estimateGrapes({...row,difference:null},opts).status,'invalid_record');
assert.equal(estimateGrapes(row,{...opts,replayDenominator:0}).status,'invalid_assumptions');
assert.equal(estimateGrapes({...row,difference:-100000},opts).status,'inconsistent_assumptions');
assert(estimateGrapes({...row,difference:row.difference+80},opts).denominator<r.denominator);
assert(estimateGrapes(row,{...opts,otherPayPerGame:.08}).denominator>r.denominator);
console.log('PASS: synthetic coin balance; error range; invalid inputs; payout sensitivity');
const s=compareGrapeOtherPay(row,opts);
assert.equal(s.status,'conditional_comparison');
assert(Math.abs(s.denominatorLow-6000/1022.5)<1e-10);
assert(Math.abs(s.denominatorHigh-6000/977.5)<1e-10);
assert.deepEqual(s,compareGrapeOtherPay(row,{...opts,differenceError:0}));
assert.equal(compareGrapeOtherPay(row,{...opts,otherPayPerGame:0}).lowerOtherPay,0);
assert.equal(compareGrapeOtherPay(row,opts,NaN).status,'invalid_assumptions');
assert.equal(compareGrapeOtherPay(row,opts,100).status,'inconsistent_assumptions');
console.log('PASS: other-payout comparison, independent ledger endpoints, zero boundary and invalid scenarios');
const {review}=require('./review_grape_conditions.cjs');
const original={...row,date:'2026-11-01',model_id:'myj5',number:2221};
const audit=review({machine_records:[original,{...original,date:'2026-11-02'},
  {...original,number:2222,games:2000}]},'2026-11-02');
assert.equal(audit.models.myj5.rows,2);
assert.equal(audit.models.myj5.counts.compared,1);
assert.equal(audit.models.myj5.counts.under_3000,1);
assert.equal(audit.models.myj6.mean_other_pay_width,null);
assert.equal(audit.changes_live_strategy,false);

