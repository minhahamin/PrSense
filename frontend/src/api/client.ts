const BASE = '';

export async function fetchPRs() {
  const r = await fetch(`${BASE}/prs/`);
  if (!r.ok) throw new Error(`list failed: ${r.status}`);
  return r.json();
}

export async function fetchPRDetail(repo: string, pr: number) {
  const r = await fetch(`${BASE}/prs/${repo}/${pr}`);
  if (!r.ok) throw new Error(`detail failed: ${r.status}`);
  return r.json();
}

export async function fetchDiff(repo: string, pr: number) {
  const r = await fetch(`${BASE}/prs/${repo}/${pr}/diff`);
  if (!r.ok) throw new Error(`diff failed: ${r.status}`);
  return r.json();
}

export async function publishReview(repo: string, pr: number) {
  const r = await fetch(`${BASE}/prs/${repo}/${pr}/publish`, { method: 'POST' });
  if (!r.ok) throw new Error(`publish failed: ${r.status}`);
  return r.json();
}

export function subscribeEvents(runId: string, onEvent: (type: string, data: any) => void): EventSource {
  const es = new EventSource(`${BASE}/events/${runId}`);
  const handler = (t: string) => (e: MessageEvent) => {
    try {
      onEvent(t, JSON.parse(e.data || '{}'));
    } catch {
      onEvent(t, {});
    }
  };
  es.addEventListener('started', handler('started') as EventListener);
  es.addEventListener('progress', handler('progress') as EventListener);
  es.addEventListener('result', handler('result') as EventListener);
  es.addEventListener('error', handler('error') as EventListener);
  es.addEventListener('end', handler('end') as EventListener);
  return es;
}
