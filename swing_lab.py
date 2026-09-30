"""Bounded causal swing strategy experiments. Never submits broker orders."""
import math

BASE={'lookback':20,'trend':20,'stop_days':5,'hold_days':10,'reward_risk':2.0,'volume_ratio':1.0}

def rules(params):
    p=dict(BASE);p.update(params)
    allowed={'lookback':(10,20,30),'trend':(10,20,30),'stop_days':(3,5,7),'hold_days':(5,10,15),'reward_risk':(1.8,2.0,2.5,3.0),'volume_ratio':(.8,1.0,1.2)}
    if set(params)-set(allowed):raise ValueError('Unsupported strategy parameter')
    if any(p[k] not in choices for k,choices in allowed.items()):raise ValueError('Parameter outside the tested strategy family')
    return p

def signal(bars,i,params):
    p=rules(params)
    if i<50:return None
    prior=bars[i-p['lookback']:i];b=bars[i]
    ma=sum(x['close'] for x in bars[i-p['trend']+1:i+1])/p['trend']
    slow=sum(x['close'] for x in bars[i-49:i+1])/50
    volume=sum(x['volume'] for x in bars[i-20:i])/20
    if volume<=0 or b['close']<=max(x['high'] for x in prior) or not b['close']>ma>slow or b['volume']/volume<p['volume_ratio']:return None
    entry=round(b['high']+.01,2);stop=round(min(x['low'] for x in bars[i-p['stop_days']+1:i+1])-.01,2)
    risk=entry-stop
    if not 0<risk/entry<=.08:return None
    return {'entry':entry,'maximum_entry':round(entry*1.005,2),'stop':stop,'target':round(entry+p['reward_risk']*risk,2),
            'relative_volume':round(b['volume']/volume,2),'signal_date':b['time'][:10],
            'reason':f"Completed daily close broke the prior {p['lookback']}-session high; price above SMA{p['trend']} above SMA50; volume {b['volume']/volume:.2f}x prior 20-session mean."}

def replay(bars,params,start,end,cost_bps=20,capital=2000):
    p=rules(params);equity=peak=float(capital);drawdown=0;trades=[];i=max(50,start)
    while i<end-1:
        plan=signal(bars,i,p)
        if not plan:i+=1;continue
        b=bars[i+1];trigger=plan['entry']
        if b['high']<trigger or b['open']>plan['maximum_entry']:i+=1;continue
        entry=max(b['open'],trigger);stop=plan['stop'];risk=entry-stop
        if not 0<risk/entry<=.08:i+=1;continue
        friction=entry*2*cost_bps/10000
        quantity=max(0,min(math.floor(equity*.0025/(risk+friction)),math.floor(equity/entry)))
        if quantity<1:i+=1;continue
        target=entry+p['reward_risk']*risk;last=min(i+p['hold_days'],end-1);exit_price=bars[last]['close'];reason='time exit' if last<end-1 else 'segment boundary exit'
        for j in range(i+1,last+1):
            candle=bars[j]
            if j>i+1 and candle['open']<=stop:exit_price=candle['open'];last=j;reason='gap stop';break
            if candle['low']<=stop:exit_price=stop;last=j;reason='stop first if path ambiguous';break
            if candle['high']>=target:exit_price=target;last=j;reason='target';break
        costs=quantity*(entry+exit_price)*cost_bps/10000
        profit=quantity*(exit_price-entry)-costs
        equity+=profit;peak=max(peak,equity);drawdown=min(drawdown,(equity/peak-1)*100)
        trades.append({'signal':bars[i]['time'],'entry_date':bars[i+1]['time'],'exit_date':bars[last]['time'],'entry':round(entry,2),'stop':stop,'target':round(target,2),'exit':round(exit_price,2),'quantity':quantity,'net_pnl':round(profit,2),'net_r':profit/(quantity*risk),'reason':reason})
        i=last+1
    wins=[t for t in trades if t['net_pnl']>0];gross=sum(t['net_pnl'] for t in wins);loss=-sum(t['net_pnl'] for t in trades if t['net_pnl']<0)
    benchmark=(bars[end-1]['close']/bars[max(50,start)+1]['open']-1)*100-2*cost_bps/100
    return {'trades':trades,'trade_count':len(trades),'net_return_pct':round((equity/capital-1)*100,3),'net_pnl_example_usd':round(equity-capital,2),'example_starting_capital_usd':capital,
            'max_drawdown_pct':round(drawdown,3),'win_rate_pct':round(100*len(wins)/len(trades),2) if trades else None,
            'expectancy_r':round(sum(t['net_r'] for t in trades)/len(trades),3) if trades else None,'profit_factor':round(gross/loss,3) if loss else None,'buy_hold_net_pct':round(benchmark,3),'cost_bps_each_side':cost_bps}

