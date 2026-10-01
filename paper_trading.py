"""Alpaca paper-only broker, Gmail approvals and opt-in daily Manager reporting."""
import asyncio, os, email, imaplib, json, math, re, secrets, smtplib, ssl
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from email.utils import parseaddr
from zoneinfo import ZoneInfo
import httpx
from pathlib import Path
from fastapi import HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

PAPER='https://paper-api.alpaca.markets'
DATA='https://data.alpaca.markets'
UTC=timezone.utc
APP=None

def utc(): return datetime.now(UTC)
def iso(): return utc().isoformat()
def first_reply(message):
    parts=message.walk() if message.is_multipart() else [message]
    for p in parts:
        if p.get_content_type()=='text/plain' and p.get_content_disposition()!='attachment':
            text=p.get_payload(decode=True).decode(p.get_content_charset() or 'utf-8',errors='replace')
            return next((x.strip().upper() for x in text.splitlines() if x.strip()),'')
    return ''

def approval_matches(message, proposal, owner):
    # Match the private thread ID and exact mailbox. Require Gmail's inbound DKIM
    # assessment; unauthenticated/spoofed From headers do not authorize orders.
    sender=parseaddr(message.get('From',''))[1].lower()
    headers=message.get_all('Authentication-Results',[])
    authenticated=any(re.match(r'\s*mx\.google\.com\s*;',h,re.I) and
                      re.search(r'\bdkim=pass\b',h,re.I) and
                      re.search(r'header\.(?:i|d)\s*=\s*(?:@)?gmail\.com\b',h,re.I) for h in headers[:1])
    refs=' '.join(message.get_all('In-Reply-To',[])+message.get_all('References',[]))
    return sender==owner.lower() and authenticated and proposal['message_id'] in refs and first_reply(message) in ('YES','NO')

def clean_plan(plan):
    symbol=str(plan.get('symbol','')).upper()
    if not re.fullmatch(r'[A-Z]{1,5}',symbol):raise ValueError('US stock ticker required')
    values={k:float(plan[k]) for k in ('entry','stop','target')}
    if not all(math.isfinite(v) and v>0 for v in values.values()):raise ValueError('Finite positive prices required')
    if not values['stop']<values['entry']<values['target']:raise ValueError('Stop < entry < target required')
    if (values['entry']-values['stop'])/values['entry']>.05:raise ValueError('Stop distance exceeds 5%')
    if (values['target']-values['entry'])/(values['entry']-values['stop'])<1.8:raise ValueError('Reward/risk below 1.8')
    return dict(symbol=symbol,**{k:round(v,2) for k,v in values.items()})

class Connection(BaseModel):
    key:str=Field(default='',max_length=200)
    secret:str=Field(default='',max_length=200)
    gmail_password:str=Field(default='',max_length=200)
    owner:str=''
    approval_enabled:bool=False
    daily_reports:bool=False
    daily_proposals:bool=False
    risk_percent:float=Field(default=.25,gt=0,le=1)

