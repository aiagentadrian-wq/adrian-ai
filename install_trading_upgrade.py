"""Copy the reviewed upgrade into an existing installation, with source backups."""
import argparse,py_compile,shutil
from pathlib import Path
from datetime import datetime
FILES=['app.py','trading_chat_bridge.py','static/index.html','job_v7_packages.py','resume_test_email.py','requirements.txt','test_trading_upgrade.py']
def main():
    parser=argparse.ArgumentParser();parser.add_argument('target',help='Existing command-center folder containing app.py and .env')
    args=parser.parse_args();source=Path(__file__).resolve().parent;target=Path(args.target).resolve()
    if not (target/'app.py').is_file() or not (target/'.env').is_file():parser.error('Target must be your existing configured command-center folder.')
    if source==target:parser.error('Run this installer from the extracted update folder, not the existing installation.')
    for name in FILES:
        if not (source/name).is_file():parser.error('Update file missing: '+name)
        if name.endswith('.py'):py_compile.compile(str(source/name),doraise=True)
    backup=target/'upgrade-backups'/datetime.now().strftime('%Y%m%d-%H%M%S')
    for name in FILES:
        dest=target/name
        if dest.exists():
            saved=backup/name;saved.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(dest,saved)
        dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source/name,dest)
    print('Upgrade copied. Existing .env and databases preserved. Source backup:',backup)
    print('Next: install requirements with your .venv Python, restart the server, and test chat/email.')
if __name__=='__main__':main()
