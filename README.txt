ADRIAN.AI V7 RESUME PACKAGES
Extract the ZIP into a folder named application-update inside your main ADRIAN.AI directory.
Stop the server and temporarily disable scheduled radar/AM/PM tasks while installing.
From PowerShell in main ADRIAN.AI directory:
.\.venv\Scripts\python.exe .\application-update\install_packages.py
If STOP, do not force; send the exact error.
Resume source: Upload your real PDF or DOCX through the existing V7 Resume Vault.
Radar and 8AM/5PM emails now attach up to 8 draft PDFs for newly discovered confirmed matches.
They contain ONLY verbatim statements selected from your original resume, followed by the original resume.
No invented work experience. These are review drafts, not employer applications.
Unknown pay/hours review candidates get links, not resume PDFs.
Indeed is NOT connected; no public Indeed API credentials were supplied.
No real SMTP/API test was possible here; run a manual radar and inspect received PDF.
Existing emailed jobs are NOT resent. New matches trigger attachments.
Your existing 15-minute task and 8AM/5PM tasks continue using updated modules.
Requires reportlab installed in .venv; if missing run:
.\.venv\Scripts\python.exe -m pip install reportlab
