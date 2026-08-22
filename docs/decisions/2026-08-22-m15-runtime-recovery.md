# M15 runtime recovery

- Connection setup has a 30-second deadline. Reconnect delay follows 5, 15, 30 and 60 seconds, with three automatic attempts before the market-data circuit opens.
- Worker heartbeats prove only that the child process is alive. During the regular session, SPY and QQQ quote pushes independently prove that the market stream is alive.
- An open circuit keeps the parent process and account/exit maintenance alive but disables new entries. It never switches to snapshot polling.
- Runtime identity requires PID, command line, process start ticks, commit, configuration fingerprint and state age. A dead or reused PID invalidates the previous health result.
- A locally issued deployment manifest must match a clean, remote-backed commit and the runtime source/config hashes before a paper entry client is created.
