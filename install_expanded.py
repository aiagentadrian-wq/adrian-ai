from pathlib import Path
import ast,hashlib,shutil,datetime,sys
root=Path.cwd();source=Path(__file__).resolve().parent/'job_v7_discovery.py';dest=root/'job_v7_discovery.py'
if not all((root/x).exists() for x in ('app.py','job_v7.py','job_v7_radar.py','job_v7_packages.py','.env')):
    sys.exit('STOP: run from main ADRIAN.AI directory. No changes made.')
if not dest.exists() or hashlib.sha256(dest.read_bytes()).hexdigest() not in ['789a95ffed1b83011f8cd658f70ebd481310a9b3e55ff8cd1f766f36e29629bf', 'd961d1a2a2840ce38495a8ebd01b429ccc27b3cfd0dc73ff2f5a3891e838e9b3']:
    sys.exit('STOP: discovery module differs from expected installed version. No changes made; upload your current file.')
ast.parse(source.read_text(encoding='utf-8'))
if hashlib.sha256(dest.read_bytes()).hexdigest()==hashlib.sha256(source.read_bytes()).hexdigest():
    print('ALREADY INSTALLED: expanded discovery present.')
else:
    backup=root/('job_v7_discovery_before_expansion_'+datetime.datetime.now().strftime('%Y%m%d_%H%M%S')+'.py')
    shutil.copy2(dest,backup);shutil.copy2(source,dest)
    print('SUCCESS: expanded Durham discovery installed. Backup:',backup)
print('Existing .env, database, UI, radar, resume generator and scheduled tasks unchanged.')
