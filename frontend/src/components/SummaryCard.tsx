import type { PRDetail } from '../types';

export default function SummaryCard({ detail }: { detail: PRDetail }) {
  const { classification, comments, recommendation } = detail;
  const files = new Set(comments.map((c) => c.file)).size;
  return (
    <div className="card">
      <div style={{ fontWeight: 700, marginBottom: 6 }}>
        {detail.repo} #{detail.pr_number}
      </div>
      <div style={{ color: '#8b949e', fontSize: 13 }}>{classification.summary}</div>
      <div className="summary-grid">
        <div className="stat">
          <div className="k">변경 파일 (지적)</div>
          <div className="v">{files}</div>
        </div>
        <div className="stat">
          <div className="k">이슈</div>
          <div className="v">{comments.length}</div>
        </div>
        <div className="stat">
          <div className="k">리스크</div>
          <div className="v">
            <span className={`pill ${classification.risk_level}`}>{classification.risk_level}</span>
          </div>
        </div>
        <div className="stat">
          <div className="k">추천</div>
          <div className="v">
            <span className={`pill ${recommendation}`}>{recommendation}</span>
          </div>
        </div>
      </div>
      <div style={{ fontSize: 12, color: '#8b949e' }}>
        변경 유형: <span className="mono">{classification.change_type}</span>
        {' · '}신뢰도 낮은 지적: {detail.low_confidence_count}건
        {classification.focus_areas?.length > 0 && (
          <> · 집중 영역: <span className="mono">{classification.focus_areas.join(', ')}</span></>
        )}
      </div>
    </div>
  );
}
