"""Scheduled briefing using the same readable five-job mailer as radar."""
import sys,traceback
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
def main():
    import app,job_v7_discovery as discovery
    from job_v7_email import build,send
    stats=discovery.discover(app.db,app.now)
    with app.db() as c:
        cols={x[1] for x in c.execute('PRAGMA table_info(job_v7_review)')}
        if 'emailed' not in cols:c.execute('ALTER TABLE job_v7_review ADD COLUMN emailed INTEGER NOT NULL DEFAULT 0')
        if 'description' not in cols:c.execute("ALTER TABLE job_v7_review ADD COLUMN description TEXT NOT NULL DEFAULT ''")
        confirmed=[dict(x) for x in c.execute('SELECT * FROM job_v7_postings WHERE emailed=0 ORDER BY id LIMIT 5')]
        review=[dict(x) for x in c.execute('SELECT * FROM job_v7_review WHERE emailed=0 ORDER BY found LIMIT ?', (5-len(confirmed),))]
        resume=c.execute('SELECT content FROM job_v7_resume ORDER BY id DESC LIMIT 1').fetchone()
    jobs=[dict(j,confirmed=True,reason='') for j in confirmed]+[dict(j,confirmed=False) for j in review]
    if not jobs:
        print('Briefing: no new unsent jobs; not repeating previous listings.',stats)
        return
    msg,body,count=build(jobs,resume['content'] if resume else '',app.now(),stats['errors'])
    msg.replace_header('Subject',f'ADRIAN.AI — {len(jobs)} jobs · {count} resume PDFs')
    send(msg)
    with app.db() as c:
        c.executemany('UPDATE job_v7_postings SET emailed=1 WHERE id=?',[(j['id'],) for j in confirmed])
        c.executemany('UPDATE job_v7_review SET emailed=1 WHERE url=?',[(j['url'],) for j in review])
        c.execute('INSERT INTO email_history(at,subject,body,recipient,sender,status,error) VALUES(?,?,?,?,?,?,?)',(app.now(),str(msg['Subject']),body,str(msg['To']),str(msg['From']),'accepted_by_smtp',None))
    print('Briefing accepted by SMTP:',len(jobs),'jobs;',count,'PDFs')
if __name__=='__main__':
    try:main()
    except Exception:traceback.print_exc();sys.exit(1)
