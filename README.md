# Zero No Banned Bot

O‘zbekcha Telegram superguruh himoyasi. Python 3.11+.

## Ishga tushirish

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env
chmod 600 .env
# .env ichiga BOT_TOKEN va kerak bo‘lsa HELPER_BOT_TOKENS ni kiriting.
.venv/bin/python bot.py
```

Asosiy bot va 1–4 yordamchi botni guruhga **oldindan** qo‘shing. Har biriga
xabar o‘chirish va a’zolarni cheklash admin huquqlarini bering. Guruh admini
`/protect on` yuborgandan keyingina moderatsiya boshlanadi. `/status` huquqlarni
va bajarilmagan ishlarni ko‘rsatadi. `/protect off` kutilayotgan moderatsiya
ishlarini bekor qiladi; allaqachon bajarilgan mutelar muddatida tugaydi.

`/raid on` 10 daqiqalik yangi a’zolar karantinini yoqadi, `/raid off` tugatadi.
`/release` foydalanuvchi xabariga reply qilib yuborilsa yozish huquqini guruhning
joriy standart ruxsatlariga qaytaradi. Anonim admin shaxsiy profilidan buyruq yuborishi kerak.
`/voice on` guruh ovozli chatini tinglaydigan userbot nazoratini yoqadi (quyida qarang),
`/voice off` to‘xtatadi.

## Qoidalar

- 10 soniyada 7-xabar yoki 60 soniyada 3 bir xil xabar: tegishli xabar o‘chiriladi, foydalanuvchiga 10 daqiqalik mute navbatga qo‘yiladi.
- 15 soniyada 5 xil foydalanuvchidan kelgan bir xil 40+ belgili matn: beshinchi va keyingi yuboruvchilar spam sifatida belgilanadi. Bu evristika, mazmunni tushunuvchi klassifikator emas.
- 10 soniyada 10 yangi a’zo: 10 daqiqaga raid rejimi. Chegarani bosib o‘tgan va keyingi yangi a’zolar vaqtincha mute qilinadi. Avval kirganlar ortga qarab cheklanmaydi.
- Bir admin 15 soniyada 5 a’zoni ban qilsa: guruhga ogohlantirish. Admin huquqlari va banlar avtomatik o‘zgartirilmaydi.
- Adminlar va yordamchi botlar cheklanmaydi. Oldindan admin qo‘ygan shaxsiy cheklovlar avtomatik mute bilan almashtirilmaydi.
- Har turdagi avtomatik ogohlantirish guruhga ko‘pi bilan daqiqada bir marta yuboriladi.

## Tezlik va ishonchlilik

Barcha botlar yangilanishlarni oladi; umumiy SQLite inbox hodisalarni birlashtiradi.
Telegram offsetlari faqat inbox saqlanganidan keyin siljiydi. Har bir moderatsiya
ishi yagona kalit bilan outboxga yoziladi. Jarayon qayta boshlansa navbat davom etadi.
Bir guruhda 4 tagacha, jami 16 tagacha amal parallel bajariladi. Bir foydalanuvchiga
tegishli cheklov amallari va bir guruhdagi xabarnomalar ketma-ket bajariladi.
Ishlar botlar bo‘ylab taqsimlanadi; yordamchining guruhga huquqi bo‘lmasa boshqasi sinaladi.
Bu bir guruhdagi Telegram limitini ko‘paytirish mexanizmi emas.

Polling vaqtida token bekor qilinsa yoki boshqa poller bilan to‘qnashsa, shu bot
o‘chiriladi va sog‘lom botlar davom etadi. Barcha botlar uzilsa xizmat qayta boshlanadi.

`429 retry_after` butun guruh navbatini kutishga qo‘yadi, botning o‘zi ham shu
muddat kutadi. 403, tarmoq uzilishi va vaqtinchalik xatolar qayta sinaladi.
Doimiy xatolar va muddati o‘tgan ishlar `/status`da ko‘rinadi. Cheklov muddati
30 soniyadan kam qolgan mute yuborilmaydi, chunki Telegram buni doimiy cheklovga
aylantirishi mumkin. O‘chirilayotgan bot huquqi yoki boshqa adminning bir vaqtdagi
qarori bilan API so‘rovi orasidagi poygani butunlay yo‘qotib bo‘lmaydi.

API javobi tarmoqda yo‘qolsa, muvaffaqiyatli bajarilgan ish qayta sinovga tushishi
mumkin. O‘chirish va mute takrorlari odatda xavfsiz; xabarnoma takrorlanishi mumkin.
Bu Telegram bilan tranzaksiyali “exactly once” kafolati emas.

Aniqlash oynalari xotirada va 30 000 kalit bilan chegaralangan; restartdan keyin
yangidan to‘planadi. Guruh sozlamalari, raid muddati, offset va navbat diskda qoladi.
120 soniyadan eski yangilanishlar jazoga sabab bo‘lmaydi. Qayta ishlangan inboxdan
xabar matni darhol olib tashlanadi; audit 7 kun saqlanadi. Diskni kuzatish zarur:
uzoq tarmoq uzilishi yoki kelish tezligidan past qayta ishlash tezligi navbatni o‘stiradi.

## Yordamchilar va cheklovlar

Botlar guruhga raqamli `chat_id` bilan murojaat qiladi. Ochiq username olib tashlansa
yoki qidiruvda chiqmasa ham, bot guruhda admin bo‘lib qolgan va Telegram guruhga API
kirishini ruxsat etgan bo‘lsa ishlash davom etadi. Yopilgan yoki Telegram tomonidan
bloklangan guruhga kirish, ommaviy shikoyatlarni aniqlash/to‘xtatish yoki platforma
banini bekor qilish imkoni yo‘q. 100% himoya kafolati berilmaydi.

Hozir CAPTCHA, rasm ichidagi spam, barcha turdagi reklama havolalari filtri,
banlarni avtomatik qaytarish va oddiy foydalanuvchi akkauntlari ulanmagan.
Yordamchi bot tokenlari kiritilmasa faqat asosiy bot ishlaydi. Bitta kompyuterdagi
ko‘p bot kompyuter/internet uzilishidan himoya qilmaydi. Ishlab chiqarishda doimiy
server, monitoring va real sinov guruhi kerak. Kompyuter o‘chsa bot ham to‘xtaydi.

## Interfeys tili

Barcha foydalanuvchiga ko‘rinadigan matnlar bitta `lang.py` modulida. Standart
til — o‘zbekcha. Yangi til qo‘shish uchun `lang.py` dagi `LOCALES` ga lug‘at
kiritiladi; topilmagan kalit avtomatik o‘zbekchaga qaytadi. `.env` dagi
`INTERFACE_LANG=uz|ru|en` faol tilni belgilaydi (hozircha faqat `uz` to‘liq).
Buyruq nomlari (`/protect` kabi) Telegram talabiga ko‘ra o‘zgarmaydi, lekin
tavsiflari `setMyCommands` orqali o‘zbekcha ko‘rsatiladi.

## Ovozli chat moderatsiyasi

Ovozli chat **matn emas, jonli ovoz** beradi, shuning uchun uni tinglab,
nutqni matnga o‘girib, keyin filtrlash kerak. Oqim:

```
ovozli chat (ovoz) → userbot tinglaydi (pytgcalls) → STT: ovoz → matn
                   → haqorat filtri (profanity.py) → mute / adminga tekshiruv