class Engine:
    def __init__(self,db,cipher,send,event,model_call):
        self.db,self.cipher,self.send,self.event,self.model_call=db,cipher,send,event,model_call
        self.lock=asyncio.Lock()
        with db() as c:
            c.execute('CREATE TABLE IF NOT EXISTS paper_settings (id INTEGER PRIMARY KEY CHECK(id=1), payload TEXT NOT NULL)')
            c.execute('CREATE TABLE IF NOT EXISTS paper_proposals (id TEXT PRIMARY KEY, at TEXT, expires TEXT, status TEXT, message_id TEXT, payload TEXT, broker_id TEXT, detail TEXT)')
            c.execute('CREATE TABLE IF NOT EXISTS paper_runs (kind TEXT, day TEXT, status TEXT, detail TEXT, PRIMARY KEY(kind,day))')
    def config(self):
        with self.db() as c:r=c.execute('SELECT payload FROM paper_settings WHERE id=1').fetchone()
        return json.loads(r['payload']) if r else {}
    def save(self,s):
        with self.db() as c:c.execute('INSERT INTO paper_settings(id,payload) VALUES(1,?) ON CONFLICT(id) DO UPDATE SET payload=excluded.payload',(json.dumps(s),))
    def secret(self,name):
        value=self.config().get(name)
        return self.cipher.decrypt(value.encode()).decode() if value else ''
    def capabilities(self):
        s=self.config()
        with self.db() as c:
            exists=c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='service_health'").fetchone()
            health=dict(c.execute("SELECT status,checked,detail FROM service_health WHERE service='alpaca'").fetchone() or {}) if exists else {}
        return {'mode':'PAPER ONLY','broker':'Alpaca','keys_saved':bool(s.get('key') and s.get('secret')),'last_actual_connection_check':health,'gmail_approval_enabled':bool(s.get('approval_enabled')),'entry_workflow':'Find & email a paper proposal, then reply YES in its exact thread before expiry. Execution rechecks fresh data, risk and market-open status.','exit_workflow':'Approved limit-entry bracket includes broker-managed stop-loss and take-profit exits activated after entry fill. These exits need no second approval.','chat_can_submit_orders':False,'real_money_supported':False,'journal':[{k:v for k,v in x.items() if k!='plan'} for x in self.summary()['proposals'][:5]]}
    async def broker(self,path,method='GET',payload=None):
        # Base URL is a constant: no setting or model can switch to live trading.
        key,secret=self.secret('key'),self.secret('secret')
        if not key or not secret:raise HTTPException(400,'Save Alpaca paper keys in Settings → Paper trading & Gmail.')
        async with httpx.AsyncClient(timeout=20) as c:
            r=await c.request(method,PAPER+path,headers={'APCA-API-KEY-ID':key,'APCA-API-SECRET-KEY':secret},json=payload)
        import dashboard_core
        dashboard_core.observe('alpaca',*dashboard_core.classify(r.status_code))
        if r.status_code>=400:raise HTTPException(502,f'Alpaca paper request failed (HTTP {r.status_code}); check paper keys and account access.')
        return r.json() if r.content else {}
    async def snapshot(self,symbol):
        async with httpx.AsyncClient(timeout=15) as c:
            r=await c.get(DATA+'/v2/stocks/'+symbol+'/snapshot',params={'feed':'iex'},headers={'APCA-API-KEY-ID':self.secret('key'),'APCA-API-SECRET-KEY':self.secret('secret')})
        if r.status_code!=200:raise HTTPException(502,'Alpaca IEX market data unavailable; approval skipped.')
        return r.json()
    async def bars(self,symbol,interval,size):
        frames={'1day':'1Day','15min':'15Min','1h':'1Hour','1min':'1Min','5min':'5Min'}
        if interval not in frames:raise HTTPException(400,'Unsupported Alpaca interval')
        size=min(max(int(size),2),1000)
        days=max(365*5 if interval=='1day' else 90,10)
        start=(utc()-timedelta(days=days)).isoformat()
        async with httpx.AsyncClient(timeout=25) as c:
            r=await c.get(DATA+'/v2/stocks/'+symbol+'/bars',params={'feed':'iex','timeframe':frames[interval],'start':start,'limit':size+2,'sort':'desc','adjustment':'all'},headers={'APCA-API-KEY-ID':self.secret('key'),'APCA-API-SECRET-KEY':self.secret('secret')})
        if r.status_code!=200:raise HTTPException(502,f'Alpaca IEX candles unavailable (HTTP {r.status_code}). No silent source substitution.')
        import trading_guard
        raw=[{'time':x['t'],'open':x['o'],'high':x['h'],'low':x['l'],'close':x['c'],'volume':x['v']} for x in reversed(r.json().get('bars',[]))]
        try:bars,quality=trading_guard.validate_bars(raw,interval)
        except ValueError as e:raise HTTPException(502,str(e))
        return {'source':'Alpaca IEX','retrieved_utc':iso(),'symbol':symbol,'interval':interval,'meta':{'exchange':'IEX','currency':'USD'},'candles':bars[-size:],'quality':quality,'timestamp_timezone':'UTC','note':'IEX-only US stock prices and volume, not consolidated market coverage. Adjusted historical bars. Paper simulation is not proof of real execution.'}
    def summary(self):
        with self.db() as c:
            rows=[dict(r) for r in c.execute('SELECT id,at,expires,status,payload,broker_id,detail FROM paper_proposals ORDER BY at DESC LIMIT 20')]
            runs=[dict(r) for r in c.execute('SELECT * FROM paper_runs ORDER BY day DESC LIMIT 8')]
        for r in rows:r['plan']=json.loads(r.pop('payload'))
        return {'mode':'PAPER ONLY','proposals':rows,'daily_runs':runs,'note':'Experimental strategy. Historical tests did not establish a profitable edge. No live orders are supported.'}
    def mail(self,subject,text,message_id=None):
        # Approval-thread mail keeps the authenticated owner identity. Routine
        # reports use the user's configured report inbox, not the bot login.
        if not message_id and __import__('os').getenv('REPORT_TO'):
            result=self.send(subject,text)
            if result.get('status')!='accepted_by_smtp':raise HTTPException(502,'Report sender did not confirm acceptance; check Reports & Email.')
            return result
        s=self.config();owner=s.get('owner','');pwd=self.secret('gmail_password')
        if not pwd:raise HTTPException(400,'Save a Gmail app password first. Your normal Gmail password is not used.')
        msg=EmailMessage();msg['From']=owner;msg['To']=owner;msg['Subject']=subject
        if message_id:msg['Message-ID']=message_id
        msg.set_content(text)
        try:
            with smtplib.SMTP_SSL('smtp.gmail.com',465,timeout=20,context=ssl.create_default_context()) as c:
                c.login(owner,pwd);refused=c.send_message(msg)
                if refused:raise RuntimeError('Recipient refused')
        except Exception:
            import dashboard_core
            dashboard_core.observe('gmail','error','Gmail send failed. Check app password and account access.')
            raise HTTPException(502,'Gmail send failed; delivery is not confirmed.')
        with self.db() as c:c.execute('INSERT INTO email_history(at,subject,body,recipient,sender,status,error) VALUES(?,?,?,?,?,?,?)',(iso(),subject,text,owner,owner,'accepted_by_smtp',None))
        self.event('Day Trader','paper email accepted by SMTP',subject)
        return {'status':'accepted_by_smtp','note':'SMTP acceptance does not prove inbox delivery.'}
    def update(self,id,status,detail,broker_id=None):
        with self.db() as c:c.execute('UPDATE paper_proposals SET status=?,detail=?,broker_id=COALESCE(?,broker_id) WHERE id=?',(status,detail,broker_id,id))
        self.event('Day Trader','paper '+status,detail[:180])
    async def propose(self,query='Compare candidates'):
        import trading_chat_bridge as bridge
        import trading_guard
        import paper_experiment
        if paper_experiment.APP and paper_experiment.APP.config().get('enabled'):
            return {'status':'no_trade','reason':'The authorized automatic paper experiment is running. Separate email entry proposals are paused to avoid conflicting orders.'}
        if not self.config().get('approval_enabled'):raise HTTPException(400,'Enable Gmail approval monitoring first.')
        if 'last_uid' not in self.config():await self.poll()
        evidence=await bridge.research(query,self.db)
        ranked=evidence.get('ranking',[])
        if not ranked:return {'status':'no_trade','reason':'No candidate has sufficient research evidence.'}
        candidate=next(x for x in evidence['results'] if x['symbol']==ranked[0]['symbol'])
        p=candidate.get('hypothetical_plan')
        if not p or candidate.get('errors') or ranked[0]['screen_score']<70:
            return {'status':'no_trade','reason':'The strongest watch candidate failed evidence or screening checks. No proposal sent.'}
        plan=clean_plan({'symbol':candidate['symbol'],'entry':p['breakout_reference'],'stop':p['stop_reference'],'target':p['target_2R']})
        clock=await self.broker('/v2/clock')
        if not clock['is_open']:return {'status':'no_trade','reason':'Market closed. No short-lived approval sent.'}
        account=await self.broker('/v2/account')
        if account.get('trading_blocked') or account.get('account_blocked') or account.get('currency')!='USD':raise HTTPException(400,'Paper account is blocked or not USD.')
        positions=await self.broker('/v2/positions');orders=await self.broker('/v2/orders?status=open')
        if positions or orders:return {'status':'no_trade','reason':'An existing paper position or order must be resolved before another proposal.'}
        with self.db() as c:
            pending=c.execute("SELECT id FROM paper_proposals WHERE status IN ('pending','executing','uncertain') AND expires>?",(iso(),)).fetchone()
        with self.db() as c:unresolved=c.execute("SELECT id FROM paper_proposals WHERE status IN ('executing','uncertain')").fetchone()
        if pending or unresolved:return {'status':'no_trade','reason':'A proposal or unresolved submission already exists.'}
        equity=float(account['equity']);loss=max(0,float(account.get('last_equity',equity))-equity)
        limit=round(plan['entry']*1.002,2)
        size=trading_guard.size_position(equity,limit,plan['stop'],self.config().get('risk_percent',.25),loss,2,0)
        shares=min(size['shares'],int(float(account.get('cash',0))/limit))
        if shares<1:return {'status':'no_trade','reason':'Risk or cash limits leave no whole-share position.'}
        plan.update(qty=shares,reason=bridge.briefing(evidence),risk_percent=self.config().get('risk_percent',.25),evidence=evidence,
                    confirmation='Fresh IEX trade and completed minute bar above entry, nonzero volume, price no more than 0.2% above entry. IEX is one venue, not the whole market.')
        # AI explains sourced evidence; it cannot choose executable parameters.
        with self.db() as c:provider=c.execute('SELECT * FROM providers ORDER BY id LIMIT 1').fetchone()
        if provider:
            try:
                result=await self.model_call(provider,[{'role':'system','content':'Explain this experimental paper proposal in at most 120 words. Use supplied evidence only. Never claim a profitable edge or completed order. Explain why this candidate leads and uncertainty. The numeric plan is fixed.'},{'role':'user','content':json.dumps(plan,default=str)[:30000]}])
                plan['ai_explanation']=result['choices'][0]['message'].get('content','')
            except Exception:plan['ai_explanation']='AI explanation unavailable; source-grounded screening rationale is included.'
        id=secrets.token_hex(16);mid='<adrian-paper-'+id+'@gmail.com>';expires=(utc()+timedelta(minutes=10)).isoformat()
        with self.db() as c:c.execute('INSERT INTO paper_proposals VALUES(?,?,?,?,?,?,?,?)',(id,iso(),expires,'mail_pending',mid,json.dumps(plan),None,''))
        text=f"PAPER ONLY — simulated money. Experimental, not proven profitable.\n\n{plan.get('ai_explanation',plan['reason'])}\n\n{plan['symbol']}: buy {shares} whole shares. Entry reference ${plan['entry']}; maximum limit ${round(plan['entry']*1.002,2)}; stop ${plan['stop']}; target ${plan['target']}.\n{plan['confirmation']}\nApproval expires {expires}.\n\nReply YES as the first line to authorize this paper entry and its bracket stop/target exits. Reply NO to decline. A stale setup will be skipped. Replies never authorize real-money orders.\n\n{plan['reason']}"
        try:await asyncio.to_thread(self.mail,'ADRIAN paper proposal '+plan['symbol'],text,mid)
        except Exception:self.update(id,'mail_failed','Proposal email failed; no order allowed.');raise
        self.update(id,'pending','Proposal emailed; waiting for authenticated YES reply.')
        return {'status':'pending','id':id,'expires':expires,'plan':plan}
    async def execute(self,row):
        id=row['id'];plan=json.loads(row['payload'])
        if not self.config().get('approval_enabled'):return
        if datetime.fromisoformat(row['expires'])<=utc():self.update(id,'expired','Approval arrived after expiry.');return
        # Claim exactly once before any network request. Uncertain submissions are
        # reconciled by client_order_id, never blindly submitted a second time.
        with self.db() as c:
            changed=c.execute("UPDATE paper_proposals SET status='executing' WHERE id=? AND status='pending'",(id,)).rowcount
        if not changed:return
        try:
            clock=await self.broker('/v2/clock');a=await self.broker('/v2/account')
            if not clock['is_open'] or a.get('trading_blocked') or a.get('account_blocked'):raise ValueError('Market closed or account blocked')
            positions=await self.broker('/v2/positions');orders=await self.broker('/v2/orders?status=open')
            if positions or orders:raise ValueError('Existing paper position/order prevents another entry')
            snap=await self.snapshot(plan['symbol']);trade=snap.get('latestTrade',{});bar=snap.get('minuteBar',{})
            for item in (trade,bar):
                age=(utc()-datetime.fromisoformat(item['t'].replace('Z','+00:00'))).total_seconds()
                if not (60<=age<=180 if item is bar else 0<=age<=120):raise ValueError('Quote stale or minute bar incomplete/stale')
            price=float(trade['p']);limit=round(plan['entry']*1.002,2)
            if not plan['entry']<=price<=limit or float(bar['c'])<plan['entry'] or float(bar['v'])<=0:raise ValueError('Breakout confirmation failed or price moved beyond approved limit')
            equity=float(a['equity']);risk=plan['qty']*(limit-plan['stop']);loss=max(0,float(a.get('last_equity',equity))-equity)
            if risk>equity*plan['risk_percent']/100 or loss+risk>equity*.02 or plan['qty']*limit>float(a.get('cash',0)):raise ValueError('Fresh risk/cash check failed')
            payload={'symbol':plan['symbol'],'qty':str(plan['qty']),'side':'buy','type':'limit','limit_price':str(limit),'time_in_force':'day','order_class':'bracket','take_profit':{'limit_price':str(plan['target'])},'stop_loss':{'stop_price':str(plan['stop'])},'client_order_id':'adrian-'+id}
        except Exception as e:
            self.update(id,'skipped',str(e.detail) if isinstance(e,HTTPException) else str(e));return
        try:
            order=await self.broker('/v2/orders','POST',payload)
            self.update(id,'submitted','Paper order accepted; fill not yet confirmed.',order['id'])
        except Exception:
            self.update(id,'uncertain','Submission outcome unknown. Reconcile before any new proposal.');return
        await asyncio.to_thread(self.mail,'ADRIAN paper order submitted',f"{plan['symbol']}: paper order {order['id']} submitted. Broker status: {order['status']}. This is not fill confirmation. See Trading Division → Alpaca paper account.")
    def read_replies(self):
        s=self.config();owner=s['owner'];pwd=self.secret('gmail_password');found=[]
        with imaplib.IMAP4_SSL('imap.gmail.com',993,ssl_context=ssl.create_default_context(),timeout=20) as c:
            c.login(owner,pwd);c.select('INBOX',readonly=True)
            validity=str(c.response('UIDVALIDITY')[1])
            typ,data=c.uid('search',None,'ALL')
            if typ!='OK':raise RuntimeError('Gmail inbox search failed')
            uids=[int(x) for x in data[0].split()]
            if 'last_uid' not in s or s.get('uidvalidity')!=validity:
                current=self.config()
                if current.get('owner')==owner:
                    current.update(last_uid=max(uids,default=0),uidvalidity=validity);self.save(current)
                return []
            for uid in [x for x in uids if x>s['last_uid']][:50]:
                typ,content=c.uid('fetch',str(uid),'(BODY.PEEK[])')
                if typ!='OK':break
                raw=next((x[1] for x in content if isinstance(x,tuple)),b'')
                if len(raw)<=2_000_000:found.append(email.message_from_bytes(raw))
                s['last_uid']=uid
            current=self.config()
            if current.get('owner')==owner:
                current.update(last_uid=s['last_uid'],uidvalidity=validity);self.save(current)
        return found
    async def poll(self):
        messages=await asyncio.to_thread(self.read_replies)
        import dashboard_core
        dashboard_core.observe('gmail','verified','Gmail inbox read succeeded; authenticated replies are checked against exact proposal threads.')
        with self.db() as c:rows=[dict(r) for r in c.execute("SELECT * FROM paper_proposals WHERE status='pending'")]
        for row in rows:
            if datetime.fromisoformat(row['expires'])<utc():self.update(row['id'],'expired','No timely approval.');continue
            for msg in messages:
                if approval_matches(msg,row,self.config()['owner']):
                    if first_reply(msg)=='NO':self.update(row['id'],'declined','Owner declined proposal.')
                    else:await self.execute(row)
                    break
        return {'checked_messages':len(messages),'status':'checked'}
    async def reconcile(self):
        with self.db() as c:rows=[dict(r) for r in c.execute("SELECT * FROM paper_proposals WHERE status IN ('submitted','uncertain','executing','filled','partially_filled')")]
        for row in rows:
            try:
                order=await self.broker('/v2/orders:by_client_order_id?client_order_id=adrian-'+row['id'])
                status=order['status'];detail=f"Broker status {status}; filled {order.get('filled_qty','0')} shares at {order.get('filled_avg_price') or 'unfilled'}."
                mapped=status if status in ('filled','partially_filled','canceled','expired','rejected') else 'submitted'
                if mapped!=row['status'] or detail!=row['detail']:
                    self.update(row['id'],mapped,detail,order['id'])
                    if mapped in ('filled','partially_filled','canceled','expired','rejected'):await asyncio.to_thread(self.mail,'ADRIAN paper order update',detail+'\n'+json.loads(row['payload'])['symbol'])
            except Exception:pass
    async def report(self):
        try:
            a=await self.broker('/v2/account');p=await self.broker('/v2/positions');o=await self.broker('/v2/orders?status=all&limit=20')
            import swing_trading,paper_experiment,learned_swing_bridge
            shared={'learned_swing':learned_swing_bridge.APP.summary() if learned_swing_bridge.APP else None,'swing':(await swing_trading.APP.status()),'machine_learning_experiment':paper_experiment.APP.summary()}
            text='Manager daily paper-trading report\nPAPER ONLY — not real money.\n'+json.dumps({'equity':a['equity'],'cash':a['cash'],'positions':[{'symbol':x['symbol'],'qty':x['qty'],'unrealized_pl':x['unrealized_pl']} for x in p],'orders':[{'symbol':x['symbol'],'status':x['status'],'filled_qty':x['filled_qty'],'filled_avg_price':x.get('filled_avg_price')} for x in o],'approval_journal':self.summary(),'shared_trading_work':shared},indent=2)
        except Exception:text='Manager daily paper-trading report\nBroker unavailable; no balances or fills confirmed.\n'+json.dumps(self.summary(),indent=2)
        result=await asyncio.to_thread(self.mail,'ADRIAN Manager — daily paper trading',text[:45000])
        self.event('Manager','daily paper report',result['status']);return result
    async def loop(self):
        while True:
            try:
                async with self.lock:
                    s=self.config()
                    if s.get('approval_enabled'):await self.poll();await self.reconcile()
                    local=utc().astimezone(ZoneInfo('America/Toronto'));day=local.date().isoformat()
                    for kind,enabled,due in [('proposal',s.get('daily_proposals'),local.weekday()<5 and (local.hour,local.minute)>=(9,45) and local.hour<10),('report',s.get('daily_reports'),(local.hour,local.minute)>=(17,0))]:
                        if not enabled or not due:continue
                        with self.db() as c:
                            claimed=c.execute('INSERT OR IGNORE INTO paper_runs VALUES(?,?,?,?)',(kind,day,'running','')).rowcount
                        if claimed:
                            try:
                                result=await self.propose() if kind=='proposal' else await self.report()
                                if kind=='proposal' and result['status']=='no_trade':await asyncio.to_thread(self.mail,'ADRIAN paper trading — no suitable trade',result['reason'])
                                status=result.get('status','completed');detail=json.dumps(result,default=str)[:300]
                            except Exception:status='failed';detail='Daily task failed; check connection status. No order or email completion is assumed.'
                            with self.db() as c:c.execute('UPDATE paper_runs SET status=?,detail=? WHERE kind=? AND day=?',(status,detail,kind,day))
            except asyncio.CancelledError:raise
            except Exception:
                import dashboard_core
                dashboard_core.observe('gmail','error','Approval worker failed. Check Gmail settings; no approval is assumed.')
            await asyncio.sleep(30)

