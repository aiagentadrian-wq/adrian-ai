"""Headless learned swing policy: yfinance + scikit-learn + official Alpaca SDK.

Only paper trading is implemented. Price/volume statistics are model inputs, not
fixed indicator buy/sell rules. Cash, position, loss and freshness limits remain
explicit safety constraints. No interactive input, eval, generated executable
strategy code, live brokerage URL, or untrusted pickle loading is used.
"""
import argparse
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime,timedelta,timezone
import hashlib,json,logging,math,os,secrets,sqlite3,sys,time
from email.utils import parsedate_to_datetime
from pathlib import Path
from zoneinfo import ZoneInfo
import numpy as np
import pandas as pd
import learning_governance as governance

LOCAL=ZoneInfo('America/Toronto');HORIZONS=(1,2,3,5,10,20);WINDOWS=(2,3,5,10,20,40,60)
LOG=logging.getLogger('adrian.learned_swing')

def record_health(service,status,detail):
    monitor=sys.modules.get('dashboard_core')
    if monitor:
        try:monitor.observe(service,status,detail)
        except Exception:LOG.warning('Service-health recording unavailable; broker outcome is unchanged.')
def utc():return datetime.now(timezone.utc)
def serial(value):
    if hasattr(value,'model_dump'):return value.model_dump(mode='json')
    if hasattr(value,'dict'):return json.loads(value.json())
    return value

@dataclass
class Config:
    symbols:tuple=('SPY','QQQ','MSFT','NVDA','AMD','AAPL')
    risk_fraction:float=.0025
    daily_loss_fraction:float=.01
    week_loss_fraction:float=.02
    max_positions:int=3
    cost_bps_each_side:float=20
    enabled:bool=False
    daily_exploration:bool=False
    evidence_mode:bool=False
    deadline:str=''
    def __post_init__(self):
        import re
        if not self.symbols or len(self.symbols)>12 or any(not re.fullmatch(r'[A-Z]{1,5}',s) for s in self.symbols):raise ValueError('US stock symbols only, up to 12')
        if not 0<self.risk_fraction<=.0025 or not 0<self.daily_loss_fraction<=.01 or not 0<self.week_loss_fraction<=.02 or not 1<=self.max_positions<=3:raise ValueError('Risk limits exceed authorized bounds')
        if not 0<=self.cost_bps_each_side<=100:raise ValueError('Invalid cost assumption')

class Store:
    def __init__(self,path):
        self.path=Path(path);self.path.parent.mkdir(parents=True,exist_ok=True)
        with self.connect() as c:c.executescript('CREATE TABLE IF NOT EXISTS config(key TEXT PRIMARY KEY,value TEXT);CREATE TABLE IF NOT EXISTS models(id INTEGER PRIMARY KEY,at TEXT,source_date TEXT,model TEXT,report TEXT);CREATE TABLE IF NOT EXISTS orders(client_id TEXT PRIMARY KEY,at TEXT,symbol TEXT,side TEXT,status TEXT,broker_id TEXT,payload TEXT,detail TEXT);CREATE TABLE IF NOT EXISTS holdings(symbol TEXT PRIMARY KEY,entry_client TEXT,quantity REAL,entry_value REAL);CREATE TABLE IF NOT EXISTS notes(id INTEGER PRIMARY KEY,at TEXT,kind TEXT,payload TEXT);')
    @contextmanager
    def connect(self):
        c=sqlite3.connect(self.path,timeout=30);c.row_factory=sqlite3.Row
        try:
            yield c
            c.commit()
        except Exception:
            c.rollback()
            raise
        finally:c.close()
    def get(self,key,default=None):
        with self.connect() as c:r=c.execute('SELECT value FROM config WHERE key=?',(key,)).fetchone()
        return json.loads(r['value']) if r else default
    def put(self,key,value):
        with self.connect() as c:c.execute('INSERT INTO config VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',(key,json.dumps(value)))
    def note(self,kind,value):
        with self.connect() as c:c.execute('INSERT INTO notes(at,kind,payload) VALUES(?,?,?)',(utc().isoformat(),kind,json.dumps(value,default=str)))
    def unresolved(self):
        with self.connect() as c:return [dict(r) for r in c.execute("SELECT * FROM orders WHERE status NOT IN ('filled','canceled','expired','rejected','skipped')")]
    def update(self,client,status,detail,broker_id=None):
        with self.connect() as c:c.execute('UPDATE orders SET status=?,detail=?,broker_id=COALESCE(?,broker_id) WHERE client_id=?',(status,detail,broker_id,client))
    def model(self):
        with self.connect() as c:r=c.execute('SELECT * FROM models ORDER BY id DESC LIMIT 1').fetchone()
        if not r:return None
        return dict(r)|{'model':json.loads(r['model']),'report':governance.report_status(json.loads(r['report']))}
    def summary(self):
        with self.connect() as c:
            orders=[dict(r) for r in c.execute('SELECT * FROM orders ORDER BY at DESC LIMIT 30')]
            notes=[{'at':r['at'],'kind':r['kind'],'data':json.loads(r['payload'])} for r in c.execute('SELECT * FROM notes ORDER BY id DESC LIMIT 12')]
            holdings=[dict(r) for r in c.execute('SELECT * FROM holdings')]
        for r in orders:r['plan']=json.loads(r.pop('payload'))
        model=self.model()
        return {'engine':'Learned daily swing policy / yfinance / alpaca-py PAPER','enabled':self.get('enabled',False),'daily_exploration':self.get('daily_exploration',False),'daily_trade_status':self.get('daily_trade_status'),'deadline':self.get('deadline'),'last_run':self.get('last_run'),'last_error':self.get('last_error'),'model':{'id':model['id'],'at':model['at'],'source_date':model['source_date'],'report':model['report']} if model else None,'orders':orders,'holdings':holdings,'notes':notes,'last_decisions':self.get('last_decisions',[]),
                'learning_scorecard':governance.scorecard(self),
                'limits':{'risk_per_new_position_percent':.25,'max_positions':3,'daily_loss_limit_percent':1,'experiment_loss_limit_percent':2,'allocation_note':'Notional is capped at 0.25% of equity. For unlevered long stock this bounds capital at risk even if the stock becomes worthless; planned app-managed stop/target/time exits can exceed planned loss during gaps or downtime.'},
                'note':'Learned entries/exits are forecasts, not guaranteed income. No model edits its risk controls or executable code. PC/server/network must remain available.'}

