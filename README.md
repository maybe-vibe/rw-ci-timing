# RisingWave CI step timing

One chart: run time of every Buildkite `pull-request` job for the last 100
commits on `risingwavelabs/risingwave` main, one curve per step.

- `index.html` renders `data.json` (no build step, no dependencies).
- `fetch_data.py` regenerates `data.json` from the GitHub and public Buildkite
  APIs (`python3 fetch_data.py`; set `GITHUB_TOKEN` for a higher rate limit).
- The workflow in `.github/workflows/update.yml` runs it daily, commits the
  result and deploys the site to GitHub Pages.

For a commit whose merge-queue build uploaded no jobs (tree identical to the
already-tested PR head), the PR head's build is used instead.
