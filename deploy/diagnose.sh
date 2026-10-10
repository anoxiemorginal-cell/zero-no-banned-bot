#!/usr/bin/env bash
# Bir martalik diagnostika — ovozli bot nega ishlamayotganини aniqlash uchun.
# Ishlatish (VPS panel terminalida, root):
#   cd /opt/zero-no-banned-bot && git pull && bash deploy/diagnose.sh
# Hech narsani o'zgartirmaydi va hech qayerga yubormaydi — faqat ekranga chiqaradi.
APP="$(cd "$(dirname "$0")/.." && pwd)"
cd "$APP"

echo "### xizmatlar (is-active)"
systemctl is-active zero-guard zero-voice 2>&1

echo "### kutubxonalar"
.venv/bin/python - <<'PY' 2>&1
for m in ("telethon","pytgcalls","faster_whisper","numpy"):
    try:
        __import__(m); print("OK", m)
    except Exception as e:
        print("YO'Q", m, "->", e)
PY

echo "### sozlama (sirlar ko'rsatilmaydi, faqat bor/yo'q)"
grep -E '^(STT_ENGINE|STT_MODEL|STT_LANG)=' .env 2>/dev/null
for k in BOT_TOKEN VOICE_API_ID VOICE_API_HASH VOICE_SESSION; do
  v=$(grep -E "^$k=" .env 2>/dev/null | cut -d= -f2-)
  if [ -n "$v" ]; then echo "$k = BOR (${#v} belgi)"; else echo "$k = BO'SH"; fi
done

echo "### voice jurnali — muhim qatorlar"
journalctl -u zero-voice --no-pager 2>&1 | grep -iE "STT dvigatel|eshitildi|CHEKLANDI|xato|error|traceback|ishlayapti|ulan|Exception|Failed" | tail -25

echo "### voice jurnali — eng oxirgi 15 qator"
journalctl -u zero-voice -n 15 --no-pager 2>&1

echo "### TUGADI — yuqoridagi matnni nusxalab tashlang"
