import unittest,asyncio,sqlite3,tempfile,json
from contextlib import contextmanager
from datetime import datetime,timedelta,timezone
from unittest.mock import Mock,AsyncMock,patch
import paper_experiment as bot

NOW=datetime(2026,9,30,15,tzinfo=timezone.utc)
def data():
    bars=[]
    for day in range(3):
        for i in range(26 if day<2 else 6):
            when=datetime(2026,9,28+day,13,30,tzinfo=timezone.utc)+timedelta(minutes=i*15)
            p=100+len(bars)*.05
            bars.append({'time':when.isoformat(),'open':p-.05,'close':p,'high':p+.2,'low':p-.2,'volume':1000000})
    return {'candles':bars,'quality':{'recent_intraday_bar':True}}
class ExperimentTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();path=self.temp.name+'/test.db'
        @contextmanager
        def db():
            c=sqlite3.connect(path);c.row_factory=sqlite3.Row
            try:yield c;c.commit()
            finally:c.close()
        self.db=db;self.account={'equity':'100000','cash':'100000','currency':'USD','status':'ACTIVE'}
        self.clock={'is_open':True,'next_close':'2026-09-30T20:00:00Z'};self.posts=[];self.orders=[];self.positions=[]
        async def broker(path,method='GET',payload=None):
            if path=='/v2/account':return self.account
            if path=='/v2/clock':return self.clock
            if path=='/v2/positions':return self.positions
            if path.startswith('/v2/orders?'):return self.orders
            if path.startswith('/v2/orders:by_client_order_id'):
                client=path.split('client_order_id=')[1]
                found=next((x for x in self.orders if x['client_order_id']==client),None)
                if not found:raise ValueError('Not found')
                return found
            if method=='POST':
                self.posts.append(payload);order=payload|{'id':'order-'+str(len(self.posts)),'status':'new','filled_qty':'0','filled_avg_price':None};self.orders.append(order);return order
            if method=='DELETE':return {}
            raise ValueError(path)
        close=data()['candles'][-1]['close']
        snapshot={'latestTrade':{'t':(NOW-timedelta(seconds=10)).isoformat(),'p':close},'latestQuote':{'t':(NOW-timedelta(seconds=10)).isoformat(),'bp':close-.01,'ap':close+.01},'minuteBar':{'t':(NOW-timedelta(seconds=90)).isoformat(),'c':close,'v':100}}
        self.paper=Mock();self.paper.broker=AsyncMock(side_effect=broker);self.paper.bars=AsyncMock(return_value=data());self.paper.snapshot=AsyncMock(return_value=snapshot)
        self.engine=bot.Engine(db,self.paper,Mock(),Mock())
        self.clock_patch=patch.object(bot,'utc',return_value=NOW);self.clock_patch.start()
    def tearDown(self):self.clock_patch.stop();self.temp.cleanup()
    async def ready(self):
        await self.engine.start();s=self.engine.config();s['universe']=['MSFT','NVDA','AMD','AAPL'];self.engine.save(s)
        model={'trees':[{'left':[-1],'right':[-1],'feature':[-2],'threshold':[-2],'positive':[.8]}]}
        with self.db() as c:c.execute('INSERT INTO ml_models(at,model,report) VALUES(?,?,?)',(NOW.isoformat(),json.dumps(model),json.dumps({'paper_eligible':True})))
    async def test_start_is_paper_only_one_week_and_empty_account(self):
        result=await self.engine.start();s=result['settings']
        self.assertEqual(datetime.fromisoformat(s['ends'])-NOW,timedelta(days=7));self.assertFalse(s['allow_real_money']);self.assertEqual(self.posts,[])
        s['enabled']=False;self.engine.save(s);self.positions=[{'symbol':'MSFT'}]
        with self.assertRaises(Exception):await self.engine.start()
    async def test_actual_broker_post_three_positions_risk_and_no_duplicate(self):
        await self.ready()
        with patch('trading_division.news',new=AsyncMock(return_value={'articles':[]})):
            await self.engine.scan(self.clock,self.account);await self.engine.scan(self.clock,self.account)
        self.assertEqual(len(self.posts),3)
        self.assertTrue(all(p['order_class']=='bracket' and p['time_in_force']=='day' for p in self.posts))
        self.assertEqual(len({p['client_order_id'] for p in self.posts}),3)
        self.assertLessEqual(sum(float(p['qty'])*float(p['limit_price']) for p in self.posts),100000)
    async def test_closed_market_never_posts(self):
        await self.ready();self.clock['is_open']=False
        await self.engine.scan(self.clock,self.account);self.assertEqual(self.posts,[])
    async def test_failed_model_never_posts(self):
        await self.ready()
        with self.db() as c:c.execute('UPDATE ml_models SET report=?',(json.dumps({'paper_eligible':False}),))
        await self.engine.scan(self.clock,self.account);self.assertEqual(self.posts,[])
    async def test_stale_quote_prevents_entry(self):
        await self.ready();self.paper.snapshot=AsyncMock(return_value={'latestTrade':{'t':(NOW-timedelta(hours=1)).isoformat()}})
        await self.engine.scan(self.clock,self.account);self.assertEqual(self.posts,[])
    async def test_uncertain_submission_blocks_retries(self):
        await self.ready();original=self.paper.broker.side_effect
        async def uncertain(path,method='GET',payload=None):
            if method=='POST':self.posts.append(payload);raise TimeoutError()
            return await original(path,method,payload)
        self.paper.broker.side_effect=uncertain
        with patch('trading_division.news',new=AsyncMock(return_value={'articles':[]})):
            await self.engine.scan(self.clock,self.account);await self.engine.scan(self.clock,self.account)
        self.assertEqual(len(self.posts),1);self.assertEqual(self.engine.active()[0]['status'],'uncertain')
    async def test_existing_symbol_not_touched(self):
        await self.ready();self.positions=[{'symbol':s} for s in ['MSFT','NVDA','AMD']]
        await self.engine.scan(self.clock,self.account);self.assertEqual(self.posts,[])
    def test_daily_week_and_cash_risk_headroom(self):
        self.assertEqual(bot.risk_size(self.account,100,99,0,100000,102000),0)
        self.assertEqual(bot.risk_size(self.account,100,99,0,103000,100000),0)
        self.assertEqual(bot.risk_size(self.account,100,99,1100,100000,100000),0)
        tiny=self.account|{'cash':'150'};self.assertEqual(bot.risk_size(tiny,100,99,0,100000,100000),1)
    async def test_stop_loss_threshold_disables_entry(self):
        await self.ready();self.account['equity']='97999'
        await self.engine.monitor(self.clock,self.account)
        self.assertTrue(self.engine.config()['halt_entries']);self.assertFalse(self.engine.config()['enabled'])
    async def test_manual_added_shares_prevent_flatten(self):
        await self.ready()
        with patch('trading_division.news',new=AsyncMock(return_value={'articles':[]})):await self.engine.scan(self.clock,self.account)
        row=self.engine.active()[0];original=self.orders[0];original.update(filled_qty='1',filled_avg_price=original['limit_price'],status='filled');self.orders=[]
        self.positions=[{'symbol':row['symbol'],'qty':'2'}]
        previous=self.paper.broker.side_effect
        async def broker(path,method='GET',payload=None):
            if path.startswith('/v2/orders:by_client_order_id'):return original
            return await previous(path,method,payload)
        self.paper.broker.side_effect=broker
        with self.assertRaises(ValueError):await self.engine.close_owned(row,'time exit')
        self.assertEqual(len(self.posts),3)
if __name__=='__main__':unittest.main()
