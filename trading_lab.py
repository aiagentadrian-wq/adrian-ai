"""ADRIAN.AI integrated research and ML lab. Research and paper simulation only."""
import os,re,json,math,time,statistics,hashlib,asyncio
from datetime import datetime,timezone
from urllib.parse import urlparse
from collections import defaultdict
from fastapi import Request,HTTPException
from pydantic import BaseModel,Field
import httpx

UTC=lambda:datetime.now(timezone.utc).isoformat(timespec='seconds')
SYMBOL=re.compile(r'^[A-Z0-9.:-]{1,24}$')
class Train(BaseModel):
    symbol:str=Field(min_length=1,max_length=24)
    horizon:str=Field(pattern='^(day|swing)$')
class Report(Train):
    capital:float=Field(gt=0,le=100000000)
    risk_pct:float=Field(gt=0,le=5)
class Scan(BaseModel):
    symbols:list[str]=Field(min_length=1,max_length=25)
def sym(s):
    s=s.strip().upper()
    if not SYMBOL.fullmatch(s):raise HTTPException(400,'Invalid symbol')
    return s
def safe_float(x):
    try:
        y=float(x)
        return y if math.isfinite(y) else None
    except (ValueError,TypeError):return None

def indicators(c):
    closes=[x['close'] for x in c]; volumes=[x.get('volume') for x in c]; last=closes[-1]
    out={'last_close':last,'last_candle_time':c[-1]['time'],'candles':len(c),'sma20':sum(closes[-20:])/20 if len(c)>=20 else None,'sma50':sum(closes[-50:])/50 if len(c)>=50 else None,'change_1bar_pct':(last/closes[-2]-1)*100 if len(c)>1 else None}
    if len(c)>=15:
        r=[closes[i]/closes[i-1]-1 for i in range(1,len(c))]
        out['realized_volatility_14bar_pct']=statistics.stdev(r[-14:])*100
        gains=[max(0,closes[i]-closes[i-1]) for i in range(len(c)-14,len(c))]
        losses=[max(0,closes[i-1]-closes[i]) for i in range(len(c)-14,len(c))]
        ag=sum(gains)/14;al=sum(losses)/14
        out['rsi14']=100 if al==0 else 100-100/(1+ag/al)
        out['atr14']=sum(max(c[i]['high']-c[i]['low'],abs(c[i]['high']-closes[i-1]),abs(c[i]['low']-closes[i-1])) for i in range(len(c)-14,len(c)))/14
    if len(c)>=20 and all(v is not None for v in volumes[-20:]):out['average_volume_20']=sum(volumes[-20:])/20
    return out

def features(c,h):
    # Features use only current and previous candles; labels use future closes.
    X=[];Y=[];dates=[];start=55
    for i in range(start,len(c)-h):
        closes=[z['close'] for z in c]; p=closes[i]
        if min(closes[i-50:i+1])<=0:continue
        returns=[closes[j]/closes[j-1]-1 for j in range(i-19,i+1)]
        v=[c[j].get('volume') for j in range(i-19,i+1)]
        x=[closes[i]/closes[i-1]-1,closes[i]/closes[i-5]-1,closes[i]/closes[i-20]-1,closes[i]/(sum(closes[i-20:i])/20)-1,closes[i]/(sum(closes[i-50:i])/50)-1,statistics.stdev(returns), (c[i]['high']-c[i]['low'])/p]
        x.append(v[-1]/(sum(v)/20)-1 if all(z is not None for z in v) and sum(v)>0 else 0.)
        X.append(x);Y.append(int(closes[i+h]>p));dates.append(c[i]['time'])
    return X,Y,dates

