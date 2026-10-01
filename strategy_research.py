"""Bounded learned strategy comparison and immutable forward shadow predictions.

Research only. This module has no broker write methods.
"""
import hashlib,json,math
import numpy as np
from datetime import datetime,timezone

FAMILIES=('trend_breakout','trend_pullback','mean_reversion')
def setup(db):
    with db() as c:c.executescript('''CREATE TABLE IF NOT EXISTS strategy_research_runs(id INTEGER PRIMARY KEY,at TEXT,payload TEXT);
    CREATE TABLE IF NOT EXISTS strategy_shadow(id TEXT PRIMARY KEY,at TEXT,source_day TEXT,symbol TEXT,family TEXT,horizon INTEGER,forecast REAL,matured TEXT,actual REAL,benchmark REAL);''')
def qualifies(family,x):
    # Feature vector: returns, relative means/volume, prior-20-session high.
    if family=='trend_breakout':return x[2]>0 and x[3]>0 and x[4]>0 and x[5]>=1 and x[6]>0
    if family=='trend_pullback':return x[2]>0 and x[0]<0 and x[4]>0
    return x[3]<-.03 and x[0]<0
def prepare(datasets):
    out={}
    for symbol,frame in datasets.items():
        f=frame.sort_index();close=f['Close'];vol=f['Volume']
        x=np.column_stack([close.pct_change(n) for n in (1,5,20)]+[close/close.rolling(20).mean()-1,close/close.rolling(50).mean()-1,vol/vol.shift().rolling(20).mean(),close/f['High'].shift().rolling(20).max()-1])
        if len(f)<300 or not np.isfinite(f[['Open','High','Low','Close','Volume']].to_numpy()).all() or (f[['Open','Close']]<=0).any().any():raise ValueError('Need 300 valid completed daily prices for each research ticker')
        out[symbol]=(f,x)
    return out
def metrics(rows,model,horizon,cost=.004):
    selected=[];last={};predict=lambda r:float(model.predict([r['x']])[0])
    for r in sorted(rows,key=lambda r:(r['day'],r['symbol'])):
        if r['day']<=last.get(r['symbol'],'') or predict(r)<=cost:continue
        selected.append(r);last[r['symbol']]=r['label_day']
    net=[r['y']-cost for r in selected]
    return {'independent_samples':len(net),'mean_net_pct':float(np.mean(net)*100) if net else None,'win_rate_pct':float(np.mean(np.array(net)>0)*100) if net else None,'worst_position_return_pct':min(net)*100 if net else None,'all_cash_return_pct':0,'matched_buy_hold_mean_pct':float(np.mean([r['y'] for r in selected])*100) if selected else None,'selection_score':float(np.mean(net)-.5*np.std(net)) if len(net)>=10 else -1}
