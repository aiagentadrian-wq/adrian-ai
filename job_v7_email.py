"""Readable, accessible HTML/plain text email with up to five individually tailored PDFs."""
import os,ssl,smtplib,email.message,html,re
from urllib.parse import urlparse
from job_v7_packages import make_pdf

def valid_link(url):
    p=urlparse(url or '')
    return url if p.scheme=='https' and p.hostname else ''

def build(jobs,resume,checked,errors=(),subject='ADRIAN.AI — 5 job opportunities'):
    jobs=jobs[:5]
    msg=email.message.EmailMessage()
    msg['From']=os.getenv('EMAIL_FROM');msg['To']=os.getenv('REPORT_TO');msg['Subject']=subject
    plain=['ADRIAN.AI — JOB OPPORTUNITIES','Checked: '+checked,
           'Each listing needs verification before applying. No applications submitted.','']
    cards=[];attachments=[]
    if not jobs:
        plain.extend(['No new matching, unemailed opportunities were found. Previously emailed listings have not been repeated.','If source checks failed, this is an incomplete search, not proof that no suitable jobs exist.',''])
        cards.append('<p>No new matching, unemailed opportunities were found. Previously emailed listings have not been repeated. Failed source checks mean the search is incomplete.</p>')
    for i,j in enumerate(jobs,1):
        label='Confirmed automated filter match' if j.get('confirmed') else 'NEEDS VERIFICATION — '+(j.get('reason') or 'Pay/hours not confirmed')
        url=valid_link(j.get('url'))
        if not url:continue
        employer=j.get('employer') or 'Employer not supplied'
        title=j.get('title') or 'Job title not supplied'
        loc=j.get('location') or 'Location not supplied'
        pay=j.get('pay') or 'Not confirmed'
        note='Resume not attached: upload your resume to the vault.' if not resume else ''
        if resume:
            try:
                pdf,_=make_pdf(resume,j)
                if not pdf.startswith(b'%PDF'):raise ValueError('Not a PDF')
                name=f'Adrian_job_{i:02d}_resume.pdf'
                attachments.append((name,pdf))
                note='Resume attached: '+name+'. Review it before applying.'
                if not j.get('description','').strip():
                    note+=' Full job description was not saved; this draft uses the role and employer only.'
            except Exception as exc:
                note='Resume generation failed ('+type(exc).__name__+'); listing included without an attachment.'
        plain.extend([f'{i}. {employer} — {title}',loc,'Status: '+label,'Pay: '+pay,
                      'Application link: '+url,note,''])
        esc=lambda s:html.escape(str(s),quote=True)
        cards.append('<div style="border:1px solid #dce5eb;border-radius:12px;padding:18px;margin:0 0 16px;background:#fff">'
          f'<div style="color:#64748b;font-size:12px;font-weight:700">JOB {i} · {esc(label)}</div>'
          f'<h2 style="margin:8px 0 4px;font-size:19px;color:#152b3b">{esc(title)}</h2>'
          f'<p style="margin:0 0 12px;font-weight:bold">{esc(employer)}</p>'
          f'<p style="margin:4px 0">📍 {esc(loc)}</p><p style="margin:4px 0">Pay: {esc(pay)}</p>'
          f'<p style="font-size:13px;color:#475569">{esc(note)}</p>'
          f'<a href="{esc(url)}" style="display:inline-block;padding:11px 18px;background:#0b6872;color:#fff;text-decoration:none;border-radius:7px;font-weight:bold">View job &amp; apply</a>'
          '</div>')
    if errors:
        plain.append('SOURCE STATUS: '+str(len(errors))+' source request(s) failed; results may be incomplete.')
    plain.append('Open each posting to verify it is still active, the hourly wage and part-time hours. No employer application was submitted.')
    msg.set_content('\n'.join(plain))
    htmlbody=('<html><body style="margin:0;padding:22px;background:#f3f7f9;font-family:Arial,sans-serif;color:#152b3b">'
       '<div style="max-width:660px;margin:auto"><h1 style="margin-bottom:4px">ADRIAN.AI · Job opportunities</h1>'
       f'<p style="color:#526775">Checked: {html.escape(checked)} · {len(cards)} listings · {len(attachments)} resume PDFs</p>'
       '<p style="background:#eaf4f4;padding:12px;border-radius:8px">Review each posting and tailored resume before applying. Unverified pay or hours are labelled clearly.</p>'
       +''.join(cards)+'<p style="font-size:12px;color:#526775">No applications were submitted. Some source checks may be temporarily unavailable.</p></div></body></html>')
    msg.add_alternative(htmlbody,subtype='html')
    for name,pdf in attachments:msg.add_attachment(pdf,maintype='application',subtype='pdf',filename=name)
    return msg,'\n'.join(plain),len(attachments)

def send(msg):
    host=os.getenv('SMTP_HOST');user=os.getenv('SMTP_USER');pwd=os.getenv('SMTP_PASSWORD')
    if not all((host,user,pwd,msg['From'],msg['To'])):raise RuntimeError('SMTP configuration incomplete')
    with smtplib.SMTP(host,int(os.getenv('SMTP_PORT','587')),timeout=30) as smtp:
        smtp.starttls(context=ssl.create_default_context());smtp.login(user,pwd)
        refused=smtp.send_message(msg)
        if refused:raise RuntimeError('SMTP refused recipient')
    return 'accepted_by_smtp'