def train_model(c,horizon):
    try:
        from sklearn.ensemble import RandomForestClassifier
        from sklearn.dummy import DummyClassifier
        from sklearn.metrics import accuracy_score,brier_score_loss,balanced_accuracy_score
    except ImportError:raise HTTPException(503,'Machine learning dependency missing. Install: .\\.venv\\Scripts\\python.exe -m pip install scikit-learn')
    h=1 if horizon=='day' else 5
    X,y,dates=features(c,h)
    if len(X)<110:raise HTTPException(422,f'Insufficient historical data: {len(X)} labeled examples; require at least 110. Data plan/interval may restrict history.')
    cut=int(len(X)*.75)
    if len(set(y[:cut]))<2:raise HTTPException(422,'Training period has only one outcome class')
    model=RandomForestClassifier(n_estimators=120,max_depth=5,min_samples_leaf=8,random_state=42,n_jobs=1,class_weight='balanced_subsample')
    model.fit(X[:cut],y[:cut]); baseline=DummyClassifier(strategy='prior').fit(X[:cut],y[:cut])
    pred=model.predict(X[cut:]);prob=model.predict_proba(X[cut:])[:,list(model.classes_).index(1)]
    bp=baseline.predict(X[cut:]);bprob=baseline.predict_proba(X[cut:])[:,list(baseline.classes_).index(1)]
    # Holdout is contiguous and predictions cannot train on its future labels.
    acc=accuracy_score(y[cut:],pred);bacc=balanced_accuracy_score(y[cut:],pred)
    brier=brier_score_loss(y[cut:],prob);bbrier=brier_score_loss(y[cut:],bprob)
    # A non-overlapping, long-only illustrative trade simulator. Decisions at close, next close entry.
    trade_returns=[];cost_bps=20
    for j in range(cut,len(X)-h,h):
        if prob[j-cut] >= .55:
            idx=55+j
            entry=c[idx+1]['open'];exit_=c[idx+h]['close']
            if entry>0:trade_returns.append(exit_/entry-1-2*cost_bps/10000)
    equity=1.;peak=1.;drawdown=0.
    for r in trade_returns:
        equity*=max(0,1+r);peak=max(peak,equity);drawdown=min(drawdown,equity/peak-1)
    latest=features(c+[dict(c[-1]) for _ in range(h)],h)[0][-1] # latest observed features only; appended rows never enter feature window
    p=float(model.predict_proba([latest])[0][list(model.classes_).index(1)])
    metrics={'holdout_start':dates[cut],'holdout_end':dates[-1],'training_examples':cut,'holdout_examples':len(X)-cut,'accuracy':round(acc,4),'balanced_accuracy':round(bacc,4),'brier':round(brier,4),'baseline_accuracy':round(accuracy_score(y[cut:],bp),4),'baseline_brier':round(bbrier,4),'backtest_trades':len(trade_returns),'illustrative_net_return_pct':round((equity-1)*100,3),'illustrative_max_drawdown_pct':round(drawdown*100,3),'cost_assumption_roundtrip_bps':40}
    qualified=len(y[cut:])>=30 and brier<bbrier and bacc>=.52
    return {'model':'RandomForestClassifier','version':'1.0','horizon':horizon,'prediction_target':('next 15-minute bar close direction' if horizon=='day' else 'five trading-day close direction'),'probability_up':round(p,4),'validation':metrics,'validation_gate_passed':qualified,'decision':'Research-only; model did not pass baseline checks' if not qualified else 'Model cleared preliminary holdout checks; not proof of future profitability','feature_names':['return_1','return_5','return_20','sma20_distance','sma50_distance','volatility_20','bar_range','relative_volume'],'data_end':c[-1]['time'],'trained_utc':UTC(),'limitations':['Single chronological holdout; not full rolling retraining','No corporate-action adjustment independently verified','Price history may be delayed or incomplete','Model probability is not independently calibrated','Paper backtest ignores borrow, taxes, market impact and currency conversion']}

