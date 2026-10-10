import asyncio
import json
import tempfile
import time
import unittest
from unittest.mock import AsyncMock

from core import Detector, Store, event_key, normalized
from bot import APIError, Guard


def message(mid=1, user=20, text='hi', chat=-100123):
    return {'update_id': mid, 'message': {'message_id': mid, 'date': int(time.time()), 'chat': {'id': chat, 'type': 'supergroup'}, 'from': {'id': user}, 'text': text}}


class CoreTests(unittest.TestCase):
    def test_normalization(self):
        self.assertEqual(normalized(' ＨＥＬＬＯ\u200b  world '), 'hello world')

    def test_flood_and_delivery_duplicates(self):
        d = Detector()
        for _ in range(20):
            self.assertIsNone(d.message(1, 2, 1, 'hi', 100))
        for mid in range(2, 7):
            self.assertIsNone(d.message(1, 2, mid, str(mid), 100))
        self.assertEqual(d.message(1, 2, 7, '7', 100), 'flood')
        self.assertIsNone(d.message(1, 2, 8, '8', 111))

    def test_repeat_and_edits(self):
        d = Detector()
        self.assertIsNone(d.message(1, 2, 1, 'spam', 100))
        self.assertIsNone(d.message(1, 2, 2, 'spam', 101))
        self.assertIsNone(d.message(1, 2, 3, 'spam', 102, edited=True))
        self.assertEqual(d.message(1, 2, 3, 'spam', 102), 'repeat')

    def test_campaign(self):
        d = Detector()
        for user in range(4):
            self.assertIsNone(d.message(1, user, user, 'long spam campaign text ' * 4, 100))
        self.assertEqual(d.message(1, 5, 5, 'long spam campaign text ' * 4, 100), 'campaign')
        for user in range(20):
            self.assertIsNone(d.message(2, user, user, 'salom', 100))

    def test_joins_unique_and_windowed(self):
        d = Detector()
        for user in range(9):
            self.assertFalse(d.join(1, user, 100))
        self.assertFalse(d.join(1, 1, 100))
        self.assertTrue(d.join(1, 9, 100))
        self.assertFalse(d.join(1, 10, 111))

    def test_bans_isolated_by_actor_and_group(self):
        d = Detector()
        for target in range(4):
            self.assertFalse(d.bans(1, 10, target, 100))
        self.assertFalse(d.bans(1, 11, 5, 100))
        self.assertTrue(d.bans(1, 10, 5, 100))
        self.assertFalse(d.bans(2, 10, 5, 100))

    def test_memory_bound(self):
        d = Detector(capacity=10)
        for user in range(100):
            d.message(1, user, 1, 'a long message', 100)
        self.assertLessEqual(len(d.windows), 10)

    def test_durable_dedup_and_offsets(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = tmp + '/state.db'
            store = Store(path)
            update = message()
            store.ingest(1, [update])
            update['update_id'] = 991
            store.ingest(2, [update])
            self.assertEqual(store.db.execute('SELECT count(*) FROM inbox').fetchone()[0], 1)
            store.db.close()
            store = Store(path)
            self.assertEqual(store.offset(2), 992)
            self.assertEqual(store.offset(1), 2)
            store.db.close()

    def test_edit_key_distinct_and_bot_delivery_key_same(self):
        update = message()
        key = event_key(update)
        update['update_id'] += 5
        self.assertEqual(key, event_key(update))
        update['edited_message'] = update.pop('message')
        self.assertNotEqual(key, event_key(update))

    def test_cooldown_and_alert_coalescing(self):
        store = Store(':memory:')
        self.addCleanup(store.db.close)
        self.assertTrue(store.alert('raid', -1, 'raid', 100))
        self.assertFalse(store.alert('raid', -1, 'raid', 101))
        store.cooldown(-1, 200)
        self.assertEqual(len(store.pending(150)), 0)
        self.assertEqual(len(store.pending(201)), 1)


class GuardTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.store = Store(':memory:')
        self.addCleanup(self.store.db.close)
        self.api = type('FakeBot', (), {'id': 99, 'username': 'ZeroNoBannedBot'})()
        self.api.call = AsyncMock(return_value={'status': 'member'})
        self.guard = Guard(self.store, [self.api])
        self.guard.admins = AsyncMock(return_value={10})
        self.guard.eligible = AsyncMock(return_value=True)
        self.chat = -100123

    def jobs(self, method=None):
        rows = self.store.db.execute('SELECT * FROM jobs').fetchall()
        return [r for r in rows if not method or r['method'] == method]

    async def test_disabled_does_not_moderate(self):
        for mid in range(20):
            await self.guard.handle(message(mid=mid, text='spam'))
        self.assertFalse(self.jobs())

    async def test_admin_never_moderated(self):
        self.store.configure(self.chat, True)
        for mid in range(20):
            await self.guard.handle(message(mid=mid, user=10, text='spam'))
        self.assertFalse(self.jobs())

    async def test_spam_queues_mute_and_deletion_once(self):
        self.store.configure(self.chat, True)
        for mid in range(1, 6):
            await self.guard.handle(message(mid=mid, text='spam'))
        self.assertEqual(len(self.jobs('restrictChatMember')), 1)
        self.assertEqual(len(self.jobs('deleteMessage')), 3)
        self.assertEqual(len(self.jobs('sendMessage')), 1)

    async def test_nonadmin_cannot_enable(self):
        await self.guard.handle(message(text='/protect on', user=20))
        self.assertFalse(self.store.group(self.chat)['enabled'])

    async def test_anonymous_cannot_enable(self):
        update = message(text='/protect on', user=10)
        update['message']['sender_chat'] = {'id': self.chat}
        await self.guard.handle(update)
        self.assertFalse(self.store.group(self.chat)['enabled'])

    async def test_missing_rights_cannot_enable(self):
        self.guard.eligible.return_value = False
        await self.guard.handle(message(text='/protect on', user=10))
        self.assertFalse(self.store.group(self.chat)['enabled'])

    async def test_disable_cancels_pending_mutes(self):
        self.store.configure(self.chat, True)
        self.guard.mute('x', self.chat, 20, time.time())
        await self.guard.handle(message(text='/protect off', user=10))
        self.assertEqual(self.jobs('restrictChatMember')[0]['state'], 'cancelled')

    async def test_stale_message_is_ignored(self):
        self.store.configure(self.chat, True)
        for mid in range(20):
            update = message(mid=mid, text='spam')
            update['message']['date'] -= 300
            await self.guard.handle(update)
        self.assertFalse(self.jobs())

    async def test_nearly_expired_mute_never_becomes_permanent(self):
        self.guard.mute('x', self.chat, 20, time.time() - 580)
        await self.guard.execute(self.jobs()[0])
        self.api.call.assert_not_awaited()
        self.assertEqual(self.jobs()[0]['state'], 'expired')

    async def test_promotion_before_mute_cancels_it(self):
        self.guard.mute('x', self.chat, 10, time.time())
        await self.guard.execute(self.jobs()[0])
        self.api.call.assert_not_awaited()
        self.assertEqual(self.jobs()[0]['state'], 'cancelled')

    async def test_retry_after_shared_cooldown_no_helper_rotation(self):
        helper = type('FakeBot', (), {'id': 98, 'username': 'helper', 'call': AsyncMock()})()
        self.guard.bots.append(helper)
        self.api.call.side_effect = APIError(429, 30)
        helper.call.side_effect = APIError(429, 30)
        self.guard.mute('x', self.chat, 20, time.time())
        await self.guard.execute(self.jobs()[0])
        self.assertEqual(self.api.call.await_count + helper.call.await_count, 1)
        self.assertFalse(self.store.pending(time.time()))
        self.assertEqual(self.jobs()[0]['state'], 'pending')

    async def test_forbidden_helper_falls_back(self):
        helper = type('FakeBot', (), {'id': 98, 'username': 'helper', 'call': AsyncMock(side_effect=APIError(403))})()
        self.guard.bots.append(helper)  # Odd chat routes to helper first.
        self.guard.mute('x', self.chat, 20, time.time())
        await self.guard.execute(self.jobs()[0])
        self.assertEqual(helper.call.await_count, 1)
        self.assertEqual(self.api.call.await_count, 2)
        self.assertEqual(self.jobs()[0]['state'], 'done')

    async def test_existing_admin_restriction_is_preserved(self):
        self.api.call.return_value = {'status': 'restricted', 'is_member': True}
        self.guard.mute('x', self.chat, 20, time.time())
        await self.guard.execute(self.jobs()[0])
        self.assertEqual(self.jobs()[0]['state'], 'cancelled')
        self.assertEqual(self.api.call.await_count, 1)

    async def test_commands_do_not_bypass_spam_filter(self):
        self.store.configure(self.chat, True)
        for mid in range(1, 5):
            await self.guard.handle(message(mid=mid, text='/start'))
        self.assertEqual(len(self.jobs('restrictChatMember')), 1)

    async def test_disabled_helper_not_eligible(self):
        # Exercise the actual permission resolver, not the usual mock.
        self.api.enabled = False
        self.assertFalse(await Guard.eligible(self.guard, self.api, self.chat, 'deleteMessage'))
        self.api.call.assert_not_awaited()

    async def test_polling_revoked_helper_does_not_stop_other_bot(self):
        self.api.enabled = True
        self.api.call.side_effect = APIError(401)
        helper = type('FakeBot', (), {'id': 98, 'enabled': True})()
        self.guard.bots.append(helper)
        await self.guard.poll(self.api)
        self.assertFalse(self.api.enabled)
        self.assertTrue(helper.enabled)

    async def test_scheduler_bounded_parallelism_in_one_group(self):
        for mid in range(20):
            self.store.job(f'd:{mid}', self.chat, 'deleteMessage', {'chat_id': self.chat, 'message_id': mid})
        gate = asyncio.Event()
        started = asyncio.Event()
        calls = []
        async def slow_call(method, **payload):
            calls.append(payload['message_id'])
            if len(calls) == 4:
                started.set()
            await gate.wait()
            return True
        self.api.call.side_effect = slow_call
        worker = asyncio.create_task(self.guard.workers())
        try:
            await asyncio.wait_for(started.wait(), 2)
            self.assertEqual(len(calls), 4)
            self.assertEqual(self.guard.chat_busy[self.chat], 4)
            self.assertEqual(len(set(calls)), 4)
        finally:
            worker.cancel()
            await asyncio.gather(worker, return_exceptions=True)
            gate.set()
            await asyncio.gather(*list(self.guard.tasks))

    async def test_disable_during_preflight_cancels_mute(self):
        self.guard.mute('x', self.chat, 20, time.time())
        async def preflight(method, **payload):
            self.store.db.execute("UPDATE jobs SET state='cancelled' WHERE key='x'")
            return {'status': 'member'}
        self.api.call.side_effect = preflight
        await self.guard.execute(self.jobs()[0])
        self.assertEqual(self.api.call.await_count, 1)
        self.assertEqual(self.jobs()[0]['state'], 'cancelled')

    async def test_raid_join_quarantine(self):
        self.store.configure(self.chat, True)
        for user in range(20, 30):
            await self.guard.handle({'chat_member': {'chat': {'id': self.chat}, 'date': int(time.time()), 'from': {'id': user}, 'old_chat_member': {'status': 'left', 'user': {'id': user}}, 'new_chat_member': {'status': 'member', 'user': {'id': user}}}})
        self.assertGreater(self.store.group(self.chat)['raid_until'], time.time())
        self.assertEqual(len(self.jobs('restrictChatMember')), 1)

    async def test_restricted_nonmember_is_not_a_join(self):
        self.store.configure(self.chat, True)
        self.store.raid(self.chat, time.time() + 600)
        await self.guard.handle({'chat_member': {'chat': {'id': self.chat}, 'date': int(time.time()), 'old_chat_member': {'status': 'left'}, 'new_chat_member': {'status': 'restricted', 'is_member': False, 'user': {'id': 20}}}})
        self.assertFalse(self.jobs())


if __name__ == '__main__':
    unittest.main()
