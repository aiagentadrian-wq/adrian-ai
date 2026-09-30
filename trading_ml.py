"""Real supervised trend learning, purged time splits, portable JSON forest models."""
import math
from datetime import datetime,timedelta
from zoneinfo import ZoneInfo

FEATURES=['return_1','return_5','return_20','distance_sma20','distance_sma50','sma20_vs_sma50','relative_volume20','atr14_fraction','close_in_range','prior20_breakout_distance']
def features(bars,i):
    if i<50:raise ValueError('Need 50 prior bars')
    close=bars[i]['close'];prior=bars[i-20:i];sma20=sum(b['close'] for b in bars[i-19:i+1])/20;sma50=sum(b['close'] for b in bars[i-49:i+1])/50
    volume=sum(b['volume'] for b in prior)/20
    atr=sum(max(bars[j]['high']-bars[j]['low'],abs(bars[j]['high']-bars[j-1]['close']),abs(bars[j]['low']-bars[j-1]['close'])) for j in range(i-13,i+1))/14
    span=bars[i]['high']-bars[i]['low']
    result=[close/bars[i-1]['close']-1,close/bars[i-5]['close']-1,close/bars[i-20]['close']-1,close/sma20-1,close/sma50-1,sma20/sma50-1,bars[i]['volume']/volume if volume else 0,atr/close,(close-bars[i]['low'])/span if span else .5,close/max(b['high'] for b in prior)-1]
    if not all(math.isfinite(x) for x in result):raise ValueError('Nonfinite learning features')
    return result

def samples(datasets,horizon=5):
    rows=[];local=ZoneInfo('America/Toronto')
    for symbol,bars in datasets.items():
        for i in range(50,len(bars)-horizon):
            start=datetime.fromisoformat(bars[i]['time'].replace('Z','+00:00'))
            finish=datetime.fromisoformat(bars[i+horizon]['time'].replace('Z','+00:00'))
            # Day-trading labels must finish within the same regular session.
            if start.astimezone(local).date()!=finish.astimezone(local).date():continue
            local_time=start.astimezone(local)
            if not (9,30)<=(local_time.hour,local_time.minute)<=(14,30):continue
            net=bars[i+horizon]['close']/bars[i+1]['open']-1-.004
            rows.append({'symbol':symbol,'time':bars[i]['time'],'label_time':bars[i+horizon]['time'],'x':features(bars,i),'y':int(net>0),'net_return':net})
    return sorted(rows,key=lambda r:(r['time'],r['symbol']))

def probability(model,x):
    if len(x)!=len(FEATURES) or not all(math.isfinite(float(v)) for v in x):raise ValueError('Invalid model input')
    values=[]
    for tree in model['trees']:
        i=0
        while tree['left'][i]!=-1:i=tree['left'][i] if x[tree['feature'][i]]<=tree['threshold'][i] else tree['right'][i]
        values.append(tree['positive'][i])
    return sum(values)/len(values)

def metrics(rows,model,threshold=.65):
    predictions=[probability(model,r['x']) for r in rows]
    selected=[];last={}
    for r,p in zip(rows,predictions):
        if p<threshold or r['time']<=last.get(r['symbol'],''):continue
        selected.append(r);last[r['symbol']]=r['label_time']
    total=sum(r['net_return'] for r in selected)
    return {'sample_count':len(rows),'positive_labels':sum(r['y'] for r in rows),'accuracy':round(sum((p>=.5)==bool(r['y']) for r,p in zip(rows,predictions))/len(rows),4) if rows else None,
            'brier_score':round(sum((p-r['y'])**2 for r,p in zip(rows,predictions))/len(rows),4) if rows else None,'selected_nonoverlap_samples':len(selected),
            'selected_mean_net_return_pct':round(total/len(selected)*100,4) if selected else None,'selected_positive_pct':round(sum(r['y'] for r in selected)/len(selected)*100,2) if selected else None,
            'note':'Predictive labels use next open to fifth future close minus 40 bps; these are not bracket-order backtest results or portfolio returns.'}

def export(forest):
    positive_index=list(forest.classes_).index(1)
    trees=[]
    for estimator in forest.estimators_:
        t=estimator.tree_;values=t.value[:,0,:];denom=values.sum(axis=1)
        trees.append({'left':t.children_left.tolist(),'right':t.children_right.tolist(),'feature':t.feature.tolist(),'threshold':t.threshold.tolist(),'positive':(values[:,positive_index]/denom).tolist()})
    return {'type':'RandomForestClassifier','features':FEATURES,'trees':trees,'parameters':forest.get_params(),'importance':forest.feature_importances_.tolist()}

