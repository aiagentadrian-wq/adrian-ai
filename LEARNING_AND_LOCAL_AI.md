# Evidence-based paper learning and local AI

The learned swing worker now permits no-trade days. It records immutable candidate predictions and evaluates them only with bars after the recording date. Symbols with tied leading scores are skipped. Entry horizons are limited to five sessions and the remaining original experiment window.

## Two tracks

Experimental entries require a distinct positive raw forecast after a 40-basis-point round-trip cost allowance. They may still have a negative uncertainty-adjusted estimate. Each is limited to $25 notional, a 2% planned app-managed stop and a $100 shared open-capital-plus-realized-loss envelope. This is not a forced daily order quota.

Performance entries require positive uncertainty-adjusted forecasts and forward promotion. Promotion requires 30 qualifying forward observations over 10 dates and two trend regimes, positive historical validation/test results, and positive lower estimates of daily net return and excess return over SPY. Candidate and incumbent forecast error are compared on matched observations. These are conservative evaluation rules, not a guarantee of profitability or a formal statistically independent proof.

All account-wide limits remain: cash only, three positions, 0.25% full-notional allocation cap, 1% daily and 2% experiment loss thresholds, original deadline. Performance trades use a 3% planned stop. Every new entry records its hypothesis, forecast, features, track, stop, target, planned loss, full capital risk and calendar deadline before submission. Quotes must pass the existing freshness/spread checks. Stops and time exits are app-managed, not broker-held guarantees; gaps, downtime and latency can exceed planned losses.

Legacy trades are separately labelled and given a 2% app-managed stop/target plus their original deadline. This is a migration rule, not an invented original entry plan. Model invalidation can exit them earlier.

## Learning and scorecard

The scorecard separates closed estimated net P/L, average wins/losses, win rate and observed position drawdowns for experimental, performance and legacy tracks. It also reports shadow forecast error, direction accuracy, SPY comparison, unlabelled predictions and promotion status. Costs reserve 20 bps each side for fees/spreads/slippage; these are assumptions rather than actual fee receipts. Shadow predictions start at the next daily open after recording, so there is no retrospective fill at an already-passed open. Forecast observations overlap and are not independent trades.

Once at least 30 fully closed feature-bearing trades over 10 dates exist, a Ridge residual model learns from actual gross outcomes and entry features/holding horizons. Whole-date chronological splits purge trades that close across boundaries. Hyperparameters are selected using validation; later outcomes compare correction MAE against the uncorrected baseline. An improved correction is frozen and records new forward shadow predictions. It can influence future forecasts only after separate matched forward testing meets the minimum evidence, error improvement and net/benchmark requirements. No samples, improvement or profit are fabricated. Reused historical tests remain labelled. The default forest is frozen for forward evaluation; manual training creates a new candidate rather than silently claiming yesterday's tests are unseen.

## Local AI

ADRIAN supports only the explicit loopback Ollama endpoint `http://127.0.0.1:11434/v1`; arbitrary local network provider URLs remain blocked. The native Ollama chat adapter supports tools, disables thinking for short routine replies, limits context/output and never silently falls back to a paid provider. The local AI explains evidence and uses existing authorized app tools; it does not receive unrestricted desktop or shell access.

The tested setup is Qwen3 8B Q4_K_M on the owner's 16 GB RX 9060 XT, Ollama 0.34.4, using Vulkan. The default ROCm runner failed; the Vulkan runner was verified with GPU-resident model memory. `start_local_ai.ps1` selects Vulkan device 0 on this tested machine. Other machines must verify the appropriate GPU index. The local runtime must be running for chat, while the paper engine operates independently. No restart/reboot survival is claimed until actually tested; the startup task is registered for logon.

Official references: https://docs.ollama.com/windows , https://docs.ollama.com/gpu , https://ollama.com/library/qwen3:8b .


Deployment verification: 128 regression tests passed before final report/UI wiring. Local Qwen3 generation and GPU-resident memory were verified. The Windows logon task ran successfully with result 0. Actual local chat routing was tested; trading-status answers now use deterministic recorded facts after an unconstrained local explanation confused some rules. Planned-exit backtests failed the benchmark comparison, so no performance strategy is promoted. The original three positions were closed by model invalidation and recorded as legacy outcomes; no new experimental entry was forced. The one-week deadline has not been extended, and ten-date promotion criteria cannot be completed within a single week.
