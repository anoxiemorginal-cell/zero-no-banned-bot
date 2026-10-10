"""Durable inbox/outbox and bounded, deterministic moderation rules."""
import hashlib
import json
import sqlite3
import time
import unicodedata
from collections import OrderedDict, deque


def normalized(value):
    value = unicodedata.normalize('NFKC', value).casefold()
    return ' '.join(''.join(c for c in value if unicodedata.category(c) != 'Cf').split())


def event_key(update):
    for kind in ('message', 'edited_message', 'chat_member', 'my_chat_member', 'chat_join_request'):
        value = update.get(kind)
        if value:
            if kind in ('message', 'edited_message'):
                extra = hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest() if kind == 'edited_message' else ''
                return f"{kind}:{value['chat']['id']}:{value['message_id']}:{extra}"
            return kind + ':' + hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()
    return None


class Store:
    def __init__(self, path):
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.executescript('''
          CREATE TABLE IF NOT EXISTS offsets(bot INTEGER PRIMARY KEY, value INTEGER NOT NULL);
          CREATE TABLE IF NOT EXISTS inbox(key TEXT PRIMARY KEY, payload TEXT NOT NULL, done INTEGER DEFAULT 0, created REAL NOT NULL);
          CREATE TABLE IF NOT EXISTS groups(chat INTEGER PRIMARY KEY, enabled INTEGER DEFAULT 0, raid_until REAL DEFAULT 0, owner INTEGER);
          CREATE TABLE IF NOT EXISTS jobs(key TEXT PRIMARY KEY, chat INTEGER, method TEXT, payload TEXT, due REAL, expires REAL, attempts INTEGER DEFAULT 0, state TEXT DEFAULT 'pending');
          CREATE TABLE IF NOT EXISTS cooldowns(chat INTEGER PRIMARY KEY, until REAL);
          CREATE TABLE IF NOT EXISTS alerts(key TEXT PRIMARY KEY, until REAL);
          CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY, at REAL, chat INTEGER, event TEXT);
        ''')
        # Eski bazalarga ovozli chat ustunini xavfsiz qo'shish (bo'lsa — e'tiborsiz).
        existing = {row[1] for row in self.db.execute('PRAGMA table_info(groups)')}
        if 'voice_enabled' not in existing:
            self.db.execute('ALTER TABLE groups ADD COLUMN voice_enabled INTEGER DEFAULT 0')
        self.db.commit()

    def ingest(self, bot, updates):
        with self.db:
            for update in updates:
                key = event_key(update)
                if key:
                    self.db.execute('INSERT OR IGNORE INTO inbox(key,payload,created) VALUES(?,?,?)', (key, json.dumps(update), time.time()))
                self.db.execute('INSERT INTO offsets VALUES(?,?) ON CONFLICT(bot) DO UPDATE SET value=max(value,excluded.value)', (bot, update['update_id'] + 1))

    def offset(self, bot):
        row = self.db.execute('SELECT value FROM offsets WHERE bot=?', (bot,)).fetchone()
        return row[0] if row else 0

    def group(self, chat):
        row = self.db.execute('SELECT * FROM groups WHERE chat=?', (chat,)).fetchone()
        return dict(row) if row else {'enabled': 0, 'raid_until': 0, 'owner': None, 'voice_enabled': 0}

    def voice(self, chat, enabled):
        self.db.execute('INSERT INTO groups(chat,voice_enabled) VALUES(?,?) ON CONFLICT(chat) DO UPDATE SET voice_enabled=excluded.voice_enabled', (chat, 1 if enabled else 0))

    def voice_chats(self):
        """Ovozli nazorat yoqilgan va himoya faol guruhlar ro'yxati."""
        return [r[0] for r in self.db.execute('SELECT chat FROM groups WHERE voice_enabled=1 AND enabled=1').fetchall()]

    def configure(self, chat, enabled, owner=None):
        self.db.execute('INSERT INTO groups(chat,enabled,owner) VALUES(?,?,?) ON CONFLICT(chat) DO UPDATE SET enabled=excluded.enabled,owner=coalesce(excluded.owner,owner)', (chat, enabled, owner))

    def raid(self, chat, until):
        self.db.execute('UPDATE groups SET raid_until=? WHERE chat=?', (until, chat))

    def job(self, key, chat, method, payload, now=None, lifetime=600):
        now = time.time() if now is None else now
        self.db.execute('INSERT OR IGNORE INTO jobs(key,chat,method,payload,due,expires) VALUES(?,?,?,?,?,?)', (key, chat, method, json.dumps(payload), now, now + lifetime))

    def alert(self, key, chat, text, now):
        row = self.db.execute('SELECT until FROM alerts WHERE key=?', (key,)).fetchone()
        if row and row[0] > now:
            return False
        self.db.execute('INSERT OR REPLACE INTO alerts VALUES(?,?)', (key, now + 60))
        self.job(f'alert:{key}:{int(now // 60)}', chat, 'sendMessage', {'chat_id': chat, 'text': text}, now)
        return True

    def cooldown(self, chat, until):
        self.db.execute('INSERT INTO cooldowns VALUES(?,?) ON CONFLICT(chat) DO UPDATE SET until=max(until,excluded.until)', (chat, until))

    def pending(self, now):
        return self.db.execute("SELECT j.* FROM jobs j LEFT JOIN cooldowns c ON c.chat=j.chat WHERE j.state='pending' AND j.due<=? AND coalesce(c.until,0)<=? ORDER BY CASE WHEN method='sendMessage' THEN 1 ELSE 0 END,due LIMIT 100", (now, now)).fetchall()

    def audit(self, chat, event):
        self.db.execute('INSERT INTO audit(at,chat,event) VALUES(?,?,?)', (time.time(), chat, event))

    def cleanup(self, now):
        with self.db:
            self.db.execute('DELETE FROM inbox WHERE done=1 AND created<?', (now - 86400,))
            self.db.execute("DELETE FROM jobs WHERE state!='pending' AND expires<?", (now - 86400,))
            self.db.execute('DELETE FROM audit WHERE at<?', (now - 7 * 86400,))
            self.db.execute('DELETE FROM alerts WHERE until<?', (now - 86400,))


class Detector:
    def __init__(self, capacity=30000):
        self.windows = OrderedDict()
        self.capacity = capacity

    def record(self, key, identity, now, seconds, limit=64):
        window = self.windows.setdefault(key, deque(maxlen=limit))
        self.windows.move_to_end(key)
        while len(self.windows) > self.capacity:
            self.windows.popitem(last=False)
        while window and window[0][0] <= now - seconds:
            window.popleft()
        if not any(item[1] == identity for item in window):
            window.append((now, identity))
        return window

    def message(self, chat, user, mid, text, now, edited=False):
        if edited:
            return None
        if len(self.record(('flood', chat, user), mid, now, 10)) > 6:
            return 'flood'
        clean = normalized(text)
        if not clean:
            return None
        digest = hashlib.sha256(clean.encode()).digest()
        if len(self.record(('repeat', chat, user, digest), mid, now, 60)) >= 3:
            return 'repeat'
        # Short common greetings must not trigger cross-user raid detection.
        if len(clean) >= 40 and len(self.record(('campaign', chat, digest), user, now, 15)) >= 5:
            return 'campaign'
        return None

    def join(self, chat, user, now):
        return len(self.record(('joins', chat), user, now, 10)) >= 10

    def bans(self, chat, actor, target, now):
        return len(self.record(('bans', chat, actor), target, now, 15)) >= 5