def train(datasets):
    from sklearn.ensemble import RandomForestClassifier
    rows=samples(datasets);times=sorted({r['time'] for r in rows})
    if len(rows)<300 or len(times)<120:raise ValueError('Need at least 300 labelled rows and 120 distinct intraday times')
    a=times[int(len(times)*.6)];b=times[int(len(times)*.8)]
    training=[r for r in rows if r['label_time']<a]
    validation=[r for r in rows if a<=r['time'] and r['label_time']<b]
    test=[r for r in rows if r['time']>=b]
    if any(len(x)<50 or len({r['y'] for r in x})<2 for x in [training,validation,test]):raise ValueError('Insufficient positive/negative labels in a time split')
    trials=[]
    for depth,leaf in [(3,20),(4,15),(5,10)]:
        forest=RandomForestClassifier(n_estimators=40,max_depth=depth,min_samples_leaf=leaf,class_weight='balanced',random_state=17,n_jobs=1)
        forest.fit([r['x'] for r in training],[r['y'] for r in training]);model=export(forest)
        trials.append({'model':model,'validation':metrics(validation,model)})
    selected=min(trials,key=lambda t:t['validation']['brier_score']);model=selected['model']
    results={'training':metrics(training,model),'validation':selected['validation'],'test':metrics(test,model)}
    eligible=results['test']['selected_nonoverlap_samples']>=10 and (results['test']['selected_mean_net_return_pct'] or -1)>0 and (results['validation']['selected_mean_net_return_pct'] or -1)>0
    report={'algorithm':'Supervised random forest, 40 trees; bounded depth/leaf candidates selected by validation Brier score','features':FEATURES,'target':'Positive next-open to fifth subsequent 15-minute close return after a 40-bps round trip; same-session labels only',
            'parameters':{k:model['parameters'][k] for k in ['n_estimators','max_depth','min_samples_leaf']},'splits':{'training_last_label':max(r['label_time'] for r in training),'validation_first':min(r['time'] for r in validation),'validation_last_label':max(r['label_time'] for r in validation),'test_first':min(r['time'] for r in test),'test_last':max(r['label_time'] for r in test)},
            'metrics':results,'trials':[{'parameters':{k:t['model']['parameters'][k] for k in ['max_depth','min_samples_leaf']},'validation':t['validation']} for t in trials],
            'paper_eligible':eligible,'verdict':'Eligible for bounded paper experiment; no profitable edge proven' if eligible else 'Learned model did not pass experimental paper-entry checks; no automatic entry',
            'feature_importance':{k:round(float(v),4) for k,v in zip(FEATURES,model['importance'])},
            'limitations':['Uncalibrated class-balanced model score is not a guaranteed probability of a profitable trade.','Price/volume features cannot recognize every event or replace news, quote and broker checks.','Purged chronological splits; candidate chosen on validation, final later test not used to choose parameters.','Retesting/retraining reuses historical test data; new forward-paper results remain essential.','Predictive labels are different from executable bracket outcomes; actual fills, fees and journal determine paper results.']}
    # Refit the frozen choice on matured historical labels for deployment, AFTER reporting
    # the untouched chronological evaluation; deployment model has no test-performance claim.
    chosen=RandomForestClassifier(n_estimators=40,max_depth=model['parameters']['max_depth'],min_samples_leaf=model['parameters']['min_samples_leaf'],class_weight='balanced',random_state=17,n_jobs=1)
    chosen.fit([r['x'] for r in rows],[r['y'] for r in rows]);return export(chosen),report


def train_outcomes(outcomes):
    """A separate learner of actual settled broker trade outcomes, once enough exist."""
    from sklearn.ensemble import RandomForestClassifier
    rows=sorted(outcomes,key=lambda r:r['entry_time'])
    if len(rows)<40:return None,{'trained':False,'settled_trades':len(rows),'reason':'Need at least 40 settled paper trades before learning actual fill outcomes.'}
    boundary=rows[int(len(rows)*.7)]['entry_time']
    earlier=[r for r in rows if r['closed_time']<boundary]
    later=[r for r in rows if r['entry_time']>=boundary]
    if len(earlier)<20 or len(later)<10 or any(len({int(r['net_pnl']>0) for r in group})<2 for group in [earlier,later]):return None,{'trained':False,'settled_trades':len(rows),'reason':'Need enough matured winners and losers in both chronological periods.'}
    learner=RandomForestClassifier(n_estimators=30,max_depth=3,min_samples_leaf=5,class_weight='balanced',random_state=17,n_jobs=1)
    learner.fit([r['features'] for r in earlier],[int(r['net_pnl']>0) for r in earlier]);model=export(learner)
    predictions=[probability(model,r['features']) for r in later]
    error=sum((p-int(r['net_pnl']>0))**2 for r,p in zip(later,predictions))/len(later)
    base=sum(r['net_pnl']>0 for r in earlier)/len(earlier)
    baseline_error=sum((base-int(r['net_pnl']>0))**2 for r in later)/len(later)
    return model,{'trained':True,'settled_trades':len(rows),'training':len(earlier),'later_test':len(later),'brier_score':round(error,4),'constant_baseline_brier':round(baseline_error,4),'eligible_as_extra_filter':error<baseline_error,'reason':'Actual broker fills minus fixed cost reserve; extra filter only, never larger risk. Repeated test reuse still applies.'}
