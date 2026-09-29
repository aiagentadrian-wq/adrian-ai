from pathlib import Path
import hashlib,shutil,datetime,ast,sys
root=Path.cwd();src=Path(__file__).resolve().parent/'job_v7_packages.py';dest=root/'job_v7_packages.py'
if not all((root/n).exists() for n in ('app.py','job_v7.py','job_v7_radar.py','job_v7_discovery.py')):
    sys.exit('STOP: run from ADRIAN.AI main folder.')
allowed=['a3aae8369ee91e07cd5584abd6930bb3b39b42bfb6950d12f5c38452eebc5f61', '90c40cd5f37cc0fbcd319cf73076615bc5de061e7cfd4752a064c584f8ffc780', '72643d2bfa6a29aeda79553a8c952eb4d63e0dfd7768dbb5175a3e4e6f7ef9f5']
if not dest.exists() or hashlib.sha256(dest.read_bytes()).hexdigest() not in allowed:
    sys.exit('STOP: existing resume module is not a recognized version; no files changed.')
ast.parse(src.read_text(encoding='utf-8'))
backup=root/('job_v7_packages_backup_'+datetime.datetime.now().strftime('%Y%m%d_%H%M%S')+'.py')
shutil.copy2(dest,backup);shutil.copy2(src,dest)
print('SUCCESS: original Chipotle-style layout installed. Backup:',backup)
print('Adzuna, app, database, UI, radar and scheduled tasks unchanged.')
