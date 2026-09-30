import unittest,asyncio,sqlite3,tempfile,json
from contextlib import contextmanager
from datetime import datetime,timedelta,timezone
from unittest.mock import AsyncMock,Mock,patch
import swing_trading as swing
import swing_lab as lab

def dataset(size=500):
    start=datetime(2024,1,1,tzinfo=timezone.utc);bars=[]
    for i in range(size):
        close=100+i*.08+__import__('math').sin(i/8)*2
        bars.append({'time':(start+timedelta(days=i)).isoformat(),'open':close-.1,'close':close,'high':close+.2,'low':close-.3,'volume':1000000+(i%7)*50000})
    return bars

class SwingTests(unittest.TestCase):
    def test_early_close_midpoint_and_holidays(self):
        rows=[{'date':'2026-11-27','open':'09:30','close':'13:00'}]
        now=datetime(2026,11,27,16,15,tzinfo=timezone.utc);slots=swing.schedule(rows,now)
        self.assertEqual(slots[1]['local'][11:16],'11:15')
        self.assertTrue(slots[1]['eligible']);self.assertEqual(slots[2]['local'][11:16],'13:05')
        self.assertEqual(swing.schedule([],now),[])
    def test_missed_slot_not_eligible(self):
        rows=[{'date':'2026-09-30','open':'09:30','close':'16:00'}]
        slots=swing.schedule(rows,datetime(2026,9,30,15,tzinfo=timezone.utc))
        self.assertFalse(slots[0]['eligible'])
    def test_stale_quote_closed_market_and_risk_size(self):
        plan={'entry':100,'maximum_entry':100.5,'stop':98}
        self.assertIn('closed',swing.confirmation(plan,{},datetime.now(timezone.utc),False))
        self.assertIn('missing',swing.confirmation(plan,{},datetime.now(timezone.utc),True))
        result=swing.sized(plan,2000,500,.25)
        self.assertLessEqual(result['quantity']*100.5,500)
        self.assertLessEqual(result['planned_risk_usd'],5)
    def test_signal_has_no_future_dependency(self):
        bars=dataset();before=lab.signal(bars,200,lab.BASE)
        bars[201]['high']=10000
        self.assertEqual(before,lab.signal(bars,200,lab.BASE))
    def test_unknown_strategy_rules_rejected(self):
        with self.assertRaises(ValueError):lab.rules({'reward_risk':100})
        with self.assertRaises(ValueError):lab.rules({'execute_live':True})
    def test_experiment_comparisons_and_reuse(self):
        result=lab.experiment({'SPY':dataset(),'QQQ':dataset()},reused=True)
        self.assertIn('before',next(iter(result['changes'].values()),{'before':0}))
        self.assertTrue(result['test_period_reused'])
        self.assertEqual(set(result['comparisons']),{'training','validation','test'})
        self.assertIn('No reliable',result['verdict'])
        self.assertLess(result['periods']['training']['end'],result['periods']['test']['start'])
    def test_boundary_trades_do_not_cross_window(self):
        bars=dataset();r=lab.replay(bars,lab.BASE,200,300)
        self.assertTrue(all(t['exit_date']<=bars[299]['time'] for t in r['trades']))
    def test_higher_costs_dont_create_better_fixed_trade_pnl(self):
        bars=dataset();cheap=lab.replay(bars,lab.BASE,50,500,5);costly=lab.replay(bars,lab.BASE,50,500,50)
        self.assertLessEqual(costly['net_return_pct'],cheap['net_return_pct'])
    def test_module_has_no_order_writes(self):
        source=__import__('pathlib').Path(swing.__file__).read_text()
        self.assertNotIn("'/v2/orders','POST'",source)

class SwingSchedulerTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();path=self.temp.name+'/test.db'
        @contextmanager
        def db():
            c=sqlite3.connect(path);c.row_factory=sqlite3.Row
            try:yield c;c.commit()
            finally:c.close()
        self.db=db;self.engine=swing.Engine(db,Mock(),Mock(),AsyncMock());self.engine.save(swing.DEFAULTS|{'enabled':True})
    def tearDown(self):self.temp.cleanup()
    async def test_one_email_per_slot_and_no_weekend_report(self):
        now=datetime(2026,9,30,13,30,tzinfo=timezone.utc)
        self.engine.calendar=AsyncMock(return_value=[{'date':'2026-09-30','open':'09:30','close':'16:00'}])
        self.engine.report=AsyncMock(return_value={'email':{'status':'accepted_by_smtp'},'decision':'NO TRADE'})
        await self.engine.tick(now);await self.engine.tick(now)
        self.engine.report.assert_awaited_once_with('open',True)
        self.engine.calendar=AsyncMock(return_value=[]);await self.engine.tick(now+timedelta(days=3))
        self.assertEqual(self.engine.report.await_count,1)
    async def test_disabled_worker_does_not_fetch_or_send(self):
        self.engine.save(swing.DEFAULTS);self.engine.calendar=AsyncMock()
        await self.engine.tick();self.engine.calendar.assert_not_called()
if __name__=='__main__':unittest.main()

class ProviderFallbackTests(unittest.TestCase):
    def test_failure_shows_recorded_execution_without_claiming_new_fill(self):
        result=swing.provider_fallback({'enabled':True,'last_run':'sample-time','orders':[{'symbol':'AMD','side':'buy','status':'filled'},{'symbol':'QQQ','side':'buy','status':'pending_new'}]},None,'HTTP 429')
        self.assertIn('AMD buy: filled',result)
        self.assertIn('QQQ buy: pending_new',result)
        self.assertIn('not a new live broker check',result)
        self.assertIn('No additional order',result)
    def test_missing_state_does_not_claim_active_engine(self):
        self.assertIn('disabled or unavailable',swing.provider_fallback({},None,'HTTP 429'))
