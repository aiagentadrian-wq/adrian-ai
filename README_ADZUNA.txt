ADRIAN.AI — ADZUNA CANADA DISCOVERY

WHAT THIS FIX DOES
Searches the official Adzuna Canada API directly on each existing 15-minute radar and 8 AM / 5 PM run, using your private .env credentials. Queries Durham Region for six entry-level job categories, sorted by newest, last 7 days. Saves real individual Adzuna listing redirect URLs, deduplicates against existing database, and sends eligible/review jobs through existing email pipeline. Missing hours or unconfirmed hourly pay go to the NEEDS VERIFICATION section. Adzuna salary predictions are NEVER represented as employer-confirmed pay.

Indeed is NOT integrated: no public unrestricted Indeed job search API or partner credentials were supplied. No scraping or fake Indeed results.

INSTALL (in your actual app PowerShell; stop app and temporarily disable AM/PM/radar tasks):
.\.venv\Scripts\python.exe "FULL_PATH_TO_EXTRACTED\install_adzuna.py"
If STOP compatibility mismatch, don't force.
Check your own .env contains ADZUNA_APP_ID and ADZUNA_APP_KEY; do not send them to anyone.
Run: .\.venv\Scripts\python.exe job_v7_test.py
Run: .\.venv\Scripts\python.exe job_v7_radar.py
If newly found postings exist, this sends a REAL email.
Then run: .\.venv\Scripts\python.exe job_v7_schedule.py
This sends one real scheduled briefing. Re-enable your existing tasks; don't reinstall tasks.

LIMITATIONS
No actual API request or inbox delivery was possible in the offline build environment because your private credentials stay on your PC. If Adzuna reports HTTP 401/403, check your credentials and API access. A source error is reported rather than falsely saying zero jobs.
The existing app generates tailored resumes through its Application Desk after review. This patch does not automate resume generation or attach unreviewed drafts; it fixes real job discovery.
