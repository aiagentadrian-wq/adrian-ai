import asyncio,json,sqlite3,tempfile,unittest
from contextlib import contextmanager
from datetime import timedelta
from email.message import EmailMessage
from unittest.mock import AsyncMock,Mock,patch
from cryptography.fernet import Fernet
import paper_trading as p

class PaperTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.path=self.temp.name+'/test.db'
        @contextmanager
        def db():
            c=sqlite3.connect(self.path);c.row_factory=sqlite3.Row
            try:yield c;c.commit()
            finally:c.close()
        self.db=db;self.cipher=Fernet(Fernet.generate_key());self.e=p.Engine(db,self.cipher,Mock(),Mock(),AsyncMock())
        self.e.save({'owner':'paper-owner@gmail.com','risk_percent':.25,'approval_enabled':True})
    def tearDown(self):self.temp.cleanup()
    def row(self,expires=None):
        plan={'symbol':'MSFT','entry':100,'stop':99,'target':102,'qty':1,'risk_percent':.25}
        row={'id':'a'*32,'at':p.iso(),'expires':expires or (p.utc()+timedelta(minutes=10)).isoformat(),'status':'pending','message_id':'<unique@gmail.com>','payload':json.dumps(plan),'broker_id':None,'detail':''}
        with self.db() as c:c.execute('INSERT INTO paper_proposals VALUES(?,?,?,?,?,?,?,?)',tuple(row.values()))
        return row
    def reply(self,sender='paper-owner@gmail.com',body='YES',auth=True):
        m=EmailMessage();m['From']=sender;m['In-Reply-To']='<unique@gmail.com>'
        if auth:m['Authentication-Results']='mx.google.com; dkim=pass header.i=@gmail.com'
        m.set_content(body);return m
    def test_approval_exact_sender_authenticated_thread_and_word(self):
        row=self.row()
        self.assertTrue(p.approval_matches(self.reply(),row,'paper-owner@gmail.com'))
        for m in (self.reply('attacker@gmail.com'),self.reply(auth=False),self.reply(body='yes please'),self.reply(body='NO\n> YES')):
            expected=p.first_reply(m)=='NO';self.assertEqual(p.approval_matches(m,row,'paper-owner@gmail.com'),expected)
        m=self.reply();m.replace_header('In-Reply-To','<wrong@gmail.com>');self.assertFalse(p.approval_matches(m,row,'paper-owner@gmail.com'))
    def test_reject_nonfinite_bad_stops_and_reward(self):
        for entry,stop,target in [(float('nan'),99,102),(100,101,102),(100,99,100.5),(100,80,140)]:
            with self.assertRaises(ValueError):p.clean_plan(dict(symbol='MSFT',entry=entry,stop=stop,target=target))
    async def test_expired_never_calls_broker(self):
        self.e.broker=AsyncMock();await self.e.execute(self.row((p.utc()-timedelta(seconds=1)).isoformat()));self.e.broker.assert_not_called()
        self.assertEqual(self.e.summary()['proposals'][0]['status'],'expired')
    def good_broker(self):
        async def broker(path,method='GET',payload=None):
            if path=='/v2/clock':return {'is_open':True}
            if path=='/v2/account':return {'equity':'1000','last_equity':'1000','cash':'1000'}
            if path.startswith('/v2/positions') or path.startswith('/v2/orders?'):return []
            if method=='POST':return {'id':'paper-order','status':'new'}
        self.e.broker=AsyncMock(side_effect=broker)
        self.e.snapshot=AsyncMock(return_value={'latestTrade':{'t':p.iso(),'p':100},'minuteBar':{'t':(p.utc()-timedelta(seconds=70)).isoformat(),'c':100,'v':10}})
        self.e.mail=Mock()
    async def test_exactly_once_bracket_submission(self):
        self.good_broker();row=self.row();await self.e.execute(row);await self.e.execute(row)
        calls=[c for c in self.e.broker.call_args_list if len(c.args)>1 and c.args[1]=='POST']
        self.assertEqual(len(calls),1);order=calls[0].args[2]
        self.assertEqual(order['order_class'],'bracket');self.assertEqual(order['client_order_id'],'adrian-'+row['id'])
        self.assertEqual(self.e.summary()['proposals'][0]['status'],'submitted')
    async def test_stale_quote_skips(self):
        self.good_broker();self.e.snapshot.return_value['latestTrade']['t']=(p.utc()-timedelta(minutes=5)).isoformat()
        await self.e.execute(self.row());self.assertEqual(self.e.summary()['proposals'][0]['status'],'skipped')
    async def test_unconfirmed_bar_skips(self):
        self.good_broker();self.e.snapshot.return_value['minuteBar']['t']=p.iso()
        await self.e.execute(self.row());self.assertEqual(self.e.summary()['proposals'][0]['status'],'skipped')
    async def test_price_chase_skips(self):
        self.good_broker();self.e.snapshot.return_value['latestTrade']['p']=101
        await self.e.execute(self.row());self.assertEqual(self.e.summary()['proposals'][0]['status'],'skipped')
    async def test_uncertain_submission_is_not_retried(self):
        self.good_broker();original=self.e.broker.side_effect
        async def broker(path,method='GET',payload=None):
            if method=='POST':raise TimeoutError()
            return await original(path,method,payload)
        self.e.broker.side_effect=broker;row=self.row();await self.e.execute(row);await self.e.execute(row)
        self.assertEqual(self.e.summary()['proposals'][0]['status'],'uncertain')
        self.assertEqual(sum(len(c.args)>1 and c.args[1]=='POST' for c in self.e.broker.call_args_list),1)
    async def test_paper_endpoint_immutable_and_secrets_encrypted(self):
        self.e.save({'key':self.cipher.encrypt(b'test-key').decode(),'secret':self.cipher.encrypt(b'test-secret').decode(),'base_url':'https://api.alpaca.markets'})
        self.assertNotIn('test-secret',json.dumps(self.e.config()))
        response=Mock(status_code=200,content=b'{}');response.json.return_value={}
        with patch('httpx.AsyncClient.request',new=AsyncMock(return_value=response)) as request:
            await self.e.broker('/v2/account');self.assertTrue(request.call_args.args[1].startswith(p.PAPER))
    async def test_risk_budget_rechecked(self):
        self.good_broker();r=self.row();plan=json.loads(r['payload']);plan['qty']=10;r['payload']=json.dumps(plan)
        await self.e.execute(r);self.assertEqual(self.e.summary()['proposals'][0]['status'],'skipped')
    def test_forged_secondary_authentication_header_cannot_approve(self):
        m=self.reply(auth=False);m['Authentication-Results']='mx.google.com; dkim=fail';m['Authentication-Results']='mx.google.com; dkim=pass header.i=@gmail.com'
        self.assertFalse(p.approval_matches(m,self.row(),'paper-owner@gmail.com'))
    async def test_existing_position_blocks_entry(self):
        self.good_broker();original=self.e.broker.side_effect
        async def broker(path,method='GET',payload=None):
            if path=='/v2/positions':return [{'symbol':'AMD'}]
            return await original(path,method,payload)
        self.e.broker.side_effect=broker;await self.e.execute(self.row())
        self.assertEqual(self.e.summary()['proposals'][0]['status'],'skipped')
    async def test_imap_initial_check_and_authenticated_reply(self):
        fake=Mock();fake.login.return_value=('OK',[]);fake.select.return_value=('OK',[]);fake.response.return_value=('UIDVALIDITY',[b'7'])
        fake.uid.side_effect=[('OK',[b'1 2'])]
        with patch('imaplib.IMAP4_SSL') as ctor:
            ctor.return_value.__enter__.return_value=fake
            self.e.secret=Mock(return_value='app-password')
            self.assertEqual(self.e.read_replies(),[])
            self.assertEqual(self.e.config()['last_uid'],2)
            fake.uid.side_effect=[('OK',[b'1 2 3']),('OK',[(b'3',self.reply().as_bytes())])]
            self.assertEqual(p.first_reply(self.e.read_replies()[0]),'YES');self.assertEqual(self.e.config()['last_uid'],3)
    async def test_imap_failure_does_not_advance_cursor(self):
        self.e.save({'owner':'paper-owner@gmail.com','last_uid':2,'uidvalidity':"[b'7']"})
        fake=Mock();fake.response.return_value=('UIDVALIDITY',[b'7']);fake.uid.side_effect=[('OK',[b'1 2 3']),('NO',[])]
        with patch('imaplib.IMAP4_SSL') as ctor:
            ctor.return_value.__enter__.return_value=fake;self.e.secret=Mock(return_value='app-password')
            self.assertEqual(self.e.read_replies(),[]);self.assertEqual(self.e.config()['last_uid'],2)

if __name__=='__main__':unittest.main()
