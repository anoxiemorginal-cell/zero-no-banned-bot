"""Zero No Banned Bot: one coordinator, up to four helper bot identities."""
import asyncio
import fcntl
import hashlib
import json
import logging
import os
import time
from pathlib import Path
from collections import Counter

import httpx

from core import Detector, Store
from lang import t, commands, set_locale

ROOT = Path(__file__).resolve().parent
LOG = logging.getLogger('zero_guard')
ADMIN = {'creator', 'administrator'}


class APIError(Exception):
    def __init__(self, code, retry=0):
        self.code, self.retry = code, retry
        super().__init__(f'Telegram error {code}')  # Never include a token-bearing URL.


class API:
    def __init__(self, token):
        self.client = httpx.AsyncClient(base_url=f'https://api.telegram.org/bot{token}/', timeout=45, limits=httpx.Limits(max_connections=12))
        self.id = None
        self.username = ''
        self.blocked_until = 0
        self.enabled = True

    async def call(self, method, **params):
        delay = self.blocked_until - time.time()
        if delay > 0:
            raise APIError(429, int(delay) + 1)
        if method == 'restrictChatMember' and params.get('until_date') and params['until_date'] <= time.time() + 35:
            raise APIError(400)
        try:
            response = await self.client.post(method, json=params)
            result = response.json()
        except (httpx.HTTPError, ValueError):
            raise APIError(503) from None
        if not result.get('ok'):
            retry = result.get('parameters', {}).get('retry_after', 0)
            if retry:
                self.blocked_until = max(self.blocked_until, time.time() + retry + 1)
            raise APIError(result.get('error_code', response.status_code), retry)
        return result['result']


