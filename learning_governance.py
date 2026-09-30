"""Forward-only paper evidence, bounded experiments and outcome calibration."""
import json,hashlib,math
from datetime import datetime,timedelta,timezone
import numpy as np

SCHEMA='''CREATE TABLE IF NOT EXISTS research_predictions(id TEXT PRIMARY KEY,model_id INTEGER,symbol TEXT,source_day TEXT,recorded TEXT,horizon INTEGER,features TEXT,forecast REAL,allowance REAL,cost REAL,regime TEXT,matured TEXT,actual REAL,benchmark REAL,drawdown REAL);
CREATE TABLE IF NOT EXISTS research_trades(entry_client TEXT PRIMARY KEY,symbol TEXT,track TEXT,model_id INTEGER,opened TEXT,plan TEXT,basis REAL,quantity REAL,peak REAL,drawdown REAL DEFAULT 0,closed TEXT,exit_value REAL,net REAL,reason TEXT);
CREATE TABLE IF NOT EXISTS research_exits(exit_client TEXT PRIMARY KEY,entry_client TEXT,quantity REAL,value REAL);
'''

def setup(store):
    with store.connect() as c:c.executescript(SCHEMA)

def record_predictions(store,version,symbol,source_day,features,forecasts,errors,regime,now,cost=.004):
    setup(store)
    with store.connect() as c:
        for h,p,e in zip((1,2,3,5,10,20),forecasts,errors):
            key=hashlib.sha256(f'{version}:{symbol}:{source_day}:{h}'.encode()).hexdigest()
            c.execute('INSERT OR IGNORE INTO research_predictions VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',(key,version,symbol,source_day,now.isoformat(),h,json.dumps(list(map(float,features))),float(p),float(e),cost,regime,None,None,None,None))

def mature(store,datasets,now):
    """Use first daily OPEN strictly after the recording day, never a past open."""
    setup(store)
    with store.connect() as c:
        rows=c.execute('SELECT * FROM research_predictions WHERE matured IS NULL').fetchall()
        for r in rows:
            prices=datasets.get(r['symbol']);benchmark=datasets.get('SPY')
            if prices is None or benchmark is None:continue
            start=max(r['source_day'],r['recorded'][:10]);future=prices.loc[prices.index.strftime('%Y-%m-%d')>start]
            if len(future)<r['horizon']:continue
            segment=future.iloc[:r['horizon']];first,last=segment.index[0],segment.index[-1]
            if first not in benchmark.index or last not in benchmark.index:continue
            entry=float(segment.iloc[0]['Open']);actual=float(segment.iloc[-1]['Close'])/entry-1
            base=float(benchmark.loc[last,'Close'])/float(benchmark.loc[first,'Open'])-1
            dd=float(segment['Low'].min())/entry-1
            c.execute('UPDATE research_predictions SET matured=?,actual=?,benchmark=?,drawdown=? WHERE id=?',(now.isoformat(),actual,base,min(0,dd),r['id']))

