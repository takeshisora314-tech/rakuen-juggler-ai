/* Conditional coin-balance inversion. Inputs are assumptions, not measured grapes. */
(function(root) {
  function estimateGrapes(row, options) {
    if (!row || !['games','bb','rb','difference'].every(k => Number.isInteger(row[k])) || row.games <= 0 || row.bb < 0 || row.rb < 0 || row.bb + row.rb > row.games) return {status:'invalid_record'};
    const keys=['bbNet','rbNet','grapePay','replayDenominator','otherPayPerGame','differenceError'];
    if (!options || keys.some(k => typeof options[k] !== 'number' || !Number.isFinite(options[k])) || options.bbNet<0 || options.rbNet<0 || options.grapePay<=0 || options.replayDenominator<=1 || options.otherPayPerGame<0 || options.differenceError<0) return {status:'invalid_assumptions'};
    const g=row.games, replay=g/options.replayDenominator;
    const cash=row.difference+3*g-options.bbNet*row.bb-options.rbNet*row.rb-3*replay-options.otherPayPerGame*g;
    const count=cash/options.grapePay, delta=options.differenceError/options.grapePay;
    const maxCount=g-replay-row.bb-row.rb;
    if(count<=0 || count>maxCount || count-delta<=0 || count+delta>maxCount) return {status:'inconsistent_assumptions'};
    return {status:'conditional_estimate',count,denominator:g/count,denominatorLow:g/(count+delta),denominatorHigh:g/(count-delta),calibrated:false};
  }
  function compareGrapeOtherPay(row, options, change=.03) {
    const base=estimateGrapes(row,options);
    if(base.status!=='conditional_estimate') return base;
    if(typeof change!=='number' || !Number.isFinite(change) || change<=0) return {status:'invalid_assumptions'};
    const lowerOtherPay=Math.max(0,options.otherPayPerGame-change),upperOtherPay=options.otherPayPerGame+change;
    const low=estimateGrapes(row,{...options,otherPayPerGame:lowerOtherPay,differenceError:0});
    const high=estimateGrapes(row,{...options,otherPayPerGame:upperOtherPay,differenceError:0});
    if(low.status!=='conditional_estimate' || high.status!=='conditional_estimate') return {status:'inconsistent_assumptions'};
    return {status:'conditional_comparison',lowerOtherPay,upperOtherPay,
      denominatorLow:low.denominator,denominatorHigh:high.denominator,calibrated:false};
  }
  if(typeof module!=='undefined' && module.exports) module.exports={estimateGrapes,compareGrapeOtherPay};
  else {root.estimateGrapes=estimateGrapes;root.compareGrapeOtherPay=compareGrapeOtherPay;}
})(globalThis);

