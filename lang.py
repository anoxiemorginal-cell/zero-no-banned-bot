"""Yagona til (interfeys) moduli.

Botning barcha foydalanuvchiga ko'rinadigan matnlari shu yerda. Boshqa modullar
matnni qattiq yozmaydi, balki ``t('kalit', ...)`` orqali oladi. Standart til —
o'zbekcha (``uz``). Keyinchalik yangi til qo'shish uchun ``LOCALES`` ga yangi
lug'at kiritish kifoya; topilmagan kalit avtomatik o'zbekchaga qaytadi.

Buyruq nomlari (``/protect`` kabi) Telegram texnik talabiga ko'ra o'zgarmaydi,
lekin ularning tavsiflari (``setMyCommands`` uchun) shu yerda tarjima qilinadi.
"""

DEFAULT_LOCALE = 'uz'

# Faol til. bot.py ishga tushganda .env dagi INTERFACE_LANG qiymati bilan
# o'rnatiladi; test va boshqa modullar ham shuni o'qiydi.
_active = DEFAULT_LOCALE


def set_locale(locale):
    """Faol tilni o'rnatadi. Noma'lum til berilsa o'zbekchada qoladi."""
    global _active
    _active = locale if locale in LOCALES else DEFAULT_LOCALE
    return _active


def locale():
    return _active


def t(key, locale=None, **kwargs):
    """Kalit bo'yicha matnni faol (yoki ko'rsatilgan) tilda qaytaradi.

    Kalit tanlangan tilda topilmasa o'zbekchaga, u ham bo'lmasa kalitning
    o'ziga qaytadi. ``kwargs`` matndagi ``{nom}`` o'rniga qo'yiladi.
    """
    loc = locale or _active
    table = LOCALES.get(loc, LOCALES[DEFAULT_LOCALE])
    text = table.get(key)
    if text is None:
        text = LOCALES[DEFAULT_LOCALE].get(key, key)
    if kwargs:
        try:
            return text.format(**kwargs)
        except (KeyError, IndexError):
            return text
    return text


def commands(locale=None):
    """``setMyCommands`` uchun [{'command':..,'description':..}, ...] ro'yxati."""
    loc = locale or _active
    table = COMMANDS.get(loc, COMMANDS[DEFAULT_LOCALE])
    return [{'command': name, 'description': desc} for name, desc in table]


