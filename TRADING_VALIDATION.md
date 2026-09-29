# Trading evidence and paper validation update

- Intraday timestamps requested explicitly in UTC; daily timestamps remain exchange dates.
- Rejects nonfinite/nonpositive prices, inconsistent OHLC ranges, invalid volume, duplicate/out-of-order bars and future timestamps.
- Excludes still-forming intraday bars and today's daily bar conservatively. Reports age and quality; recent data is not proof of live entitlement.
- Purges training examples whose future labels could reach the model holdout boundary.
- Adds a fixed 20-bar breakout paper replay: completed-close signal, next-open entry, ATR stop, 2R target, five-bar timeout and pessimistic stop-first handling when stop and target both touch.
- Chronological periods, buy-and-hold comparison and 10/40/100 basis-point round-trip cost scenarios. Returns describe fully invested individual positions, not account-equity forecasts or a validated profitable strategy.
- Paper size calculator caps per-position risk at 1%, considers a default 2% daily loss limit and existing exposure, and permits no leverage. Inputs must share a currency; gaps can exceed planned stop losses.
- Accessible inside Trading Division's advanced tools. Validation records are stored locally.
- The job-email subprocess now inherits the server's dependency paths. This fixes managed-runtime installations where the site can import FastAPI but a new worker process cannot.
- Ten additional guard/replay tests cover bad/stale/future data, incomplete candles, risk caps, causal entry timing, future independence, costs and ambiguous stop/target handling.

No live orders, guaranteed performance, automatic strategy promotion or new email sends are enabled by this update.

## Verification on 2026-09-29

27 automated tests passed: 10 new guard/replay tests, 9 prior trading tests and 8 dashboard tests. JavaScript syntax check passed. A child process successfully imported FastAPI, the application and job radar with inherited dependency paths; no discovery or email was executed for that preflight.

One fixed strategy was evaluated on provider-returned MSFT history. These are limited, illustrative historical experiments, not proof of profitable trading:

| Sample | Completed bars | Trades | Return at 40 bps round-trip cost | Buy-and-hold comparison |
| --- | ---: | ---: | ---: | ---: |
| Daily | 499 | 17 | -6.45% | +16.77% |
| 15-minute | 500 | 13 | -4.76% | +0.77% |

The strategy lost money in both samples; higher cost scenarios were worse. It remains experimental and is not promoted to live trading. The intraday request was checked after the regular trading session; old session bars correctly did not qualify as recent live evidence. Today's forming/unverified daily candle was conservatively excluded. Exact provider data, adjustments and executable prices have not been independently verified.
