import unittest,tempfile,sqlite3,os,asyncio
from pathlib import Path
from contextlib import contextmanager
from datetime import datetime,timezone
from unittest.mock import patch,Mock
import job_daily
NOW=datetime(2026,9,30,14,tzinfo=timezone.utc)
class DailyMailTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.path=Path(self.temp.name)/'test.db'
        @contextmanager
        def db():
            c=sqlite3.connect(self.path);c.row_factory=sqlite3.Row
            try:yield c;c.commit()
            finally:c.close()
        self.db=db
        with db() as c:c.executescript('CREATE TABLE email_history(id INTEGER PRIMARY KEY,at TEXT,subject TEXT,body TEXT,recipient TEXT,sender TEXT,status TEXT,error TEXT);CREATE TABLE job_v7_postings(id INTEGER PRIMARY KEY,emailed INTEGER);CREATE TABLE job_v7_review(url TEXT,emailed INTEGER,found TEXT);CREATE TABLE job_v7_resume(content TEXT,id INTEGER PRIMARY KEY);')
        self.engine=job_daily.Engine(db,Mock(),lambda:NOW.isoformat())
        self.time=patch.object(job_daily,'utc',return_value=NOW);self.time.start()
        self.env=patch.dict(os.environ,EMAIL_FROM='owner@example.com',REPORT_TO='owner@example.com');self.env.start()
    def tearDown(self):self.env.stop();self.time.stop();self.temp.cleanup()
    def test_empty_daily_update_sends_once_and_reports_source_failures(self):
        with patch.object(job_daily.job_v7_discovery,'discover',return_value={'errors':['Example feed unavailable']}),patch.object(job_daily.job_v7_email,'send',return_value='accepted_by_smtp') as send:
            result=self.engine.run();self.engine.run()
        send.assert_called_once();msg=send.call_args.args[0]
        self.assertIn('No new matching',msg.get_body(preferencelist=('plain',)).get_content())
        self.assertIn('source request(s) failed',msg.get_body(preferencelist=('plain',)).get_content())
        self.assertEqual(result['today']['status'],'accepted_by_smtp')
    def test_unknown_smtp_handoff_not_retried(self):
        with patch.object(job_daily.job_v7_discovery,'discover',return_value={'errors':[]}),patch.object(job_daily.job_v7_email,'send',side_effect=TimeoutError()) as send:
            self.engine.run();result=self.engine.run()
        self.assertEqual(send.call_count,1);self.assertEqual(result['today']['status'],'uncertain')
    def test_earlier_owner_job_email_prevents_duplicate_daily_batch(self):
        with self.db() as c:c.execute('INSERT INTO email_history(at,subject,status) VALUES(?,?,?)',(NOW.isoformat(),'ADRIAN.AI — 3 jobs','accepted_by_smtp'))
        with patch.object(job_daily.job_v7_discovery,'discover') as discover:
            result=self.engine.run()
        discover.assert_not_called();self.assertEqual(result['today']['status'],'already_sent')
    def test_disabled_worker_does_not_discover_or_send(self):
        with patch.object(job_daily.job_v7_discovery,'discover') as discover:asyncio.run(self.engine.tick())
        discover.assert_not_called()
    def test_toronto_due_and_next_day_persisted_status(self):
        self.engine.save({'enabled':True,'hour':9,'minute':0});self.assertTrue(self.engine.summary()['catchup_due'])
        with patch.object(job_daily.job_v7_discovery,'discover',return_value={'errors':[]}),patch.object(job_daily.job_v7_email,'send'):self.engine.run()
        self.assertEqual(self.engine.summary()['next_due'],'2026-10-01T09:00:00-04:00')
if __name__=='__main__':unittest.main()
