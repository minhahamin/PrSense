import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { fetchPRs } from '../api/client';
import type { PRListItem } from '../types';

export default function PRList() {
  const [prs, setPrs] = useState<PRListItem[]>([]);
  const [err, setErr] = useState('');

  useEffect(() => {
    fetchPRs()
      .then((d) => setPrs(d.prs ?? []))
      .catch((e) => setErr(String(e)));
  }, []);

  return (
    <div className="container">
      <div className="toolbar">
        <h2 style={{ margin: 0 }}>Pull Requests</h2>
        <span style={{ color: '#8b949e' }}>{prs.length}건</span>
      </div>
      {err && <div className="card">불러오기 실패: {err}</div>}
      {!err && prs.length === 0 && (
        <div className="empty">
          아직 리뷰된 PR이 없습니다.
          <br />
          <span className="mono" style={{ fontSize: 12 }}>
            POST /webhook/review/:owner/:repo/:pr 로 리뷰를 트리거하세요.
          </span>
        </div>
      )}
      {prs.map((p) => (
        <Link
          key={p.run_id}
          to={`/pr/${p.repo}/${p.pr_number}`}
          style={{ textDecoration: 'none', color: 'inherit' }}
        >
          <div className="pr-row">
            <span className="num">#{p.pr_number}</span>
            <div style={{ flex: 1 }}>
              <div className="title">{p.title || `${p.repo} #${p.pr_number}`}</div>
              <div className="mono" style={{ fontSize: 12, color: '#8b949e' }}>
                {p.repo} · {p.status} · {p.run_id.slice(-8)}
              </div>
            </div>
            {p.risk_level && <span className={`pill ${p.risk_level}`}>{p.risk_level}</span>}
            {p.recommendation && <span className={`pill ${p.recommendation}`}>{p.recommendation}</span>}
            <span className="mono" style={{ fontSize: 12 }}>
              {p.comment_count} issues
            </span>
          </div>
        </Link>
      ))}
    </div>
  );
}
