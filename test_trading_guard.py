import unittest,math
from datetime import datetime,timezone,timedelta
import trading_guard as g

def bars(n=250):
    start=datetime(2025,1,1,tzinfo=timezone.utc);out=[]
    for i in range(n):
        p=100+i*.08+math.sin(i/4)*1.8+(i//30)*3
        out.append(dict(time=(start+timedelta(minutes=15*i)).isoformat(),open=p,high=p+1,low=p-1,close=p+.2,volume=10000+i*10))
    return out

class GuardTests(unittest.TestCase):
    def test_bad_prices_and_duplicates_rejected(self):
        for value in [float('nan'),-1,0]:
            b=bars(3);b[1]['close']=value
            with self.assertRaises(ValueError):g.validate_bars(b,'15min')
        b=bars(3);b[1]['time']=b[0]['time']
        with self.assertRaises(ValueError):g.validate_bars(b,'15min')
    def test_inconsistent_range_rejected(self):
        b=bars(3);b[1]['low']=b[1]['close']+10
        with self.assertRaises(ValueError):g.validate_bars(b,'15min')
    def test_forming_bar_excluded(self):
        b=bars(4);now=datetime.fromisoformat(b[-1]['time'])+timedelta(minutes=5)
        clean,q=g.validate_bars(b,'15min',now)
        self.assertEqual(len(clean),3);self.assertEqual(q['excluded_incomplete_bars'],1)
        self.assertFalse(q['live_entitlement_verified'])
    def test_stale_and_future_bars(self):
        b=bars(3);_,q=g.validate_bars(b,'15min',datetime(2026,1,1,tzinfo=timezone.utc))
        self.assertFalse(q['recent_intraday_bar'])
        with self.assertRaises(ValueError):g.validate_bars(b,'15min',datetime(2024,1,1,tzinfo=timezone.utc))
    def test_risk_and_loss_caps(self):
        r=g.size_position(10000,100,98);self.assertEqual(r['shares'],25);self.assertEqual(r['stop_risk'],50)
        self.assertEqual(g.size_position(10000,100,98,daily_loss=200)['shares'],0)
        self.assertEqual(g.size_position(10000,100,98,exposure=10000)['shares'],0)
        with self.assertRaises(ValueError):g.size_position(10000,100,105)
    def test_replay_has_no_same_bar_entries(self):
        b=bars();r=g.replay(b)
        self.assertTrue(r['trades'])
        for t in r['trades']:self.assertGreater(t['entry_time'],t['signal_time'])
    def test_cost_stress_reduces_returns(self):
        b=bars();cheap=g.replay(b,cost_bps=5);expensive=g.replay(b,cost_bps=50)
        self.assertGreater(cheap['trade_count'],0)
        self.assertEqual(cheap['trade_count'],expensive['trade_count'])
        self.assertGreaterEqual(cheap['compound_return_pct'],expensive['compound_return_pct'])
    def test_future_changes_do_not_change_earlier_trades(self):
        b=bars();original=g.replay(b,end=150);self.assertTrue(original['trades']);b[200]['close']=900
        self.assertEqual(original,g.replay(b,end=150))
    def test_fold_boundaries_and_insufficient_history(self):
        r=g.evaluate(bars());self.assertGreaterEqual(len(r['folds']),3)
        for a,b in zip(r['folds'],r['folds'][1:]):self.assertLess(a['end'],b['start'])
        with self.assertRaises(ValueError):g.evaluate(bars(50))
    def test_same_bar_stop_and_target_is_pessimistic(self):
        b=bars(70)
        for x in b:x.update(open=100,close=100,high=101,low=99)
        b[60].update(close=102,high=103)
        b[61].update(open=102,high=110,low=90,close=102)
        t=g.replay(b)['trades'][0]
        self.assertIn('stop',t['reason']);self.assertLess(t['net_return'],0)

if __name__=='__main__':unittest.main()
