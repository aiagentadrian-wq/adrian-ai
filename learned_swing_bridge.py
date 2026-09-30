"""Integrate the headless SDK swing runner with ADRIAN's existing account/report UI."""
import asyncio,json
from datetime import datetime,timedelta
from pathlib import Path
from fastapi import Request,HTTPException
from pydantic import BaseModel
import autonomous_swing as policy

APP=None
class Activation(BaseModel):
    enabled:bool=False
    paper_only:bool=True
    daily_exploration:bool|None=None

class Engine:
    def __init__(self,root,paper,swing,experiment,event):
        self.paper,self.swing,self.experiment,self.event=paper,swing,experiment,event
        self.store=policy.Store(Path(root)/'job_v7_private'/'autonomous_swing.db');self.lock=asyncio.Lock();self.last_monitor=None
    def runner(self):
        state=self.experiment.config()
        config=policy.Config(symbols=tuple(self.swing.config()['universe'][:12]),enabled=self.store.get('enabled',False),daily_exploration=self.store.get('daily_exploration',False),deadline=state.get('ends',''))
        broker=policy.AlpacaBroker(self.paper.secret('key'),self.paper.secret('secret'))
        return policy.Runner(config,self.store,broker)
    def summary(self):return self.store.summary()|{'worker_running':hasattr(self,'task') and not self.task.done(),'daily_run':'09:40 America/Toronto on actual stock-market sessions','monitor_seconds':30}
    async def activate(self,enabled,daily_exploration=None):
        # The shared one-week start/deadline keeps the two workers from creating
        # independent unlimited account experiments.
        state=self.experiment.config()
        if enabled and (not state.get('enabled') or state.get('halt_entries')):raise HTTPException(400,'An authorized, active paper experiment is required.')
        if enabled:
            self.store.put('start_equity',state['start_equity']);self.store.put('deadline',state['ends'])
        if daily_exploration is not None:self.store.put('daily_exploration',daily_exploration)
        self.store.put('enabled',enabled);self.store.note('learned swing activation',{'enabled':enabled,'deadline':state.get('ends')});return self.summary()
    async def run(self,train_only=False):
        core=__import__('dashboard_core');token='learned-swing-'+str(id(asyncio.current_task()))
        core.RUNNING[token]={'agent':'Swing Trader','started':core.stamp(),'task':'train learned policy' if train_only else 'daily learned policy'}
        try:
            result=await asyncio.to_thread(self.runner().run,train_only)
            if result.get('model'):
                __import__('dashboard_core').observe('yfinance','verified','Historical OHLCV received; completed source session '+result['model']['source_date']+'. Free delayed research data, not a live execution feed.')
            self.event('Swing Trader','learned policy run',result.get('model',{}).get('report',{}).get('verdict','Run completed'))
            return result
        except Exception as exc:
            message=str(exc)[:250];self.store.put('last_error',message);self.store.note('learned run failed',{'error':message});self.event('Swing Trader','learned run failed',message)
            if 'yfinance' in message or 'OHLCV' in message or 'Yahoo' in message or 'Historical data' in message:__import__('dashboard_core').observe('yfinance','error',message)
            raise HTTPException(502,message)
        finally:core.RUNNING.pop(token,None)
    async def monitor(self):
        runner=self.runner();await asyncio.to_thread(runner.reconcile)
        account=await self.paper.broker('/v2/account');clock=await self.paper.broker('/v2/clock');state=self.experiment.config()
        if not self.store.get('enabled',False):return
        deadline=self.store.get('deadline');equity=float(account['equity'])
        halt=bool(state.get('halt_entries')) or deadline and policy.utc()>=datetime.fromisoformat(deadline) or equity<=state.get('start_equity',equity)*.98 or equity<=state.get('day_equity',equity)*.99
        if halt and clock['is_open']:
            positions=await asyncio.to_thread(runner.broker.positions);orders=await asyncio.to_thread(runner.broker.orders)
            with self.store.connect() as c:symbols=[r['symbol'] for r in c.execute('SELECT symbol FROM holdings')]
            for symbol in symbols:await asyncio.to_thread(runner.exit,symbol,'Shared loss limit or experiment deadline',positions,orders)
            self.store.put('enabled',False)
    async def tick(self):
        if not self.store.get('enabled',False) and not self.store.unresolved():return
        await self.monitor();now=policy.utc();today=now.astimezone(policy.LOCAL).date().isoformat()
        if not self.store.get('enabled',False):return
        for row in await self.swing.calendar(now):
            if row['date']!=today:continue
            start,end=__import__('swing_trading').session_times(row);due=start+timedelta(minutes=10)
            if due<=now<due+timedelta(minutes=15) and self.store.get('last_scheduled_day')!=today:
                self.store.put('last_scheduled_day',today)
                try:await self.run(False)
                except HTTPException:pass
            elif self.store.get('daily_exploration',False) and due<=now<end-timedelta(minutes=10):
                last=self.store.get('last_run');status=self.store.get('daily_trade_status') or {}
                if status.get('day')!=today or status.get('status','').startswith('No paper entry'):
                    if not last or (now-datetime.fromisoformat(last)).total_seconds()>=300:
                        try:await self.run(False)
                        except HTTPException:pass
        # Train newly completed daily history before the next open if started
        # outside the market. No market order is sent by train-only execution.
        if not self.store.model() and self.store.get('initial_training_attempt')!=today:
            self.store.put('initial_training_attempt',today)
            try:await self.run(True)
            except HTTPException:pass
    async def loop(self):
        while True:
            try:
                async with self.lock:
                    async with self.paper.lock:await self.tick()
            except asyncio.CancelledError:raise
            except Exception as exc:
                self.store.put('last_error',str(exc)[:250]);self.event('Swing Trader','learned worker failure',type(exc).__name__)
            await asyncio.sleep(30)

def install(app,root,paper,swing,experiment,auth,csrf,event):
    global APP
    engine=Engine(root,paper,swing,experiment,event);APP=engine
    @app.get('/api/swing/learned/status')
    def status(req:Request):auth(req);return engine.summary()
    @app.post('/api/swing/learned/settings')
    async def settings(body:Activation,req:Request):
        csrf(req)
        if not body.paper_only:raise HTTPException(400,'Only paper trading exists.')
        async with engine.lock:return await engine.activate(body.enabled,body.daily_exploration)
    @app.post('/api/swing/learned/train')
    async def train(req:Request):
        csrf(req)
        async with engine.lock:
            async with engine.paper.lock:return await engine.run(True)
    @app.post('/api/swing/learned/run')
    async def run(req:Request):
        csrf(req)
        async with engine.lock:
            async with engine.paper.lock:return await engine.run(False)
    @app.on_event('startup')
    async def startup():engine.task=asyncio.create_task(engine.loop())
    @app.on_event('shutdown')
    async def shutdown():
        if hasattr(engine,'task'):
            engine.task.cancel()
            try:await engine.task
            except asyncio.CancelledError:pass
