"""15-minute radar. Five jobs per readable email, no duplicates or fake confirmations."""
import sys,msvcrt,traceback
from pathlib import Path
ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT))
def main():
    lock=open(ROOT/'job_v7_radar.lock','a+b')
    try:msvcrt.locking(lock.fileno(),msvcrt.LK_NBLCK,1)
    except OSError:
        print('Radar already running; skipping overlapping check.');lock.close();return
    try:
        import app,job_v7_discovery as discovery
        from job_v7_email import build,send
        stats=discovery.discover(app.db,app.now)
        with app.db() as c:
            c.execute('''CREATE TABLE IF NOT EXISTS job_v7_radar_log(id INTEGER PRIMARY KEY,at TEXT,status TEXT,new_confirmed INTEGER,new_review INTEGER,details TEXT)''')
            cols={x[1] for x in c.execute('PRAGMA table_info(job_v7_review)')}
            if 'emailed' not in cols:c.execute('ALTER TABLE job_v7_review ADD COLUMN emailed INTEGER NOT NULL DEFAULT 0')
            if 'description' not in cols:c.execute("ALTER TABLE job_v7_review ADD COLUMN description TEXT NOT NULL DEFAULT ''")
            confirmed=[dict(x) for x in c.execute('SELECT * FROM job_v7_postings WHERE emailed=0 ORDER BY id LIMIT 5')]
            review=[dict(x) for x in c.execute('SELECT * FROM job_v7_review WHERE emailed=0 ORDER BY found LIMIT ?', (5-len(confirmed),))]
            resume=c.execute('SELECT content FROM job_v7_resume ORDER BY id DESC LIMIT 1').fetchone()
        if not confirmed and not review:
            print('Radar check OK: no new matches.',stats)
            with app.db() as c:c.execute('INSERT INTO job_v7_radar_log(at,status,new_confirmed,new_review,details) VALUES(?,?,?,?,?)',(app.now(),'no_new_jobs',0,0,str(stats)[:1500]))
            return
        jobs=[dict(j,confirmed=True,reason='') for j in confirmed]+[dict(j,confirmed=False) for j in review]
        msg,body,count=build(jobs,resume['content'] if resume else '',app.now(),stats['errors'],subject='ADRIAN.AI — Job opportunities')
        # Subject reflects actual number of attachments, not a promise of attachments.
        msg.replace_header('Subject',f'ADRIAN.AI — {len(jobs)} jobs · {count} resume PDFs')
        send(msg)
        with app.db() as c:
            c.executemany('UPDATE job_v7_postings SET emailed=1 WHERE id=?',[(j['id'],) for j in confirmed])
            c.executemany('UPDATE job_v7_review SET emailed=1 WHERE url=?',[(j['url'],) for j in review])
            c.execute('INSERT INTO job_v7_radar_log(at,status,new_confirmed,new_review,details) VALUES(?,?,?,?,?)',(app.now(),'accepted_by_smtp',len(confirmed),len(review),str(stats)[:1500]))
            c.execute('INSERT INTO email_history(at,subject,body,recipient,sender,status,error) VALUES(?,?,?,?,?,?,?)',(app.now(),str(msg['Subject']),body,str(msg['To']),str(msg['From']),'accepted_by_smtp',None))
        print('Radar email accepted by SMTP:',len(confirmed),'confirmed;',len(review),'review;',count,'PDFs.',stats)
    finally:
        try:msvcrt.locking(lock.fileno(),msvcrt.LK_UNLCK,1)
        finally:lock.close()
if __name__=='__main__':
    try:main()
    except Exception:traceback.print_exc();sys.exit(1)