def grouping(articles):
    groups={}
    for a in articles:
        title=(a.get('title') or '').lower();title=re.sub(r'[^a-z0-9 ]',' ',title);words=[w for w in title.split() if w not in {'the','a','an','and','of','on','for','in','to','at','as'}]
        k=' '.join(words[:8]);g=groups.setdefault(k,{'headline':a.get('title'),'sources':set(),'articles':[]})
        g['sources'].add(a.get('source') or 'unknown');g['articles'].append({'source':a.get('source'),'url':a.get('url'),'published_at':a.get('published_at')})
    return [{'headline':v['headline'],'source_names':sorted(v['sources']),'article_count':len(v['articles']),'independence':'not verified; title-based duplicate grouping only','articles':v['articles']} for v in groups.values()]

def init(db):
    with db() as c:
        c.execute('CREATE TABLE IF NOT EXISTS trading_ml_runs(id INTEGER PRIMARY KEY,created_utc TEXT NOT NULL,symbol TEXT NOT NULL,horizon TEXT NOT NULL,results_json TEXT NOT NULL)')
        c.execute('CREATE TABLE IF NOT EXISTS trading_deep_reports(id INTEGER PRIMARY KEY,created_utc TEXT NOT NULL,symbol TEXT NOT NULL,report_json TEXT NOT NULL)')