def clean_prices(frame,before):
    frame=frame.copy()
    if isinstance(frame.columns,pd.MultiIndex):frame.columns=frame.columns.get_level_values(0)
    required=['Open','High','Low','Close','Volume']
    if any(k not in frame for k in required):raise ValueError('OHLCV columns missing')
    frame=frame[required].sort_index();frame.index=pd.to_datetime(frame.index).tz_localize(None).normalize()
    if frame.index.duplicated().any():raise ValueError('Duplicate daily bars')
    frame=frame.loc[frame.index<pd.Timestamp(before)].astype(float)
    if len(frame)<400:raise ValueError('Need 400 completed daily sessions')
    if not np.isfinite(frame.to_numpy()).all() or (frame[['Open','High','Low','Close']]<=0).any().any() or (frame['Volume']<0).any():raise ValueError('Invalid OHLCV values')
    if ((frame['Low']>frame[['Open','Close']].min(axis=1))|(frame['High']<frame[['Open','Close']].max(axis=1))|(frame['Low']>frame['High'])).any():raise ValueError('Inconsistent OHLC range')
    return frame

def download_history(symbol,before=None):
    import yfinance as yf
    before=before or utc().astimezone(LOCAL).date().isoformat()
    # Yahoo's adjusted history can be revised after splits/dividends; document this
    # point-in-time limitation instead of presenting it as a perfect archival feed.
    frame=yf.download(symbol,start=(pd.Timestamp(before)-pd.DateOffset(years=6)).date().isoformat(),end=before,interval='1d',auto_adjust=True,actions=False,progress=False,threads=False,multi_level_index=False,timeout=20)
    if frame is None or frame.empty:raise ValueError('yfinance returned no historical data for '+symbol)
    return clean_prices(frame,before)

def statistical_features(frame):
    """All rolling statistics end at the current completed daily close."""
    close=frame['Close'];ret=close.pct_change();volume=frame['Volume'];result=pd.DataFrame(index=frame.index)
    result['open_gap']=frame['Open']/close.shift(1)-1
    result['intraday_return']=close/frame['Open']-1
    result['daily_range']=(frame['High']-frame['Low'])/close
    result['close_in_range']=(close-frame['Low'])/(frame['High']-frame['Low']).replace(0,np.nan)
    result['log_volume_change']=np.log1p(volume).diff()
    for n in WINDOWS:
        roll=ret.rolling(n,min_periods=n)
        result[f'momentum_{n}']=close/close.shift(n)-1
        result[f'mean_return_{n}']=roll.mean()
        result[f'volatility_{n}']=roll.std()
        result[f'downside_{n}']=ret.clip(upper=0).pow(2).rolling(n,min_periods=n).mean().pow(.5)
        result[f'price_relative_mean_{n}']=close/close.rolling(n,min_periods=n).mean()-1
        result[f'price_relative_high_{n}']=close/frame['High'].rolling(n,min_periods=n).max()-1
        result[f'price_relative_low_{n}']=close/frame['Low'].rolling(n,min_periods=n).min()-1
        result[f'volume_relative_{n}']=volume/volume.shift(1).rolling(n,min_periods=n).mean().replace(0,np.nan)
        result[f'range_mean_{n}']=((frame['High']-frame['Low'])/close).rolling(n,min_periods=n).mean()
    return result.replace([np.inf,-np.inf],np.nan)

def forest_json(estimator):
    trees=[]
    for tree in estimator.estimators_:
        t=tree.tree_;trees.append({'left':t.children_left.tolist(),'right':t.children_right.tolist(),'feature':t.feature.tolist(),'threshold':t.threshold.tolist(),'values':t.value[:,:,0].tolist()})
    return {'features':estimator.feature_names_in_.tolist() if hasattr(estimator,'feature_names_in_') else [],'trees':trees,'importance':estimator.feature_importances_.tolist()}

def predict(model,x):
    x=np.asarray(x,dtype=float)
    if not np.isfinite(x).all():raise ValueError('Nonfinite policy features')
    values=[]
    for tree in model['trees']:
        i=0
        while tree['left'][i]!=-1:i=tree['left'][i] if x[tree['feature'][i]]<=tree['threshold'][i] else tree['right'][i]
        values.append(tree['values'][i])
    return np.mean(values,axis=0).tolist()

