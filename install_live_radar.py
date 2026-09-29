from pathlib import Path
import shutil,datetime,sys
target=Path.cwd()
source=Path(__file__).resolve().parent/'job_v7_radar.py'
if not (target/'app.py').is_file() or not (target/'job_v7_discovery.py').is_file() or not (target/'job_v7_schedule.py').is_file() or not (target/'.venv'/'Scripts'/'python.exe').is_file():
    print('STOP: Run from actual V7 ADRIAN.AI app folder; no files changed.');sys.exit(1)
dest=target/'job_v7_radar.py'
if dest.exists():
    backup=target/('job_v7_radar_backup_'+datetime.datetime.now().strftime('%Y%m%d_%H%M%S')+'.py')
    shutil.copy2(dest,backup);print('Backup:',backup)
shutil.copy2(source,dest)
print('SUCCESS: Radar installed. Existing .env, DB, app, UI, Manager and schedules unchanged.')
