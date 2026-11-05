import unittest
from unittest.mock import patch
import server as s
import rules_policy as p

class TenSeconds(unittest.TestCase):
    def room(self):
        r=s.Room('TEN');r.claim(None,'A');r.claim(None,'B');r.moves=2;r.turn_started=1000;r.remaining['black']=5;return r
    def test_new_room_main_to_ten_seconds(self):
        r=self.room();self.assertEqual(r.clock(1005)['remaining']['black'],10)
        self.assertEqual(r.clock(1014.99)['periods']['black'],3)
        self.assertEqual(r.clock(1015)['periods']['black'],2)
        self.assertEqual(r.clock(1035)['remaining']['black'],0)
        self.assertEqual(r.clock(1005)['byoyomiSeconds'],10)
        self.assertIn('OT[3x10 byo-yomi]',r.sgf())
    def test_move_resets_ten_seconds(self):
        r=self.room()
        with patch('server.time.time',return_value=1016):r.act('black',{'type':'move','index':0})
        self.assertEqual(r.periods['black'],2);self.assertEqual(r.clock(1016)['remaining']['black'],10)
    def test_existing_snapshot_retains_thirty_seconds(self):
        r=self.room();saved=r.snapshot();saved.pop('byoyomi_seconds')
        old=s.Room.from_snapshot(saved)
        self.assertEqual(old.clock(1005)['remaining']['black'],30)
        self.assertIn('OT[3x30 byo-yomi]',old.sgf())
        self.assertEqual(s.Room.from_snapshot(r.snapshot()).byoyomi_seconds,10)
