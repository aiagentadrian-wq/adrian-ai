# ADRIAN.AI — Professional Dashboard 2.0

A private, locally hosted assistant dashboard for coordinated research, job applications and authentic writing. This release includes the earlier grounded stock comparison and ATS résumé updates.

## What is included

| Page | What it does |
| --- | --- |
| Overview | Shows the installed agents, their responsibilities, actual working/idle/disabled state, and latest recorded work. |
| Manager | Coordinates registered specialists, retrieves shared preferences and historical results, searches the web through the connected OpenAI account, and reports actual tool outcomes. |
| Trading Division | Market Terminal, searchable/paginated SEC company directory, compact candidate comparison and Ask Day Trader. Advanced research, model training, discovery and paper portfolio tools are collapsed. |
| Job Finder | Saved opportunities, résumé packages, discovery matches needing verification, application progress, job board searches, résumé vault and email actions. Replaces the separate Application Desk navigation. |
| Writer Studio | Assignment instructions, editable draft, voice review, persistent local saves and text download. Samples and corrections live in Settings → Writing voice. |
| Reports & Email | Command briefing, activity records and the existing report sender. |
| API Center | Measured access/response status for AI, market/news/economic/company/job feeds and SMTP. Shows checked times and failures rather than a decorative online indicator. |
| Settings | Agent instructions, writing samples, reviewable memory, security and logout. |

### AI and shared memory

- GPT-6 Astra was verified with the owner's existing OpenAI account during installation. Account access and billing remain provider-controlled. A fresh installation requires its own configured provider and model.
- `ai_adapter.py` uses OpenAI Responses for GPT-5/GPT-6/reasoning models, including function calls and encrypted reasoning continuity; existing older/OpenRouter Chat Completions integrations are retained.
- Manager delegation and a real Writer response were checked end to end. Agent coordination invokes actual registered specialists; it does not create new external capabilities.
- Say **“Remember that …”** in agent chat to save a preference explicitly. Exact duplicates are avoided. Credential-like content is rejected. All agents can use shared memories; current instructions take priority.
- Retrieval prioritizes relevant stored text and recent corrections. Memory is persistent database context, not retraining the language model. Review, disable, edit or delete it in Settings.
- Historical specialist results are shared as historical context, never proof of current facts or newly completed actions.

### Trading

- Compares configured watchlist/universe candidates rather than hard-coding Apple. AAPL appears only if its evidence earns its ranking.
- Compact brief and detailed chat/email share the same grounded decision logic. The brief refreshes when the trading page first opens and caches results for five minutes.
- Describes comparative historical momentum and volume, available news, conditional entry confirmation, illustrative stops/targets, invalidation and reasons to skip.
- Missing, stale, delayed or unverified live evidence produces WAIT/NO TRADE. The current pipeline does not assert a verified live entry or execute broker orders.
- Company directory pages expose every returned SEC entry. This is US SEC coverage, not every public/private company worldwide; directory inclusion does not verify current listing status.
- Model Lab remains available for historical training/backtesting. A saved model is not a guarantee of future returns.

### Jobs, applications and email

- Uses configured Adzuna, Arbeitnow, Lever, Greenhouse and optional public feeds. Strict eligibility filters and deduplication are retained.
- Unconfirmed pay/hours/fit appear as discovery matches needing verification. Open the posting and paste the full description before preparing a package.
- Application stages: saved, preparing, applied, interview, offer, closed. These are **user-recorded progress**, not automatic employer submissions.
- Single-column ATS PDFs preserve supplied facts, readable text and ordering. Review drafts before approval.
- Email test and approved-package actions use the existing local SMTP configuration. SMTP acceptance is distinguished from inbox delivery.
- Next check times come from Windows Task Scheduler. If task access is unavailable or no ADRIAN tasks exist, the app says so. No schedule, next-email time or successful delivery is fabricated; this release does not create new scheduled tasks.
- A manual discovery refresh checks feeds without sending email and limits refresh frequency to protect quota. Existing scheduled mailers retain their deduplication and authorization behavior.

### Writing

Uses genuine samples and saved corrections, prioritizes assignment requirements, preserves facts, flags missing sources and reviews formulaic phrasing. Edits can now be saved to the local database and restored after a refresh. No detector score or detector pass rate is promised.

### Connection status

Configured is separate from verified. HTTP/API failures update status during normal requests; successful checks have timestamps and become stale after 15 minutes. Quota/credit errors, denied access and unreachable services are reported. API credit balances are not guessed. An authentication/model-list check is distinguished from a successful paid model invocation. SMTP checks authenticate without sending mail.

## Install or upgrade

Use Python 3.12 or newer. Keep the app bound to localhost unless you deliberately configure authenticated private remote access.

### Existing installation

1. Stop the server and back up `.env`, `command_center.db` and private résumé files. Preserve the encryption key; replacing it makes stored provider keys unreadable.
2. Download this release branch. From the downloaded folder run:

   ```powershell
   python install_dashboard_upgrade.py --target "C:\path\to\existing\adrian-command-center"
   ```

   The installer backs up source and the database, copies an explicit source allowlist, and preserves `.env`, database records and private files. It does not change the connected model or scheduled tasks.
3. In the existing app folder install dependencies and restart:

   ```powershell
   .\.venv\Scripts\python.exe -m pip install -r requirements.txt
   .\.venv\Scripts\python.exe -m uvicorn app:app --host 127.0.0.1 --port 8000
   ```

4. Sign in. Open API Center → Check connections. If choosing a new model, use one your account permits; the installed owner's model was separately smoke-tested before switching.

### Fresh installation

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe generate_secrets.py
.\.venv\Scripts\python.exe -m uvicorn app:app --host 127.0.0.1 --port 8000
```

Keep the generated password private. Configure an AI provider in API Center. Add optional feed/SMTP settings from `.env.example` locally. Never commit real credentials, databases, résumés, logs or screenshots of private data.

## Validation

```powershell
python -m unittest test_dashboard_v2
python -m unittest test_trading_upgrade test_trading_monitor
```

Eight isolated dashboard tests plus nine trading tests passed during development. Dashboard tests use a temporary synthetic database and credentials. Live checks covered flagship model invocation, Manager → Writer tool delegation, configured source access and SMTP authentication. Browser checks cover the simplified pages and company pagination. No new email was sent for this dashboard release.

Read `RELEASE_NOTES.md` for the release scope, verification and known limits. Earlier setup notes and `TRADING_CHAT_UPGRADE.md` remain available as historical documentation; this README describes the current dashboard.

## Main files

`app.py` — authenticated application, agent/tools, conversation and writing workflows.

`dashboard_core.py` — professional dashboard endpoints, measured service health, working status, shared retrieval, schedule reads, application stages and persistent edits.

`ai_adapter.py` — current OpenAI Responses/tool compatibility.

`static/index.html`, `static/dashboard.js`, `static/dashboard.css` — existing tools plus the simplified responsive interface.

`trading_*` — sourced research, screening, company directory, paper records and model lab.

`job_v7*`, `job_manager_bridge.py`, `resume_test_email.py` — discovery, deduplication, reviewed résumé packages and email.

`adrian_intelligence.py` — existing job preference/recommendation intelligence.

`test_dashboard_v2.py`, `test_trading_upgrade.py`, `test_trading_monitor.py` — regression checks.

