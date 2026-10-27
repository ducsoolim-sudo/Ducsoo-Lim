import unittest
from unittest.mock import patch
import server as s
import rules_policy as p


class Socket:
    closed=False


class MannersTests(unittest.TestCase):
    def room(self):
        r=s.Room('MANNERS');r.claim(None,'A');r.claim(None,'B')
        r.turn_started=1000;r.game_started_at=1000
        self.black,self.white=Socket(),Socket();r.clients={self.black:'black',self.white:'white'}
        return r

    def act(self,r,role,action,now):
        with patch('server.time.time',return_value=now):r.act(role,action)

    def test_first_action_30_second_boundary(self):
        r=self.room();self.assertFalse(r.tick(1029.99));self.assertTrue(r.tick(1030))
        self.assertEqual(r.result,{'reason':'first_move_timeout','winner':'white'})
        r=self.room();self.act(r,'black',{'type':'move','index':0},1029.9)
        self.assertEqual(r.moves,1);self.assertAlmostEqual(r.remaining['black'],270.1)

    def test_idle_warning_and_loss(self):
        r=self.room();r.moves=2
        self.assertIsNone(r.clock(1059.9)['idleWarning'])
        self.assertEqual(r.clock(1060)['idleWarning'],'black')
        self.assertFalse(r.tick(1089.9));self.assertTrue(r.tick(1090))
        self.assertEqual(r.result['reason'],'move_delay')
        with self.assertRaises(ValueError):self.act(r,'black',{'type':'move','index':0},1091)
        self.assertEqual(r.board[0],0)

    def test_main_to_byoyomi_periods_and_reset(self):
        r=self.room();r.moves=2;r.remaining['black']=5
        self.assertEqual(r.clock(1005)['remaining']['black'],30)
        self.assertEqual(r.clock(1034.99)['periods']['black'],3)
        self.assertEqual(r.clock(1035)['periods']['black'],2)
        self.act(r,'black',{'type':'move','index':0},1036)
        self.assertEqual(r.remaining['black'],0);self.assertEqual(r.periods['black'],2)
        self.assertEqual(r.clock(1036)['remaining']['black'],30)

    def test_third_period_expiry_and_no_idle_penalty_in_byoyomi(self):
        r=self.room();r.moves=2;r.remaining['black']=0
        self.assertFalse(r.tick(1089.9));self.assertTrue(r.tick(1090))
        self.assertEqual(r.result['reason'],'time')
        r=self.room();r.moves=2;r.remaining['black']=10
        self.assertFalse(r.tick(1090))  # 80 seconds of overtime, one period left.

    def test_invalid_move_does_not_reset_clock(self):
        r=self.room();r.moves=2;r.board[0]=1
        with self.assertRaises(ValueError):self.act(r,'black',{'type':'move','index':0},1050)
        self.assertEqual(r.turn_started,1000);self.assertEqual(r.remaining['black'],300)

    def test_three_disconnects_no_reset_or_duplicate_counts(self):
        r=self.room();r.moves=2
        for index in range(3):
            start=1001+index*15
            r.clients.pop(self.black)
            with patch('server.time.time',return_value=start):r.connection_changed()
            r.tick(start+9);self.assertEqual(r.departures['black'],index)
            r.tick(start+10);self.assertEqual(r.departures['black'],index+1)
            r.tick(start+11);self.assertEqual(r.departures['black'],index+1)
            if index<2:
                r.clients[self.black]='black'
                with patch('server.time.time',return_value=start+12):r.connection_changed()
                self.assertEqual(r.turn_started,1000)
        self.assertEqual(r.result['reason'],'repeated_departure')

    def test_reconnect_before_cleanup_still_counts(self):
        r=self.room();r.moves=2;r.clients.pop(self.black)
        with patch('server.time.time',return_value=1001):r.connection_changed()
        r.clients[self.black]='black'
        with patch('server.time.time',return_value=1012):r.connection_changed()
        self.assertEqual(r.departures['black'],1)
        self.assertEqual(r.offline_used['black'],11)

    def test_sub_ten_second_outage_not_counted_but_budget_persists(self):
        r=self.room();r.moves=2;r.turn=-1;r.turn_started=1000
        r.offline_used['black']=85
        r.clients.pop(self.black)
        with patch('server.time.time',return_value=1001):r.connection_changed()
        self.assertFalse(r.tick(1005.9));self.assertTrue(r.tick(1006))
        self.assertEqual(r.departures['black'],0)
        self.assertEqual(r.result['reason'],'disconnect')

    def test_review_30_seconds_only_after_ready(self):
        r=self.room();r.status='scoring';r.adjudication={'status':'analyzing'};r.review_deadline=None
        self.assertFalse(r.tick(5000));self.assertEqual(r.status,'scoring')
        r.review_deadline=1030;r.approvals={'white'}
        self.assertFalse(r.tick(1029.9));self.assertTrue(r.tick(1030))
        self.assertEqual(r.result,{'reason':'review_timeout','winner':'white'})

    def test_snapshot_preserves_counters_and_legacy_policy(self):
        r=self.room();r.periods['black']=1;r.departures['white']=2;r.offline_used['white']=24
        restored=s.Room.from_snapshot(r.snapshot())
        self.assertEqual(restored.periods['black'],1);self.assertEqual(restored.departures['white'],2)
        self.assertEqual(restored.offline_used['white'],24)
        old=r.snapshot();old.pop('time_policy')
        self.assertEqual(s.Room.from_snapshot(old).time_policy,'fischer-v1')
