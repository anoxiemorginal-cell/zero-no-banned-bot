"""O'zbekcha haqoratni aniqlovchi sozlanadigan modul.

Bu — ovozli chat STT matnini (yoki istalgan matnni) tekshiruvchi sof mantiq.
Tarmoq yoki Telegram bilan ishlamaydi, shuning uchun to'liq test qilinadi.

Tamoyillar:
  * Lotin va kirill o'zbekcha bir xil ko'rinishga keltiriladi (transliteratsiya).
  * Cho'zilgan harflar ("jaaalab") va ajratgichlar ("j a l a b") qisqartiriladi.
  * Moslik SO'Z (token) darajasida — oddiy so'z ichidagi tasodifiy bo'lak jazo
    bermaydi (masalan "assalom" ichidagi bo'lak). Ko'p so'zli iboralar ham bor.
  * Ikki ro'yxat: STRONG (aniq haqorat → mute) va REVIEW (shubhali/kontekstga
    bog'liq → adminga tekshiruvga). WHITELIST aniq begunoh so'zlarni himoya qiladi.
  * Lug'atlar fayldan yuklanadi va admin tomonidan tahrirlanadi.
"""
import re
import unicodedata
from pathlib import Path

# O'zbek kirill -> lotin. Ko'p harfli almashinuvlar avval keladi.
_CYR = [
    ("ё", "yo"), ("ж", "j"), ("ч", "ch"), ("ш", "sh"), ("ю", "yu"), ("я", "ya"),
    ("ў", "o"), ("қ", "q"), ("ғ", "g"), ("ҳ", "h"), ("ъ", ""), ("ь", ""),
    ("а", "a"), ("б", "b"), ("в", "v"), ("г", "g"), ("д", "d"), ("е", "e"),
    ("з", "z"), ("и", "i"), ("й", "y"), ("к", "k"), ("л", "l"), ("м", "m"),
    ("н", "n"), ("о", "o"), ("п", "p"), ("р", "r"), ("с", "s"), ("т", "t"),
    ("у", "u"), ("ф", "f"), ("х", "x"), ("ц", "s"), ("ы", "i"), ("э", "e"),
]


def transliterate(text):
    """Kirillni lotinga o'giradi; lotin matn o'zgarmaydi."""
    text = unicodedata.normalize('NFKC', text).casefold()
    for cyr, lat in _CYR:
        text = text.replace(cyr, lat)
    return text


def _collapse(token):
    """Cho'zilgan harflarni qisqartiradi: 'jaaalab' -> 'jalab', 'ммм' bartaraf."""
    return re.sub(r'(.)\1+', r'\1', token)


def canon(text):
    """Matnni taqqoslash uchun kanonik tokenlarga ajratadi."""
    text = transliterate(text)
    # o' va g' kabi tutuq belgilarini ham, boshqa ortiqcha belgilarni ham olib tashlash.
    text = text.replace('ʻ', '').replace('ʼ', '').replace("'", '').replace('`', '')
    text = re.sub(r"[^a-z\s]", ' ', text)
    return [_collapse(tok) for tok in text.split() if tok]


def _load_set(path):
    terms = set()
    if path.exists():
        for line in path.read_text(encoding='utf-8').splitlines():
            line = line.split('#', 1)[0].strip()
            if line:
                # Lug'at yozuvining o'zini ham kanonik shaklga keltiramiz.
                parts = canon(line)
                if parts:
                    terms.add(' '.join(parts))
    return terms


class Profanity:
    """Sozlanadigan haqorat tekshiruvchisi.

    ``check(text)`` natijasi:
      * ``('mute', term)``   — aniq haqorat, foydalanuvchi cheklansin.
      * ``('review', term)`` — shubhali, administratorga yuborilsin.
      * ``None``             — toza.
    """

    def __init__(self, strong=None, review=None, whitelist=None):
        self.strong = set(strong or ())
        self.review = set(review or ())
        self.whitelist = set(whitelist or ())
        # Eng uzun ibora necha so'zdan iborat — bigram/trigram tekshiruvi uchun.
        self._max_n = max((len(t.split()) for t in self.strong | self.review), default=1)

    @classmethod
    def from_dir(cls, directory):
        """``<dir>/profanity.uz.txt`` va ``profanity.review.txt`` dan yuklaydi.

        Fayl bo'lmasa o'rnatilgan boshlang'ich lug'at yoziladi, keyin admin
        tahrirlaydi.
        """
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True)
        strong_path = directory / 'profanity.uz.txt'
        review_path = directory / 'profanity.review.txt'
        white_path = directory / 'profanity.allow.txt'
        if not strong_path.exists():
            strong_path.write_text(_SEED_STRONG, encoding='utf-8')
            strong_path.chmod(0o600)
        if not review_path.exists():
            review_path.write_text(_SEED_REVIEW, encoding='utf-8')
            review_path.chmod(0o600)
        if not white_path.exists():
            white_path.write_text(_SEED_ALLOW, encoding='utf-8')
            white_path.chmod(0o600)
        return cls(_load_set(strong_path), _load_set(review_path), _load_set(white_path))

    def check(self, text):
        tokens = canon(text)
        if not tokens:
            return None
        token_set = set(tokens)
        # Oddiy suhbatdagi begunoh so'z — jazolamaymiz (kontekst himoyasi).
        allowed = token_set & self.whitelist
        hit_review = None
        n = min(self._max_n, len(tokens))
        for size in range(n, 0, -1):
            for i in range(len(tokens) - size + 1):
                gram = ' '.join(tokens[i:i + size])
                if gram in allowed:
                    continue
                if gram in self.strong:
                    return ('mute', gram)
                if hit_review is None and gram in self.review:
                    hit_review = gram
        if hit_review:
            return ('review', hit_review)
        return None


# --- Boshlang'ich lug'at (admin tahrirlaydi) --------------------------------
# Bu ro'yxatlar data/ ichiga yoziladi va keyin guruh ehtiyojiga qarab
# to'ldiriladi. Har bir yozuv lotin yoki kirill bo'lishi mumkin — ikkalasi ham
# bir xil kanonik shaklga keltiriladi.
_SEED_STRONG = """\
# Aniq haqorat — aniqlanganda foydalanuvchi vaqtincha cheklanadi.
# Har qatorda bitta so'z yoki ibora. '#' bilan izoh. Lotin/kirill farqi yo'q.
jalab
ablah
haromi
"""

_SEED_REVIEW = """\
# Shubhali/kontekstga bog'liq — avtomatik jazo o'rniga administratorga yuboriladi.
# Oddiy suhbatda ham uchrashi mumkin bo'lgan so'zlar shu yerga.
eshak
tentak
"""

_SEED_ALLOW = """\
# Begunoh so'zlar — tasodifan haqorat ro'yxatiga tushib qolsa ham jazolanmaydi.
assalom
salom
"""
