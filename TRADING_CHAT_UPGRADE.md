# Trading chat and ATS resume upgrade

Trading chat uses the configured AI provider, saved conversation history and current tool results. Broad daily questions compare the watchlist plus a configurable universe (default SPY, QQQ, NVDA, AMD, MSFT, AAPL), capped at eight candidates. This is a limited research screen, not a claim to find the entire market's best trade. The screen ranks long-bias trend, daily change and relative volume after a liquidity check. News is fetched for the top two and 15-minute candles for the leader. API credit limits may leave checks incomplete. The answer must wait for verified quote freshness before calling an entry live. No broker orders are connected.

The site renders short chat paragraphs, headings, emphasis and source links safely. A conversational chat is available inside Trading Division. Technical report JSON is folded below a readable summary. All model calls receive concise communication instructions; this does not change your configured model or grant unimplemented tools.

The default resume PDF is now single-column with embedded fonts, conventional headings and readable extraction order. It copies factual experience and education from the saved resume and targets the saved employer/title; it does not claim a validated ATS score. The previous visual layout remains available through make_original_pdf. The Application Desk has SEND ATS TEST EMAIL. This sends one saved-posting resume to REPORT_TO, without changing emailed flags or submitting applications. Current posting availability is not checked by this test.

## Install all steps (Windows PowerShell)

1. Stop the running server with Ctrl+C.
2. Download this branch's ZIP from GitHub and extract it into a separate folder.
3. Open PowerShell in the extracted folder containing install_trading_upgrade.py. Run the following, adjusting the target only if your installation moved:

```powershell
$AdrianTarget = 'C:\Users\Aj123\Downloads\adrian-command-center-v1-1\adrian-command-center'
& "$AdrianTarget\.venv\Scripts\python.exe" .\install_trading_upgrade.py "$AdrianTarget"
Set-Location "$AdrianTarget"
& .\.venv\Scripts\python.exe -m pip install -r requirements.txt
& .\.venv\Scripts\python.exe -m unittest test_trading_upgrade -v
& .\.venv\Scripts\python.exe -m uvicorn app:app --host 127.0.0.1 --port 8000
```

4. Reload the site with Ctrl+F5. In Trading Division, click COMPARE TODAY'S CANDIDATES, then ask “Why that one?” Confirm the response is short and formatting is rendered.
5. In Application Desk, click SEND ATS TEST EMAIL. Confirm SMTP status, check your inbox and review Adrian_ATS_resume_test.pdf. A saved resume, saved real posting and working SMTP configuration are required.

Optional .env setting: `TRADING_UNIVERSE=SPY,QQQ,NVDA,AMD,MSFT,AAPL`. Set your own supported symbols; watchlist symbols are included first. Keep credentials in the local .env. Do not upload it to GitHub.

## Validation performed

Python compilation; four tests exercising comparison selection, non-Apple ranking, failed sources, no-candidate behavior, PDF extraction order and owner-only email attachment construction without job-flag writes. PDF visually rendered and checked. JavaScript syntax and DOM renderer logic checked for formatting and unsafe HTML/URLs. Market/news/SMTP boundaries were mocked; missing server dependencies were stubbed in this sandbox only. No live model/feed/SMTP end-to-end check or full browser layout check was available. Actual email has not been sent from this environment.