def aggregate(results):
    count=sum(r['trade_count'] for r in results)
    return {'trade_count':count,'mean_independent_account_return_pct':round(sum(r['net_return_pct'] for r in results)/len(results),3),
            'worst_independent_drawdown_pct':min(r['max_drawdown_pct'] for r in results),'expectancy_r':round(sum((r['expectancy_r'] or 0)*r['trade_count'] for r in results)/count,3) if count else None,
            'win_rate_pct':round(sum((r['win_rate_pct'] or 0)*r['trade_count'] for r in results)/count,2) if count else None,
            'note':'Each symbol is simulated in its own $2,000 account. This is not a combined portfolio or income forecast.'}

def score(summary):
    if summary['trade_count']<10:return -10000+summary['trade_count']
    return summary['mean_independent_account_return_pct']+summary['worst_independent_drawdown_pct']*.5

def experiment(datasets,baseline=None,reused=False):
    baseline=rules(baseline or BASE)
    if not datasets or any(len(b)<300 for b in datasets.values()):raise ValueError('At least 300 completed daily bars per symbol required')
    # Common date boundaries prevent a different ticker from leaking later history.
    dates=sorted(set.intersection(*[{b['time'][:10] for b in bars} for bars in datasets.values()]))
    if len(dates)<300:raise ValueError('At least 300 shared completed sessions required')
    datasets={s:[b for b in bars if b['time'][:10] in set(dates)] for s,bars in datasets.items()}
    n=len(dates);train_end=int(n*.6);validate_end=int(n*.8)
    windows={'training':(50,train_end),'validation':(train_end,validate_end),'test':(validate_end,n)}
    candidates=[baseline]
    for key,choices in [('lookback',(10,30)),('stop_days',(3,7)),('hold_days',(5,15)),('reward_risk',(1.8,2.5)),('volume_ratio',(.8,1.2))]:
        for value in choices:
            p=dict(baseline);p[key]=value
            if p not in candidates:candidates.append(p)
    def evaluate(p,window,cost=20):
        a,b=windows[window];items={s:replay(bars,p,a,b,cost) for s,bars in datasets.items()}
        return {'summary':aggregate(list(items.values())),'symbols':items}
    trials=[{'parameters':p,'training':evaluate(p,'training')['summary']} for p in candidates]
    ranked=sorted(trials,key=lambda x:score(x['training']),reverse=True)
    # Freeze candidate before inspecting later periods. It is never chosen on test returns.
    candidate=ranked[0]['parameters']
    comparisons={name:{'baseline':evaluate(baseline,name),'candidate':evaluate(candidate,name)} for name in windows}
    test=comparisons['test'];validation=comparisons['validation']
    delta={key:round(test['candidate']['summary'][key]-test['baseline']['summary'][key],3) for key in ['mean_independent_account_return_pct','worst_independent_drawdown_pct']}
    enough=test['candidate']['summary']['trade_count']>=20 and validation['candidate']['summary']['trade_count']>=10
    better=delta['mean_independent_account_return_pct']>0 and delta['worst_independent_drawdown_pct']>=-1 and validation['candidate']['summary']['mean_independent_account_return_pct']>0 and test['candidate']['summary']['mean_independent_account_return_pct']>0
    verdict='Promising for forward-paper evaluation only' if enough and better and not reused else 'No reliable improvement established; keep experimental'
    return {'strategy_family':'Daily trend-filtered close breakout; next-session trigger; 0.5% chase cap; structural stop; whole shares; 0.25% account risk including modelled costs',
            'baseline':baseline,'candidate':candidate,'changes':{k:{'before':baseline[k],'after':candidate[k]} for k in baseline if baseline[k]!=candidate[k]},'candidate_count':len(trials),'selection':'Training only: net account return minus half absolute maximum closed-trade drawdown; require 10 training trades.',
            'periods':{name:{'start':dates[a],'end':dates[b-1],'sessions':b-a} for name,(a,b) in windows.items()},'comparisons':comparisons,'test_improvement':delta,'training_trials':trials,'verdict':verdict,
            'test_period_reused':reused,'cost_stress':{str(cost):evaluate(candidate,'test',cost)['summary'] for cost in [5,20,50]},
            'limitations':['Historical experiment, not a validated income model. Current selected tickers introduce survivorship/selection bias.','Daily bars cannot reveal intraday price order; stop assumed first on ambiguous bars, including entry bar.','Costs are fixed scenarios, not measured fills. No intratrade mark-to-market drawdown; reported drawdown is closed-trade only.','Segment-end positions are force-closed; independent symbol accounts are not an executable combined portfolio.','Repeated improvement runs reuse later data: it is no longer untouched out-of-sample evidence. Fresh forward-paper results are required.','No strategy is automatically activated and no order endpoint is called by this lab.']}
