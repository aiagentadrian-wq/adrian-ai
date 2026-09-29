"""Build and send an explicit owner-only ATS resume test without changing job flags."""
import os,email.message
from job_v7_packages import make_pdf
from job_v7_email import send

def build_test(db):
    with db() as c:
        resume=c.execute('SELECT content FROM job_v7_resume ORDER BY id DESC LIMIT 1').fetchone()
        job=c.execute('SELECT employer,title,location,url,description FROM job_v7_postings ORDER BY id DESC LIMIT 1').fetchone()
    if not resume or not resume['content'].strip():raise ValueError('Upload your resume to the vault first.')
    if not job:raise ValueError('Save a real job posting first so the test can use its employer and title.')
    job=dict(job);pdf,_=make_pdf(resume['content'],job)
    msg=email.message.EmailMessage()
    msg['From']=os.getenv('EMAIL_FROM');msg['To']=os.getenv('REPORT_TO')
    msg['Subject']='[TEST] ADRIAN.AI - ATS resume'
    msg.set_content('Your single-column ATS resume test is attached.\n\nRole: '+job['title']+'\nEmployer: '+job['employer']+'\nSaved posting: '+job['url']+'\n\nThis uses a saved posting; its current availability has not been checked. Review the source facts and resume before applying. No application was submitted; job email flags were not changed.')
    msg.add_attachment(pdf,maintype='application',subtype='pdf',filename='Adrian_ATS_resume_test.pdf')
    return msg

def send_test(db):
    message=build_test(db)
    status=send(message)
    return {'ok':True,'status':status,'note':'Email accepted by SMTP. Check your inbox to confirm delivery.'}