def install(app,db,cipher,auth,csrf,send,event,model_call):
    global APP
    engine=Engine(db,cipher,send,event,model_call);APP=engine
    with db() as c:
        c.execute("UPDATE agents SET description=? WHERE name='Day Trader' AND description IN (?,?)",('Market research and approval-based Alpaca paper entries with broker-managed stop/target exits.','Research-only market analyst.','Research-only market analyst; examines supplied market data and trading setups.'))
    @app.get('/paper.js')
    def javascript():return FileResponse(Path(__file__).parent/'static'/'paper.js',media_type='text/javascript')
    @app.get('/api/paper/settings')
    def settings(req:Request):
        auth(req);s=engine.config()
        return {k:v for k,v in s.items() if k not in ('key','secret','gmail_password','last_uid','uidvalidity')}|{'key_saved':bool(s.get('key')),'secret_saved':bool(s.get('secret')),'gmail_saved':bool(s.get('gmail_password')),'mode':'PAPER ONLY','owner':s.get('owner',os.getenv('SMTP_USER','') if os.getenv('SMTP_USER','').endswith('@gmail.com') else '')}
    @app.post('/api/paper/settings')
    def save(body:Connection,req:Request):
        csrf(req)
        if not re.fullmatch(r'[a-zA-Z0-9._%+\-]+@gmail\.com',body.owner):raise HTTPException(400,'A Gmail approval mailbox is required.')
        s=engine.config();old_owner=s.get('owner');s.update(body.model_dump(exclude={'key','secret','gmail_password'}))
        if body.daily_proposals and not body.approval_enabled:raise HTTPException(400,'Daily proposals require Gmail reply checking to be enabled.')
        if old_owner and old_owner!=body.owner:
            s.pop('gmail_password',None);s.pop('last_uid',None)
        for name in ('key','secret','gmail_password'):
            value=getattr(body,name).strip()
            if value:s[name]=cipher.encrypt(value.encode()).decode()
        if (body.approval_enabled or body.daily_reports or body.daily_proposals) and not all(s.get(k) for k in ('key','secret','gmail_password')):raise HTTPException(400,'Save both paper keys and Gmail app password before enabling automation.')
        engine.save(s);return settings(req)
    @app.get('/api/paper/account')
    async def account(req:Request):
        auth(req)
        a=await engine.broker('/v2/account');positions=await engine.broker('/v2/positions');orders=await engine.broker('/v2/orders?status=all&limit=30&nested=true')
        return {'mode':'PAPER ONLY','checked':iso(),'account':{k:a.get(k) for k in ('equity','cash','buying_power','last_equity','currency','status','trading_blocked')},'positions':positions,'orders':orders,'journal':engine.summary()}
    @app.get('/api/paper/journal')
    def journal(req:Request):auth(req);return engine.summary()
    @app.post('/api/paper/check-gmail')
    async def check(req:Request):
        csrf(req)
        async with engine.lock:return await engine.poll()
    @app.post('/api/paper/propose')
    async def propose(req:Request):
        csrf(req)
        if not engine.config().get('approval_enabled'):raise HTTPException(400,'Enable Gmail approval checking before emailing proposals.')
        async with engine.lock:return await engine.propose()
    @app.post('/api/paper/report')
    async def report(req:Request):csrf(req);return await engine.report()
    @app.on_event('startup')
    async def startup():engine.task=asyncio.create_task(engine.loop())
    @app.on_event('shutdown')
    async def shutdown():
        if hasattr(engine,'task'):
            engine.task.cancel()
            try:await engine.task
            except asyncio.CancelledError:pass
