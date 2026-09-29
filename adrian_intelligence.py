"""Shared job intelligence: real V7 records, public-web leads, explicit feedback, transparent ranking."""
import json,re,sqlite3
from urllib.parse import urlparse,parse_qsl,urlencode,urlunparse
from datetime import datetime,timezone
from fastapi import HTTPException

KEYWORDS={'fast_food':('crew','restaurant','food','kitchen','cook','barista','cashier','mcdonald','tim horton','wendy','chipotle','subway','popeyes','burger'), 'retail':('retail','store','sales associate','cashier','stock','walmart','grocery','loblaw','dollarama','marshalls'), 'warehouse':('warehouse','picker','packer','fulfillment','shipping','inventory'), 'customer_service':('customer service','service representative','front desk')}
AREAS=('whitby','oshawa','ajax','pickering','brooklin','courtice','bowmanville','clarington','durham')
def init(db):
 with db() as c:
  c.executescript('''CREATE TABLE IF NOT EXISTS ai_job_feedback(id INTEGER PRIMARY KEY,job_key TEXT NOT NULL,category TEXT NOT NULL,choice TEXT NOT NULL,at TEXT NOT NULL, UNIQUE(job_key,choice)); CREATE TABLE IF NOT EXISTS ai_web_leads(id INTEGER PRIMARY KEY,url TEXT NOT NULL UNIQUE,title TEXT NOT NULL,query TEXT NOT NULL,found TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'unverified_search_lead'); CREATE TABLE IF NOT EXISTS ai_job_checks(id INTEGER PRIMARY KEY,at TEXT NOT NULL,source TEXT NOT NULL,result TEXT NOT NULL);''')
def normalized(url):
 p=urlparse(url or '')
 if p.scheme!='https' or not p.hostname or p.username or p.password or len(url)>1500:return None
 if p.hostname in ('localhost','127.0.0.1') or p.hostname.endswith('.local'):return None
 qs=[(k,v) for k,v in parse_qsl(p.query) if not k.lower().startswith('utm_') and k.lower() not in ('fbclid','gclid')]
 return urlunparse((p.scheme,p.netloc.lower(),p.path.rstrip('/'),'',urlencode(qs),'')).lower()
def category(j):
 s=(j.get('title','')+' '+j.get('employer','')).lower()
 return next((k for k,terms in KEYWORDS.items() if any(t in s for t in terms)),'other')
def feedback(db,job_key,choice):
 if choice not in ('save','skip','applied'):raise ValueError('Invalid feedback')
 with db() as c:
  row=c.execute('SELECT employer,title,url FROM job_v7_postings WHERE id=?',(job_key,)).fetchone()
  if not row:
   row=c.execute('SELECT employer,title,url FROM job_v7_review WHERE id=?',(job_key,)).fetchone() if c.execute("SELECT name FROM sqlite_master WHERE name='job_v7_review'").fetchone() else None
  if not row:raise ValueError('Job not found')
  key=normalized(row['url']) or row['url'];cat=category(dict(row))
  c.execute('INSERT OR IGNORE INTO ai_job_feedback(job_key,category,choice,at) VALUES(?,?,?,?)',(key,cat,choice,datetime.now(timezone.utc).isoformat()))
 return {'ok':True,'choice':choice,'category':cat}
def recommendations(db,limit=30):
 with db() as c:
  weights={r['category']:r['n'] for r in c.execute("SELECT category,SUM(CASE WHEN choice IN ('save','applied') THEN 2 ELSE -2 END) n FROM ai_job_feedback GROUP BY category")}
  seen={r['job_key'] for r in c.execute('SELECT job_key FROM ai_job_feedback')}
  items=[]
  for table,kind in [('job_v7_postings','posting'),('job_v7_review','needs_verification')]:
   if not c.execute('SELECT 1 FROM sqlite_master WHERE name=?',(table,)).fetchone():continue
   cols={x[1] for x in c.execute('PRAGMA table_info('+table+')')}

   select = 'rowid AS _sort_id,' + ','.join(
    x for x in ('id', 'employer', 'title', 'location', 'url', 'pay', 'reason', 'emailed', 'found')
    if x in cols
   )
   for r in c.execute('SELECT ' + select + ' FROM ' + table + ' ORDER BY rowid DESC LIMIT 250'):

    j=dict(r);j['kind']=kind;j['category']=category(j)
    j['id']=j.get('id',j['_sort_id'])
    j['feedback_weight']=weights.get(j['category'],0)
    j['already_reviewed']=bool((normalized(j['url']) or j['url']) in seen)
    j['reasoning']='Preference weight from your saved/skipped/applied job categories; not a hiring probability.'
    items.append(j)
  items.sort(key=lambda x:(x['already_reviewed'], -x['feedback_weight'],-x['id']))
  leads=[dict(r) for r in c.execute('SELECT * FROM ai_web_leads ORDER BY id DESC LIMIT 50')]
 return {'jobs':items[:limit],'web_leads':leads,'learned_category_weights':weights,'note':'Job records originate in installed V7 feeds. Web leads are unverified search citations, NOT confirmed openings. Feedback ranking is a transparent local heuristic, not model retraining.'}
def store_leads(db,query,result):
 count=0
 with db() as c:
  for src in result.get('sources',[]):
   url=src.get('url','');key=normalized(url)
   if not key:continue
   title=str(src.get('title') or 'Public search result')[:180]
   if not any(a in (title+' '+query).lower() for a in AREAS):continue
   cur=c.execute('INSERT OR IGNORE INTO ai_web_leads(url,title,query,found) VALUES(?,?,?,?)',(key,title,query[:500],datetime.now(timezone.utc).isoformat()))
   count+=cur.rowcount
 return count
SEARCHES=(
 'Whitby Oshawa Ajax Pickering Bowmanville part time crew member McDonalds Tim Hortons Wendy Subway careers hiring',
 'Durham Region Ontario part time retail cashier sales associate Walmart Dollarama grocery careers hiring',
 'Durham Region Ontario part time warehouse picker packer customer service jobs hiring')
async def web_discovery(db,provider,web_search):
 if not provider:return {'ok':False,'error':'Connect OpenAI provider for public web search; existing V7 feeds remain available.'}
 checks=[];new=0
 for q in SEARCHES:
  result=await web_search(provider,q)
  if result.get('ok'):new+=store_leads(db,q,result)
  checks.append({'query':q,'ok':result.get('ok',False),'sources':len(result.get('sources',[])),'error':result.get('error')})
 with db() as c:c.execute('INSERT INTO ai_job_checks(at,source,result) VALUES(?,?,?)',(datetime.now(timezone.utc).isoformat(),'public_web',json.dumps(checks)))
 return {'ok':any(x['ok'] for x in checks),'new_unverified_leads':new,'checks':checks,'note':'Cited web pages are leads, not verified vacancies. Existing V7 discovery handles structured job postings.'}
