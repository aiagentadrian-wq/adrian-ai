"""Isolated regression checks: never touch the installed user's database or credentials."""
import asyncio
import importlib
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch,AsyncMock
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

class DashboardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory();root=Path(cls.temp.name)
        for p in Path(__file__).parent.glob('*.py'):
            if 'backup' not in p.name and not p.name.startswith('test_'):shutil.copy2(p,root/p.name)
        shutil.copytree(Path(__file__).parent/'static',root/'static')
        shutil.copy2(Path(__file__).parent/'trading_course_knowledge.json',root/'trading_course_knowledge.json')
        cls.env=patch.dict(os.environ,APP_PASSWORD='dashboard-test-password',SESSION_SECRET='x'*64,ENCRYPTION_KEY=Fernet.generate_key().decode())
        cls.env.start();sys.path.insert(0,str(root))
        cls.app=importlib.import_module('app');cls.core=importlib.import_module('dashboard_core')
        cls.client=TestClient(cls.app.app)
        cls.client.post('/api/login',json={'password':'dashboard-test-password'})
        cls.headers={'X-CSRF-Token':cls.client.cookies.get('acc_csrf')}

    @classmethod
    def tearDownClass(cls):
        cls.client.close();cls.env.stop();sys.path.pop(0);cls.temp.cleanup()

    def test_writer_chat_saves_current_draft_and_emails_once(self):
        from unittest.mock import Mock
        with self.app.db() as c:c.execute('INSERT INTO providers(name,base_url,model,secret,created) VALUES(?,?,?,?,?)',('writer-local-test','http://127.0.0.1:11434/v1','test',self.app.CIPHER.encrypt(b'local'),self.app.now()))
        try:
            with patch.object(self.app,'writer_generate',new=AsyncMock(return_value='Current truthful draft.')),patch.object(self.app,'send_owner_email',new=Mock(return_value={'status':'accepted_by_smtp'})) as send:
                first=self.client.post('/api/chat',headers=self.headers,json={'agent_id':4,'message':'Write a short draft.'});self.assertEqual(first.status_code,200)
                for _ in range(2):self.assertEqual(self.client.post('/api/chat',headers=self.headers,json={'agent_id':4,'message':'Email that to me please'}).status_code,200)
                send.assert_called_once_with('ADRIAN.AI - Your saved writing draft','Current truthful draft.')
        finally:
            with self.app.db() as c:c.execute("DELETE FROM providers WHERE name='writer-local-test'")
    def test_primary_reference_is_in_every_generation_stage(self):
        import local_learning
        reference='A primary voice example with ordinary words. '+('Complete reference text, including the final paragraph. '*60)+'FINAL_REFERENCE_MARKER'
        local_learning.set_primary_reference(self.app.db,'Primary test voice',reference)
        def result(text):return {'choices':[{'message':{'content':text}}]}
        try:
            with patch.object(self.app,'model_call',new=AsyncMock(side_effect=[result('Short initial draft.'),result('Use natural contractions.'),result('Short revised draft.'),result(' '.join(['business']*100))])) as model:
                draft,report=asyncio.run(self.app.writer_generate({'model':'test'},'Write 90 to 120 words about bakery inventory.',details=True))
                self.assertEqual(report['primary_reference'],'Primary test voice')
                self.assertEqual(model.await_count,4)
                for call in model.await_args_list:
                    system=call.args[1][0]['content']
                    self.assertIn('FINAL_REFERENCE_MARKER',system)
                    self.assertIn(reference,system)
                    self.assertNotIn('Remove stock phrases such as',system)
                self.assertNotIn('these stock phrases:',model.await_args_list[2].args[1][-1]['content'])
                data=self.client.get('/api/writer').json()['primary_reference']
                self.assertEqual(data['title'],'Primary test voice')
                self.assertNotIn('content',data)
        finally:
            with self.app.db() as c:c.execute('DELETE FROM writer_primary_reference')

    def test_writer_rejects_copied_sample_before_saving(self):
        sample='Checking a job posting before applying is important because postings can expire and you do not want to waste time on opportunities that are no longer open.'
        with self.app.db() as c:
            c.execute('INSERT INTO writer_samples(created,title,kind,content) VALUES(?,?,?,?)',(self.app.now(),'job example','general',sample))
        try:
            with self.assertRaises(self.app.HTTPException):
                self.app.writer_check_sample_copy(sample,'Analyze tariffs and market forces for a business idea.')
            self.app.writer_check_sample_copy(sample,'Edit this supplied text: '+sample)
            self.app.writer_check_sample_copy('Tariffs increase the cost of imported materials for the business.','Analyze market forces.')
        finally:
            with self.app.db() as c:c.execute("DELETE FROM writer_samples WHERE title='job example'")

    def test_edited_assignment_retains_its_request(self):
        response=self.client.post('/api/pro/writer/save',headers=self.headers,json={'content':'My revised business assignment.','request':'TITLE: Market forces'})
        self.assertEqual(response.status_code,200)
        latest=self.client.get('/api/pro/writer/latest').json()['draft']
        self.assertEqual(latest['request'],'TITLE: Market forces')

    def test_writer_repairs_word_count_and_reports_actual_length(self):
        def result(text):return {'choices':[{'message':{'content':text}}]}
        with patch.object(self.app,'model_call',new=AsyncMock(side_effect=[result('short draft'),result('keep the facts'),result('short revised draft'),result(' '.join(['word']*100))])) as model:
            import asyncio
            draft,report=asyncio.run(self.app.writer_generate({'model':'test'},'Write 90 to 120 words on supplied facts.',details=True))
            self.assertTrue(report['length_met']);self.assertEqual(report['word_count'],100);self.assertEqual(model.await_count,4)
    def test_writer_uses_its_assigned_local_model(self):
        import asyncio,ai_adapter
        with self.app.db() as c:
            original=c.execute("SELECT model FROM agents WHERE name='Writer'").fetchone()[0]
            c.execute("UPDATE agents SET model='adrian-writer' WHERE name='Writer'")
        try:
            provider={'base_url':'http://127.0.0.1:11434/v1','model':'adrian-agent','secret':self.app.CIPHER.encrypt(b'local')}
            with patch.object(ai_adapter,'call',new=AsyncMock(return_value={})) as call:
                asyncio.run(self.app.model_call(provider,[{'role':'system','content':'voice-matching writing assistant'}]))
                self.assertEqual(call.call_args.args[0]['model'],'adrian-writer')
        finally:
            with self.app.db() as c:c.execute("UPDATE agents SET model=? WHERE name='Writer'",(original,))
    def test_local_job_chat_uses_connected_feeds_without_paid_ai(self):
        from unittest.mock import Mock
        with self.app.db() as c:c.execute('INSERT INTO providers(name,base_url,model,secret,created) VALUES(?,?,?,?,?)',('jobs-local-test','http://127.0.0.1:11434/v1','test',self.app.CIPHER.encrypt(b'local'),self.app.now()))
        try:
            with patch('job_v7_discovery.discover',return_value={'new':0,'errors':['source failed']}),patch.object(self.app.adrian_intelligence,'recommendations',return_value={'jobs':[]}),patch.object(self.app,'job_finder_search',new=AsyncMock()) as paid:
                r=self.client.post('/api/chat',headers=self.headers,json={'agent_id':3,'message':'Find jobs from my connected feeds'});self.assertEqual(r.status_code,200);self.assertIn('source failures',r.json()['answer']);paid.assert_not_awaited()
        finally:
            with self.app.db() as c:c.execute("DELETE FROM providers WHERE name='jobs-local-test'")
    def test_local_learning_routes_require_auth_and_csrf(self):
        with TestClient(self.app.app) as anonymous:
            self.assertEqual(anonymous.get('/api/agents/learning/status').status_code,401)
            self.assertEqual(anonymous.get('/api/learning/local/jobs').status_code,401)
        self.assertEqual(self.client.post('/api/learning/local/train').status_code,403)
        self.assertEqual(self.client.post('/api/agents/learning/settings',json={'enabled':True}).status_code,403)

    def test_auth_and_csrf(self):
        self.assertEqual(self.client.post('/api/swing/learned/run').status_code,403)
        self.assertEqual(self.client.post('/api/paper/settings',json={}).status_code,403)
        with TestClient(self.app.app) as anonymous:
            self.assertEqual(anonymous.get('/api/swing/learned/status').status_code,401)
            self.assertEqual(anonymous.get('/api/paper/journal').status_code,401)
        with TestClient(self.app.app) as anonymous:
            self.assertEqual(anonymous.get('/api/pro/services').status_code,401)
        self.assertEqual(self.client.post('/api/pro/writer/save',json={'content':'test'}).status_code,403)
    def test_swing_and_experiment_routes_require_auth_and_csrf(self):
        with TestClient(self.app.app) as anonymous:
            self.assertEqual(anonymous.get('/api/swing/status').status_code,401)
            self.assertEqual(anonymous.get('/api/experiment/status').status_code,401)
        self.assertEqual(self.client.post('/api/swing/lab',json={}).status_code,403)
        self.assertEqual(self.client.post('/api/experiment/start',json={}).status_code,403)
        self.assertEqual(self.client.post('/api/experiment/start',json={},headers=self.headers).status_code,400)
        self.assertEqual(self.client.get('/swing.js').status_code,200)
        self.assertTrue(any(a['name']=='Swing Trader' for a in self.client.get('/api/agents').json()))

    def test_private_paper_settings_do_not_return_credentials(self):
        self.assertEqual(self.client.get('/paper.js').status_code,200)
        data={'key':'mock-paper-key','secret':'mock-paper-secret','gmail_password':'mock-app-password','owner':'paper-owner@gmail.com'}
        result=self.client.post('/api/paper/settings',json=data,headers=self.headers)
        self.assertEqual(result.status_code,200)
        self.assertNotIn('mock-paper',result.text);self.assertNotIn('mock-app-password',result.text)
        self.assertTrue(result.json()['key_saved'])
        with self.app.db() as c:stored=c.execute('SELECT payload FROM paper_settings').fetchone()[0]
        self.assertNotIn('mock-paper',stored)
        self.client.post('/api/paper/settings',json={'owner':'paper-owner@gmail.com'},headers=self.headers)
        self.assertTrue(self.client.get('/api/paper/settings').json()['secret_saved'])
        with self.app.db() as c:c.execute('DELETE FROM paper_settings')
    def test_chat_emails_proposal_without_claiming_order(self):
        with self.app.db() as c:
            c.execute('INSERT INTO providers(name,base_url,model,secret,created) VALUES(?,?,?,?,?)',('paper-chat-test','https://api.openai.com/v1','test',self.app.CIPHER.encrypt(b'test'),self.app.now()))
        try:
            with patch.object(self.app.paper_trading.APP,'propose',new=AsyncMock(return_value={'status':'pending','expires':'future'})) as proposed:
                r=self.client.post('/api/chat',headers=self.headers,json={'message':'Email me a paper trade proposal for MSFT','agent_id':2})
                self.assertEqual(r.status_code,200);proposed.assert_awaited_once_with('Email me a paper trade proposal for MSFT')
                self.assertIn('No order has been placed',r.json()['answer']);self.assertIn('stop/target exits',r.json()['answer'])
        finally:
            with self.app.db() as c:c.execute("DELETE FROM providers WHERE name='paper-chat-test'")
    def test_day_trader_receives_actual_paper_capabilities(self):
        with self.app.db() as c:c.execute('INSERT INTO providers(name,base_url,model,secret,created) VALUES(?,?,?,?,?)',('paper-chat-test','https://api.openai.com/v1','test',self.app.CIPHER.encrypt(b'test'),self.app.now()))
        try:
            with patch.object(self.app.trading_chat_bridge,'research',new=AsyncMock(return_value={'ranking':[],'results':[]})),patch.object(self.app,'model_call',new=AsyncMock(return_value={'choices':[{'message':{'content':'Paper approval required.'}}]})) as model:
                r=self.client.post('/api/chat',headers=self.headers,json={'message':'Explain your broker connection and automatic stop/target exits.','agent_id':2})
                self.assertEqual(r.status_code,200)
                messages=model.call_args.args[1]
                self.assertIn('paper_connection',messages[-1]['content']);self.assertIn('Alpaca',messages[-1]['content'])
                self.assertIn('stop-loss',messages[-1]['content']);self.assertIn('Do not claim no broker exists',messages[0]['content'])
        finally:
            with self.app.db() as c:c.execute("DELETE FROM providers WHERE name='paper-chat-test'")

    def test_real_service_statuses(self):
        self.core.observe('boc','verified','successful response')
        status={x['id']:x['status'] for x in self.client.get('/api/pro/services').json()['items']}
        self.assertEqual(status['boc'],'verified')
        self.core.observe('boc','unreachable','failed request')
        status={x['id']:x['status'] for x in self.client.get('/api/pro/services').json()['items']}
        self.assertEqual(status['boc'],'unreachable')
        self.assertEqual(self.core.classify(429)[0],'limited')
        self.assertEqual(self.core.classify(200,{'status':'error','message':'API credits exhausted'})[0],'limited')
        self.assertEqual(self.core.classify(401)[0],'access denied')

    def test_explicit_memory_without_model(self):
        r=self.client.post('/api/chat',headers=self.headers,json={'message':'Remember that I prefer concise reports','agent_id':1})
        self.assertEqual(r.status_code,200);self.assertIn('Remembered',r.json()['answer'])
        self.assertIn('concise reports',self.core.shared_context('reports'))
        r=self.client.post('/api/chat',headers=self.headers,json={'message':'Remember my password is secret','agent_id':1})
        self.assertIn('not stored',r.json()['answer'])
        self.assertNotIn('password is secret',self.core.shared_context())

    def test_persistent_writer_edits(self):
        r=self.client.post('/api/pro/writer/save',headers=self.headers,json={'content':'My edited draft.'})
        self.assertEqual(r.status_code,200)
        self.assertEqual(self.client.get('/api/pro/writer/latest').json()['draft']['content'],'My edited draft.')

    def test_application_tracking_is_not_submission(self):
        with self.app.db() as c:
            c.execute("INSERT INTO job_v7_postings(source,employer,title,location,url,description,found) VALUES('test','Example','Assistant','Ontario','https://example.org/job','Example job description',?)",(self.app.now(),))
            jid=c.execute('SELECT last_insert_rowid()').fetchone()[0]
        r=self.client.put('/api/pro/applications/'+str(jid),headers=self.headers,json={'stage':'interview'})
        self.assertEqual(r.status_code,200);self.assertIn('no application',r.json()['note'])
        self.assertEqual(self.client.put('/api/pro/applications/'+str(jid),headers=self.headers,json={'stage':'invented'}).status_code,400)

    def test_running_state_tracks_real_work(self):
        self.core.RUNNING['test']={'agent':'Writer','started':self.app.now(),'task':'draft'}
        try:
            agents=self.client.get('/api/pro/overview').json()['agents']
            self.assertEqual(next(x for x in agents if x['name']=='Writer')['state'],'working')
            self.assertEqual(next(x for x in agents if x['name']=='Day Trader')['state'],'idle')
        finally:self.core.RUNNING.pop('test')

    def test_response_tool_roundtrip(self):
        import ai_adapter
        data={'output':[{'type':'function_call','call_id':'call_1','name':'delegate','arguments':'{}'}],'status':'completed'}
        msg=ai_adapter.normalize(data)['choices'][0]['message']
        items=ai_adapter.response_input([msg,{'role':'tool','tool_call_id':'call_1','content':'result'}])
        self.assertEqual(items[0]['type'],'function_call')
        self.assertEqual(items[1]['call_id'],'call_1')
        self.assertEqual(items[1]['type'],'function_call_output')

    def test_smtp_login_failure_updates_health(self):
        import smtplib
        with patch.object(self.core,'ORIGINAL_SMTP_LOGIN',side_effect=smtplib.SMTPAuthenticationError(535,b'Authentication rejected')):
            with self.assertRaises(smtplib.SMTPAuthenticationError):self.core.tracked_smtp_login(object(),'test','test')
        with self.app.db() as c:
            self.assertEqual(c.execute("SELECT status FROM service_health WHERE service='smtp'").fetchone()[0],'access denied')

if __name__=='__main__':unittest.main()
