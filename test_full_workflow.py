"""One-shot REAL-source end-to-end test. No DB writes, no dedupe changes."""
import os,sys,ssl,smtplib,email.message,traceback
from pathlib import Path
ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(Path.cwd()))
def main():
    import app,job_v7_discovery as discovery
    from job_v7_packages import make_pdf
    # Source is queried afresh; do not select a manufactured or manually imported listing.
    jobs,errors=discovery.fetch_jobs()
    real=[j for j in jobs if j.get('source')=='Adzuna Canada'
          and j.get('url','').startswith('https://')
          and (discovery.eligible(j) or discovery.review_reason(j))]
    if not real:
        with app.db() as c:
            stored=c.execute("SELECT employer,title,location,url,pay,description,source FROM job_v7_postings WHERE source='Adzuna Canada' ORDER BY id DESC LIMIT 1").fetchone()
            if not stored:
                stored=c.execute("SELECT employer,title,location,url,pay,source FROM job_v7_review WHERE source='Adzuna Canada' ORDER BY found DESC LIMIT 1").fetchone()
        if stored:
            j=dict(stored);j.setdefault('description','')
            real=[j]
            print('TEST NOTE: using a previously discovered REAL Adzuna listing from your database; no new match required.')
        else:
            print('NO TEST EMAIL: No real relevant Adzuna posting currently available.')
            print('Source errors:',errors)
            return 2
    # Prefer confirmed, otherwise clearly identify a review candidate.
    real.sort(key=lambda j:(not discovery.eligible(j),j.get('posted','')))
    j=real[0];confirmed=discovery.eligible(j)
    with app.db() as c:
        resume=c.execute('SELECT content FROM job_v7_resume ORDER BY id DESC LIMIT 1').fetchone()
    if not resume or not resume['content'].strip():
        print('NO TEST EMAIL: resume vault is empty.');return 2
    pdf,count=make_pdf(resume['content'],j)
    if not pdf.startswith(b'%PDF') or len(pdf)<1000:raise ValueError('PDF generation failed')
    host=os.getenv('SMTP_HOST');user=os.getenv('SMTP_USER');pwd=os.getenv('SMTP_PASSWORD')
    sender=os.getenv('EMAIL_FROM');recipient=os.getenv('REPORT_TO')
    if not all((host,user,pwd,sender,recipient)):raise ValueError('SMTP settings incomplete')
    label='CONFIRMED FILTER MATCH' if confirmed else 'REVIEW ONLY — pay/hours not verified'
    body='\n'.join(['ADRIAN.AI — END-TO-END TEST — NO APPLICATION SUBMITTED',
        'This is a real Adzuna listing from live discovery or existing saved discovery, not a fabricated test job.',
        'Status: '+label,'Employer: '+j['employer'],'Job: '+j['title'],
        'Location: '+j['location'],'Pay: '+(j.get('pay') or 'Not confirmed'),
        'Hours/pay caveat: '+(discovery.review_reason(j) or 'Meets automated filter; verify with employer'),
        'Source: '+j['source'],'Apply / listing: '+j['url'],
        'Posting description available to resume generator: '+str(len(j.get('description','')))+' characters.',
        'Attached: resume tailored to this employer and title using the saved original resume.',
        'Review all details and PDF before applying. This test does not change emailed flags or job database.',
        'Source errors: '+('; '.join(errors) if errors else 'none')])
    msg=email.message.EmailMessage();msg['From']=sender;msg['To']=recipient
    msg['Subject']='[TEST] ADRIAN.AI — Real job + tailored resume'
    msg.set_content(body)
    msg.add_attachment(pdf,maintype='application',subtype='pdf',filename='Adrian_TEST_tailored_resume.pdf')
    with smtplib.SMTP(host,int(os.getenv('SMTP_PORT','587')),timeout=30) as smtp:
        smtp.starttls(context=ssl.create_default_context());smtp.login(user,pwd)
        refused=smtp.send_message(msg)
        if refused:raise RuntimeError('Recipient refused by SMTP')
    print('PASS: real Adzuna listing fetched; tailored PDF generated; email accepted by SMTP.')
    print('Status:',label,'| Employer:',j['employer'],'| Job:',j['title'])
    print('PDF bytes:',len(pdf),'| PDF filename: Adrian_TEST_tailored_resume.pdf')
    print('No DB writes, no duplicate flags changed, no employer application submitted.')
    print('Inbox delivery must be checked manually.')
    return 0
if __name__=='__main__':
    try:sys.exit(main())
    except Exception as exc:
        # Never dump request URLs containing API keys or SMTP secrets.
        print('TEST FAILED:',type(exc).__name__,str(exc) if isinstance(exc,(ValueError,RuntimeError)) else 'See local configuration; no email success claimed.')
        sys.exit(1)
