"""A transient database outage must not strand completed score analysis."""
import asyncio
import unittest
from unittest.mock import AsyncMock, patch
import server as s
from storage import StaleRoom


class AdjudicationSaveRetry(unittest.IsolatedAsyncioTestCase):
    def setup_case(self, result=None):
        app = s.make_app()
        room = s.Room('RETRY')
        room.status = 'scoring'
        room.players = {'black': {'name': 'B'}, 'white': {'name': 'W'}}
        room.adjudication = {'status': 'pending'}
        room.board[0] = 1
        room.board[168] = -1
        engine = app[s.ENGINE]
        engine.analyze = AsyncMock(return_value=result or {
            'status': 'ready', 'dead': [], 'uncertain': [],
            'score': room.calculate_score()})
        room.broadcast = AsyncMock()
        return app, room

    async def run_job(self, app, room):
        with patch.object(s.KataGo, 'configured', True):
            s.schedule_adjudication(app, room)
            await asyncio.gather(*tuple(app[s.JOBS]))

    async def test_transient_save_failures_retry_result_once_and_reset_review_budget(self):
        app, room = self.setup_case()
        clock = [100]
        attempts = []
        async def save(candidate):
            attempts.append(candidate.review_deadline)
            if len(attempts) < 3:
                clock[0] += 50
                raise OSError('database unavailable')
        app[s.STORE].save = AsyncMock(side_effect=save)
        async def retry_wait(delay):
            self.assertEqual(room.adjudication['status'], 'analyzing')
            self.assertIsNone(room.review_deadline)
            with self.assertRaises(ValueError):
                room.act('black', {'type': 'approve'})
        with patch('server.time.time', side_effect=lambda: clock[0]), patch('server.asyncio.sleep', side_effect=retry_wait), self.assertLogs(level='ERROR'):
            await self.run_job(app, room)
        self.assertEqual(attempts, [130, 180, 230])
        self.assertEqual(room.review_deadline, 230)
        self.assertEqual(room.adjudication['status'], 'ready')
        app[s.ENGINE].analyze.assert_awaited_once()
        room.broadcast.assert_awaited_once()

    async def test_unrelated_rollback_during_retry_keeps_the_same_analysis_job(self):
        app, room = self.setup_case()
        app[s.STORE].save = AsyncMock(side_effect=[OSError('offline'), None])
        async def rollback(delay):
            # A disconnected client or a rejected action may restore a deep copy.
            room.restore(room.snapshot())
        with patch('server.asyncio.sleep', side_effect=rollback), self.assertLogs(level='ERROR'):
            await self.run_job(app, room)
        self.assertEqual(room.adjudication['status'], 'ready')
        self.assertEqual(app[s.STORE].save.await_count, 2)
        app[s.ENGINE].analyze.assert_awaited_once()

    async def test_game_change_during_retry_discards_old_result(self):
        app, room = self.setup_case()
        app[s.STORE].save = AsyncMock(side_effect=OSError('offline'))
        async def changed(delay):
            room.game_id = 'new-game'
            room.adjudication = {'status': 'pending'}
        with patch('server.asyncio.sleep', side_effect=changed), self.assertLogs(level='ERROR'):
            await self.run_job(app, room)
        self.assertEqual(app[s.STORE].save.await_count, 1)
        self.assertEqual(room.adjudication['status'], 'pending')
        room.broadcast.assert_not_awaited()

    async def test_stale_revision_never_retries_over_newer_game(self):
        app, room = self.setup_case()
        newer = room.snapshot()
        newer['status'] = 'finished'
        newer['result'] = {'winner': 'white', 'reason': 'resign'}
        app[s.STORE].save = AsyncMock(side_effect=StaleRoom(newer))
        with self.assertLogs(level='ERROR'):
            await self.run_job(app, room)
        self.assertEqual(room.status, 'finished')
        self.assertEqual(room.result['reason'], 'resign')
        self.assertEqual(app[s.STORE].save.await_count, 1)
        room.broadcast.assert_not_awaited()

    async def test_uncertain_result_resume_is_also_retried_before_broadcast(self):
        app, room = self.setup_case({'status': 'unavailable'})
        app[s.STORE].save = AsyncMock(side_effect=[OSError('offline'), None])
        with patch('server.asyncio.sleep', new=AsyncMock()), self.assertLogs(level='ERROR'):
            await self.run_job(app, room)
        self.assertEqual(room.status, 'playing')
        self.assertIsNone(room.review_deadline)
        self.assertEqual(app[s.STORE].save.await_count, 2)
        room.broadcast.assert_awaited_once()

    async def test_shutdown_cancellation_does_not_publish_unsaved_result(self):
        app, room = self.setup_case()
        waiting = asyncio.Event()
        app[s.STORE].save = AsyncMock(side_effect=OSError('offline'))
        async def retry_wait(delay):
            waiting.set()
            await asyncio.Event().wait()
        with patch.object(s.KataGo, 'configured', True), patch('server.asyncio.sleep', side_effect=retry_wait), self.assertLogs(level='ERROR'):
            s.schedule_adjudication(app, room)
            task = next(iter(app[s.JOBS]))
            await waiting.wait()
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
        self.assertEqual(room.adjudication['status'], 'analyzing')
        self.assertIsNone(room.review_deadline)
        room.broadcast.assert_not_awaited()
