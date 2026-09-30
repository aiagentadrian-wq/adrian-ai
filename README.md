# ADRIAN.AI — Professional Dashboard and Learned Paper Trading

A private local dashboard coordinating Manager, Day Trader, Swing Trader, Job Finder and Writer. This cumulative release contains the complete simplified site, ATS résumé workflows, shared memory, measured API status, the TradingView course library, broker-backed paper trading and unattended machine-learning workers.

**All broker execution is Alpaca paper trading. No real-money trading endpoint exists.** Models can choose NO TRADE for the entire experiment. Profit is not guaranteed.

## Complete capabilities

Read [FEATURES.md](FEATURES.md) for every agent, page and workflow.

| Area | Included |
| --- | --- |
| Overview / Manager | Agent responsibilities, actual work state, specialist coordination, web research and shared preferences. |
| Trading Division | Market Terminal, compact candidate comparison, Ask Day Trader, SEC directory and actual paper portfolio. |
| Learned Swing Trader | yfinance OHLCV, 68 causal statistical features, learned BUY/HOLD/EXIT forecasts, official alpaca-py orders and scheduled monitoring. |
| Paper experiment | Separate trained intraday model, chronological evaluation, model versions, guarded automatic paper orders and settled outcome journal. |
| Strategy lab | Optional historical baseline/candidate comparisons, cost stress and version improvement data. |
| Job Finder | Discovery, verification queue, ATS packages, résumé vault, application progress and configured email sender. |
| Writer Studio | Assignment-aware drafts, authentic voice context, editable persistent saves and download. |
| Reports & Email | Briefing, activity and broker-backed daily Manager/swing reports. |
| API Center / Settings | Measured access/health, encrypted connection settings, writing samples, reviewable memory, security and logout. |

## Learned swing framework

`autonomous_swing.py` is a complete modular headless daily script. It fetches completed historical OHLCV using yfinance, generates rolling features over 2–60 sessions, trains multi-output random forests for 1/2/3/5/10/20-session returns and derives entry/hold/exit decisions from forecasts, validation error and assumed costs. It has no fixed RSI/SMA buy trigger. Labels are purged across chronological split boundaries; candidate selection uses validation, followed by separate later-data replay and a frozen-candidate deployment refit.

Model versions retain tests, feature importance, forecasts and before/after comparisons. Reused historical tests are labelled. Yahoo-adjusted history can be revised after corporate actions; causal features do not remove this data limitation. Historical diagnostics, simulation profits and actual broker fills are reported separately.

`TradingClient(paper=True)` is invariant. Entries use SDK `MarketOrderRequest` with notional allocation; owned exits use `close_position`. Durable claims, deterministic entry IDs, fill/partial-fill reconciliation and unknown-submission blocking prevent blind retry. Failed model eligibility or stale/missing evidence blocks entries.

The authorized experiment uses 0.25% risk per trade, 1% daily / 2% experiment loss checks, at most three positions and no leverage. For the learned swing policy, the **entire position notional** is capped at 0.25% equity—about $250 per symbol on a $100,000 paper account—because it does not assume a fixed protective-stop distance. The original seven-day deadline is shared with the intraday worker and preserved across restarts. Stock execution is regular-hours only; 24/7 crypto is not implemented.

The app runs the learned policy ten minutes after exchange open and monitors every 30 seconds. Swing emails occur at open, session midpoint and five minutes after close, with early-close/holiday awareness; Manager daily reporting includes learned policy state. Workers share account-entry locking. Run only one account-entry installation/state.

See [HEADLESS_SWING.md](HEADLESS_SWING.md), [SWING_TRADING.md](SWING_TRADING.md) and [PAPER_TRADING.md](PAPER_TRADING.md).

## Installation

Use Python 3.12 or newer. Bind to localhost; keep passwords, databases and résumé records private.

For an existing configured app, stop its server and run the source-only upgrade from a downloaded release folder:

```powershell
python install_dashboard_upgrade.py --target "C:\path\to\existing\adrian-command-center"
```

The allowlisted installer backs up source/database and preserves `.env`, private records and encryption keys. In the existing app environment install `requirements.txt` and restart. A fresh installation:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe generate_secrets.py
.\.venv\Scripts\python.exe start_server.py
```

Sign in and configure your AI provider in API Center. The owner's existing connected flagship model was smoke-tested; fresh installs require their own provider/model access. Configure Alpaca **paper** keys and optional Gmail/SMTP settings in the private connection controls. Standalone swing execution instead reads `APCA_API_KEY_ID` and `APCA_API_SECRET_KEY` with `os.getenv`; never put real keys in source or GitHub.

## Unattended operation

`install_headless_task.ps1 -PythonPath <absolute pythonw.exe path>` registers the local server at Windows sign-in and 09:20 daily, as the current limited user. Optional `-DependencyPath` supports a prepared library directory. The installer is explicit; merely downloading the repository does not install tasks. The app's calendar determines market runs and email times. `headless_swing_cron.txt` is a standalone daily scheduling example.

The PC must remain on, awake, signed in and connected for this local setup. API or broker failures are recorded; acceptance is not a fill, and SMTP acceptance is not proof of inbox delivery. Software monitoring cannot guarantee an exit during an outage or gap.

## AI, writing and memory

OpenAI Responses/tool support and configured alternate providers are retained. Manager coordination invokes actual registered tools; it does not grant every capability of ChatGPT. Say “Remember that…” to save relevant preferences; stored context can be reviewed or deleted in Settings. This retrieval does not retrain the provider's language model. The trading forests are genuine separately trained ML models.

Writer uses genuine samples, corrections and assignment requirements. No AI-detector pass rate is guaranteed. Job packages preserve supplied facts and require review; application progress is user-recorded, not automatic employer submission. API Center distinguishes configured, verified, stale, limited, denied and unreachable status from actual requests, including yfinance historical access. Credit balances are not guessed.

## Verification

```text
python -m unittest test_trading_education test_trading_upgrade test_paper_trading test_trading_guard test_dashboard_v2 test_trading_monitor test_swing_trading test_trading_ml test_paper_experiment test_autonomous_swing
```

The cumulative suite exercises causal features, purged labels, real model fitting, official SDK request construction, paper-only bounds, no duplicate submissions, partial-fill ownership, loss/deadline controls, authentication and the existing dashboard/job/writing workflows. Live verification records are deployment-specific; tests do not establish future profit.

Read [RELEASE_NOTES.md](RELEASE_NOTES.md) for this release's verification and limitations. `.env.example` contains placeholders only. Never commit credentials, private models/databases, résumés, logs or local screenshots.
