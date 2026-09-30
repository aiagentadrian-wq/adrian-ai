"""Calendar-aware swing research, real paper-account monitoring and strategy lab.

Recommendations are advisory. This module has no broker order-write capability.
"""
import asyncio,json,math,re,hashlib
from datetime import datetime,timedelta,timezone
from pathlib import Path
from zoneinfo import ZoneInfo
from fastapi import HTTPException,Request
from fastapi.responses import FileResponse
from pydantic import BaseModel,Field
import trading_education
import swing_lab

LOCAL=ZoneInfo('America/Toronto');UTC=timezone.utc;APP=None
DEFAULTS={'enabled':False,'universe':['SPY','QQQ','MSFT','NVDA','AMD','AAPL','AMZN','META','GOOGL','TSLA','AVGO','JPM'],'risk_percent':.25}
def utc():return datetime.now(UTC)
def stamp():return utc().isoformat()
def session_times(row):
    def parse(value):
        return datetime.fromisoformat(row['date']+'T'+value).replace(tzinfo=LOCAL).astimezone(UTC)
    return parse(row['open']),parse(row['close'])

def schedule(rows,now):
    result=[]
    for row in rows:
        start,end=session_times(row)
        for kind,due in [('open',start),('midday',start+(end-start)/2),('close',end+timedelta(minutes=5))]:
            result.append({'day':row['date'],'kind':kind,'due':due.isoformat(),'local':due.astimezone(LOCAL).isoformat(),
                           'eligible':due<=now<due+timedelta(minutes=15)})
    return result

def sized(plan,equity,cash,risk_percent):
    limit=plan['maximum_entry'];distance=limit-plan['stop'];reserve=limit*.004
    if not all(math.isfinite(float(v)) and float(v)>0 for v in [equity,cash,limit,distance,risk_percent]):return {'quantity':0,'planned_risk_usd':0}
    quantity=max(0,min(math.floor(equity*risk_percent/100/(distance+reserve)),math.floor(cash/limit)))
    return {'quantity':quantity,'planned_risk_usd':round(quantity*(distance+reserve),2),'cost_assumption':'40 bps round trip reserved; actual gaps/costs can exceed planned risk.'}

def confirmation(plan,snapshot,now,is_open):
    if not is_open:return 'WAIT — market closed'
    trade=snapshot.get('latestTrade',{});bar=snapshot.get('minuteBar',{});quote=snapshot.get('latestQuote',{})
    try:
        for item,minimum,maximum in [(trade,0,90),(quote,0,90),(bar,60,180)]:
            age=(now-datetime.fromisoformat(item['t'].replace('Z','+00:00'))).total_seconds()
            if not minimum<=age<=maximum:raise ValueError('Stale/incomplete quote or bar')
        bid,ask=float(quote['bp']),float(quote['ap'])
        if not 0<bid<=ask or (ask-bid)/ask>.003:raise ValueError('Invalid/wide spread')
        if not plan['entry']<=float(trade['p'])<=plan['maximum_entry'] or not plan['entry']<=ask<=plan['maximum_entry']:return 'SKIP — trigger not met or price beyond chase cap'
        if float(bar['c'])<plan['entry'] or float(bar['v'])<=0:return 'WAIT — completed minute confirmation missing'
        return 'PAPER ENTRY CONDITION MET — review the plan and event risk before placing'
    except (KeyError,ValueError,TypeError):return 'WAIT — fresh bid/ask and completed minute evidence missing'

class Settings(BaseModel):
    enabled:bool=False
    universe:list[str]=Field(default_factory=lambda:list(DEFAULTS['universe']),min_length=1,max_length=12)
    risk_percent:float=Field(default=.25,gt=0,le=.5)
class LabRequest(BaseModel):
    symbols:list[str]=Field(default_factory=lambda:['SPY','QQQ','MSFT'],min_length=1,max_length=12)
    improve:bool=False
    parameters:dict=Field(default_factory=dict)

