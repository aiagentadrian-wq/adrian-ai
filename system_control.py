"""Local desktop controls; manages only processes launched by this installation."""
from pathlib import Path
import argparse,ctypes,json,os,subprocess,sys,threading,time,urllib.request
from ctypes import wintypes
ROOT=Path(__file__).resolve().parent
PRIVATE=ROOT/'job_v7_private'
STATE=PRIVATE/'launcher-state.json'
STOP=PRIVATE/'launcher.stop'
RUN_KEY=r'Software\Microsoft\Windows\CurrentVersion\Run'
RUN_NAME='ADRIAN AI'
if (PRIVATE/'launcher.json').is_file():
    sys.path.insert(0,json.loads((PRIVATE/'launcher.json').read_text(encoding='utf-8-sig'))['dependencies'])

def online(url):
    try:
        with urllib.request.urlopen(url,timeout=2) as r:return r.status==200
    except Exception:return False

def process_identity(pid):
    if os.name!='nt':return None
    api=ctypes.WinDLL('kernel32',use_last_error=True)
    api.OpenProcess.argtypes=[wintypes.DWORD,wintypes.BOOL,wintypes.DWORD];api.OpenProcess.restype=wintypes.HANDLE
    api.CloseHandle.argtypes=[wintypes.HANDLE]
    api.GetProcessTimes.argtypes=[wintypes.HANDLE]+[ctypes.POINTER(wintypes.FILETIME)]*4
    api.QueryFullProcessImageNameW.argtypes=[wintypes.HANDLE,wintypes.DWORD,wintypes.LPWSTR,ctypes.POINTER(wintypes.DWORD)]
    h=api.OpenProcess(0x1000,False,int(pid))
    if not h:return None
    try:
        created,ended,kernel,user=[wintypes.FILETIME() for _ in range(4)]
        if not api.GetProcessTimes(h,ctypes.byref(created),ctypes.byref(ended),ctypes.byref(kernel),ctypes.byref(user)):return None
        size=wintypes.DWORD(32768);buf=ctypes.create_unicode_buffer(size.value)
        if not api.QueryFullProcessImageNameW(h,0,buf,ctypes.byref(size)):return None
        return {'pid':int(pid),'created':(created.dwHighDateTime<<32)|created.dwLowDateTime,'exe':os.path.normcase(buf.value)}
    finally:api.CloseHandle(h)

def alive(record):
    return bool(record and process_identity(record['pid'])==record)

def read_state():
    try:return json.loads(STATE.read_text(encoding='utf-8'))
    except FileNotFoundError:return {}

def write_state(state):
    PRIVATE.mkdir(exist_ok=True);temp=STATE.with_suffix('.tmp');temp.write_text(json.dumps(state),encoding='utf-8');temp.replace(STATE)

def startup(enabled=None):
    import winreg
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER,RUN_KEY) as key:
        if enabled is True:
            cfg=json.loads((PRIVATE/'launcher.json').read_text(encoding='utf-8-sig'))
            pythonw=Path(cfg['python']).with_name('pythonw.exe')
            if not pythonw.is_file():raise RuntimeError('The Windows Python launcher is missing.')
            command=subprocess.list2cmdline([str(pythonw),str(ROOT/'system_control.py'),'--action','start','--quiet'])
            winreg.SetValueEx(key,RUN_NAME,0,winreg.REG_SZ,command)
        elif enabled is False:
            try:winreg.DeleteValue(key,RUN_NAME)
            except FileNotFoundError:pass
        try:
            value=winreg.QueryValueEx(key,RUN_NAME)[0]
            return str(ROOT/'system_control.py').lower() in value.lower()
        except FileNotFoundError:return False