def decision(forecasts,errors,cost_bps=20,holding=False):
    cost=cost_bps/10000*(1 if holding else 2)
    opportunities=[{'horizon_sessions':h,'forecast_gross_return':float(p),'uncertainty_allowance':float(e),'conservative_net_estimate':float(p-e-cost),'score_per_session':float(p-e-cost)/h} for h,p,e in zip(HORIZONS,forecasts,errors)]
    best=max(opportunities,key=lambda x:x['score_per_session'])
    return {'action':('HOLD' if holding else 'BUY') if best['conservative_net_estimate']>0 else ('EXIT' if holding else 'WAIT'),'selected':best,'forecasts':opportunities,'reason':'Learned multi-horizon return forecast minus later validation error allowance and assumed costs. This is not a calibrated confidence interval.'}

def replay_policy(prices,features,model,errors,start,end,cost_bps=20):
    cash=2000.;quantity=0.;peak=cash;drawdown=0.;trades=[];entry_value=0.;entry_date=None
    for i in range(start,end-1):
        if features.iloc[i].isna().any():continue
        d=decision(predict(model,features.iloc[i].to_numpy()),errors,cost_bps,quantity>0)
        next_open=float(prices.iloc[i+1]['Open']);date=str(prices.index[i+1].date());cost=cost_bps/10000
        if quantity and d['action']=='EXIT':
            proceeds=quantity*next_open*(1-cost);cash+=proceeds;trades.append({'entry_date':entry_date,'exit_date':date,'net_pnl_usd':proceeds-entry_value});quantity=0.
        elif not quantity and d['action']=='BUY':
            # Same full-loss risk/cash cap used by the headless notional order path.
            spend=cash*.0025;quantity=spend/(next_open*(1+cost));cash-=spend;entry_value=spend;entry_date=date
        equity=cash+quantity*float(prices.iloc[i+1]['Close']);peak=max(peak,equity);drawdown=min(drawdown,(equity/peak-1)*100)
    if quantity:
        proceeds=quantity*float(prices.iloc[end-1]['Close'])*(1-cost_bps/10000);cash+=proceeds;trades.append({'entry_date':entry_date,'exit_date':str(prices.index[end-1].date()),'net_pnl_usd':proceeds-entry_value,'reason':'Forced segment-end exit for comparison'})
    return {'net_return_pct':round((cash/2000-1)*100,5),'net_pnl_example_usd':round(cash-2000,4),'max_mark_to_market_drawdown_pct':round(drawdown,5),'trade_count':len(trades),'win_rate_pct':round(100*sum(t['net_pnl_usd']>0 for t in trades)/len(trades),2) if trades else None,'trades':trades,
            'buy_hold_net_pct':round((float(prices.iloc[end-1]['Close'])/float(prices.iloc[start+1]['Open'])-1)*100-2*cost_bps/100,3),'note':'Independent $2,000 symbol simulation with only 0.25% notional per position; not a combined portfolio or income forecast.'}

def fit_policy(datasets,cost_bps=20):
    from sklearn.ensemble import RandomForestRegressor
    common=sorted(set.intersection(*[set(frame.index) for frame in datasets.values()]))
    if len(common)<400:raise ValueError('Need 400 common completed sessions across the requested universe')
    first_cut=common[int(len(common)*.6)];second_cut=common[int(len(common)*.8)]
    training=[];validation=[];test=[];prepared={};feature_names=None
    for symbol,prices in datasets.items():
        prices=prices.loc[common];x=statistical_features(prices);feature_names=list(x.columns);prepared[symbol]=(prices,x)
        labels=pd.DataFrame({h:prices['Close'].shift(-h)/prices['Open'].shift(-1)-1 for h in HORIZONS})
        for i in range(60,len(prices)-max(HORIZONS)):
            if x.iloc[i].isna().any() or labels.iloc[i].isna().any():continue
            row=(x.iloc[i].to_numpy(),labels.iloc[i].to_numpy(),prices.index[i],prices.index[i+max(HORIZONS)])
            if row[3]<first_cut:training.append(row)
            elif row[2]>=first_cut and row[3]<second_cut:validation.append(row)
            elif row[2]>=second_cut:test.append(row)
    if min(len(training),len(validation),len(test))<80:raise ValueError('Insufficient purged learning/evaluation rows')
    xtrain=pd.DataFrame([r[0] for r in training],columns=feature_names);ytrain=np.array([r[1] for r in training]);xval=np.array([r[0] for r in validation]);yval=np.array([r[1] for r in validation]);trials=[]
    for depth,leaf in [(3,20),(5,15),(7,10)]:
        estimator=RandomForestRegressor(n_estimators=50,max_depth=depth,min_samples_leaf=leaf,random_state=23,n_jobs=1)
        estimator.fit(xtrain,ytrain);model=forest_json(estimator);predictions=np.array([predict(model,r) for r in xval]);errors=np.mean(abs(predictions-yval),axis=0)
        trials.append({'model':model,'parameters':{'max_depth':depth,'min_samples_leaf':leaf},'validation_mae':float(errors.mean()),'errors':errors.tolist()})
    choice=min(trials,key=lambda t:t['validation_mae']);selected=choice['model'];errors=choice['errors'];periods={'validation':(int(len(common)*.6),int(len(common)*.8)),'test':(int(len(common)*.8),len(common))};results={}
    for period,(a,b) in periods.items():results[period]={symbol:replay_policy(prices,x,selected,errors,a,b,cost_bps) for symbol,(prices,x) in prepared.items()}
    summary={period:{'mean_independent_return_pct':round(sum(r['net_return_pct'] for r in values.values())/len(values),5),'worst_drawdown_pct':min(r['max_mark_to_market_drawdown_pct'] for r in values.values()),'trade_count':sum(r['trade_count'] for r in values.values())} for period,values in results.items()}
    test_predictions=np.array([predict(selected,r[0]) for r in test]);test_errors=np.mean(abs(test_predictions-np.array([r[1] for r in test])),axis=0)
    eligible=summary['validation']['mean_independent_return_pct']>0 and summary['test']['mean_independent_return_pct']>0
    report={'algorithm':'RandomForestRegressor learns six future-return horizons from 68 rolling OHLCV statistical features; entry/hold/exit follow learned forecasts, not RSI/SMA trade thresholds.',
            'feature_count':len(feature_names),'feature_names':feature_names,'horizons':list(HORIZONS),'chosen_parameters':choice['parameters'],'candidate_models':[{k:v for k,v in t.items() if k!='model'} for t in trials],
            'validation_error_by_horizon':errors,'test_error_by_horizon':test_errors.tolist(),'training_rows':len(training),'validation_rows':len(validation),'test_rows':len(test),
            'split_dates':{'training_last_label':str(max(r[3] for r in training).date()),'validation_first':str(min(r[2] for r in validation).date()),'validation_last_label':str(max(r[3] for r in validation).date()),'test_first':str(min(r[2] for r in test).date()),'test_last':str(common[-1].date())},
            'evaluations':results,'summary':summary,'paper_eligible':eligible,'verdict':'Experimental learned policy eligible for bounded paper trials' if eligible else 'No reliable positive later-data result; automatic entries blocked',
            'important_features':sorted([{'feature':k,'weight':round(float(v),5)} for k,v in zip(feature_names,selected['importance'])],key=lambda r:r['weight'],reverse=True)[:12],
            'cost_stress':{str(cost):{symbol:replay_policy(prices,x,selected,errors,*periods['test'],cost) for symbol,(prices,x) in prepared.items()} for cost in (5,20,50)},
            'limitations':['Adjusted Yahoo history can be retrospectively revised; free data is not an executable quote or point-in-time fundamental database.','Current ticker universe introduces selection/survivorship bias. Daily features can miss sudden events and overnight gaps.','Purged chronological model selection; repeated training reuses test history, and subsequent forward-paper results are separate.','Validation MAE is an uncertainty allowance, not a calibrated probability or guaranteed return bound.','A learned policy cannot promise profit or recognize every market event. No generated code or risk-limit self-modification.']}
    report['planned_exit_tests']={period:{str(cost):{symbol:governance.replay_planned(prices,x,selected,errors,*periods[period],cost) for symbol,(prices,x) in prepared.items()} for cost in (20,50)} for period in ('validation','test')}
    # Freeze chosen parameters, then refit only on rows with fully matured outcomes.
    mature=training+validation+test
    estimator=RandomForestRegressor(n_estimators=50,random_state=23,n_jobs=1,**choice['parameters'])
    estimator.fit(pd.DataFrame([r[0] for r in mature],columns=feature_names),np.array([r[1] for r in mature]))
    return forest_json(estimator),report

