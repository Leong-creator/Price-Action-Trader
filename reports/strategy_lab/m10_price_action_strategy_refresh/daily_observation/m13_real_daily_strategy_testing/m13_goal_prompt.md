# M13 Codex Goal

Goal: Build a real daily strategy testing loop for Price-Action-Trader.

Hard constraints:
- Follow AGENTS.md, plans/active-plan.md, docs/implement.md, docs/status.md.
- Use Simplified Chinese for user-facing updates.
- Do not connect real broker accounts, place real orders, or enable real-money execution.
- Do not fabricate market data, trades, backtest results, paper results, or approvals.
- Every run must distinguish: not_connected, detector_missing, missing_data, zero_signal, signal_generated, open, close, risk_blocked, plugin_ab_attached.

Primary objective:
Every M10/M12 strategy or module must enter an auditable daily test ledger. A strategy is not tested today unless it has a ledger event for the current New York trading date.
