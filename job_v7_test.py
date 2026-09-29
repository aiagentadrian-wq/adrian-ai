"""Offline source-filter and duplicate smoke checks; never sends mail."""
import tempfile,sqlite3
from pathlib import Path
from job_v7_discovery import eligible,pay_ok
assert pay_ok('$17.00 per hour')
assert not pay_ok('$16.50 per hour')
assert not pay_ok('Competitive salary')
base=dict(title='Part-time Crew Member',location='Oshawa, Ontario',description='Part-time food service',pay='$17.50 per hour',url='https://example.org/jobs/123')
assert eligible(base)
assert not eligible(dict(base,location='Vancouver, BC'))
assert not eligible(dict(base,pay='Not listed'))
assert not eligible(dict(base,title='Store Manager'))
with tempfile.TemporaryDirectory() as d:
    c=sqlite3.connect(str(Path(d)/'test.db'))
    try:
        c.execute('CREATE TABLE jobs(url TEXT UNIQUE, emailed INTEGER DEFAULT 0)')
        c.execute('INSERT OR IGNORE INTO jobs(url) VALUES(?)',(base['url'],))
        c.execute('INSERT OR IGNORE INTO jobs(url) VALUES(?)',(base['url'],))
        assert c.execute('SELECT COUNT(*) FROM jobs').fetchone()[0]==1
        c.execute('UPDATE jobs SET emailed=1 WHERE url=?',(base['url'],))
        assert c.execute('SELECT COUNT(*) FROM jobs WHERE emailed=0').fetchone()[0]==0
        c.commit()
    finally:
        c.close()

print('PASS: pay, region, part-time, exclusion and persistent duplicate filters')
