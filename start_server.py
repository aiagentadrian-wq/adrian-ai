"""Noninteractive ADRIAN server entry point for a background scheduled task."""
from pathlib import Path
import argparse,os,socket,sys,threading,time

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--dependencies',type=Path);parser.add_argument('--stop-file',type=Path);parser.add_argument('--port',type=int,default=8000);args=parser.parse_args()
    root=Path(__file__).resolve().parent;os.chdir(root)
    if args.dependencies:sys.path.insert(0,str(args.dependencies.resolve()))
    with socket.socket() as sock:
        if sock.connect_ex(('127.0.0.1',args.port))==0:return 0
    from filelock import FileLock,Timeout
    (root/'job_v7_private').mkdir(parents=True,exist_ok=True)
    try:
        with FileLock(str(root/'job_v7_private'/'server.lock'),timeout=0):
            import uvicorn
            server=uvicorn.Server(uvicorn.Config('app:app',host='127.0.0.1',port=args.port,log_config=None,timeout_graceful_shutdown=20))
            if args.stop_file:
                def watch_stop():
                    while not server.should_exit:
                        if args.stop_file.exists():
                            server.should_exit=True;return
                        time.sleep(.25)
                threading.Thread(target=watch_stop,daemon=True).start()
            server.run()
    except Timeout:return 0
    return 0
if __name__=='__main__':raise SystemExit(main())
