"""Ovozli chat moderatsiyasi — alohida userbot jarayoni.

OGOHLANTIRISH: ovozli chatga ulanish Telegram Bot API bilan MUMKIN EMAS. Bu
modul shaxsiy akkaunt sessiyasi (userbot) talab qiladi. Shaxsiy sessiyadan
foydalanish Telegram xizmat shartlariga va akkaunt ban xavfiga daxldor. Asosiy
bot (bot.py) bundan mustaqil ishlaydi; ovozli modul faqat VOICE_SESSION
sozlanganda va alohida ishga tushirilganda faollashadi.

Oqim:
    ovozli chat (jonli ovoz)
      -> userbot tinglaydi (pytgcalls, PCM audio frame)
      -> har ma'ruzachi bo'yicha segment (SpeakerBuffer)
      -> STT: audio -> matn (stt.py)
      -> haqorat filtri (profanity.py)
      -> mute / adminga tekshiruv  (umumiy SQLite outbox orqali)

Mute/tekshiruv ishlari asosiy bot bilan BITTA SQLite bazasiga yoziladi; ularni
bot.py ning ishchi havzasi (worker) bajaradi. Shunday qilib Telegram cheklovlari
va navbat mantig'i bitta joyda qoladi.
"""
import asyncio
import logging
import os
import time
from pathlib import Path

from core import Store
from lang import t, set_locale
from profanity import Profanity
from stt import load_engine, SAMPLE_RATE

ROOT = Path(__file__).resolve().parent
LOG = logging.getLogger('zero_guard.voice')
MUTE_MINUTES = 10


class SpeakerBuffer:
    """Bir ma'ruzachining PCM audiosini yig'ib, segmentlarga bo'ladi.

    Segment tayyor bo'ladi: (a) ``segment_seconds`` audio to'planganda, yoki
    (b) ``gap_seconds`` jimlikdan keyin (ma'ruzachi to'xtaganda). Bu — sof
    mantiq, test qilinadi.
    """

    def __init__(self, segment_seconds=4.0, gap_seconds=1.0, sample_rate=SAMPLE_RATE):
        self.segment_bytes = int(segment_seconds * sample_rate) * 2  # 16-bit = 2 bayt
        self.gap_seconds = gap_seconds
        self._buf = bytearray()
        self._last = None

    def add(self, pcm, now):
        """Audio qo'shadi. Tayyor segment (bytes) yoki None qaytaradi."""
        if self._last is not None and now - self._last > self.gap_seconds and self._buf:
            segment = self._flush()
            self._buf.extend(pcm)
            self._last = now
            return segment
        self._buf.extend(pcm)
        self._last = now
        if len(self._buf) >= self.segment_bytes:
            return self._flush()
        return None

    def drain(self):
        """Qolgan audioni (ma'ruzachi chiqqanda) segment sifatida qaytaradi."""
        return self._flush() if self._buf else None

    def _flush(self):
        segment = bytes(self._buf)
        self._buf.clear()
        return segment


