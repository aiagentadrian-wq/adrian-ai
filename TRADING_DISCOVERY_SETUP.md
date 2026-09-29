# Discovery and web-evidence preview

This branch builds on Royal Premium and the opt-in email monitor. It adds a bounded research universe to Day Trader chat when asked "What should I invest in today?" The default symbols are AAPL, MSFT, AMD, SHOP, SOFI and PLTR; override with a comma-separated `TRADING_RESEARCH_UNIVERSE` in the local `.env`. These are example research subjects, not picks, rankings or a comprehensive market scanner. Up to eight candidates may use substantial market/news API credits.

Optional Google Programmable Search context uses `GOOGLE_SEARCH_API_KEY` and `GOOGLE_SEARCH_ENGINE_ID` in local `.env`. The owner must obtain and configure these credentials with the provider; availability, billing and quotas depend on their account. Without both, the chat explicitly reports that Google search did not run. Search snippets are not verification or investor consensus. News uses the existing GNews source and market candles use Twelve Data; quotes may be delayed.

The independent reviewer currently performs deterministic completeness checks (missing market evidence, timestamps, news and source failures), not an independent AI adjudication. Do not claim full 14-agent orchestration. The report worker filters unrelated headlines but still needs deeper company/event validation and per-security horizon modeling.

Run ` .\.venv\Scripts\python.exe -m unittest -v test_trading_discovery.py test_trading_monitor.py ` without the leading space. Then run the app and ask Day Trader: "What should I invest in today? Compare the configured universe with timestamps, sources, opposing evidence, risks and possible research horizons." The monitor preview remains ` .\.venv\Scripts\python.exe trading_monitor.py morning --force `. Neither command sends email. Do not enable `--send` or Windows Task Scheduler until Adrian separately approves. No broker orders are available.

Review the candidate reports and API usage before merging. This branch is a draft and does not activate Google credentials, live scheduling or email delivery.
