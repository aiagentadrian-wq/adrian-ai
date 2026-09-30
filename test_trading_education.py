import unittest
import asyncio
from unittest.mock import AsyncMock,patch
from pathlib import Path
import trading_education as education
import trading_chat_bridge as bridge

class CourseKnowledgeTests(unittest.TestCase):
    def test_teaching_skips_unrelated_market_requests(self):
        with patch.object(bridge,'research',new_callable=AsyncMock) as research:
            output=asyncio.run(bridge.research_context('Teach the course ORB versus ATR strategy',None))
            research.assert_not_called()
            self.assertEqual(output['symbols'],[])

    def test_current_market_question_still_requests_data(self):
        with patch.object(bridge,'research',new_callable=AsyncMock,return_value={'fresh':'test'}) as research:
            output=asyncio.run(bridge.research_context('Explain current MSFT setup today',None))
            research.assert_awaited_once()
            self.assertEqual(output,{'fresh':'test'})

    def test_complete_versioned_course_and_sources(self):
        data=education.library()
        self.assertEqual([p['number'] for p in data['pages']],list(range(1,38)))
        self.assertEqual(len(data['sources']),16)
        self.assertTrue(all(p['text'].strip() for p in data['pages']))
        self.assertEqual(len(data['pdf_sha256']),64)

    def test_question_retrieves_specific_risk_math(self):
        context=education.context('Explain position sizing with $2000 equity, 0.25% risk, 50.40 entry, 49.90 stop and $1 costs')
        self.assertIn('floor($4 / $0.50) = 8 shares',context)
        self.assertIn('Size from the stop',context)

    def test_replay_and_canadian_topics_are_available(self):
        self.assertIn('Replay',education.context('TradingView historical Bar Replay'))
        self.assertIn('TFSA trust',education.context('Canadian TFSA taxes settlement'))
        self.assertIn('https://www.canada.ca/',education.context('Canadian TFSA taxes'))

    def test_education_not_replaced_by_fixed_daily_brief(self):
        self.assertFalse(bridge.daily_decision('Teach me the course opening range breakout entry and stop'))
        self.assertTrue(bridge.daily_decision('Compare the strongest setup today'))

    def test_core_distinguishes_examples_execution_and_data(self):
        system=bridge.system_prompt('What is VWAP?')
        for phrase in ['NOT quotes','NOT changes','unvalidated','authenticated email approval','separate simulators','actual capabilities','No income guarantee']:
            self.assertIn(phrase,system)

    def test_all_trading_model_paths_use_context(self):
        app=Path(__file__).with_name('app.py').read_text(encoding='utf-8')
        self.assertEqual(app.count('trading_chat_bridge.system_prompt('),3)
        self.assertNotIn('trading_chat_bridge.SYSTEM+',app)

if __name__=='__main__':unittest.main()
