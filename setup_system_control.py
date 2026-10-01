"""Install per-user desktop control and optional Windows sign-in startup."""
from pathlib import Path
import argparse,json,os,subprocess,sys,winreg

def main():
 p=argparse.ArgumentParser();p.add_argument('--dependencies',required=True,type=Path);p.add_argument('--ollama',type=Path,default=Path(os.environ['LOCALAPPDATA'])/'Programs/Ollama/ollama.exe');p.add_argument('--enable-startup',action='store_true');a=p.parse_args()
 root=Path(__file__).resolve().parent
 if not (root/'.env').is_file():raise SystemExit('Run setup from your configured ADRIAN.AI folder.')
 if not a.dependencies.is_dir() or not a.ollama.is_file():raise SystemExit('The dependencies and local AI program must already be installed.')
 pythonw=Path(sys.executable).with_name('pythonw.exe')
 if not pythonw.is_file():raise SystemExit('Use the Windows Python installation that runs ADRIAN.AI.')
 private=root/'job_v7_private';private.mkdir(exist_ok=True)
 (private/'launcher.json').write_text(json.dumps({'python':sys.executable,'dependencies':str(a.dependencies.resolve()),'ollama':str(a.ollama.resolve())}),encoding='utf-8')
 with winreg.OpenKey(winreg.HKEY_CURRENT_USER,r'Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders') as key:desktop=Path(os.path.expandvars(winreg.QueryValueEx(key,'Desktop')[0]))
 desktop.mkdir(exist_ok=True)
 command='@echo off\nstart "" '+subprocess.list2cmdline([str(pythonw),str(root/'system_control.py')])+'\n'
 (desktop/'ADRIAN AI Control.cmd').write_text(command,encoding='utf-8')
 if a.enable_startup:subprocess.run([sys.executable,str(root/'system_control.py'),'--action','enable-startup'],check=True)
 print('ADRIAN AI Control is on your desktop. Open it for ON/OFF and automatic startup.')
if __name__=='__main__':main()
