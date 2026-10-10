"""Nutqni matnga o'giruvchi (STT) dvigatel interfeysi.

Ovozli chat MATN emas, JONLI OVOZ oqimi beradi. Bu modul audio (16-bit mono
PCM) qabul qilib, uni MATNga o'giradigan dvigatellarni belgilaydi. Keyin
``profanity.py`` o'sha matnni filtrlaydi.

Dvigatel tanlovi hozircha ochiq (``STT_ENGINE=null``). Lokal Whisper yoki bulut
STT'ga o'tish uchun faqat shu yerga bitta sinf qo'shiladi va ``_ENGINES`` ga
ro'yxatdan o'tkaziladi — ``voice.py`` o'zgarmaydi.

Kelishuv (barcha dvigatellar uchun):
  * kirish: ``pcm`` — ``sample_rate`` chastotali, 16-bit, mono, little-endian audio.
  * chiqish: aniqlangan matn (bo'sh bo'lishi mumkin, masalan jimlik).
"""
import logging

LOG = logging.getLogger('zero_guard.stt')
SAMPLE_RATE = 16000  # Aksar STT modellar 16 kHz kutadi; voice.py shu chastotaga keltiradi.


class SttEngine:
    """Barcha STT dvigatellari uchun asos. Audio bo'lagini matnga o'giradi."""
    name = 'base'
    sample_rate = SAMPLE_RATE

    def transcribe(self, pcm):
        """``pcm`` (16-bit mono PCM) ni matnga o'giradi. Qism sinf aniqlaydi."""
        raise NotImplementedError

    def close(self):
        """Resurslarni bo'shatadi (modellar, fayllar). Standart — hech narsa."""


class NullSttEngine(SttEngine):
    """O'rin egallovchi: hech narsa eshitmaydi, hamisha bo'sh matn.

    Haqiqiy dvigatel tanlanmaguncha ishlatiladi. Butun ovozli pipeline (ulanish,
    audio ushlash, filtrlash) shu bilan ham xatosiz ishlaydi — faqat hech kim
    cheklanmaydi, chunki matn chiqmaydi.
    """
    name = 'null'

    def transcribe(self, pcm):
        return ''


class FasterWhisperEngine(SttEngine):
    """Lokal Whisper (faster-whisper) — 16 kHz mono PCM'ni o'zbekcha matnga o'giradi.

    Kutubxona o'rnatilmagan bo'lsa, ``load_engine`` tushunarli xato beradi va bot
    ``null`` bilan davom etadi. ``vad_filter`` jimlik bo'laklarini tashlab,
    noto'g'ri aniqlashlarni kamaytiradi. Aniqlik modelga bog'liq (``STT_MODEL``).
    """
    name = 'faster-whisper'

    def __init__(self, model='small', language='uz', device='cpu'):
        try:
            from faster_whisper import WhisperModel  # lazy: faqat kerak bo'lsa
        except ImportError as exc:
            raise RuntimeError(
                'faster-whisper o‘rnatilmagan. STT_ENGINE=null bilan ishlating '
                'yoki `pip install faster-whisper` qiling.'
            ) from exc
        import numpy  # noqa: F401  (audio float32 ga o'tkazish uchun kerak)
        self._np = numpy
        self._model = WhisperModel(model, device=device, compute_type='int8')
        self._language = language

    def transcribe(self, pcm):
        # 16-bit int PCM -> float32 [-1, 1], Whisper shuni kutadi.
        audio = self._np.frombuffer(pcm, dtype=self._np.int16).astype('float32') / 32768.0
        if audio.size == 0:
            return ''
        segments, _ = self._model.transcribe(audio, language=self._language, vad_filter=True)
        return ' '.join(seg.text for seg in segments).strip()


# Dvigatel nomi -> sinf. Yangi dvigatel shu yerga qo'shiladi.
_ENGINES = {
    'null': NullSttEngine,
    'faster-whisper': FasterWhisperEngine,
}


def load_engine(name, **opts):
    """Nom bo'yicha STT dvigatelini yaratadi. Xato bo'lsa ``null`` ga qaytadi."""
    name = (name or 'null').strip().lower()
    cls = _ENGINES.get(name)
    if cls is None:
        LOG.warning('Noma\'lum STT dvigatel %r; null ishlatiladi', name)
        return NullSttEngine()
    try:
        return cls(**opts)
    except Exception as exc:  # o'rnatilmagan kutubxona va h.k.
        LOG.warning('STT dvigatel %r yuklanmadi (%s); null ishlatiladi', name, exc)
        return NullSttEngine()
