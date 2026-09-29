from pathlib import Path
import hashlib,shutil,datetime,sys,ast
root=Path.cwd();src=Path(__file__).resolve().parent
expected={'job_v7.py': '247e144bcf8868709c9ea3cf47a269e0806d2be2d67c03010e2d3ea62ce761bf', 'job_v7_radar.py': 'c79a753d2d6bf31a706be634e39c17e72fae5adee7eafcec3e6ad594f61d6ab3'}
if not (root/'app.py').is_file() or not (root/'job_v7_discovery.py').is_file() or not (root/'.venv'/'Scripts'/'python.exe').is_file():
    sys.exit('STOP: run from your ADRIAN.AI main app directory.')
for name,digest in expected.items():
    p=root/name
    if not p.exists() or hashlib.sha256(p.read_bytes()).hexdigest()!=digest:
        sys.exit('STOP: '+name+' differs from uploaded version; no files changed. Upload your current copy.')
for name in ('job_v7.py','job_v7_radar.py','job_v7_packages.py'):
    ast.parse((src/name).read_text(encoding='utf-8'))
stamp=datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
for name in expected:shutil.copy2(root/name,root/(name.replace('.py','')+'_before_packages_'+stamp+'.py'))
for name in ('job_v7.py','job_v7_radar.py','job_v7_packages.py'):shutil.copy2(src/name,root/name)
print('SUCCESS: automatic extractive resume PDFs added to radar and scheduled email.')
print('Adzuna discovery, .env, DB, app.py, UI and scheduled tasks unchanged.')