class Guard:
    def __init__(self, store, bots):
        self.store, self.bots = store, bots
        self.detector = Detector()
        self.admin_cache = {}
        self.access_cache = {}
        self.inflight = set()
        self.chat_busy = Counter()
        self.resource_busy = set()
        self.tasks = set()
        self.worker_error = None

    async def admins(self, chat, fresh=False):
        entry = self.admin_cache.get(chat)
        if fresh or not entry or entry[0] < time.time():
            # Bot list isn't used for routing; each helper's own rights are checked below.
            for bot in self.bots:
                if not getattr(bot, 'enabled', True):
                    continue
                try:
                    rows = await bot.call('getChatAdministrators', chat_id=chat)
                    entry = (time.time() + 30, {r['user']['id'] for r in rows})
                    self.admin_cache[chat] = entry
                    break
                except APIError as exc:
                    if exc.code not in (400, 403):
                        raise
            else:
                raise APIError(403)
        return entry[1]

    async def eligible(self, bot, chat, method):
        if not getattr(bot, 'enabled', True):
            return False
        key = (bot.id, chat)
        entry = self.access_cache.get(key)
        if not entry or entry[0] < time.time():
            try:
                member = await bot.call('getChatMember', chat_id=chat, user_id=bot.id)
            except APIError as exc:
                if exc.code not in (400, 403):
                    raise
                member = {'status': 'left'}
            entry = (time.time() + 20, member)
            self.access_cache[key] = entry
        member = entry[1]
        if chat > 0 and method == 'sendMessage':
            return True
        if member['status'] not in ADMIN:
            return False
        right = {'deleteMessage': 'can_delete_messages', 'restrictChatMember': 'can_restrict_members'}.get(method)
        return not right or bool(member.get(right)) or member['status'] == 'creator'

    def notify(self, key, chat, text, now):
        self.store.alert(key, chat, text, now)

    def mute(self, key, chat, user, now):
        self.store.job(key, chat, 'restrictChatMember', {
            'chat_id': chat, 'user_id': user,
            'permissions': {'can_send_messages': False},
            'use_independent_chat_permissions': True, 'until_date': int(now + 600),
        }, now, lifetime=500)

    async def command(self, message, now):
        chat = message['chat']['id']
        actor = message.get('from', {}).get('id')
        parts = message.get('text', '').split()
        name, _, mention = parts[0].partition('@')
        if mention and mention.lower() not in {b.username.lower() for b in self.bots}:
            return False
        command = name.lower()
        known = {'/start', '/help', '/protect', '/status', '/raid', '/release', '/voice'}
        if command not in known:
            return False
        if command in {'/start', '/help'}:
            self.notify(f'help:{chat}', chat, t('help'), now)
            return True
        if message['chat']['type'] != 'supergroup':
            self.notify(f'group-only:{chat}', chat, t('group_only'), now)
            return True
        if not actor or message.get('sender_chat') or actor not in await self.admins(chat, fresh=True):
            return True
        result = ''
        if command == '/protect':
            if parts[1:] not in (['on'], ['off']):
                result = t('protect_usage')
            else:
                enabled = parts[1] == 'on'
                ready = False
                if enabled:
                    for bot in self.bots:
                        if await self.eligible(bot, chat, 'deleteMessage') and await self.eligible(bot, chat, 'restrictChatMember'):
                            ready = True
                    if not ready:
                        self.notify(f'rights:{chat}', chat, t('protect_need_rights'), now)
                        return True
                self.store.configure(chat, enabled, actor)
                if not enabled:
                    self.store.raid(chat, 0)
                    self.store.voice(chat, False)
                    self.store.db.execute("UPDATE jobs SET state='cancelled' WHERE chat=? AND state='pending' AND method!='sendMessage'", (chat,))
                result = t('protect_on') if enabled else t('protect_off')
        elif command == '/raid':
            if not self.store.group(chat)['enabled']:
                result = t('raid_need_protect')
            elif parts[1:] in (['on'], ['off']):
                self.store.raid(chat, now + 600 if parts[1] == 'on' else 0)
                result = t('raid_set', state=parts[1])
            else:
                result = t('raid_usage')
        elif command == '/voice':
            if not self.store.group(chat)['enabled']:
                result = t('raid_need_protect')
            elif parts[1:] not in (['on'], ['off']):
                result = t('voice_usage')
            elif parts[1] == 'on':
                if not os.environ.get('VOICE_SESSION'):
                    result = t('voice_no_session')
                else:
                    self.store.voice(chat, True)
                    result = t('voice_on')
            else:
                self.store.voice(chat, False)
                result = t('voice_off')
        elif command == '/release':
            reply = message.get('reply_to_message', {})
            target = reply.get('from', {}).get('id')
            if not target or reply.get('sender_chat'):
                result = t('release_need_reply')
            elif target in await self.admins(chat):
                result = t('release_admin')
            else:
                full = await self.bots[0].call('getChat', chat_id=chat)
                if not full.get('permissions'):
                    raise APIError(503)
                self.store.db.execute("UPDATE jobs SET state='cancelled' WHERE chat=? AND state='pending' AND method='restrictChatMember' AND json_extract(payload,'$.user_id')=?", (chat, target))
                self.store.job(f'release:{chat}:{message["message_id"]}', chat, 'restrictChatMember', {'chat_id': chat, 'user_id': target, 'permissions': full['permissions'], 'use_independent_chat_permissions': True}, now)
                result = t('release_queued')
        elif command == '/status':
            group = self.store.group(chat)
            pending = self.store.db.execute("SELECT count(*) FROM jobs WHERE chat=? AND state='pending'", (chat,)).fetchone()[0]
            failed = self.store.db.execute("SELECT count(*) FROM jobs WHERE chat=? AND state IN ('failed','expired')", (chat,)).fetchone()[0]
            rows = []
            for bot in self.bots:
                ready = await self.eligible(bot, chat, 'deleteMessage') and await self.eligible(bot, chat, 'restrictChatMember')
                rows.append(t('bot_ready' if ready else 'bot_not_ready', username=bot.username))
            on, off = t('status_on'), t('status_off')
            result = t('status',
                       protect=on if group['enabled'] else off,
                       raid=on if group['raid_until'] > now else off,
                       voice=on if group.get('voice_enabled') else off,
                       pending=pending, failed=failed, bots='\n'.join(rows))
        self.store.job(f'command:{chat}:{message["message_id"]}', chat, 'sendMessage', {'chat_id': chat, 'text': result}, now)
        return True

    async def handle(self, update):
        now = time.time()
        message = update.get('message') or update.get('edited_message')
        if message:
            chat = message['chat']['id']
            # Ignore old buffered messages instead of punishing a user after downtime.
            if now - message.get('date', now) > 120:
                return
            if message.get('text', '').startswith('/') and not update.get('edited_message'):
                await self.command(message, now)
            if message['chat']['type'] != 'supergroup' or not self.store.group(chat)['enabled']:
                return
            user = message.get('from', {}).get('id')
            if message.get('sender_chat') or not user or user in {b.id for b in self.bots}:
                return
            admins = await self.admins(chat)
            if user in admins:
                return
            text = message.get('text') or message.get('caption') or ''
            if not text:
                for field in ('sticker', 'animation', 'document', 'video', 'voice', 'audio'):
                    if message.get(field):
                        text = message[field].get('file_unique_id', '')
                        break
                if message.get('photo'):
                    text = message['photo'][-1].get('file_unique_id', '')
            reason = self.detector.message(chat, user, message['message_id'], text, now, bool(update.get('edited_message')))
            if reason:
                self.store.job(f'delete:{chat}:{message["message_id"]}', chat, 'deleteMessage', {'chat_id': chat, 'message_id': message['message_id']}, now)
                self.mute(f'mute:{chat}:{user}:{int(now // 600)}', chat, user, now)
                self.notify(f'spam:{chat}', chat, t('alert_spam'), now)
                self.store.audit(chat, f'spam:{reason}')
            return
        member = update.get('chat_member') or update.get('my_chat_member')
        if member:
            chat = member['chat']['id']
            target = member['new_chat_member']['user']['id']
            if member['old_chat_member']['status'] in ADMIN or member['new_chat_member']['status'] in ADMIN:
                self.admin_cache.pop(chat, None)
            self.access_cache.pop((target, chat), None)
            if not self.store.group(chat)['enabled'] or now - member.get('date', now) > 120:
                return
            old, new = member['old_chat_member'], member['new_chat_member']
            present = lambda m: m['status'] in {'member', 'administrator', 'creator'} or (m['status'] == 'restricted' and m.get('is_member', False))
            if not present(old) and present(new) and new['status'] not in ADMIN and target not in {b.id for b in self.bots}:
                if self.detector.join(chat, target, now):
                    self.store.raid(chat, now + 600)
                    self.notify(f'raid:{chat}', chat, t('alert_raid'), now)
                if self.store.group(chat)['raid_until'] > now:
                    self.mute(f'join:{chat}:{target}:{member["date"]}', chat, target, now)
            if new['status'] == 'kicked' and old['status'] != 'kicked':
                actor = member.get('from', {}).get('id')
                if actor not in {b.id for b in self.bots} and self.detector.bans(chat, actor, target, now):
                    self.notify(f'bans:{chat}', chat, t('alert_mass_ban', actor=actor), now)
                    self.store.audit(chat, 'mass_admin_ban')

    async def poll(self, bot):
        backoff = 1
        while True:
            try:
                updates = await bot.call('getUpdates', offset=self.store.offset(bot.id), timeout=30, limit=100,
                                         allowed_updates=['message', 'edited_message', 'chat_member', 'my_chat_member'])
                self.store.ingest(bot.id, updates)
                backoff = 1
            except APIError as exc:
                LOG.warning('Polling bot=%s code=%s', bot.id, exc.code)
                if exc.code in (401, 409):
                    bot.enabled = False
                    if not any(b.enabled for b in self.bots):
                        raise RuntimeError('No healthy bot receivers remain') from None
                    LOG.error('Receiver disabled bot=%s code=%s; other identities continue', bot.id, exc.code)
                    return
                await asyncio.sleep(max(exc.retry + 1, backoff))
                backoff = min(30, backoff * 2)

    async def consume(self):
        while True:
            rows = self.store.db.execute('SELECT key,payload FROM inbox WHERE done=0 ORDER BY created LIMIT 100').fetchall()
            if not rows:
                await asyncio.sleep(.05)
                continue
            for row in rows:
                try:
                    # No DB transaction spans network awaits; output keys provide idempotence.
                    await self.handle(json.loads(row['payload']))
                    self.store.db.execute('UPDATE inbox SET done=1,payload=? WHERE key=?', ('{}', row['key']))
                except APIError as exc:
                    LOG.warning('Event postponed code=%s', exc.code)
                    if exc.code in (400, 403):
                        self.store.db.execute('UPDATE inbox SET done=1,payload=? WHERE key=?', ('{}', row['key']))
                    else:
                        await asyncio.sleep(min(30, max(1, exc.retry)))
                        break
                finally:
                    self.store.db.commit()

    async def execute(self, row):
        key, chat = row['key'], row['chat']
        payload = json.loads(row['payload'])
        now = time.time()
        try:
            # <=30s until_date can mean forever in Telegram; never send an expired mute.
            if row['expires'] <= now or (payload.get('until_date') and payload['until_date'] <= now + 35):
                self.store.db.execute("UPDATE jobs SET state='expired' WHERE key=?", (key,))
                return
            target = payload.get('user_id')
            if target and target in await self.admins(chat, fresh=True):
                self.store.db.execute("UPDATE jobs SET state='cancelled' WHERE key=?", (key,))
                return
            first = hashlib.sha256(key.encode()).digest()[0] % len(self.bots)
            ordered = self.bots[first:] + self.bots[:first]
            # Private replies belong to the main bot the user started.
            if chat > 0:
                ordered = self.bots[:1]
            for bot in ordered:
                if not await self.eligible(bot, chat, row['method']):
                    continue
                # Recheck after awaited access lookup: /protect off may have cancelled this job.
                state = self.store.db.execute('SELECT state FROM jobs WHERE key=?', (key,)).fetchone()[0]
                if state != 'pending':
                    return
                try:
                    if row['method'] == 'restrictChatMember' and payload.get('until_date'):
                        current = await bot.call('getChatMember', chat_id=chat, user_id=target)
                        # Preserve an existing admin restriction, and never restrict a departed user.
                        if current['status'] != 'member':
                            self.store.db.execute("UPDATE jobs SET state='cancelled' WHERE key=?", (key,))
                            return
                    cooldown = self.store.db.execute('SELECT until FROM cooldowns WHERE chat=?', (chat,)).fetchone()
                    if cooldown and cooldown[0] > time.time():
                        raise APIError(429, int(cooldown[0] - time.time()) + 1)
                    if self.store.db.execute('SELECT state FROM jobs WHERE key=?', (key,)).fetchone()[0] != 'pending':
                        return
                    await bot.call(row['method'], **payload)
                    self.store.db.execute("UPDATE jobs SET state='done' WHERE key=?", (key,))
                    return
                except APIError as exc:
                    if exc.code == 403:
                        self.access_cache.pop((bot.id, chat), None)
                        continue
                    raise
            raise APIError(403)
        except APIError as exc:
            attempts = row['attempts'] + 1
            if exc.code == 429:
                # Shared chat cooldown: helpers do not circumvent Telegram rate limits.
                delay = max(1, exc.retry) + 1
                self.store.cooldown(chat, time.time() + delay)
            else:
                delay = min(60, 2 ** min(attempts, 6))
            failed = exc.code in (400, 401) or attempts >= 10
            self.store.db.execute('UPDATE jobs SET attempts=?,due=?,state=? WHERE key=?', (attempts, time.time() + delay, 'failed' if failed else 'pending', key))
            self.store.audit(chat, f'api:{row["method"]}:code={exc.code}')
            LOG.warning('Action chat=%s method=%s code=%s', chat, row['method'], exc.code)
        finally:
            self.store.db.commit()
            self.inflight.discard(key)
            self.chat_busy[chat] -= 1
            if self.chat_busy[chat] <= 0:
                del self.chat_busy[chat]
            self.resource_busy.discard(self.resource(row))

    @staticmethod
    def resource(row):
        payload = json.loads(row['payload'])
        if 'user_id' in payload:
            return (row['chat'], 'user', payload['user_id'])
        if row['method'] == 'sendMessage':
            return (row['chat'], 'notice')
        return (row['chat'], 'message', payload.get('message_id', row['key']))

    def completed(self, task):
        self.tasks.discard(task)
        if not task.cancelled() and task.exception() is not None:
            self.worker_error = task.exception()

    async def workers(self):
        last_cleanup = 0
        while True:
            if self.worker_error:
                raise RuntimeError('Worker failed; restarting coordinator preserves queued actions') from self.worker_error
            for row in self.store.pending(time.time()):
                if len(self.tasks) >= 16:
                    break
                resource = self.resource(row)
                if row['key'] in self.inflight or self.chat_busy[row['chat']] >= 4 or resource in self.resource_busy:
                    continue
                self.inflight.add(row['key'])
                self.chat_busy[row['chat']] += 1
                self.resource_busy.add(resource)
                task = asyncio.create_task(self.execute(row))
                self.tasks.add(task)
                task.add_done_callback(self.completed)
            if time.time() - last_cleanup > 3600:
                self.store.cleanup(time.time())
                self.admin_cache = {k: v for k, v in self.admin_cache.items() if v[0] > time.time()}
                self.access_cache = {k: v for k, v in self.access_cache.items() if v[0] > time.time()}
                last_cleanup = time.time()
            await asyncio.sleep(.05)