def promotion(store,model_id,report):
    """One-session matched SPY benchmark, genuinely forward after frozen creation."""
    setup(store)
    with store.connect() as c:rows=c.execute('SELECT * FROM research_predictions WHERE model_id=? AND horizon=1 AND matured IS NOT NULL AND forecast-allowance-cost>0',(model_id,)).fetchall()
    days={r['source_day'] for r in rows};regimes={r['regime'] for r in rows}
    reason='Need 30 qualifying forward outcomes over 10 dates and at least two regimes, plus positive historical validation/test.'
    planned=report.get('planned_exit_tests',{})
    historical_ok=bool(planned) and all(np.mean([r['net_return_pct']-r['exposure_matched_buy_hold_pct'] for r in planned.get(period,{}).get(str(cost),{}).values()])>0 for period in ('validation','test') for cost in (20,50))
    eligible=historical_ok and len(rows)>=30 and len(days)>=10 and len(regimes)>=2 and report.get('paper_eligible',False)
    edge=np.mean([r['actual']-r['benchmark'] for r in rows]) if rows else 0
    net=np.mean([r['actual']-r['cost'] for r in rows]) if rows else 0
    champion=store.get('research_champion')
    daily_net=[np.mean([r['actual']-r['cost'] for r in rows if r['source_day']==day]) for day in days]
    daily_edge=[np.mean([r['actual']-r['benchmark'] for r in rows if r['source_day']==day]) for day in days]
    def lower(values):return float(np.mean(values)-1.96*np.std(values,ddof=1)/math.sqrt(len(values))) if len(values)>1 else -1
    if eligible and lower(daily_net)>0 and lower(daily_edge)>0:
        if champion and champion!=model_id:
            with store.connect() as c:old=c.execute('SELECT * FROM research_predictions WHERE model_id=? AND horizon=1 AND matured IS NOT NULL',(champion,)).fetchall()
            paired={(r['symbol'],r['source_day']):r for r in old}
            pairs=[(r,paired[(r['symbol'],r['source_day'])]) for r in rows if (r['symbol'],r['source_day']) in paired]
            if len(pairs)<30:return {'promoted':False,'reason':'Insufficient same-date comparison with incumbent.','count':len(rows)}
            new_mae=np.mean([abs(a['forecast']-a['actual']) for a,b in pairs]);old_mae=np.mean([abs(b['forecast']-b['actual']) for a,b in pairs])
            if new_mae>=old_mae:return {'promoted':False,'reason':'Candidate did not improve matched forward forecast error.','count':len(rows)}
        store.put('research_champion',model_id);reason='Forward net return, SPY excess return and incumbent comparison passed.'
    else:eligible=False
    result={'promoted':eligible,'reason':reason,'count':len(rows),'dates':len(days),'regimes':len(regimes),'mean_net_return':float(net),'mean_excess_over_spy':float(edge)}
    store.put('research_promotion',result);return result

def choose(decisions,champion,model_id,remaining_sessions,store):
    """Only positive post-cost experiments; ties produce WAIT rather than list order."""
    max_h=min(5,max(0,remaining_sessions));candidates=[]
    for original in decisions:
        if original['action'] in ('HOLD','EXIT'):continue
        options=[p for p in original['forecasts'] if p['horizon_sessions']<=max_h]
        if not options:continue
        p=max(options,key=lambda p:p['score_per_session'])
        if p['forecast_gross_return']-.004<=0:continue
        track='performance' if champion==model_id and p['conservative_net_estimate']>0 else 'experimental'
        d=dict(original,selected=p,action='BUY',model_action=original['action'],track=track,exploration=track=='experimental')
        d['reason']='Test learned price/volume return forecast over '+str(p['horizon_sessions'])+' sessions; raw forecast exceeds assumed round-trip costs. '+('Forward promotion passed.' if track=='performance' else 'Uncertainty still prevents a validated trade; tightly budgeted experiment.')
        candidates.append(d)
    candidates.sort(key=lambda d:d['selected']['score_per_session'],reverse=True)
    if not candidates:return [],'No positive post-cost forecast within the remaining experiment horizon.'
    if len(candidates)>1 and candidates[0]['selected']['score_per_session']-candidates[1]['selected']['score_per_session']<.0001:
        return [],'Leading candidates are indistinguishable (less than 1 basis point per session); no list-order selection.'
    return candidates[:1],'Distinct candidate; check budget and execution conditions.'

def experiment_available(store):
    setup(store)
    with store.connect() as c:
        rows=c.execute("SELECT basis,net,closed FROM research_trades WHERE track='experimental'").fetchall()
    used=sum(float(r['basis']) for r in rows if not r['closed'])+sum(max(0,-float(r['net'] or 0)) for r in rows if r['closed'])
    return max(0,100-used) # $100 experiment capital/loss envelope, not renewed daily

