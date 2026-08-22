# M15 exit-only dispatch

- Market-data acceptance and deployment gates control new entries, not protective exits.
- When an entry gate is closed, the realtime router may continue producing audit-only entry candidates, but only position-manager exit signals are passed to the SDK execution client.
- The same persistent paper trade context serves exits while entry submission remains disabled. This does not enable account-wide liquidation or synthetic orders.
- Realtime boundary, paper-account and account-state checks still apply to exits; local simulation remains isolated.
