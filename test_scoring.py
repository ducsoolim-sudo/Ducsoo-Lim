import time
import unittest
from scoring import territory_score, automatic_dead, pass_alive
import server as s


class JapaneseScoring(unittest.TestCase):
    def test_territory_and_prisoners_not_live_stones(self):
        board = [1]*169
        board[0] = board[2] = 0
        score = territory_score(board, set(), {'black': 3, 'white': 2})
        self.assertEqual(score['black'], 5)
        self.assertEqual(score['white'], 8.5)

    def test_dead_stones_count_as_prisoners_and_vacated_territory(self):
        board = [1]*169
        board[0] = board[2] = 0; board[84] = -1
        score = territory_score(board, {84}, {'black': 0, 'white': 0})
        self.assertEqual(score['blackTerritory'], 3)
        self.assertEqual(score['blackPrisoners'], 1)
        self.assertEqual(score['black'], 4)

    def test_shared_dame_excludes_seki_eyes(self):
        board = [1]*169
        for i in range(7, 13):
            for j in range(13): board[j*13+i] = -1
        for j in range(13): board[j*13+6] = 0
        board[0] = board[12] = 0
        score = territory_score(board, set(), {'black': 0, 'white': 0})
        self.assertEqual((score['blackTerritory'], score['whiteTerritory']), (0, 0))

    def test_automatic_enclosed_single_eye_death(self):
        board = [1]*169
        board[0] = board[2] = 0  # Two unconditional black eyes.
        board[84] = -1; board[85] = 0
        dead, uncertain = automatic_dead(board)
        self.assertEqual(dead, {84})
        self.assertNotIn(84, uncertain)

    def test_two_eyes_live_never_removed(self):
        board = [1]*169
        board[0] = board[2] = 0
        self.assertEqual(automatic_dead(board), (set(), set()))

    def test_open_and_unsettled_groups_never_guessed_dead(self):
        board = [0]*169; board[84] = 1; board[86] = -1
        dead, uncertain = automatic_dead(board)
        self.assertFalse(dead); self.assertEqual(uncertain, {84, 86})

    def test_pass_marks_dead_before_confirmation_and_sgf_rules(self):
        room = s.Room('SCORE', solo=True); room.claim(None, 'A')
        room.board = [1]*169
        room.board[0] = room.board[2] = room.board[85] = 0
        room.board[84] = -1
        room.act('black', {'type': 'pass'}); room.act('black', {'type': 'pass'})
        self.assertEqual(room.dead, {84})
        room.act('black', {'type': 'approve'})
        self.assertEqual(room.result['black'], 5)
        self.assertIn('RU[Japanese]', room.sgf())

    def test_user_correction_clears_acceptance(self):
        room = s.Room('REVIEW'); room.claim(None, 'A'); room.claim(None, 'B')
        room.board[0] = 1
        room.act('black', {'type': 'pass'}); room.act('white', {'type': 'pass'})
        room.act('black', {'type': 'approve'})
        room.act('white', {'type': 'dead', 'index': 0})
        self.assertFalse(room.approvals)
        room.act('white', {'type': 'resume'})
        self.assertFalse(room.dead); self.assertFalse(room.score_uncertain)

    def test_old_snapshot_without_analysis_restores(self):
        room = s.Room('OLD'); snapshot = room.snapshot(); snapshot.pop('score_uncertain')
        self.assertFalse(s.Room.from_snapshot(snapshot).score_uncertain)

    def test_japanese_simple_ko_blocks_immediate_recapture(self):
        room=s.Room('KO',solo=True);room.claim(None,'A')
        for p in (1,13,27):room.board[p]=1
        for p in (14,2,16,28):room.board[p]=-1
        room.act('black',{'type':'move','index':15})
        self.assertEqual(room.board[14],0)
        with self.assertRaises(ValueError):room.act('black',{'type':'move','index':14})
        room.act('black',{'type':'pass'})
        room.act('black',{'type':'move','index':168})
        room.act('black',{'type':'move','index':14})
        self.assertEqual(room.board[15],0)
