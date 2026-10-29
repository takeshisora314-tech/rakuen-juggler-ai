import test from 'node:test';
import assert from 'node:assert/strict';
import worker,{trigger} from './external_morning_trigger.mjs';
const now=Date.parse('2026-10-29T20:03:00Z'); // 10/30 05:03 JST
const env={GITHUB_ACTIONS_TOKEN:'unit-test-only'};
test('fixed workflow and branch; acceptance is not publication',async()=>{
  let calls=0;
  const result=await trigger({scheduledTime:now},env,async(url,options)=>{
    calls++; assert.equal(url,'https://api.github.com/repos/takeshisora314-tech/rakuen-juggler-ai/actions/workflows/morning-forecast.yml/dispatches');
    assert.equal(options.redirect,'error'); assert.equal(options.method,'POST');
    assert.deepEqual(JSON.parse(options.body),{ref:'main'});
    assert.equal(options.headers.Authorization,'Bearer unit-test-only');
    return {status:204};
  },now);
  assert.equal(calls,1); assert.equal(result.status,'dispatch_accepted');
});
test('late, future and outside morning events make no request',async()=>{
  for(const time of [now-1000, now+600001,Date.parse('2026-10-29T22:00:00Z')]) {
    let calls=0; const result=await trigger({scheduledTime:now},env,async()=>{calls++;},time);
    assert.match(result.status,/skipped/);assert.equal(calls,0);
  }
});
test('missing secret and invalid clocks fail before network',async()=>{
  const fetcher=()=>assert.fail('network forbidden');
  await assert.rejects(trigger({scheduledTime:now},{},fetcher,now),/Missing/);
  await assert.rejects(trigger({scheduledTime:NaN},env,fetcher,now),/clock/);
});
test('HTTP failure and transport failure are not reported as success',async()=>{
  for(const status of [200,202,301,401,403,429,500])
    await assert.rejects(trigger({scheduledTime:now},env,async()=>({status}),now),/dispatch failed/);
  await assert.rejects(trigger({scheduledTime:now},env,async()=>{throw Error('network');},now),/network/);
});
test('public HTTP endpoint cannot dispatch a workflow',async()=>{
  assert.equal((await worker.fetch()).status,404);
});
