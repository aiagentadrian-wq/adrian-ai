from cryptography.fernet import Fernet
import secrets, pathlib
p=pathlib.Path('.env')
if p.exists():
    raise SystemExit('.env exists; refusing to overwrite credentials')
password=secrets.token_urlsafe(18)
p.write_text('APP_PASSWORD='+password+'\nSESSION_SECRET='+secrets.token_urlsafe(48)+'\nENCRYPTION_KEY='+Fernet.generate_key().decode()+'\nSMTP_HOST=\nSMTP_PORT=587\nSMTP_USER=\nSMTP_PASSWORD=\nEMAIL_FROM=\nREPORT_TO=\n',encoding='utf-8')
print('Created .env. Your initial login password is:',password)
print('Store it in a password manager. Do not share .env.')
