# M14 Codex Goal

Goal: Build a reliable strategy challenge and internal paper-trading gate.

Hard constraints:
- No real-money execution, no live broker orders, no fabricated trades or profits.
- Run M12.37/M12.29 + M13 every New York trading day.
- Keep every strategy in append-only daily ledger history.
- Use 10 NY trading days as the default challenge window.
- Allow early modification/rejection only on circuit breaker conditions.
- Internal simulated account is the default; broker paper/sim account requires separate approval.
- Losing strategies must be frozen, diagnosed, and A/B tested as new variants, not silently overwritten.
