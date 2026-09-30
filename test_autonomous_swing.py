import unittest,tempfile,json
from datetime import datetime,timedelta,timezone
from unittest.mock import patch,Mock
import numpy as np
import pandas as pd
import autonomous_swing as bot

NOW=datetime(2026,9,29,15,tzinfo=timezone.utc)
def prices(size=650):
    dates=pd.bdate_range(end='2026-09-28',periods=size);rng=np.random.default_rng(23)
    close=100*np.cumprod(1+.0004+rng.normal(0,.012,size));opens=close*(1+rng.normal(0,.002,size))
    return pd.DataFrame({'Open':opens,'High':np.maximum(opens,close)*1.005,'Low':np.minimum(opens,close)*.995,'Close':close,'Volume':rng.integers(100000,500000,size)},index=dates)
class FakeBroker:
    def __init__(self):
        self.data={'equity':'100000','cash':'100000','status':'ACTIVE','currency':'USD'};self.open=True;self.pending=[];self.held=[];self.buys=[];self.closes=[];self.unknown=False
    def account(self):return self.data
    def clock(self):return {'is_open':self.open}
    def positions(self):return self.held
    def orders(self):return self.pending
    def calendar(self,a,b):return [{'date':'2026-09-28','open':'09:30','close':'16:00'}]
    def asset(self,symbol):return {'tradable':True,'fractionable':True,'status':'active'}
    def quote(self,symbol):return {'timestamp':NOW.isoformat(),'bid_price':100,'ask_price':100.01}
    def buy(self,symbol,notional,client):
        order={'symbol':symbol,'id':client,'client_order_id':client,'side':'buy','status':'new','notional':str(notional),'filled_qty':'0'};self.buys.append(order)
        if self.unknown:raise TimeoutError()
        self.pending.append(order);return order
    def by_client(self,client):
        found=next((x for x in self.pending if x['client_order_id']==client),None)
        if not found:raise ValueError('Unknown')
        return found
    def close(self,symbol):
        self.closes.append(symbol);return {'id':'exit-id','symbol':symbol,'status':'new'}

class LearnedPolicyTests(unittest.TestCase):
    def test_rolling_features_have_no_future_dependency(self):
        p=prices();before=bot.statistical_features(p).iloc[100].copy();p.iloc[101,p.columns.get_loc('Close')]*=10
        after=bot.statistical_features(p).iloc[100];pd.testing.assert_series_equal(before,after)
        self.assertEqual(len(before),68)
    def test_invalid_or_forming_daily_data_rejected(self):
        p=prices();clean=bot.clean_prices(p,'2026-09-28');self.assertLess(clean.index[-1],pd.Timestamp('2026-09-28'))
        p.iloc[-1,p.columns.get_loc('Low')]=100000
        with self.assertRaises(ValueError):bot.clean_prices(p,'2026-09-29')
    def test_decisions_are_learned_forecast_based(self):
        self.assertEqual(bot.decision([.05]*6,[.01]*6)['action'],'BUY')
        self.assertEqual(bot.decision([-.05]*6,[.01]*6,holding=True)['action'],'EXIT')
        self.assertEqual(bot.decision([.05]*6,[.01]*6,holding=True)['action'],'HOLD')
    def test_real_multioutput_learning_purged_splits(self):
        model,report=bot.fit_policy({'SPY':prices(),'QQQ':prices()})
        self.assertEqual(report['feature_count'],68);self.assertEqual(len(bot.predict(model,bot.statistical_features(prices()).iloc[-1])),6)
        self.assertLess(report['split_dates']['training_last_label'],report['split_dates']['validation_first'])
        self.assertLess(report['split_dates']['validation_last_label'],report['split_dates']['test_first'])
        self.assertEqual(set(report['summary']),{'validation','test'})
    def test_official_sdk_fixed_paper_notional_market_and_close(self):
        with patch('alpaca.trading.client.TradingClient') as client,patch('alpaca.data.historical.StockHistoricalDataClient'):
            broker=bot.AlpacaBroker('mock-key','mock-secret');self.assertTrue(client.call_args.kwargs['paper'])
            client.return_value.submit_order.return_value={'id':'123','status':'new'}
            broker.buy('SPY',250,'client-id');request=client.return_value.submit_order.call_args.kwargs['order_data']
            self.assertEqual(request.notional,250);self.assertIsNone(request.qty)
            broker.close('SPY');client.return_value.close_position.assert_called_once_with('SPY')

class HeadlessExecutionTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.store=bot.Store(self.temp.name+'/state.db');self.broker=FakeBroker()
        self.runner=bot.Runner(bot.Config(symbols=('SPY','QQQ','MSFT','NVDA'),enabled=True),self.store,self.broker,lambda s,b:prices())
        model={'trees':[{'left':[-1],'right':[-1],'feature':[-2],'threshold':[-2],'values':[[.05]*6]}]}
        report={'paper_eligible':True,'validation_error_by_horizon':[.005]*6,'summary':{'validation':{},'test':{}}}
        with self.store.connect() as c:c.execute('INSERT INTO models(at,source_date,model,report) VALUES(?,?,?,?)',(NOW.isoformat(),'2026-09-28',json.dumps(model),json.dumps(report)))
        self.time=patch.object(bot,'utc',return_value=NOW);self.time.start()
    def tearDown(self):self.time.stop();self.temp.cleanup()
    def test_headless_sdk_entries_no_duplicate_max_three_and_risk(self):
        self.runner.run();self.runner.run()
        self.assertEqual(len(self.broker.buys),3)
        self.assertTrue(all(float(o['notional'])<=250 for o in self.broker.buys))
        self.assertEqual(len({o['client_order_id'] for o in self.broker.buys}),3)
    def test_closed_market_trains_decides_but_does_not_order(self):
        self.broker.open=False;self.runner.run();self.assertEqual(self.broker.buys,[])
    def test_failed_validation_blocks_entry(self):
        with self.store.connect() as c:c.execute('UPDATE models SET report=?',(json.dumps({'paper_eligible':False,'validation_error_by_horizon':[.005]*6}),))
        self.runner.run();self.assertEqual(self.broker.buys,[])
    def test_uncertain_broker_submission_is_not_retried(self):
        self.broker.unknown=True;self.runner.run();self.runner.run()
        self.assertEqual(len(self.broker.buys),1);self.assertEqual(self.store.unresolved()[0]['status'],'uncertain')
    def test_no_margin_cash_and_other_account_positions(self):
        self.broker.held=[{'symbol':s,'market_value':'5000'} for s in ('AMD','META','AMZN')];self.runner.run();self.assertEqual(self.broker.buys,[])
    def test_extra_manual_shares_not_closed(self):
        with self.store.connect() as c:c.execute('INSERT INTO holdings VALUES(?,?,?,?)',('SPY','original',1,100))
        with self.assertRaises(ValueError):self.runner.exit('SPY','model exit',[{'symbol':'SPY','qty':'2'}],[])
        self.assertEqual(self.broker.closes,[])
    def test_learned_exit_closes_owned_position(self):
        with self.store.connect() as c:c.execute('INSERT INTO holdings VALUES(?,?,?,?)',('SPY','original',1,100))
        self.runner.exit('SPY','model exit',[{'symbol':'SPY','qty':'1'}],[]);self.assertEqual(self.broker.closes,['SPY'])
    def test_deadline_halts_new_entries(self):
        self.store.put('deadline',(NOW-timedelta(seconds=1)).isoformat());self.runner.run();self.assertEqual(self.broker.buys,[])
    def test_invalid_risk_escalation_rejected(self):
        with self.assertRaises(ValueError):bot.Config(risk_fraction=.01)
    def test_canceled_partial_entry_keeps_owned_shares(self):
        self.runner.run();order=self.broker.pending[0]
        order.update(status='canceled',filled_qty='0.5',filled_avg_price='100')
        self.runner.reconcile()
        with self.store.connect() as c:held=c.execute('SELECT * FROM holdings WHERE symbol=?',(order['symbol'],)).fetchone()
        self.assertEqual(held['quantity'],.5);self.assertEqual(held['entry_value'],50)
    def test_daily_exploration_places_one_bounded_order_despite_wait(self):
        self.runner.config.daily_exploration=True
        with self.store.connect() as c:
            r=c.execute('SELECT model,report FROM models').fetchone();m=json.loads(r['model']);m['trees'][0]['values']=[[-.05]*6];report=json.loads(r['report']);report['paper_eligible']=False
            c.execute('UPDATE models SET model=?,report=?',(json.dumps(m),json.dumps(report)))
        self.runner.run();self.runner.run()
        self.assertEqual(len(self.broker.buys),1);self.assertLessEqual(float(self.broker.buys[0]['notional']),250)
        with self.store.connect() as c:plan=json.loads(c.execute("SELECT payload FROM orders WHERE side='buy'").fetchone()[0])
        self.assertTrue(plan['exploration']);self.assertEqual(plan['model_action'],'WAIT')
        self.assertTrue(all(x['action']=='WAIT' for x in self.store.summary()['last_decisions']))
        order=self.broker.pending[0];order.update(status='filled',filled_qty='2.5',filled_avg_price='100')
        self.broker.held=[{'symbol':order['symbol'],'qty':'2.5','market_value':'250'}];self.broker.pending=[order]
        self.runner.run();self.assertEqual(self.broker.closes,[])
        self.assertEqual(len(self.broker.buys),2)
        self.assertNotEqual(self.broker.buys[0]['symbol'],self.broker.buys[1]['symbol'])
        self.runner.run();self.assertEqual(len(self.broker.buys),2)
    def test_daily_exploration_never_bypasses_stale_quote(self):
        self.runner.config.daily_exploration=True
        self.broker.quote=lambda symbol:{'timestamp':(NOW-timedelta(minutes=5)).isoformat(),'bid_price':100,'ask_price':100.01}
        self.runner.run();self.assertEqual(self.broker.buys,[])
        self.assertIn('No paper entry',self.store.summary()['daily_trade_status']['status'])
    def test_daily_exploration_retains_deadline_limit(self):
        self.runner.config.daily_exploration=True;self.store.put('deadline',(NOW-timedelta(seconds=1)).isoformat())
        self.runner.run();self.assertEqual(self.broker.buys,[])
    def test_blocked_first_candidate_does_not_hide_successful_paper_entry(self):
        self.runner.config.daily_exploration=True
        self.broker.quotes=lambda symbols:{s:{'timestamp':(NOW-timedelta(minutes=5) if s=='SPY' else NOW).isoformat(),'bid_price':100,'ask_price':100.01} for s in symbols}
        self.runner.run();self.assertEqual(len(self.broker.buys),1)
        self.assertIn('submitted',self.store.summary()['daily_trade_status']['status'])
    def test_partial_exit_reconciliation_does_not_double_subtract(self):
        with self.store.connect() as c:c.execute('INSERT INTO holdings VALUES(?,?,?,?)',('SPY','original',2,200))
        self.runner.exit('SPY','model exit',[{'symbol':'SPY','qty':'2'}],[])
        order={'id':'exit-id','status':'partially_filled','filled_qty':'1','filled_avg_price':'105'}
        self.broker.call=Mock(return_value=order)
        self.runner.reconcile();self.runner.reconcile()
        with self.store.connect() as c:held=c.execute('SELECT * FROM holdings WHERE symbol=?',('SPY',)).fetchone()
        self.assertEqual(held['quantity'],1);self.assertEqual(held['entry_value'],100)
        order.update(status='filled',filled_qty='2');self.runner.reconcile()
        with self.store.connect() as c:self.assertIsNone(c.execute('SELECT * FROM holdings WHERE symbol=?',('SPY',)).fetchone())
        self.assertEqual(self.store.summary()['notes'][0]['data']['gross_pnl_usd'],10)
if __name__=='__main__':unittest.main()

class BrokerClockTests(unittest.TestCase):
    def test_small_local_skew_uses_verified_source_time(self):
        with patch.object(bot,'utc',return_value=NOW+timedelta(seconds=104)):
            self.assertEqual(bot.validate_broker_clock(NOW.isoformat(),'Tue, 29 Sep 2026 15:00:00 GMT','0',.3),NOW)
    def test_cached_disagreeing_slow_or_excessive_skew_rejected(self):
        with patch.object(bot,'utc',return_value=NOW):
            for date,age,elapsed,stamp in [('Tue, 29 Sep 2026 15:00:00 GMT','2',.3,NOW),('Tue, 29 Sep 2026 14:59:00 GMT','0',.3,NOW),('Tue, 29 Sep 2026 15:00:00 GMT','0',6,NOW),('Tue, 29 Sep 2026 14:50:00 GMT','0',.3,NOW-timedelta(minutes=10))]:
                with self.assertRaises(ValueError):bot.validate_broker_clock(stamp.isoformat(),date,age,elapsed)
