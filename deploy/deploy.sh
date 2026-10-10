#!/usr/bin/env bash
# Zero No Banned Bot — VPS'ga avtomatik o'rnatish.
# Ishlatish (root bilan, VPS konsolida):
#   cd /opt && git clone <REPO_URL> zero-no-banned-bot \
#     && bash zero-no-banned-bot/deploy/deploy.sh
# Qayta ishga tushirsangiz — kodni yangilaydi (git pull) va xizmatlarni qayta ishga tushiradi.
set -euo pipefail

APP="$(cd "$(dirname "$0")/.." && pwd)"
PY="$APP/.venv/bin/python"
PIP="$APP/.venv/bin/pip"

if [ "$(id -u)" -ne 0 ]; then
  echo "Bu skriptni root bilan ishga tushiring (sudo)."; exit 1
fi

echo "==> [1/6] Tizim kutubxonalari (python, ffmpeg, git)"
export DEBIAN_FRONTEND=noninteractive
apt-get update -y -qq
apt-get install -y -qq python3-venv python3-pip ffmpeg git

echo "==> [2/6] Kodni yangilash (agar git repo bo'lsa)"
if [ -d "$APP/.git" ]; then
  git -C "$APP" pull --ff-only || echo "   (git pull o'tkazib yuborildi)"
fi

echo "==> [3/6] Python muhiti va kutubxonalar"
[ -d "$APP/.venv" ] || python3 -m venv "$APP/.venv"
"$PIP" install --upgrade -q pip
"$PIP" install -q httpx==0.28.1
echo "    Ovozli chat kutubxonalari (bir oz vaqt oladi)..."
if "$PIP" install -q telethon==1.36.0 py-tgcalls==2.3.3 faster-whisper==1.0.3 numpy; then
  echo "    Ovozli kutubxonalar o'rnatildi."
else
  echo "    OGOHLANTIRISH: ovozli kutubxonalar o'rnatilmadi — asosiy bot baribir ishlaydi."
fi

echo "==> [4/6] Sozlama (.env)"
cd "$APP"
if [ ! -f .env ]; then cp .env.example .env; fi
chmod 600 .env

get_val() { grep -E "^$1=" .env | head -1 | cut -d= -f2-; }
set_val() {  # set_val KEY VALUE  — .env dagi qatorni almashtiradi/qo'shadi
  local key="$1" val="$2"
  if grep -qE "^$key=" .env; then
    python3 - "$key" "$val" <<'PY'
import sys,io
key,val=sys.argv[1],sys.argv[2]
lines=open('.env',encoding='utf-8').read().splitlines()
out=[(f"{key}={val}" if l.startswith(key+"=") else l) for l in lines]
open('.env','w',encoding='utf-8').write("\n".join(out)+"\n")
PY
  else
    printf '%s=%s\n' "$key" "$val" >> .env
  fi
}

if [ -z "$(get_val BOT_TOKEN)" ]; then
  read -rp "Asosiy BOT_TOKEN (BotFather'dan): " BT
  set_val BOT_TOKEN "$BT"
  read -rp "Yordamchi bot tokenlari (vergul bilan, bo'sh bo'lsa Enter): " HT
  [ -n "$HT" ] && set_val HELPER_BOT_TOKENS "$HT"
else
  echo "    BOT_TOKEN allaqachon bor — o'zgartirilmadi."
fi

echo
read -rp "Ovozli chat nazoratini sozlaymizmi? (ha/yo'q): " VOICE
if [ "$VOICE" = "ha" ]; then
  [ -z "$(get_val VOICE_API_ID)" ]   && { read -rp "VOICE_API_ID (my.telegram.org): " V1; set_val VOICE_API_ID "$V1"; }
  [ -z "$(get_val VOICE_API_HASH)" ] && { read -rp "VOICE_API_HASH (my.telegram.org): " V2; set_val VOICE_API_HASH "$V2"; }
  set_val STT_ENGINE faster-whisper
  if [ -z "$(get_val VOICE_SESSION)" ]; then
    echo "    Endi userbot sessiyasini yaratamiz — telefon raqam, kod va (bo'lsa) 2FA parol so'raladi."
    "$PY" session_login.py || echo "    Sessiya yaratilmadi — keyin '.venv/bin/python session_login.py' bilan qayta urining."
  fi
fi
chmod 600 .env

echo "==> [5/6] systemd xizmatlari"
sed "s#/opt/zero-no-banned-bot#$APP#g" deploy/zero-guard.service > /etc/systemd/system/zero-guard.service
sed "s#/opt/zero-no-banned-bot#$APP#g" deploy/zero-voice.service > /etc/systemd/system/zero-voice.service
systemctl daemon-reload
systemctl enable --now zero-guard
if [ -n "$(get_val VOICE_SESSION)" ]; then
  systemctl enable --now zero-voice
else
  systemctl disable --now zero-voice 2>/dev/null || true
fi

echo "==> [6/6] Holat"
sleep 2
systemctl --no-pager --lines=5 status zero-guard || true
echo
echo "TAYYOR. Jurnal: journalctl -u zero-guard -f"
echo "Ovozli jurnal:  journalctl -u zero-voice -f"
