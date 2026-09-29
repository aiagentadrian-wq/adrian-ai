"""ADRIAN.AI trading research add-on. No broker connectivity or live order execution."""
import os, time, json, sqlite3, math
from datetime import datetime, timezone
from pathlib import Path
import httpx
from fastapi import HTTPException, Request
from pydantic import BaseModel, Field

AGENTS = [
('Trading Manager','Coordinates verified evidence and research reports'),('Market Data','Quotes and candles with timestamps'),
('News Intelligence','Timestamped financial news and provenance'),('Company Research','SEC filings and company facts'),
('Technical Analysis','Transparent indicator calculations'),('Discovery','Research watchlist for listed companies'),
('Economic Intelligence','US and Canadian economic series'),('Event Intelligence','Filings and economic event timelines'),
('Sentiment','News text review, never fabricated scores'),('ML Prediction','Out-of-sample model laboratory'),
('Risk Management','Risk and liquidity scenarios'),('Backtesting','Historical evaluation with costs'),
('Portfolio','Paper positions and trade journal'),('Independent Reviewer','Flags missing and contradictory evidence')]
_cache={}
def utc(): return datetime.now(timezone.utc).isoformat(timespec='seconds')
def cached(key, ttl, loader):
    t=time.monotonic(); entry=_cache.get(key)
    if entry and t-entry[0]<ttl:return entry[1]
    value=loader(); _cache[key]=(t,value);return value
async def get_json(url, params=None, headers=None):
    try:
        async with httpx.AsyncClient(timeout=20,follow_redirects=False) as client:
            r=await client.get(url,params=params,headers=headers)
        if r.status_code>=400:raise HTTPException(502,f'Upstream data service HTTP {r.status_code}')
        return r.json()
    except (httpx.RequestError,ValueError) as e:raise HTTPException(502,f'Data source unavailable: {type(e).__name__}')
def key(name):return os.getenv(name,'').strip().strip('"').strip("'")
async def market(symbol,interval='1day',size=60):
    if not key('TWELVE_DATA_API_KEY'):raise HTTPException(503,'TWELVE_DATA_API_KEY not configured')
    data=await get_json('https://api.twelvedata.com/time_series',{'symbol':symbol,'interval':interval,'outputsize':size,'apikey':key('TWELVE_DATA_API_KEY')})
    if not data.get('values'):raise HTTPException(502,'Market feed returned no candles: '+str(data.get('message','unknown'))[:120])
    candles=[]
    for x in reversed(data['values']):
        candles.append({'time':x['datetime'],'open':float(x['open']),'high':float(x['high']),'low':float(x['low']),'close':float(x['close']),'volume':float(x['volume']) if x.get('volume') not in (None,'') else None})
    return {'source':'Twelve Data','retrieved_utc':utc(),'symbol':symbol,'interval':interval,'meta':data.get('meta',{}),'candles':candles,'note':'Data may be delayed or exchange-restricted. Verify feed entitlement and timestamps.'}
async def news(q):
    if not key('GNEWS_API_KEY'):raise HTTPException(503,'GNEWS_API_KEY not configured')
    d=await get_json('https://gnews.io/api/v4/search',{'q':q,'lang':'en','max':8,'apikey':key('GNEWS_API_KEY')})
    return {'source':'GNews','retrieved_utc':utc(),'articles':[{'title':x.get('title'),'url':x.get('url'),'published_at':x.get('publishedAt'),'source':x.get('source',{}).get('name'),'description':x.get('description')} for x in d.get('articles',[])],'note':'Free-plan news may be delayed; syndicated stories are not independent confirmations.'}
async def fred():
    if not key('FRED_API_KEY'):raise HTTPException(503,'FRED_API_KEY not configured')
    d=await get_json('https://api.stlouisfed.org/fred/series/observations',{'series_id':'FEDFUNDS','api_key':key('FRED_API_KEY'),'file_type':'json','sort_order':'desc','limit':3})
    return {'source':'FRED','series':'FEDFUNDS','retrieved_utc':utc(),'observations':[{'date':x['date'],'value':x['value']} for x in d.get('observations',[])]}