class Engine:
    def __init__(self,db,paper,event,model_call):
        self.db,self.paper,self.event,self.model_call=db,paper,event,model_call;self.lock=asyncio.Lock();self.calendar_cache=None
        with db() as c:
            c.executescript('CREATE TABLE IF NOT EXISTS swing_settings(id INTEGER PRIMARY KEY CHECK(id=1),payload TEXT);CREATE TABLE IF NOT EXISTS swing_reports(id INTEGER PRIMARY KEY,at TEXT,kind TEXT,payload TEXT);CREATE TABLE IF NOT EXISTS swing_runs(day TEXT,kind TEXT,due TEXT,status TEXT,detail TEXT,PRIMARY KEY(day,kind));CREATE TABLE IF NOT EXISTS swing_experiments(id INTEGER PRIMARY KEY,at TEXT,fingerprint TEXT,payload TEXT);')
    def config(self):
        with self.db() as c:row=c.execute('SELECT payload FROM swing_settings WHERE id=1').fetchone()
        return DEFAULTS| (json.loads(row['payload']) if row else {})
    def save(self,value):
        with self.db() as c:c.execute('INSERT INTO swing_settings VALUES(1,?) ON CONFLICT(id) DO UPDATE SET payload=excluded.payload',(json.dumps(value),))
    async def calendar(self,now=None):
        now=now or utc()
        if self.calendar_cache and (now-self.calendar_cache[0]).total_seconds()<300:return self.calendar_cache[1]
        day=now.astimezone(LOCAL).date();rows=await self.paper.broker('/v2/calendar?start='+(day-timedelta(days=14)).isoformat()+'&end='+(day+timedelta(days=14)).isoformat())
        if not isinstance(rows,list) or not rows:raise HTTPException(502,'Market calendar unavailable; swing scheduling blocked.')
        for row in rows:session_times(row)
        self.calendar_cache=(now,rows);return rows
    async def status(self):
        value=self.config();now=utc();error=None;upcoming=[]
        try:upcoming=[x for x in schedule(await self.calendar(now),now) if datetime.fromisoformat(x['due'])>=now][:6]
        except Exception:error='Calendar/broker unavailable. No scheduled session times confirmed.'
        with self.db() as c:
            last=c.execute('SELECT * FROM swing_reports ORDER BY id DESC LIMIT 1').fetchone()
            runs=[dict(x) for x in c.execute('SELECT * FROM swing_runs ORDER BY due DESC LIMIT 12')]
            experiments=[{'id':x['id'],'at':x['at'],'result':json.loads(x['payload'])} for x in c.execute('SELECT * FROM swing_experiments ORDER BY id DESC LIMIT 5')]
        if last:last=dict(last);last['report']=json.loads(last.pop('payload'))
        return {'settings':value,'mode':'PAPER RESEARCH / MANUAL PLACEMENT','checked':now.isoformat(),'upcoming':upcoming,'calendar_error':error,'last_report':last,'runs':runs,'experiments':experiments,'learned_policy':__import__('learned_swing_bridge').APP.summary() if __import__('learned_swing_bridge').APP else None,'worker_running':hasattr(self,'task') and not self.task.done(),'note':'Emails run while ADRIAN is running. Missed sessions are recorded, not backfilled. No live-money orders or guaranteed profits.'}
    async def scan(self,kind='manual'):
        now=utc();rows=await self.calendar(now);today=now.astimezone(LOCAL).date().isoformat()
        # Alpaca daily bars can include extended hours: use prior session daily bars even
        # after the regular close. Closing snapshots are labelled separately.
        prior=[x['date'] for x in rows if x['date']<today]
        expected=max(prior) if prior else None
        clock=await self.paper.broker('/v2/clock');account=await self.paper.broker('/v2/account')
        positions=await self.paper.broker('/v2/positions');orders=await self.paper.broker('/v2/orders?status=open&nested=true')
        candidates=[];failures=[];s=self.config()
        for symbol in s['universe']:
            try:
                data=await self.paper.bars(symbol,'1day',160);bars=data['candles']
                bars=[b for b in bars if b['time'][:10]<=expected] if expected else []
                if not bars:raise ValueError('No prior-session completed daily history')
                if bars[-1]['time'][:10]!=expected:raise ValueError('Latest completed daily bar does not match prior trading session')
                plan=swing_lab.signal(bars,len(bars)-1,swing_lab.BASE)
                if not plan:continue
                # Require IEX volume-based dollar liquidity, labelled partial coverage.
                dollar=sum(b['close']*b['volume'] for b in bars[-20:])/20
                if dollar<2000000:continue
                plan.update(symbol=symbol,hold_sessions=10,valid_session=today,source=data['source'],daily_as_of=bars[-1]['time'],score=round(plan['relative_volume'],2))
                plan.update(sized(plan,float(account['equity']),float(account['cash']),s['risk_percent']))
                plan['action']=confirmation(plan,await self.paper.snapshot(symbol),now,clock['is_open'])
                if positions or orders:plan['action']='WAIT — existing paper positions/orders; no additional exposure recommended'
                if plan['quantity']<1 or account.get('trading_blocked') or account.get('account_blocked') or account.get('currency')!='USD':plan['action']='SKIP — account, cash or risk checks failed'
                candidates.append(plan)
            except Exception as exc:failures.append({'symbol':symbol,'reason':str(exc.detail) if isinstance(exc,HTTPException) else str(exc)[:160]})
        candidates.sort(key=lambda x:x['score'],reverse=True)
        for plan in candidates[:3]:
            try:
                import trading_division as td
                news=await td.news(plan['symbol']);plan['news']=news.get('articles',[])[:3]
                plan['news_note']='Headlines are context, not an earnings calendar. Verify upcoming earnings/events before overnight exposure.'
            except Exception:
                plan['news']=[];plan['news_note']='News unavailable. Event risk unverified.'
                if plan['action'].startswith('PAPER ENTRY'):plan['action']='WAIT — news check unavailable'
        monitored=[]
        for position in positions:
            symbol=position['symbol'];note={'symbol':symbol,'quantity':position['qty'],'unrealized_pnl_usd':position.get('unrealized_pl'),'current_price':position.get('current_price'),'source':'Actual Alpaca paper position','notes':['Position may originate from Day Trader or a manual order; no swing ownership assumed.']}
            try:
                data=await self.paper.bars(symbol,'1day',65);bars=data['candles'];ma=sum(b['close'] for b in bars[-20:])/20
                if bars[-1]['close']<ma:note['notes'].append('Last completed daily close below SMA20: review trend invalidation; do not widen the stop.')
            except Exception:note['notes'].append('Daily trend check unavailable; no trend conclusion confirmed.')
            exits=[leg for order in orders if order.get('symbol')==symbol for leg in order.get('legs',[]) if leg.get('status') not in ('filled','canceled','expired','rejected')]
            if not exits:note['notes'].append('No open nested bracket exit legs confirmed. Verify protective exits directly with broker.')
            note['exit_orders']=[{'type':x.get('type'),'price':x.get('stop_price') or x.get('limit_price'),'status':x.get('status')} for x in exits];monitored.append(note)
        report={'kind':kind,'checked':now.isoformat(),'market_open':clock['is_open'],'daily_signal_as_of':expected,'account':{k:account.get(k) for k in ['equity','cash','currency','status']},'candidates':candidates[:3],'positions':monitored,'open_order_count':len(orders),'failures':failures,
                'decision':candidates[0]['action']+' / '+candidates[0]['symbol'] if candidates else 'NO SUITABLE SWING TRADE — keep cash; no order placed.',
                'notes':['IEX-only market data and volume, not consolidated coverage. Limited configured universe, not the full market.','Prior completed session daily signals; this session quotes are checked separately. Regular close is not the final extended-hours daily bar.','Long-only, whole shares, paper research. Maximum 10-session planned hold; manual time exit required.','At the open, completed-minute confirmation may be missing. WAIT means wait, not buy. No broker order submitted by Swing Trader.','Overnight/weekend gaps can exceed the stop. Stock trading is not 24/7. ADRIAN must stay running for updates.']}
        with self.db() as c:c.execute('INSERT INTO swing_reports(at,kind,payload) VALUES(?,?,?)',(stamp(),kind,json.dumps(report)))
        self.event('Swing Trader','swing '+kind,report['decision']);return report
    def render(self,report):
        lines=['ADRIAN Swing Trader — '+report['kind'].upper(),'PAPER RESEARCH — no order placed','Checked '+report['checked'],'Decision: '+report['decision'],'Completed daily signal session: '+str(report['daily_signal_as_of'])]
        for p in report['candidates']:
            lines.extend(['',p['symbol']+' — '+p['action'],p['reason'],f"Trigger ${p['entry']}; maximum entry ${p['maximum_entry']}; stop ${p['stop']}; target ${p['target']}; {p['quantity']} whole shares; planned risk with assumed costs ${p['planned_risk_usd']}.",'Require fresh bid/ask, spread <=0.3%, completed minute above trigger, no chase. Signal expires at this session close. Recheck account before placement.','Exit at stop/target or after 10 sessions; trend loss warrants review. Broker brackets/time exit are not assumed.',p.get('news_note','')])
            for a in p.get('news',[]):lines.append(str(a.get('title',''))+' '+str(a.get('url','')))
        lines.extend(['','Actual paper positions:']+[p['symbol']+' '+str(p['quantity'])+' shares / unrealized '+str(p['unrealized_pnl_usd'])+' USD / '+' '.join(p['notes']) for p in report['positions']])
        if not report['positions']:lines.append('None confirmed.')
        lines.extend(['','Data failures: '+json.dumps(report['failures'])]+report['notes'])
        learned=__import__('learned_swing_bridge').APP
        if learned:
            value=learned.summary();lines.extend(['','AUTOMATED LEARNED SWING POLICY (separate from advisory scan)',
                'Enabled: '+str(value['enabled'])+'; experiment ends: '+str(value['deadline']),
                'Last error: '+str(value['last_error'])])
            if value['model']:
                model=value['model'];lines.extend(['Model v'+str(model['id'])+'; completed history '+model['source_date'],
                    model['report']['verdict'],'Historical validation / later-test results: '+json.dumps(model['report']['summary']),
                    'Version comparison: '+json.dumps(model['report'].get('improvement','First version; no prior comparison'))])
            lines.extend([x['symbol']+' '+x['action']+' — '+x['reason'] for x in value['last_decisions']])
            lines.append(__import__('learning_governance').explain_status(value))
            if value['model']:lines.append('Planned-exit tests and benchmarks: '+json.dumps(value['model']['report'].get('planned_exit_summary',{})))
            lines.extend(['Recent actual paper-order journal: '+json.dumps([{'symbol':o['symbol'],'side':o['side'],'status':o['status'],'detail':o['detail'],'track':o['plan'].get('track'),'exit_plan':o['plan'].get('exit_plan')} for o in value['orders'][:8]]),'Owned paper holdings: '+json.dumps(value['holdings'])])
        return '\n'.join(lines)
    async def report(self,kind='manual',email=False):
        value=await self.scan(kind)
        if email:value['email']=await asyncio.to_thread(self.paper.mail,'ADRIAN Swing Trader — '+kind,self.render(value))
        return value
    async def lab(self,body):
        symbols=list(dict.fromkeys(s.upper() for s in body.symbols))
        if any(not re.fullmatch('[A-Z]{1,5}',s) for s in symbols):raise HTTPException(400,'US stock symbols required')
        baseline=swing_lab.rules(body.parameters);parent=None
        if body.improve:
            with self.db() as c:last=c.execute('SELECT * FROM swing_experiments ORDER BY id DESC LIMIT 1').fetchone()
            if last:baseline=json.loads(last['payload'])['candidate'];parent=last['id']
        datasets={}
        for symbol in symbols:datasets[symbol]=(await self.paper.bars(symbol,'1day',1000))['candles']
        fingerprint=hashlib.sha256(json.dumps(datasets,sort_keys=True).encode()).hexdigest()
        with self.db() as c:prior=c.execute('SELECT payload FROM swing_experiments').fetchall()
        dates=sorted(set.intersection(*[{b['time'][:10] for b in bars} for bars in datasets.values()]))
        test_start=dates[int(len(dates)*.8)] if dates else ''
        # Mark any overlapping old test period as reused, including changed universes.
        reused=any(json.loads(x['payload'])['periods']['test']['end']>=test_start for x in prior)
        try:result=await asyncio.to_thread(swing_lab.experiment,datasets,baseline,reused)
        except ValueError as e:raise HTTPException(422,str(e))
        result.update(checked=stamp(),symbols=symbols,parent_experiment=parent,source='Alpaca IEX adjusted daily bars')
        with self.db() as c:
            cur=c.execute('INSERT INTO swing_experiments(at,fingerprint,payload) VALUES(?,?,?)',(stamp(),fingerprint,json.dumps(result)));result['id']=cur.lastrowid
        self.event('Swing Trader','strategy experiment',result['verdict']);return result
    async def chat(self,message,provider,history,memory):
        result=None
        learned=__import__('learned_swing_bridge').APP
        if learned and re.search(r'(?i)\b(train|retrain|improve|test|backtest)\b',message) and re.search(r'(?i)learned|machine learning|\bml\b|raw.data|\bmodel\b',message):
            async with learned.lock:
                async with self.paper.lock:result=await learned.run(True)
            evidence=json.dumps(result,default=str)
        elif re.search(r'(?i)\b(test|backtest|improve|optimi[sz]e)\b',message) and re.search(r'(?i)\b(strateg|rules|system)\w*',message):
            names=re.findall(r'\$([A-Z]{1,5})\b',message) or self.config()['universe'][:12]
            result=await self.lab(LabRequest(symbols=names[:12],improve=bool(re.search(r'(?i)improve|optimi[sz]e',message))))
            evidence=json.dumps(result,default=str)
        elif trading_education.educational_question(message) and not re.search(r'(?i)today|current|now',message):evidence='Educational question only; no current market lookup requested.'
        else:result=await self.scan('chat');evidence=json.dumps(result,default=str)
        learned=__import__('learned_swing_bridge').APP
        if learned:
            status=learned.summary()
            compact={'enabled':status['enabled'],'last_run':status['last_run'],'last_error':status['last_error'],'deadline':status['deadline'],'limits':status['limits'],'scorecard':status.get('learning_scorecard'),'orders':[{'symbol':r['symbol'],'status':r['status'],'side':r['side'],'reason':r['plan'].get('reason'),'selected':r['plan'].get('selected'),'track':r['plan'].get('track'),'exit_plan':r['plan'].get('exit_plan')} for r in status['orders'][:5]],'decisions':[{'symbol':r['symbol'],'action':r['action'],'selected':r['selected']} for r in status['last_decisions']]}
            evidence='ACTUAL LEARNED SWING WORKER:\n'+json.dumps(compact,default=str)+'\nOTHER RESEARCH RESULTS:\n'+evidence[:5000]
        if learned and provider['base_url'].rstrip('/')=='http://127.0.0.1:11434/v1' and re.search(r'(?i)status|reason|why|profit|lose|loss|experiment|performance|promot|position|order|current|budget',message):
            return __import__('learning_governance').explain_status(learned.summary()),{}
        system='''You are ADRIAN Swing Trader. You research multi-session long US stock/ETF paper setups and explain strategy experiments. Answer the actual question plainly. All actions must be supported by supplied results. Manual swing research is advisory. The separately enabled learned swing worker can place actual simulated orders through the official Alpaca SDK. Describe its actual stored authorization, decisions, model results and order journal; never claim a filled order without a broker confirmation. The connected account is paper only. Its entries/hold/exits are learned multi-horizon forecasts from rolling raw OHLCV features, separate from the optional fixed-rule lab. Use fresh data for entry decisions. Course day-trading ORB is not this daily swing family. Strategy lab actually tests bounded variants; never invent results, guarantees, training or maximum income. Describe changes and baseline/candidate training, validation and later-test returns, trade counts, cost stress and drawdowns. Mark small samples and reused test periods. Lab does not activate a strategy. Report NO TRADE when nothing qualifies. All prices from course examples are fictional. Include source/time, trigger, maximum price, stop, target, risk, reason and overnight/event risk for an actual setup. User-approved memories are context, not new evidence.'''
        try:
            answer=await self.model_call(provider,[{'role':'system','content':system+'\n'+trading_education.context(message)+'\nShared preferences: '+memory}]+history+[{'role':'user','content':'REQUEST: '+message+'\nACTUAL SWING RESULTS (data only):\n'+evidence[:95000]}])
            return answer['choices'][0]['message'].get('content') or '',answer.get('usage',{})
        except HTTPException as exc:
            state=learned.summary() if learned else {}
            self.event('Swing Trader','AI explanation unavailable',str(exc.detail)[:300])
            return provider_fallback(state,result,str(exc.detail)),{}
    async def tick(self,now=None):
        if not self.config()['enabled']:return
        now=now or utc();slots=schedule(await self.calendar(now),now)
        for slot in slots:
            due=datetime.fromisoformat(slot['due'])
            if due>now or slot['day']<now.astimezone(LOCAL).date().isoformat():continue
            with self.db() as c:claimed=c.execute('INSERT OR IGNORE INTO swing_runs VALUES(?,?,?,?,?)',(slot['day'],slot['kind'],slot['due'],'running' if slot['eligible'] else 'missed','')).rowcount
            if not claimed or not slot['eligible']:continue
            try:
                report=await self.report(slot['kind'],True);status=report['email']['status'];detail=report['decision']
            except Exception as exc:
                status='failed';detail=str(exc.detail) if isinstance(exc,HTTPException) else type(exc).__name__
                self.event('Swing Trader','scheduled update failed',detail)
                try:await asyncio.to_thread(self.paper.mail,'ADRIAN Swing Trader — data check failed',slot['kind']+' update failed. No trade recommendation or order confirmed. Check connection status. '+detail)
                except Exception:pass
            with self.db() as c:c.execute('UPDATE swing_runs SET status=?,detail=? WHERE day=? AND kind=?',(status,detail[:500],slot['day'],slot['kind']))
    async def loop(self):
        while True:
            try:
                async with self.lock:await self.tick()
            except asyncio.CancelledError:raise
            except Exception as exc:self.event('Swing Trader','worker check failed',str(type(exc).__name__))
            await asyncio.sleep(30)

