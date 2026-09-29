# Emerging-company news discovery

When Day Trader receives an open-ended investment research request, it now includes news discovery across small-cap, newly public and microcap themes, alongside the existing bounded established-stock universe. These are **news leads**, not confirmed listed securities. Company names, tickers, market capitalization, trading access and financial condition must be independently verified before a lead becomes a researched public-security candidate. Private startups cannot be assumed purchasable through a normal brokerage.

This implementation uses the existing GNews API key, with dated article URLs and explicit errors. Google Programmable Search remains optional and credential-gated for the established ticker research. News search can be incomplete, stale or quota-limited. No comprehensive IPO calendar, exchange listing verification, market-cap feed, fundamentals or startup database is connected yet. Do not claim otherwise.

Run `.\\.venv\\Scripts\\python.exe -m unittest -v test_emerging_discovery.py test_trading_discovery.py test_trading_monitor.py` locally, then ask Day Trader to compare established symbols and show emerging-company news leads, separating verified listed companies from unverified/private startups. Preview the monitor with `morning --force` only. No email sends or scheduler changes.