def plan_exit(d,entry,notional,now,expiry):
    # Risk limits are explicit controls, not indicators pretending to be learned.
    fraction=.02 if d['track']=='experimental' else .03
    return {'stop_price':round(entry*(1-fraction),4),'target_price':round(entry*(1+max(d['selected']['forecast_gross_return'],fraction)),4),'max_planned_loss_usd':round(notional*fraction,2),'maximum_capital_loss_usd':notional,'exit_by':expiry,'horizon_sessions':d['selected']['horizon_sessions'],'rule':'Exit on observed stop, target, horizon, model invalidation or shared limits; gaps/latency can exceed planned loss. App-managed; no broker stop claimed.'}

def register_trade(store,entry_client,symbol,plan,basis,quantity,opened):
    setup(store)
    with store.connect() as c:c.execute('INSERT INTO research_trades VALUES(?,?,?,?,?,?,?,?,?,?,NULL,NULL,NULL,NULL) ON CONFLICT(entry_client) DO UPDATE SET basis=excluded.basis,quantity=excluded.quantity',(entry_client,symbol,plan.get('track','legacy'),plan.get('model_version',0),opened,json.dumps(plan),basis,quantity,basis,0))

def record_exit(store,exit_client,entry_client,quantity,value,reason,now):
    setup(store)
    with store.connect() as c:
        row=c.execute('SELECT * FROM research_trades WHERE entry_client=?',(entry_client,)).fetchone()
        if not row:return
        c.execute('INSERT INTO research_exits VALUES(?,?,?,?) ON CONFLICT(exit_client) DO UPDATE SET quantity=excluded.quantity,value=excluded.value',(exit_client,entry_client,quantity,value))
        total=c.execute('SELECT SUM(quantity),SUM(value) FROM research_exits WHERE entry_client=?',(entry_client,)).fetchone()
        if total[0]>=row['quantity']-1e-6:
            net=total[1]-row['basis']-.002*(total[1]+row['basis'])
            c.execute('UPDATE research_trades SET closed=?,exit_value=?,net=?,reason=? WHERE entry_client=?',(now.isoformat(),total[1],net,reason,entry_client))

def monitor(store,positions,now):
    setup(store);exits=[]
    with store.connect() as c:
        for row in c.execute('SELECT * FROM research_trades WHERE closed IS NULL').fetchall():
            p=next((p for p in positions if p['symbol']==row['symbol']),None)
            if not p:continue
            value=float(p.get('market_value') or 0);peak=max(row['peak'],value);dd=min(row['drawdown'],value/peak-1 if peak else 0)
            c.execute('UPDATE research_trades SET peak=?,drawdown=? WHERE entry_client=?',(peak,dd,row['entry_client']))
            rule=json.loads(row['plan']).get('exit_plan');price=float(p.get('current_price') or 0)
            if not rule:continue
            reason=''
            if now>=datetime.fromisoformat(rule['exit_by']):reason='Planned time exit'
            elif price>0 and price<=rule['stop_price']:reason='Planned stop observed'
            elif price>=rule['target_price']:reason='Planned target observed'
            if reason:exits.append((row['symbol'],reason))
    return exits

