# ADRIAN.AI — complete feature list

This describes the cumulative professional dashboard release. Connection-dependent features require configured credentials, accessible services and a running local server. All trading execution is simulated Alpaca paper trading; live-money execution is not implemented.

## Overview and Manager

- Agent-focused overview: responsibilities, latest work and actual working/idle/disabled state.
- Manager coordinates registered Day Trader, Swing Trader, Job Finder and Writer specialists using the configured AI provider.
- Connected OpenAI Responses/tool calling and hosted web research; alternate configured provider support.
- Agent-specific conversation history, shared relevant preferences, explicit “Remember that…” storage, review/edit/disable/delete controls.
- Stored memories are retrieved context. The provider language model is not retrained. Trading models are separately trained statistical models.
- Command briefing, recorded activity, shared specialist outcomes and daily broker-backed trading reports.

## Trading Division

- Market Terminal, compact daily comparison and formatted Ask Day Trader conversation.
- Broader configured stock universe; Apple is selected only when its supplied evidence earns the ranking.
- Timestamped prices, historical momentum/volume and available news; conditional entry, invalidation, stops/targets and NO TRADE when evidence fails.
- Searchable and paginated SEC company directory covering returned US SEC entries.
- Alpaca paper account, cash/equity, actual positions, open/recent orders and order journal.
- Shared Alpaca IEX research data, source/freshness checks and conservative broker execution constraints.
- Versioned 37-page TradingView course knowledge with lesson/page references and official source links, retrieved by Day Trader and Manager.
- Historical Model Lab and guarded chronological replay; results distinguish diagnostics, simulations and actual fills.

## Learned autonomous Swing Trader

- Modular, unattended `autonomous_swing.py`: daily scheduler entry point, environment credentials, error exit codes and overlap lock.
- yfinance completed historical OHLCV; 68 causal statistical features spanning 2–60 sessions.
- Supervised random forests estimate returns over 1, 2, 3, 5, 10 and 20 sessions; learned BUY/HOLD/EXIT decisions subtract error allowance and assumed costs.
- Chronological training, validation-based candidate selection, label-boundary purging and separate later-data replay; no future values in features.
- Refit the frozen model choice on matured labels after evaluation; versioned models, feature importance, validation/test statistics and before/after comparisons.
- Explicit reused-test and changing-period labels; no claim that historical improvement proves future profitability.
- Failed eligibility, stale data, missing quotes, account blocks and uncertain submissions prevent new entries.
- Official alpaca-py SDK, fixed `paper=True`, notional DAY market buys and owned-position `close_position` exits.
- Durable order intent before submission, deterministic entry IDs, fill reconciliation, partial-fill ownership and cancellation of entry remainders after three minutes.
- Daily learned run 10 minutes after the exchange open; reconciliation/risk checks every 30 seconds while the app runs.
- Shared original seven-day paper experiment deadline and account loss limits. Maximum three positions including other account holdings; no leverage.
- Entire new swing position notional capped at 0.25% of equity: about $250 on $100,000. This differs from sizing a larger position around a fixed stop.
- 1% daily / 2% experiment loss checks, cash/headroom checks, fresh bid/ask and spread checks. These checks cannot guarantee fills or prevent every loss.
- Learned model results, decisions, errors and paper-order evidence included in open/midday/close swing emails and Manager reports.

## Intraday paper experiment and approval mode

- Separate supervised intraday model, matured-price labels, purged evaluation, model versions and eligibility checks.
- Five-minute entry scans and 30-second monitoring, bounded risk, maximum three positions, no leverage, original one-week deadline.
- Paper order reconciliation, bracket protection when applicable, session/time exits and uncertain-submission blocking.
- Actual settled outcomes are journalled; an additional outcome filter requires sufficient evidence before use.
- Separate email-approval workflow: expiring, authenticated YES replies in the exact Gmail proposal thread; paper limit/bracket orders after checks.
- The automatic experiment uses previously authorized paper orders without per-order YES. Approval mode and automatic mode are explicitly distinguished.
- No 24/7 crypto or extended-hours stock execution in this release. No profit guarantee or forced trade.

## Swing research and strategy lab

- Multi-session comparison and position review; fresh entry confirmation and overnight/event risk explanations.
- Calendar-aware emails at market open, session midpoint and five minutes after close, including early closes. Missed windows are recorded rather than fabricated.
- Optional fixed-rule lab for comparison: baseline/candidate tests, chronological partitions, cost stress, trade counts, drawdown and before/after results.
- The fixed-rule lab does not control the learned swing model or automatically activate strategies.

## Job Finder and application workspace

- Configured Adzuna, Arbeitnow, Lever, Greenhouse and optional public-feed discovery, eligibility filters and deduplication.
- Saved matches, source links and discovery items requiring verification when pay/hours/fit are unknown.
- Resume vault, job-description-based package preparation and single-column ATS PDF output preserving supplied facts.
- Saved/preparing/applied/interview/offer/closed application stages with user-recorded progress.
- Test résumé email and reviewed-package sending through the local configured sender; SMTP acceptance is distinct from inbox delivery.
- Actual scheduled-task information or a clear unavailable/not-scheduled state; manual discovery refresh with quota protection.
- No automatic employer application submission or invented résumé claims.

## Writer Studio

- Assignment constraints, editable drafts, persistent saves, word count and text download.
- Genuine voice samples and saved corrections in Settings; relevant voice context and review of formulaic phrasing.
- Factual/source requirements and missing-source flags. No guaranteed AI-detector score or pass rate.

## Reports, connections and Settings

- Reports & Email houses briefing and activity; security/logout and advanced controls live in Settings.
- API Center covers OpenAI/OpenRouter, Alpaca, Gmail, Yahoo/yfinance, Twelve Data, GNews, FRED, SEC, Bank of Canada, Statistics Canada, job feeds and SMTP.
- Configured/access-verified/stale/limited/denied/unreachable states with actual checked times; credit balances are not guessed.
- Password authentication, CSRF protection, encrypted stored provider/broker secrets and localhost binding.
- Source-only upgrade installer preserving local environment, private records and encryption keys; backup before upgrade.
- Windows background-server installer: sign-in plus daily startup, limited current-user execution, restart settings and duplicate-server protection.
- Standalone daily cron example; use one account-entry scheduler/state, not duplicate independently configured workers.
- Private credentials, databases, models, résumé files, logs and local screenshots excluded from the release source.

See README.md, HEADLESS_SWING.md, SWING_TRADING.md and PAPER_TRADING.md for setup, scheduling, risk and service limitations.

## Daily-testing follow-up

The minimum five historical trades gate has been removed. Separately authorized daily paper exploration can test a relative learned choice even when its recommendation is WAIT, while all hard risk/account/fresh-data limits remain. This is forward simulated learning, not proof of profitability or a guarantee of a fill every day. The learned bot supports 12 configured symbols; the lab defaults to that full comparison list. Job Finder now has an integrated daily email worker and sends an honest no-new-matches/source-failure update when appropriate, instead of silently skipping email.


## Evidence-based learning and local AI update

Supersedes forced daily exploration: no-trade days, distinct post-cost candidates, $25 experimental entries in a $100 budget, separate performance promotion, immutable forward predictions, outcome-based residual learning, planned app-managed exits and an honest scorecard. Local Qwen3 8B via Ollama replaces paid chat calls in the configured installation. See [LEARNING_AND_LOCAL_AI.md](LEARNING_AND_LOCAL_AI.md) for exact gates, limits, setup and limitations.
