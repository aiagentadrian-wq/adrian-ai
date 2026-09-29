"""Explicit owner-requested bridge to the existing V7 radar; no AI-generated job data."""
import json, subprocess, sys
from pathlib import Path

def run(root, db, now):
    root=Path(root)
    required=('job_v7_radar.py','job_v7_email.py','job_v7_discovery.py','job_v7_packages.py')
    missing=[x for x in required if not (root/x).is_file()]
    if missing:return {'ok':False,'error':'Missing installed job pipeline modules: '+', '.join(missing)}
    with db() as c:
        before=c.execute('SELECT COALESCE(MAX(id),0) FROM email_history').fetchone()[0]
    try:
        p=subprocess.run([sys.executable,str(root/'job_v7_radar.py')],cwd=str(root),capture_output=True,text=True,timeout=180)
    except subprocess.TimeoutExpired:return {'ok':False,'error':'Job pipeline timed out. Check the task log before retrying; email status unknown.'}
    with db() as c:
        row=c.execute('SELECT id,subject,recipient,status FROM email_history WHERE id>? AND subject LIKE ? ORDER BY id DESC LIMIT 1',(before,'ADRIAN.AI — % jobs · % resume PDFs')).fetchone()
        status=c.execute('SELECT status,new_confirmed,new_review,details FROM job_v7_radar_log ORDER BY id DESC LIMIT 1').fetchone() if c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='job_v7_radar_log'").fetchone() else None
    if row and row['status']=='accepted_by_smtp':
        return {'ok':True,'status':'accepted_by_smtp','subject':row['subject'],'recipient':row['recipient'],'email_id':row['id'],'note':'The installed job pipeline sent the email with its generated attachments. Inbox delivery and vacancy status are not independently verified. No employer application submitted.'}
    if 'already running' in p.stdout.lower():return {'ok':False,'status':'busy','error':'Job radar already running; no second email attempted.'}
    if p.returncode:return {'ok':False,'status':'failed','error':'Job pipeline exited with an error. Check the local terminal/log; no new email confirmed.','diagnostic':(p.stderr or p.stdout)[-500:]}
    return {'ok':True,'status':'no_new_jobs','new_email':False,'note':'Job check completed, but no new unemailed matches were available. No duplicate or empty email sent.'}

def status(db):
    with db() as c:
        def count(table):
            if not c.execute('SELECT 1 FROM sqlite_master WHERE type="table" AND name=?',(table,)).fetchone():return 0
            return c.execute('SELECT count(*) FROM '+table+' WHERE emailed=0').fetchone()[0]
        return {'unsent_confirmed':count('job_v7_postings'),'unsent_needs_verification':count('job_v7_review'),'note':'Unsent database counts, not independently verified active vacancies.'}
