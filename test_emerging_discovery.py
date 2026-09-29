import unittest
from unittest.mock import AsyncMock,patch
import trading_chat_bridge as bridge

class EmergingDiscoveryTests(unittest.IsolatedAsyncioTestCase):
    async def test_missing_key_is_explicit(self):
        with patch.dict("os.environ",{},clear=True):
            result=await bridge.emerging_news()
        self.assertEqual(result["status"],"not_configured")
        self.assertEqual(result["articles"],[])

    async def test_deduplicates_article_urls_without_inventing_tickers(self):
        article={"title":"Example emerging business","url":"https://example.org/story","published_at":"2026-09-29","source":"Example"}
        with patch.dict("os.environ",{"GNEWS_API_KEY":"test"}),patch.object(bridge.td,"news",new_callable=AsyncMock,return_value={"articles":[article,article]}),patch.object(bridge.asyncio,"sleep",new_callable=AsyncMock):
            result=await bridge.emerging_news()
        self.assertEqual(len(result["articles"]),1)
        self.assertNotIn("ticker",result["articles"][0])
        self.assertIn("UNVERIFIED",result["note"])

if __name__=="__main__": unittest.main()
