#!/usr/bin/env python3
"""Build data.json for the CI step timing chart.

For the last N commits on risingwavelabs/risingwave main, find the Buildkite
`pull-request` build that ran on that exact commit (the merge-queue build),
fall back to the PR head's build when the queue build ran no jobs, and record
the run time of every job's final attempt.

Only the standard library is used. Set GITHUB_TOKEN to raise the GitHub rate
limit; Buildkite's public pipeline needs no token.
"""
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

REPO = "risingwavelabs/risingwave"
BK = "https://buildkite.com/risingwavelabs/pull-request/builds"
STATUS_CONTEXT = "buildkite/pull-request"
N_COMMITS = int(os.environ.get("N_COMMITS", "100"))
PLUMBING = (":pipeline:", "buildkite-agent pipeline upload")
QUEUE_BRANCH = re.compile(r"^gh-readonly-queue/[^/]+/pr-(\d+)-")


def get_json(url, headers=None, tries=4):
    req = urllib.request.Request(url, headers=headers or {})
    for attempt in range(tries):
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                return json.load(resp)
        except urllib.error.HTTPError as e:
            if e.code < 500 and e.code != 429:
                raise
            err = e
        except (urllib.error.URLError, TimeoutError) as e:
            err = e
        time.sleep(2 ** attempt)
    raise RuntimeError(f"giving up on {url}: {err}")


def gh(path):
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "ci-timing"}
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return get_json(f"https://api.github.com/repos/{REPO}/{path}", headers)


def bk(path):
    return get_json(f"{BK}/{path}", {"Accept": "application/json", "User-Agent": "ci-timing"})


def build_number_for(sha):
    """Build number of the newest whole-pipeline status on the commit, or None.

    The combined-status endpoint (`/status`) sometimes omits the top-level
    context on commits with many statuses, so the full list is read instead.
    """
    newest = None
    page = 1
    while True:
        statuses = gh(f"commits/{sha}/statuses?per_page=100&page={page}")
        for st in statuses:
            if st["context"] == STATUS_CONTEXT and st.get("target_url"):
                if newest is None or st["created_at"] > newest["created_at"]:
                    newest = st
        if len(statuses) < 100:
            break
        page += 1
    if newest is None:
        return None
    return int(newest["target_url"].rstrip("/").rsplit("/", 1)[1])


def script_jobs(build_number):
    page = bk(f"{build_number}/data/jobs")
    if page.get("has_next_page"):
        print(f"warning: build {build_number} job list is paginated; only the first page is used", file=sys.stderr)
    return [j for j in page["records"] if j.get("type") == "script"]


def is_real(job):
    return not job["name"].startswith(PLUMBING)


def seconds_between(a, b):
    if not a or not b:
        return None
    ta = datetime.fromisoformat(a.replace("Z", "+00:00"))
    tb = datetime.fromisoformat(b.replace("Z", "+00:00"))
    return round((tb - ta).total_seconds())


def job_rows(jobs):
    rows = []
    for j in jobs:
        if j.get("retried_in_job_uuid"):
            continue  # an earlier attempt; the final one is recorded
        attempts = sum(1 for k in jobs if k["name"] == j["name"] and k.get("parallel_group_index") == j.get("parallel_group_index"))
        step = j["name"]
        if j.get("parallel_group_total"):
            step = f'{j["name"]} {j["parallel_group_index"] + 1}/{j["parallel_group_total"]}'
        rows.append({"step": step, "family": j["name"], "run": seconds_between(j.get("started_at"), j.get("finished_at")), "attempts": attempts})
    return rows


def main():
    commits = list(reversed(gh(f"commits?sha=main&per_page={N_COMMITS}")))  # oldest first
    per_commit = []
    for c in commits:
        sha = c["sha"]
        subject = c["commit"]["message"].split("\n", 1)[0]
        m = re.search(r"\(#(\d+)\)$", subject)
        entry = {"sha": sha[:10], "date": c["commit"]["committer"]["date"], "subject": subject, "pr": int(m.group(1)) if m else None, "build": None, "src": "none", "rows": []}
        n = build_number_for(sha)
        if n is None:
            print(f"warning: {sha[:10]} has no {STATUS_CONTEXT} status", file=sys.stderr)
            per_commit.append(entry)
            continue
        entry["build"], entry["src"] = n, "queue"
        jobs = script_jobs(n)
        if not any(is_real(j) for j in jobs):
            # The merge-queue build diffs against the PR head and uploads nothing when
            # the trees match; the PR head's own build is the run that tested this tree.
            branch = bk(f"{n}.json").get("branch_name") or ""
            qm = QUEUE_BRANCH.match(branch)
            pr = int(qm.group(1)) if qm else entry["pr"]
            if pr is not None:
                head = gh(f"pulls/{pr}")["head"]["sha"]
                hn = build_number_for(head)
                if hn is not None:
                    entry["build"], entry["src"], jobs = hn, "prhead", script_jobs(hn)
        entry["rows"] = job_rows(jobs)
        print(f'{entry["sha"]} build {entry["build"]} ({entry["src"]}) {len(entry["rows"])} jobs', file=sys.stderr)
        per_commit.append(entry)

    family_total, step_family = {}, {}
    for e in per_commit:
        for r in e["rows"]:
            family_total[r["family"]] = family_total.get(r["family"], 0) + (r["run"] or 0)
            step_family[r["step"]] = r["family"]
    families = sorted(family_total, key=lambda f: -family_total[f])
    steps = []
    for step in sorted(step_family, key=lambda s: (step_family[s], s)):
        run, attempts = [], []
        for e in per_commit:
            r = next((x for x in e["rows"] if x["step"] == step), None)
            run.append(r["run"] if r else None)
            attempts.append(r["attempts"] if r else None)
        steps.append({"step": step, "family": step_family[step], "run": run, "attempts": attempts})

    data = {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "commits": [{k: e[k] for k in ("sha", "date", "subject", "pr", "build", "src")} for e in per_commit],
        "families": families,
        "steps": steps,
    }
    with open("data.json", "w") as f:
        json.dump(data, f, separators=(",", ":"))
    print(f'{len(per_commit)} commits, {len(steps)} steps, {sum(1 for e in per_commit if e["src"] == "prhead")} from PR-head builds', file=sys.stderr)


if __name__ == "__main__":
    main()
