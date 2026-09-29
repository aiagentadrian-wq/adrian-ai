import unittest
from unittest.mock import patch
import trading_chat_bridge as bridge

class DiscoveryTests(unittest.TestCase):
    def test_discovery_intent(self):
        self.assertTrue(bridge.discovery_requested("What should I invest in today?"))
        self.assertFalse(bridge.discovery_requested("Research AAPL"))

    def test_bounded_configurable_universe(self):
        with patch.dict("os.environ", {"TRADING_RESEARCH_UNIVERSE":"AAPL,MSFT,AAPL,INVALID!!!,SHOP"}):
            self.assertEqual(bridge.universe(), ["AAPL","MSFT","SHOP"])

    def test_review_flags_missing_market(self):
        item={"sources":{},"errors":{"market":"unavailable"}}
        self.assertTrue(any("No verified" in x for x in bridge.review_item(item)))

if __name__=="__main__":
    unittest.main()
