"""Fail-closed candle checks, bounded paper risk and causal strategy replay."""
import math
from datetime import datetime,timezone,timedelta

def validate_bars(candles,interval,now=None):
    now=now or datetime.now(timezone.utc)
    minutes={'15min':15,'1h':60,'1min':1,'5min':5}.get(interval)
    clean=[];previous=None;forming=0
    for bar in candles:
        b=dict(bar)
        values=[float(b[k]) for k in ('open','high','low','close')]
        if not all(math.isfinite(x) and x>0 for x in values):raise ValueError('Nonfinite or nonpositive price')
        o,h,l,c=values
        if l>min(o,c) or h<max(o,c) or l>h:raise ValueError('Inconsistent candle range')
        if b.get('volume') is not None and (not math.isfinite(float(b['volume'])) or float(b['volume'])<0):raise ValueError('Invalid volume')
        dt=datetime.fromisoformat(b['time'].replace('Z','+00:00'))
        if dt.tzinfo is None:dt=dt.replace(tzinfo=timezone.utc)
        if previous is not None and dt<=previous:raise ValueError('Duplicate or out-of-order candle')
        previous=dt
        if dt>now+timedelta(seconds=5):raise ValueError('Future candle timestamp')
        # Intraday request explicitly uses UTC. Daily dates remain exchange dates;
        # exclude today's daily candle conservatively rather than guessing market close.
        if (minutes and dt+timedelta(minutes=minutes)>now) or (interval=='1day' and b['time'][:10]>=now.date().isoformat()):
            forming+=1;continue
        clean.append(b)
    if len(clean)<2:raise ValueError('Insufficient completed candles')
    last=datetime.fromisoformat(clean[-1]['time'].replace('Z','+00:00'))
    if last.tzinfo is None:last=last.replace(tzinfo=timezone.utc)
    age=(now-last-timedelta(minutes=minutes or 0)).total_seconds()
    return clean,{'checked_utc':now.isoformat(),'completed_bars':len(clean),'excluded_incomplete_bars':forming,
        'last_bar':clean[-1]['time'],'age_seconds':max(0,round(age)),
        'recent_intraday_bar':bool(minutes and 0<=age<=minutes*60+120),
        'live_entitlement_verified':False,'note':'Recent bars do not establish real-time entitlement or bid/ask freshness.'}

def size_position(equity,entry,stop,risk_percent=0.5,daily_loss=0,daily_limit_percent=2,exposure=0):
    values=(equity,entry,stop,risk_percent,daily_loss,daily_limit_percent,exposure)
    if not all(math.isfinite(float(x)) for x in values):raise ValueError('Nonfinite risk input')
    if equity<=0 or not 0<stop<entry or not 0<risk_percent<=1 or not 0<daily_limit_percent<=5 or min(daily_loss,exposure)<0:raise ValueError('Invalid risk inputs')
    limit=equity*daily_limit_percent/100
    remaining=max(0,limit-daily_loss)
    budget=min(equity*risk_percent/100,remaining)
    shares=max(0,min(math.floor(budget/(entry-stop)),math.floor(max(0,equity-exposure)/entry)))
    return {'shares':shares,'risk_budget':round(budget,2),'stop_risk':round(shares*(entry-stop),2),
        'position_value':round(shares*entry,2),'daily_loss_remaining':round(remaining,2),
        'decision':'PAPER ONLY' if shares else 'SKIP: loss limit, exposure or minimum size prevents a position',
        'assumptions':'Long only, whole shares, no leverage, same account/price currency. Stop losses can be exceeded by gaps. Fees not included in sizing.'}

