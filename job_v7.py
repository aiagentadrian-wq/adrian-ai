"""ADRIAN.AI V7: private resume vault, reviewed applications and deduplicated briefings."""
import base64, hashlib, io, json, os, re, sqlite3, ssl, smtplib, email.message, zipfile
from pathlib import Path
from datetime import datetime, timezone
from urllib.parse import urlparse
from xml.etree import ElementTree as ET
import httpx
from fastapi import HTTPException, Request
from pydantic import BaseModel, Field


def install(app, root, db, auth, csrf, now, record_action, event, model_call, cipher):
    folder=root/'job_v7_private'; folder.mkdir(exist_ok=True)
    with db() as c:
        c.executescript('''CREATE TABLE IF NOT EXISTS job_v7_resume(id INTEGER PRIMARY KEY, filename TEXT NOT NULL, content TEXT NOT NULL, created TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS job_v7_postings(id INTEGER PRIMARY KEY, source TEXT NOT NULL, employer TEXT NOT NULL, title TEXT NOT NULL, location TEXT NOT NULL, url TEXT NOT NULL UNIQUE, description TEXT NOT NULL, pay TEXT, found TEXT NOT NULL, score INTEGER, reasoning TEXT, draft TEXT, approved INTEGER NOT NULL DEFAULT 0, emailed INTEGER NOT NULL DEFAULT 0);
        CREATE TABLE IF NOT EXISTS job_v7_likes(posting_id INTEGER PRIMARY KEY, liked_at TEXT NOT NULL);\n        CREATE TABLE IF NOT EXISTS job_v7_runs(id INTEGER PRIMARY KEY, at TEXT NOT NULL, mode TEXT NOT NULL, found INTEGER NOT NULL, emailed INTEGER NOT NULL, status TEXT NOT NULL);''')
    class ResumeIn(BaseModel):
        filename:str=Field(min_length=5,max_length=150)
        data:str=Field(min_length=20,max_length=4000000)
    class JobIn(BaseModel):
        url:str=Field(min_length=12,max_length=1500)
        description:str=Field(min_length=40,max_length=20000)
        employer:str=Field(min_length=2,max_length=150)
        title:str=Field(min_length=2,max_length=150)
        location:str=Field(min_length=2,max_length=150)
        pay:str=''
    def resume_text(name, raw):
        if len(raw)>2200000: raise HTTPException(413,'Resume too large (2 MB max)')
        if name.lower().endswith('.pdf'):
            if not raw.startswith(b'%PDF'):raise HTTPException(400,'Invalid PDF')
            try:
                from pypdf import PdfReader
                text='\n'.join(p.extract_text() or '' for p in PdfReader(io.BytesIO(raw)).pages[:6])
            except ImportError:raise HTTPException(503,'Install pypdf in your virtual environment')
        elif name.lower().endswith('.docx'):
            try:
                with zipfile.ZipFile(io.BytesIO(raw)) as z:
                    xml=z.read('word/document.xml')
                tree=ET.fromstring(xml)
                text='\n'.join(''.join(n.itertext()) for n in tree.iter() if n.tag.endswith('}p'))
            except Exception:raise HTTPException(400,'Invalid DOCX')
        else:raise HTTPException(400,'PDF or DOCX only')
        text=re.sub(r'\n{3,}','\n\n',text).strip()
        if len(text)<100:raise HTTPException(400,'Could not extract enough text; use a text-based PDF or DOCX')
        return text[:18000]
    def resume():
        with db() as c:r=c.execute('SELECT * FROM job_v7_resume ORDER BY id DESC LIMIT 1').fetchone()
        return dict(r) if r else None
    @app.post('/api/jobs/v7/resume')
    def upload(body:ResumeIn,req:Request):
        csrf(req)
        try:raw=base64.b64decode(body.data,validate=True)
        except Exception:raise HTTPException(400,'Invalid file data')
        text=resume_text(body.filename,raw)
        with db() as c:c.execute('INSERT INTO job_v7_resume(filename,content,created) VALUES(?,?,?)',(Path(body.filename).name,text,now()))
        return {'ok':True,'filename':Path(body.filename).name,'characters':len(text),'note':'Stored as extracted text in the local database; original file stays on your computer.'}
    @app.get('/api/jobs/v7/resume')
    def resume_status(req:Request):
        auth(req); r=resume();return {'found':bool(r),'filename':r['filename'] if r else None,'created':r['created'] if r else None}
    def valid_url(url):
        p=urlparse(url)
        if p.scheme!='https' or not p.hostname or p.username or p.password or len(url)>1500:raise HTTPException(400,'Use a valid public HTTPS job posting URL')
        if p.hostname in {'localhost','127.0.0.1'} or p.hostname.endswith('.local'):raise HTTPException(400,'Private URL not allowed')
        return url
    @app.post('/api/jobs/v7/import')
    def import_job(body:JobIn,req:Request):
        csrf(req);valid_url(body.url)
        with db() as c:
            c.execute('INSERT INTO job_v7_postings(source,employer,title,location,url,description,pay,found) VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(url) DO UPDATE SET description=excluded.description,pay=excluded.pay',(urlparse(body.url).hostname,body.employer,body.title,body.location,body.url,body.description,body.pay[:100],now()))
        return {'ok':True,'note':'User-imported posting; confirm it is still open on the employer site.'}
    @app.get('/api/jobs/v7/postings')
    def postings(req:Request):
        auth(req)
        with db() as c:return {'items':[dict(r) for r in c.execute('SELECT p.id,p.source,p.employer,p.title,p.location,p.url,p.pay,p.found,p.score,p.reasoning,p.approved,p.emailed,CASE WHEN l.posting_id IS NULL THEN 0 ELSE 1 END AS liked FROM job_v7_postings p LEFT JOIN job_v7_likes l ON l.posting_id=p.id ORDER BY p.id DESC LIMIT 100')]}
    @app.put('/api/jobs/v7/postings/{jid}/liked')
    def set_liked(jid:int,body:dict,req:Request):
        csrf(req)
        if type(body.get('liked')) is not bool:raise HTTPException(400,'liked must be true or false')
        with db() as c:
            if not c.execute('SELECT 1 FROM job_v7_postings WHERE id=?',(jid,)).fetchone():raise HTTPException(404,'Posting not found')
            if body['liked']:c.execute('INSERT OR REPLACE INTO job_v7_likes(posting_id,liked_at) VALUES(?,?)',(jid,now()))
            else:c.execute('DELETE FROM job_v7_likes WHERE posting_id=?',(jid,))
        return {'ok':True,'liked':body['liked']}
    async def generate(provider, instructions, prompt):
        response=await model_call(provider,[{'role':'system','content':instructions},{'role':'user','content':prompt}])
        return (response['choices'][0]['message'].get('content') or '').strip()
    @app.post('/api/jobs/v7/postings/{jid}/tailor')
    async def tailor(jid:int,req:Request):
        csrf(req);r=resume()
        if not r:raise HTTPException(400,'Upload a resume first')
        with db() as c:
            j=c.execute('SELECT * FROM job_v7_postings WHERE id=?',(jid,)).fetchone()
            provider=c.execute('SELECT * FROM providers ORDER BY id LIMIT 1').fetchone()
        if not j:raise HTTPException(404,'Posting not found')
        if not provider:raise HTTPException(400,'Connect an AI provider first')
        instructions=('Create an ATS-readable single-column plain-text resume, tailored to the supplied job description. Use ONLY facts supported by the original resume. Never invent employers, dates, qualifications, credentials, skills, metrics, languages, availability, education or achievements. Previous tailored summaries are not proof of employment. Match the job requirements by reordering and rewriting supported skills and experience, not by inserting unsupported keywords. Standard headings: NAME AND CONTACT, PROFESSIONAL SUMMARY, SKILLS, EXPERIENCE or RELEVANT EXPERIENCE, EDUCATION, and ADDITIONAL INFORMATION only if supported. Preserve employer names, job titles and dates as given. No tables, columns, graphics, icons, rating bars, text boxes or decorative characters. Use concise factual bullets. Omit unknown details. No guarantee of passing automated screening. Output the resume only.')
        draft=await generate(provider,instructions,'ORIGINAL RESUME:\n'+r['content']+'\n\nTARGET POSTING:\n'+j['employer']+' | '+j['title']+' | '+j['location']+'\n'+j['description']+'\n\nIdentify the actual job requirements and reflect substantiated matches in the summary, skills and experience wording. Keep a simple single-column ATS-readable structure. Do not invent missing qualifications. No preface.')
        if not draft:raise HTTPException(502,'AI returned an empty draft')
        # Explainable fit score is a heuristic, not a hiring prediction.
        source=(r['content']+' '+j['description']).lower();desc=j['description'].lower();matches=[w for w in ('food','kitchen','customer','service','team','clean','retail','warehouse','stock','cash','cook','prep','safety','organize') if w in r['content'].lower() and w in desc]
        score=min(85,35+len(matches)*6)
        reasoning='Shared resume/posting terms: '+(', '.join(matches) if matches else 'none found')+'. Heuristic only; schedule, pay, eligibility and employer requirements need manual confirmation.'
        with db() as c:c.execute('UPDATE job_v7_postings SET score=?,reasoning=?,draft=?,approved=0 WHERE id=?',(score,reasoning,draft[:22000],jid))
        return {'ok':True,'score':score,'reasoning':reasoning,'draft':draft,'warning':'Review every claim against your original resume before approving.'}
    @app.get('/api/jobs/v7/postings/{jid}/draft')
    def draft(jid:int,req:Request):
        auth(req)
        with db() as c:r=c.execute('SELECT id,employer,title,draft,score,reasoning,approved FROM job_v7_postings WHERE id=?',(jid,)).fetchone()
        if not r:raise HTTPException(404,'Posting not found')
        return dict(r)
    @app.post('/api/jobs/v7/postings/{jid}/approve')
    def approve(jid:int,req:Request):
        csrf(req)
        with db() as c:
            r=c.execute('SELECT draft FROM job_v7_postings WHERE id=?',(jid,)).fetchone()
            if not r or not r['draft']:raise HTTPException(400,'Generate and review the draft first')
            c.execute('UPDATE job_v7_postings SET approved=1 WHERE id=?',(jid,))
        return {'ok':True}
    def pdf_bytes(title,content):
        try:
            from reportlab.platypus import SimpleDocTemplate,Paragraph,Spacer
            from reportlab.lib.styles import getSampleStyleSheet
            from reportlab.lib.utils import simpleSplit
            from xml.sax.saxutils import escape
        except ImportError:raise HTTPException(503,'Install reportlab in your virtual environment')
        out=io.BytesIO();doc=SimpleDocTemplate(out,pagesize=(612,792),leftMargin=48,rightMargin=48,topMargin=42,bottomMargin=42)
        styles=getSampleStyleSheet();story=[Paragraph(escape(title),styles['Heading1']),Spacer(1,12)]
        for line in content.splitlines():
            story.append(Paragraph(escape(line) or '&nbsp;',styles['Normal']));story.append(Spacer(1,5))
        doc.build(story);return out.getvalue()
    @app.get('/api/jobs/v7/postings/{jid}/pdf')
    def get_pdf(jid:int,req:Request):
        auth(req)
        with db() as c:r=c.execute('SELECT title,draft FROM job_v7_postings WHERE id=?',(jid,)).fetchone()
        if not r or not r['draft']:raise HTTPException(404,'No draft generated')
        from fastapi.responses import Response
        return Response(pdf_bytes('Tailored resume — '+r['title'],r['draft']),media_type='application/pdf',headers={'Content-Disposition':f'attachment; filename="tailored_resume_{jid}.pdf"'})
    def send_mail(subject,body,attachments=()):
        host=os.getenv('SMTP_HOST');user=os.getenv('SMTP_USER');pwd=os.getenv('SMTP_PASSWORD');sender=os.getenv('EMAIL_FROM');to=os.getenv('REPORT_TO')
        if not all((host,user,pwd,sender,to)):raise HTTPException(400,'SMTP not configured')
        msg=email.message.EmailMessage();msg['From']=sender;msg['To']=to;msg['Subject']=subject;msg.set_content(body)
        for name,raw in attachments:msg.add_attachment(raw,maintype='application',subtype='pdf',filename=name)
        try:
            with smtplib.SMTP(host,int(os.getenv('SMTP_PORT','587')),timeout=25) as smtp:
                smtp.starttls(context=ssl.create_default_context());smtp.login(user,pwd)
                refused=smtp.send_message(msg)
                if refused:raise ValueError('Recipient refused')
        except Exception:raise HTTPException(502,'SMTP failed; nothing marked emailed')
        with db() as c:c.execute('INSERT INTO email_history(at,subject,body,recipient,sender,status,error) VALUES(?,?,?,?,?,?,?)',(now(),subject,body,to,sender,'accepted_by_smtp',None))
        return {'ok':True,'status':'accepted_by_smtp','note':'Inbox delivery not independently verified'}
    @app.post('/api/jobs/v7/email-approved')
    def email_approved(req:Request):
        csrf(req)
        with db() as c:items=[dict(x) for x in c.execute('SELECT * FROM job_v7_postings WHERE approved=1 AND emailed=0 ORDER BY id LIMIT 12')]
        if not items:raise HTTPException(400,'No newly approved resumes to send')
        report='ADRIAN.AI — MANAGER APPLICATION REPORT\nGenerated: '+now()+'\n\n'
        attachments=[]
        for j in items:
            report+=f"{j['employer']} — {j['title']}\nLocation: {j['location']}\nPay: {j['pay'] or 'Not confirmed'}\nFit: {j['score']}/100 (heuristic)\nReason: {j['reasoning']}\nApply: {j['url']}\n\n"
            attachments.append((f"Adrian_tailored_resume_{j['id']}.pdf",pdf_bytes(j['title'],j['draft'])))
        result=send_mail('ADRIAN.AI — Approved application package',report,attachments)
        with db() as c:c.executemany('UPDATE job_v7_postings SET emailed=1 WHERE id=?',[(j['id'],) for j in items])
        event('Manager','application package accepted by SMTP',str(len(items))+' approved resumes')
        return dict(result,count=len(items))
    @app.get('/api/jobs/v7/report')
    def report(req:Request):
        auth(req)
        with db() as c:items=[dict(x) for x in c.execute('SELECT employer,title,location,url,pay,score,reasoning,approved,emailed FROM job_v7_postings ORDER BY id DESC LIMIT 50')]
        return {'created':now(),'items':items,'note':'Manager-readable local report; no employer applications submitted.'}
    @app.post('/api/jobs/v7/briefing')
    def briefing(req:Request):
        csrf(req)
        with db() as c:items=[dict(x) for x in c.execute('SELECT * FROM job_v7_postings WHERE emailed=0 ORDER BY id LIMIT 50')]
        lines=['ADRIAN.AI — NEW JOB BRIEFING','Checked: '+now(),'Imported/reviewed postings not previously emailed: '+str(len(items)),'']
        for j in items:lines.extend([j['employer']+' — '+j['title'],j['location']+' | '+(j['pay'] or 'Pay not confirmed'),j['url'],''])
        if not items:lines.append('No new reviewed postings. No previous listings repeated.')
        result=send_mail('ADRIAN.AI — Job briefing', '\n'.join(lines))
        with db() as c:
            c.executemany('UPDATE job_v7_postings SET emailed=1 WHERE id=?',[(j['id'],) for j in items])
            c.execute('INSERT INTO job_v7_runs(at,mode,found,emailed,status) VALUES(?,?,?,?,?)',(now(),'briefing',len(items),len(items),'accepted_by_smtp'))
        return dict(result,count=len(items))
    # Invoked only by the local Windows scheduled runner; independent of the browser.
    def scheduled_briefing():
        from job_v7_discovery import discover
        discovery=discover(db,now)
        with db() as c:items=[dict(x) for x in c.execute('SELECT * FROM job_v7_postings WHERE emailed=0 ORDER BY id LIMIT 50')]
        lines=['ADRIAN.AI — AUTOMATIC JOB HUNT','Checked: '+now(),
               'New eligible postings discovered: '+str(discovery['new']),
               'Unsent matching postings: '+str(len(items)),
               'Sources: public permitted job feeds; no Indeed/Job Bank scraping.',
               'Requirements: Durham Region, part-time, listed hourly pay >= CAD $17.00.','Listings require your verification before applying. Resume drafts are reviewed separately.','']
        for j in items:lines.extend([j['employer']+' — '+j['title'],j['location']+' | '+(j['pay'][:150] if j['pay'] else 'Pay not confirmed'),j['url'],''])
        if not items:lines.append('No new confirmed matches found. Previously emailed jobs are not repeated.')
        lines.extend(['', 'Relevant postings requiring verification: '+str(discovery.get('review_candidates',0)),
                      'These are not confirmed $17+/hour part-time matches and are NOT included as eligible jobs.'])
        with db() as c:
            cols={r[1] for r in c.execute('PRAGMA table_info(job_v7_review)')}
            if 'emailed' not in cols: c.execute('ALTER TABLE job_v7_review ADD COLUMN emailed INTEGER NOT NULL DEFAULT 0')
            review_items=[dict(x) for x in c.execute('SELECT * FROM job_v7_review WHERE emailed=0 ORDER BY found DESC LIMIT 15')]
        for j in review_items:
            lines.extend([j['employer']+' — '+j['title'],j['location']+' | '+j['reason'],j['url'],''])
        lines.extend(['', 'Official Durham Region careers (search portal; NOT an individual job listing):',
                      'https://www.durham.ca/regional-government/careers-and-volunteering/job-postings/',
                      'The official portal offers saved-search daily alerts. Those alerts are separate from ADRIAN.AI.'])
        lines.append('Sources configured: '+str(discovery.get('sources_checked',{})))
        if not os.getenv('JOB_GREENHOUSE_BOARDS') and not os.getenv('JOB_LEVER_SITES') and not os.getenv('JOB_PUBLIC_FEEDS'):
            lines.append('SOURCE COVERAGE WARNING: No employer boards or public feeds configured. Arbeitnow alone is not a comprehensive Canadian feed.')
        if discovery['errors']:lines.extend(['','Source checks with errors:']+discovery['errors'])
        # Automatic, extractive resume PDFs: original facts preserved; never auto-apply.
        from job_v7_packages import make_pdf
        attachments=[]
        with db() as c: saved=c.execute('SELECT content FROM job_v7_resume ORDER BY id DESC LIMIT 1').fetchone()
        if saved and saved['content'].strip():
            for j in items[:8]:
                try:
                    raw,count=make_pdf(saved['content'],j)
                    attachments.append((f"Adrian_resume_job_{j['id']}.pdf",raw))
                except Exception as exc:
                    lines.append(f"Resume for job {j['id']} failed: {type(exc).__name__}. Job link remains above.")
            lines.append(f"Resume drafts attached: {len(attachments)}. Review each before applying.")
        else:
            lines.append('Resume attachments unavailable: upload your resume to the V7 Resume Vault.')
        result=send_mail('ADRIAN.AI — Automatic job hunt','\\n'.join(lines),attachments)
        with db() as c:
            c.executemany('UPDATE job_v7_postings SET emailed=1 WHERE id=?',[(j['id'],) for j in items])
            c.executemany('UPDATE job_v7_review SET emailed=1 WHERE url=?',[(j['url'],) for j in review_items])
            c.execute('INSERT INTO job_v7_runs(at,mode,found,emailed,status) VALUES(?,?,?,?,?)',(now(),'automatic_discovery',discovery['new'],len(items),'accepted_by_smtp'))
        return dict(result,discovery=discovery,count=len(items))
    globals()['scheduled_briefing']=scheduled_briefing