def validate_broker_clock(timestamp,http_date,cache_age,elapsed):
    source=datetime.fromisoformat(str(timestamp).replace('Z','+00:00'))
    server=parsedate_to_datetime(http_date)
    if source.tzinfo is None or server.tzinfo is None or float(cache_age)!=0 or not 0<=elapsed<=5:
        raise ValueError('Untrusted broker clock response')
    if abs((source-server).total_seconds())>3 or abs((utc()-source).total_seconds())>300:
        raise ValueError('Broker clock timestamps disagree or local skew exceeds five minutes')
    return source

class AlpacaBroker:
    """SDK adapter with paper=True as an invariant, not a user-selectable endpoint."""
    def __init__(self,key=None,secret=None):
        from alpaca.trading.client import TradingClient
        key=key or os.getenv('APCA_API_KEY_ID') or os.getenv('ALPACA_API_KEY')
        secret=secret or os.getenv('APCA_API_SECRET_KEY') or os.getenv('ALPACA_SECRET_KEY')
        if not key or not secret:raise ValueError('Paper credentials missing: APCA_API_KEY_ID and APCA_API_SECRET_KEY')
        self.client=TradingClient(api_key=key,secret_key=secret,paper=True)
        self._clock_http=None
        self.client._session.hooks.setdefault('response',[]).append(self._observe_clock_response)
        from alpaca.data.historical import StockHistoricalDataClient
        self.data_client=StockHistoricalDataClient(api_key=key,secret_key=secret)
    def call(self,name,*args,**kwargs):
        try:
            result=getattr(self.client,name)(*args,**kwargs)
            record_health('alpaca','verified','Actual paper SDK '+name+' request succeeded; order acceptance is not a fill.')
            return result
        except Exception as exc:
            code=getattr(exc,'status_code',None)
            status='limited' if code==429 else 'access denied' if code in (401,403) else 'error'
            record_health('alpaca',status,'Paper SDK '+name+' failed; no completed action inferred.')
            LOG.error('Alpaca %s failed (%s)',name,type(exc).__name__)
            raise RuntimeError('Alpaca paper '+name+' failed; state not assumed complete') from exc
    def account(self):return serial(self.call('get_account'))
    def _observe_clock_response(self,response,*args,**kwargs):
        if response.url.split('?')[0]=='https://paper-api.alpaca.markets/v2/clock':
            self._clock_http=(response.headers.get('Date'),response.headers.get('Age','0'),response.elapsed.total_seconds(),time.monotonic())
    def clock(self):
        self._clock_http=None
        result=serial(self.call('get_clock'))
        if not self._clock_http:raise RuntimeError('Broker clock HTTP timestamp unavailable')
        date,age,elapsed,received=self._clock_http
        self._trusted_clock=validate_broker_clock(result['timestamp'],date,age,elapsed)
        self._trusted_received=received
        return result
    def quote_now(self):
        elapsed=time.monotonic()-self._trusted_received
        if not 0<=elapsed<=60:raise RuntimeError('Broker clock calibration expired')
        return self._trusted_clock+timedelta(seconds=elapsed)
    def positions(self):return [serial(x) for x in self.call('get_all_positions')]
    def orders(self):
        from alpaca.trading.requests import GetOrdersRequest
        from alpaca.trading.enums import QueryOrderStatus
        return [serial(x) for x in self.call('get_orders',filter=GetOrdersRequest(status=QueryOrderStatus.OPEN,nested=True))]
    def by_client(self,id):return serial(self.call('get_order_by_client_id',id))
    def asset(self,symbol):return serial(self.call('get_asset',symbol))
    def calendar(self,start,end):
        from alpaca.trading.requests import GetCalendarRequest
        return [serial(x) for x in self.call('get_calendar',filters=GetCalendarRequest(start=start,end=end))]
    def buy(self,symbol,notional,client_id):
        from alpaca.trading.requests import MarketOrderRequest
        from alpaca.trading.enums import OrderSide,TimeInForce
        return serial(self.call('submit_order',order_data=MarketOrderRequest(symbol=symbol,notional=round(notional,2),side=OrderSide.BUY,time_in_force=TimeInForce.DAY,client_order_id=client_id)))
    def close(self,symbol):return serial(self.call('close_position',symbol))
    def cancel(self,id):self.call('cancel_order_by_id',id)
    def quote(self,symbol):
        return self.quotes([symbol])[symbol]
    def quotes(self,symbols):
        from alpaca.data.requests import StockLatestQuoteRequest
        from alpaca.data.enums import DataFeed
        try:return {symbol:serial(value) for symbol,value in self.data_client.get_stock_latest_quote(StockLatestQuoteRequest(symbol_or_symbols=list(symbols),feed=DataFeed.IEX)).items()}
        except Exception as exc:raise RuntimeError('Fresh Alpaca IEX quote unavailable') from exc

