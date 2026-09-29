"""Public permitted feeds only. No scraping Indeed/Job Bank. Fail closed on unknown pay/hours/location."""
import os,re,html,sqlite3,datetime,urllib.parse,hashlib
from xml.etree import ElementTree as ET
import httpx
from pathlib import Path
from zoneinfo import ZoneInfo
AREA=('whitby','oshawa','ajax','pickering','brooklin','courtice','bowmanville','clarington','durham region')
TYPES=('retail','warehouse','food','restaurant','crew','cashier','customer service','stock','store associate','barista','kitchen','cook','server','team member','fulfillment','fulfilment','sales associate','dishwasher','picker','packer')
EXCLUDE=('manager','director','supervisor','senior engineer','registered nurse','software engineer')
def clean(s):return re.sub(r'\s+',' ',html.unescape(re.sub('<[^>]*>',' ',s or ''))).strip()
def pay_ok(s):
    t=clean(s).lower().replace(',','')
    # Never guess annual/monthly compensation or missing wage.
    if not re.search(r'(hour|hr|hourly)',t):return False
    vals=[float(x) for x in re.findall(r'\$\s*(\d{2}(?:\.\d{1,2})?)',t)]
    return bool(vals) and min(vals)>=17

def eligible(j):
    title=clean(j.get('title','')).lower(); loc=clean(j.get('location','')).lower(); desc=clean(j.get('description','')).lower(); pay=clean(j.get('pay',''))
    if not any(a in loc for a in AREA):return False
    if not any(t in title for t in TYPES) or any(t in title for t in EXCLUDE):return False
    if not re.search(r'part[ -]?time',title+' '+desc):return False
    if not pay_ok(pay):return False
    u=urllib.parse.urlparse(j.get('url',''))
    return u.scheme=='https' and bool(u.hostname)

def review_reason(j):
    """Why a relevant Durham posting is not a confirmed match."""
    title=clean(j.get('title','')).lower()
    loc=clean(j.get('location','')).lower()
    desc=clean(j.get('description','')).lower()
    if not any(a in loc for a in AREA): return None
    if not any(t in title for t in TYPES) or any(t in title for t in EXCLUDE): return None
    if not re.search(r'part[ -]?time', title+' '+desc): return 'Hours not explicitly part-time'
    if not pay_ok(j.get('pay','')): return 'Hourly pay of at least CAD $17 not confirmed'
    return None

def public_feed_jobs(client, feed_url):
    """Read a user-configured public RSS/Atom feed, not a search-page scrape."""
    u=urllib.parse.urlparse(feed_url)
    if u.scheme!='https' or not u.hostname or u.username or u.password:
        raise ValueError('Public HTTPS feed URL required')
    if u.hostname.lower() in ('localhost','127.0.0.1') or u.hostname.lower().endswith('.local'):
        raise ValueError('Private feed host disallowed')
    response=client.get(feed_url);response.raise_for_status()
    if len(response.content)>2_000_000:raise ValueError('Feed too large')
    tree=ET.fromstring(response.content)
    entries=tree.findall('.//item')
    atom=False
    if not entries:
        entries=tree.findall('.//{http://www.w3.org/2005/Atom}entry');atom=True
    out=[]
    for entry in entries[:200]:
        def value(name):
            node=entry.find(name)
            return ''.join(node.itertext()).strip() if node is not None else ''
        if atom:
            title=value('{http://www.w3.org/2005/Atom}title')
            description=value('{http://www.w3.org/2005/Atom}content') or value('{http://www.w3.org/2005/Atom}summary')
            link=next((x.attrib.get('href','') for x in entry.findall('{http://www.w3.org/2005/Atom}link') if x.attrib.get('rel','alternate')=='alternate'),'')
        else:
            title=value('title');description=value('description') or value('{http://purl.org/rss/1.0/modules/content/}encoded')
            link=value('link')
        link=link.strip();p=urllib.parse.urlparse(link)
        if p.scheme!='https' or not p.hostname:continue
        description=clean(description)
        out.append(dict(source='Configured public feed: '+u.hostname,employer=u.hostname,title=clean(title),location=clean(title+' '+description)[:300],url=link,description=description,pay=description))
    return out



