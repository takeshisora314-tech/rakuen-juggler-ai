const assert=require('node:assert/strict');
const {estimateGrapes}=require('./grape_estimator.js');
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