class Runner:
    def __init__(self,config,store,broker,loader=download_history):self.config,self.store,self.broker,self.loader=config,store,broker,loader
    def expected_session(self,now):
        rows=self.broker.calendar((now.astimezone(LOCAL).date()-timedelta(days=14)).isoformat(),now.astimezone(LOCAL).date().isoformat())
        day=now.astimezone(LOCAL).date().isoformat();dates=[str(r['date'])[:10] for r in rows if str(r['date'])[:10]<day]
        if not dates:raise ValueError('No prior session confirmed by broker calendar')
        return max(dates)
    def learn(self):
        now=utc();expected=self.expected_session(now);datasets={s:self.loader(s,now.astimezone(LOCAL).date().isoformat()) for s in self.config.symbols}
        if any(str(f.index[-1].date())!=expected for f in datasets.values()):raise ValueError('Historical data stale; latest day must match prior broker session')
        model,report=fit_policy(datasets,self.config.cost_bps_each_side);previous=self.store.model()
        if previous:
            report['previous_version']=previous['id'];report['test_data_reused']=True
            report['improvement']={period:{'before':previous['report']['summary'][period],'after':report['summary'][period]} for period in ('validation','test')}
            report['comparison_note']='Rolling-window comparison; test history is reused and changed dates do not establish a causal improvement.'
        else:report['test_data_reused']=False
        with self.store.connect() as c:
            cur=c.execute('INSERT INTO models(at,source_date,model,report) VALUES(?,?,?,?)',(now.isoformat(),expected,json.dumps(model),json.dumps(report)));version=cur.lastrowid
        self.store.note('policy learned',{'model_version':version,'summary':report['summary'],'verdict':report['verdict'],'parameters':report['chosen_parameters'],'improvement':report.get('improvement')})
        self.store.put('last_error',None);return datasets
    def reconcile(self):
        for row in self.store.unresolved():
            try:
                if row['side']=='sell' and not row['broker_id']:
                    # SDK close_position has no client-ID field. Its unknown result is
                    # deliberately not retried; inspect actual position/orders instead.
                    positions=self.broker.positions();pending=self.broker.orders()
                    if not any(p['symbol']==row['symbol'] for p in positions) and not any(o['symbol']==row['symbol'] for o in pending):
                        self.store.update(row['client_id'],'filled','Position absent after requested close; exact exit P/L not inferred.')
                        with self.store.connect() as c:c.execute('DELETE FROM holdings WHERE symbol=?',(row['symbol'],))
                    continue
                order=self.broker.by_client(row['client_id']) if row['side']=='buy' else serial(self.broker.call('get_order_by_id',row['broker_id']))
                status=str(order['status']);self.store.update(row['client_id'],status,'Broker '+status+'; filled '+str(order.get('filled_qty')),str(order['id']))
                quantity=float(order.get('filled_qty') or 0)
                if quantity>0:
                    value=quantity*float(order['filled_avg_price'])
                    if row['side']=='buy':
                        governance.register_trade(self.store,row['client_id'],row['symbol'],json.loads(row['payload']),value,quantity,row['at'])
                        with self.store.connect() as c:c.execute('INSERT INTO holdings VALUES(?,?,?,?) ON CONFLICT(symbol) DO UPDATE SET quantity=excluded.quantity,entry_value=excluded.entry_value',(row['symbol'],row['client_id'],quantity,value))
                    else:
                        plan=json.loads(row['payload'])
                        if plan.get('entry_client'):governance.record_exit(self.store,row['client_id'],plan['entry_client'],quantity,value,plan.get('reason',''),utc())
                        previous=float(plan.get('_accounted_qty',0));delta=max(0,quantity-previous)
                        with self.store.connect() as c:
                            holding=c.execute('SELECT * FROM holdings WHERE symbol=?',(row['symbol'],)).fetchone()
                            if holding and delta:
                                remainder=max(0,holding['quantity']-delta)
                                if remainder<1e-6:c.execute('DELETE FROM holdings WHERE symbol=?',(row['symbol'],))
                                else:c.execute('UPDATE holdings SET quantity=?,entry_value=? WHERE symbol=?',(remainder,holding['entry_value']*remainder/holding['quantity'],row['symbol']))
                            plan['_accounted_qty']=quantity;c.execute('UPDATE orders SET payload=? WHERE client_id=?',(json.dumps(plan),row['client_id']))
                        if status=='filled' and plan.get('entry_value') is not None:
                            basis=float(plan['entry_value']);self.store.note('settled learned-policy outcome',{'symbol':row['symbol'],'entry_value_usd':basis,'exit_value_usd':value,'gross_pnl_usd':round(value-basis,4),'estimated_net_usd':round(value-basis-(value+basis)*self.config.cost_bps_each_side/10000,4)})
                if row['side']=='buy' and status not in ('filled','canceled','expired','rejected') and (utc()-datetime.fromisoformat(row['at'])).total_seconds()>180:
                    self.broker.cancel(str(order['id']))
                    self.store.update(row['client_id'],'cancel_requested','Unfilled entry remainder cancellation requested; existing partial fill retained.',str(order['id']))
            except Exception:self.store.update(row['client_id'],'uncertain','Broker outcome unresolved; new entries blocked, no blind retry.')
    def exit(self,symbol,reason,positions,opens):
        with self.store.connect() as c:owned=c.execute('SELECT * FROM holdings WHERE symbol=?',(symbol,)).fetchone()
        if not owned:return
        actual=next((p for p in positions if p['symbol']==symbol),None)
        if not actual:return
        if float(actual['qty'])>owned['quantity']+1e-6 or float(actual['qty'])<=0:raise ValueError('Position ownership changed; automated full close blocked')
        if any(o['symbol']==symbol for o in opens):return
        if any(o['symbol']==symbol for o in self.store.unresolved()):return
        client='swing-exit-'+secrets.token_hex(12)
        with self.store.connect() as c:c.execute('INSERT INTO orders VALUES(?,?,?,?,?,?,?,?)',(client,utc().isoformat(),symbol,'sell','submitting',None,json.dumps({'reason':reason,'entry_value':owned['entry_value'],'entry_quantity':owned['quantity'],'entry_client':owned['entry_client']}),'Claim persisted before SDK close request.'))
        try:
            order=self.broker.close(symbol);self.store.update(client,str(order['status']),'SDK close_position submitted; fill unconfirmed.',str(order['id']))
        except Exception:self.store.update(client,'uncertain','Close outcome unknown; position reconciliation required before any retry.')
    def run(self,train_only=False):
        from filelock import FileLock,Timeout
        try:
            with FileLock(str(self.store.path)+'.lock',timeout=0):return self._run(train_only)
        except Timeout:return {'status':'already_running','note':'Overlapping headless run skipped; no order submitted.'}
    def _run(self,train_only=False):
        now=utc();self.store.put('last_run',now.isoformat());self.reconcile()
        account=self.broker.account();clock=self.broker.clock();positions=self.broker.positions();opens=self.broker.orders()
        if account.get('currency')!='USD' or account.get('status')!='ACTIVE' or account.get('trading_blocked') or account.get('account_blocked'):raise ValueError('Active unblocked USD paper account required')
        if self.store.get('start_equity') is None:
            self.store.put('start_equity',float(account['equity']));self.store.put('deadline',self.store.get('deadline') or self.config.deadline or (now+timedelta(days=7)).isoformat())
        day=now.astimezone(LOCAL).date().isoformat()
        if self.store.get('day')!=day:self.store.put('day',day);self.store.put('day_equity',float(account['equity']))
        self.store.put('enabled',self.config.enabled)
        self.store.put('daily_exploration',self.config.daily_exploration)
        deadline=self.store.get('deadline');halt=now>=datetime.fromisoformat(deadline) or float(account['equity'])<=self.store.get('start_equity')*(1-self.config.week_loss_fraction) or float(account['equity'])<=self.store.get('day_equity')*(1-self.config.daily_loss_fraction)
        if self.config.enabled and halt and clock['is_open']:
            with self.store.connect() as c:owned=[r['symbol'] for r in c.execute('SELECT symbol FROM holdings')]
            for symbol in owned:self.exit(symbol,'Risk/experiment deadline exit',positions,opens)
            self.store.note('entries halted',{'reason':'Deadline or account loss limit','equity':account['equity']});return self.store.summary()
        expected=self.expected_session(now);version=self.store.model();datasets=None
        if train_only or not version or (not self.config.evidence_mode and version['source_date']!=expected) or set(version['report'].get('evaluations',{}).get('test',self.config.symbols))!=set(self.config.symbols):datasets=self.learn();version=self.store.model()
        if train_only:return self.store.summary()
        if datasets is None:datasets={s:self.loader(s,day) for s in self.config.symbols}
        if any(str(f.index[-1].date())!=expected for f in datasets.values()):raise ValueError('Stale Yahoo data; no learned decision or order permitted')
        if self.config.evidence_mode:
            governance.mature(self.store,datasets,now);governance.evaluate_outcome_shadow(self.store);governance.train_outcomes(self.store)
            governance.promotion(self.store,version['id'],version['report'])
        evidence_sessions=[]
        if self.config.evidence_mode:evidence_sessions=[r for r in self.broker.calendar(day,self.store.get('deadline')[:10]) if day<=str(r['date'])[:10]<self.store.get('deadline')[:10]]
        decisions=[];model=version['model'];report=version['report'];errors=report['validation_error_by_horizon']
        with self.store.connect() as c:owned={r['symbol'] for r in c.execute('SELECT symbol FROM holdings')}
        for symbol,prices in datasets.items():
            x=statistical_features(prices).iloc[-1]
            forecasts=predict(model,x.to_numpy())
            if self.config.evidence_mode:forecasts=governance.corrected_forecasts(self.store,version['id'],x.to_numpy(),forecasts)
            d=decision(forecasts,errors,self.config.cost_bps_each_side,symbol in owned)
            if self.config.evidence_mode:
                options=[p for p in d['forecasts'] if p['horizon_sessions']<=min(5,len(evidence_sessions))]
                if options:
                    d['selected']=max(options,key=lambda p:p['score_per_session'])
                    d['action']=('HOLD' if symbol in owned else 'BUY') if d['selected']['conservative_net_estimate']>0 else ('EXIT' if symbol in owned else 'WAIT')
                else:d['action']='EXIT' if symbol in owned else 'WAIT'
            d.update(symbol=symbol,model_version=version['id'],as_of=expected)
            if self.config.evidence_mode:
                d['entry_features']=x.to_numpy().tolist()
                regime='positive_trend' if float(x.get('momentum_20',0))>0 else 'negative_trend'
                governance.record_predictions(self.store,version['id'],symbol,expected,x.to_numpy(),predict(model,x.to_numpy()),errors,regime,now)
                governance.record_calibrated_shadow(self.store,version['id'],symbol,expected,x.to_numpy(),predict(model,x.to_numpy()),errors,regime,now)
                champion=self.store.get('research_champion')
                if champion and champion!=version['id']:
                    with self.store.connect() as c:old=c.execute('SELECT * FROM models WHERE id=?',(champion,)).fetchone()
                    if old:
                        oldmodel=json.loads(old['model']);oldreport=json.loads(old['report'])
                        governance.record_predictions(self.store,champion,symbol,expected,x.to_numpy(),predict(oldmodel,x.to_numpy()),oldreport['validation_error_by_horizon'],regime,now)

            if self.config.evidence_mode and d['action']=='EXIT' and d['selected']['forecast_gross_return']>2*self.config.cost_bps_each_side/10000:
                with self.store.connect() as c:entry_plan=c.execute('SELECT o.payload FROM holdings h JOIN orders o ON h.entry_client=o.client_id WHERE h.symbol=?',(symbol,)).fetchone()
                if entry_plan and json.loads(entry_plan['payload']).get('track')=='experimental':
                    d['action']='HOLD';d['reason']='Experimental hypothesis remains positive before uncertainty allowance; obey planned stop, target and time exit. Exit earlier if raw post-cost forecast turns nonpositive.'
            if d['action']=='EXIT' and self.config.daily_exploration:
                with self.store.connect() as c:entry=c.execute('SELECT o.at,o.payload FROM holdings h JOIN orders o ON o.client_id=h.entry_client WHERE h.symbol=?',(symbol,)).fetchone()
                if entry and json.loads(entry['payload']).get('exploration') and datetime.fromisoformat(entry['at']).astimezone(LOCAL).date().isoformat()==day:
                    d['action']='HOLD';d['reason']='Paper learning position: evaluate after a new completed daily session; loss/deadline controls remain active.'
            if d['action']=='BUY' and not report['paper_eligible']:d['action']='WAIT';d['reason']='Learned policy failed later-period eligibility checks.'
            decisions.append(d)
        self.store.put('last_decisions',decisions)
        if not self.config.enabled or not clock['is_open'] or halt:return self.store.summary()
        for d in decisions:
            if d['action']=='EXIT':self.exit(d['symbol'],d['reason'],positions,opens)
        self.reconcile()
        if self.store.unresolved():return self.store.summary()
        if self.config.evidence_mode:
            sessions=evidence_sessions
            attempts,why=governance.choose(decisions,self.store.get('research_champion'),version['id'],len(sessions),self.store)
            self.store.put('daily_trade_status',{'day':day,'status':why})
        elif self.config.daily_exploration:
            # Research WAIT stays visible. Paper exploration is a separate,
            # explicitly authorized learning action, not a profitable signal.
            attempts=[d.copy()|{'model_action':d['action'],'exploration':d['action']!='BUY','action':'BUY','reason':d['reason'] if d['action']=='BUY' else 'Owner-authorized daily paper exploration despite model WAIT; selected by learned relative forecast. No positive edge claimed.'} for d in decisions if d['symbol'] not in owned]
        else:attempts=decisions
        quotes=self.broker.quotes([d['symbol'] for d in attempts]) if hasattr(self.broker,'quotes') and attempts else None
        blocked=[];submitted=False
        for d in sorted(attempts,key=lambda r:r['selected']['score_per_session'],reverse=True):
            if d['action']!='BUY':continue
            account=self.broker.account();positions=self.broker.positions();opens=self.broker.orders();clock=self.broker.clock()
            occupied={p['symbol'] for p in positions+opens}
            if not clock['is_open'] or d['symbol'] in occupied or len(occupied)>=self.config.max_positions:
                blocked.append({'symbol':d['symbol'],'reason':'Market closed, symbol occupied, or position cap reached'});continue
            asset=self.broker.asset(d['symbol'])
            if not asset.get('tradable') or not asset.get('fractionable') or asset.get('status')!='active':
                blocked.append({'symbol':d['symbol'],'reason':'Asset unavailable for fractional paper orders'});continue
            quote=quotes.get(d['symbol']) if quotes is not None else self.broker.quote(d['symbol'])
            if not quote:
                blocked.append({'symbol':d['symbol'],'reason':'Broker returned no quote'});continue
            quote_now=self.broker.quote_now() if hasattr(self.broker,'quote_now') else utc()
            age=(quote_now-datetime.fromisoformat(quote['timestamp'].replace('Z','+00:00'))).total_seconds()
            bid,ask=float(quote['bid_price']),float(quote['ask_price'])
            if not 0<=age<=90 or not 0<bid<=ask or (ask-bid)/ask>.003:
                blocked.append({'symbol':d['symbol'],'reason':'Quote freshness / spread check','quote_age_seconds':round(age,1),'spread_pct':round((ask-bid)/ask*100,3) if ask>0 else None});continue
            equity=float(account['equity']);cash=float(account['cash']);pending=sum(float(o.get('notional') or 0) for o in opens if o.get('side')=='buy')
            existing_risk=sum(float(p.get('market_value') or 0) for p in positions)+pending
            daily_remaining=self.store.get('day_equity')*self.config.daily_loss_fraction-max(0,self.store.get('day_equity')-equity)-existing_risk
            week_remaining=self.store.get('start_equity')*self.config.week_loss_fraction-max(0,self.store.get('start_equity')-equity)-existing_risk
            notional=round(max(0,min(equity*self.config.risk_fraction,cash-pending,daily_remaining,week_remaining)),2)
            if self.config.evidence_mode and d.get('track')=='experimental':notional=min(notional,25.,governance.experiment_available(self.store))
            if notional<1 or account.get('trading_blocked') or account.get('account_blocked'):
                blocked.append({'symbol':d['symbol'],'reason':'Cash, loss headroom or account block'});continue
            if self.config.evidence_mode:
                target=sessions[min(d['selected']['horizon_sessions'],len(sessions))-1]
                from swing_trading import session_times
                if 'T' in str(target['close']):
                    close_at=datetime.fromisoformat(str(target['close'])).replace(tzinfo=LOCAL).astimezone(timezone.utc)
                else:_,close_at=session_times(target)
                expiry=min(close_at-timedelta(minutes=10),datetime.fromisoformat(self.store.get('deadline')))
                d['exit_plan']=governance.plan_exit(d,ask,notional,now,expiry.isoformat())
            # Persist unique source-session intent: daily scheduler retries cannot
            # duplicate a buy even after a completed position is closed that day.
            client='swing-'+hashlib.sha256((d['symbol']+expected).encode()).hexdigest()[:28]
            with self.store.connect() as c:
                claimed=c.execute('INSERT OR IGNORE INTO orders VALUES(?,?,?,?,?,?,?,?)',(client,now.isoformat(),d['symbol'],'buy','submitting',None,json.dumps(d|{'notional':notional}),'Claim persisted before SDK market order.')).rowcount
            if not claimed:continue
            try:
                order=self.broker.buy(d['symbol'],notional,client);self.store.update(client,str(order['status']),'Actual SDK paper market order accepted; fill unconfirmed.',str(order['id']))
                submitted=True
                self.store.note('learned paper buy submitted',{'symbol':d['symbol'],'notional':notional,'broker_order_id':str(order['id']),'model_version':version['id'],'decision':d})
                if self.config.daily_exploration:
                    self.store.put('daily_trade_status',{'day':day,'status':'Paper learning order submitted; fill requires broker confirmation.','symbol':d['symbol'],'exploration':d.get('exploration',False)});break
            except Exception:
                self.store.update(client,'uncertain','Submission unknown; no retry or further entries.')
                if self.config.daily_exploration:self.store.put('daily_trade_status',{'day':day,'status':'Paper submission outcome unknown; entries blocked until broker reconciliation.'})
                break
        if self.config.daily_exploration and blocked and not submitted and not self.store.unresolved():self.store.put('daily_trade_status',{'day':day,'status':'No paper entry: execution checks blocked available candidates. Will retry during this session.','blocked':blocked})
        return self.store.summary()

def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--state',default=os.getenv('SWING_STATE_PATH','state/autonomous_swing.db'));parser.add_argument('--symbols',default=os.getenv('SWING_SYMBOLS','SPY,QQQ,MSFT'));parser.add_argument('--train-only',action='store_true');parser.add_argument('--status',action='store_true');args=parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO,format='%(asctime)s %(levelname)s %(message)s')
    store=Store(args.state)
    if args.status:print(json.dumps(store.summary(),indent=2));return 0
    try:
        config=Config(symbols=tuple(x.strip().upper() for x in args.symbols.split(',') if x.strip()),enabled=os.getenv('SWING_PAPER_ENABLED','0')=='1',daily_exploration=os.getenv('SWING_DAILY_EXPLORATION','0')=='1',deadline=os.getenv('SWING_DEADLINE',''))
        result=Runner(config,store,AlpacaBroker()).run(args.train_only);print(json.dumps(result,indent=2,default=str));return 0
    except Exception as exc:
        message=type(exc).__name__+': '+str(exc);store.put('last_error',message);store.note('headless run failed',{'error':message,'note':'No successful trade, training or delivery inferred.'});LOG.error('%s',message);return 1

if __name__=='__main__':raise SystemExit(main())
