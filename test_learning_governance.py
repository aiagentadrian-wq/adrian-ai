import unittest,tempfile,json
from pathlib import Path
from datetime import datetime,timedelta,timezone
import pandas as pd
import autonomous_swing as bot
import learning_governance as g
class GovernanceTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.store=bot.Store(Path(self.temp.name)/'test.db');self.now=datetime(2026,9,30,15,tzinfo=timezone.utc);g.setup(self.store)
 def tearDown(self):self.temp.cleanup()
 def test_ties_do_not_pick_list_order(self):
  d=bot.decision([.04]*6,[.01]*6);a=dict(d,symbol='SPY');b=dict(d,symbol='QQQ')
  selected,reason=g.choose([a,b],None,1,3,self.store);self.assertEqual(selected,[]);self.assertIn('indistinguishable',reason)
 def test_no_20_day_forecast_for_one_week(self):
  d=dict(bot.decision([-.01]*5+[.9],[.01]*6),symbol='SPY');self.assertEqual(g.choose([d],None,1,5,self.store)[0],[])
 def test_uncertain_positive_opportunity_is_small_experiment(self):
  d=dict(bot.decision([.02]*6,[.04]*6),symbol='AMD');a=g.choose([d],None,1,3,self.store)[0][0]
  self.assertEqual(a['track'],'experimental');self.assertTrue(a['selected']['horizon_sessions']<=3)
  rule=g.plan_exit(a,100,25,self.now,(self.now+timedelta(days=3)).isoformat());self.assertEqual(rule['max_planned_loss_usd'],.5)
 def test_shadow_cannot_label_using_past_open(self):
  g.record_predictions(self.store,1,'SPY','2026-09-29',[1]*68,[.01]*6,[.02]*6,'positive_trend',self.now)
  frame=pd.DataFrame({'Open':[100,100],'Close':[100,105],'Low':[99,99]},index=pd.to_datetime(['2026-09-29','2026-09-30']))
  g.mature(self.store,{'SPY':frame},self.now);self.assertEqual(g.scorecard(self.store)['matured_predictions'],0)
  frame.loc[pd.Timestamp('2026-10-01')]=[100,110,98];g.mature(self.store,{'SPY':frame},self.now+timedelta(days=2));self.assertEqual(g.scorecard(self.store)['matured_predictions'],1)
 def test_duplicate_predictions_are_immutable(self):
  for forecast in (.01,.9):g.record_predictions(self.store,1,'SPY','2026-09-29',[1]*68,[forecast]*6,[.02]*6,'positive_trend',self.now)
  with self.store.connect() as c:rows=c.execute('SELECT * FROM research_predictions').fetchall()
  self.assertEqual(len(rows),6);self.assertEqual(rows[0]['forecast'],.01)
 def test_no_early_promotion(self):self.assertFalse(g.promotion(self.store,1,{'paper_eligible':True})['promoted'])
 def test_partial_exits_idempotent_and_budget_tracks_loss(self):
  g.register_trade(self.store,'entry','AMD',{'track':'experimental'},25,1,self.now.isoformat())
  for _ in range(2):g.record_exit(self.store,'exit','entry',.5,10,'stop',self.now)
  self.assertEqual(g.scorecard(self.store)['tracks']['experimental']['closed'],0)
  g.record_exit(self.store,'exit','entry',1,20,'stop',self.now)
  self.assertEqual(g.scorecard(self.store)['tracks']['experimental']['closed'],1)
  self.assertAlmostEqual(g.experiment_available(self.store),94.91)
 def test_planned_exit_and_drawdown(self):
  g.register_trade(self.store,'entry','AMD',{'track':'experimental','exit_plan':{'stop_price':98,'target_price':104,'exit_by':(self.now+timedelta(days=1)).isoformat()}},25,.25,self.now.isoformat())
  self.assertEqual(g.monitor(self.store,[{'symbol':'AMD','market_value':'24','current_price':'96'}],self.now),[('AMD','Planned stop observed')])
  self.assertLess(g.scorecard(self.store)['tracks']['experimental']['worst_observed_position_drawdown_pct'],0)

