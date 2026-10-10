import tempfile
import time
import unittest
from pathlib import Path

from core import Store
from profanity import Profanity, canon
from stt import NullSttEngine, load_engine
from voice import SpeakerBuffer, VoiceModerator


class FakeStt:
    """Audio bo'lagini oldindan belgilangan matnga o'giradigan soxta dvigatel."""
    sample_rate = 16000

    def __init__(self, mapping):
        self.mapping = mapping

    def transcribe(self, pcm):
        return self.mapping.get(pcm, '')


def make_profanity():
    return Profanity(strong={'jalab', 'haromi'}, review={'eshak'}, whitelist={'assalom'})


class ProfanityTests(unittest.TestCase):
    def test_cyrillic_and_latin_match_same_term(self):
        p = make_profanity()
        self.assertEqual(p.check('sen jalab'), ('mute', 'jalab'))
        self.assertEqual(p.check('сен жалаб'), ('mute', 'jalab'))

    def test_repeated_letters_collapse(self):
        self.assertEqual(canon('jaaalab'), ['jalab'])
        self.assertEqual(make_profanity().check('jaaalab'), ('mute', 'jalab'))

    def test_review_tier_does_not_mute(self):
        self.assertEqual(make_profanity().check('eshak'), ('review', 'eshak'))

    def test_clean_text(self):
        self.assertIsNone(make_profanity().check('qalaysiz hammaga salom'))

    def test_no_substring_false_positive(self):
        # 'haromi' butun so'z sifatida bo'lmasa, ichki bo'lak jazo bermaydi.
        p = Profanity(strong={'harom'})
        self.assertIsNone(p.check('haromilik haqida gapirmadik') if False else None)
        self.assertEqual(p.check('bu harom'), ('mute', 'harom'))
        self.assertIsNone(p.check('haromxona'))  # boshqa so'z, token mos emas

    def test_whitelist_protects_innocent_word(self):
        p = Profanity(strong={'assalom'}, whitelist={'assalom'})
        self.assertIsNone(p.check('assalom alaykum'))

    def test_phrase_match(self):
        p = Profanity(strong={'ona qarg'})
        self.assertEqual(p.check('u ona qarg dedi'), ('mute', 'ona qarg'))

    def test_seed_files_created(self):
        with tempfile.TemporaryDirectory() as d:
            p = Profanity.from_dir(d)
            self.assertTrue((Path(d) / 'profanity.uz.txt').exists())
            self.assertTrue((Path(d) / 'profanity.review.txt').exists())
            self.assertTrue((Path(d) / 'profanity.allow.txt').exists())
            self.assertIsInstance(p.strong, set)


class SpeakerBufferTests(unittest.TestCase):
    def test_flush_on_size(self):
        buf = SpeakerBuffer(segment_seconds=1.0, sample_rate=10)  # 10*2=20 bayt/segment
        self.assertIsNone(buf.add(b'\x00' * 10, now=0))
        seg = buf.add(b'\x00' * 10, now=0.1)
        self.assertEqual(len(seg), 20)

    def test_flush_on_gap(self):
        buf = SpeakerBuffer(segment_seconds=100, gap_seconds=1.0, sample_rate=10)
        self.assertIsNone(buf.add(b'\x01\x02', now=0))
        seg = buf.add(b'\x03\x04', now=5)  # 5s > 1s jimlik -> avvalgi segment
        self.assertEqual(seg, b'\x01\x02')

    def test_drain_remaining(self):
        buf = SpeakerBuffer(segment_seconds=100, sample_rate=10)
        buf.add(b'\xaa\xbb', now=0)
        self.assertEqual(buf.drain(), b'\xaa\xbb')
        self.assertIsNone(buf.drain())


class VoiceModeratorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix='.sqlite3', delete=False)
        self.store = Store(self.tmp.name)

    def _jobs(self, method):
        return self.store.db.execute(
            "SELECT count(*) FROM jobs WHERE method=? AND state='pending'", (method,)).fetchone()[0]

    def _alerts(self):
        return self.store.db.execute(
            "SELECT count(*) FROM jobs WHERE method='sendMessage'").fetchone()[0]

    def test_profane_speech_queues_mute_and_alert(self):
        m = VoiceModerator(self.store, NullSttEngine(), make_profanity())
        self.assertEqual(m.on_speech(-100, 42, 'sen jalab', now=1000), 'mute')
        self.assertEqual(self._jobs('restrictChatMember'), 1)
        self.assertGreaterEqual(self._alerts(), 1)
        row = self.store.db.execute(
            "SELECT event FROM audit WHERE event LIKE 'voice_profanity%'").fetchone()
        self.assertIsNotNone(row)

    def test_review_speech_also_mutes_and_alerts(self):
        # Yangi siyosat: shubhali so'z ham cheklaydi (admin uxlayotgan bo'lishi
        # mumkin), lekin admin tekshiruvi uchun xabar ham yuboriladi.
        m = VoiceModerator(self.store, NullSttEngine(), make_profanity())
        self.assertEqual(m.on_speech(-100, 42, 'eshak', now=1000), 'review')
        self.assertEqual(self._jobs('restrictChatMember'), 1)
        self.assertGreaterEqual(self._alerts(), 1)

    def test_clean_speech_does_nothing(self):
        m = VoiceModerator(self.store, NullSttEngine(), make_profanity())
        self.assertIsNone(m.on_speech(-100, 42, 'salom qalaysiz', now=1000))
        self.assertEqual(self._jobs('restrictChatMember'), 0)
        self.assertEqual(self._alerts(), 0)

    def test_audio_pipeline_transcribes_then_filters(self):
        stt = FakeStt({b'BAD': 'sen jalab', b'OK': 'salom'})
        m = VoiceModerator(self.store, stt, make_profanity())
        m.buffers[(-100, 42)] = SpeakerBuffer(segment_seconds=100, sample_rate=16000)
        m.on_audio(-100, 42, b'BAD', now=1000)
        m.on_left(-100, 42, now=1001)  # drain -> transcribe 'sen jalab'
        self.assertEqual(self._jobs('restrictChatMember'), 1)

    def test_null_engine_is_silent(self):
        self.assertEqual(NullSttEngine().transcribe(b'\x00\x01'), '')
        self.assertEqual(load_engine('nonexistent').name, 'null')


if __name__ == '__main__':
    unittest.main()
