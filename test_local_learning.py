import unittest,tempfile,sqlite3,asyncio,os,json
from pathlib import Path
from contextlib import contextmanager
from datetime import datetime,timezone,timedelta
from unittest.mock import AsyncMock,Mock,patch
import numpy as np
import pandas as pd
import local_learning as learn
import strategy_research as research
import agent_learning_reports as reports
import ai_adapter

class LearningTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name)/'test.db'
        @contextmanager
        def db():
            c=sqlite3.connect(self.path);c.row_factory=sqlite3.Row
            try:yield c;c.commit()
            finally:c.close()
        self.db=db;learn.setup(db)
        with db() as c:c.executescript('CREATE TABLE writer_samples(id INTEGER PRIMARY KEY,kind TEXT,title TEXT,content TEXT);CREATE TABLE writer_feedback(id INTEGER PRIMARY KEY,feedback TEXT);')
    def tearDown(self):self.tmp.cleanup()
    def test_writer_learns_and_invalidates_deleted_samples(self):
        with self.db() as c:c.execute('INSERT INTO writer_samples VALUES(1,?,?,?)',('email','My email','I like short sentences. My ideas are practical. We can test these things with real examples.'))
        a=learn.writer_model(self.db);self.assertEqual(a['sample_count'],1)
        self.assertIn('My email',learn.writer_context(self.db,'write an email'))
        with self.db() as c:c.execute('DELETE FROM writer_samples')
        b=learn.writer_model(self.db);self.assertEqual(b['sample_count'],0);self.assertNotEqual(a['fingerprint'],b['fingerprint'])
    def test_primary_voice_survives_recency_topic_and_sample_deletion(self):
        reference='Plain everyday language. '+('Full reference retained. '*600)+'LAST_SENTENCE'
        learn.set_primary_reference(self.db,'My permanent voice',reference)
        with self.db() as c:
            for i in range(125):c.execute('INSERT INTO writer_samples VALUES(?,?,?,?)',(i+1,'email','Older competing example','Use highly formal corporate phrasing.'))
            c.execute('INSERT INTO writer_feedback VALUES(1,?)',('Always sound very formal.',))
        for request in ['Write about sports.','Write a business email.','Explain a science assignment.']:
            context=learn.writer_context(self.db,request)
            self.assertIn(reference,context)
            self.assertNotIn('highly formal corporate',context)
            self.assertNotIn('Always sound very formal',context)
        with self.db() as c:c.execute('DELETE FROM writer_samples')
        self.assertEqual(learn.primary_reference(self.db)['content'],reference)
        self.assertIn('LAST_SENTENCE',learn.writer_context(self.db,'Another task'))

    def test_job_cold_start_does_not_invent_trained_model(self):
        m=learn.train_jobs(self.db);self.assertFalse(m['enabled']);self.assertEqual(m['labels'],0)
        job={'title':'cashier','employer':'Store','location':'Whitby','url':'https://example.org/job','pay':'$18 per hour'}
        ranked=learn.rank_jobs(self.db,[job]);self.assertIsNone(ranked[0]['preference_score'])
    def test_writer_word_constraints_ignore_unrelated_numbers(self):
        self.assertEqual(learn.requested_words('Write one paragraph, 90 to 120 words.'),(90,120))
        self.assertEqual(learn.requested_words('Write exactly 100 words.'),(100,100))
        self.assertIsNone(learn.requested_words('Compare 100 jobs and 20 matches.'))
    def test_job_feedback_replaces_choice_not_duplicate_labels(self):
        j={'title':'cashier','url':'https://example.org/1'}
        learn.record_job(self.db,j,'save');m=learn.record_job(self.db,j,'skip')
        self.assertEqual(m['labels'],1);self.assertEqual(m['negative'],1)
    def test_job_learner_uses_real_labels_and_holdout(self):
        with self.db() as c:
            for i in range(40):
                good=i%2==0;j={'title':'cashier' if good else 'warehouse picker','location':'Whitby' if good else 'Ajax'}
                c.execute('INSERT INTO local_job_labels VALUES(?,?,?,?)',(str(i),f'2026-01-{i//2+1:02d}T{i%2:02d}:00:00Z','save' if good else 'skip',json.dumps(learn.job_features(j))))
        m=learn.train_jobs(self.db);self.assertTrue(m['enabled']);self.assertEqual(m['validation_count'],10)
    def datasets(self):
        idx=pd.bdate_range('2022-01-01',periods=850);rng=np.random.default_rng(123)
        out={}
        for symbol in ('SPY','AMD'):
            close=100*np.exp(np.cumsum(rng.normal(.0004,.025,850)))
            out[symbol]=pd.DataFrame({'Open':close*.998,'High':close*1.02,'Low':close*.98,'Close':close,'Volume':rng.integers(10000,50000,850)},index=idx)
        return out
    def test_later_test_prices_do_not_choose_candidate(self):
        data=self.datasets();now=datetime(2026,1,1,tzinfo=timezone.utc)
        a=research.train(self.db,data,now)
        changed={s:f.copy() for s,f in data.items()}
        for f in changed.values():f.iloc[690:,f.columns.get_indexer(['Open','High','Low','Close'])]*=np.linspace(1,3,len(f)-690)[:,None]
        b=research.train(self.db,changed,now)
        self.assertEqual(a['selected_on_validation'],b['selected_on_validation']);self.assertTrue(b['test_reused'])
        va=[t.get('validation') for t in a['trials']];vb=[t.get('validation') for t in b['trials']];self.assertEqual(va,vb)
    def test_forward_predictions_are_immutable_and_not_retroactively_filled(self):
        data=self.datasets();now=datetime(2026,1,1,tzinfo=timezone.utc);research.train(self.db,data,now)
        with self.db() as c:before=[tuple(r) for r in c.execute('SELECT * FROM strategy_shadow ORDER BY id')]
        research.train(self.db,data,now+timedelta(days=1))
        with self.db() as c:after=[tuple(r) for r in c.execute('SELECT * FROM strategy_shadow ORDER BY id')]
        self.assertEqual(before,after);self.assertTrue(all(r[7] is None for r in after))
    def test_context_keeps_entire_rubric_and_samples(self):
        messages=[{'role':'system','content':'voice-matching writing assistant '+('sample '*1000)},{'role':'user','content':'old'*12000},{'role':'assistant','content':'old reply'},{'role':'user','content':'rubric '*1500+'FINAL REQUIREMENT'}]
        packed=ai_adapter.local_messages(messages);self.assertEqual(packed[0],messages[0]);self.assertEqual(packed[-1],messages[-1]);self.assertEqual(len(packed),2)
    def test_oversized_essential_context_fails_without_silent_cut(self):
        with self.assertRaises(Exception):ai_adapter.local_messages([{'role':'system','content':'s'*10000},{'role':'user','content':'u'*40000}])
    def test_report_claim_prevents_duplicate_and_uncertain_retries(self):
        engine=reports.Engine(self.db,Mock(),Mock(),Mock(),Mock());engine.build=AsyncMock(return_value='report')
        engine.paper.mail=Mock(side_effect=TimeoutError())
        async def exercise():
            first=await engine.run('test',research=False);second=await engine.run('test',research=False)
            self.assertEqual(first['status'],'uncertain');self.assertTrue(second['duplicate_prevented']);engine.paper.mail.assert_called_once()
        asyncio.run(exercise())
    def test_report_pre_send_failure_can_recover(self):
        engine=reports.Engine(self.db,Mock(),Mock(),Mock(),Mock());engine.build=AsyncMock(side_effect=[ValueError(), 'report']);engine.paper.mail=Mock(return_value={'status':'accepted_by_smtp'})
        async def exercise():
            self.assertEqual((await engine.run('recover',research=False))['status'],'failed_before_send')
            self.assertEqual((await engine.run('recover',research=False))['status'],'accepted_by_smtp')
        asyncio.run(exercise())
    def test_deadline_sends_final_without_daily_duplicate(self):
        e=reports.Engine(self.db,Mock(),Mock(),Mock(),Mock());e.save({'enabled':True,'hour':18,'minute':0});e.experiment.config.return_value={'ends':'2026-09-29T00:00:00+00:00'};e.run=AsyncMock()
        asyncio.run(e.tick());self.assertTrue(e.run.call_args.args[0].startswith('final:'));self.assertTrue(e.run.call_args.args[1])

class EmailRoutingTests(unittest.TestCase):
    def test_report_recipient_differs_from_approval_owner(self):
        import paper_trading
        engine=object.__new__(paper_trading.Engine);engine.send=Mock(return_value={'status':'accepted_by_smtp'});engine.config=Mock(side_effect=AssertionError('Report must not use bot inbox'))
        with patch.dict(os.environ,{'REPORT_TO':'recipient@example.org'}):
            self.assertEqual(engine.mail('Report','Body')['status'],'accepted_by_smtp');engine.send.assert_called_once_with('Report','Body')
    def test_failed_report_sender_never_claims_success(self):
        import paper_trading
        e=object.__new__(paper_trading.Engine);e.send=Mock(return_value={'status':'failed'})
        with patch.dict(os.environ,{'REPORT_TO':'recipient@example.org'}):
            with self.assertRaises(Exception):e.mail('Report','Body')

if __name__=='__main__':unittest.main()
