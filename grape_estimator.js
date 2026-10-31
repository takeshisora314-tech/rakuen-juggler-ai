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
  if(typeof module!=='undefined' && module.exports) module.exports={estimateGrapes};
  else root.estimateGrapes=estimateGrapes;
})(globalThis);