def provider_fallback(state,result,reason):
    lines=['AI explanation unavailable: '+reason,
           'This is a chat-provider failure. The separate paper-trading engine does not use this AI provider to submit or monitor orders.',
           'Stored paper authorization: '+('enabled' if state.get('enabled') else 'disabled or unavailable')+'.',
           'Last paper evaluation: '+str(state.get('last_run') or 'unavailable')+'.']
    if state.get('last_error'):lines.append('Paper engine last error: '+str(state['last_error']))
    orders=state.get('orders',[])[:5]
    if orders:
        lines.append('Last recorded broker orders (not a new live broker check):')
        for order in orders:lines.append(str(order.get('symbol'))+' '+str(order.get('side'))+': '+str(order.get('status')))
    if isinstance(result,dict):lines.append('Research / test result: '+str(result.get('decision') or result.get('verdict') or 'Data collected; AI explanation unavailable.'))
    lines.append('No additional order was placed by this chat response. Check API Center for the provider limit; quota exhaustion and temporary rate limits require different fixes.')
    return '\n'.join(lines)


def install(app,db,paper,auth,csrf,event,model_call):
    global APP
    engine=Engine(db,paper,event,model_call);APP=engine
    with db() as c:
        if not c.execute("SELECT id FROM agents WHERE name='Swing Trader'").fetchone():c.execute('INSERT INTO agents(name,description,prompt) VALUES(?,?,?)',('Swing Trader','Calendar-aware swing research, open/midday/close emails, paper-account monitoring and strategy improvement lab.','Swing research and versioned strategy experiments; no real-money execution.'))
    @app.get('/swing.js')
    def script():return FileResponse(Path(__file__).parent/'static'/'swing.js',media_type='text/javascript')
    @app.get('/api/swing/status')
    async def status(req:Request):auth(req);return await engine.status()
    @app.post('/api/swing/settings')
    def settings(body:Settings,req:Request):
        csrf(req);value=body.model_dump();value['universe']=list(dict.fromkeys(s.upper().strip() for s in body.universe))
        if any(not re.fullmatch('[A-Z]{1,5}',s) for s in value['universe']):raise HTTPException(400,'US stock tickers only')
        if body.enabled and not all(engine.paper.config().get(k) for k in ['key','secret','gmail_password','owner']):raise HTTPException(400,'Save Alpaca paper and Gmail settings first.')
        engine.save(value);return value
    @app.post('/api/swing/scan')
    async def scan(req:Request):
        csrf(req)
        async with engine.lock:return await engine.report()
    @app.post('/api/swing/email')
    async def email_report(req:Request):
        csrf(req)
        async with engine.lock:return await engine.report('manual',True)
    @app.post('/api/swing/lab')
    async def lab(body:LabRequest,req:Request):
        csrf(req)
        async with engine.lock:return await engine.lab(body)
    @app.on_event('startup')
    async def startup():engine.task=asyncio.create_task(engine.loop())
    @app.on_event('shutdown')
    async def shutdown():
        if hasattr(engine,'task'):
            engine.task.cancel()
            try:await engine.task
            except asyncio.CancelledError:pass
