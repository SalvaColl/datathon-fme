# Read-only team tools

Keep exactly one existing live starter running. These tools do not start it.

- `python tools/feedback_monitor.py --watch 15 --window 30`: read-only live feedback diagnostics.
- `python tools/local_league.py prepare --sample 10000`: independently cache training, validation and sealed test periods.
- `python tools/local_league.py validation`: compare policies without opening final test.

See [LEAGUE.md](LEAGUE.md) for the policy interface, existing virtualenv commands, freeze/final-test procedure, metrics, uncertainty and limitations. The old `holdout.json` remains legacy evidence and is never silently upgraded.
