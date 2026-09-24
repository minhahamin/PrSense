import { Fragment, useMemo } from 'react';
import type { DiffFile, ReviewComment } from '../types';
import { CommentCard } from './CommentCard';

interface Row {
  kind: 'hunk' | 'add' | 'del' | 'ctx';
  oldLn: number | null;
  newLn: number | null;
  text: string;
}

/** unified diff patch → 렌더 행으로 파싱 */
function parsePatch(patch: string): Row[] {
  const rows: Row[] = [];
  let oldLn = 0;
  let newLn = 0;
  for (const raw of patch.split('\n')) {
    const hunk = raw.match(/^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@/);
    if (hunk) {
      oldLn = parseInt(hunk[1], 10);
      newLn = parseInt(hunk[2], 10);
      rows.push({ kind: 'hunk', oldLn: null, newLn: null, text: raw });
      continue;
    }
    if (raw.startsWith('+') && !raw.startsWith('+++')) {
      rows.push({ kind: 'add', oldLn: null, newLn: newLn++, text: raw.slice(1) });
    } else if (raw.startsWith('-') && !raw.startsWith('---')) {
      rows.push({ kind: 'del', oldLn: oldLn++, newLn: null, text: raw.slice(1) });
    } else {
      const text = raw.startsWith(' ') ? raw.slice(1) : raw;
      rows.push({ kind: 'ctx', oldLn: oldLn++, newLn: newLn++, text });
    }
  }
  return rows;
}

function FileDiff({ file, comments }: { file: DiffFile; comments: ReviewComment[] }) {
  const rows = useMemo(() => parsePatch(file.patch || ''), [file.patch]);
  const byLine = useMemo(() => {
    const m = new Map<number, ReviewComment[]>();
    for (const c of comments) {
      if (!m.has(c.line)) m.set(c.line, []);
      m.get(c.line)!.push(c);
    }
    return m;
  }, [comments]);

  if (!file.patch) {
    return (
      <div className="file-block">
        <div className="file-head">
          <span>{file.filename}</span>
          <span className="dim">{file.status} · diff 없음</span>
        </div>
      </div>
    );
  }

  return (
    <div className="file-block">
      <div className="file-head">
        <span>{file.filename}</span>
        <span className="dim">
          {file.status} · <span style={{ color: '#2f9e44' }}>+{file.additions}</span>{' '}
          <span style={{ color: '#d6336c' }}>-{file.deletions}</span>
          {comments.length > 0 && (
            <span className="pill warning" style={{ marginLeft: 8 }}>
              {comments.length}건
            </span>
          )}
        </span>
      </div>
      <table className="diff-table">
        <tbody>
          {rows.map((r, i) => {
            if (r.kind === 'hunk') {
              return (
                <tr key={i}>
                  <td className="ln">…</td>
                  <td className="ln">…</td>
                  <td className="diff-hunk">{r.text}</td>
                </tr>
              );
            }
            const cls = r.kind === 'add' ? 'diff-add' : r.kind === 'del' ? 'diff-del' : '';
            const inline = r.newLn != null ? byLine.get(r.newLn) ?? [] : [];
            return (
              <Fragment key={i}>
                <tr className={cls}>
                  <td className="ln">{r.oldLn ?? ''}</td>
                  <td className="ln">{r.newLn ?? ''}</td>
                  <td>
                    {r.kind === 'add' ? '+' : r.kind === 'del' ? '-' : ' '}
                    {r.text}
                  </td>
                </tr>
                {inline.map((c, j) => (
                  <tr key={`${i}-c${j}`}>
                    <td className="ln" style={{ border: 'none' }} />
                    <td className="ln" style={{ border: 'none' }} />
                    <td style={{ padding: 0 }}>
                      <CommentCard c={c} />
                    </td>
                  </tr>
                ))}
              </Fragment>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

export default function DiffViewer({
  files,
  comments,
  severityFilter,
}: {
  files: DiffFile[];
  comments: ReviewComment[];
  severityFilter: string;
}) {
  const filtered = comments.filter((c) => severityFilter === 'all' || c.severity === severityFilter);
  return (
    <div>
      {files.map((f) => (
        <FileDiff key={f.filename} file={f} comments={filtered.filter((c) => c.file === f.filename)} />
      ))}
      {files.length === 0 && <div className="empty">diff가 없습니다.</div>}
    </div>
  );
}
