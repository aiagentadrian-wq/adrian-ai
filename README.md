# Adrian AI Command Center — V1
A runnable, private, mobile-responsive command center inspired by a GTA Master Control Terminal. This is a foundation, not a finished autonomous multi-agent system.

## Windows quick start
1. Install Python 3.11+ from python.org. During setup check **Add Python to PATH**.
2. Unzip this project. Open PowerShell inside its folder.
3. Run:
   ```powershell
   py -m venv .venv
   .\.venv\Scripts\Activate.ps1
   pip install -r requirements.txt
   python generate_secrets.py
   python -m uvicorn app:app --host 127.0.0.1 --port 8000
   ```
4. Open http://127.0.0.1:8000 and enter the generated password. Keep the `.env` file private.
5. API Center: add an OpenAI or OpenRouter key and an exact model ID supported by your account. Chat works after this step.
6. Create agents in the Agents page. You can enable/disable them and chat with them individually.

## Private remote access from phone/tablet
1. Install Tailscale on your PC and your other device. Sign into the same account and enable MFA on your identity provider.
2. With the app running on localhost, run `tailscale serve --bg 8000` on your PC. Follow the Tailscale output to find the private HTTPS URL. Do **not** use `tailscale funnel` or router port forwarding.
3. Open that private URL from a device connected to your tailnet. You still need the command center password.
4. Use your browser's **Add to Home Screen** option for an app-like shortcut. PWA install behavior depends on the browser.
5. To turn remote access off, run `tailscale serve reset`.

## Optional email
Edit `.env` and configure SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD, EMAIL_FROM and REPORT_TO. Restart the server. Email sends only to REPORT_TO after a manual click in V1. Use a dedicated SMTP credential or app password.

## Security and limitations
- No public registration. Session expires after 8 hours; sessions are memory-only and reset on restart. Login attempts are rate-limited per client address in memory.
- API keys are encrypted with Fernet using ENCRYPTION_KEY in `.env`; losing the key makes stored provider keys unrecoverable. Back up `.env` in a secure password manager, not a public repository.
- Keep the app on 127.0.0.1 and access it remotely through Tailscale Serve. Do not expose port 8000 publicly. Set COOKIE_SECURE=1 in `.env` only if every browser connection to the app is HTTPS; localhost HTTP otherwise needs the default 0.
- Provider endpoints are restricted to OpenAI and OpenRouter HTTPS hosts. The first connected provider powers all chats in V1. Model routing, per-agent model selection, cost accounting and balance APIs are **not yet implemented**.
- No live market data, live job scraping, autonomous scheduling, email automation, PC control, voice, persistent chat memory or automatic agent delegation yet. The UI does not falsely claim these actions ran.
- AI outputs may be wrong. Review market research, job applications, emails and any future PC actions before consequential use.
- Run behind a trusted private network only. For a production internet-facing deployment, add persistent auth, secure cookies, MFA, reverse-proxy hardening, backup/restore, secrets management, and security review.

## V1.1 Manager registry and delegation
The Manager now receives the actual installed agent registry on every request and has `list_agents` and `delegate_to_agent` AI function tools. Delegation invokes the selected specialist prompt and returns its answer to the Manager. This is **AI-only delegation**, not browser access, real-time market data, live job search, file access, automatic email or PC control. Each call can consume additional API tokens. The four original agents remain Manager, Day Trader, Job Finder and Writer. New agents created in the site appear in the registry automatically. Existing `.env` and `command_center.db` should be retained during an upgrade.

## V1.2 Manager email tool
Configure SMTP settings in your existing `.env` and restart. The Manager can now send a plain-text email to the single configured REPORT_TO address when the current message explicitly requests sending. For example: “Send me an email with today's activity report.” The Manager's send_email_to_owner tool returns success only after the SMTP server accepts the message; this does not guarantee inbox delivery. Failed sends are reported as errors. Never share `.env`, SMTP credentials, or API keys in chat. Use a dedicated SMTP credential or provider app password.


## V1.3 intelligence upgrade
Existing database automatically gains conversation, email_history, delegations and action_log tables. Existing .env and command_center.db are preserved by updater. Chat history stores the latest 16 user/assistant turns per agent for model context. Email history records SMTP acceptance or failure; SMTP acceptance is not proof of delivery. GET /api/activity (authenticated) returns metadata for recent emails, delegations and actions without email body. Stop server before updating; back up .env and database privately.


## V1.4 Adaptive Intelligence
Adds a Memory & Learning page, user-approved long-term memories, edit/disable/delete controls, memory-aware Manager and specialists, and recorded reviews of email and delegation outcomes. The underlying model does not retrain itself. No autonomous code changes, live job feeds, PC actions or scheduled tasks are included. Only save non-sensitive preferences, corrections, goals and project decisions.

The updater must preserve .env and command_center.db. Back both up privately before installing. Remove duplicate blank SMTP keys from .env; keep exactly one value per setting.


## V1.5 General Intelligence
Manager now has one general-purpose OpenAI hosted web search tool. It automatically chooses it for current public information and returns source URLs. No separate weather/news API keys. Uses the existing OpenAI provider key and selected model; optionally set WEB_SEARCH_MODEL in .env to a supported model if the chosen chat model cannot use hosted search. The OpenAI Responses API web-search tool incurs separate usage charges. This does not supply brokerage-grade real-time prices, private account data, or autonomous code changes. OpenRouter remains supported for normal chat, but hosted search requires OpenAI. Existing SQLite and .env remain untouched by the updater.


## V1.6 Writer Studio
Open Writer Studio in the sidebar. Save original writing samples and explicit style feedback, then create drafts. Samples, feedback and drafts are stored in existing SQLite database. Delete controls remove examples and feedback. Drafts are not sent or submitted. Writer chat and Manager delegation also receive saved style examples. The upgrade does not modify .env or existing database files.
