# Learned, unattended swing policy

`autonomous_swing.py` is a complete modular daily entry point. It reads optional paper credentials with `os.getenv`, fetches historical OHLCV using yfinance, creates 68 causal rolling statistical features, trains supervised multi-output random forests, evaluates learned BUY/HOLD/EXIT decisions, and executes notional market buys / `close_position` through `alpaca-py` with `paper=True`. It has no interactive input and returns a nonzero exit code for errors. State, model versions, forecasts and reconciled outcomes persist in SQLite; overlapping jobs use a file lock. Private model/order files must not be committed.

## Learning and validation

The model estimates future gross returns over 1, 2, 3, 5, 10 and 20 sessions. Input statistics include rolling momentum, return mean/volatility, downside movement, relative price/volume, daily range and gaps. These are inputs for learning, not hardcoded RSI/SMA entry rules. Candidate forests are selected on chronological validation error. Training labels must end before validation starts, and validation labels must end before later testing starts. Learned decisions subtract the validation-error allowance and assumed costs; this allowance is not a calibrated confidence interval. Deployment refits the frozen candidate on matured labels after evaluation. Repeated training flags reused historical tests and reports before/after comparisons.

Later-data replay enters/exits at the following session open, models costs, reports mark-to-market drawdown and segment-end closure. Current tickers have selection/survivorship bias. Adjusted Yahoo prices can be revised after corporate actions: strictly causal features and purged splits do not turn free adjusted data into an archival point-in-time database. Backtests and forecasts cannot guarantee profitability. Failed later-period checks block new entries.

## SDK execution and conservative risk

`TradingClient(..., paper=True)` is fixed in code. Regular market sessions only; notional stock buys use `MarketOrderRequest` with DAY duration. The model chooses whether to buy, hold or exit; it does not change account risk limits. Each new position's entire notional is capped at 0.25% of equity, so a complete loss of an unlevered long stock remains within that capital-risk budget. This is a small experimental allocation: about $250 per symbol on a $100,000 paper account, at most three positions including other account holdings. The script checks cash reserves, full-position capital risk, 1% daily and 2% experiment headroom, asset eligibility, fresh IEX bid/ask and a 0.3% spread bound. It never uses margin buying power.

SDK acceptance is not a fill. Entry intentions have deterministic source-session client IDs persisted before submission; uncertain orders block new entries and are reconciled without blind retry. `close_position` lacks a custom client-ID parameter, so unknown closes deliberately require position/order reconciliation and are never blindly repeated. Only owned quantities can be closed; extra manual shares block automated full closure. Models learn from matured price outcomes; actual broker fills are separately journalled and evaluated. No claim that one winning week proves an edge.

## Existing ADRIAN installation

The app bridge uses existing encrypted Alpaca settings in memory. No API key needs to be copied into source or GitHub. Trading Division → Learned swing bot shows models, tests, predictions and orders. The shared, explicitly authorized seven-day paper experiment supplies its start equity and deadline. The learned swing job runs at 09:40 Toronto on actual trading sessions; order/risk monitoring runs every 30 seconds. Swing and Manager reports include learned work. The older fixed-rule lab remains a comparison tool and is not the learned policy's signal engine.

Install dependencies with `python -m pip install -r requirements.txt`. To install the Windows background server task, run `install_headless_task.ps1` with `-PythonPath` pointing to the environment's `pythonw.exe`; an optional `-DependencyPath` supports an already prepared dependency folder. The task starts at sign-in and 09:20 daily; duplicate running servers are skipped. It runs as the current signed-in user, without storing a Windows password or exposing the server beyond localhost. A PC that is off, asleep, offline or logged out cannot reliably deliver updates or software exits. For continual uptime, use an appropriately secured always-on host.

## Standalone scheduling

Privately set `APCA_API_KEY_ID`, `APCA_API_SECRET_KEY`, `SWING_PAPER_ENABLED=1`, `SWING_SYMBOLS`, `SWING_STATE_PATH` and an explicit `SWING_DEADLINE` in the task's environment. Credentials are read with `os.getenv`; they are never logged. Run:

```text
python autonomous_swing.py --state /absolute/private/path/autonomous_swing.db
python autonomous_swing.py --train-only --state /absolute/private/path/autonomous_swing.db
python autonomous_swing.py --status --state /absolute/private/path/autonomous_swing.db
```

`headless_swing_cron.txt` provides a daily cron example. Do not run a separate standalone account-entry scheduler alongside the integrated app worker on another state database. The integrated app provides the more frequent monitoring and open/midday/close emails requested by the owner. No human approval is required for each authorized paper order, but unresolved broker/API failures are surfaced rather than bypassed.

## Daily-testing follow-up

The minimum five historical trades gate has been removed. Separately authorized daily paper exploration can test a relative learned choice even when its recommendation is WAIT, while all hard risk/account/fresh-data limits remain. This is forward simulated learning, not proof of profitability or a guarantee of a fill every day. The learned bot supports 12 configured symbols; the lab defaults to that full comparison list. Job Finder now has an integrated daily email worker and sends an honest no-new-matches/source-failure update when appropriate, instead of silently skipping email.


Broker-time freshness checks use the official paper SDK clock response, verified against its HTTPS Date header, cache age and request latency. Monotonic elapsed time preserves the 90-second quote limit even when the PC clock is slightly ahead. Cached responses, disagreeing timestamps, requests over five seconds and clock differences over five minutes fail closed. The follow-up safety suite passes 109 tests. Actual paper submission and subsequent broker fill reconciliation were verified.


Continuous paper opportunities: the daily one-entry cap has been removed. During the scheduled market window, the worker reevaluates every five minutes even after a successful entry. It can submit one new candidate per evaluation, up to the shared three-position cap, subject to existing cash, loss, freshness and spread checks. Unresolved orders block new entries; the same symbol and daily dataset cannot generate duplicate purchases. The learned forecasts still update from completed daily bars, not every five minutes.


## Evidence-based learning and local AI update

Supersedes forced daily exploration: no-trade days, distinct post-cost candidates, $25 experimental entries in a $100 budget, separate performance promotion, immutable forward predictions, outcome-based residual learning, planned app-managed exits and an honest scorecard. Local Qwen3 8B via Ollama replaces paid chat calls in the configured installation. See [LEARNING_AND_LOCAL_AI.md](LEARNING_AND_LOCAL_AI.md) for exact gates, limits, setup and limitations.
