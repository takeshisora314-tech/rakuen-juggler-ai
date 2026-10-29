// Cloudflare Git integration entry point for Worker "deploy".
// Retry Git-connected build; verify Cloudflare logs separately.
// Runtime secret and cron activation are separate, explicitly approved steps.
const ENDPOINT = 'https://api.github.com/repos/takeshisora314-tech/rakuen-juggler-ai/actions/workflows/morning-forecast.yml/dispatches';
export async function trigger(event, env, fetcher = fetch, now = Date.now()) {
  const scheduled = event.scheduledTime;
  if (!Number.isFinite(now) || !Number.isFinite(scheduled)) throw new Error('Invalid clock');
  const local = new Date(now + 9 * 3600000);
  const scheduledLocal = new Date(scheduled + 9 * 3600000);
  if (now < scheduled || now - scheduled > 600000 ||
      local.toISOString().slice(0,10) !== scheduledLocal.toISOString().slice(0,10) ||
      local.getUTCHours() < 5 || local.getUTCHours() >= 7) {
    return {status:'skipped_outside_window_or_stale'};
  }
  if (!env.GITHUB_ACTIONS_TOKEN) throw new Error('Missing GitHub secret');
  const response = await fetcher(ENDPOINT, {
    method:'POST', redirect:'error', signal:AbortSignal.timeout(15000),
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
