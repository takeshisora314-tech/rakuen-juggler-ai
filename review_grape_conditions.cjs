// Offline assumption audit, without measured grape counts or setting labels.
const fs=require('node:fs'),crypto=require('node:crypto');
const {estimateGrapes,compareGrapeOtherPay}=require('./grape_estimator.js');
function review(data,asOf) {
  const options={bbNet:240,rbNet:96,grapePay:8,replayDenominator:7.3,otherPayPerGame:.06,differenceError:100};
  const models={};
  for(const model of ['myj5','myj6']) {
    const rows=data.machine_records.filter(r=>r.model_id===model && r.date<asOf);
    const widths=[],counts={},examples=[];
    for(const row of rows) {
      if(row.games<3000){counts.under_3000=(counts.under_3000||0)+1;continue;}
      const base=estimateGrapes(row,options);
      if(base.status!=='conditional_estimate'){counts[base.status]=(counts[base.status]||0)+1;continue;}
      const alternative=compareGrapeOtherPay(row,options);
      if(alternative.status!=='conditional_comparison'){counts.comparison_unavailable=(counts.comparison_unavailable||0)+1;continue;}
      counts.compared=(counts.compared||0)+1;
      const width=alternative.denominatorHigh-alternative.denominatorLow;
      widths.push(width);
      examples.push({date:row.date,number:row.number,denominator:base.denominator,
        difference_only_width:base.denominatorHigh-base.denominatorLow,
        other_pay_only_width:width,other_pay_only_low:alternative.denominatorLow,
        other_pay_only_high:alternative.denominatorHigh});
    }
    widths.sort((a,b)=>a-b);examples.sort((a,b)=>b.other_pay_only_width-a.other_pay_only_width);
    models[model]={rows:rows.length,counts,compared_days:new Set(examples.map(e=>e.date)).size,
      mean_other_pay_width:widths.length?widths.reduce((a,b)=>a+b,0)/widths.length:null,
      largest_width_examples:examples.slice(0,3)};
  }
  return {kind:'grape_assumption_display_audit',as_of:asOf,calibrated:false,
    changes_live_strategy:false,options,other_pay_comparison:{lower:.03,upper:.09},models,
    interpretation:'Arbitrary other-payout variation, not measured play-style error, confidence interval, actual grape accuracy or setting validation. Only available saved rows before as_of; under 3000G excluded. Difference-only and other-payout-only ranges are separate.'};
}
if(require.main===module) {
  const [input,asOf,output]=process.argv.slice(2);
  if(!input||!/^\d{4}-\d{2}-\d{2}$/.test(asOf||'')||!output)throw Error('Usage: node review_grape_conditions.cjs data.json YYYY-MM-DD output.json');
  const bytes=fs.readFileSync(input),report=review(JSON.parse(bytes),asOf);
  report.data_sha256=crypto.createHash('sha256').update(bytes).digest('hex');
  fs.writeFileSync(output,JSON.stringify(report,null,2)+'\n');
  console.log(JSON.stringify(report.models));
}
module.exports={review};