def replay(candles,cost_bps=20,window=20,start=60,end=None):
    """Signal on a completed close, enter the NEXT open, pessimistic same-bar exits."""
    end=min(end or len(candles),len(candles));trades=[];i=max(start,window+1)
    while i<end-1:
        prior=candles[i-window:i];signal=candles[i]
        reference=max(b['high'] for b in prior)
        if signal['close']<=reference:i+=1;continue
        ranges=[max(b['high']-b['low'],abs(b['high']-candles[i-window+j-1]['close']),abs(b['low']-candles[i-window+j-1]['close'])) for j,b in enumerate(prior)]
        atr=sum(ranges)/len(ranges)
        entry=candles[i+1]['open'];stop=signal['close']-atr
        risk=entry-stop
        if atr<=0 or risk<=0 or risk/entry>0.05:i+=1;continue
        target=entry+2*risk;exit_price=None;exit_index=min(i+5,end-1);reason='time exit'
        for j in range(i+1,exit_index+1):
            b=candles[j]
            if b['open']<=stop:exit_price=b['open'];exit_index=j;reason='gap stop';break
            if b['low']<=stop:exit_price=stop;exit_index=j;reason='stop (first if target also touched)';break
            if b['high']>=target:exit_price=target;exit_index=j;reason='target';break
        if exit_price is None:exit_price=candles[exit_index]['close']
        net=exit_price/entry-1-2*cost_bps/10000
        trades.append({'signal_time':signal['time'],'entry_time':candles[i+1]['time'],'exit_time':candles[exit_index]['time'],
            'entry':entry,'exit':exit_price,'stop':stop,'target':target,'net_return':net,'reason':reason})
        i=exit_index+1
    returns=[t['net_return'] for t in trades];equity=peak=1.;drawdown=0
    for r in returns:equity*=max(0,1+r);peak=max(peak,equity);drawdown=min(drawdown,equity/peak-1)
    gross=sum(r for r in returns if r>0);loss=-sum(r for r in returns if r<0)
    return {'trades':trades,'trade_count':len(trades),'win_rate':sum(r>0 for r in returns)/len(returns) if returns else None,
        'profit_factor':gross/loss if loss else None,'compound_return_pct':(equity-1)*100,'max_drawdown_pct':drawdown*100,
        'roundtrip_cost_bps':2*cost_bps}

def evaluate(candles):
    if len(candles)<160:raise ValueError('Require at least 160 completed bars for chronological evaluation')
    start=60;folds=[]
    for a in range(start,len(candles)-1,50):
        b=min(a+50,len(candles));r=replay(candles,start=a,end=b)
        folds.append({'start':candles[a]['time'],'end':candles[b-1]['time'],**{k:v for k,v in r.items() if k!='trades'}})
    scenarios=[replay(candles,cost_bps=c,start=start) for c in (5,20,50)]
    benchmark=(candles[-1]['close']/candles[start+1]['open']-1)*100-0.4
    return {'strategy':'Fixed 20-bar completed-close breakout; next-open entry; ATR stop; 2R target; five-bar timeout',
        'folds':folds,'cost_scenarios':scenarios,'buy_hold_net_pct':benchmark,'status':'EXPERIMENTAL — not approved for live trading',
        'limitations':['No parameter optimization or claimed predictive training','Contiguous chronological evaluation; finite historical sample',
        'Fixed spread/slippage scenarios, not measured executable quotes','No account-currency conversion, taxes, impact or broker execution',
        'Results are per-position returns, not an account-equity forecast','Last completed historical bar is not a live signal']}

def install(app,db,auth,csrf,now):
    from fastapi import Request,HTTPException
    from pydantic import BaseModel,Field
    import trading_division as td
    import trading_lab as lab
    import json
    with db() as c:c.execute('CREATE TABLE IF NOT EXISTS trading_validation(id INTEGER PRIMARY KEY,at TEXT,symbol TEXT,interval TEXT,result TEXT)')
    class Evaluation(BaseModel):
        symbol:str=Field(min_length=1,max_length=15)
        interval:str='15min'
    class Risk(BaseModel):
        equity:float;entry:float;stop:float
        risk_percent:float=0.5
        daily_loss:float=0
        daily_limit_percent:float=2
        exposure:float=0
    @app.post('/api/trading/lab/validate')
    async def validate(body:Evaluation,req:Request):
        csrf(req)
        if body.interval not in ('15min','1day'):raise HTTPException(400,'Choose 15min or 1day')
        symbol=lab.sym(body.symbol)
        data=await td.market(symbol,body.interval,500)
        try:result=evaluate(data['candles'])
        except ValueError as exc:raise HTTPException(422,str(exc))
        result.update(symbol=symbol,interval=body.interval,source=data['source'],data_quality=data.get('quality'),checked=now())
        with db() as c:c.execute('INSERT INTO trading_validation(at,symbol,interval,result) VALUES(?,?,?,?)',(now(),symbol,body.interval,json.dumps(result)))
        return result
    @app.post('/api/trading/risk-preview')
    def risk(body:Risk,req:Request):
        csrf(req)
        try:return size_position(**body.model_dump())
        except ValueError as exc:raise HTTPException(400,str(exc))
    @app.get('/api/trading/lab/validations')
    def history(req:Request):
        auth(req)
        with db() as c:return {'items':[dict(r) for r in c.execute('SELECT * FROM trading_validation ORDER BY id DESC LIMIT 20')]}
