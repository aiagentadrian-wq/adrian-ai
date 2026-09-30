"""One-week, explicitly authorized autonomous STOCK PAPER experiment.

Broker orders are real records on Alpaca's paper endpoint, never real money.
"""
import asyncio,json,math,secrets,re
from datetime import datetime,timedelta,timezone
from fastapi import HTTPException,Request
from pydantic import BaseModel
import trading_ml
from swing_trading import LOCAL,session_times

APP=None
def utc():return datetime.now(timezone.utc)
def stamp():return utc().isoformat()
def flatten_orders(orders):
    return [item for order in orders for item in [order]+order.get('legs',[])]

def risk_size(account,entry,stop,reserved_risk,start_equity,day_equity):
    equity=float(account['equity']);cash=float(account.get('cash',0));distance=entry-stop
    if not all(math.isfinite(x) for x in [equity,cash,entry,stop,reserved_risk,start_equity,day_equity]) or not 0<stop<entry or equity<=0:return 0
    # Loss headroom includes planned risk of all unfinished bot entries/positions.
    budget=min(equity*.0025,max(0,day_equity*.01-max(0,day_equity-equity)-reserved_risk),max(0,start_equity*.02-max(0,start_equity-equity)-reserved_risk))
    cost_per_share=entry*.004
    return max(0,min(math.floor(budget/(distance+cost_per_share)),math.floor(cash/entry)))

class Start(BaseModel):
    confirm_paper:bool=False
    acknowledge_risk:bool=False

