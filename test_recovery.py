"""Server downtime must not become a player's timeout or departure."""
import unittest
from unittest.mock import patch
import server as s

class Connected:
    closed = False

class Recovery(unittest.TestCase):
    def room(self):
        r=s.Room('RECOVER');r.status='playing';r.turn_started=90
        r.game_started_at=90
        r.players={'black':{'name':'B'},'white':{'name':'W'}}
        r.recover_after_restart(100)
        return r

    def reconnect(self,r,now):
        r.clients={Connected():'black',Connected():'white'}
        with patch('server.time.time',return_value=now):r.connection_changed()

    def test_first_move_budget_frozen_until_both_return(self):
        r=self.room()
        self.assertFalse(r.tick(10000))
        self.assertIsNone(r.clock(10000)['running'])
        self.assertEqual(r.clock(10000)['turnElapsed'],10)
        r.clients={Connected():'black'}
        with patch('server.time.time',return_value=10000):r.connection_changed()
        self.assertIsNotNone(r.recovery_anchor)
        with self.assertRaises(ValueError):r.act('black',{'type':'pass'})
        self.reconnect(r,10000)
        self.assertFalse(r.tick(10019))
        self.assertTrue(r.tick(10020))
        self.assertEqual(r.result['reason'],'first_move_timeout')
        self.assertEqual(r.departures,{'black':0,'white':0})

    def test_scoring_deadline_preserves_pre_restart_elapsed(self):
        r=self.room();r.status='scoring';r.turn_started=None;r.review_deadline=120
        self.assertFalse(r.tick(10000))
        self.assertIsNone(r.clock(10000)['reviewDeadline'])
        self.reconnect(r,10000)
        self.assertEqual(r.review_deadline,10020)
        self.assertFalse(r.tick(10019))
        self.assertTrue(r.tick(10020))

    def test_repeated_restart_keeps_original_freeze_point(self):
        r=self.room();r=s.Room.from_snapshot(r.snapshot())
        r.recover_after_restart(999)
        self.assertEqual(r.recovery_anchor,100)
        self.reconnect(r,10000)
        self.assertEqual(r.clock(10000)['turnElapsed'],10)

    def test_preexisting_absence_is_preserved_without_downtime(self):
        r=self.room();r.absent_since['white']=95
        self.reconnect(r,10000)
        self.assertEqual(r.offline_used['white'],5)
        self.assertEqual(r.departures['white'],0)

    def test_byoyomi_is_frozen(self):
        r=self.room();r.moves=8;r.remaining['black']=0;r.periods['black']=3
        before=r.clock(100)
        self.assertEqual(r.clock(10000)['remaining'],before['remaining'])
        self.reconnect(r,10000)
        self.assertEqual(r.clock(10000)['remaining'],before['remaining'])

class DurableRecovery(unittest.IsolatedAsyncioTestCase):
    async def test_real_application_restart_freezes_saved_clock(self):
        import tempfile
        from pathlib import Path
        from storage import RoomStore
        with tempfile.TemporaryDirectory() as folder:
            path=str(Path(folder)/'rooms.sqlite3')
            store=RoomStore(path=path,database_url='');await store.open()
            r=s.Room('DURABLE');r.status='playing';r.turn_started=90;r.game_started_at=90
            r.players={'black':{'name':'B'},'white':{'name':'W'}}
            with patch('storage.time.time',return_value=100):await store.save(r)
            await store.close()
            app=s.make_app(RoomStore(path=path,database_url=''))
            ctx=s.cleanup_context(app)
            with patch('server.time.time',return_value=10000):await ctx.__anext__()
            try:
                restored=s.ROOMS['DURABLE']
                self.assertEqual(restored.recovery_anchor,100)
                self.assertEqual(restored.clock(10000)['turnElapsed'],10)
                self.assertFalse(restored.tick(10000))
                self.assertEqual(restored.departures,{'black':0,'white':0})
            finally:
                with self.assertRaises(StopAsyncIteration):await ctx.__anext__()

    async def test_unsettled_scoring_waits_for_reconnect_before_analysis(self):
        r=s.Room('SCORING');r.status='scoring';r.recover_after_restart(100)
        app=s.make_app()
        s.schedule_adjudication(app,r)
        self.assertEqual(r.status,'scoring')
        r.clients={Connected():'black',Connected():'white'}
        with patch('server.time.time',return_value=10000):r.connection_changed()
        s.schedule_adjudication(app,r)
        self.assertEqual(r.status,'playing')
