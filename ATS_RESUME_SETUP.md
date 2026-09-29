# ATS Resume Builder — Application Desk

This draft builds on Trading Workspace V2. Upload your existing text-based PDF or DOCX to the local resume vault, import a real posting with its full description, and press TAILOR RESUME. The model is instructed to identify actual job requirements, emphasize supported matches in summary, skills and experience, and avoid unsupported claims. No format guarantees ATS passage or hiring.

Use VIEW DRAFT to load the result into the new editable text area. SAVE EDITED DRAFT saves locally and resets approval; it preserves any previous emailed status. Download a simple one-column DOCX or text-based PDF. DOCX requires python-docx; PDF requires reportlab. Review facts, contact details, dates and relevance before approval. The system does not apply to employers. Email actions remain separate and require clicking the existing explicit confirmation.

Local smoke test: upload a real resume, import two substantially different job descriptions, tailor each, compare their summaries/skills/experience emphasis, edit one, save, refresh, download DOCX and PDF, confirm no invented credentials or experience and no send occurred. Run existing unittest suites. No automatic email or scheduler activation.
