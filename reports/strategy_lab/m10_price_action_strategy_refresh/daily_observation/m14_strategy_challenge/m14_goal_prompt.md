# M14 Codex Goal

Goal: Build a reliable strategy challenge and internal paper-trading gate.

Hard constraints:
- No real-money execution, no live broker orders, no fabricated trades or profits.
- Run M12.37/M12.29 + M13 every New York trading day.
- Keep every strategy in append-only daily ledger history.
- Use 10 NY trading days as the default challenge window.
- Evaluate and advance each runtime separately; do not merge 1d and 5m gate decisions by parent strategy.
- Use sizing and repair actions for high-drawdown or low-win-rate profitable runtimes instead of blanket rejection.
- Internal simulated account is the default; broker paper/sim account requires separate approval.
- Losing or zero-signal runtimes must get a concrete repair or pause action, not a generic observation state.
