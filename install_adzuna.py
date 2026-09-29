from pathlib import Path
import sys,hashlib,shutil,datetime
target=Path.cwd();source=Path(__file__).resolve().parent/'job_v7_discovery.py'
dest=target/'job_v7_discovery.py'
expected='af3eb1425ee6817d27695916411a0a4eecb93d244d70a0d24b115f3af1297a47'
if not (target/'app.py').is_file() or not (target/'job_v7.py').is_file() or not (target/'.venv'/'Scripts'/'python.exe').is_file():
    print('STOP: Run from your actual ADRIAN.AI app folder.');sys.exit(1)
if not dest.is_file() or hashlib.sha256(dest.read_bytes()).hexdigest()!=expected:
    print('STOP: compatibility mismatch. No files changed. Upload your current job_v7_discovery.py for a safe patch.');sys.exit(1)
backup=target/('job_v7_discovery_backup_'+datetime.datetime.now().strftime('%Y%m%d_%H%M%S')+'.py')
shutil.copy2(dest,backup)
shutil.copy2(source,dest)
print('SUCCESS: Adzuna discovery installed. Backup:',backup)
print('Existing .env, DB, app, UI, Manager, resume vault and Windows tasks untouched.')