async def sec(cik='0000320193'):
    ua=key('SEC_USER_AGENT')
    if not ua:raise HTTPException(503,'SEC_USER_AGENT not configured')
    d=await get_json(f'https://data.sec.gov/submissions/CIK{cik}.json',headers={'User-Agent':ua,'Accept':'application/json'})
    r=d.get('filings',{}).get('recent',{})
    return {'source':'SEC EDGAR','retrieved_utc':utc(),'company':d.get('name'),'cik':cik,'filings':[{'form':f,'date':dt,'accession':a} for f,dt,a in list(zip(r.get('form',[]),r.get('filingDate',[]),r.get('accessionNumber',[])))[:12]]}
async def boc():
    d=await get_json('https://www.bankofcanada.ca/valet/observations/FXUSDCAD/json',{'recent':3})
    return {'source':'Bank of Canada','series':'FXUSDCAD','retrieved_utc':utc(),'observations':[{'date':x.get('d'),'value':x.get('FXUSDCAD',{}).get('v')} for x in d.get('observations',[])]}
async def statcan():
    try:
        async with httpx.AsyncClient(timeout=25) as client:r=await client.post('https://www150.statcan.gc.ca/t1/wds/rest/getCubeMetadata',json=[{'productId':18100004}])
        r.raise_for_status();d=r.json()[0]
        if d.get('status')!='SUCCESS':raise ValueError('Metadata not available')
        return {'source':'Statistics Canada','retrieved_utc':utc(),'dataset':d['object'].get('cubeTitleEn'),'product_id':18100004,'note':'Metadata only; not a live CPI observation.'}
    except (httpx.RequestError,httpx.HTTPStatusError,ValueError,KeyError,IndexError,TypeError) as e:raise HTTPException(502,f'Statistics Canada unavailable: {type(e).__name__}')
def technical(candles):
    close=[x['close'] for x in candles]; last=close[-1]
    sma=lambda n:round(sum(close[-n:])/n,4) if len(close)>=n else None
    change=round((last/close[-2]-1)*100,3) if len(close)>1 and close[-2] else None
    return {'last_close':last,'change_percent':change,'sma_20':sma(20),'sma_50':sma(50),'sample_count':len(close),'note':'Descriptive indicators, not validated trade signals.'}
def init(db):
    with db() as c:
        c.execute('CREATE TABLE IF NOT EXISTS trading_watchlist(symbol TEXT PRIMARY KEY, added_utc TEXT NOT NULL, note TEXT NOT NULL DEFAULT "")')
        c.execute('CREATE TABLE IF NOT EXISTS trading_research(id INTEGER PRIMARY KEY, created_utc TEXT NOT NULL, symbol TEXT NOT NULL, report_json TEXT NOT NULL)')
        c.execute('CREATE TABLE IF NOT EXISTS trading_paper_journal(id INTEGER PRIMARY KEY, created_utc TEXT NOT NULL, symbol TEXT NOT NULL, side TEXT NOT NULL, quantity REAL NOT NULL, price REAL NOT NULL, note TEXT NOT NULL)')
class SymbolIn(BaseModel):
    symbol:str=Field(min_length=1,max_length=24,pattern=r'^[A-Za-z0-9.:-]+$')
    note:str=Field(default='',max_length=300)
class PaperIn(BaseModel):
    symbol:str=Field(min_length=1,max_length=24,pattern=r'^[A-Za-z0-9.:-]+$')
    side:str=Field(pattern=r'^(buy|sell)$')
    quantity:float=Field(gt=0,le=1000000)
    price:float=Field(gt=0,le=100000000)
    note:str=Field(default='',max_length=500)
