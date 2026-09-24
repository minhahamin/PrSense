import { isLowConfidence, type ReviewComment } from '../types';

export function SeverityBadge({ severity }: { severity: string }) {
  return <span className={`sev ${severity}`}>{severity}</span>;
}

export function CommentCard({ c }: { c: ReviewComment }) {
  const low = isLowConfidence(c);
  return (
    <div className={`inline-comment ${c.severity}${low ? ' lowconf' : ''}`}>
      <div className="meta">
        <SeverityBadge severity={c.severity} />
        <span className="cat mono">{c.category}</span>
        {low && <span className="badge-low">확인 필요 · 신뢰도 {c.confidence.toFixed(2)}</span>}
        {!low && <span className="conf">신뢰도 {c.confidence.toFixed(2)}</span>}
      </div>
      <div>{c.comment}</div>
      {c.suggested_fix && (
        <div className="fix">
          <div className="label">제안 수정</div>
          <pre>{c.suggested_fix}</pre>
        </div>
      )}
    </div>
  );
}
