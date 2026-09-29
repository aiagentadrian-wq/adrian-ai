ADRIAN.AI V7 — LIVE JOB RADAR (15-minute polling)

WHAT IT DOES
Every 15 minutes, check existing configured public feeds/ATS endpoints, save new postings, and immediately email newly discovered confirmed or review-needed jobs. Persistent emailed flags prevent repeating them in the 8 AM/5 PM briefings. No emails when there are no new postings. The existing 8 AM and 5 PM summaries remain intact.

CRITICAL LIMITATION
Your last diagnostics showed 0 Greenhouse, 0 Lever, 0 RSS feeds configured. This installer DOES NOT add new employer sources, so it will not magically find Durham jobs. Configure real permitted public source identifiers/feeds in your own .env; otherwise Arbeitnow remains the only general source. Do not enter ordinary search-page URLs as RSS feeds. A job can only appear after a source publishes it and the next check retrieves it. It is NOT instant push. No Indeed/Job Bank scraping.

INSTALL ALL AT ONCE
1. Extract ZIP, stop ADRIAN.AI and temporarily disable the AM/PM Windows tasks.
2. Open PowerShell in your actual app folder.
3. Run: .\.venv\Scripts\python.exe "FULL_PATH_TO_EXTRACTED\install_live_radar.py"
4. Run: .\.venv\Scripts\python.exe job_v7_radar.py
   No email if there are no new matches. If pending jobs exist, sends a REAL email.
5. Run PowerShell AS ADMINISTRATOR, then:
   & "FULL_PATH_TO_EXTRACTED\install_live_radar_task.ps1"
6. In Task Scheduler verify ADRIAN_AI_Live_Job_Radar, and re-enable your existing AM/PM tasks.
7. Keep the existing ADRIAN_AI_Server_At_Boot task. No second server is installed.

TO STOP RADAR: Disable-ScheduledTask -TaskName 'ADRIAN_AI_Live_Job_Radar'
No changes to your .env, database, app.py, Writer Studio, Manager, existing task definitions, or UI.
