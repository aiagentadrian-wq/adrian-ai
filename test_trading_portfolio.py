"""Regression tests for long-only manual paper portfolio accounting."""
import unittest
from trading_lab import paper_positions


def row(symbol, side, quantity, price):
    return {'symbol':symbol,'side':side,'quantity':quantity,'price':price}


class PaperPositionsTests(unittest.TestCase):
    def test_normal_round_trip(self):
        result=paper_positions([row('AAPL','buy',10,100),row('AAPL','sell',4,110)])
        position=result['positions']['AAPL']
        self.assertEqual(position['quantity'],6)
        self.assertEqual(position['net_cost'],600)
        self.assertEqual(position['realized_pnl'],40)
        self.assertEqual(result['net_cashflow'],-560)

    def test_oversell_does_not_create_short_position_or_extra_cashflow(self):
        result=paper_positions([row('AAPL','buy',2,100),row('AAPL','sell',5,110)])
        position=result['positions']['AAPL']
        self.assertEqual(position['quantity'],0)
        self.assertEqual(position['net_cost'],0)
        self.assertEqual(position['realized_pnl'],20)
        self.assertEqual(result['net_cashflow'],20)
        self.assertIn('Excess quantity is excluded',position['warnings'][0])

    def test_sell_without_position_is_excluded(self):
        result=paper_positions([row('MSFT','sell',3,50)])
        self.assertEqual(result['positions']['MSFT']['quantity'],0)
        self.assertEqual(result['net_cashflow'],0)
        self.assertEqual(result['positions']['MSFT']['realized_pnl'],0)

    def test_rebuy_after_oversell(self):
        result=paper_positions([row('AAPL','buy',1,100),row('AAPL','sell',2,110),row('AAPL','buy',2,120)])
        self.assertEqual(result['positions']['AAPL']['quantity'],2)
        self.assertEqual(result['positions']['AAPL']['net_cost'],240)


if __name__=='__main__':
    unittest.main()
