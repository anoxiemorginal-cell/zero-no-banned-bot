"""Userbot sessiyasini (VOICE_SESSION) xavfsiz yaratish.

Buni EGASI o'zi ishga tushiradi: telefon raqam, login kodi va 2FA parol faqat
shu jarayonda qoladi, hech qayerga chop etilmaydi. Natijada tayyor sessiya satri
.env ga (VOICE_SESSION) yoziladi. Terminalda sessiya satri KO'RSATILMAYDI.

Ishga tushirish:
    .venv/bin/python session_login.py

Avval .env da VOICE_API_ID va VOICE_API_HASH to'ldirilgan bo'lishi kerak
(my.telegram.org dan olinadi).
"""
import asyncio
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def _load_env():
    env = ROOT / '.env'
    if env.exists():
        for line in env.read_text().splitlines():
            if line.strip() and not line.lstrip().startswith('#') and '=' in line:
                key, value = line.split('=', 1)
                os.environ.setdefault(key.strip(), value.strip())


def _save_session(value):
    """VOICE_SESSION ni .env ga yozadi (bor bo'lsa yangilaydi), 600 huquq bilan."""
    env = ROOT / '.env'
    lines = env.read_text().splitlines() if env.exists() else []
    out, done = [], False
    for line in lines:
        if line.startswith('VOICE_SESSION='):
            out.append(f'VOICE_SESSION={value}')
            done = True
        else:
            out.append(line)
    if not done:
        out.append(f'VOICE_SESSION={value}')
    tmp = env.with_suffix('.tmp')
    tmp.write_text('\n'.join(out) + '\n')
    tmp.chmod(0o600)
    tmp.replace(env)


async def main():
    os.umask(0o077)
    _load_env()
    api_id = os.environ.get('VOICE_API_ID', '').strip()
    api_hash = os.environ.get('VOICE_API_HASH', '').strip()
    if not api_id or not api_hash:
        raise SystemExit('Avval .env da VOICE_API_ID va VOICE_API_HASH ni to‘ldiring.')
    try:
        from telethon import TelegramClient
        from telethon.sessions import StringSession
    except ImportError:
        raise SystemExit('telethon o‘rnatilmagan: .venv/bin/pip install telethon')

    client = TelegramClient(StringSession(), int(api_id), api_hash)
    # Telethon telefon raqam, kod va 2FA parolni shu yerda interaktiv so'raydi.
    await client.start()
    session = client.session.save()
    _save_session(session)
    me = await client.get_me()
    await client.disconnect()
    print(f'Sessiya .env ga saqlandi (VOICE_SESSION). Akkaunt: @{me.username or me.id}')
    print('Diqqat: bu shaxsiy akkaunt sessiyasi — faylni maxfiy saqlang.')


if __name__ == '__main__':
    asyncio.run(main())
