"""Faithful recreation of Adrian's original Chipotle resume layout; job-specific wording."""
import io,re
from xml.sax.saxutils import escape
from reportlab.pdfgen import canvas
from reportlab.lib.colors import HexColor
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import Paragraph
from reportlab.lib.enums import TA_LEFT
W,H=595.92,842.88
INK=HexColor('#202020'); LIGHT=HexColor('#f8f9fa'); LINE=HexColor('#d3d3d3')
def clean(s):return re.sub(r'\s+',' ',s).strip()
def parse(resume):
    lines=[x.strip() for x in resume.splitlines() if x.strip()]
    if not lines or 'EXPERIENCE' not in lines:raise ValueError('Original resume with EXPERIENCE section required')
    name=lines[0]
    contact=next((x for x in lines if '@' in x),'')
    a=lines.index('EDUCATION')+1
    ed=lines[a:next((i for i in range(a,len(lines)) if lines[i].startswith('★')),len(lines))]
    exp=lines[lines.index('EXPERIENCE')+1:]
    roles=('Cook','Food Prep & Catering','Kitchen Volunteer','Food Service Volunteer')
    jobs=[];current=None
    for x in exp:
        if any(x.startswith(role+' |') for role in roles):
            if current:jobs.append(current)
            current={'heading':x,'details':[]}
        elif current:current['details'].append(x)
    if current:jobs.append(current)
    if not jobs:raise ValueError('Could not parse original work history')
    for j in jobs:
        role,rest=j['heading'].split(' |',1)
        m=re.search(r'(?:(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+)?\d{4}\s*[–-]\s*(?:Present|\d{4}|(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{4})$',rest)
        j['role']=role;j['employer']=rest[:m.start()].strip() if m else rest.strip()
        j['date']=rest[m.start():].strip() if m else ''
        j['bullets']=[];buffer=''
        for line in j['details']:
            buffer=clean(buffer+' '+line)
            if line.endswith(('.','!','?')):
                j['bullets'].append(buffer);buffer=''
        if buffer:j['bullets'].append(buffer)
    return name,contact,ed,jobs
