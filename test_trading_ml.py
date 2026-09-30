import unittest,random,math
from datetime import datetime,timedelta,timezone
import trading_ml as ml

def bars(days=60,seed=17):
    rng=random.Random(seed);start=datetime(2025,1,6,14,30,tzinfo=timezone.utc);data=[];price=100
    for day in range(days):
        date=start+timedelta(days=day)
        if date.weekday()>4:continue
        drift=.0015 if (day//4)%2==0 else -.0015
        for step in range(26):
            old=price;price*=1+drift+rng.gauss(0,.002)
            data.append({'time':(date+timedelta(minutes=15*step)).isoformat(),'open':old,'close':price,'high':max(old,price)*1.001,'low':min(old,price)*.999,'volume':10000+rng.randrange(10000)})
    return data
class MachineLearningTests(unittest.TestCase):
    def test_features_are_causal_and_finite(self):
        data=bars();x=ml.features(data,100);data[101]['close']=9999
        self.assertEqual(x,ml.features(data,100));self.assertTrue(all(math.isfinite(v) for v in x))
    def test_labels_do_not_cross_session(self):
        rows=ml.samples({'SPY':bars()})
        self.assertTrue(rows)
        self.assertTrue(all(r['time'][:10]==r['label_time'][:10] for r in rows))
    def test_real_forest_training_and_purged_time_splits(self):
        model,report=ml.train({'SPY':bars(),'QQQ':bars(seed=31)})
        self.assertEqual(len(model['trees']),40)
        self.assertEqual(len(report['features']),10)
        self.assertLess(report['splits']['training_last_label'],report['splits']['validation_first'])
        self.assertLess(report['splits']['validation_last_label'],report['splits']['test_first'])
        self.assertTrue(0<=ml.probability(model,ml.features(bars(),100))<=1)
        self.assertGreater(report['metrics']['test']['sample_count'],50)
    def test_portable_model_matches_sklearn_probability(self):
        from sklearn.ensemble import RandomForestClassifier
        x=[[i/100]*10 for i in range(100)];y=[int(i>49) for i in range(100)]
        forest=RandomForestClassifier(n_estimators=5,max_depth=3,random_state=17).fit(x,y)
        self.assertAlmostEqual(ml.probability(ml.export(forest),x[70]),forest.predict_proba([x[70]])[0,1])
    def test_insufficient_data_fails(self):
        with self.assertRaises(ValueError):ml.train({'SPY':bars(days=3)})
    def test_invalid_prediction_input_fails(self):
        with self.assertRaises(ValueError):ml.probability({},[float('nan')]*10)
    def test_actual_fill_learning_waits_for_enough_outcomes(self):
        model,report=ml.train_outcomes([])
        self.assertIsNone(model);self.assertFalse(report['trained'])
    def test_actual_fill_learning_is_real_supervised_model(self):
        start=datetime(2025,1,1,tzinfo=timezone.utc)
        rows=[{'entry_time':(start+timedelta(days=i)).isoformat(),'closed_time':(start+timedelta(days=i,hours=1)).isoformat(),'features':[float(i%2)]*10,'net_pnl':10 if i%2 else -10} for i in range(60)]
        model,report=ml.train_outcomes(rows)
        self.assertTrue(report['trained']);self.assertEqual(len(model['trees']),30)
        self.assertLess(report['brier_score'],report['constant_baseline_brier'])
if __name__=='__main__':unittest.main()
