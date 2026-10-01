"""Durable local daily learning and one-week paper evaluation reports."""
import asyncio,json,os
from pathlib import Path
from datetime import datetime,timedelta,timezone
from zoneinfo import ZoneInfo
from fastapi import Request,HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel,Field
import local_learning,strategy_research

LOCAL=ZoneInfo('America/Toronto');APP=None
def utc():return datetime.now(timezone.utc)
class Settings(BaseModel):
    enabled:bool=False
    hour:int=Field(default=18,ge=0,le=23)
    minute:int=Field(default=0,ge=0,le=59)
class Engine:
    def __init__(self,db,paper,experiment,learned,event):
        self.db,self.paper,self.experiment,self.learned,self.event=db,paper,experiment,learned,event;self.lock=asyncio.Lock()
        with db() as c:c.executescript('''CREATE TABLE IF NOT EXISTS agent_report_settings(id INTEGER PRIMARY KEY CHECK(id=1),payload TEXT);
        CREATE TABLE IF NOT EXISTS agent_report_runs(key TEXT PRIMARY KEY,at TEXT,status TEXT,body TEXT,detail TEXT);''')
        strategy_research.setup(db)
    def config(self):
        with self.db() as c:r=c.execute('SELECT payload FROM agent_report_settings WHERE id=1').fetchone()
        return {'enabled':False,'hour':18,'minute':0}|(json.loads(r[0]) if r else {})
    def save(self,s):
        with self.db() as c:c.execute('INSERT INTO agent_report_settings VALUES(1,?) ON CONFLICT(id) DO UPDATE SET payload=excluded.payload',(json.dumps(s),))
    def summary(self):
        with self.db() as c:rows=[dict(r) for r in c.execute('SELECT key,at,status,detail FROM agent_report_runs ORDER BY at DESC LIMIT 12')]
        cfg=self.config();now=utc().astimezone(LOCAL);due=now.replace(hour=cfg['hour'],minute=cfg['minute'],second=0,microsecond=0)
        if due<now:due+=timedelta(days=1)
        return {'settings':cfg,'next_due':due.isoformat() if cfg['enabled'] else None,'week_deadline':self.experiment.config().get('ends'),'worker_running':hasattr(self,'task') and not self.task.done(),'report_recipient':os.getenv('REPORT_TO',''),'recent':rows,'learning':local_learning.status(self.db),'strategies':strategy_research.status(self.db),'note':'Daily reports catch up after a restart. At the experiment deadline a final evaluation is sent, even with no trades. App and network must remain available. SMTP acceptance is distinct from inbox receipt.'}
    async def research(self):
        import autonomous_swing as policy
        datasets={};failures=[]
        # Bounded universe shared with the current swing policy, no fabricated feeds.
        for symbol in self.learned.swing.config()['universe']:
            try:datasets[symbol]=await asyncio.to_thread(policy.download_history,symbol)
            except Exception:failures.append(symbol)
        if len(datasets)<2:raise ValueError('Research blocked: insufficient valid history')
        report=await asyncio.to_thread(strategy_research.train,self.db,datasets,utc());report['source_failures']=failures
        return report
    async def build(self,final=False):
        learning=await asyncio.to_thread(local_learning.status,self.db)
        learned=self.learned.summary();experiment=self.experiment.summary();cfg=experiment['settings']
        title='Your week of paper trading: results' if final else 'Your daily bot update'
        lines=[title,'Checked '+utc().astimezone(LOCAL).strftime('%b %d, %Y at %I:%M %p')+' Toronto','', 'TRADING']
        try:
            account=await self.paper.broker('/v2/account');positions=await self.paper.broker('/v2/positions')
            equity=float(account['equity']);start=cfg.get('start_equity');change=equity-start if start else None
            lines+=['Paper account balance: $'+format(equity,',.2f'), 'Change since the experiment began: '+('$'+format(change,'+,.2f') if change is not None else 'starting balance unavailable')+'. This is the whole account, not profit attributed to one strategy.', 'Open positions: '+(', '.join(p['symbol'] for p in positions) or 'none')+'.']
        except Exception:lines+=['Could not check the current broker account. No current balance or profit is claimed.']
        card=learned.get('learning_scorecard') or {};promoted=card.get('champion')
        lines+=['Current status: '+('A strategy has passed the production evidence checks.' if promoted else 'Still learning. No strategy has passed the production evidence checks.'),'Experiments use simulated money. Losses and no-trade days are included.']
        research=strategy_research.status(self.db);last=research['latest']
        if last:
            lines+=['','STRATEGY IDEAS','Compared '+str(len(last['trials']))+' ideas: breakout, pullback and rebound over 3 or 5 sessions.','A candidate is being observed before any trading change.' if last['selected_on_validation'] else 'None passed every validation check, so the production strategy stays unchanged.']
            settled=sum(int(r['settled'] or 0) for r in research['forward']);lines+=['Fresh shadow observations settled: '+str(settled)+'. These observations are not broker trades.','Open Trading Division → See strategy comparisons for the full historical results.']
        else:lines+=['Strategy comparison has not finished yet. No improvement is claimed.']
        with self.db() as c:
            job=c.execute('SELECT status,detail FROM job_daily_runs ORDER BY day DESC LIMIT 1').fetchone();drafts=c.execute('SELECT COUNT(*) FROM writer_drafts').fetchone()[0]
        lines+=['','JOB FINDER',('Latest daily search: '+job['detail']) if job else 'The first daily search has not completed.','Daily job updates are scheduled for 9 a.m. They include matches or an honest no-new-results update.','Your feedback: '+str(learning['jobs']['labels'])+' labelled jobs. '+('Your preferences now guide ranking.' if learning['jobs']['enabled'] else 'Use Save or Skip on real listings to teach your preferences.'),'No employer applications were sent.','','WRITER',str(learning['writer']['sample_count'])+' original writing samples saved; '+str(drafts)+' saved drafts.','Your samples guide drafting, review and revision in your voice. Add corrections in Writer Studio.','Check facts and assignment requirements. Detector scores cannot guarantee authorship or acceptance.']
        if cfg.get('ends'):lines+=['','NEXT UPDATE','Final paper evaluation: '+datetime.fromisoformat(cfg['ends']).astimezone(LOCAL).strftime('%b %d at %I:%M %p')+' Toronto.']
        if final:lines+=['','WHAT THIS WEEK TELLS US','Review the actual paper gains/losses, settled observations and failed ideas. Too little evidence or no improvement is a valid result. A week cannot prove reliable profit or performance better than a human. Unsettled positions still require monitoring and exits.']
        lines+=['','Keep your PC and ADRIAN.AI running for scheduled checks.','Report inbox: '+os.getenv('REPORT_TO','')]
        return '\n'.join(lines)
    async def run(self,key,final=False,research=True):
        # Persist claim before any external action. Restart never blindly repeats sends.
        with self.db() as c:
            c.execute("DELETE FROM agent_report_runs WHERE key=? AND status='failed_before_send'",(key,))
            claimed=c.execute('INSERT OR IGNORE INTO agent_report_runs VALUES(?,?,?,?,?)',(key,utc().isoformat(),'building','','')).rowcount
            if not claimed:return {'status':c.execute('SELECT status FROM agent_report_runs WHERE key=?',(key,)).fetchone()[0],'duplicate_prevented':True}
        research_error=None
        try:
            if research:
                try:await self.research()
                except Exception as exc:research_error=type(exc).__name__
            body=await self.build(final)
            if research_error:body+='\nCurrent research refresh failed: '+research_error+'. Prior results may be stale.'
        except Exception as exc:
            with self.db() as c:c.execute('UPDATE agent_report_runs SET status=?,detail=? WHERE key=?',('failed_before_send',type(exc).__name__,key))
            return {'status':'failed_before_send'}
        with self.db() as c:c.execute('UPDATE agent_report_runs SET status=?,body=?,detail=? WHERE key=?',('sending',body,'Research '+('failed: '+research_error if research_error else 'complete or skipped'),key))
        try:
            result=await asyncio.to_thread(self.paper.mail,'ADRIAN.AI - '+('One-week paper results' if final else 'Local agents daily learning report'),body)
            if result.get('status')!='accepted_by_smtp':raise ValueError('Sender did not confirm acceptance')
            status='accepted_by_smtp'
        except Exception:status='uncertain'
        with self.db() as c:c.execute('UPDATE agent_report_runs SET status=?,at=? WHERE key=?',(status,utc().isoformat(),key))
        self.event('Manager','local learning report '+status,key)
        return {'status':status,'key':key,'inbox_delivery_confirmed':False}
    async def tick(self):
        cfg=self.config()
        if not cfg['enabled']:return
        now=utc();deadline=self.experiment.config().get('ends')
        if deadline and now>=datetime.fromisoformat(deadline):
            await self.run('final:'+deadline,True);return
        local=now.astimezone(LOCAL)
        if local>=local.replace(hour=cfg['hour'],minute=cfg['minute'],second=0,microsecond=0):await self.run('daily:'+local.date().isoformat())
    async def loop(self):
        # A persisted unfinished handoff is uncertain, never assumed delivered.
        with self.db() as c:
            c.execute("UPDATE agent_report_runs SET status='uncertain',detail='Restart during sender handoff; check inbox before retry' WHERE status='sending'")
            c.execute("UPDATE agent_report_runs SET status='failed_before_send',detail='Restart while building; no send attempted' WHERE status='building'")
        while True:
            try:
                async with self.lock:await self.tick()
            except asyncio.CancelledError:raise
            except Exception as exc:self.event('Manager','learning report worker error',type(exc).__name__)
            await asyncio.sleep(60)
