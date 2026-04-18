# Shadow Mode Runbook

## 1. Purpose

`M8 shadow/paper baseline` uses `shadow / paper` validation to prove the existing research pipeline can consume:

- user-exported local historical CSV/JSON
- local recorded realtime snapshots
- local public-data snapshots

without crossing into real broker, real account, or live execution.

## 2. Hard Boundaries

- output stays `paper / simulated`
- no real order submission
- no real broker SDK
- no account connection
- no paid API prerequisite
- browser automation, if ever used, remains read-only and outside production execution

## 3. Accepted Inputs

- curated sample manifests under `/home/hgl/projects/Price-Action-Trader/tests/test_data/real_history_small/`
- local real-history manifests under `data/real_history/` or `local_data/real_history/`
- local recorded realtime manifests under `data/realtime_recordings/` or `local_data/realtime_recordings/`

Every dataset must provide `dataset.manifest.json`.

## 4. Basic Commands

List discoverable local manifests:

```bash
python /home/hgl/projects/Price-Action-Trader/scripts/run_shadow_session.py --list-manifests
```

Run the bundled sample fixture in `shadow` mode:

```bash
python /home/hgl/projects/Price-Action-Trader/scripts/run_shadow_session.py --sample-manifest --mode shadow
```

Run a user-provided local manifest in `paper` mode and write a local JSON report:

```bash
python /home/hgl/projects/Price-Action-Trader/scripts/run_shadow_session.py \
  --manifest /abs/path/to/dataset.manifest.json \
  --mode paper \
  --report-output /abs/path/to/report.json
```

## 5. Expected Outcomes

- If no manifest is provided, the runner must return `status=deferred`.
- If the manifest is invalid, points to missing files, or is not approved for the repo's `m8d_shadow_paper` purpose tag, the runner must fail fast without pretending success.
- If the input is valid, the runner may produce:
  - signals
  - backtest summaries
  - simulated risk/execution outcomes
  - review traceability

This still does **not** count as real-money or live validation.

## 6. Report Minimums

Every local shadow report should preserve:

- dataset metadata
- session metadata
- KB refs
- PA explanation
- strategy `risk_notes`
- news traceability
- execution/review evidence refs
- explicit statement that the report is not a profitability proof

## 7. Deferred Cases

Deferred is the correct outcome when:

- no approved local dataset manifest exists
- real-history files have not been supplied yet
- recorded realtime snapshots are unavailable
- the manifest is incomplete or points to missing files

Deferred is not a failure of honesty. It is the required behavior when the environment lacks approved local inputs.
