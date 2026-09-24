import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useParams } from 'react-router-dom';
import {
  fetchDiff,
  fetchPRDetail,
  publishReview,
  subscribeEvents,
  triggerReview,
} from '../api/client';
import DiffViewer from '../components/DiffViewer';
import StepIndicator, { deriveStep } from '../components/StepIndicator';
import SummaryCard from '../components/SummaryCard';
import type { DiffFile, PRDetail } from '../types';

interface ProgressEvent {
  node?: string;
  detail?: string;
}

export default function PRDetailPage() {
  const { owner, repo, pr } = useParams();
  const fullRepo = `${owner}/${repo}`;
  const prNumber = Number(pr);
  const [detail, setDetail] = useState<PRDetail | null>(null);
  const [runId, setRunId] = useState<string | null>(null);
  const [status, setStatus] = useState('missing');
  const [events, setEvents] = useState<ProgressEvent[]>([]);
  const [files, setFiles] = useState<DiffFile[]>([]);
  const [filter, setFilter] = useState('all');
  const [msg, setMsg] = useState('');
  const esRef = useRef<EventSource | null>(null);

  const loadDetail = useCallback(async () => {
    try {
      const d: PRDetail = await fetchPRDetail(fullRepo, prNumber);
      setDetail(d.status === 'missing' ? null : d);
      setRunId(d.run_id ?? null);
      setStatus(d.status ?? 'missing');
    } catch {
      setDetail(null);
      setRunId(null);
      setStatus('missing');
    }
    try {
      const d = await fetchDiff(fullRepo, prNumber);
      setFiles(d.files ?? []);
    } catch {
      /* diff는 없어도 진행 표시와 요약은 동작 */
    }
  }, [fullRepo, prNumber]);

  // 최초 로드
  useEffect(() => {
    loadDetail();
  }, [loadDetail]);

  // runId가 있고 아직 끝나지 않았으면 SSE 실시간 구독 (새로고침 불필요)
  useEffect(() => {
    esRef.current?.close();
    esRef.current = null;
    if (!runId || status === 'done' || status === 'error' || status === 'missing') return;
    const es = subscribeEvents(runId, (type, data) => {
      if (type === 'progress') setEvents((prev) => [...prev, data]);
      if (type === 'result' || type === 'error' || type === 'end') {
        // 최종 결과는 서버에서 다시 조회 (단일 진실 공급원)
        loadDetail();
      }
      if (type === 'end' || type === 'error') es.close();
    });
    esRef.current = es;
    return () => es.close();
  }, [runId, status, loadDetail]);

  const step = useMemo(() => deriveStep(events, status), [events, status]);
  const lastDetail = events.length > 0 ? events[events.length - 1].detail : '';

  const onRerun = async () => {
    try {
      setMsg('리뷰를 시작합니다…');
      setEvents([]);
      const { run_id } = await triggerReview(fullRepo, prNumber);
      setRunId(run_id);
      setStatus('running');
      setDetail(null);
      setMsg('');
    } catch (e) {
      setMsg(`실행 실패: ${e}`);
    }
  };

  const onPublish = async () => {
    try {
      const r = await publishReview(fullRepo, prNumber);
      setMsg(`GitHub에 ${r.posted}건 게시 완료`);
    } catch (e) {
      setMsg(`게시 실패: ${e}`);
    }
  };

  const finished = status === 'done' && detail?.classification;

  return (
    <div className="container">
      <StepIndicator step={step} />
      {status === 'running' && (
        <div className="card" style={{ marginBottom: 12, color: '#8b949e', fontSize: 13 }}>
          실시간 분석 중{lastDetail ? ` — ${lastDetail}` : '…'}
        </div>
      )}
      {msg && <div className="card" style={{ marginBottom: 12 }}>{msg}</div>}
      {finished && detail && <SummaryCard detail={detail} />}
      <div className="toolbar" style={{ marginTop: 16 }}>
        <select className="btn" value={filter} onChange={(e) => setFilter(e.target.value)}>
          <option value="all">전체 심각도</option>
          <option value="critical">critical</option>
          <option value="warning">warning</option>
          <option value="nit">nit</option>
        </select>
        <button className="btn" onClick={onRerun}>
          리뷰 다시 실행
        </button>
        <button className="btn primary" onClick={onPublish} disabled={!finished}>
          GitHub에 게시
        </button>
      </div>
      {status === 'missing' && (
        <div className="empty">
          아직 이 PR의 리뷰가 없습니다.
          <br />
          [리뷰 다시 실행] 버튼으로 분석을 시작하세요.
        </div>
      )}
      {status === 'error' && (
        <div className="card">리뷰 실행 중 오류가 발생했습니다. 다시 실행해주세요.</div>
      )}
      {finished && detail && (
        <DiffViewer files={files} comments={detail.comments} severityFilter={filter} />
      )}
    </div>
  );
}