class Engine:
    def __init__(self,db,paper,swing,event):
        self.db,self.paper,self.swing,self.event=db,paper,swing,event;self.lock=asyncio.Lock();self.last_scan=None
        with db() as c:c.executescript('CREATE TABLE IF NOT EXISTS ml_experiment(id INTEGER PRIMARY KEY CHECK(id=1),payload TEXT);CREATE TABLE IF NOT EXISTS ml_models(id INTEGER PRIMARY KEY,at TEXT,model TEXT,report TEXT);CREATE TABLE IF NOT EXISTS ml_orders(id TEXT PRIMARY KEY,at TEXT,symbol TEXT,status TEXT,broker_id TEXT,payload TEXT,detail TEXT);CREATE TABLE IF NOT EXISTS ml_notes(id INTEGER PRIMARY KEY,at TEXT,kind TEXT,payload TEXT);CREATE TABLE IF NOT EXISTS ml_runs(day TEXT,kind TEXT,status TEXT,detail TEXT,PRIMARY KEY(day,kind));')
    def config(self):
        with self.db() as c:row=c.execute('SELECT payload FROM ml_experiment WHERE id=1').fetchone()
        return json.loads(row['payload']) if row else {'enabled':False}
    def save(self,s):
        with self.db() as c:c.execute('INSERT INTO ml_experiment VALUES(1,?) ON CONFLICT(id) DO UPDATE SET payload=excluded.payload',(json.dumps(s),))
    def note(self,kind,value):
        with self.db() as c:c.execute('INSERT INTO ml_notes(at,kind,payload) VALUES(?,?,?)',(stamp(),kind,json.dumps(value,default=str)))
        self.event('Day Trader',kind,str(value)[:180])
    def update(self,id,status,detail,broker_id=None):
        with self.db() as c:c.execute('UPDATE ml_orders SET status=?,detail=?,broker_id=COALESCE(?,broker_id) WHERE id=?',(status,detail,broker_id,id))
    def active(self):
        with self.db() as c:return [dict(x) for x in c.execute("SELECT * FROM ml_orders WHERE status NOT IN ('closed','canceled','expired','rejected','skipped')")]
    def summary(self):
        with self.db() as c:
            orders=[dict(x) for x in c.execute('SELECT * FROM ml_orders ORDER BY at DESC LIMIT 100')]
            models=[{'id':x['id'],'at':x['at'],'report':json.loads(x['report'])} for x in c.execute('SELECT id,at,report FROM ml_models ORDER BY id DESC LIMIT 5')]
            notes=[{'at':x['at'],'kind':x['kind'],'data':json.loads(x['payload'])} for x in c.execute('SELECT * FROM ml_notes ORDER BY id DESC LIMIT 20')]
        for order in orders:order['plan']=json.loads(order.pop('payload'))
        return {'settings':self.config(),'mode':'AUTOMATIC STOCK PAPER ORDERS','risk_per_trade_percent':.25,'daily_loss_limit_percent':1,'experiment_loss_limit_percent':2,'maximum_positions':3,'no_leverage':True,'scan_every_seconds':300,'monitor_every_seconds':30,'orders':orders,'models':models,'notes':notes,'worker_running':hasattr(self,'task') and not self.task.done(),
                'limitations':['Stocks only, regular sessions. Crypto/24-hour execution is not enabled.','Paper results are simulated; a $100,000 paper balance is not real money.','Loss limits are checks, not insurance against gaps or delayed execution.','Profit is not guaranteed. The system may select NO TRADE for the entire experiment if evidence fails.','App/PC must remain running and connected. Restart reconciles journalled broker orders, never blindly resubmits.']}
    async def start(self):
        existing=self.config()
        if existing.get('enabled'):return self.summary()
        if self.active():raise HTTPException(409,'Unresolved previous experiment orders must be reconciled before a restart.')
        account=await self.paper.broker('/v2/account')
        if account.get('status')!='ACTIVE' or account.get('currency')!='USD' or account.get('trading_blocked') or account.get('account_blocked'):raise HTTPException(400,'Active unblocked USD paper account required.')
        if await self.paper.broker('/v2/positions') or await self.paper.broker('/v2/orders?status=open'):raise HTTPException(409,'Start with no existing paper positions/orders to avoid mixing experiments.')
        with self.db() as c:
            table=c.execute("SELECT name FROM sqlite_master WHERE name='paper_proposals'").fetchone()
            pending=c.execute("SELECT id FROM paper_proposals WHERE status IN ('pending','executing','uncertain')").fetchone() if table else None
        if pending:raise HTTPException(409,'Resolve the existing email proposal before starting the automatic experiment.')
        now=utc();s={'enabled':True,'started':now.isoformat(),'ends':(now+timedelta(days=7)).isoformat(),'start_equity':float(account['equity']),'day':now.astimezone(LOCAL).date().isoformat(),'day_equity':float(account['equity']),'universe':['SPY','QQQ','MSFT','NVDA','AMD','AAPL'],'risk_percent':.25,'daily_loss_limit_percent':1,'experiment_loss_limit_percent':2,'max_positions':3,'threshold':.65,'allow_real_money':False,'state':'learning','last_check':now.isoformat()}
        # Store authorization before worker runs; order writes still require gates/model.
        self.save(s);self.note('experiment started',{'deadline':s['ends'],'starting_paper_equity':s['start_equity'],'authorized':'Automatic paper orders only, fixed limits; no email YES required for this experiment.'})
        # Do not run a second entry scheduler against the same paper account.
        if hasattr(self.paper,'config') and isinstance(self.paper.config(),dict):
            legacy=self.paper.config();s['previous_daily_proposals']=bool(legacy.get('daily_proposals'));legacy['daily_proposals']=False;self.paper.save(legacy);self.save(s)
        return self.summary()
    async def train(self):
        s=self.config();datasets={};errors=[]
        for symbol in s.get('universe',['SPY','QQQ','MSFT']):
            try:
                rows=(await self.paper.bars(symbol,'15min',1000))['candles']
                # Intraday API also returns extended hours: exclude them before labels.
                datasets[symbol]=[b for b in rows if (9,30)<=(datetime.fromisoformat(b['time'].replace('Z','+00:00')).astimezone(LOCAL).hour,datetime.fromisoformat(b['time'].replace('Z','+00:00')).astimezone(LOCAL).minute)<(16,0)]
            except Exception:errors.append(symbol)
        if len(datasets)<2:raise ValueError('Need historical data for at least two configured symbols')
        first=min(bars[0]['time'][:10] for bars in datasets.values());last=max(bars[-1]['time'][:10] for bars in datasets.values())
        sessions=await self.paper.broker('/v2/calendar?start='+first+'&end='+last)
        bounds={row['date']:session_times(row) for row in sessions}
        datasets={symbol:[bar for bar in bars if bar['time'][:10] in bounds and bounds[bar['time'][:10]][0]<=datetime.fromisoformat(bar['time'].replace('Z','+00:00'))<bounds[bar['time'][:10]][1]] for symbol,bars in datasets.items()}
        if any(len(bars)<100 for bars in datasets.values()):raise ValueError('Insufficient regular-session history after calendar checks')
        model,report=await asyncio.to_thread(trading_ml.train,datasets)
        with self.db() as c:records=[json.loads(x['payload']) for x in c.execute("SELECT payload FROM ml_notes WHERE kind='broker trade outcome'")]
        outcome_rows=[{'entry_time':r['entry_time'],'closed_time':r['closed_time'],'features':r['features'],'net_pnl':r['estimated_net_after_40bps_usd']} for r in records if 'entry_time' in r]
        outcome_model,outcome_report=await asyncio.to_thread(trading_ml.train_outcomes,outcome_rows)
        report['actual_trade_learning']=outcome_report
        if outcome_model and outcome_report.get('eligible_as_extra_filter'):model['actual_outcome_filter']=outcome_model
        with self.db() as c:
            last=c.execute('SELECT id,report FROM ml_models ORDER BY id DESC LIMIT 1').fetchone()
            if last:
                old=json.loads(last['report']);report['previous_version']=last['id'];report['improvement']={k:{'before':old['metrics']['test'].get(k),'after':report['metrics']['test'].get(k)} for k in ['accuracy','brier_score','selected_nonoverlap_samples','selected_mean_net_return_pct']};report['test_data_reused']=True
            else:report['test_data_reused']=False
            report['data_failures']=errors
            cur=c.execute('INSERT INTO ml_models(at,model,report) VALUES(?,?,?)',(stamp(),json.dumps(model),json.dumps(report)));version=cur.lastrowid
        s=self.config();s.update(model_version=version,state='paper scanning' if report['paper_eligible'] else 'learning / no eligible model');self.save(s)
        self.note('machine learning trained',{'version':version,'verdict':report['verdict'],'metrics':report['metrics'],'improvement':report.get('improvement')})
        return report
    async def reconcile(self):
        for row in self.active():
            plan=json.loads(row['payload']);client='adrian-ml-'+row['id']
            try:order=await self.paper.broker('/v2/orders:by_client_order_id?client_order_id='+client)
            except Exception:
                if row['status'] in ('submitting','uncertain'):self.update(row['id'],'uncertain','Submission unresolved. Further entries blocked until broker reconciliation.')
                continue
            status=order['status'];id=order['id']
            exits=[x for x in order.get('legs',[]) if float(x.get('filled_qty') or 0)>0]
            if row['status'] in ('flattening','exit_uncertain'):
                try:
                    timed=await self.paper.broker('/v2/orders:by_client_order_id?client_order_id=adrian-exit-'+row['id'])
                    if float(timed.get('filled_qty') or 0)>0:exits.append(timed)
                except Exception:pass
            entry_qty=float(order.get('filled_qty') or 0);exit_qty=sum(float(x.get('filled_qty') or 0) for x in exits)
            if entry_qty>0 and exit_qty>=entry_qty:
                entry=float(order['filled_avg_price']);exit_value=sum(float(x['filled_avg_price'])*float(x['filled_qty']) for x in exits);gross=exit_value-entry*entry_qty
                if row['status']!='closed':self.note('broker trade outcome',{'symbol':row['symbol'],'entry_time':row['at'],'closed_time':stamp(),'entry_fill':entry,'exit_fills':[{k:x.get(k) for k in ['type','filled_avg_price','filled_qty','filled_at']} for x in exits],'gross_pnl_usd':round(gross,2),'estimated_net_after_40bps_usd':round(gross-(entry*entry_qty+exit_value)*.002,2),'model_version':plan['model_version'],'features':plan['features'],'lesson':'Winning/losing outcome recorded; one trade does not establish an edge.'})
                self.update(row['id'],'closed','Broker entry and complete bracket exit fills confirmed.',id);continue
            if status in ('canceled','expired','rejected') and entry_qty==0:self.update(row['id'],status,'Broker '+status+'; no fill confirmed.',id);continue
            if row['status'] not in ('exit_pending','flattening','exit_uncertain'):
                self.update(row['id'],'filled' if entry_qty>0 else 'submitted','Broker '+status+'; filled '+str(entry_qty)+' at '+str(order.get('filled_avg_price')),id)
    async def close_owned(self,row,reason):
        # Only a symbol exclusively acquired by this bot at start can be flattened.
        # Cancel protective orders first, verify no open order remains, then sell the
        # actual long position. Persist the exit ID before the write; never blind retry.
        plan=json.loads(row['payload']);symbol=row['symbol']
        if row['status']=='exit_uncertain':
            try:
                order=await self.paper.broker('/v2/orders:by_client_order_id?client_order_id=adrian-exit-'+row['id'])
                self.update(row['id'],'flattening','Exit broker status '+order['status']);return
            except Exception:return
        positions=await self.paper.broker('/v2/positions');position=next((p for p in positions if p['symbol']==symbol),None)
        opens=flatten_orders(await self.paper.broker('/v2/orders?status=open&nested=true'))
        matching=[x for x in opens if x.get('symbol')==symbol and x.get('status') not in ('filled','canceled','expired','rejected')]
        if matching:
            for order in matching:
                # Cancel only original bot entry or its bracket descendants.
                original=await self.paper.broker('/v2/orders:by_client_order_id?client_order_id=adrian-ml-'+row['id'])
                ids={original['id']}|{x['id'] for x in original.get('legs',[])}
                if order['id'] not in ids:raise ValueError('Other order on bot symbol: manual review required before exit')
                try:await self.paper.broker('/v2/orders/'+order['id'],'DELETE')
                except Exception:pass
            self.update(row['id'],'exit_pending',reason+'; waiting for cancellation confirmation.');return
        if not position:
            self.update(row['id'],'closed','No remaining broker position or open orders; '+reason)
            self.note('position resolved',{'symbol':symbol,'reason':reason,'note':'No numeric realized P/L inferred without matching fill records.'});return
        if float(position['qty'])<=0:raise ValueError('Unexpected short/zero position; no automated sell')
        original=await self.paper.broker('/v2/orders:by_client_order_id?client_order_id=adrian-ml-'+row['id'])
        if float(position['qty'])>float(original.get('filled_qty') or 0):raise ValueError('Position contains additional/manual shares; no automated flatten')
        exit_client='adrian-exit-'+row['id']
        if row['status']=='flattening':
            try:
                order=await self.paper.broker('/v2/orders:by_client_order_id?client_order_id='+exit_client)
                if order['status'] in ('rejected','canceled','expired'):self.update(row['id'],'exit_uncertain','Exit failed; manual broker review required.')
            except Exception:self.update(row['id'],'exit_uncertain','Exit outcome unresolved; manual review.')
            return
        self.update(row['id'],'exit_uncertain',reason+'; market exit claim persisted before submission.')
        try:
            result=await self.paper.broker('/v2/orders','POST',{'symbol':symbol,'qty':position['qty'],'side':'sell','type':'market','time_in_force':'day','client_order_id':exit_client})
            self.update(row['id'],'flattening',reason+'; market exit submitted, fill unconfirmed.')
            self.note('paper time exit submitted',{'symbol':symbol,'id':result['id'],'reason':reason})
        except Exception:pass
    async def monitor(self,clock,account):
        now=utc();s=self.config();day=now.astimezone(LOCAL).date().isoformat()
        if s.get('day')!=day:s.update(day=day,day_equity=float(account['equity']));self.save(s)
        equity=float(account['equity']);stop=equity<=s['day_equity']*.99 or equity<=s['start_equity']*.98
        deadline=now>=datetime.fromisoformat(s['ends']);end=datetime.fromisoformat(clock['next_close'].replace('Z','+00:00'))
        await self.reconcile()
        for row in self.active():
            plan=json.loads(row['payload']);elapsed=(now-datetime.fromisoformat(row['at'])).total_seconds()
            pending=row['status'] in ('submitted','submitting','uncertain')
            if pending and elapsed>180 and row.get('broker_id'):
                try:await self.paper.broker('/v2/orders/'+row['broker_id'],'DELETE');self.note('entry timeout',{'symbol':row['symbol'],'reason':'Unfilled limit canceled after three minutes; awaiting broker confirmation.'})
                except Exception:pass
            due=stop or deadline or now>=end-timedelta(minutes=15) or elapsed>=75*60 or row['status'] in ('exit_pending','flattening','exit_uncertain')
            if due and clock['is_open']:await self.close_owned(row,'Loss limit' if stop else 'Experiment deadline' if deadline else 'Time/session exit')
        if stop or deadline:
            s=self.config();s.update(state='risk stop / managing exits' if stop else 'completed' if not self.active() else 'deadline / managing exits',halt_entries=True)
            if not self.active():s['enabled']=False
            self.save(s)
            if not self.active():await self.email_report('final')
    async def scan(self,clock,account):
        s=self.config();now=utc()
        if not s.get('enabled') or s.get('halt_entries') or now>=datetime.fromisoformat(s['ends']) or not clock['is_open']:return
        end=datetime.fromisoformat(clock['next_close'].replace('Z','+00:00'))
        if now>=end-timedelta(minutes=90):return
        with self.db() as c:row=c.execute('SELECT * FROM ml_models ORDER BY id DESC LIMIT 1').fetchone()
        if not row:return
        report=json.loads(row['report']);model=json.loads(row['model'])
        if not report['paper_eligible']:self.note('no trade',{'reason':'Model failed later-period experimental eligibility checks.'});return
        if account.get('status')!='ACTIVE' or account.get('currency')!='USD' or account.get('trading_blocked') or account.get('account_blocked'):return
        active=self.active()
        if any(x['status'] in ('submitting','uncertain','exit_pending','exit_uncertain','flattening') for x in active):return
        positions=await self.paper.broker('/v2/positions');orders=flatten_orders(await self.paper.broker('/v2/orders?status=open&nested=true'))
        occupied={x['symbol'] for x in positions+orders};reserved=sum(json.loads(x['payload'])['planned_risk'] for x in active)
        slots=max(0,3-len(occupied));candidates=[]
        for symbol in s['universe']:
            if symbol in occupied or any(x['symbol']==symbol for x in active):continue
            try:
                data=await self.paper.bars(symbol,'15min',160);bars=[b for b in data['candles'] if (9,30)<=(datetime.fromisoformat(b['time'].replace('Z','+00:00')).astimezone(LOCAL).hour,datetime.fromisoformat(b['time'].replace('Z','+00:00')).astimezone(LOCAL).minute)<(16,0)]
                if len(bars)<51 or not data['quality']['recent_intraday_bar']:continue
                bar_time=datetime.fromisoformat(bars[-1]['time'].replace('Z','+00:00'))
                if bar_time.astimezone(LOCAL).date()!=now.astimezone(LOCAL).date() or now-bar_time>timedelta(minutes=32):continue
                x=trading_ml.features(bars,len(bars)-1);p=trading_ml.probability(model,x)
                if p<s['threshold'] or x[3]<=0 or x[5]<=0 or x[6]<.8:continue
                if 'actual_outcome_filter' in model and trading_ml.probability(model['actual_outcome_filter'],x)<.55:continue
                with self.db() as c:used=c.execute("SELECT id FROM ml_orders WHERE symbol=? AND json_extract(payload,'$.signal_time')=?",(symbol,bars[-1]['time'])).fetchone()
                if used:continue
                snap=await self.paper.snapshot(symbol);trade=snap['latestTrade'];quote=snap['latestQuote'];minute=snap['minuteBar']
                for item,minimum,maximum in [(trade,0,90),(quote,0,90),(minute,60,180)]:
                    age=(now-datetime.fromisoformat(item['t'].replace('Z','+00:00'))).total_seconds()
                    if not minimum<=age<=maximum:raise ValueError('Stale or incomplete entry data')
                bid,ask=float(quote['bp']),float(quote['ap']);price=float(trade['p'])
                if not 0<bid<=ask or (ask-bid)/ask>.003 or abs(price/ask-1)>.005 or float(minute['v'])<=0:continue
                limit=round(ask*1.001,2);atr=x[7]*bars[-1]['close'];stop=round(limit-max(atr,limit*.003),2)
                if not 0<(limit-stop)/limit<=.03:continue
                # Quote chase/confirmation uses latest complete signal, not AI guesses.
                if float(minute['c'])<bars[-1]['close'] or limit>bars[-1]['close']*1.005:continue
                target=round(limit+2*(limit-stop),2)
                candidates.append({'symbol':symbol,'entry':limit,'stop':stop,'target':target,'score':p,'features':x,'model_version':row['id'],'signal_time':bars[-1]['time'],'reason':'ML score >=0.65, completed regular-session trend above SMA20 above SMA50, relative volume >=0.8; fresh quote and completed minute confirmed.'})
            except Exception as exc:self.note('candidate skipped',{'symbol':symbol,'reason':str(exc.detail) if isinstance(exc,HTTPException) else type(exc).__name__})
        for plan in sorted(candidates,key=lambda x:x['score'],reverse=True)[:slots]:
            # Recheck actual account, occupied symbols, clock immediately before write.
            current=await self.paper.broker('/v2/account');fresh_clock=await self.paper.broker('/v2/clock')
            current_positions=await self.paper.broker('/v2/positions');fresh_orders=flatten_orders(await self.paper.broker('/v2/orders?status=open&nested=true'))
            occupied={x['symbol'] for x in current_positions+fresh_orders}
            if not fresh_clock['is_open'] or plan['symbol'] in occupied or len(occupied)>=3 or current.get('trading_blocked') or current.get('account_blocked'):continue
            # Cash reserves for unfilled buys prevent aggregate pending orders from
            # accidentally using the paper margin buying-power allowance.
            pending_cash=sum(max(0,float(o.get('qty') or 0)-float(o.get('filled_qty') or 0))*float(o.get('limit_price') or plan['entry']) for o in fresh_orders if o.get('side')=='buy')
            current=dict(current);current['cash']=max(0,float(current['cash'])-pending_cash)
            quantity=risk_size(current,plan['entry'],plan['stop'],reserved,s['start_equity'],s['day_equity'])
            if quantity<1:continue
            try:
                import trading_division as td
                plan['news']=(await td.news(plan['symbol'])).get('articles',[])[:3]
                plan['event_risk_note']='News retrieved; upcoming earnings/halts cannot be guaranteed absent. Small paper exposure only.'
            except Exception:
                self.note('candidate skipped',{'symbol':plan['symbol'],'reason':'News service unavailable before entry.'});continue
            plan.update(quantity=quantity,planned_risk=round(quantity*(plan['entry']-plan['stop']+plan['entry']*.004),2),mode='PAPER ONLY')
            id=secrets.token_hex(12);client='adrian-ml-'+id
            with self.db() as c:c.execute('INSERT INTO ml_orders VALUES(?,?,?,?,?,?,?)',(id,stamp(),plan['symbol'],'submitting',None,json.dumps(plan),'Claim persisted; broker outcome not yet confirmed.'))
            payload={'symbol':plan['symbol'],'qty':str(quantity),'side':'buy','type':'limit','limit_price':str(plan['entry']),'time_in_force':'day','order_class':'bracket','take_profit':{'limit_price':str(plan['target'])},'stop_loss':{'stop_price':str(plan['stop'])},'client_order_id':client}
            try:
                order=await self.paper.broker('/v2/orders','POST',payload);self.update(id,'submitted','Actual Alpaca paper order accepted; fill not yet confirmed.',order['id'])
                self.note('actual paper order submitted',{'broker_order_id':order['id'],'plan':plan});reserved+=plan['planned_risk']
            except Exception:self.update(id,'uncertain','Submission uncertain; no blind retry or further entry.');break
    async def email_report(self,kind):
        day=utc().astimezone(LOCAL).date().isoformat()
        with self.db() as c:claimed=c.execute('INSERT OR IGNORE INTO ml_runs VALUES(?,?,?,?)',(day,kind,'sending','')).rowcount
        if not claimed:return
        try:
            summary=self.summary();account=await self.paper.broker('/v2/account');s=self.config()
            result={'kind':kind,'paper_equity':account['equity'],'paper_change_from_start_usd':round(float(account['equity'])-s.get('start_equity',float(account['equity'])),2),'state':s.get('state'),'models':summary['models'],'orders':summary['orders'],'notes':summary['notes'],'limitations':summary['limitations']}
            text='ADRIAN one-week MACHINE LEARNING paper experiment\n'+json.dumps(result,indent=2,default=str)[:45000]
            sent=await asyncio.to_thread(self.paper.mail,'ADRIAN ML paper experiment — '+kind,text)
            with self.db() as c:c.execute('UPDATE ml_runs SET status=?,detail=? WHERE day=? AND kind=?',(sent['status'],'Accepted by SMTP; inbox delivery not confirmed.',day,kind))
        except Exception:
            with self.db() as c:c.execute("UPDATE ml_runs SET status='failed',detail='Email/account failed; no delivery assumed.' WHERE day=? AND kind=?",(day,kind))
    async def tick(self):
        s=self.config()
        if not s.get('enabled'):return
        account=await self.paper.broker('/v2/account');clock=await self.paper.broker('/v2/clock')
        await self.monitor(clock,account);s=self.config()
        if not s.get('enabled'):return
        day=utc().astimezone(LOCAL).date().isoformat()
        with self.db() as c:last=c.execute('SELECT at FROM ml_models ORDER BY id DESC LIMIT 1').fetchone()
        # Once per local day; completed historical labels only. Never mutate an order.
        if not last or datetime.fromisoformat(last['at']).astimezone(LOCAL).date().isoformat()<day:
            try:await self.train()
            except Exception as exc:
                s=self.config();s.update(state='learning blocked',last_error=str(exc.detail) if isinstance(exc,HTTPException) else str(exc)[:200]);self.save(s);self.note('training failed',s['last_error'])
        if not self.last_scan or (utc()-self.last_scan).total_seconds()>=300:
            await self.scan(clock,account);self.last_scan=utc()
        s=self.config();s['last_check']=stamp();self.save(s)
        for row in await self.swing.calendar():
            if row['date']!=day:continue
            start,end=session_times(row)
            for kind,due in [('open',start),('midday',start+(end-start)/2),('close',end+timedelta(minutes=5))]:
                if due<=utc()<due+timedelta(minutes=15):await self.email_report(kind)
    async def loop(self):
        while True:
            try:
                async with self.lock:
                    async with self.paper.lock:await self.tick()
            except asyncio.CancelledError:raise
            except Exception as exc:
                s=self.config();s['last_error']=str(exc.detail) if isinstance(exc,HTTPException) else type(exc).__name__;s['last_check']=stamp();self.save(s);self.note('experiment check failed',s['last_error'])
            await asyncio.sleep(30)

def install(app,db,paper,swing,auth,csrf,event):
    global APP
    engine=Engine(db,paper,swing,event);APP=engine
    @app.get('/api/experiment/status')
    def status(req:Request):auth(req);return engine.summary()
    @app.post('/api/experiment/start')
    async def start(body:Start,req:Request):
        csrf(req)
        if not body.confirm_paper or not body.acknowledge_risk:raise HTTPException(400,'Explicit paper authorization and acknowledgement required.')
        async with engine.lock:
            async with engine.paper.lock:return await engine.start()
    @app.post('/api/experiment/stop')
    async def stop(req:Request):
        csrf(req);s=engine.config();s.update(halt_entries=True,state='stopping / managing exits')
        if not engine.active():s['enabled']=False
        else:s['ends']=stamp()
        engine.save(s);return engine.summary()
    @app.post('/api/experiment/train')
    async def train(req:Request):
        csrf(req)
        async with engine.lock:return await engine.train()
    @app.on_event('startup')
    async def startup():engine.task=asyncio.create_task(engine.loop())
    @app.on_event('shutdown')
    async def shutdown():
        if hasattr(engine,'task'):
            engine.task.cancel()
            try:await engine.task
            except asyncio.CancelledError:pass