def scorecard(store):
    setup(store)
    with store.connect() as c:
        rows=c.execute('SELECT * FROM research_trades').fetchall();pred=c.execute('SELECT * FROM research_predictions WHERE matured IS NOT NULL').fetchall();pending=c.execute('SELECT count(*) FROM research_predictions WHERE matured IS NULL').fetchone()[0]
    tracks={}
    for track in ('experimental','performance','legacy'):
        subset=[r for r in rows if r['track']==track];closed=[r for r in subset if r['closed']];wins=[r['net'] for r in closed if r['net']>0];losses=[r['net'] for r in closed if r['net']<=0]
        tracks[track]={'open':sum(not r['closed'] for r in subset),'closed':len(closed),'estimated_net_usd':round(sum(r['net'] for r in closed),4),'net_return_on_closed_capital_pct':100*sum(r['net'] for r in closed)/sum(r['basis'] for r in closed) if closed else None,'average_win_usd':float(np.mean(wins)) if wins else None,'average_loss_usd':float(np.mean(losses)) if losses else None,'worst_observed_position_drawdown_pct':100*min([r['drawdown'] for r in subset]+[0]),'win_rate':len(wins)/len(closed) if closed else None}
    return {'tracks':tracks,'matured_predictions':len(pred),'pending_predictions':pending,'forecast_mae':float(np.mean([abs(r['forecast']-r['actual']) for r in pred])) if pred else None,'direction_accuracy':float(np.mean([(r['forecast']>0)==(r['actual']>0) for r in pred])) if pred else None,'mean_net_shadow_return':float(np.mean([r['actual']-r['cost'] for r in pred])) if pred else None,'mean_excess_over_spy':float(np.mean([r['actual']-r['benchmark'] for r in pred])) if pred else None,'champion':store.get('research_champion'),'promotion':store.get('research_promotion'),'experiment_budget_remaining_usd':experiment_available(store),'outcome_forward_comparison':store.get('outcome_forward_comparison'),'outcome_correction_active':bool(store.get('outcome_active')),'calibration':store.get('outcome_calibration',{'status':'Awaiting 30 closed trades over 10 dates; no learned outcome correction active.'}),'note':'Costs estimated at 20 bps each side, including fees/spread/slippage allowance; observed drawdown can miss between-check moves. Shadow returns use next-session open after recording, not fictitious past execution. Legacy positions remain separate.'}

def train_outcomes(store):
    """Residual learner from actual closed trades; whole-date splits avoid leakage."""
    setup(store)
    with store.connect() as c:rows=c.execute('SELECT * FROM research_trades WHERE closed IS NOT NULL ORDER BY opened').fetchall()
    samples=[]
    for r in rows:
        p=json.loads(r['plan']);x=p.get('entry_features');forecast=p.get('selected',{}).get('forecast_gross_return')
        if x and forecast is not None and r['basis']>0:samples.append((r,x+[float(p['selected']['horizon_sessions'])/20],float(forecast),(r['exit_value']-r['basis'])/r['basis']))
    existing=store.get('outcome_calibration')
    if existing and samples and existing.get('last_closed')==max(s[0]['closed'] for s in samples):return
    if existing and existing.get('improved') and not store.get('outcome_active'):return
    dates=sorted({r['opened'][:10] for r,x,f,y in samples})
    if len(samples)<30 or len(dates)<10:return
    cut1=dates[int(len(dates)*.6)];cut2=dates[int(len(dates)*.8)]
    train=[s for s in samples if s[0]['closed'][:10]<cut1];val=[s for s in samples if cut1<=s[0]['opened'][:10]<cut2 and s[0]['closed'][:10]<cut2];test=[s for s in samples if s[0]['opened'][:10]>=cut2]
    if min(map(len,(train,val,test)))<3:return
    from sklearn.linear_model import Ridge
    from sklearn.preprocessing import StandardScaler
    x=np.array([s[1] for s in train]);scaler=StandardScaler().fit(x);y=np.array([s[3]-s[2] for s in train]);trials=[]
    for alpha in (1.,10.,100.):
        model=Ridge(alpha=alpha).fit(scaler.transform(x),y)
        err=np.mean([abs(s[3]-(s[2]+float(model.predict(scaler.transform([s[1]]))[0]))) for s in val]);trials.append((err,alpha,model))
    _,alpha,model=min(trials,key=lambda x:x[0]);base=float(np.mean([abs(s[3]-s[2]) for s in test]));err=float(np.mean([abs(s[3]-(s[2]+float(model.predict(scaler.transform([s[1]]))[0]))) for s in test]))
    store.put('outcome_calibration',{'status':'Outcome learner evaluated; shadow only until forward promotion.','samples':len(samples),'train':len(train),'validation':len(val),'test':len(test),'baseline_mae':base,'candidate_mae':err,'improved':err<base,'alpha':alpha,'coefficients':model.coef_.tolist(),'intercept':float(model.intercept_),'mean':scaler.mean_.tolist(),'scale':scaler.scale_.tolist(),'last_closed':max(s[0]['closed'] for s in samples),'automatic_live_use':False})

