import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync, existsSync} from 'node:fs';
import worker,{trigger} from './external_morning_trigger.mjs';
const now=Date.parse('2026-10-29T20:03:00Z'); // 10/30 05:03 JST
const env={GITHUB_ACTIONS_TOKEN:'unit-test-only'};
test('fixed workflow and branch; acceptance is not publication',async()=>{
  let calls=0;
  const result=await trigger({scheduledTime:now},env,async(url,options)=>{
    calls++; assert.equal(url,'https://api.github.com/repos/takeshisora314-tech/rakuen-juggler-ai/actions/workflows/morning-forecast.yml/dispatches');
    assert.equal(options.redirect,'manual'); assert.equal(options.method,'POST');
    assert.deepEqual(JSON.parse(options.body),{ref:'main'});
    assert.equal(options.headers.Authorization,'Bearer unit-test-only');
    return {status:204};
  },now);
  assert.equal(calls,1); assert.equal(result.status,'dispatch_accepted');
});
test('late, future and outside allowed windows make no request',async()=>{
  for(const time of [now-1000, now+600001,Date.parse('2026-10-29T22:00:00Z')]) {
    let calls=0; const result=await trigger({scheduledTime:now},env,async()=>{calls++;},time);
    assert.match(result.status,/skipped/);assert.equal(calls,0);
  }
});

test('night and after-midnight retries dispatch collection, never a backdated morning forecast',async()=>{
  for(const iso of ['2026-11-03T14:33:00Z','2026-11-03T15:33:00Z','2026-11-03T17:33:00Z']) {
    const time=Date.parse(iso);let calls=0;
    const result=await trigger({scheduledTime:time},env,async(url,options)=>{
      calls++;
      assert.equal(url,'https://api.github.com/repos/takeshisora314-tech/rakuen-juggler-ai/actions/workflows/collect-test.yml/dispatches');
      assert.deepEqual(JSON.parse(options.body),{ref:'main'});
      assert.equal(options.redirect,'manual');
      return {status:204};
    },time);
    assert.equal(calls,1);assert.equal(result.status,'dispatch_accepted');
  }
});

test('night window boundaries and scheduled time are checked before transmission',async()=>{
  const fetcher=()=>assert.fail('network forbidden');
  for(const iso of ['2026-11-03T14:29:59Z','2026-11-03T18:00:00Z',
                     '2026-11-03T19:59:59Z','2026-11-03T22:00:00Z']) {
    const time=Date.parse(iso);
    assert.match((await trigger({scheduledTime:time},env,fetcher,time)).status,/skipped/);
  }
  const justBefore=Date.parse('2026-11-03T14:29:59Z');
  assert.match((await trigger({scheduledTime:justBefore},env,fetcher,justBefore+2000)).status,/skipped/);
  const late=Date.parse('2026-11-03T14:33:00Z');
  assert.match((await trigger({scheduledTime:late},env,fetcher,late+600001)).status,/skipped/);
});

test('night dispatch failure cannot be reported as completion',async()=>{
  const time=Date.parse('2026-11-03T14:33:00Z');
  await assert.rejects(trigger({scheduledTime:time},env,async()=>({status:403}),time),/dispatch failed/);
  await assert.rejects(trigger({scheduledTime:time},{},()=>assert.fail('network forbidden'),time),/Missing/);
});

test('all existing four morning slots still dispatch only the morning workflow',async()=>{
  for(const iso of ['2026-11-03T20:03:00Z','2026-11-03T20:33:00Z',
                     '2026-11-03T21:03:00Z','2026-11-03T21:33:00Z']) {
    const time=Date.parse(iso);
    const result=await trigger({scheduledTime:time},env,async url=>{
      assert.match(url,/morning-forecast.yml\/dispatches$/);return {status:204};
    },time);
    assert.equal(result.status,'dispatch_accepted');
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
test('Git integration uses the existing Worker and no public URLs or embedded secrets',()=>{
  const config=JSON.parse(readFileSync(new URL('./wrangler.jsonc',import.meta.url),'utf8'));
  assert.equal(config.name,'deploy');
  assert.equal(config.main,'external_morning_trigger.mjs');
  assert.ok(existsSync(new URL(config.main,import.meta.url)));
  assert.equal(config.workers_dev,false);
  assert.equal(config.preview_urls,false);
  assert.equal(config.vars,undefined);
  assert.deepEqual(config.triggers.crons,['3,33 20,21 * * *','33 14,15,17 * * *']);
});

test('configured daily schedules preserve four morning slots and add exactly three night slots',async()=>{
  const config=JSON.parse(readFileSync(new URL('./wrangler.jsonc',import.meta.url),'utf8'));
  const observed=[];
  for(const cron of config.triggers.crons) {
    const [minutes,hours,day,month,weekday]=cron.split(' ');
    assert.deepEqual([day,month,weekday],['*','*','*']);
    for(const hour of hours.split(',').map(Number)) for(const minute of minutes.split(',').map(Number)) {
      const time=Date.UTC(2026,10,3,hour,minute);
      const local=new Date(time+9*3600000);
      const label=local.toISOString().slice(11,16);
      const result=await trigger({scheduledTime:time},env,async(url)=>{
        observed.push([label,url.includes('morning-forecast')?'morning':'evening']);
        return {status:204};
      },time);
      assert.equal(result.status,'dispatch_accepted');
    }
  }
  assert.deepEqual(observed.sort(),[
    ['00:33','evening'],['02:33','evening'],['05:03','morning'],
    ['05:33','morning'],['06:03','morning'],['06:33','morning'],['23:33','evening']]);
});


test('Workers-compatible request rejects redirects without following or forwarding the token',async()=>{
  let calls=0;
  await assert.rejects(trigger({scheduledTime:now},env,async(url,options)=>{
    calls++;
    if (!['follow','manual'].includes(options.redirect)) throw new TypeError('Invalid redirect value');
    assert.equal(options.redirect,'manual');
    return new Response(null,{status:302,headers:{Location:'https://example.invalid/'}});
  },now),/GitHub dispatch failed: HTTP 302/);
  assert.equal(calls,1);
});
