"""Install only public release sources; preserve credentials and private records."""
import argparse
from datetime import datetime
from pathlib import Path
import shutil
import sqlite3

FILES=['trading_education.py','trading_course_knowledge.json','test_trading_education.py','paper_trading.py','test_paper_trading.py','PAPER_TRADING.md','trading_guard.py','test_trading_guard.py','TRADING_VALIDATION.md','app.py','dashboard_core.py','ai_adapter.py','adrian_intelligence.py','job_manager_bridge.py',
       'job_v7.py','job_v7_discovery.py','job_v7_email.py','job_v7_packages.py','job_v7_radar.py','job_v7_schedule.py',
       'resume_test_email.py','trading_chat_bridge.py','trading_company_directory.py','trading_division.py','trading_lab.py','trading_monitor.py',
       'static/paper.js','static/index.html','static/dashboard.js','static/dashboard.css','static/a5-crown.svg','static/manifest.webmanifest','static/sw.js',
       'requirements.txt','README.md','RELEASE_NOTES.md','test_dashboard_v2.py','test_trading_upgrade.py','test_trading_monitor.py']

def install(source,target):
    source=source.resolve();target=target.resolve()
    if source==target:raise SystemExit('Run the installer from the downloaded release folder, not the active app folder.')
    if not (target/'app.py').is_file() or not (target/'.env').is_file():raise SystemExit('Target must be an existing configured ADRIAN.AI installation.')
    missing=[name for name in FILES if not (source/name).is_file()]
    if missing:raise SystemExit('Incomplete release: '+', '.join(missing))
    backup=target/'upgrade-backups'/('dashboard-v2-'+datetime.now().strftime('%Y%m%d-%H%M%S'))
    backup.mkdir(parents=True,exist_ok=False)
    if (target/'command_center.db').exists():
        with sqlite3.connect(target/'command_center.db') as original,sqlite3.connect(backup/'command_center.db') as snapshot:original.backup(snapshot)
    for name in FILES:
        old=target/name
        if old.is_file():
            saved=backup/name;saved.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(old,saved)
    for name in FILES:
        destination=target/name;destination.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source/name,destination)
    print('Dashboard sources installed. Credentials and private files preserved. Backup:',backup)
    print('Restart the server to apply schema additions. Connected model and scheduled tasks were not changed.')

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--target',required=True,type=Path)
    install(Path(__file__).parent,parser.parse_args().target)
