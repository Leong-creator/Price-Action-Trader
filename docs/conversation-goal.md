# Conversation Goal

## Purpose

Codex client slash commands are outside this repository. If `/goal` is not available in a conversation, use this repo-local fallback to make the goal explicit and auditable.

## Set The Current Goal

```bash
python scripts/set_conversation_goal.py "只读检查 M12.47 守护器状态，不运行 M12.37"
```

The command writes:

- `reports/conversation_goal/current_goal.json`
- `reports/conversation_goal/current_goal.md`

## Priority

The conversation goal guides the current agent turn, but it does not override:

- `AGENTS.md`
- `plans/active-plan.md`
- `docs/implement.md`
- `docs/status.md`
- closer `AGENTS.md` or `AGENTS.override.md`

If the stored goal conflicts with project safety rules, the safety rules win.

## Trading Boundary

Setting a goal cannot authorize broker connections, real orders, live execution, real-money actions, fabricated data, fabricated trades, or fabricated approvals.