def adzuna_jobs(client):
    """Official Adzuna Canada search API. Never log API credentials."""
    app_id=os.getenv('ADZUNA_APP_ID','').strip()
    app_key=os.getenv('ADZUNA_APP_KEY','').strip()
    if not app_id or not app_key:
        return [], ['Adzuna: ADZUNA_APP_ID or ADZUNA_APP_KEY missing']
    jobs=[];errors=[]
    # Wider discovery: old active postings included; no arbitrary seven-day cutoff.
    terms=('crew member','cashier','fast food','restaurant team member','food service',
           'retail associate','sales associate','store associate','grocery clerk',
           'warehouse associate','picker packer','stock associate','customer service',
           'barista','kitchen helper','dishwasher')
    places=('Whitby, Ontario','Oshawa, Ontario','Ajax, Ontario',
            'Pickering, Ontario','Courtice, Ontario','Bowmanville, Ontario')
    # Six municipalities x sixteen categories. Adzuna may rate-limit: stop cleanly
    # and preserve already gathered jobs rather than hiding an API failure.
    seen=set()
    # Two queries per check: reduce API load; 96 searches rotate over 12 hours.
    slot=(int(datetime.datetime.now().timestamp())//900)%48
    queries=[(place,term) for place in places for term in terms]
    for place,term in queries[slot*2:(slot+1)*2]:
        try:
            response=client.get('https://api.adzuna.com/v1/api/jobs/ca/search/1',
                params={'app_id':app_id,'app_key':app_key,'results_per_page':50,
                        'what':term,'where':place,'distance':10,'sort_by':'date'},
                headers={'Accept':'application/json'})
            response.raise_for_status()
            payload=response.json()
            for item in payload.get('results',[]):
                ident=str(item.get('id',''))
                if ident and ident in seen:continue
                seen.add(ident)
                location=item.get('location') or {}
                area=location.get('area') or []
                place_name=location.get('display_name','') or ', '.join(area)
                contract=item.get('contract_time','') or ''
                title=clean(item.get('title',''))
                description=clean(item.get('description',''))
                predicted=bool(item.get('salary_is_predicted',False))
                salary=item.get('salary_min')
                salary_max=item.get('salary_max')
                pay=''
                if not predicted and salary is not None:
                    pay='Adzuna salary figure (period unspecified): '+str(salary)
                    if salary_max is not None:pay+=' to '+str(salary_max)
                url=item.get('redirect_url','')
                if url.startswith('http://'):url='https://'+url[7:]
                if not url.startswith('https://'):continue
                company=item.get('company') or {}
                jobs.append(dict(source='Adzuna Canada',employer=clean(company.get('display_name','Unknown employer')),
                    title=title,location=place_name,url=url,description=description+' '+contract.replace('_','-'),
                    pay=pay,posted=item.get('created',''),external_id=ident))
        except Exception as exc:
            status=getattr(getattr(exc,'response',None),'status_code',None)
            errors.append('Adzuna '+place+' / '+term+': HTTP '+str(status) if status else 'Adzuna '+place+' / '+term+': '+type(exc).__name__)
            if status in (401,403,429,500,502,503,504):return jobs,errors
    return jobs,errors

def fetch_jobs():

    jobs=[]; errors=[]
    feeds=[x.strip() for x in os.getenv('JOB_PUBLIC_FEEDS','').split(',') if x.strip()]
    lever=[x.strip() for x in os.getenv('JOB_LEVER_SITES','').split(',') if re.fullmatch(r'[a-zA-Z0-9_-]{2,80}',x.strip())]
    # Optional explicit public ATS board identifiers. Only official public JSON endpoints.
    boards=[x.strip() for x in os.getenv('JOB_GREENHOUSE_BOARDS','').split(',') if re.fullmatch(r'[a-zA-Z0-9_-]{2,80}',x.strip())]
    with httpx.Client(timeout=16,follow_redirects=True,headers={'User-Agent':'ADRIAN-AI-personal-job-discovery/1.0'}) as client:
        found,issues=adzuna_jobs(client);jobs.extend(found);errors.extend(issues)
        for board in boards:
            try:
                r=client.get(f'https://boards-api.greenhouse.io/v1/boards/{board}/jobs',params={'content':'true'});r.raise_for_status()
                for j in r.json().get('jobs',[]):
                    loc=j.get('location') or {}; loc=loc.get('name','') if isinstance(loc,dict) else str(loc)
                    desc=clean(j.get('content','')); pay=desc
                    jobs.append(dict(source='Greenhouse: '+board,employer=board,title=j.get('title',''),location=loc,url=j.get('absolute_url',''),description=desc,pay=pay))
            except Exception as e:errors.append('Greenhouse '+board+': '+type(e).__name__)
        for site in lever:
            try:
                r=client.get(f'https://api.lever.co/v0/postings/{site}',params={'mode':'json'});r.raise_for_status()
                for j in r.json():
                    cats=j.get('categories') or {}
                    loc=cats.get('location','')
                    desc=clean(j.get('descriptionPlain') or j.get('description') or '')
                    desc+=' '+clean(' '.join(x.get('text','')+' '+clean(x.get('content','')) for x in j.get('lists',[])))
                    jobs.append(dict(source='Lever: '+site,employer=site,title=j.get('text',''),location=loc,url=j.get('hostedUrl',''),description=desc,pay=desc))
            except Exception as e: errors.append('Lever '+site+': '+type(e).__name__)
        for feed in feeds[:12]:
            try:jobs.extend(public_feed_jobs(client,feed))
            except Exception as e:errors.append('Configured feed '+urllib.parse.urlparse(feed).hostname.__str__()+': '+type(e).__name__)
        # Public jobs API; individual listings, filtered strictly for location, hours and wage.
        try:
            for page in (1,2):
                r=client.get('https://www.arbeitnow.com/api/job-board-api',params={'page':page});r.raise_for_status()
                for j in r.json().get('data',[]):
                    jobs.append(dict(source='Arbeitnow',employer=j.get('company_name',''),title=j.get('title',''),location=j.get('location',''),url=j.get('url',''),description=clean(j.get('description','')),pay=clean(j.get('description',''))))
        except Exception as e:errors.append('Arbeitnow: '+type(e).__name__)
    return jobs,errors

def job_fingerprint(j):
    """Stable cross-source vacancy key, ignoring job-board redirect URLs."""
    def norm(x):return re.sub(r'[^a-z0-9]+',' ',clean(x).lower()).strip()
    loc=norm(j.get('location',''))
    city=next((a for a in AREA if re.search(r'\\b'+re.escape(a)+r'\\b',loc)),loc)
    raw='|'.join((norm(j.get('employer','')),norm(j.get('title','')),city))
    return hashlib.sha256(raw.encode('utf-8')).hexdigest()

def discover(db,now):
    jobs,errors=fetch_jobs()
    confirmed=0; review=0; added=0
    with db() as c:
        c.execute("""CREATE TABLE IF NOT EXISTS job_v7_fingerprints (
            fingerprint TEXT PRIMARY KEY, first_url TEXT NOT NULL, first_seen TEXT NOT NULL)""")
        # Backfill existing history before accepting newly discovered jobs.
        for table in ('job_v7_postings','job_v7_review'):
            for old in c.execute('SELECT employer,title,location,url FROM '+table):
                fingerprint=job_fingerprint(dict(old))
                c.execute('INSERT OR IGNORE INTO job_v7_fingerprints VALUES(?,?,?)',
                          (fingerprint,old['url'],now()))
        c.execute("""CREATE TABLE IF NOT EXISTS job_v7_review (
            url TEXT PRIMARY KEY, source TEXT, employer TEXT, title TEXT,
            location TEXT, pay TEXT, reason TEXT, found TEXT, description TEXT NOT NULL DEFAULT '')""")
        columns={r[1] for r in c.execute('PRAGMA table_info(job_v7_review)')}
        if 'description' not in columns:c.execute("ALTER TABLE job_v7_review ADD COLUMN description TEXT NOT NULL DEFAULT ''")
        for j in jobs:
            if not eligible(j) and not review_reason(j):continue
            fingerprint=job_fingerprint(j)
            if c.execute('SELECT 1 FROM job_v7_fingerprints WHERE fingerprint=?',(fingerprint,)).fetchone():
                continue
            if eligible(j):
                confirmed+=1
                before=c.total_changes
                c.execute('INSERT OR IGNORE INTO job_v7_postings(source,employer,title,location,url,description,pay,found) VALUES(?,?,?,?,?,?,?,?)',
                          tuple(j[k] for k in ('source','employer','title','location','url','description','pay'))+(now(),))
                if c.total_changes>before:
                    c.execute('INSERT OR IGNORE INTO job_v7_fingerprints VALUES(?,?,?)',(fingerprint,j['url'],now()))
                    added+=1
            else:
                reason=review_reason(j)
                if reason and j.get('url','').startswith('https://'):
                    review+=1
                    before=c.total_changes
                    c.execute('INSERT OR IGNORE INTO job_v7_review(url,source,employer,title,location,pay,reason,found,description) VALUES(?,?,?,?,?,?,?,?,?)',
                              (j['url'],j['source'],j['employer'],j['title'],j['location'],j['pay'][:150],reason,now(),j.get('description','')[:12000]))
                    if c.total_changes>before:
                        c.execute('INSERT OR IGNORE INTO job_v7_fingerprints VALUES(?,?,?)',(fingerprint,j['url'],now()))
    return {'eligible':confirmed,'new':added,'review_candidates':review,'sources_checked':{'greenhouse':len([x for x in os.getenv('JOB_GREENHOUSE_BOARDS','').split(',') if x.strip()]),'lever':len([x for x in os.getenv('JOB_LEVER_SITES','').split(',') if x.strip()]),'arbeitnow_pages':2,'public_feeds':len([x for x in os.getenv('JOB_PUBLIC_FEEDS','').split(',') if x.strip()]),'adzuna':bool(os.getenv('ADZUNA_APP_ID') and os.getenv('ADZUNA_APP_KEY')),'adzuna_queries_total':96,'adzuna_queries_this_run':2},'errors':errors}