def make_original_pdf(resume,job):
    name,contact,education,jobs=parse(resume)
    title=clean(job.get('title',''))[:75];employer=clean(job.get('employer',''))[:75]
    if not title or not employer:raise ValueError('Employer and job title required')
    description=(job.get('description') or '').lower()
    # All claims below are anchored in the uploaded resume's actual work history.
    if any(w in (title+' '+description).lower() for w in ('warehouse','stock','inventory','package')):
        profile='Dependable team member with experience preparing and packaging orders, working efficiently under tight timelines, maintaining organized work areas, and collaborating in busy environments. Interested in the '+title+' position at '+employer+'.'
        skills=['Order Preparation & Packaging','Fast-Paced Operations','Teamwork & Organization','Clean & Organized Work Areas','Customer Service']
    elif any(w in (title+' '+description).lower() for w in ('retail','cashier','sales','customer','store')):
        profile='Friendly, dependable worker with experience serving customers, fulfilling orders accurately, and collaborating with teams in fast-paced environments. Interested in the '+title+' position at '+employer+'.'
        skills=['Customer Hospitality','Accurate Order Fulfillment','Teamwork & Organization','Fast-Paced Service','Clean & Organized Work Areas']
    else:
        profile='Friendly, dependable food service worker with experience in meal preparation, catering, customer service, and fast-paced kitchen operations. Interested in the '+title+' position at '+employer+'.'
        skills=['Food Preparation & Assembly','Fast-Paced Kitchen Operations','Customer Hospitality','Hygiene & Sanitation','Teamwork & Organization']
    if 'Bilingual (English/French)' in resume:skills.append('Bilingual (English/French)')
    b=io.BytesIO();c=canvas.Canvas(b,pagesize=(W,H))
    def rect(x,top,w,h,fill,r=0):
        c.setFillColor(fill)
        if r:c.roundRect(x,H-top-h,w,h,r,fill=1,stroke=0)
        else:c.rect(x,H-top-h,w,h,fill=1,stroke=0)
    def line(x1,top1,x2,top2,color=LINE,width=.8):
        c.setStrokeColor(color);c.setLineWidth(width);c.line(x1,H-top1,x2,H-top2)
    def t(x,top,text,size=8,font='Helvetica',color=INK):
        c.setFillColor(color);c.setFont(font,size);c.drawString(x,H-top-size,text)
    def para(x,top,w,text,size=8.3,leading=12,font='Helvetica',color=INK):
        style=ParagraphStyle('p',fontName=font,fontSize=size,leading=leading,textColor=color)
        p=Paragraph(escape(text),style);_,h=p.wrap(w,1000);p.drawOn(c,x,H-top-h);return h
    def section(x,top,w,label):
        t(x,top,label,12,'Helvetica-Bold');line(x,top+22,x+w,top+22)
    def header(page=1):
        rect(45,45,506,111,HexColor('#202020'),9)
        c.setFillColor(HexColor('#ffffff'));c.setFont('Helvetica-Bold',25)
        c.drawCentredString(W/2,H-88,name)
        c.setFont('Helvetica-Bold',9.5)
        subtitle=(title.upper()+' CANDIDATE')
        while c.stringWidth(subtitle,'Helvetica-Bold',9.5)>475:subtitle=subtitle[:-2]
        c.drawCentredString(W/2,H-108,subtitle)
        c.setFont('Helvetica',8.3);c.drawCentredString(W/2,H-130,contact)
    header()
    # Original page geometry: rounded light-grey sidebar; right profile and experience.
    rect(45,169,161,618,HexColor('#fafbfc'),9)
    c.setStrokeColor(LINE);c.roundRect(45,H-169-618,161,618,9,fill=0,stroke=1)
    section(60,185,130,'CORE SKILLS')
    y=213
    for skill in skills:
        p=Paragraph(escape(skill),ParagraphStyle('skill',fontName='Helvetica-Bold',fontSize=8.1,leading=10))
        _,h=p.wrap(113,200);height=max(24,h+10)
        rect(60,y,130,height,HexColor('#ffffff'),4)
        c.setStrokeColor(LINE);c.roundRect(60,H-y-height,130,height,4,fill=0,stroke=1)
        rect(60,y,2.5,height,INK)
        p.drawOn(c,69,H-y-5-h)
        y+=height+7
    y+=4;section(60,y,130,'EDUCATION');y+=29
    # Preserve exact original educational facts, not guessed upgrades.
    edtext=education
    for heading in ('TVO ILC (Asynchronous)','Durham Christian High'):
        try:i=edtext.index(heading)
        except ValueError:continue
        stop=next((k for k in range(i+1,len(edtext)) if edtext[k] in ('TVO ILC (Asynchronous)','Durham Christian High')),len(edtext))
        t(60,y,heading,8.4,'Helvetica-Bold');y+=13
        for detail in edtext[i+1:stop]:
            y+=para(60,y,129,detail,8,10)+1
        y+=8
    rect(60,739,130,42,HexColor('#f2f3f4'),6)
    c.setStrokeColor(LINE);c.roundRect(60,H-739-42,130,42,6,stroke=1,fill=0)
    t(71,750,'References available',8,'Helvetica-Bold');t(88,763,'upon request',8,'Helvetica-Bold')
    section(221,179,330,'PROFILE')
    ph=para(221,208,328,profile,9.1,14)
    y=max(296,208+ph+16)
    section(221,y,330,'EXPERIENCE');y+=31
    for j in jobs:
        bullets=j['bullets']
        # Maintain the original employer band, date pill, and distinct bullet list.
        needed=24+sum(para(0,0,302,x,8.1,12) for x in []) if False else 24
        for bullet in bullets:
            p=Paragraph(escape(bullet),ParagraphStyle('measure',fontName='Helvetica',fontSize=8.1,leading=12))
            _,h=p.wrap(305,500);needed+=h+5
        needed+=11
        if y+needed>785:
            c.showPage();header();y=180;section(45,y,506,'EXPERIENCE (CONTINUED)');y+=35
            x=45;bw=506
        else:x=221;bw=330
        rect(x,y,bw,22,HexColor('#f4f5f6'),5);rect(x,y,2.5,22,INK)
        role=j['role'];company=j['employer'];date=j['date']
        # Role and company are kept as separate visual labels, like original.
        heading=role+'  |  '+company
        while c.stringWidth(heading,'Helvetica-Bold',8.4)>bw-92:heading=heading[:-2]
        t(x+9,y+5,heading,8.4,'Helvetica-Bold')
        if date:
            dw=c.stringWidth(date,'Helvetica-Bold',7)+12
            rect(x+bw-dw-7,y+4,dw,14,HexColor('#e4e6e8'),7)
            t(x+bw-dw-1,y+6,date,7,'Helvetica-Bold')
        y+=28
        for bullet in bullets:
            t(x+3,y,'•',8.8)
            h=para(x+14,y,bw-17,bullet,8.1,12)
            y+=h+5
        y+=9
    c.setFont('Helvetica',7);c.setFillColor(HexColor('#526775'))
    c.drawString(45,24,name.title());c.drawRightString(W-45,24,'Resume • Review before applying')
    c.save();return b.getvalue(),len(skills)


