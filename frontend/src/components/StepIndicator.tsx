const STEPS = [
  { id: 'classify', label: '분류중' },
  { id: 'analyze', label: '분석중' },
  { id: 'aggregate', label: '종합중' },
  { id: 'rewrite', label: '재작성중' },
  { id: 'done', label: '완료' },
] as const;

export type StepId = (typeof STEPS)[number]['id'];

/** SSE progress 이벤트로부터 현재 스텝을 계산 */
export function deriveStep(events: { node?: string }[], status: string): StepId {
  if (status === 'done') return 'done';
  const nodes = new Set(events.map((e) => e.node));
  if (nodes.has('rewrite')) return 'rewrite';
  if (nodes.has('aggregate')) return 'aggregate';
  if (nodes.has('analyze')) return 'analyze';
  return 'classify';
}

export default function StepIndicator({ step }: { step: StepId }) {
  const idx = STEPS.findIndex((s) => s.id === step);
  return (
    <div className="steps">
      {STEPS.map((s, i) => (
        <div key={s.id} className={`step${i < idx ? ' done' : ''}${i === idx ? ' active' : ''}`}>
          <span className="dot" />
          {s.label}
        </div>
      ))}
    </div>
  );
}
