# RisingWave CI step timing

One chart: run time of every Buildkite `pull-request` job for each commit on
`risingwavelabs/risingwave` main since 2026-08-27, one curve per step.

- `commits.jsonl` holds one line per main commit, oldest first, with the run
  time of every job in the build that tested it.
- `fetch_data.py` appends the commits that landed since the last line
  (`python3 fetch_data.py`; set `GITHUB_TOKEN` for a higher rate limit). With
  no file present it seeds the last 100 commits.
- `index.html` reads `commits.jsonl` and draws one curve per step; the
  selector limits the view to the most recent commits.
- The workflow in `.github/workflows/update.yml` runs it daily, commits the
  result and deploys the site to GitHub Pages.

For a commit whose merge-queue build uploaded no jobs (tree identical to the
already-tested PR head), the PR head's build is used instead.
