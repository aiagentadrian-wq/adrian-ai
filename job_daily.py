"""Durable daily Job Finder mail, including an honest no-new-results update."""
import asyncio,json
from datetime import datetime,timedelta,timezone
from zoneinfo import ZoneInfo
from fastapi import Request,HTTPException
from pydantic import BaseModel,Field
import job_v7_discovery,job_v7_email
LOCAL=ZoneInfo('America/Toronto');APP=None
def utc():return datetime.now(timezone.utc)
class Settings(BaseModel):
    enabled:bool=False
    hour:int=Field(default=9,ge=0,le=23)
    minute:int=Field(default=0,ge=0,le=59)
class Engine:
    def __init__(self,db,event,now):
        self.db,self.event,self.now=db,event,now;self.lock=asyncio.Lock()
        with db() as c:c.executescript('CREATE TABLE IF NOT EXISTS job_daily_settings(id INTEGER PRIMARY KEY CHECK(id=1),payload TEXT);CREATE TABLE IF NOT EXISTS job_daily_runs(day TEXT PRIMARY KEY,at TEXT,status TEXT,detail TEXT);')
    def config(self):
        with self.db() as c:r=c.execute('SELECT payload FROM job_daily_settings WHERE id=1').fetchone()
        return {'enabled':False,'hour':9,'minute':0}|(json.loads(r['payload']) if r else {})
    def save(self,value):
        with self.db() as c:c.execute('INSERT INTO job_daily_settings VALUES(1,?) ON CONFLICT(id) DO UPDATE SET payload=excluded.payload',(json.dumps(value),))
    def summary(self):
        settings=self.config();now=utc().astimezone(LOCAL);day=now.date().isoformat()
        with self.db() as c:r=c.execute('SELECT * FROM job_daily_runs WHERE day=?',(day,)).fetchone();last=c.execute('SELECT * FROM job_daily_runs ORDER BY day DESC LIMIT 1').fetchone()
        due=now.replace(hour=settings['hour'],minute=settings['minute'],second=0,microsecond=0)
        if r:due+=timedelta(days=1)
        return {'settings':settings,'next_due':due.isoformat() if settings['enabled'] else None,'catchup_due':settings['enabled'] and not r and now>=due,'today':dict(r) if r else None,'last':dict(last) if last else None,'worker_running':hasattr(self,'task') and not self.task.done(),'note':'Daily email includes new matches or no-new-matches/source-failure status. Runs when the local server is available; SMTP acceptance is not inbox receipt.'}
    def run(self):
        day=utc().astimezone(LOCAL).date().isoformat()
        with self.db() as c:
            # External/manual radar emails already accepted today fulfill the daily
            # report. Do not duplicate the same batch or fabricate delivery.
            history=c.execute("SELECT at FROM email_history WHERE status='accepted_by_smtp' AND subject LIKE 'ADRIAN.AI%job%' ORDER BY id DESC LIMIT 30").fetchall()
            already=any(datetime.fromisoformat(r['at']).astimezone(LOCAL).date().isoformat()==day for r in history)
            claimed=c.execute('INSERT OR IGNORE INTO job_daily_runs VALUES(?,?,?,?)',(day,self.now(),'already_sent' if already else 'running','Earlier owner job email accepted today.' if already else 'Daily claim persisted before discovery and email.')).rowcount
        if not claimed or already:return self.summary()
        try:
            stats=job_v7_discovery.discover(self.db,self.now)
            with self.db() as c:
                columns={r[1] for r in c.execute('PRAGMA table_info(job_v7_review)')}
                if 'emailed' not in columns:c.execute('ALTER TABLE job_v7_review ADD COLUMN emailed INTEGER NOT NULL DEFAULT 0')
                confirmed=[dict(r) for r in c.execute('SELECT * FROM job_v7_postings WHERE emailed=0 ORDER BY id LIMIT 5')]
                review=[dict(r) for r in c.execute('SELECT * FROM job_v7_review WHERE emailed=0 ORDER BY found LIMIT ?',(5-len(confirmed),))]
                resume=c.execute('SELECT content FROM job_v7_resume ORDER BY id DESC LIMIT 1').fetchone()
            jobs=[dict(j,confirmed=True,reason='') for j in confirmed]+[dict(j,confirmed=False) for j in review]
            subject='ADRIAN.AI — Daily Job Finder · '+str(len(jobs))+' new jobs'
            msg,body,count=job_v7_email.build(jobs,resume['content'] if resume else '',self.now(),stats.get('errors',[]),subject=subject)
            with self.db() as c:c.execute("UPDATE job_daily_runs SET status='sending',detail=? WHERE day=?",(str(len(jobs))+' jobs; '+str(count)+' PDFs; '+str(len(stats.get('errors',[])))+' source errors.',day))
        except Exception as exc:
            with self.db() as c:c.execute("UPDATE job_daily_runs SET status='failed_before_send',detail=? WHERE day=?",(type(exc).__name__+'; no email attempted.',day))
            self.event('Job Finder','daily email failed',type(exc).__name__);return self.summary()
        try:
            job_v7_email.send(msg)
            with self.db() as c:
                c.executemany('UPDATE job_v7_postings SET emailed=1 WHERE id=?',[(j['id'],) for j in confirmed])
                c.executemany('UPDATE job_v7_review SET emailed=1 WHERE url=?',[(j['url'],) for j in review])
                c.execute('INSERT INTO email_history(at,subject,body,recipient,sender,status,error) VALUES(?,?,?,?,?,?,?)',(self.now(),subject,body,str(msg['To']),str(msg['From']),'accepted_by_smtp',None))
                c.execute("UPDATE job_daily_runs SET at=?,status='accepted_by_smtp' WHERE day=?",(self.now(),day))
            self.event('Job Finder','daily email accepted by SMTP',str(len(jobs))+' new jobs; '+str(count)+' PDFs; inbox receipt unverified.')
        except Exception as exc:
            with self.db() as c:c.execute("UPDATE job_daily_runs SET status='uncertain',detail=? WHERE day=?",(type(exc).__name__+' during email handoff; no blind retry. Check inbox/sender.',day))
            self.event('Job Finder','daily email uncertain',type(exc).__name__)
        return self.summary()
    async def tick(self):
        s=self.config();now=utc().astimezone(LOCAL)
        if s['enabled'] and now>=now.replace(hour=s['hour'],minute=s['minute'],second=0,microsecond=0):
            with self.db() as c:exists=c.execute('SELECT 1 FROM job_daily_runs WHERE day=?',(now.date().isoformat(),)).fetchone()
            if not exists:
                core=__import__('dashboard_core');core.RUNNING['job-daily']={'agent':'Job Finder','started':core.stamp(),'task':'daily discovery and email'}
                try:await asyncio.to_thread(self.run)
                finally:core.RUNNING.pop('job-daily',None)
    async def loop(self):
        while True:
            try:
                async with self.lock:await self.tick()
            except asyncio.CancelledError:raise
            except Exception as exc:self.event('Job Finder','daily worker error',type(exc).__name__)
            await asyncio.sleep(60)
def install(app,db,auth,csrf,event,now):
    global APP
    engine=Engine(db,event,now);APP=engine
    @app.get('/api/jobs/daily/status')
    def status(req:Request):auth(req);return engine.summary()
    @app.post('/api/jobs/daily/settings')
    def settings(body:Settings,req:Request):csrf(req);engine.save(body.model_dump());return engine.summary()
    @app.post('/api/jobs/daily/run')
    async def run(req:Request):
        csrf(req)
        async with engine.lock:return await asyncio.to_thread(engine.run)
    @app.on_event('startup')
    async def startup():engine.task=asyncio.create_task(engine.loop())
    @app.on_event('shutdown')
    async def shutdown():
        engine.task.cancel()
        try:await engine.task
        except asyncio.CancelledError:pass
