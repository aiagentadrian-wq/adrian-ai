# Professional Dashboard 2.0 — 2026-09-29

This is a cumulative release including the grounded trading and ATS update.

## Changes

- Reduced navigation; moved security/logout, memory review, samples and agent administration into Settings.
- Agent-focused Overview with real working/idle state and latest recorded tasks. Briefing/activity relocated to Reports & Email.
- Trading surface focused on compact comparison, Market Terminal and Ask Day Trader; advanced tools remain collapsed. All SEC directory entries reachable through search and pagination.
- Job Finder combines discovery, reviewed packages and user-recorded application tracking. Displays actual scheduler data or a clear unavailable/not-scheduled state.
- API Center includes OpenAI/OpenRouter, Twelve Data, GNews, FRED, SEC, Bank of Canada, Statistics Canada, Adzuna, Arbeitnow, configured Lever/Greenhouse/public feeds and SMTP.
- Tracks actual successful/failed requests, access and quota problems, checked times and stale status. Checks never infer credit balances or inbox delivery.
- GPT-6 Astra invocation verified on the connected account; supported Responses function/tool adapter added.
- Explicit natural-language memory with relevant retrieval and shared historical specialist results. No claim of LLM retraining.
- Writer edits now persist in the local database; voice review and sample controls decluttered. Fixed legacy form newline/word-count escaping.
- Removed redundant model calls for deterministic daily trade comparisons.

## Verified

- Seven dashboard regression tests and nine existing trading tests.
- Actual GPT-6 Astra response and Manager tool delegation to Writer.
- All configured feed access checks and SMTP authentication succeeded at verification time.
- Credentials, private records and scheduled tasks are excluded from repository updates. Existing .env is preserved during upgrade.

## Limits

- API access, entitlement, freshness and credit availability can change after a check.
- No broker orders or automatic employer applications.
- Trading stays WAIT when live-entry evidence is unverified; ranking covers a limited configured universe.
- Windows schedule reads can fail under restricted accounts. No registered ADRIAN scheduled tasks were found during the elevated read-only inspection; no automatic cadence was created.
- Authentic writing review does not guarantee AI-detector results.
- Memory is stored/retrieved context, not training the provider's language model.
- Email authentication/acceptance does not verify inbox delivery. No additional test email was sent for this release.

