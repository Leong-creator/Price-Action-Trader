# M10 Workspace Audit and Legacy Inventory

## Branch

- current branch: `codex/m10-price-action-strategy-refresh`
- expected branch: `codex/m10-price-action-strategy-refresh`

## Git Status

```text
## codex/m10-price-action-strategy-refresh
 M .gitignore
 M README.md
 M docs/acceptance.md
 M docs/architecture.md
 M docs/decisions.md
 M docs/knowledge-atomization.md
 M docs/knowledge-base-design.md
 M docs/pa-strategy-spec.md
 M docs/requirements.md
 M docs/roadmap.md
 M docs/status.md
 M knowledge/indices/chunk_manifest.jsonl
 M knowledge/indices/knowledge_atoms.jsonl
 M knowledge/indices/knowledge_callable_index.json
 M knowledge/indices/source_manifest.json
 M knowledge/raw/README.md
 M knowledge/raw/brooks/README.md
 M knowledge/schema/chunk-registry-schema.md
 M knowledge/schema/source-registry-schema.md
 M plans/active-plan.md
 M reports/strategy_lab/README.md
 M scripts/kb_atomization_lib.py
 M tests/reliability/test_kb_coverage.py
?? knowledge/raw/brooks/transcribed_v2/
?? knowledge/raw/chatgpt/
?? knowledge/raw/codex_threads/
?? knowledge/wiki/sources/al-brooks-price-action-course-v2-manual-transcript.md
?? knowledge/wiki/sources/chatgpt-bpa-reference-share.md
?? knowledge/wiki/sources/codex-brooks-v2-transcription-thread.md
?? reports/strategy_lab/m10_price_action_strategy_refresh/
?? scripts/generate_m10_strategy_refresh.py
?? scripts/import_brooks_v2_source.py
?? tests/unit/test_m10_backtest_spec_freeze.py
?? tests/unit/test_m10_strategy_refresh.py
```

## Worktrees

```text
worktree /home/hgl/projects/Price-Action-Trader
HEAD b3f13bbcbd5b0a3df9520f8c9c8cea773cd14d7c
branch refs/heads/main

worktree /home/hgl/projects/Price-Action-Trader-analysis-snapshot
HEAD e49049fa8c92a03dea3b9cc5f291fce58440a82e
branch refs/heads/analysis/project-audit-snapshot

worktree /home/hgl/projects/Price-Action-Trader-m10-price-action-strategy-refresh
HEAD b3f13bbcbd5b0a3df9520f8c9c8cea773cd14d7c
branch refs/heads/codex/m10-price-action-strategy-refresh

worktree /home/hgl/projects/Price-Action-Trader-m8d1-artifact-trace-unification
HEAD 10ae38a439bb7b53768bc4f9181546b176d5b8f6
branch refs/heads/feature/m8d1-artifact-trace-unification

worktree /home/hgl/projects/Price-Action-Trader-m8d2-curated-promotion-minimal-expansion
HEAD 85aa176f633e30de62adfcf47bdb67c5e874c381
branch refs/heads/feature/m8d2-curated-promotion-minimal-expansion

worktree /home/hgl/projects/Price-Action-Trader-m9-longbridge-history
HEAD d9ef8a73ff8bdb4e08605b13cd64233d95ade6dc
branch refs/heads/feature/m9-longbridge-history-source

worktree /home/hgl/projects/Price-Action-Trader-m9j2-sf001-rescue
HEAD b3f13bbcbd5b0a3df9520f8c9c8cea773cd14d7c
branch refs/heads/feature/m9j2-sf001-rescue-revision-backtest

worktree /home/hgl/projects/Price-Action-Trader-m9j2-sf003-rescue-review
HEAD b3f13bbcbd5b0a3df9520f8c9c8cea773cd14d7c
branch refs/heads/feature/m9j2-sf003-rescue-review

worktree /home/hgl/projects/Price-Action-Trader-m9sf
HEAD d9ef8a73ff8bdb4e08605b13cd64233d95ade6dc
branch refs/heads/feature/m9-strategy-factory-extraction

worktree /home/hgl/projects/Price-Action-Trader-sf002-v03-wt
HEAD b3f13bbcbd5b0a3df9520f8c9c8cea773cd14d7c
branch refs/heads/feature/m9-sf002-v0-4-midday-confirmation
```

## Legacy-Only Inventory

The following paths are registered only for post-extraction comparison. They are forbidden as clean-room extraction inputs.

- `knowledge/wiki/strategy_cards`: exists=True files=14 ids=PA-SC-001, PA-SC-002, PA-SC-003, PA-SC-004, PA-SC-005, PA-SC-006, PA-SC-007, PA-SC-008, PA-SC-009, PA-SC-010
- `reports/strategy_lab/strategy_catalog.json`: exists=True files=1 ids=SF-001, SF-002, SF-003, SF-004, SF-005
- `reports/strategy_lab/cards`: exists=True files=5 ids=SF-001, SF-002, SF-003, SF-004, SF-005
- `reports/strategy_lab/specs`: exists=True files=9 ids=SF-001, SF-002, SF-003, SF-004, SF-005
- `reports/strategy_lab/strategy_triage_matrix.json`: exists=True files=1 ids=SF-001, SF-002, SF-003, SF-004, SF-005
