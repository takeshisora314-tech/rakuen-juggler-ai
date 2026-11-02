// Cloudflare Git integration entry point for Worker "deploy".
// Separate watch-path entries saved; verify Cloudflare build logs.
// Runtime secret and cron activation are separate, explicitly approved steps.
const ENDPOINTS = Object.freeze({
  morning:'https://api.github.com/repos/takeshisora314-tech/rakuen-juggler-ai/actions/workflows/morning-forecast.yml/dispatches',
  evening:'https://api.github.com/repos/takeshisora314-tech/rakuen-juggler-ai/actions/workflows/collect-test.yml/dispatches'
});
function routeAt(local) {
  const hour=local.getUTCHours(), minute=local.getUTCMinutes();
  if (hour>=5 && hour<7) return 'morning';
  if ((hour===23 && minute>=30) || hour<3) return 'evening';
  return null;
}
export async function trigger(event, env, fetcher = fetch, now = Date.now()) {
  const scheduled = event.scheduledTime;
  if (!Number.isFinite(now) || !Number.isFinite(scheduled)) throw new Error('Invalid clock');
  const local = new Date(now + 9 * 3600000);
  const scheduledLocal = new Date(scheduled + 9 * 3600000);
  const route=routeAt(local);
  if (now < scheduled || now - scheduled > 600000 ||
      local.toISOString().slice(0,10) !== scheduledLocal.toISOString().slice(0,10) ||
      !route || route!==routeAt(scheduledLocal)) {
    return {status:'skipped_outside_window_or_stale'};
  }
  if (!env.GITHUB_ACTIONS_TOKEN) throw new Error('Missing GitHub secret');
  const response = await fetcher(ENDPOINTS[route], {
    method:'POST', redirect:'manual', signal:AbortSignal.timeout(15000),
    headers:{Authorization:`Bearer ${env.GITHUB_ACTIONS_TOKEN}`,
      Accept:'application/vnd.github+json', 'User-Agent':'rakuen-morning-trigger',
      'X-GitHub-Api-Version':'2026-03-10'},
    body:JSON.stringify({ref:'main'})
  });
  // Acceptance is NOT execution, forecast generation, or publication evidence.
  if (response.status !== 204) throw new Error(`GitHub dispatch failed: HTTP ${response.status}`);
  return {status:'dispatch_accepted',observed_at:new Date(now).toISOString()};
}
export default {
  async scheduled(event, env) {
    console.log(JSON.stringify(await trigger(event,env)));
  },
  async fetch() { return new Response('Not found',{status:404}); }
};