def record_calibrated_shadow(store,version,symbol,source_day,features,forecasts,errors,regime,now):
    calibration=store.get('outcome_calibration')
    if not calibration or not calibration.get('improved'):return
    signature=hashlib.sha256(json.dumps(calibration,sort_keys=True).encode()).hexdigest()
    shadow_id=-int(signature[:10],16)
    corrected=[]
    for horizon,forecast in zip((1,2,3,5,10,20),forecasts):
        x=np.array(list(features)+[horizon/20]);scaled=(x-np.array(calibration['mean']))/np.array(calibration['scale'])
        corrected.append(float(forecast)+float(np.dot(scaled,calibration['coefficients']))+calibration['intercept'])
    record_predictions(store,shadow_id,symbol,source_day,features,corrected,errors,regime,now)
    store.put('outcome_shadow_model',{'id':shadow_id,'parent':version,'status':'Predicting forward; no order authority until separate evidence review.'})

def adopt_legacy(store,positions,deadline,now):
    setup(store)
    with store.connect() as c:
        rows=c.execute('SELECT h.*,o.payload,o.at FROM holdings h JOIN orders o ON h.entry_client=o.client_id').fetchall()
        for row in rows:
            if c.execute('SELECT 1 FROM research_trades WHERE entry_client=?',(row['entry_client'],)).fetchone():continue
            plan=json.loads(row['payload']);plan['track']='legacy'
            entry=row['entry_value']/row['quantity']
            plan['exit_plan']={'stop_price':round(entry*.98,4),'target_price':round(entry*1.02,4),'max_planned_loss_usd':round(row['entry_value']*.02,2),'maximum_capital_loss_usd':row['entry_value'],'exit_by':deadline,'horizon_sessions':None,'rule':'Legacy migration: 2% app-managed stop/target plus original experiment deadline; model invalidation can exit earlier. Not a retroactive original entry plan.'}
            c.execute('UPDATE orders SET payload=? WHERE client_id=?',(json.dumps(plan),row['entry_client']))
            c.execute('INSERT INTO research_trades VALUES(?,?,?,?,?,?,?,?,?,?,NULL,NULL,NULL,NULL)',(row['entry_client'],row['symbol'],'legacy',plan.get('model_version',0),row['at'],json.dumps(plan),row['entry_value'],row['quantity'],row['entry_value'],0))

def evaluate_outcome_shadow(store):
    candidate=store.get('outcome_shadow_model');calibration=store.get('outcome_calibration')
    if not candidate or not calibration:return
    with store.connect() as c:
        rows=c.execute('SELECT * FROM research_predictions WHERE model_id=? AND matured IS NOT NULL AND horizon=1',(candidate['id'],)).fetchall()
        base=c.execute('SELECT * FROM research_predictions WHERE model_id=? AND matured IS NOT NULL AND horizon=1',(candidate['parent'],)).fetchall()
    lookup={(r['symbol'],r['source_day']):r for r in base};pairs=[(r,lookup[(r['symbol'],r['source_day'])]) for r in rows if (r['symbol'],r['source_day']) in lookup]
    if len(pairs)<30 or len({a['source_day'] for a,b in pairs})<10 or len({a['regime'] for a,b in pairs})<2:return
    before=float(np.mean([abs(b['forecast']-b['actual']) for a,b in pairs]));after=float(np.mean([abs(a['forecast']-a['actual']) for a,b in pairs]))
    selected=[a for a,b in pairs if a['forecast']-a['allowance']-a['cost']>0]
    days=sorted({a['source_day'] for a in selected})
    daily=[np.mean([a['actual']-a['cost'] for a in selected if a['source_day']==d]) for d in days]
    edge=[np.mean([a['actual']-a['benchmark'] for a in selected if a['source_day']==d]) for d in days]
    def lower(v):return np.mean(v)-1.96*np.std(v,ddof=1)/math.sqrt(len(v)) if len(v)>1 else -1
    passed=after<before*.95 and len(selected)>=30 and len(days)>=10 and lower(daily)>0 and lower(edge)>0
    store.put('outcome_forward_comparison',{'count':len(pairs),'before_mae':before,'after_mae':after,'promoted':bool(passed)})
    if passed:store.put('outcome_active',dict(calibration,parent=candidate['parent'],forward_model_id=candidate['id']))

