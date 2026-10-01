# Simple system controls

Open **ADRIAN AI Control** on your desktop.

- **Turn system ON** starts the dashboard and all enabled bots, along with local AI if needed.
- **Turn system OFF** stops the dashboard and pauses all bot work and scheduled emails. It preserves settings, job feedback, drafts and paper records. A report already accepted by its email sender cannot be recalled.
- **Open dashboard** starts the system if needed, then opens its browser page.
- **Start automatically when I sign into Windows** enables or disables quiet startup for your Windows account. This is sign-in startup; your computer must be awake and you must sign in for scheduled work.

Closing the control window or browser leaves the bots running. Use Turn system OFF to stop them. Turning off today leaves the startup checkbox unchanged, so the system starts next time you sign in if the box remains checked. To keep it off after sign-in, uncheck startup and turn it off.

The launcher stops only the dashboard and AI processes it started. If Ollama was already running for another program, that shared AI service stays available. It never terminates another Python application or stops a broker position. Paper records and enabled-worker settings persist while the app is off. Existing report deduplication protects against duplicate reports after restarting; scheduled catch-up follows the app's existing rules.

## Installation on another Windows machine

Use the configured application folder and its existing Python runtime. Run `setup_system_control.py --dependencies PATH_TO_INSTALLED_DEPENDENCIES --enable-startup` with that Python. Use `--ollama PATH` if Ollama is elsewhere. The dependency directory must include the application's existing filelock, FastAPI and other requirements. No model download or account setup is performed by this launcher. The launcher stores machine-specific runtime paths in the private folder, not in public release files.

The per-user startup entry is named `ADRIAN AI` under the Windows Run registry key. Unchecking the box removes that entry. No administrator rights or Windows security changes are needed.

## Verification

Four isolated checks cover repeated starts, PID reuse protection, unrelated processes and graceful shutdown. The installed system was also started, stopped, restarted and started again to confirm no duplicate launch. Startup registration was checked without rebooting Windows.
