# Trading Workspace v2 — local preview

This draft reorganizes the existing Trading Division panels into four clearly described groups: Market Intelligence, Research & Discovery, Model Lab, and Paper Portfolio. It preserves the existing button IDs and API handlers. A sticky Day Trader mini chat uses the existing authenticated chat endpoint and registered agent, not a separate AI service.

The alphabetical selector uses the SEC company_tickers.json directory cached for 24 hours by the local FastAPI server. Set SEC_USER_AGENT in the local .env to an honest app/contact identifier. It is a US SEC directory, not all worldwide listed companies or private startups; trading/listing status is not independently verified. Type to filter by name or symbol. The dropdown shows the first 300 matches for performance; refine the search to find more. Manual ticker entry remains available.

Local review: fetch and switch to feat/trading-workspace-redesign, run the existing unittest suites, start uvicorn, hard-refresh. Verify every original button, responsive/mobile layout, directory loading/fallback, company selection, and mini-chat with Day Trader enabled. No email scheduling, send, brokerage action or merge is included.
