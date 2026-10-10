"""Save a helper token copied from BotFather, without printing secrets."""
import os
import re
import subprocess
import time
from pathlib import Path

os.umask(0o077)
time.sleep(0.4)
try:
    token = subprocess.check_output(['xclip', '-selection', 'clipboard', '-o'], text=True, stderr=subprocess.DEVNULL).strip()
except subprocess.CalledProcessError:
    raise SystemExit('Clipboard is unavailable; nothing saved') from None
if not re.fullmatch(r'\d{6,12}:[A-Za-z0-9_-]{35}', token):
    raise SystemExit('Clipboard does not contain a bot token; nothing saved')
path = Path(__file__).resolve().parent / '.env'
values = dict(line.split('=', 1) for line in path.read_text().splitlines() if '=' in line and not line.startswith('#'))
helpers = [t for t in values.get('HELPER_BOT_TOKENS', '').split(',') if t]
if token == values['BOT_TOKEN'] or token in helpers:
    raise SystemExit('This token is already configured; nothing changed')
if len(helpers) >= 4:
    raise SystemExit('Four helpers already configured')
helpers.append(token)
values['HELPER_BOT_TOKENS'] = ','.join(helpers)
temp = path.with_suffix('.tmp')
temp.write_text('\n'.join(f'{key}={value}' for key, value in values.items()) + '\n')
temp.chmod(0o600)
temp.replace(path)
subprocess.run(['xclip', '-selection', 'clipboard'], input='', text=True, check=True)
print(f'Helper token saved privately; configured helper count={len(helpers)}')