def corrected_forecasts(store,version,features,forecasts):
    active=store.get('outcome_active')
    if not active or active['parent']!=version:return forecasts
    values=[]
    for h,f in zip((1,2,3,5,10,20),forecasts):
        x=(np.array(list(features)+[h/20])-np.array(active['mean']))/np.array(active['scale'])
        values.append(float(f)+float(np.dot(x,active['coefficients']))+active['intercept'])
    return values

def explain_status(state):
    card=state.get('learning_scorecard') or {};tracks=card.get('tracks',{});lines=['**Paper trading: '+('enabled' if state.get('enabled') else 'entries paused')+'**',
    'Experimental trades: up to $25 each within a $100 capital/loss budget. A distinct positive raw forecast after assumed costs is required; no forced daily trades.',
    'Performance trades: require positive uncertainty-adjusted evidence and forward promotion. Both tracks share the three-position, cash-only and account loss limits.',
    'Every new entry has an app-managed stop, target and time exit. Planned losses are 2% of an experimental allocation (up to $0.50 on $25), or 3% of a performance allocation. Gaps/downtime can exceed the plan; the full allocation remains at risk.',
    'Strategy promoted: '+('yes, model '+str(card['champion']) if card.get('champion') else 'none yet')+'.']
    for name,value in tracks.items():lines.append(name.capitalize()+': '+str(value['open'])+' open / '+str(value['closed'])+' closed; estimated net after assumed costs $'+format(value['estimated_net_usd'],'.2f')+'.')
    lines.append(str(card.get('pending_predictions',0))+' predictions awaiting future outcomes; '+str(card.get('matured_predictions',0))+' evaluated. No expected profit is validated.')
    if state.get('daily_trade_status'):lines.append('Latest decision: '+state['daily_trade_status']['status'])
    lines.append('Last evaluation: '+str(state.get('last_run'))+'. Original experiment deadline: '+str(state.get('deadline'))+'.')
    lines.append('This explanation uses recorded workflow rules and results directly; it is not a fresh broker balance check.')
    return '\n\n'.join(lines)