def install(app,db,auth,csrf,base):
    init(db)
    async def fetch(symbol,horizon,size=400):
        interval='15min' if horizon=='day' else '1day'
        # The free plan may deny 15min or return fewer bars; surface that limitation.
        d=await base.market(symbol,interval,size)
        return d
    @app.post('/api/trading/lab/train')
    async def train(body:Train,req:Request):
        csrf(req);symbol=sym(body.symbol)
        d=await fetch(symbol,body.horizon,500)
        result=train_model(d['candles'],body.horizon)
        result.update({'symbol':symbol,'source':d['source'],'retrieved_utc':d['retrieved_utc'],'feed_note':d['note'],'sample_interval':d['interval']})
        with db() as c:c.execute('INSERT INTO trading_ml_runs(created_utc,symbol,horizon,results_json) VALUES(?,?,?,?)',(UTC(),symbol,body.horizon,json.dumps(result)))
        return result
    @app.get('/api/trading/lab/models')
    def models(req:Request,symbol:str='AAPL'):
        auth(req);symbol=sym(symbol)
        with db() as c:return {'runs':[dict(r) for r in c.execute('SELECT id,created_utc,symbol,horizon,results_json FROM trading_ml_runs WHERE symbol=? ORDER BY id DESC LIMIT 12',(symbol,))]}
    @app.get('/api/trading/lab/evidence')
    async def evidence(req:Request,q:str='AAPL'):
        auth(req);q=sym(q)
        d=await base.news(q)
        return {'retrieved_utc':UTC(),'query':q,'groups':grouping(d['articles']),'warning':'Same story on multiple sites is not independent confirmation. Grouping is approximate, not an original-source verification.'}
    @app.post('/api/trading/lab/scan')
    async def scan(body:Scan,req:Request):
        csrf(req);results=[]
        for s in body.symbols:
            symbol=sym(s)
            try:
                d=await base.market(symbol,'1day',65)
                t=indicators(d['candles'])
                results.append({'symbol':symbol,'technical':t,'retrieved_utc':d['retrieved_utc'],'feed_note':d['note'],'classification':'listed symbol supplied by user; market capitalization and startup status unverified'})
            except HTTPException as e:results.append({'symbol':symbol,'error':e.detail})
            await asyncio.sleep(.25)
        return {'results':results,'note':'Universe scan, not a comprehensive startup or IPO discovery service. Free market API credits may be exhausted by this scan.'}
    @app.get('/api/trading/lab/portfolio')
    def portfolio(req:Request):
        auth(req)
        with db() as c:rows=[dict(x) for x in c.execute('SELECT * FROM trading_paper_journal ORDER BY id')]
        positions={};cashflow=0.
        for x in rows:
            s=x['symbol'];z=positions.setdefault(s,{'quantity':0.,'net_cost':0.,'realized_pnl':0.})
            q=x['quantity'];price=x['price']
            if x['side']=='buy':z['quantity']+=q;z['net_cost']+=q*price;cashflow-=q*price
            else:
                if q>z['quantity']:z.setdefault('warnings',[]).append('Sell exceeds prior long position; short accounting unsupported')
                avg=z['net_cost']/z['quantity'] if z['quantity'] else 0.
                z['realized_pnl']+=(price-avg)*min(q,z['quantity']);z['net_cost']-=avg*min(q,z['quantity']);z['quantity']-=q;cashflow+=q*price
        return {'positions':positions,'net_cashflow':round(cashflow,2),'limitations':['Manual records only','No fees, tax, currency conversion, dividends or current market valuation','Short positions unsupported']}
    @app.post('/api/trading/lab/report')
    async def report(body:Report,req:Request):
        csrf(req);symbol=sym(body.symbol);errors={};sources={}
        async def get(name,fn):
            try:sources[name]=await fn()
            except Exception as e:errors[name]=e.detail if isinstance(e,HTTPException) else type(e).__name__
        await get('market',lambda:fetch(symbol,body.horizon,500))
        if 'market' not in sources:raise HTTPException(502,'Market data required: '+str(errors['market']))
        await get('news',lambda:base.news(symbol))
        await get('fred',base.fred);await get('bank_of_canada',base.boc);await get('statistics_canada',base.statcan)
        # SEC is US-specific; ticker-to-CIK mapping is deliberately not guessed.
        with db() as c:r=c.execute('SELECT results_json FROM trading_ml_runs WHERE symbol=? AND horizon=? ORDER BY id DESC LIMIT 1',(symbol,body.horizon)).fetchone()
        ml=json.loads(r['results_json']) if r else None
        candles=sources['market']['candles'];t=indicators(candles)
        atr=t.get('atr14');price=t['last_close'];stop=2*atr if atr else None
        qty=math.floor(body.capital*body.risk_pct/100/stop) if stop and stop>0 else None
        qty=min(qty,math.floor(body.capital/price)) if qty is not None else None
        risk={'hypothetical_capital':body.capital,'risk_pct':body.risk_pct,'price':price,'atr14':atr,'illustrative_stop_distance_2atr':stop,'illustrative_max_whole_shares':qty,'currency_warning':'Capital and quote must share currency; no CAD/USD conversion performed','not_an_order':True,'not_a_personalized_allocation':True}
        report={'symbol':symbol,'horizon':body.horizon,'generated_utc':UTC(),'market':{'source':sources['market']['source'],'retrieved_utc':sources['market']['retrieved_utc'],'last_bar':candles[-1]['time'],'interval':sources['market']['interval'],'meta':sources['market']['meta']},'technical':t,'evidence':grouping(sources['news']['articles']) if 'news' in sources else [],'economy':{k:v for k,v in sources.items() if k in ('fred','bank_of_canada','statistics_canada')},'model':ml,'risk_scenario':risk,'filings':'Ticker-to-CIK not verified; use SEC EDGAR panel with confirmed CIK. Canadian SEDAR+ automated ingestion not integrated.','errors':errors,'independent_review':{'data_freshness':'Check each source observation and publication date','news_independence':'Not established by syndication counts','model_validation':'No trained model' if not ml else ('Preliminary holdout passed' if ml['validation_gate_passed'] else 'Did not beat validation gate'),'missing':['Verified ticker-to-CIK mapping','Earnings calendar and company press-release ingestion','Corporate action adjustments','Live quote entitlement','Walk-forward retraining and probability calibration']},'decision':'Research scenario only; no automated buy/sell order or assured return'}
        with db() as c:c.execute('INSERT INTO trading_deep_reports(created_utc,symbol,report_json) VALUES(?,?,?)',(UTC(),symbol,json.dumps(report)))
        return report
