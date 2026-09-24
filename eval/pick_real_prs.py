"""실제 merged PR 후보 탐색 (파일 수/증감 포함)."""

import json
import urllib.request

REPOS = ["psf/requests", "encode/httpx", "pallets/click"]


def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "prsense-eval"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


for repo in REPOS:
    print(f"=== {repo} ===")
    prs = get(f"https://api.github.com/repos/{repo}/pulls?state=closed&per_page=30")
    n = 0
    for p in prs:
        if not p.get("merged_at"):
            continue
        if (p.get("user") or {}).get("login", "").endswith("[bot]"):
            continue
        num = p["number"]
        d = get(f"https://api.github.com/repos/{repo}/pulls/{num}")
        print(f"  #{num} files={d['changed_files']} "
              f"+{d['additions']}/-{d['deletions']} :: {p['title'][:65]}")
        n += 1
        if n >= 6:
            break
