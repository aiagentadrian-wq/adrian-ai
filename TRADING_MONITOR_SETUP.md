# Trading monitor — opt-in preview

Configuration: America/Toronto; 09:00 morning report; 18:00 next-day preparation; 15-minute checks during regular US equity hours on weekdays; material alerts only; recipient amazingchefadrian@gmail.com. No SMTP email is sent unless the command explicitly includes `--send`. Do not use `--send` before Adrian approves a test email and later approves enabling scheduled delivery.

This is a standalone one-cycle worker, **not** a background service. The application must be running on an awake Windows PC, or the worker must be scheduled on an always-on host. The monitor can run independently of the web server but needs its local files, Python environment, internet and API credentials. It uses up to five saved watchlist symbols; it does not discover or rank new investments. Each check may use market and news API credits. Existing `.env` supplies `TWELVE_DATA_API_KEY`, `GNEWS_API_KEY`, `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `EMAIL_FROM`. Secrets stay local. Monitor observations and delivery state are stored in `trading_monitor.db` locally and must not be committed.

## Preview and test

Run ` .\.venv\Scripts\python.exe -m unittest -v test_trading_monitor.py ` and then ` .\.venv\Scripts\python.exe trading_monitor.py morning --force ` (remove leading space before the executable). The preview prints a report and does **not** send email. Use `monitor` to save observations without email if no qualifying move occurs. An alert is triggered by an absolute daily candle change of at least 5% on a same-date candle, not by a verified causal event; its cause must not be asserted. Alerts have a six-hour per-symbol cooldown and two-per-day cap. Scheduled report delivery is deduplicated per report/date/body; overlapping pending sends are blocked. Failed sends require review before retry to avoid duplicates.

## Scheduling after approval

Use Windows Task Scheduler with working directory set to the project folder and the venv Python executable. Set weekday triggers at 09:00 for `trading_monitor.py morning --send`, 18:00 for `trading_monitor.py next_day --send`, and every 15 minutes during 09:30–16:00 for `trading_monitor.py monitor --send`. **Do not enable these tasks before explicit approval.** The module checks weekday and regular-hours boundaries for monitor mode. Timezone must be America/Toronto on the host. Holidays and early closes are not yet recognized; do not treat it as an exchange calendar. If a scheduled run is missed while the machine sleeps, this module does not backfill it. Monitoring and report delivery are not currently active just because this branch exists.

Research reports describe watchlist evidence and risk, not individualized investment instructions or a validated holding-period forecast. More advanced 14-agent coordination, verified event detection and exchange-calendar integration remain separate work.