def train(db,datasets,now):
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler
    from sklearn.linear_model import Ridge
    setup(db);prepared=prepare(datasets)
    dates=sorted(set.intersection(*[set(f.index.strftime('%Y-%m-%d')) for f,x in prepared.values()]))
    if len(dates)<300:raise ValueError('Need 300 shared completed sessions')
    a,b=dates[int(len(dates)*.6)],dates[int(len(dates)*.8)];trials=[];all_rows={};models={}
    for family in FAMILIES:
        for horizon in (3,5):
            key=family+'_'+str(horizon);rows=[]
            for symbol,(f,x) in prepared.items():
                for i in range(50,len(f)-horizon):
                    if not np.isfinite(x[i]).all() or not qualifies(family,x[i]):continue
                    rows.append({'symbol':symbol,'day':str(f.index[i].date()),'label_day':str(f.index[i+horizon].date()),'x':x[i].tolist(),'y':float(f.iloc[i+horizon]['Close']/f.iloc[i+1]['Open']-1)})
            parts={'train':[r for r in rows if r['label_day']<a],'validation':[r for r in rows if a<=r['day'] and r['label_day']<b],'test':[r for r in rows if r['day']>=b]}
            if len(parts['train'])<50 or len(parts['validation'])<20:
                trials.append({'name':key,'family':family,'horizon':horizon,'status':'insufficient chronological signal samples'});continue
            # Fixed regularization; family/horizon selected on validation only.
            model=make_pipeline(StandardScaler(),Ridge(alpha=10.)).fit([r['x'] for r in parts['train']],[r['y'] for r in parts['train']])
            validation=metrics(parts['validation'],model,horizon)
            trials.append({'name':key,'family':family,'horizon':horizon,'status':'evaluated','validation':validation})
            models[key]=model;all_rows[key]=parts
    evaluated=[r for r in trials if r['status']=='evaluated'];selected=max(evaluated,key=lambda r:r['validation']['selection_score']) if evaluated else None
    # Choice is frozen before any later test is inspected.
    for r in evaluated:r['test']=metrics(all_rows[r['name']]['test'],models[r['name']],r['horizon']);r['cost_stress_100bps']=metrics(all_rows[r['name']]['test'],models[r['name']],r['horizon'],.01)
    candidate=selected['name'] if selected and selected['validation']['selection_score']>0 else None
    digest=hashlib.sha256(''.join(s+f.to_csv() for s,(f,x) in sorted(prepared.items())).encode()).hexdigest()
    with db() as c:prior=c.execute('SELECT payload FROM strategy_research_runs ORDER BY id DESC LIMIT 1').fetchone()
    old=json.loads(prior[0]) if prior else {};reused=bool(old and old.get('test_end','')>=b)
    report={'at':now.isoformat(),'algorithm':'Standardized Ridge return forecasts for three rule-defined families at 3/5-session horizons','train_label_before':a,'validation_label_before':b,'test_start':b,'test_end':dates[-1],'fingerprint':digest,'selected_on_validation':candidate,'trials':trials,'test_reused':reused,'production_strategy_changed':False,'verdict':'Shadow candidate only; new forward outcomes required' if candidate else 'No candidate passed validation; keep cash/shadow observation','limitations':['Historical next-open to future-close labels are not executable stop/target outcomes or portfolio P&L.','Signals selected using validation only; repeated runs reuse historical tests.','40 bps assumed round-trip costs; 100 bps stress shown. Selected current tickers have selection bias.','Shadow forecasts are not orders; current production learned policy keeps its separate risk and promotion checks.','One week cannot establish human superiority or a reliable profitable edge.']}
    with db() as c:
        c.execute('INSERT INTO strategy_research_runs(at,payload) VALUES(?,?)',(now.isoformat(),json.dumps(report)))
        for r in evaluated:
            # Frozen choice/fit evaluated above. Refit matured data only for future shadow use.
            rows=sum(all_rows[r['name']].values(),[]);model=models[r['name']];model.fit([v['x'] for v in rows],[v['y'] for v in rows])
            for symbol,(f,x) in prepared.items():
                if not np.isfinite(x[-1]).all() or not qualifies(r['family'],x[-1]):continue
                source=str(f.index[-1].date());key=hashlib.sha256((r['name']+symbol+source).encode()).hexdigest()
                c.execute('INSERT OR IGNORE INTO strategy_shadow VALUES(?,?,?,?,?,?,?,NULL,NULL,NULL)',(key,now.isoformat(),source,symbol,r['family'],r['horizon'],float(model.predict([x[-1]])[0])))
        pending=c.execute('SELECT * FROM strategy_shadow WHERE matured IS NULL').fetchall()
        for r in pending:
            if r['symbol'] not in datasets:continue
            f=datasets[r['symbol']];after=max(r['source_day'],r['at'][:10]);future=f.loc[f.index.strftime('%Y-%m-%d')>after]
            if len(future)<r['horizon']:continue
            segment=future.iloc[:r['horizon']];actual=float(segment.iloc[-1]['Close']/segment.iloc[0]['Open']-1)-.004;bench=None
            spy=datasets.get('SPY')
            if spy is not None and all(day in spy.index for day in (segment.index[0],segment.index[-1])):bench=float(spy.loc[segment.index[-1],'Close']/spy.loc[segment.index[0],'Open']-1)-.004
            c.execute('UPDATE strategy_shadow SET matured=?,actual=?,benchmark=? WHERE id=?',(now.isoformat(),actual,bench,r['id']))
    return report
def status(db):
    setup(db)
    with db() as c:
        r=c.execute('SELECT payload FROM strategy_research_runs ORDER BY id DESC LIMIT 1').fetchone()
        forward=[dict(v) for v in c.execute('SELECT family,horizon,COUNT(*) predictions,SUM(matured IS NOT NULL) settled,AVG(actual)*100 mean_net_pct,AVG(actual-benchmark)*100 mean_excess_spy_pct FROM strategy_shadow GROUP BY family,horizon')]
    return {'latest':json.loads(r[0]) if r else None,'forward':forward}
