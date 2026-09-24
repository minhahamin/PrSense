"""Function/class-granularity chunking for code RAG.

Strategy:
- Python files: AST parse → one chunk per FunctionDef/AsyncFunctionDef/ClassDef
  (with leading docstring), plus a leftover "module" chunk for imports/globals.
- Other text files: sliding-window split by lines (max ~120 lines, 20 overlap).
- Each chunk carries metadata: path, type, name, lines.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path

SUPPORTED_SUFFIXES = {
    ".py", ".ts", ".tsx", ".js", ".jsx", ".go", ".java", ".rs", ".md", ".txt",
}

MAX_LINES_FALLBACK = 120
OVERLAP_FALLBACK = 20


@dataclass
class CodeChunk:
    content: str
    path: str
    kind: str  # "function" | "class" | "module" | "block"
    name: str
    start_line: int
    end_line: int

    def to_document(self) -> str:
        header = f"# {self.path} :: {self.kind} {self.name} (L{self.start_line}-{self.end_line})\n"
        return header + self.content


def chunk_python_file(path: str, source: str) -> list[CodeChunk]:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return chunk_text_fallback(path, source)

    lines = source.splitlines()
    chunks: list[CodeChunk] = []
    covered: list[tuple[int, int]] = []

    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            start = node.lineno
            end = getattr(node, "end_lineno", start)
            covered.append((start, end))
            kind = "class" if isinstance(node, ast.ClassDef) else "function"
            snippet = "\n".join(lines[start - 1 : end])
            chunks.append(
                CodeChunk(
                    content=snippet,
                    path=path,
                    kind=kind,
                    name=node.name,
                    start_line=start,
                    end_line=end,
                )
            )

    # leftover module-level code (imports, constants)
    covered_set: set[int] = set()
    for s, e in covered:
        covered_set.update(range(s, e + 1))
    leftover = [ln for i, ln in enumerate(lines, start=1) if i not in covered_set]
    leftover_text = "\n".join(leftover).strip()
    if leftover_text:
        chunks.append(
            CodeChunk(
                content=leftover_text[:6000],
                path=path,
                kind="module",
                name="(module)",
                start_line=1,
                end_line=len(lines),
            )
        )
    if not chunks:
        return chunk_text_fallback(path, source)
    return chunks


def chunk_text_fallback(path: str, source: str) -> list[CodeChunk]:
    lines = source.splitlines()
    chunks: list[CodeChunk] = []
    step = MAX_LINES_FALLBACK - OVERLAP_FALLBACK
    for i in range(0, max(len(lines), 1), step):
        block = lines[i : i + MAX_LINES_FALLBACK]
        if not block or not "\n".join(block).strip():
            continue
        chunks.append(
            CodeChunk(
                content="\n".join(block),
                path=path,
                kind="block",
                name=f"block-{i // step}",
                start_line=i + 1,
                end_line=min(i + MAX_LINES_FALLBACK, len(lines)),
            )
        )
    return chunks


def chunk_file(path: str, source: str) -> list[CodeChunk]:
    if path.endswith(".py"):
        return chunk_python_file(path, source)
    return chunk_text_fallback(path, source)


def collect_repo_files(root: Path, max_bytes: int = 200_000) -> list[tuple[str, str]]:
    """Walk repo root, return (rel_path, text) for indexable files."""
    out: list[tuple[str, str]] = []
    skip_dirs = {".git", "node_modules", "__pycache__", ".venv", "venv", "dist", "build", ".next"}
    for p in root.rglob("*"):
        if not p.is_file():
            continue
        if any(part in skip_dirs for part in p.parts):
            continue
        if p.suffix not in SUPPORTED_SUFFIXES:
            continue
        try:
            if p.stat().st_size > max_bytes:
                continue
            text = p.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if text.strip():
            out.append((p.relative_to(root).as_posix(), text))
    return out