class VoiceModerator:
    """Audio -> matn -> filtr -> moderatsiya ishi. Tarmoqsiz yadro (testlanadi)."""

    def __init__(self, store, stt, profanity, mute_minutes=MUTE_MINUTES):
        self.store = store
        self.stt = stt
        self.profanity = profanity
        self.mute_minutes = mute_minutes
        self.buffers = {}  # (chat, user) -> SpeakerBuffer

    def _buffer(self, chat, user):
        key = (chat, user)
        buf = self.buffers.get(key)
        if buf is None:
            buf = self.buffers[key] = SpeakerBuffer(sample_rate=self.stt.sample_rate)
        return buf

    def on_audio(self, chat, user, pcm, now=None):
        """Jonli audio bo'lagi keldi. Segment tayyor bo'lsa matnga o'girib tekshiradi."""
        now = time.time() if now is None else now
        segment = self._buffer(chat, user).add(pcm, now)
        if segment:
            self._process(chat, user, segment, now)

    def on_left(self, chat, user, now=None):
        """Ma'ruzachi ovozli chatdan chiqdi — qolgan audioni tekshiramiz."""
        now = time.time() if now is None else now
        buf = self.buffers.pop((chat, user), None)
        if buf:
            segment = buf.drain()
            if segment:
                self._process(chat, user, segment, now)

    def _process(self, chat, user, segment, now):
        text = ''
        try:
            text = self.stt.transcribe(segment)
        except Exception as exc:  # STT xatosi butun jarayonni to'xtatmasin
            LOG.warning('STT xato chat=%s user=%s: %s', chat, user, exc)
            return
        if text:
            LOG.info('eshitildi chat=%s user=%s: %r', chat, user, text)
            self.on_speech(chat, user, text, now)

    def _queue_mute(self, chat, user, now):
        self.store.job(
            f'voicemute:{chat}:{user}:{int(now // 600)}', chat, 'restrictChatMember',
            {'chat_id': chat, 'user_id': user,
             'permissions': {'can_send_messages': False},
             'use_independent_chat_permissions': True,
             'until_date': int(now + self.mute_minutes * 60)},
            now, lifetime=500)

    def on_speech(self, chat, user, text, now=None):
        """Aniqlangan matnni filtrlab, moderatsiya ishini navbatga qo'yadi.

        Natija: 'mute', 'review' yoki None. Ikki holatda ham foydalanuvchi
        cheklanadi — admin ishda/uxlayotgan bo'lishi mumkin, shuning uchun jazo
        darhol beriladi. Shubhali ('review') holatda admin xabardor qilinadi va
        kerak bo'lsa /release bilan qaytara oladi. Barchasi asosiy bot
        bajaradigan umumiy outboxga yoziladi.
        """
        now = time.time() if now is None else now
        verdict = self.profanity.check(text)
        if not verdict:
            return None
        kind, term = verdict
        LOG.info('CHEKLANDI (%s) chat=%s user=%s so_z=%r', kind, chat, user, term)
        self._queue_mute(chat, user, now)
        if kind == 'mute':
            self.store.alert(f'voicemute:{chat}', chat, t('voice_muted', minutes=self.mute_minutes), now)
            self.store.audit(chat, f'voice_profanity:{term}')
        else:  # 'review' — ehtiyot uchun cheklab, admin tekshiruviga yuboriladi
            self.store.alert(f'voicereview:{chat}', chat, t('voice_review_muted', minutes=self.mute_minutes), now)
            self.store.audit(chat, f'voice_review:{term}')
        self.store.db.commit()
        return kind


# --- Jonli ulanish qatlami (userbot) ----------------------------------------
# Telethon + py-tgcalls talab qiladi va faqat VOICE_SESSION sozlanganda ishlaydi.
# Kutubxonalar lazily import qilinadi — o'rnatilmagan bo'lsa ham qolgan modullar
# va testlar ishlaydi. API: py-tgcalls v2 (record + stream_frame INCOMING).


def _resample_16k_mono(pcm, src_rate, src_channels):
    """16-bit PCM'ni (manba chastota/kanal) 16 kHz mono 16-bit PCM'ga keltiradi.

    py-tgcalls RecordStream HIGH sifatda 48 kHz stereo beradi; Whisper esa
    16 kHz mono kutadi. numpy faqat shu yo'lда (voice ishlaganda) kerak.
    """
    import numpy as np
    audio = np.frombuffer(pcm, dtype=np.int16).astype(np.float32)
    if audio.size == 0:
        return b''
    if src_channels > 1:
        audio = audio.reshape(-1, src_channels).mean(axis=1)
    if src_rate != 16000:
        n = int(round(audio.size * 16000 / src_rate))
        if n <= 0:
            return b''
        audio = np.interp(np.linspace(0, audio.size - 1, n),
                          np.arange(audio.size), audio)
    return audio.astype(np.int16).tobytes()


class _Participants:
    """Ovozli chat ishtirokchilarining SSRC -> user_id moslamasini keshlaydi."""

    def __init__(self, calls, ttl=20):
        self.calls, self.ttl = calls, ttl
        self._map = {}
        self._exp = {}

    async def user_for(self, chat, ssrc, now):
        table = self._map.get(chat)
        if table is None or self._exp.get(chat, 0) < now or ssrc not in table:
            await self._refresh(chat, now)
            table = self._map.get(chat, {})
        return table.get(ssrc) or table.get(ssrc & 0xffffffff)

    async def _refresh(self, chat, now):
        try:
            parts = await self.calls.get_participants(chat)
        except Exception as exc:
            LOG.warning('get_participants xato chat=%s: %s', chat, exc)
            return
        table = {}
        for p in (parts or []):
            if p.source:
                table[p.source] = p.user_id
                table[p.source & 0xffffffff] = p.user_id  # imzolangan/imzolanmagan SSRC
        self._map[chat] = table
        self._exp[chat] = now + self.ttl


