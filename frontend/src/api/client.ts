// API 베이스 URL 우선순위:
//  1) window.__BACKEND_URL__ — Railway 등 배포 환경에서 컨테이너 부팅 시 주입 (env.js)
//  2) VITE_API_URL — 빌드 타임 변수
//  3) '' — 로컬 dev (vite proxy /prs, /events … 사용)
declare global {
  interface Window {
    __BACKEND_URL__?: string;
  }
}
const BASE =
  (typeof window !== 'undefined' && window.__BACKEND_URL__) ||
  (import.meta.env.VITE_API_URL as string | undefined) ||
  '';

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

export async function triggerReview(repo: string, pr: number): Promise<{ run_id: string }> {
  const r = await fetch(`${BASE}/webhook/review/${repo}/${pr}`, { method: 'POST' });
  if (!r.ok) throw new Error(`trigger failed: ${r.status}`);
  return r.json();
}

export function subscribeEvents(runId: string, onEvent: (type: string, data: any) => void): EventSource {
  const es = new EventSource(`${BASE}/events/${encodeURIComponent(runId)}`);
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