def make_pdf(resume,job):
    """Single-column ATS text order. Preserve source facts; tailor the target role."""
    from reportlab.platypus import SimpleDocTemplate,Spacer,KeepTogether
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib import colors
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    import reportlab
    from pathlib import Path
    font_dir=Path(reportlab.__file__).parent/'fonts'
    if 'ATSSans' not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont('ATSSans',str(font_dir/'Vera.ttf')))
        pdfmetrics.registerFont(TTFont('ATSSansBold',str(font_dir/'VeraBd.ttf')))
    name,contact,education,jobs=parse(resume)
    title=clean(job.get('title',''))
    employer=clean(job.get('employer',''))
    if bool(title)!=bool(employer):raise ValueError('Supply both employer and job title, or neither for a general resume')
    lines=[x.strip() for x in resume.splitlines() if x.strip()]
    start=lines.index('CORE SKILLS')+1 if 'CORE SKILLS' in lines else 0
    end=lines.index('EDUCATION') if 'EDUCATION' in lines else start
    skills=lines[start:end]
    education=education[:next((i for i,x in enumerate(education) if x in ('PROFILE','EXPERIENCE') or 'References' in x),len(education))]
    styles=getSampleStyleSheet()
    body=ParagraphStyle('atsbody',fontName='ATSSans',fontSize=9.3,leading=12.5,spaceAfter=3,textColor=colors.HexColor('#202020'))
    heading=ParagraphStyle('atssection',parent=body,fontName='ATSSansBold',fontSize=11,spaceBefore=10,spaceAfter=5,keepWithNext=True)
    role=ParagraphStyle('atsrole',parent=body,fontName='ATSSansBold',spaceBefore=7)
    def para(text,style=body):return Paragraph(escape(text.replace('•','-').replace('–','-').replace('—','-')),style)
    story=[para(name,ParagraphStyle('atsname',parent=heading,fontSize=20,leading=24)),para(contact)]
    if title:story.append(para(title+' | '+employer))
    story.append(para('PROFILE',heading))
    experience=', '.join(dict.fromkeys(j['role'].lower() for j in jobs))
    story.append(para('Experience as '+experience+'.'+(' Seeking the '+title+' position at '+employer+'.' if title else '')))
    story.append(para('EXPERIENCE',heading))
    for j in jobs:
        story.append(KeepTogether([para(j['role']+' | '+j['employer'],role),para(j['date'])]))
        story.extend(para('- '+b.lstrip('•- ')) for b in j['bullets'])
    story.append(para('EDUCATION',heading))
    story.extend(para(x) for x in education)
    if skills:
        story.append(para('SKILLS',heading));story.append(para(' | '.join(skills)))
    output=io.BytesIO()
    SimpleDocTemplate(output,pagesize=(W,H),rightMargin=45,leftMargin=45,topMargin=36,bottomMargin=36,title=name+' - '+title,author=name).build(story)
    return output.getvalue(),len(skills)
