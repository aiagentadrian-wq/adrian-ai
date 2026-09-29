import unittest,asyncio,sqlite3,io,os
from contextlib import contextmanager
from unittest.mock import patch
import trading_chat_bridge as bridge
from job_v7_packages import make_pdf
from resume_test_email import build_test
from pypdf import PdfReader

RESUME='''TEST CANDIDATE
Test City | test@example.com
CORE SKILLS
Customer Service
Teamwork
EDUCATION
Example Secondary School
2025 - Present
Secondary student
★ References available upon request
PROFILE
Chipotle candidate
EXPERIENCE
Cook | Example Kitchen 2025 - Present
Prepared food orders.
Maintained clean work areas.
'''

class UpgradeTests(unittest.TestCase):
    def setUp(self):
        self.env=patch.dict(os.environ,{'TRADING_UNIVERSE':bridge.DEFAULT_UNIVERSE});self.env.start()
        self.conn=sqlite3.connect(':memory:');self.conn.row_factory=sqlite3.Row
        self.conn.executescript('CREATE TABLE trading_watchlist(symbol TEXT,added_utc TEXT);CREATE TABLE job_v7_resume(id INTEGER PRIMARY KEY,content TEXT);CREATE TABLE job_v7_postings(employer TEXT,title TEXT,location TEXT,url TEXT,description TEXT,id INTEGER);')
        self.conn.execute("INSERT INTO trading_watchlist VALUES('AAPL','today')")
    def tearDown(self):self.conn.close();self.env.stop()
    @contextmanager
    def db(self):yield self.conn
    def test_broad_question_compares_more_than_apple(self):
        names,_=bridge.symbols('What should I buy today?',self.db)
        self.assertIn('AAPL',names);self.assertIn('NVDA',names);self.assertGreater(len(names),1)
        self.assertEqual(bridge.symbols('Research Apple',self.db)[0],['AAPL'])
        self.assertEqual(bridge.symbols('Compare $AMD and $MSFT',self.db)[0],['AMD','MSFT'])
    def test_ranking_can_choose_other_stock_and_preserves_failed_checks(self):
        async def market(symbol,interval,size):
            if symbol=='SPY':raise bridge.HTTPException(502,'Feed unavailable')
            step=1 if symbol=='NVDA' else -0.1
            candles=[{'time':'2026-09-29 12:00:00','open':100+i*step,'close':100+i*step,'high':101+i*step,'low':99+i*step,'volume':2000000} for i in range(65)]
            return {'candles':candles,'source':'TEST FEED','interval':interval,'meta':{},'retrieved_utc':'test','note':'freshness unknown'}
        async def news(symbol):return {'articles':[],'source':'TEST NEWS'}
        with patch.object(bridge.td,'market',market),patch.object(bridge.td,'news',news):r=asyncio.run(bridge.research('What should I buy today?',self.db))
        self.assertEqual(r['ranking'][0]['symbol'],'NVDA')
        self.assertIn('market',next(x for x in r['results'] if x['symbol']=='SPY')['errors'])
        self.assertIn('no confirmed live entry',r['decision'])
        self.assertIn('hypothetical_plan',next(x for x in r['results'] if x['symbol']=='NVDA'))
    def test_all_sources_failed_produces_no_candidate(self):
        async def failed(*args):raise bridge.HTTPException(502,'Feed unavailable')
        with patch.object(bridge.td,'market',failed):r=asyncio.run(bridge.research('Compare $AMD and $MSFT',self.db))
        self.assertEqual(r['ranking'],[]);self.assertTrue(r['decision'].startswith('No suitable candidate'))
    def test_ats_text_order_and_test_attachment_no_job_flags(self):
        job={'employer':'Example Store','title':'Retail Associate','location':'Test City','url':'https://example.org/job','description':'Customer service role'}
        pdf,_=make_pdf(RESUME,job);text='\n'.join(p.extract_text() for p in PdfReader(io.BytesIO(pdf)).pages)
        self.assertLess(text.index('EXPERIENCE'),text.index('EDUCATION'))
        self.assertIn('Example Store',text);self.assertIn('Example Kitchen',text);self.assertNotIn('Chipotle',text)
        self.conn.execute('INSERT INTO job_v7_resume(content) VALUES(?)',(RESUME,))
        self.conn.execute('INSERT INTO job_v7_postings VALUES(?,?,?,?,?,?)',(*job.values(),1))
        before=self.conn.total_changes
        with patch.dict(os.environ,{'EMAIL_FROM':'sender@example.org','REPORT_TO':'owner@example.org'}):msg=build_test(self.db)
        attachments=list(msg.iter_attachments())
        self.assertEqual(len(attachments),1);self.assertEqual(msg['To'],'owner@example.org')
        self.assertEqual(attachments[0].get_filename(),'Adrian_ATS_resume_test.pdf')
        self.assertEqual(before,self.conn.total_changes)
        from pathlib import Path
        import tempfile
        (Path(tempfile.gettempdir())/'ats-test.pdf').write_bytes(pdf)

if __name__=='__main__':unittest.main()
