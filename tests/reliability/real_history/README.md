# Local Real History Placeholder

Use this directory only for local, approved manifests and files when exercising M8D against user-exported real history.

Rules:

- keep the runner in `shadow / paper`
- do not store real broker credentials
- do not claim completion if no approved local manifest is present
- prefer local manifests plus local CSV/JSON files

Suggested local layout:

- `tests/reliability/real_history/<dataset_slug>/dataset.manifest.json`
- `tests/reliability/real_history/<dataset_slug>/ohlcv/*.csv`
- `tests/reliability/real_history/<dataset_slug>/news/*.json`

If large datasets should stay out of git, place them under `local_data/real_history/` and keep only the runbook and manifest convention in the repo.