class LocalAdapterTests(unittest.IsolatedAsyncioTestCase):
 async def test_local_failure_does_not_call_paid_provider(self):
  import ai_adapter,httpx
  from unittest.mock import patch,AsyncMock
  from fastapi import HTTPException
  with patch.object(httpx.AsyncClient,'post',new_callable=AsyncMock,side_effect=httpx.ConnectError('offline')) as request:
   with self.assertRaises(HTTPException) as err:await ai_adapter.call({'base_url':'http://127.0.0.1:11434/v1','model':'qwen3:8b'},[{'role':'user','content':'status'}],'local-only')
   self.assertEqual(request.await_count,1);self.assertIn('no paid fallback',str(err.exception.detail))
 async def test_local_tools_normalize_arguments(self):
  import ai_adapter,httpx
  from unittest.mock import patch,AsyncMock
  response=httpx.Response(200,json={'message':{'role':'assistant','content':'','tool_calls':[{'function':{'name':'status','arguments':{'symbol':'AMD'}}}]}})
  with patch.object(httpx.AsyncClient,'post',new_callable=AsyncMock,return_value=response):
   data=await ai_adapter.call({'base_url':'http://127.0.0.1:11434/v1','model':'qwen3:8b'},[{'role':'user','content':'status'}],'local-only')
   call=data['choices'][0]['message']['tool_calls'][0];self.assertEqual(json.loads(call['function']['arguments']),{'symbol':'AMD'})

class OutcomeLearningTests(unittest.TestCase):
 def test_closed_outcomes_fit_residual_without_enabling_orders(self):
  with tempfile.TemporaryDirectory() as folder:
   store=bot.Store(Path(folder)/'db');g.setup(store)
   start=datetime(2025,1,1,tzinfo=timezone.utc)
   for i in range(60):
    at=start+timedelta(days=i);plan={'track':'experimental','entry_features':[float(i%7)]*68,'selected':{'horizon_sessions':1,'forecast_gross_return':.03},'model_version':1}
    g.register_trade(store,'e'+str(i),'AMD',plan,25,1,at.isoformat());g.record_exit(store,'x'+str(i),'e'+str(i),1,25.25,'time',at+timedelta(hours=6))
   g.train_outcomes(store);report=store.get('outcome_calibration')
   self.assertTrue(report['improved']);self.assertEqual(report['samples'],60);self.assertFalse(report['automatic_live_use'])
   self.assertEqual(g.corrected_forecasts(store,1,[1]*68,[.03]*6),[.03]*6)
 def test_legacy_migration_does_not_consume_experiment_budget(self):
  with tempfile.TemporaryDirectory() as folder:
   store=bot.Store(Path(folder)/'db');now=datetime(2026,9,30,tzinfo=timezone.utc)
   with store.connect() as c:
    c.execute('INSERT INTO orders VALUES(?,?,?,?,?,?,?,?)',('e',now.isoformat(),'AMD','buy','filled','b',json.dumps({'model_version':3}),'filled'))
    c.execute('INSERT INTO holdings VALUES(?,?,?,?)',('AMD','e',1,250))
   g.adopt_legacy(store,[],(now+timedelta(days=5)).isoformat(),now);g.adopt_legacy(store,[],(now+timedelta(days=5)).isoformat(),now)
   card=g.scorecard(store);self.assertEqual(card['tracks']['legacy']['open'],1);self.assertEqual(card['experiment_budget_remaining_usd'],100)

class PlannedBacktestTests(unittest.TestCase):
 def test_entry_bar_stop_wins_ambiguous_target(self):
  from unittest.mock import patch
  prices=pd.DataFrame({'Open':[100]*4,'High':[120]*4,'Low':[90]*4,'Close':[110]*4})
  features=pd.DataFrame({'x':[1]*4})
  with patch.object(bot,'predict',return_value=[.1]*6):
   result=g.replay_planned(prices,features,{},[.01]*6,0,4,20)
  self.assertLess(result['net_return_pct'],0);self.assertEqual(result['closed_trades'],3)

class ReportVerdictTests(unittest.TestCase):
 def test_positive_old_baseline_cannot_override_failed_new_strategy(self):
  result=g.report_status({'paper_eligible':True,'planned_exit_tests':{'test':{'20':{'SPY':{'net_return_pct':1,'exposure_matched_buy_hold_pct':5,'worst_drawdown_pct':-2,'closed_trades':10}}}}})
  self.assertFalse(result['paper_eligible']);self.assertIn('Research only',result['verdict'])
