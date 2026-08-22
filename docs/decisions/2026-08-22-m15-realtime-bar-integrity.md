# M15 realtime bar integrity

- Production five-minute bars are closed once per boundary as one symbol batch.
- Trade pushes provide OHLCV. Quote pushes only maintain the latest carry-forward price and connection health.
- A subscribed symbol with no trade in a boundary receives a zero-volume flat bar marked `no_trade_carry_forward`; that row cannot open a position.
- A boundary may authorize strategy dispatch only when every configured trading symbol is present, every row has the same close time, and finalization occurs no later than five seconds after the boundary.
- Historical or post-close repairs remain research evidence and never restore order eligibility for a missed realtime boundary.