# --- O'zbekcha interfeys matnlari -------------------------------------------
# Kalitlar ma'no bo'yicha guruhlangan. Yangi matn qo'shganda shu yerga yoz.
UZ = {
    # Yordam / umumiy
    'help': (
        '🛡 Zero No Banned Bot\n'
        'Flood, takroriy spam va ommaviy kirishlarni kuzataman.\n'
        'Guruhga admin qilib qo‘shing: xabar o‘chirish va a’zolarni cheklash huquqlari kerak.\n'
        '\n'
        'Admin buyruqlari (superguruhda):\n'
        '/protect on — himoyani yoqish\n'
        '/protect off — himoyani o‘chirish, kutilayotgan cheklovlarni bekor qilish\n'
        '/status — himoya, yordamchilar va navbat holati\n'
        '/raid on — yangi kiruvchilar uchun 10 daqiqalik himoya rejimi\n'
        '/raid off — yangi cheklovlar uchun himoya rejimini tugatish\n'
        '/release — foydalanuvchi xabariga reply qilib cheklovni yechish\n'
        '\n'
        '10 soniyada 7-xabar yoki 60 soniyada 3 bir xil xabar: o‘chirish va 10 daqiqa mute.\n'
        '10 soniyada 10 kishi kirsa: keyingi yangi a’zolar 10 daqiqa mute.\n'
        'Ommaviy admin banlari aniqlansa ogohlantiraman; avtomatik admin huquqini olmayman.\n'
        'Telegram banini yoki shikoyatlarni bot bekor qila olmaydi.'
    ),
    'group_only': 'Bu buyruq superguruhda ishlaydi.',

    # /protect
    'protect_usage': 'Misol: /protect on yoki /protect off',
    'protect_need_rights': 'Avval botga xabar o‘chirish va a’zolarni cheklash admin huquqlarini bering.',
    'protect_on': 'Himoya yoqildi ✅',
    'protect_off': 'Himoya o‘chirildi. Avval qo‘yilgan vaqtli mutelar o‘z muddatida tugaydi.',

    # /raid
    'raid_need_protect': 'Avval /protect on yuboring.',
    'raid_set': 'Yangi a’zolar uchun himoya rejimi: {state}',
    'raid_usage': 'Misol: /raid on yoki /raid off',

    # /release
    'release_need_reply': 'Foydalanuvchi xabariga reply qiling.',
    'release_admin': 'Admin cheklanmaydi.',
    'release_queued': 'Cheklovni yechish navbatga qo‘yildi.',

    # /status
    'status': (
        '🛡 Himoya: {protect}\n'
        'Raid: {raid}\n'
        'Ovozli chat: {voice}\n'
        'Navbat: {pending}; bajarilmagan: {failed}\n{bots}'
    ),
    'status_on': 'yoqilgan',
    'status_off': 'o‘chiq',
    'bot_ready': '@{username}: tayyor',
    'bot_not_ready': '@{username}: admin huquqlari yetishmaydi',

    # Ogohlantirishlar (guruhga yuboriladi)
    'alert_spam': '🛡 Spam oqimi aniqlandi. Xabarlarni o‘chirish va vaqtli cheklovlar navbatga qo‘yildi.',
    'alert_raid': '🛡 Ommaviy kirish aniqlandi. 10 daqiqa davomida yangi a’zolarga vaqtli yozish cheklovi qo‘yiladi.',
    'alert_mass_ban': '⚠️ Admin {actor} 15 soniyada kamida 5 a’zoni ban qildi. Guruh egasi adminlar huquqlarini tekshirsin. Banlar avtomatik bekor qilinmadi.',

    # Ovozli chat moderatsiyasi
    'voice_on': 'Ovozli chat nazorati faol.',
    'voice_off': 'Ovozli chat nazorati o‘chirildi.',
    'voice_usage': 'Misol: /voice on yoki /voice off',
    'voice_joining': 'Yordamchi userbot ovozli chatga ulanmoqda.',
    'voice_join_failed': 'Ovozli chatga ulanish amalga oshmadi. Qayta urinish boshlanadi.',
    'voice_no_session': 'Ovozli chat nazorati sozlanmagan (userbot sessiyasi yo‘q).',
    'voice_running': 'Bot hozir ishlayapti.',
    'voice_muted': 'Foydalanuvchi haqoratli so‘z ishlatgani sababli {minutes} daqiqaga vaqtincha cheklab qo‘yildi.',
    'voice_review': 'Diqqat! Aniqlangan ibora haqoratli bo‘lishi mumkin. Tekshirish uchun administratorga yuborildi.',
    'voice_review_muted': 'Shubhali ibora aniqlandi — foydalanuvchi ehtiyot uchun {minutes} daqiqaga vaqtincha cheklandi. Admin tekshirib, kerak bo‘lsa reply qilib /release bilan qaytaradi.',

    # Asosiy menyu tugmalari (kelgusi admin paneli uchun tayyor matnlar)
    'menu_protect': '🛡 Guruh himoyasi',
    'menu_voice': '🎙 Ovozli chat nazorati',
    'menu_settings': '⚙️ Sozlamalar',
    'menu_stats': '📊 Statistika',
    'menu_log': '📋 Moderatsiya jurnali',
    'menu_admins': '👮 Administratorlar',
    'menu_help': '❓ Yordam',
}

# Ruscha va inglizcha — ixtiyoriy. Bo'sh kalitlar avtomatik o'zbekchaga qaytadi.
# Keyinchalik to'ldirish uchun joy; INTERFACE_LANG=ru/en bilan yoqiladi.
RU = {}
EN = {}

LOCALES = {'uz': UZ, 'ru': RU, 'en': EN}

# Buyruq tavsiflari (setMyCommands). Buyruq nomlari barcha tillarda bir xil.
_UZ_COMMANDS = [
    ('protect', 'Himoyani yoqish yoki o‘chirish'),
    ('raid', 'Yangi kiruvchilar uchun himoya rejimi'),
    ('voice', 'Ovozli chat nazoratini boshqarish'),
    ('release', 'Reply qilingan foydalanuvchidan cheklovni yechish'),
    ('status', 'Himoya, yordamchilar va navbat holati'),
    ('help', 'Yordam va qoidalar'),
]
COMMANDS = {'uz': _UZ_COMMANDS, 'ru': _UZ_COMMANDS, 'en': _UZ_COMMANDS}
