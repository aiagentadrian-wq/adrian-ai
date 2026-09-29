"""Isolated regression checks: never touch the installed user's database or credentials."""
import asyncio
import importlib
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

class DashboardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory();root=Path(cls.temp.name)
        for p in Path(__file__).parent.glob('*.py'):
            if 'backup' not in p.name and not p.name.startswith('test_'):shutil.copy2(p,root/p.name)
        shutil.copytree(Path(__file__).parent/'static',root/'static')
        cls.env=patch.dict(os.environ,APP_PASSWORD='dashboard-test-password',SESSION_SECRET='x'*64,ENCRYPTION_KEY=Fernet.generate_key().decode())
        cls.env.start();sys.path.insert(0,str(root))
        cls.app=importlib.import_module('app');cls.core=importlib.import_module('dashboard_core')
        cls.client=TestClient(cls.app.app)
        cls.client.post('/api/login',json={'password':'dashboard-test-password'})
        cls.headers={'X-CSRF-Token':cls.client.cookies.get('acc_csrf')}

    @classmethod
    def tearDownClass(cls):
        cls.client.close();cls.env.stop();sys.path.pop(0);cls.temp.cleanup()

    def test_auth_and_csrf(self):
        with TestClient(self.app.app) as anonymous:
            self.assertEqual(anonymous.get('/api/pro/services').status_code,401)
        self.assertEqual(self.client.post('/api/pro/writer/save',json={'content':'test'}).status_code,403)

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

if __name__=='__main__':unittest.main()