def install(app,db,paper,experiment,learned,auth,csrf,event):
    global APP
    engine=Engine(db,paper,experiment,learned,event);APP=engine
    @app.get('/agent-learning.js')
    def script():return FileResponse(Path(__file__).parent/'static'/'agent-learning.js',media_type='text/javascript')
    @app.get('/agent-learning.css')
    def stylesheet():return FileResponse(Path(__file__).parent/'static'/'agent-learning.css',media_type='text/css')
    @app.get('/api/agents/learning/status')
    def status(req:Request):auth(req);return engine.summary()
    @app.post('/api/agents/learning/settings')
    def settings(body:Settings,req:Request):csrf(req);engine.save(body.model_dump());return engine.summary()
    @app.post('/api/agents/learning/report')
    async def report(req:Request):
        csrf(req)
        async with engine.lock:return await engine.run('manual:'+utc().astimezone(LOCAL).date().isoformat(),research=False)
    @app.post('/api/agents/learning/research')
    async def research(req:Request):
        csrf(req)
        async with engine.lock:return await engine.research()
    @app.on_event('startup')
    async def startup():engine.task=asyncio.create_task(engine.loop())
    @app.on_event('shutdown')
    async def shutdown():
        engine.task.cancel()
        try:await engine.task
        except asyncio.CancelledError:pass
