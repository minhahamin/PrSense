import { useEffect, useMemo, useState } from 'react';
import { useParams } from 'react-router-dom';
import { fetchDiff, fetchPRDetail, publishReview, subscribeEvents } from '../api/client';
import DiffViewer from '../components/DiffViewer';
import StepIndicator, { deriveStep } from '../components/StepIndicator';
import SummaryCard from '../components/SummaryCard';
import type { DiffFile, PRDetail } from '../types';

export default function PRDetailPage() {
  const { owner, repo, pr } = useParams();
  const fullRepo = `${owner}/${repo}`;
  const prNumber = Number(pr);
  const [detail, setDetail] = useState<PRDetail | null>(null);
  const [files, setFiles] = useState<DiffFile[]>([]);
  const [events, setEvents] = useState<{ node?: string }[]>([]);
  const [status, setStatus] = useState('running');
  const [filter, setFilter] = useState('all');
  const [msg, setMsg] = useState('');

  useEffect(() => {
    fetchPRDetail(fullRepo, prNumber)
      .then((d) => {
        setDetail(d);
        setStatus(d.status ?? 'done');
      })
      .catch(() => setMsg('리뷰 결과를 불러오지 못했습니다. (아직 실행 중일 수 있음)'));
    fetchDiff(fullRepo, prNumber)
      .then((d) => setFiles(d.files ?? []))
      .catch(() => {});
  }, [fullRepo, prNumber]);

  // 실시간 진행 구독 (run_id를 알 때만)
  useEffect(() => {
    if (!detail?.run_id || status === 'done') return;
    const es = subscribeEvents(detail.run_id, (type, data) => {
      if (type === 'progress') setEvents((prev) => [...prev, data]);
      if (type === 'result' && data.result) {
        setDetail((prev) =>
          prev ? { ...prev, ...data.result, run_id: prev.run_id } : prev,
        );
        setStatus('done');
      }
      if (type === 'end') es.close();
    });
    return () => es.close();
  }, [detail?.run_id, status]);

  const step = useMemo(() => deriveStep(events, status), [events, status]);

  const onPublish = async () => {
    try {
      const r = await publishReview(fullRepo, prNumber);
      setMsg(`GitHub에 ${r.posted}건 게시 완료`);
    } catch (e) {
      setMsg(`게시 실패: ${e}`);
    }
  };

  return (
    <div className="container">
      <StepIndicator step={step} />
      {msg && <div className="card" style={{ marginBottom: 12 }}>{msg}</div>}
      {detail && <SummaryCard detail={detail} />}
      <div className="toolbar" style={{ marginTop: 16 }}>
        <select className="btn" value={filter} onChange={(e) => setFilter(e.target.value)}>
          <option value="all">전체 심각도</option>
          <option value="critical">critical</option>
          <option value="warning">warning</option>
          <option value="nit">nit</option>
        </select>
        <button className="btn primary" onClick={onPublish}>
          GitHub에 게시
        </button>
      </div>
      {detail && <DiffViewer files={files} comments={detail.comments} severityFilter={filter} />}
    </div>
  );
}