def _engine_opts():
    opts = {}
    if os.environ.get('STT_MODEL'):
        opts['model'] = os.environ['STT_MODEL']
    if os.environ.get('STT_LANG'):
        opts['language'] = os.environ['STT_LANG']
    if os.environ.get('STT_DEVICE'):
        opts['device'] = os.environ['STT_DEVICE']
    return opts


async def _sync_calls(calls, store, quality, interval=15):
    """voice_enabled guruhlar ovozli chatini tinglashга ulanadi/uziladi."""
    from pytgcalls.types import RecordStream
    joined = set()
    while True:
        want = set(store.voice_chats())
        for chat in want - joined:
            try:
                await calls.record(chat, RecordStream(True, quality))
                LOG.info('%s chat=%s', t('voice_joining'), chat)
                joined.add(chat)
            except Exception as exc:
                LOG.warning('%s chat=%s (%s)', t('voice_join_failed'), chat, exc)
        for chat in joined - want:
            try:
                await calls.leave_call(chat)
            except Exception:
                pass
            joined.discard(chat)
        await asyncio.sleep(interval)


def _load_env():
    """`.env` qiymatlarini os.environ ga yuklaydi (systemd EnvironmentFile'siz)."""
    env = ROOT / '.env'
    if env.exists():
        for line in env.read_text(encoding='utf-8').splitlines():
            if line.strip() and not line.lstrip().startswith('#') and '=' in line:
                key, value = line.split('=', 1)
                os.environ.setdefault(key.strip(), value.strip())


async def run():
    _load_env()
    set_locale(os.environ.get('INTERFACE_LANG', 'uz'))
    session = os.environ.get('VOICE_SESSION', '').strip()
    if not session:
        LOG.error('VOICE_SESSION sozlanmagan — ovozli modul ishga tushmaydi.')
        return
    api_id = os.environ.get('VOICE_API_ID', '').strip()
    api_hash = os.environ.get('VOICE_API_HASH', '').strip()
    if not api_id or not api_hash:
        LOG.error('VOICE_API_ID va VOICE_API_HASH kerak (my.telegram.org).')
        return
    try:
        from telethon import TelegramClient
        from telethon.sessions import StringSession
        from pytgcalls import PyTgCalls, filters, idle
        from pytgcalls.types import AudioQuality, Device, Direction
    except ImportError:
        LOG.error('telethon/py-tgcalls o‘rnatilmagan. '
                  '`pip install telethon py-tgcalls` qiling.')
        return

    store = Store(ROOT / 'data' / 'guard.sqlite3')
    stt = load_engine(os.environ.get('STT_ENGINE', 'null'), **_engine_opts())
    profanity = Profanity.from_dir(ROOT / 'data')
    moderator = VoiceModerator(store, stt, profanity)
    LOG.info('STT dvigatel: %s', stt.name)

    quality = AudioQuality.HIGH          # (48000, 2) — resample 16k mono'ga qilinadi
    src_rate, src_channels = quality.value

    client = TelegramClient(StringSession(session), int(api_id), api_hash)
    calls = PyTgCalls(client)
    participants = _Participants(calls)
    await client.start()
    me = await client.get_me()
    self_id = me.id
    await calls.start()
    LOG.info(t('voice_running'))

    @calls.on_update(filters.stream_frame(Direction.INCOMING, Device.MICROPHONE))
    async def _on_audio(_, update):
        now = time.time()
        for frame in update.frames:
            user = await participants.user_for(update.chat_id, frame.ssrc, now)
            if not user or user == self_id:  # userbotning o'zini tekshirmaymiz
                continue
            pcm = _resample_16k_mono(frame.frame, src_rate, src_channels)
            if pcm:
                moderator.on_audio(update.chat_id, user, pcm, now)

    asyncio.create_task(_sync_calls(calls, store, quality))
    await idle()


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(name)s %(message)s')
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        pass