def install(app,db,auth,csrf):
    init(db)
    @app.get('/api/trading/status')
    def status(req:Request):
        auth(req)
        return {'agents':[{'name':n,'role':d} for n,d in AGENTS],'connections':{x:bool(key(y)) for x,y in [('Twelve Data','TWELVE_DATA_API_KEY'),('GNews','GNEWS_API_KEY'),('FRED','FRED_API_KEY'),('SEC EDGAR','SEC_USER_AGENT')]},'public_sources':['Bank of Canada','Statistics Canada'],'mode':'research_and_manual_paper_journal','ml_status':'not trained; requires timestamped historical dataset and walk-forward evaluation','live_orders_enabled':False}
    @app.get('/api/trading/market')
    async def market_route(req:Request,symbol:str,interval:str='1day'):
        auth(req)
        if not __import__('re').fullmatch(r'[A-Za-z0-9.:-]{1,24}',symbol):raise HTTPException(400,'Invalid symbol')
        if interval not in ('1day','1h','15min'):raise HTTPException(400,'Unsupported interval')
        return await market(symbol.upper(),interval)
    @app.get('/api/trading/news')
    async def news_route(req:Request,q:str='stock market'):
        auth(req)
        if not 2<=len(q)<=100:raise HTTPException(400,'Invalid query')
        return await news(q)
    @app.get('/api/trading/economy')
    async def economy(req:Request):
        auth(req); results={}
        for name,fn in [('FRED',fred),('Bank of Canada',boc),('Statistics Canada',statcan)]:
            try:results[name]=await fn()
            except HTTPException as e:results[name]={'error':e.detail}
        return results
    @app.get('/api/trading/filings')
    async def filings(req:Request,cik:str='0000320193'):
        auth(req)
        if not __import__('re').fullmatch(r'\d{1,10}',cik):raise HTTPException(400,'Invalid CIK')
        return await sec(cik.zfill(10))
    @app.get('/api/trading/watchlist')
    def watchlist(req:Request):
        auth(req)
        with db() as c:return {'items':[dict(x) for x in c.execute('SELECT * FROM trading_watchlist ORDER BY added_utc DESC')]}
    @app.post('/api/trading/watchlist')
    def add_watchlist(body:SymbolIn,req:Request):
        csrf(req)
        with db() as c:c.execute('INSERT INTO trading_watchlist(symbol,added_utc,note) VALUES(?,?,?) ON CONFLICT(symbol) DO UPDATE SET note=excluded.note',(body.symbol.upper(),utc(),body.note))
        return {'ok':True}
    @app.delete('/api/trading/watchlist/{symbol}')
    def remove_watchlist(symbol:str,req:Request):
        csrf(req)
        with db() as c:c.execute('DELETE FROM trading_watchlist WHERE symbol=?',(symbol.upper(),))
        return {'ok':True}
    @app.post('/api/trading/research')
    async def research(body:SymbolIn,req:Request):
        csrf(req); symbol=body.symbol.upper(); sources={}; errors={}
        for name,fn in [('market',lambda:market(symbol)),('news',lambda:news(symbol)),('economy_us',fred),('economy_ca',boc)]:
            try:sources[name]=await fn()
            except HTTPException as e:errors[name]=e.detail
        if 'market' not in sources:raise HTTPException(502,'Cannot research without verified market data: '+str(errors.get('market')))
        report={'symbol':symbol,'created_utc':utc(),'sources':sources,'errors':errors,'technical':technical(sources['market']['candles']),'evidence_status':'Partial if errors are present; no source-independence validation yet.','trade_decision':'No trade recommendation: ML and risk models not validated.','ml_status':'Not trained','paper_only':True}
        with db() as c:c.execute('INSERT INTO trading_research(created_utc,symbol,report_json) VALUES(?,?,?)',(report['created_utc'],symbol,json.dumps(report)))
        return report
    @app.get('/api/trading/reports')
    def reports(req:Request):
        auth(req)
        with db() as c:return {'items':[{'id':x['id'],'created_utc':x['created_utc'],'symbol':x['symbol']} for x in c.execute('SELECT id,created_utc,symbol FROM trading_research ORDER BY id DESC LIMIT 30')]}
    @app.get('/api/trading/reports/{rid}')
    def report(rid:int,req:Request):
        auth(req)
        with db() as c:r=c.execute('SELECT report_json FROM trading_research WHERE id=?',(rid,)).fetchone()
        if not r:raise HTTPException(404,'Report not found')
        return json.loads(r['report_json'])
    @app.get('/api/trading/paper')
    def paper(req:Request):
        auth(req)
        with db() as c:return {'items':[dict(x) for x in c.execute('SELECT * FROM trading_paper_journal ORDER BY id DESC LIMIT 100')],'note':'Manual paper journal, not a broker-connected simulator or realized P&L engine.'}
    @app.post('/api/trading/paper')
    def paper_add(body:PaperIn,req:Request):
        csrf(req)
        with db() as c:c.execute('INSERT INTO trading_paper_journal(created_utc,symbol,side,quantity,price,note) VALUES(?,?,?,?,?,?)',(utc(),body.symbol.upper(),body.side,body.quantity,body.price,body.note))
        return {'ok':True,'mode':'paper_only'}