class Controller:
    def __init__(self):self.config=json.loads((PRIVATE/'launcher.json').read_text(encoding='utf-8-sig'))
    def launch(self,args,name):
        with (PRIVATE/(name+'.log')).open('a',encoding='utf-8') as out,(PRIVATE/(name+'-errors.log')).open('a',encoding='utf-8') as err:
            p=subprocess.Popen(args,cwd=ROOT,stdout=out,stderr=err,creationflags=subprocess.CREATE_NO_WINDOW,env=os.environ.copy())
        record=process_identity(p.pid)
        if not record:raise RuntimeError(name+' exited before startup. Check its error log.')
        return record
    def start(self):
        from filelock import FileLock
        with FileLock(str(PRIVATE/'launcher.lock'),timeout=45):return self._start()
    def _start(self):
        state=read_state()
        if not online('http://127.0.0.1:11434/api/version'):
            os.environ.update(OLLAMA_LLM_LIBRARY='vulkan',GGML_VK_VISIBLE_DEVICES='0',OLLAMA_VULKAN='1',OLLAMA_NO_CLOUD='1',OLLAMA_HOST='127.0.0.1:11434',OLLAMA_NUM_PARALLEL='1',OLLAMA_MAX_LOADED_MODELS='1',OLLAMA_CONTEXT_LENGTH='8192')
            state['ai']=self.launch([self.config['ollama'],'serve'],'local-ai');write_state(state)
            self.wait('http://127.0.0.1:11434/api/version',state['ai'])
        if not online('http://127.0.0.1:8000/'):
            STOP.unlink(missing_ok=True)
            args=[self.config['python'],str(ROOT/'start_server.py'),'--dependencies',self.config['dependencies'],'--stop-file',str(STOP)]
            state['server']=self.launch(args,'system');write_state(state)
            self.wait('http://127.0.0.1:8000/',state['server'])
        return 'System is ON. All configured bots and email schedules are running.'
    def wait(self,url,record):
        for _ in range(60):
            if online(url):return
            if not alive(record):raise RuntimeError('Startup failed. Open the error logs in job_v7_private.')
            time.sleep(.5)
        raise RuntimeError('Startup is taking too long. Check the error logs and try again.')
    def stop(self):
        from filelock import FileLock
        with FileLock(str(PRIVATE/'launcher.lock'),timeout=45):return self._stop()
    def _stop(self):
        state=read_state()
        if alive(state.get('server')):
            STOP.write_text('stop',encoding='utf-8')
            for _ in range(80):
                if not alive(state['server']):break
                time.sleep(.5)
            if alive(state['server']):self.terminate(state['server'])
        if alive(state.get('ai')):self.terminate(state['ai'])
        write_state({})
        if online('http://127.0.0.1:8000/'):
            raise RuntimeError('A separate launcher is running ADRIAN.AI. Close it before using these controls.')
        return 'System is OFF. Bots and scheduled emails are paused.'
    def terminate(self,record):
        if alive(record):
            subprocess.run(['taskkill','/PID',str(record['pid']),'/T','/F'],capture_output=True,creationflags=subprocess.CREATE_NO_WINDOW,check=True)
    def status(self):
        return 'System: '+('ON' if online('http://127.0.0.1:8000/') else 'OFF')+'\nLocal AI: '+('Ready' if online('http://127.0.0.1:11434/api/version') else 'Off')

def panel(controller):
    import tkinter as tk
    from tkinter import messagebox
    root=tk.Tk();root.title('ADRIAN.AI — System control');root.geometry('480x430');root.resizable(False,False);root.configure(bg='#151820')
    tk.Label(root,text='ADRIAN.AI',font=('Segoe UI',25,'bold'),fg='#e6c064',bg='#151820').pack(anchor='w',padx=28,pady=(22,12))
    status=tk.StringVar(value='Checking your system…')
    tk.Label(root,textvariable=status,font=('Segoe UI',12),justify='left',wraplength=420,fg='white',bg='#151820').pack(anchor='w',padx=30,pady=(0,14))
    buttons=[]
    def run(action):
        for b in buttons:b.config(state='disabled')
        status.set('Please wait…')
        def worker():
            try:result=action();root.after(0,lambda:status.set(result))
            except Exception as exc:root.after(0,lambda msg=str(exc):messagebox.showerror('ADRIAN.AI',msg))
            finally:root.after(0,finish)
        threading.Thread(target=worker,daemon=True).start()
    def finish():
        for b in buttons:b.config(state='normal')
    def open_dashboard():
        controller.start()
        os.startfile('http://127.0.0.1:8000/')
        return controller.status()
    row=tk.Frame(root,bg='#151820');row.pack(padx=28,pady=5,fill='x')
    for text,fn in [('Turn system ON',controller.start),('Turn system OFF',controller.stop)]:
        b=tk.Button(row,text=text,command=lambda f=fn:run(f),font=('Segoe UI',12,'bold'),bg='#e6c064',fg='#151820',height=2,width=19);b.pack(side='left',padx=3);buttons.append(b)
    row2=tk.Frame(root,bg='#151820');row2.pack(padx=28,pady=5,fill='x')
    for text,fn in [('Open dashboard',open_dashboard),('Refresh status',controller.status)]:
        b=tk.Button(row2,text=text,command=lambda f=fn:run(f),font=('Segoe UI',11),width=21,height=2);b.pack(side='left',padx=3);buttons.append(b)
    auto=tk.BooleanVar(value=startup())
    def toggle_startup():
        try:startup(auto.get())
        except Exception as exc:auto.set(startup());messagebox.showerror('ADRIAN.AI',str(exc))
    tk.Checkbutton(root,text='Start automatically when I sign into Windows',variable=auto,command=toggle_startup,font=('Segoe UI',11),bg='#151820',fg='white',selectcolor='#151820',activebackground='#151820',activeforeground='white').pack(anchor='w',padx=28,pady=(20,8))
    tk.Label(root,text='OFF pauses all bots and emails. Startup runs quietly.\nKeep your PC awake for scheduled work.',font=('Segoe UI',10),justify='left',fg='#b8bdca',bg='#151820').pack(anchor='w',padx=30)
    run(controller.status);root.mainloop()

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--action',choices=['panel','start','stop','status','enable-startup','disable-startup'],default='panel');parser.add_argument('--quiet',action='store_true');args=parser.parse_args()
    PRIVATE.mkdir(exist_ok=True)
    from filelock import FileLock
    c=Controller()
    if args.action=='panel':panel(c);return
    try:
        result=startup(args.action=='enable-startup') if args.action.endswith('startup') else getattr(c,args.action)()
        if not args.quiet:print(result)
    except Exception as exc:
        with (PRIVATE/'launcher-errors.log').open('a',encoding='utf-8') as log:log.write(time.strftime('%Y-%m-%d %H:%M:%S')+' '+str(exc)+'\n')
        if not args.quiet:raise
        raise SystemExit(1)
if __name__=='__main__':main()
