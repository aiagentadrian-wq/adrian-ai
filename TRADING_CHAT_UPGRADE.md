# ADRIAN.AI update — installed and verified

Installed on September 29, 2026. Trading questions compare your saved watchlist plus SPY, QQQ, NVDA, AMD, MSFT and AAPL (up to eight symbols). Set TRADING_UNIVERSE in your local .env to change the comparison list. Apple has no privileged ranking; explicit ticker requests remain supported.

Daily decisions are assembled directly from market evidence. They include candidate scores, daily momentum and relative volume, returned news or a missing-news notice, a conditional breakout reference, illustrative stop and 1R/2R targets, invalidation and skip rules. Unknown quote freshness always blocks a live entry. News is checked for the top two candidates; it is reported separately and does not contribute to the technical score. This is a limited watch-list screen, not a whole-market search or a validated trading strategy.

The Day Trader retains saved conversation context. Site answers render paragraphs, emphasis and source links safely. The existing Writer workspace, voice-review controls, company directory, job dashboard and branding are preserved. Trading Division now has COMPARE TODAY'S CANDIDATES. Broad comparisons do not inherit the currently selected chart ticker.

The ATS resume uses one column, embedded fonts, standard headings and source experience/education. SEND ATS TEST EMAIL sends to your configured REPORT_TO. If there is no saved posting, it sends a general resume without inventing an employer. It does not apply for jobs or change emailed flags.

## Verified locally

- Nine regression tests passed; source compilation and JavaScript syntax passed.
- Configured AI provider answered live. Six candidate market requests succeeded; an NVDA news request was unavailable and remained visible.
- MSFT outranked AAPL in the live limited comparison. Decision: no suitable trade today because freshness and entry confirmation were unverified.
- Browser comparison button and formatted answer checked; company directory loaded.
- Real saved resume generated as one page; PDF rendered and text extraction checked.
- Trading briefing and ATS test email were both accepted by SMTP. Inbox delivery has not been independently confirmed.
- Configuration and database were preserved during installation; source and database backups are in the existing installation's upgrade-backups folder.

## Use the installed app

Open http://127.0.0.1:8000. In Trading Division, use COMPARE TODAY'S CANDIDATES. To email a fresh briefing, ask Day Trader to compare today's stocks and email you the result. Application Desk has SEND ATS TEST EMAIL. Avoid repeating the email test unless you want another copy.

The server was started with Codex's bundled Python and an isolated dependency folder because the sandbox blocked launching your existing Python runtime. This does not change your saved credentials or existing .venv. On a normal local PowerShell session you can restart as usual:

```powershell
Set-Location 'C:\Users\Aj123\Downloads\adrian-command-center-v1-1\adrian-command-center'
& .\.venv\Scripts\python.exe -m pip install -r requirements.txt
& .\.venv\Scripts\python.exe -m unittest test_trading_upgrade test_trading_monitor -v
& .\.venv\Scripts\python.exe -m uvicorn app:app --host 127.0.0.1 --port 8000
```

Stop the existing server before restarting. No new recurring schedule was enabled. Existing morning/next-day monitor runs now use the comparison briefing when invoked; material alert limits remain in place.

## Reinstall from GitHub

Download the improve-trading-chat-ats branch ZIP, extract to a separate folder, stop the server, and run install_trading_upgrade.py with your installation folder as its target. Install requirements and restart using the commands above. Keep .env and database files private. Do not run generate_secrets.py for an upgrade.