def load_tokens():
    env = ROOT / '.env'
    if env.exists():
        if env.stat().st_mode & 0o077:
            raise RuntimeError('.env permissions must be 600')
        for line in env.read_text().splitlines():
            if line.strip() and not line.lstrip().startswith('#') and '=' in line:
                key, value = line.split('=', 1)
                os.environ.setdefault(key.strip(), value.strip())
    tokens = [os.environ.get('BOT_TOKEN', '')] + os.environ.get('HELPER_BOT_TOKENS', '').split(',')
    tokens = list(dict.fromkeys(t.strip() for t in tokens if t.strip()))
    if not tokens or len(tokens) > 5:
        raise RuntimeError('Configure BOT_TOKEN and at most four helper tokens in .env')
    return tokens


async def main():
    os.umask(0o077)
    (ROOT / 'data').mkdir(exist_ok=True, mode=0o700)
    lock = (ROOT / 'data' / 'process.lock').open('w')
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        raise RuntimeError('Another Zero Guard coordinator is already running') from None
    store = Store(ROOT / 'data' / 'guard.sqlite3')
    tokens = load_tokens()  # .env ni ham yuklaydi
    set_locale(os.environ.get('INTERFACE_LANG', 'uz'))
    bots = [API(token) for token in tokens]
    tasks = []
    try:
        for index, bot in enumerate(bots):
            try:
                me = await bot.call('getMe')
            except APIError as exc:
                if index == 0 or exc.code != 401:
                    raise
                bot.enabled = False
                LOG.error('Helper configuration %s has an invalid token; other bots continue', index)
                continue
            bot.id, bot.username = me['id'], me['username']
            info = await bot.call('getWebhookInfo')
            if info.get('url'):
                bot.enabled = False
                LOG.error('@%s already has a webhook; not taking over this identity', bot.username)
                continue
            LOG.info('Connected @%s', bot.username)
        active = [b for b in bots if b.enabled]
        if not active:
            raise RuntimeError('No available bot identities')
        try:
            await active[0].call('setMyCommands', commands=commands())
        except APIError as exc:
            LOG.warning('setMyCommands failed code=%s', exc.code)
        guard = Guard(store, active)
        tasks = [asyncio.create_task(guard.poll(b)) for b in active]
        tasks += [asyncio.create_task(guard.consume()), asyncio.create_task(guard.workers())]
        await asyncio.gather(*tasks)
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        if 'guard' in locals():
            for task in list(guard.tasks):
                task.cancel()
            await asyncio.gather(*guard.tasks, return_exceptions=True)
        for bot in bots:
            await bot.client.aclose()
        store.db.close()
        lock.close()


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(name)s %(message)s')
    logging.getLogger('httpx').setLevel(logging.WARNING)
    logging.getLogger('httpcore').setLevel(logging.WARNING)
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
