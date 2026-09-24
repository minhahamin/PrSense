"""사람 리뷰 vs 에이전트 리뷰 겹침 측정 (간단한 precision/recall).

입력: JSON 파일 {"human": [{"file":..., "line":..., "note":...}], "agent": [...]}
  agent 항목은 ReviewComment 스키마를 따름.

매칭 규칙: 같은 파일 + 라인 윈도우(±3줄) 안에 있으면 hit.
실행:
    python eval/compare_reviews.py --human eval/sample_human.json --agent eval/last_result.json

출력: precision / recall / F1 + 매칭 상세.
"""

from __future__ import annotations

import argparse
import json

LINE_WINDOW = 3


def load_comments(path: str, key: str | None = None) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, dict):
        if key and key in data:
            return data[key]
        # test_real_prs.py 출력 형태: {"comments": [...]}
        return data.get("comments", data.get("human", []))
    return data


def match(h: dict, agents: list[dict]) -> dict | None:
    for a in agents:
        if (a.get("file") or "") != (h.get("file") or ""):
            continue
        try:
            if abs(int(a.get("line", -999)) - int(h.get("line", -999))) <= LINE_WINDOW:
                return a
        except (TypeError, ValueError):
            continue
    return None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--human", required=True)
    ap.add_argument("--agent", required=True)
    ap.add_argument("--agent-key", default=None)
    args = ap.parse_args()

    human = load_comments(args.human, "human")
    agent = load_comments(args.agent, args.agent_key)

    hits = []
    for h in human:
        m = match(h, agent)
        hits.append({"human": h, "agent_match": m})

    matched_agent_ids = {id(m["agent_match"]) for m in hits if m["agent_match"]}
    recall = (len([h for h in hits if h["agent_match"]]) / len(human)) if human else 0.0
    precision = (len(matched_agent_ids) / len(agent)) if agent else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0

    print(f"human: {len(human)}  agent: {len(agent)}")
    print(f"precision: {precision:.2f}  recall: {recall:.2f}  F1: {f1:.2f}")
    print(f"(매칭 기준: 동일 파일 ±{LINE_WINDOW}줄)")
    for h in hits:
        mark = "✅" if h["agent_match"] else "❌"
        a = h["agent_match"] or {}
        print(f" {mark} {h['human'].get('file')}:{h['human'].get('line')} — "
              f"{str(h['human'].get('note', h['human'].get('comment', '')))[:70]}"
              + (f"  ↔ agent[{a.get('severity')}] {str(a.get('comment', ''))[:60]}" if a else ""))


if __name__ == "__main__":
    main()