def replay_planned(prices,features,model,errors,start,end,cost_bps):
    """Frozen-model, next-open experimental simulation with conservative OHLC exits."""
    import autonomous_swing as bot
    cash=100.;position=None;trades=[];peak=100.;drawdown=0.;cost=cost_bps/10000
    for i in range(start,end-1):
        if features.iloc[i].isna().any():continue
        next_bar=prices.iloc[i+1];d=bot.decision(bot.predict(model,features.iloc[i].to_numpy()),errors,cost_bps,position is not None)
        choices=[p for p in d['forecasts'] if p['horizon_sessions']<=min(5,end-i-1)]
        if not choices:continue
        selected=max(choices,key=lambda p:p['score_per_session'])
        if position:
            exit_price=None;reason=None
            if float(next_bar['Open'])<=position['stop']:exit_price=float(next_bar['Open']);reason='gap stop'
            elif float(next_bar['Low'])<=position['stop']:exit_price=position['stop'];reason='stop (first if target also touched)'
            elif float(next_bar['High'])>=position['target']:exit_price=position['target'];reason='target'
            elif i+1>=position['end']:exit_price=float(next_bar['Close']);reason='time'
            elif selected['forecast_gross_return']<=2*cost:exit_price=float(next_bar['Open']);reason='forecast invalidation'
            if exit_price is not None:
                proceeds=position['qty']*exit_price*(1-cost);cash+=proceeds
                benchmark=(float(prices.iloc[i+1]['Close'])/position['entry_raw']-1)-2*cost
                trades.append({'net_usd':proceeds-position['basis'],'return':proceeds/position['basis']-1,'same_symbol_buy_hold_return':benchmark,'exit_reason':reason});position=None
        elif selected['forecast_gross_return']>2*cost and cash>=25:
            entry=float(next_bar['Open'])*(1+cost);qty=25/entry;cash-=25
            position={'qty':qty,'basis':25,'stop':entry*.98,'target':entry*(1+max(.02,selected['forecast_gross_return'])),'end':min(end-1,i+selected['horizon_sessions']),'entry_raw':float(next_bar['Open'])}
            first_exit=None;first_reason=None
            if float(next_bar['Low'])<=position['stop']:first_exit=position['stop'];first_reason='entry-session stop (first if target touched)'
            elif float(next_bar['High'])>=position['target']:first_exit=position['target'];first_reason='entry-session target'
            elif i+1>=position['end']:first_exit=float(next_bar['Close']);first_reason='entry-session time exit'
            if first_exit is not None:
                proceeds=qty*first_exit*(1-cost);cash+=proceeds;trades.append({'net_usd':proceeds-25,'return':proceeds/25-1,'exit_reason':first_reason});position=None

        equity=cash+(position['qty']*float(next_bar['Close']) if position else 0);peak=max(peak,equity);drawdown=min(drawdown,equity/peak-1)
    if position:
        proceeds=position['qty']*float(prices.iloc[end-1]['Close'])*(1-cost);cash+=proceeds;trades.append({'net_usd':proceeds-position['basis'],'return':proceeds/position['basis']-1,'exit_reason':'segment end'})
    benchmark=.25*(float(prices.iloc[end-1]['Close'])/float(prices.iloc[start+1]['Open'])-1-2*cost)
    return {'net_return_pct':100*(cash/100-1),'worst_drawdown_pct':100*drawdown,'closed_trades':len(trades),'average_net_per_trade':float(np.mean([t['net_usd'] for t in trades])) if trades else None,'exposure_matched_buy_hold_pct':100*benchmark,'cost_bps_each_side':cost_bps,'note':'Independent $100 per-symbol test with $25 position; 25% buy/hold plus 75% cash benchmark. Daily OHLC cannot reproduce intraday fills. No portfolio or distinct-ranking benefit claimed.'}

def report_status(report):
    planned=report.get('planned_exit_tests')
    if not planned:return report
    summary={period:{cost:{'mean_net_return_pct':float(np.mean([r['net_return_pct'] for r in symbols.values()])), 'mean_benchmark_return_pct':float(np.mean([r['exposure_matched_buy_hold_pct'] for r in symbols.values()])), 'worst_drawdown_pct':min(r['worst_drawdown_pct'] for r in symbols.values()),'closed_trades':sum(r['closed_trades'] for r in symbols.values())} for cost,symbols in costs.items()} for period,costs in planned.items()}
    passed=all(r['mean_net_return_pct']>max(0,r['mean_benchmark_return_pct']) for costs in summary.values() for r in costs.values())
    return dict(report,planned_exit_summary=summary,paper_eligible=bool(report.get('paper_eligible') and passed),verdict='Historical planned-exit checks passed; forward promotion still required.' if passed else 'Research only: planned-exit tests did not establish an advantage over the benchmark.')