```

**Ogohlantirish:** ovozli chatga ulanish Telegram Bot API bilan **mumkin emas**;
u shaxsiy akkaunt sessiyasini (userbot) talab qiladi. Bu Telegram xizmat
shartlari va akkaunt ban xavfiga daxldor. Shuning uchun ovozli modul asosiy
botdan **ajralgan**, ixtiyoriy va alohida jarayon:

```sh
# .env ichiga VOICE_SESSION, VOICE_API_ID, VOICE_API_HASH (my.telegram.org) va
# STT_ENGINE ni kiriting, keyin:
.venv/bin/pip install telethon py-tgcalls faster-whisper
.venv/bin/python voice.py
```

Guruh admini `/voice on` yuborsa, userbot shu guruh ovozli chatini tinglaydi;
`/voice off` to‘xtatadi. `/voice` faqat `/protect on` yoqilgan guruhda ishlaydi,
va `VOICE_SESSION` sozlanmagan bo‘lsa bot buni aytadi.

Haqorat lug‘ati `data/` ichida uch faylda va sozlanadi:
`profanity.uz.txt` (aniq haqorat → mute), `profanity.review.txt` (shubhali →
avtomatik jazo o‘rniga administratorga yuboriladi), `profanity.allow.txt`
(begunoh so‘zlar). Lotin va kirill o‘zbekcha bir xil ko‘rinishga keltiriladi,
cho‘zilgan harflar qisqartiriladi, moslik so‘z darajasida — oddiy so‘z ichidagi
tasodifiy bo‘lak jazo bermaydi. STT dvigateli `STT_ENGINE` bilan tanlanadi:
`null` (standart, hech narsa eshitmaydi) yoki `faster-whisper` (lokal). Dvigatel
tanlanmaguncha butun pipeline xatosiz ishlaydi, faqat hech kim cheklanmaydi.
O‘zbekcha STT aniqligi modelga bog‘liq va kafolatlanmaydi; shubhali holatlar
jazo o‘rniga tekshiruvga yuboriladi.

## Tekshirish

```sh
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python benchmark.py
```

Benchmark faqat lokal aniqlash qoidalarini o‘lchaydi, Telegram API ishlash tezligini emas.
Testlar API ni mock qiladi. Haqiqiy guruhdagi huquqlar, cheklash/o‘chirish va yordamchi
almashish sinovlari alohida bajarilishi kerak.

Rasmiy hujjatlar: [Bot API](https://core.telegram.org/bots/api),
[a’zo yangilanishlari](https://core.telegram.org/bots/api#chatmemberupdated),
[vaqtli cheklov](https://core.telegram.org/bots/api#restrictchatmember),
[bot FAQ](https://core.telegram.org/bots/faq).
